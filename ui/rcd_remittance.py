"""Review report-only instruments and full handover; no payment/bank writes."""

from copy import deepcopy
from datetime import date, timedelta
from tkinter import messagebox, ttk

import customtkinter as ctk

from utils import format_curr
from utils.rcd_remittance import build_remittance_review
from ui.rcd_stock import RcdStockReview


class RcdRemittanceDialog(ctk.CTkToplevel):
    def __init__(self, parent, payload, initial=None):
        super().__init__(parent)
        self.title("Daily RCD - instruments, handover and stock review")
        self.geometry("900x720")
        self.minsize(780, 640)
        self.transient(parent)
        self.payload = payload
        self.result = None
        previous = initial or {}
        self.checks = deepcopy(previous.get("checks", []))
        self.receipt_map = {r["or_number"]: r for r in payload["receipts"]}
        ctk.CTkLabel(
            self,
            text="Review the report, not the payment records",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w", padx=18, pady=(14, 6))
        ctk.CTkLabel(
            self,
            text="OR date stays "
            + payload["report_date"]
            + ". No receiving acknowledgment or bank-deposit entry is created here.",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", padx=18)
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=14, pady=8)
        check_tab = self.tabs.add("Cash / checks")
        handover = self.tabs.add("Full handover")
        stock_tab = self.tabs.add("Receipt stock")
        self.stock = RcdStockReview(stock_tab, payload, previous.get("stock"))
        self.stock.pack(fill="both", expand=True)
        ctk.CTkLabel(
            check_tab,
            text="List every check. After confirmation, the remaining recorded receipt amounts are classified as cash. Mixed cash/check on one OR is supported.",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        form = ctk.CTkFrame(check_tab)
        form.pack(fill="x")
        self.or_number = ctk.CTkComboBox(
            form,
            values=list(self.receipt_map) or ["No recorded ORs"],
            state="readonly",
            command=self._selected_or,
        )
        self.bank = ctk.CTkEntry(form)
        self.check_number = ctk.CTkEntry(form)
        self.payee = ctk.CTkEntry(form)
        self.amount = ctk.CTkEntry(form)
        self.face_amount = ctk.CTkEntry(form)
        for row, (label, widget) in enumerate(
            (
                ("Recorded OR", self.or_number),
                ("Bank on the check", self.bank),
                ("Check number", self.check_number),
                ("Payee on the check", self.payee),
                ("Check amount applied to this OR", self.amount),
                ("Whole amount on the actual check", self.face_amount),
            )
        ):
            ctk.CTkLabel(form, text=label).grid(
                row=row, column=0, sticky="w", padx=10, pady=3
            )
            widget.grid(row=row, column=1, sticky="ew", padx=10, pady=3)
        form.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(form, text="Add check to draft", command=self._add_check).grid(
            row=6, column=1, sticky="w", padx=10, pady=8
        )
        frame = ctk.CTkFrame(check_tab)
        frame.pack(fill="both", expand=True, pady=8)
        self.tree = ttk.Treeview(
            frame,
            columns=("OR", "Bank", "Check", "Payee", "Applied", "Whole check"),
            show="headings",
            height=4,
        )
        for name in self.tree["columns"]:
            self.tree.heading(name, text=name)
            self.tree.column(name, width=130, minwidth=80)
        scroll = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        vertical = ttk.Scrollbar(frame, command=self.tree.yview)
        self.tree.configure(xscrollcommand=scroll.set, yscrollcommand=vertical.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        scroll.grid(row=1, column=0, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        ctk.CTkButton(
            check_tab,
            text="Remove selected check from draft",
            command=self._remove_check,
        ).pack(anchor="w")
        self.cash_confirmed = ctk.BooleanVar(
            value=previous.get("cash_check_confirmed") is True
        )
        ctk.CTkCheckBox(
            check_tab,
            text="I reviewed all checks; the remaining receipt amounts are cash.",
            variable=self.cash_confirmed,
        ).pack(anchor="w", pady=10)
        body = ctk.CTkScrollableFrame(handover)
        body.pack(fill="both", expand=True)
        ctk.CTkLabel(
            body,
            text="Normal workflow: remit all daily collections; bank deposit is normally the following morning. Confirm actual events, not an expected transfer.",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", padx=10, pady=8)
        self.opening_100 = self._entry(
            body,
            "Fund 100 opening accountability (blank if unknown)",
            previous.get("opening_100"),
        )
        self.opening_200 = self._entry(
            body,
            "Fund 200 opening accountability (blank if unknown)",
            previous.get("opening_200"),
        )
        ctk.CTkButton(
            body,
            text="Confirm no opening balance for either fund",
            command=self._zero_opening,
        ).pack(anchor="w", padx=10, pady=8)
        self.handed = ctk.BooleanVar(
            value=previous.get("full_handover_confirmed") is True
        )
        ctk.CTkCheckBox(
            body,
            text="All collections in this RCD were actually handed over in full.",
            variable=self.handed,
            command=self._toggle_handover,
        ).pack(anchor="w", padx=10, pady=10)
        self.recipient = self._entry(
            body,
            "Actual receiving / liquidating officer",
            previous.get("receiving_officer"),
        )
        self.handover_date = self._entry(
            body, "Actual handover date (YYYY-MM-DD)", previous.get("handover_date")
        )
        planned = (
            previous.get("planned_deposit_date")
            or (
                date.fromisoformat(payload["report_date"]) + timedelta(days=1)
            ).isoformat()
        )
        self.deposit_date = self._entry(
            body, "Planned bank-deposit date - NOT proof of deposit", planned
        )
        ctk.CTkLabel(
            body,
            text="Opening balances are never assumed. Receiver signatures and bank-deposit evidence remain separate. This review does not edit payments or mark the report COA-certified.",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", padx=10, pady=12)
        self.summary = ctk.CTkLabel(
            self,
            text="Review the actual checks and handover before accepting.",
            wraplength=720,
            justify="left",
        )
        self.summary.pack(anchor="w", padx=18, pady=4)
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(4, 14))
        ctk.CTkButton(actions, text="Accept report review", command=self._save).pack(
            side="right"
        )
        ctk.CTkButton(
            actions, text="Cancel", command=self.destroy, fg_color="gray"
        ).pack(side="right", padx=8)
        self._selected_or(self.or_number.get())
        self._toggle_handover()
        self._refresh_checks()
        self.tabs.set("Cash / checks")

    def _entry(self, parent, label, value):
        ctk.CTkLabel(parent, text=label).pack(anchor="w", padx=10, pady=(8, 0))
        entry = ctk.CTkEntry(parent)
        entry.pack(fill="x", padx=10, pady=4)
        if value is not None:
            entry.insert(0, str(value))
        return entry

    def _selected_or(self, number):
        self.amount.delete(0, "end")
        if number in self.receipt_map:
            self.amount.insert(0, self.receipt_map[number]["cash"])

    def _toggle_handover(self):
        state = "normal" if self.handed.get() else "disabled"
        self.recipient.configure(state=state)
        self.handover_date.configure(state=state)

    def _zero_opening(self):
        for entry in (self.opening_100, self.opening_200):
            entry.delete(0, "end")
            entry.insert(0, "0.00")

    def _add_check(self):
        item = {
            "or_number": self.or_number.get(),
            "bank": self.bank.get(),
            "check_number": self.check_number.get(),
            "payee": self.payee.get(),
            "amount": self.amount.get(),
            "face_amount": self.face_amount.get(),
        }
        try:
            build_remittance_review(
                self.payload,
                {"cash_check_confirmed": True, "checks": self.checks + [item]},
                allow_incomplete_checks=True,
            )
        except ValueError as error:
            messagebox.showerror("Check details", str(error), parent=self)
            return
        self.checks.append(item)
        self.cash_confirmed.set(False)
        self._refresh_checks()

    def _remove_check(self):
        chosen = {int(item) for item in self.tree.selection()}
        self.checks = [
            item for index, item in enumerate(self.checks) if index not in chosen
        ]
        self.cash_confirmed.set(False)
        self._refresh_checks()

    def _refresh_checks(self):
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.checks):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    item["or_number"],
                    item["bank"],
                    item["check_number"],
                    item["payee"],
                    format_curr(item["amount"]),
                    format_curr(item["face_amount"]),
                ),
            )

    def _save(self):
        values = {
            "cash_check_confirmed": self.cash_confirmed.get(),
            "checks": self.checks,
            "opening_100": self.opening_100.get(),
            "opening_200": self.opening_200.get(),
            "full_handover_confirmed": self.handed.get(),
            "receiving_officer": self.recipient.get() if self.handed.get() else "",
            "handover_date": self.handover_date.get() if self.handed.get() else None,
            "planned_deposit_date": self.deposit_date.get(),
            "stock": self.stock.values(),
        }
        try:
            reviewed = build_remittance_review(self.payload, values)
        except ValueError as error:
            messagebox.showerror("Review required", str(error), parent=self)
            return
        breakdown = "\n".join(
            f"Fund {fund}: cash {format_curr(data['cash'])}; checks {format_curr(data['checks'])}"
            for fund, data in reviewed["funds"].items()
        )
        if not messagebox.askyesno(
            "Confirm report-only details",
            "Use this reviewed cash/check breakdown?\n\n"
            + breakdown
            + "\n\nUnused forms: "
            + str(reviewed["stock"]["totals"]["opening"])
            + " opening + "
            + str(reviewed["stock"]["totals"]["received"])
            + " received - "
            + str(reviewed["stock"]["totals"]["paid"])
            + " paid - "
            + str(reviewed["stock"]["totals"]["cancelled"])
            + " cancelled/spoiled = "
            + str(reviewed["stock"]["totals"]["ending"])
            + " ending unused."
            + "\n\n"
            + (
                "You declared full actual handover to "
                + reviewed["details"]["receiving_officer"]
                + " on "
                + reviewed["details"]["handover_date"]
                + "."
                if self.handed.get()
                else "Actual handover remains unconfirmed; remittance/closing lines stay blank."
            )
            + "\n\nNo receiving acknowledgment, bank deposit or payment change will be recorded.",
            parent=self,
        ):
            return
        self.result = reviewed["details"]
        self.destroy()
