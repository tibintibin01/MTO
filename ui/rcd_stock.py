"""Office-log stock inputs for the daily RCD; no register or payment mutation."""

from copy import deepcopy
from datetime import date
from tkinter import messagebox, ttk

import customtkinter as ctk

from utils.rcd_booklets import receipt_serial
from utils.rcd_metadata import _report_text


class RcdStockReview(ctk.CTkScrollableFrame):
    def __init__(self, parent, payload, initial=None):
        super().__init__(parent)
        previous = initial or {}
        self.opening = deepcopy(previous.get("opening_ranges", []))
        self.received = list(previous.get("received_booklet_ids", []))
        self.cancelled = deepcopy(previous.get("cancelled", []))
        self.booklets = {
            f"{b['form_type']}  {b['first_or']} - {b['last_or']}  / issued {b['issued_on']}": b
            for b in payload.get("stock_booklets", [])
        }
        self.day = date.fromisoformat(payload["report_date"])
        ctk.CTkLabel(
            self,
            text="Use the official booklet/register, not a guessed first-to-last range. Include every unused booklet still held by this collecting officer on the OR date, even if idle. Exhausted/previously returned booklets are not opening unused stock.",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", padx=8, pady=8)
        self.reference = self._entry(
            "Stock register / previous RCD reference",
            previous.get("register_reference", ""),
        )
        ctk.CTkLabel(self, text="Registered booklet").pack(
            anchor="w", padx=8, pady=(8, 0)
        )
        self.booklet = ctk.CTkComboBox(
            self,
            values=list(self.booklets) or ["No registered booklets for this date"],
            state="readonly",
            width=600,
        )
        self.booklet.pack(fill="x", padx=8, pady=4)
        self.booklet.set(
            next(iter(self.booklets), "No registered booklets for this date")
        )
        self.first = self._entry("Opening unused first OR (from the log)")
        self.last = self._entry("Opening unused last OR (from the log)")
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=8, pady=6)
        ctk.CTkButton(
            actions, text="Add opening unused range", command=self._add_opening
        ).pack(side="left")
        ctk.CTkButton(
            actions,
            text="Add full booklet received on OR date",
            command=self._add_received,
        ).pack(side="left", padx=8)
        self.stock_tree = self._tree(("Section", "Booklet", "From", "To"))
        ctk.CTkButton(
            self, text="Remove selected stock draft line", command=self._remove_stock
        ).pack(anchor="w", padx=8, pady=6)
        ctk.CTkLabel(
            self,
            text="Cancelled / spoiled ORs with NO collection",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w", padx=8, pady=(12, 4))
        ctk.CTkLabel(
            self,
            text="These serials are included in Section C issued/used stock, with zero collection in the supporting list. Retain original/duplicate copies for submission with the RCD. This does not cancel a saved payment or authorize destruction/relief.",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", padx=8, pady=4)
        self.cancel_or = self._entry("Actual cancelled / spoiled OR number")
        self.status = ctk.CTkComboBox(
            self, values=["CANCELLED", "SPOILED"], state="readonly"
        )
        self.status.pack(anchor="w", padx=8, pady=4)
        self.reason = self._entry("Reason recorded in the office log")
        self.cancel_reference = self._entry(
            "Cancellation / spoilage register reference"
        )
        self.copies = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self,
            text="The original and duplicate copies are retained for the RCD.",
            variable=self.copies,
        ).pack(anchor="w", padx=8, pady=8)
        ctk.CTkButton(
            self,
            text="Add cancelled / spoiled OR to draft",
            command=self._add_cancelled,
        ).pack(anchor="w", padx=8, pady=4)
        self.cancel_tree = self._tree(("OR", "Status", "Reason", "Reference"))
        ctk.CTkButton(
            self,
            text="Remove selected cancellation draft line",
            command=self._remove_cancelled,
        ).pack(anchor="w", padx=8, pady=6)
        self.confirmed = ctk.BooleanVar(value=previous.get("confirmed") is True)
        ctk.CTkCheckBox(
            self,
            variable=self.confirmed,
            text="I checked ALL unused stock and cancelled/spoiled ORs against the office log.",
        ).pack(anchor="w", padx=8, pady=12)
        self.reference.bind("<KeyRelease>", lambda _event: self.confirmed.set(False))
        self._refresh()

    def _entry(self, label, value=""):
        ctk.CTkLabel(self, text=label).pack(anchor="w", padx=8, pady=(8, 0))
        entry = ctk.CTkEntry(self)
        entry.pack(fill="x", padx=8, pady=4)
        entry.insert(0, value)
        return entry

    def _tree(self, columns):
        frame = ctk.CTkFrame(self)
        frame.pack(fill="x", padx=8, pady=6)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=3)
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=160, minwidth=100)
        scroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        vertical = ttk.Scrollbar(frame, command=tree.yview)
        tree.configure(xscrollcommand=scroll.set, yscrollcommand=vertical.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        scroll.grid(row=1, column=0, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        return tree

    def _selected(self):
        book = self.booklets.get(self.booklet.get())
        if book is None:
            raise ValueError("Register the actual booklet before reviewing its stock.")
        return book

    def _add_opening(self):
        try:
            book = self._selected()
            a, b = receipt_serial(self.first.get()), receipt_serial(self.last.get())
            start, end = receipt_serial(book["first_or"]), receipt_serial(
                book["last_or"]
            )
            if date.fromisoformat(book["issued_on"]) >= self.day or not (
                a[0] == b[0] == start[0] and start[1] <= a[1] <= b[1] <= end[1]
            ):
                raise ValueError(
                    "Use unused bounds within a booklet received before the OR date."
                )
            self.opening.append(
                {
                    "booklet_id": book["id"],
                    "from_or": self.first.get(),
                    "to_or": self.last.get(),
                }
            )
            self.confirmed.set(False)
            self._refresh()
        except ValueError as error:
            messagebox.showerror(
                "Opening stock", str(error), parent=self.winfo_toplevel()
            )

    def _add_received(self):
        try:
            book = self._selected()
            if (
                date.fromisoformat(book["issued_on"]) != self.day
                or book["id"] in self.received
            ):
                raise ValueError(
                    "Use a full booklet actually received on the OR date, listed once."
                )
            self.received.append(book["id"])
            self.confirmed.set(False)
            self._refresh()
        except ValueError as error:
            messagebox.showerror(
                "Received stock", str(error), parent=self.winfo_toplevel()
            )

    def _add_cancelled(self):
        try:
            receipt_serial(self.cancel_or.get())
            reason = _report_text(self.reason.get(), "Reason", 240)
            reference = _report_text(
                self.cancel_reference.get(), "Register reference", 160
            )
            if not reason or not reference or not self.copies.get():
                raise ValueError(
                    "Enter the reason and log reference, and confirm both copies are retained."
                )
            self.cancelled.append(
                {
                    "or_number": self.cancel_or.get(),
                    "status": self.status.get(),
                    "reason": reason,
                    "reference": reference,
                    "copies_retained": True,
                }
            )
            self.confirmed.set(False)
            self.copies.set(False)
            self._refresh()
        except ValueError as error:
            messagebox.showerror(
                "Cancelled / spoiled OR", str(error), parent=self.winfo_toplevel()
            )

    def _remove_stock(self):
        chosen = set(self.stock_tree.selection())
        self.opening = [r for i, r in enumerate(self.opening) if f"o{i}" not in chosen]
        self.received = [
            r for i, r in enumerate(self.received) if f"r{i}" not in chosen
        ]
        self.confirmed.set(False)
        self._refresh()

    def _remove_cancelled(self):
        chosen = set(self.cancel_tree.selection())
        self.cancelled = [
            r for i, r in enumerate(self.cancelled) if str(i) not in chosen
        ]
        self.confirmed.set(False)
        self._refresh()

    def _refresh(self):
        self.stock_tree.delete(*self.stock_tree.get_children())
        self.cancel_tree.delete(*self.cancel_tree.get_children())
        by_id = {b["id"]: b for b in self.booklets.values()}
        for i, row in enumerate(self.opening):
            book = by_id.get(row["booklet_id"], {})
            self.stock_tree.insert(
                "",
                "end",
                iid=f"o{i}",
                values=(
                    "Opening",
                    book.get("first_or", "Unavailable"),
                    row["from_or"],
                    row["to_or"],
                ),
            )
        for i, identity in enumerate(self.received):
            book = by_id.get(identity, {})
            self.stock_tree.insert(
                "",
                "end",
                iid=f"r{i}",
                values=(
                    "Received",
                    book.get("first_or", "Unavailable"),
                    book.get("first_or", ""),
                    book.get("last_or", ""),
                ),
            )
        for i, row in enumerate(self.cancelled):
            self.cancel_tree.insert(
                "",
                "end",
                iid=str(i),
                values=tuple(
                    row[k] for k in ("or_number", "status", "reason", "reference")
                ),
            )

    def values(self):
        return {
            "confirmed": self.confirmed.get(),
            "register_reference": self.reference.get(),
            "opening_ranges": deepcopy(self.opening),
            "received_booklet_ids": list(self.received),
            "cancelled": deepcopy(self.cancelled),
        }
