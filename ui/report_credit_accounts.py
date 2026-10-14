"""Private, paged credit review. No mutation or TD-only account navigation."""

import threading
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk
import api_clients.billing_service as billing
from theme_manager import ModernTheme
from utils import format_curr
from utils.report_labels import RECORDED_CREDIT_BALANCE_HELP
from ui.report_workspace_state import captured_time_label


class CreditAccountsWindow(ctk.CTkToplevel):
    def __init__(self, parent, year, scope, barangay=None):
        super().__init__(parent)
        self.title("Recorded credit accounts — read only")
        self.geometry("1080x620")
        self.minsize(760, 460)
        self.year, self.barangay = year, barangay
        self.signature = scope["signature"]
        self.offset, self.token, self.rows = 0, 0, {}
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        ctk.CTkLabel(self, text="Recorded credit accounts", font=ModernTheme.H3).grid(
            row=0, column=0, sticky="w", padx=20, pady=(18, 4)
        )
        self.basis = ctk.CTkLabel(
            self,
            text=(
                f"Balances at December 31, {year}. "
                if year
                else "All billing years / all recorded payment dates. "
            )
            + RECORDED_CREDIT_BALANCE_HELP,
            wraplength=950,
            justify="left",
            anchor="w",
        )
        self.basis.grid(row=1, column=0, sticky="ew", padx=20)

        def resize_basis(event):
            target = max(
                320, int(self.winfo_width() / self.basis._get_widget_scaling()) - 40
            )
            if self.basis.cget("wraplength") != target:
                self.basis.configure(wraplength=target)

        self.bind("<Configure>", resize_basis)
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="ew", padx=20, pady=10)
        self.search = ctk.CTkEntry(
            controls,
            placeholder_text="Search TD or owner (all matching credit rows)",
            width=380,
        )
        self.search.pack(side="left")
        self.search.bind("<Return>", lambda e: self.load(reset=True))
        ctk.CTkButton(
            controls, text="Search", width=90, command=lambda: self.load(reset=True)
        ).pack(side="left", padx=8)
        self.open_btn = ctk.CTkButton(
            controls,
            text="Open ledger · read only",
            command=self.open_ledger,
            state="disabled",
        )
        self.open_btn.pack(side="right")
        host = tk.Frame(self, bg="#0f172a")
        host.grid(row=3, column=0, sticky="nsew", padx=20)
        columns = (
            "TD",
            "Account ID",
            "Owner",
            "Barangay",
            "Year",
            "Recorded charge",
            "Applied payment",
            "Credit",
        )
        self.tree = ttk.Treeview(
            host,
            columns=columns,
            show="headings",
            style="CreditReport.Treeview",
            selectmode="browse",
        )
        sy = ttk.Scrollbar(host, orient="vertical", command=self.tree.yview)
        sx = ttk.Scrollbar(host, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        sy.pack(side="right", fill="y")
        sx.pack(side="bottom", fill="x")
        self.tree.pack(fill="both", expand=True)
        for i, col in enumerate(columns):
            self.tree.heading(col, text=col)
            self.tree.column(
                col, width=170 if col == "Owner" else 130, anchor="e" if i >= 5 else "w"
            )
        self.tree.bind(
            "<<TreeviewSelect>>",
            lambda e: self.open_btn.configure(
                state="normal" if self.tree.selection() else "disabled"
            ),
        )
        self.tree.bind("<Double-1>", lambda e: self.open_ledger())
        self.tree.bind("<Return>", lambda e: self.open_ledger())
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=20, pady=12)
        self.previous = ctk.CTkButton(
            footer, text="Previous", width=90, command=lambda: self.move(-100)
        )
        self.previous.pack(side="left")
        self.next = ctk.CTkButton(
            footer, text="Next", width=90, command=lambda: self.move(100)
        )
        self.next.pack(side="right")
        self.status = ctk.CTkLabel(footer, text="Ready", wraplength=650)
        self.status.pack(fill="x", expand=True, padx=10)

        def resize_status(event):
            target = max(240, int(event.width / footer._get_widget_scaling()) - 200)
            if self.status.cget("wraplength") != target:
                self.status.configure(wraplength=target)

        footer.bind("<Configure>", resize_status)
        self.load()

    def close(self):
        self.token += 1
        self.destroy()

    def move(self, delta):
        self.offset = max(0, self.offset + delta)
        self.load()

    def load(self, reset=False):
        if reset:
            self.offset = 0
        self.token += 1
        token, offset, search = self.token, self.offset, self.search.get().strip()
        self.status.configure(text="Loading credit accounts…")
        for button in (self.previous, self.next, self.open_btn):
            button.configure(state="disabled")
        self.tree.delete(*self.tree.get_children())
        self.rows = {}

        def worker():
            try:
                report = billing.get_credit_accounts(
                    self.year,
                    barangay=self.barangay,
                    search=search,
                    offset=offset,
                    expected_signature=self.signature,
                )
                self.after(0, lambda: self.apply(token, report))
            except Exception as error:
                try:
                    self.after(0, lambda err=str(error): self.failure(token, err))
                except (tk.TclError, RuntimeError):
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def failure(self, token, error):
        if token == self.token:
            self.status.configure(
                text=f"Unable to load: {error} · Refresh the parent report if credits changed."
            )

    def apply(self, token, report):
        if token != self.token:
            return
        for row in report["items"]:
            item = self.tree.insert(
                "",
                "end",
                values=(
                    row["td_number"],
                    row["property_id"],
                    row["owner_name"],
                    row["barangay"],
                    row["tax_year"],
                    format_curr(row["recorded_charge"]),
                    format_curr(row["applied_payment"]),
                    format_curr(row["credit"]),
                ),
            )
            self.rows[item] = row
        count = report["count"]
        self.status.configure(
            text=f"{self.barangay or 'All barangays'} · {count:,} matching billings · Credit {format_curr(report['credit_total'])}\nLoaded search: {report.get('search') or 'All credit accounts'} · Captured {captured_time_label(report['captured_at_utc'])} · Read only"
        )
        self.previous.configure(state="normal" if self.offset > 0 else "disabled")
        self.next.configure(state="normal" if report["has_more"] else "disabled")

    def open_ledger(self):
        selection = self.tree.selection()
        if selection and selection[0] in self.rows:
            row = self.rows[selection[0]]
            ReadOnlyAccountLedger(self, row["property_id"], self.year, self.signature)


