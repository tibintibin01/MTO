"""Tax Bill account search. Discovery is not a compliance/payment classification."""

import os
from queue import Empty, Queue
import threading
from tkinter import messagebox, ttk

import customtkinter as ctk

from api_clients import billing_service, property_service


def tax_bill_year(value):
    text = str(value).strip()
    if not text.isascii() or not text.isdigit() or len(text) != 4:
        raise ValueError("Enter a four-digit Tax Bill year from 1900 to 2200.")
    year = int(text)
    if not 1900 <= year <= 2200:
        raise ValueError("Enter a Tax Bill year from 1900 to 2200.")
    return year


def validate_candidates(page, cursor=None, existing_ids=()):
    """Fail closed on ambiguous/malformed pages, not on duplicate TD numbers."""
    if not isinstance(page, dict) or type(page.get("has_more")) is not bool:
        raise ValueError("Invalid property search response. Search again.")
    rows = page.get("items")
    if not isinstance(rows, list) or len(rows) > 50:
        raise ValueError("Invalid property search response. Search again.")
    seen = set(existing_ids)
    previous = cursor
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid property search response. Search again.")
        pid = row.get("id")
        if (
            type(pid) is not int
            or pid <= 0
            or pid in seen
            or (previous is not None and pid >= previous)
            or any(
                not isinstance(row.get(key), str)
                for key in (
                    "td_number",
                    "owner_name",
                    "pin",
                    "lot_number",
                    "block_number",
                    "location",
                    "barangay",
                    "effectivity",
                )
            )
        ):
            raise ValueError("Invalid property search response. Search again.")
        seen.add(pid)
        previous = pid
    expected_cursor = rows[-1]["id"] if page["has_more"] and rows else None
    if (
        page.get("next_cursor") != expected_cursor
        or (expected_cursor is not None and type(page.get("next_cursor")) is not int)
        or (page["has_more"] and not rows)
    ):
        raise ValueError("Invalid property search cursor. Search again.")
    return rows


