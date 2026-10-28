"""Selected-account payment history preview and read-only server exports."""

from decimal import Decimal
import os
from queue import Empty, Queue
import shutil
import threading
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from api_clients import payment_service


def selected_history_account(context, selected_context=None):
    """A selected row may disambiguate a broad ledger search; never use TD text."""
    chosen = selected_context if selected_context is not None else context
    if not chosen or chosen.get("multiple"):
        return None
    pid = chosen.get("property_id")
    return pid if type(pid) is int and pid > 0 else None


def history_save_options(format, property_id):
    if format not in ("pdf", "xlsx"):
        raise ValueError("Choose PDF or Excel.")
    title, pattern = ("PDF", "*.pdf") if format == "pdf" else ("Excel", "*.xlsx")
    return {
        "title": f"Save property payment history - {title}",
        "initialfile": f"Property_Payment_History_{property_id}.{format}",
        "defaultextension": f".{format}",
        "filetypes": [(f"{title} files", pattern)],
    }


class PaymentHistoryDialog(ctk.CTkToplevel):
    def __init__(self, parent, property_id):
        super().__init__(parent)
        self.property_id = property_id  # fixed even if the ledger search changes
        self.payload = None
        self.busy = False
        self.closed = False
        self.results = Queue()
        self.title("Property payment history - office reference")
        self.geometry("1120x760")
        self.minsize(850, 620)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)
        ctk.CTkLabel(
            self,
            text=f"Payment history - selected account #{property_id}",
            font=("Arial", 20, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 5))
        ctk.CTkLabel(
            self,
            text="All recorded years. Recorded cash only. No payment or TD records are changed.",
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=20)
        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.grid(row=2, column=0, sticky="ew", padx=20, pady=10)
        self.previous = ctk.BooleanVar(value=False)
        self.previous_check = ctk.CTkCheckBox(
            tools,
            text="Include verified previous TDs",
            variable=self.previous,
            command=self.reload,
        )
        self.previous_check.pack(side="left", padx=(0, 15))
        self.reload_btn = ctk.CTkButton(
            tools, text="Reload preview", width=120, command=self.reload
        )
        self.reload_btn.pack(side="left", padx=5)
        self.pdf_btn = ctk.CTkButton(
            tools,
            text="Export PDF",
            width=110,
            command=lambda: self.export("pdf"),
            state="disabled",
        )
        self.pdf_btn.pack(side="right", padx=5)
        self.excel_btn = ctk.CTkButton(
            tools,
            text="Export Excel",
            width=110,
            command=lambda: self.export("xlsx"),
            state="disabled",
        )
        self.excel_btn.pack(side="right", padx=5)
        self.summary = ctk.CTkLabel(
            self, text="Loading preview...", anchor="w", justify="left", wraplength=1020
        )
        self.summary.grid(row=3, column=0, sticky="ew", padx=20)
        self.sections = ctk.CTkOptionMenu(
            self,
            values=["Loading..."],
            command=self.show_section,
            state="disabled",
            width=650,
        )
        self.sections.grid(row=4, column=0, sticky="w", padx=20, pady=10)
        frame = ctk.CTkFrame(self)
        frame.grid(row=5, column=0, sticky="nsew", padx=20)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            frame,
            columns=(
                "id",
                "date",
                "or",
                "years",
                "penalty",
                "discount",
                "cash",
                "remarks",
            ),
            show="headings",
        )
        for name, label, width in zip(
            self.tree["columns"],
            (
                "Payment ID",
                "Receipt date",
                "OR number",
                "Tax years",
                "Penalty",
                "Discount",
                "Cash (PHP)",
                "Remarks",
            ),
            (90, 110, 130, 130, 95, 95, 120, 350),
        ):
            self.tree.heading(name, text=label)
            self.tree.column(
                name,
                width=width,
                minwidth=65,
                anchor="e" if name in ("penalty", "discount", "cash") else "w",
                stretch=name == "remarks",
            )
        self.tree.grid(row=0, column=0, sticky="nsew")
        y = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        y.grid(row=0, column=1, sticky="ns")
        x = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        x.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        self.notes = ctk.CTkTextbox(self, height=140, wrap="word")
        self.notes.grid(row=6, column=0, sticky="ew", padx=20, pady=10)
        self.status = ctk.CTkLabel(self, text="", anchor="w", wraplength=1020)
        self.status.grid(row=7, column=0, sticky="ew", padx=20, pady=(0, 12))
        self.section_map = {}
        self._poll_id = self.after(100, self.poll)
        self.reload()

    def close(self):
        self.closed = True
        self.after_cancel(self._poll_id)
        self.destroy()

    def set_busy(self, value):
        self.busy = value
        self.reload_btn.configure(state="disabled" if value else "normal")
        self.previous_check.configure(state="disabled" if value else "normal")
        export_state = (
            "normal" if self.payload is not None and not value else "disabled"
        )
        self.pdf_btn.configure(state=export_state)
        self.excel_btn.configure(state=export_state)

    def run(self, operation, work):
        self.set_busy(True)

        def worker():
            try:
                self.results.put((operation, work(), None))
            except Exception as exc:
                self.results.put((operation, None, str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        try:
            operation, result, error = self.results.get_nowait()
        except Empty:
            pass
        else:
            if error:
                self.payload = None
                self.status.configure(
                    text="Unable to complete. Reload the preview before exporting."
                )
                messagebox.showerror("Payment history", error, parent=self)
            elif operation == "load":
                try:
                    if (
                        not isinstance(result, dict)
                        or result.get("selected_property_id") != self.property_id
                        or result.get("include_previous") is not self.previous.get()
                        or not result.get("sections")
                        or (
                            not result["include_previous"]
                            and [s["property_id"] for s in result["sections"]]
                            != [self.property_id]
                        )
                    ):
                        raise ValueError("Invalid account scope")
                    self.payload = result
                    self.render()
                except (KeyError, TypeError, ValueError, StopIteration):
                    self.payload = None
                    self.status.configure(
                        text="The server returned an invalid preview. Reload or contact the operator. Export is disabled."
                    )
            else:
                self.status.configure(
                    text=f"Saved: {result}. No payment records were changed."
                )
            self.set_busy(False)
        self._poll_id = self.after(100, self.poll)

    def reload(self):
        if self.busy:
            return
        self.payload = None
        self.tree.delete(*self.tree.get_children())
        self.sections.configure(state="disabled")
        self.summary.configure(text="Loading selected-account history...")
        self.status.configure(text="")
        include = self.previous.get()
        self.run(
            "load",
            lambda: payment_service.get_property_payment_history(
                self.property_id, include_previous=include
            ),
        )

    def render(self):
        p = self.payload
        self.section_map = {
            f"TD {s['td_number']} - Account #{s['property_id']}"
            + (" (selected)" if s["selected"] else " (previous TD)")
            + (" - ARCHIVED" if s["archived"] else ""): s
            for s in p["sections"]
        }
        values = list(self.section_map)
        self.sections.configure(values=values, state="normal")
        selected = next(k for k, s in self.section_map.items() if s["selected"])
        self.sections.set(selected)
        self.show_section(selected)
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", "\n".join([p["previous_scope_note"], *p["notes"]]))
        self.notes.configure(state="disabled")
        self.status.configure(
            text=f"Preview generated (UTC): {p['generated_at_utc']}. Export rechecks this snapshot before saving."
        )

    def show_section(self, label):
        section = self.section_map.get(label)
        if not section or self.payload is None:
            return
        p = self.payload
        self.summary.configure(
            text=(
                f"{p['payment_count']} payment entries across {len(p['sections'])} account(s). Total cash: PHP {Decimal(p['recorded_cash_total']):,.2f}. "
                f"Dated coverage: {p['coverage_start'] or 'None'} to {p['coverage_end'] or 'None'}. Undated: {p['undated_count']}.\n"
                f"Shown: {section['current_owner']} (current stored owner) - {section['current_barangay'] or '-'} / {section['current_location'] or '-'}\n"
                f"Account subtotal: PHP {Decimal(section['recorded_cash_total']):,.2f} ({section['payment_count']} entries)."
            )
        )
        self.tree.delete(*self.tree.get_children())
        for r in section["payments"]:
            self.tree.insert(
                "",
                "end",
                values=(
                    r["payment_id"],
                    r["receipt_date"] or "Not recorded",
                    r["or_number"] or "Not recorded",
                    r["tax_years"] or "Not recorded",
                    *(
                        f"{Decimal(r[k]):,.2f}" if r[k] is not None else "Not recorded"
                        for k in ("penalty", "discount", "cash")
                    ),
                    r["remarks"] or "",
                ),
            )
        if not section["payments"]:
            self.tree.insert(
                "", "end", values=("", "", "No payments recorded", "", "", "", "", "")
            )

    def export(self, format):
        if self.busy or self.payload is None:
            return
        dest = filedialog.asksaveasfilename(
            parent=self, **history_save_options(format, self.property_id)
        )
        if not dest:
            return
        if os.path.splitext(dest)[1].lower() != f".{format}":
            messagebox.showwarning(
                "Payment history",
                f"Use a .{format} filename for this export.",
                parent=self,
            )
            return
        fingerprint, include = (
            self.payload["fingerprint"],
            self.payload["include_previous"],
        )

        def save():
            path = payment_service.download_property_payment_history(
                self.property_id, include, format, fingerprint
            )
            try:
                shutil.copyfile(path, dest)
            finally:
                os.remove(path)
            return dest

        self.run("export", save)
