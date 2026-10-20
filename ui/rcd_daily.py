"""Daily officer-scoped RPT reporting. No backend or database imports."""

from pathlib import Path
from copy import deepcopy
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from api_clients import reports_service as reports_api
from utils import format_curr
from utils.rcd_booklets import booklet_range
from utils.rcd_metadata import philippine_report_date, resolve_rcd_metadata
from ui.rcd_remittance import RcdRemittanceDialog


class DailyRcdWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Daily RPT RCD - Funds 100 and 200")
        self.geometry("1040x700")
        self.minsize(780, 600)
        self.transient(parent.winfo_toplevel())
        self._busy = False
        self._closed = False
        self.preview = None
        self.remittance_review = None
        self.registry = {"officers": [], "booklets": []}
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._buttons = []
        self._build_ui()
        self._initial_load = self.after(50, self._load_register)

    def _close(self):
        self._closed = True
        self.destroy()

    def _button(self, parent, text, command):
        button = ctk.CTkButton(parent, text=text, command=command, height=34)
        self._buttons.append(button)
        return button

    def _build_ui(self):
        ctk.CTkLabel(
            self,
            text="Daily RPT Report of Collections and Deposits",
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(
            self,
            text="Select the OR date and booklet owner. Encoded payment amounts populate the reports; no re-entry of collection totals.",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 12))
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        daily = self.tabs.add("Daily RCD")
        register = self.tabs.add("Booklet Register")
        filters = ctk.CTkFrame(daily)
        filters.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(filters, text="OR date (YYYY-MM-DD)").grid(
            row=0, column=0, padx=10, pady=(8, 0), sticky="w"
        )
        ctk.CTkLabel(filters, text="Accountable / collecting officer").grid(
            row=0, column=1, padx=10, pady=(8, 0), sticky="w"
        )
        ctk.CTkLabel(filters, text="Report number").grid(
            row=0, column=2, padx=10, pady=(8, 0), sticky="w"
        )
        self.day = ctk.CTkEntry(filters, width=155)
        self.day.insert(0, philippine_report_date().isoformat())
        self.day.grid(row=1, column=0, padx=10, pady=(4, 12), sticky="ew")
        self.day.bind("<KeyRelease>", lambda _event: self._invalidate())
        self.collector = ctk.CTkComboBox(
            filters,
            values=["Register an officer first"],
            state="readonly",
            command=lambda _value: self._invalidate(),
        )
        self.collector.grid(row=1, column=1, padx=10, pady=(4, 12), sticky="ew")
        self.number = ctk.CTkEntry(
            filters, placeholder_text="Office report number", width=180
        )
        self.number.grid(row=1, column=2, padx=10, pady=(4, 12), sticky="ew")
        filters.grid_columnconfigure(1, weight=1)
        actions = ctk.CTkFrame(daily, fg_color="transparent")
        actions.pack(fill="x", pady=(0, 8))
        self._button(actions, "Load daily preview", self._load_preview).pack(
            side="left", padx=(0, 8)
        )
        self.export_button = self._button(
            actions, "Export 100 / 200 Excel", self._export
        )
        self.export_button.pack(side="left")
        self.export_button.configure(state="disabled")
        self.remittance_button = self._button(
            actions, "Review instruments / stock", self._edit_remittance
        )
        self.remittance_button.pack(side="left", padx=8)
        self.remittance_button.configure(state="disabled")
        self.totals = ctk.CTkLabel(
            daily,
            text="100: —     200: —     Combined recorded collections: —",
            font=("Segoe UI", 15, "bold"),
            wraplength=700,
            justify="left",
            height=46,
        )
        self.totals.pack(anchor="w", pady=(4, 6))
        self.receipts = self._table(
            daily,
            ("OR", "Payment rows", "100 portion", "200 portion", "Recorded amount"),
        )
        self.review = ctk.CTkTextbox(daily, height=110, wrap="word")
        self.review.pack(fill="x", pady=(8, 0))
        self._review_text(
            "Load a date/officer preview. Remittance acceptance, cash/check split and complete physical form-stock accountability remain subject to office verification."
        )

        ctk.CTkLabel(
            register,
            text="Register each 50-receipt AF 56 booklet from the official issuance record. Existing assignments cannot be overwritten or deleted here.",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))
        roster = ctk.CTkFrame(register, fg_color="transparent")
        roster.pack(fill="x", pady=(0, 10))
        self._button(roster, "Add collecting officer", self._add_officer).pack(
            side="left", padx=(0, 8)
        )
        self._button(roster, "Refresh register", self._load_register).pack(side="left")
        form = ctk.CTkFrame(register)
        form.pack(fill="x", pady=(0, 8))
        self.book_collector = ctk.CTkComboBox(
            form, values=["Register an officer first"], state="readonly", width=300
        )
        self.book_first = ctk.CTkEntry(
            form, placeholder_text="First OR (including prefix)"
        )
        self.book_last = ctk.CTkEntry(form, placeholder_text="Last OR (50th receipt)")
        self.book_date = ctk.CTkEntry(
            form, placeholder_text="YYYY-MM-DD from issuance log"
        )
        for row, (label, widget) in enumerate(
            (
                ("Assigned collecting officer", self.book_collector),
                ("Actual first OR", self.book_first),
                ("Actual last OR", self.book_last),
                ("Date issued (YYYY-MM-DD)", self.book_date),
            )
        ):
            ctk.CTkLabel(form, text=label).grid(
                row=row, column=0, sticky="w", padx=12, pady=6
            )
            widget.grid(row=row, column=1, sticky="ew", padx=12, pady=6)
        form.grid_columnconfigure(1, weight=1)
        self._button(form, "Register booklet", self._add_booklet).grid(
            row=4, column=1, sticky="w", padx=12, pady=12
        )
        self.books = self._table(
            register, ("ID", "Collecting officer", "First OR", "Last OR", "Issued on")
        )
        self.status = ctk.CTkLabel(self, text="Loading register…", anchor="w")
        self.status.pack(fill="x", padx=20, pady=(0, 12))

    def _table(self, parent, columns):
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=7)
        for name in columns:
            tree.heading(name, text=name)
            tree.column(name, width=150, minwidth=95, anchor="w")
        vertical = ttk.Scrollbar(frame, command=tree.yview)
        horizontal = ttk.Scrollbar(frame, command=tree.xview, orient="horizontal")
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        return tree

    def _request(self, operation, on_success):
        if self._busy:
            return
        self._busy = True
        for button in self._buttons:
            button.configure(state="disabled")
        self.status.configure(text="Working…")

        def finish(result, error):
            if self._closed:
                return
            self._busy = False
            for button in self._buttons:
                button.configure(state="normal")
            try:
                if error:
                    self.status.configure(
                        text="Operation did not complete. No automatic repair was performed."
                    )
                    messagebox.showerror("Daily RCD", error, parent=self)
                else:
                    on_success(result)
            except Exception as failure:
                self.status.configure(text="Review the response before continuing.")
                messagebox.showerror("Daily RCD", str(failure), parent=self)
            self._update_export()

        def worker():
            result, error = None, None
            try:
                result = operation()
            except Exception as failure:
                error = str(failure)
            try:
                self.after(0, lambda: finish(result, error))
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _officer_id(self, selector):
        value = selector.get()
        try:
            result = int(value.split(":", 1)[0])
        except ValueError as error:
            raise ValueError("Select a registered collecting officer.") from error
        if result not in {officer["id"] for officer in self.registry["officers"]}:
            raise ValueError("Select a registered collecting officer.")
        return result

    def _scope(self):
        return (
            self._officer_id(self.collector),
            resolve_rcd_metadata(report_date=self.day.get()).report_date.isoformat(),
        )

    def _review_text(self, text):
        self.review.configure(state="normal")
        self.review.delete("1.0", "end")
        self.review.insert("1.0", text)
        self.review.configure(state="disabled")

    def _invalidate(self):
        self.preview = None
        self.remittance_review = None
        self.totals.configure(
            text="100: —     200: —     Combined recorded collections: —"
        )
        self.receipts.delete(*self.receipts.get_children())
        self._review_text(
            "Selection or register changed. Load the daily preview before exporting."
        )
        self._update_export()

    def _update_export(self):
        valid = False
        if self.preview and not self._busy:
            try:
                valid = (
                    self._scope()
                    == (self.preview["collector"]["id"], self.preview["report_date"])
                    and not self.preview["issues"]
                )
            except ValueError:
                pass
        self.export_button.configure(state="normal" if valid else "disabled")
        self.remittance_button.configure(state="normal" if valid else "disabled")

    def _edit_remittance(self):
        if not self.preview or self.preview["issues"]:
            return False
        dialog = RcdRemittanceDialog(self, self.preview, self.remittance_review)
        dialog.wait_visibility()
        dialog.grab_set()
        self.wait_window(dialog)
        if dialog.result is None:
            return False
        self.remittance_review = dialog.result
        self.status.configure(
            text="Instrument, handover and stock review accepted for this preview. Bank deposit and receiver acceptance are not recorded."
        )
        return True

    def _load_register(self):
        def loaded(result):
            if (
                not isinstance(result, dict)
                or "officers" not in result
                or "booklets" not in result
            ):
                raise ValueError("A valid register response was not received.")
            self.registry = result
            labels = [
                f'{item["id"]}: {item["name"]}' for item in result["officers"]
            ] or ["Register an officer first"]
            for selector in (self.collector, self.book_collector):
                old = selector.get()
                selector.configure(values=labels)
                selector.set(old if old in labels else labels[0])
            names = {item["id"]: item["name"] for item in result["officers"]}
            self.books.delete(*self.books.get_children())
            for item in result["booklets"]:
                self.books.insert(
                    "",
                    "end",
                    values=(
                        item["id"],
                        names.get(item["collector_id"], "Unknown"),
                        item["first_or"],
                        item["last_or"],
                        item["issued_on"],
                    ),
                )
            self._invalidate()
            self.status.configure(
                text=f'{len(result["officers"])} collecting officer(s); {len(result["booklets"])} booklet(s) registered.'
            )

        self._request(reports_api.get_rcd_register, loaded)

    def _add_officer(self):
        name = ctk.CTkInputDialog(
            text="Collecting officer's full name from the issuance record:",
            title="Register collecting officer",
        ).get_input()
        if name:
            self._request(
                lambda: reports_api.register_rcd_officer(name),
                lambda _result: self._load_register(),
            )

    def _add_booklet(self):
        try:
            collector_id = self._officer_id(self.book_collector)
            first, last = self.book_first.get().strip(), self.book_last.get().strip()
            booklet_range(first, last)
            issued = resolve_rcd_metadata(
                report_date=self.book_date.get()
            ).report_date.isoformat()
        except ValueError as error:
            messagebox.showerror("Check booklet details", str(error), parent=self)
            return
        if not messagebox.askyesno(
            "Confirm issuance record",
            f"Register AF 56 {first} to {last}\nAssigned to {self.book_collector.get()}\nIssued on {issued}\n\nConfirm against the issuance log. This assignment cannot be overwritten here.",
            parent=self,
        ):
            return
        self._request(
            lambda: reports_api.register_rcd_booklet(collector_id, first, last, issued),
            lambda _result: self._load_register(),
        )

    def _load_preview(self):
        try:
            scope = self._scope()
        except ValueError as error:
            messagebox.showerror("Check report selection", str(error), parent=self)
            return
        self._invalidate()

        def loaded(payload):
            try:
                if self._scope() != scope:
                    self._invalidate()
                    return
            except ValueError:
                self._invalidate()
                return
            self.preview = payload
            for item in payload["receipts"]:
                self.receipts.insert(
                    "",
                    "end",
                    values=(
                        item["or_number"],
                        len(item["payment_ids"]),
                        format_curr(item["basic_cash"]),
                        format_curr(item["sef_cash"]),
                        format_curr(item["cash"]),
                    ),
                )
            totals = payload["totals"]
            prefix = "INCOMPLETE - " if payload["issues"] else ""
            self.totals.configure(
                text=f'{prefix}100: {format_curr(totals["basic_cash"])}     200: {format_curr(totals["sef_cash"])}     Combined: {format_curr(totals["cash"])}'
            )
            notes = [
                f'{payload["receipt_count"]} OR(s), {payload["payment_row_count"]} payment entry/entries. {payload["other_officer_payment_rows"]} correctly assigned entry/entries belong to other officers and are excluded.'
            ]
            notes += [
                f'{item["code"]} (payment ID {item["payment_id"]}): {item["message"]}'
                for item in payload["issues"][:30]
            ]
            if len(payload["issues"]) > 30:
                notes.append(
                    f'{len(payload["issues"]) - 30} additional findings; resolve the complete daily source review.'
                )
            notes.extend(payload["limitations"])
            self._review_text("\n".join(notes))
            self.status.configure(
                text=(
                    "Collections ready for review/export."
                    if not payload["issues"]
                    else "Export blocked: review the receipt/booklet findings. No data was repaired."
                )
            )

        self._request(lambda: reports_api.get_daily_rcd(*scope), loaded)

    def _export(self):
        try:
            scope = self._scope()
            if (
                not self.preview
                or scope
                != (self.preview["collector"]["id"], self.preview["report_date"])
                or self.preview["issues"]
            ):
                raise ValueError("Load a current, unblocked preview before exporting.")
            metadata = resolve_rcd_metadata(
                self.number.get(),
                self.preview["collector"]["name"],
                scope[1],
                required=True,
            )
        except ValueError as error:
            messagebox.showerror("Check daily RCD", str(error), parent=self)
            return
        if self.remittance_review is None and not self._edit_remittance():
            return
        try:
            scope_unchanged = self.preview is not None and self._scope() == scope
        except ValueError:
            scope_unchanged = False
        if not scope_unchanged:
            messagebox.showerror(
                "Reload daily RCD",
                "The report selection changed. Load a fresh preview.",
                parent=self,
            )
            return
        review_details = deepcopy(self.remittance_review)
        destination = filedialog.asksaveasfilename(
            parent=self,
            title="Save daily RPT RCD 100 / 200",
            initialfile=f"RPT_RCD_100_200_{scope[1]}.xlsx",
            defaultextension=".xlsx",
            filetypes=[("Excel workbook (*.xlsx)", "*.xlsx")],
        )
        if not destination:
            return
        if Path(destination).suffix.lower() != ".xlsx":
            messagebox.showerror(
                "Check file format",
                "Choose an .xlsx filename. This export does not convert to PDF.",
                parent=self,
            )
            return
        signature = self.preview["source_signature"]

        def operation():
            source = reports_api.download_daily_rcd(
                scope[0],
                scope[1],
                metadata.report_number,
                signature,
                review=review_details,
            )
            shutil.copy2(source, destination)
            return destination

        def saved(path):
            self.status.configure(text=f"Daily collections draft saved: {path}")
            messagebox.showinfo(
                "RCD saved",
                "The 100/200 forms and reviewed instrument/stock details were exported. Retain cancelled OR copies and obtain office verification and receiver acknowledgment. No bank deposit was created.",
                parent=self,
            )

        self._request(operation, saved)