class TaxBillDialog(ctk.CTkToplevel):
    def __init__(self, parent, initial_year, initial_search="", preferred_id=None):
        super().__init__(parent)
        self.title("Generate Tax Bill - select a property account")
        self.geometry("1160x640")
        self.minsize(900, 540)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.closed = self.busy = False
        self.results = Queue()
        self.request_id = 0
        self.items = {}
        self.next_cursor = None
        self.loaded_term = ""
        self.preferred_id = preferred_id
        self.search_var = ctk.StringVar(value=initial_search)
        self.year_var = ctk.StringVar(value=str(initial_year))
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        ctk.CTkLabel(self, text="Generate Tax Bill", font=("Arial", 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(18, 5)
        )
        ctk.CTkLabel(
            self,
            anchor="w",
            justify="left",
            wraplength=820,
            text=(
                "Search includes new and future-effective declarations, even with no payments. "
                "Select the correct account; identical TDs are not interchangeable.\n"
                "Tax Bill year is separate from the Compliant list's AS OF YEAR. "
                "Generating a bill does not post a payment or mark the account compliant."
            ),
        ).grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))
        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.grid(row=2, column=0, sticky="ew", padx=20, pady=8)
        tools.grid_columnconfigure(0, weight=1)
        self.search_entry = ctk.CTkEntry(
            tools,
            textvariable=self.search_var,
            width=390,
            placeholder_text="TD / PIN / owner / location",
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search_entry.bind("<Return>", lambda _event: self.search())
        self.search_btn = ctk.CTkButton(
            tools, text="Search", width=100, command=self.search
        )
        self.search_btn.grid(row=0, column=1, padx=5)
        ctk.CTkLabel(tools, text="TAX BILL YEAR").grid(row=0, column=2, padx=(20, 8))
        self.year_entry = ctk.CTkEntry(tools, textvariable=self.year_var, width=90)
        self.year_entry.grid(row=0, column=3)

        frame = ctk.CTkFrame(self)
        frame.grid(row=3, column=0, sticky="nsew", padx=20, pady=8)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        columns = (
            ("id", "Account #", 85),
            ("td_number", "TD number", 150),
            ("owner_name", "Owner", 230),
            ("pin", "PIN", 110),
            ("lot", "Lot / Block", 130),
            ("place", "Barangay / Location", 220),
            ("effectivity", "Effectivity", 110),
        )
        self.tree = ttk.Treeview(
            frame, columns=[c[0] for c in columns], show="headings", selectmode="browse"
        )
        for key, label, width in columns:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=70)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self.selection_changed)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.selected_label = ctk.CTkLabel(
            self,
            text="No account selected.",
            anchor="w",
            justify="left",
            wraplength=820,
        )
        self.selected_label.grid(row=4, column=0, sticky="ew", padx=20, pady=6)
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew", padx=20, pady=8)
        self.more_btn = ctk.CTkButton(
            actions,
            text="Load more matches",
            command=lambda: self.search(more=True),
            state="disabled",
        )
        self.more_btn.pack(side="left")
        self.generate_btn = ctk.CTkButton(
            actions, text="Generate PDF", command=self.generate, state="disabled"
        )
        self.generate_btn.pack(side="right")
        self.status = ctk.CTkLabel(
            self,
            text="Enter a TD, PIN, owner or location, then Search.",
            anchor="w",
            justify="left",
            wraplength=820,
        )
        self.status.grid(row=6, column=0, sticky="ew", padx=20, pady=(5, 16))
        self.search_var.trace_add("write", self.inputs_changed)
        self.year_var.trace_add("write", self.inputs_changed)
        self._poll_id = self.after(100, self.poll)
        self.search_entry.focus_set()
        if initial_search:
            self.search()

    def selected_account(self):
        if self.search_var.get().strip() != self.loaded_term:
            return None
        selection = self.tree.selection()
        return self.items.get(selection[0]) if len(selection) == 1 else None

    def inputs_changed(self, *_args):
        if self.closed:
            return
        self.selection_changed()

    def selection_changed(self, _event=None):
        row = self.selected_account()
        self.selected_label.configure(
            text=(
                (
                    f"Selected account #{row['id']} | TD {row['td_number']} | {row['owner_name']}\n"
                    f"Effectivity: {row['effectivity'] or 'Not recorded'}. "
                    "The server rechecks the requested tax year before generating."
                )
                if row
                else "No account selected. Search and explicitly select the correct property."
            )
        )
        self.update_controls()

    def update_controls(self):
        normal = "disabled" if self.busy else "normal"
        for widget in (self.search_btn, self.search_entry, self.year_entry):
            widget.configure(state=normal)
        same_search = self.search_var.get().strip() == self.loaded_term
        self.more_btn.configure(
            state=(
                "normal"
                if not self.busy and same_search and self.next_cursor
                else "disabled"
            )
        )
        try:
            tax_bill_year(self.year_var.get())
            valid_year = True
        except ValueError:
            valid_year = False
        self.generate_btn.configure(
            state=(
                "normal"
                if not self.busy and valid_year and self.selected_account()
                else "disabled"
            )
        )

    def run(self, operation, work, context):
        self.busy = True
        self.request_id += 1
        token = self.request_id
        self.update_controls()

        def worker():
            try:
                self.results.put((token, operation, work(), None, context))
            except Exception as exc:
                self.results.put((token, operation, None, str(exc), context))

        threading.Thread(target=worker, daemon=True).start()

    def search(self, more=False):
        if self.closed or self.busy:
            return
        term = self.search_var.get().strip()
        if not term or len(term) > 100:
            self.status.configure(
                text="Enter 1 to 100 characters of a TD, PIN, owner or location."
            )
            return
        cursor = self.next_cursor if more and term == self.loaded_term else None
        if more and cursor is None:
            return
        self.tree.selection_remove(*self.tree.selection())
        if cursor is None:
            self.items = {}
            self.tree.delete(*self.tree.get_children())
        self.loaded_term = term
        self.next_cursor = None
        self.selection_changed()
        self.status.configure(
            text="Searching all non-deleted declarations, including future effectivity..."
        )
        self.run(
            "search",
            lambda: property_service.search_tax_bill_properties(term, cursor=cursor),
            (term, cursor),
        )

    def render_page(self, result, context):
        term, cursor = context
        rows = validate_candidates(result, cursor, (int(i) for i in self.items))
        if term != self.search_var.get().strip():
            return
        for row in rows:
            key = str(row["id"])
            self.items[key] = row
            self.tree.insert(
                "",
                "end",
                iid=key,
                values=(
                    row["id"],
                    row["td_number"],
                    row["owner_name"],
                    row["pin"],
                    " / ".join(filter(None, (row["lot_number"], row["block_number"]))),
                    " / ".join(filter(None, (row["barangay"], row["location"]))),
                    row["effectivity"] or "Not recorded",
                ),
            )
        self.next_cursor = result["next_cursor"]
        if self.preferred_id is not None and str(self.preferred_id) in self.items:
            self.tree.selection_set(str(self.preferred_id))
            self.tree.see(str(self.preferred_id))
        self.preferred_id = None
        self.status.configure(
            text=(
                (
                    f"{len(self.items)} match(es) loaded. Select the correct account and Tax Bill year. "
                    + (
                        "More matches are available."
                        if self.next_cursor
                        else "No further matches."
                    )
                )
                if self.items
                else "No matches. Check the TD/PIN or try part of the owner's name. No financial records were changed."
            )
        )
        self.selection_changed()

    def generate(self):
        if self.closed or self.busy:
            return
        row = self.selected_account()
        try:
            year = tax_bill_year(self.year_var.get())
            if row is None:
                raise ValueError(
                    "Search and select the correct property account first."
                )
        except ValueError as exc:
            messagebox.showwarning("Tax Bill", str(exc), parent=self)
            return
        if not messagebox.askyesno(
            "Confirm Tax Bill",
            (
                f"Generate Tax Bill {year} for account #{row['id']}?\n"
                f"TD: {row['td_number']}\nOwner: {row['owner_name']}\n"
                f"Location: {row['barangay']} / {row['location']}\n"
                f"Effectivity: {row['effectivity'] or 'Not recorded'}\n\n"
                "This generates a document only. It does not record a payment."
            ),
            parent=self,
        ):
            return
        if self.closed or self.busy:
            return
        pid = row["id"]
        self.status.configure(text=f"Generating Tax Bill {year} for account #{pid}...")
        self.run(
            "pdf", lambda: billing_service.download_tax_bill_pdf(pid, year), (pid, year)
        )

    def poll(self):
        if self.closed:
            return
        try:
            token, operation, result, error, context = self.results.get_nowait()
        except Empty:
            pass
        else:
            if token == self.request_id:
                self.busy = False
                if error:
                    self.status.configure(
                        text="Unable to complete. Check the selected account/year and try again. No payment was posted."
                    )
                    messagebox.showerror("Tax Bill", error, parent=self)
                elif operation == "search":
                    try:
                        self.render_page(result, context)
                    except (KeyError, TypeError, ValueError) as exc:
                        self.items = {}
                        self.next_cursor = None
                        self.tree.delete(*self.tree.get_children())
                        self.selection_changed()
                        self.status.configure(text=str(exc))
                else:
                    pid, year = context
                    self.status.configure(
                        text=f"Tax Bill {year} downloaded for account #{pid}. No financial records were changed."
                    )
                    try:
                        os.startfile(result)
                    except (OSError, TypeError) as exc:
                        messagebox.showerror(
                            "Tax Bill",
                            f"PDF downloaded but could not be opened: {exc}",
                            parent=self,
                        )
                self.update_controls()
        self._poll_id = self.after(100, self.poll)

    def close(self):
        self.closed = True
        self.request_id += 1
        self.after_cancel(self._poll_id)
        self.destroy()