class ReadOnlyAccountLedger(ctk.CTkToplevel):
    def __init__(self, parent, property_id, year, signature):
        super().__init__(parent)
        self.title(f"Recorded ledger — account {property_id} — read only")
        self.geometry("900x510")
        self.minsize(700, 400)
        self.label = ctk.CTkLabel(
            self, text="Loading the exact account…", justify="left", wraplength=850
        )
        self.label.pack(fill="x", padx=20, pady=15)
        host = tk.Frame(self, bg="#0f172a")
        host.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        cols = ("Year", "Recorded charge", "Applied payment", "Receivable", "Credit")
        self.tree = ttk.Treeview(
            host, columns=cols, show="headings", style="CreditReport.Treeview"
        )
        scroll = ttk.Scrollbar(host, command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(fill="both", expand=True)
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=140, anchor="e")

        def apply(report):
            self.label.configure(
                text=f"{report['td_number']} · Account ID {report['property_id']} · {report['owner_name']}\n{report['basis']} · Captured {captured_time_label(report['captured_at_utc'])}\nFresh recorded balances; not a live SOA. No editing or refund actions."
            )
            for row in report["items"]:
                self.tree.insert(
                    "",
                    "end",
                    values=(
                        row["tax_year"],
                        *(
                            format_curr(row[key])
                            for key in (
                                "recorded_charge",
                                "applied_payment",
                                "receivable",
                                "credit",
                            )
                        ),
                    ),
                )

        def worker():
            try:
                report = billing.get_credit_account_ledger(
                    property_id, year, expected_signature=signature
                )
                self.after(0, lambda: apply(report))
            except Exception as error:
                try:
                    self.after(
                        0,
                        lambda err=str(error): self.label.configure(
                            text=f"Unable to load ledger: {err}"
                        ),
                    )
                except (tk.TclError, RuntimeError):
                    pass

        threading.Thread(target=worker, daemon=True).start()
