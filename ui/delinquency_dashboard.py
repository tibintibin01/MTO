import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

import api_clients.api_helper as api
import api_clients.auth_service as auth
import api_clients.billing_service as billing
import api_clients.property_service as properties
from theme_manager import ModernTheme
from ui.dossier import PropertyDossierModal
from ui_components import LoadingOverlay, ErrorDialog
from utils import export_data_to_excel, format_curr


class DelinquencyDashboardPage:
    def __init__(self, parent, user=None):
        self.parent = parent
        self.user = user
        self.current_offset = 0
        self.page_size = 50
        self.has_more = False
        self.next_offset = None
        self.current_items = {}
        self.summary_cards = {}

        self.container = ctk.CTkFrame(parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)
        self.setup_ui()
        self.fetch_barangays()
        self.refresh_table(reset=True)

    def setup_ui(self):
        header = ctk.CTkFrame(self.container, fg_color="transparent")
        header.pack(fill="x", pady=(0, 14))

        title_block = ctk.CTkFrame(header, fg_color="transparent")
        title_block.pack(side="left")
        ctk.CTkLabel(
            title_block,
            text="COLLECTION WORKBENCH",
            font=ModernTheme.H1,
            text_color=ModernTheme.PRIMARY,
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_block,
            text="Prioritize delinquent accounts, prepare documents, and post collections from one screen.",
            font=ModernTheme.BODY,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(anchor="w", pady=(3, 0))

        ctk.CTkButton(
            header,
            text="REFRESH",
            command=lambda: self.refresh_table(reset=True),
            width=130,
            height=34,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.SECONDARY,
        ).pack(side="right")

        self._build_summary()
        self._build_filters()
        self._build_table()
        self._build_footer()

    def _build_summary(self):
        summary = ctk.CTkFrame(self.container, fg_color="transparent")
        summary.pack(fill="x", pady=(0, 12))

        cards = [
            ("accounts", "ACCOUNTS", "0"),
            ("balance", "TOTAL BALANCE", "0.00"),
            ("oldest", "120+ DAYS", "0.00"),
            ("selected", "SELECTED BALANCE", "0.00"),
        ]
        for key, label, value in cards:
            card = ctk.CTkFrame(
                summary,
                fg_color=ModernTheme.CARD_DARK,
                border_width=1,
                border_color="#334155",
                corner_radius=8,
            )
            card.pack(side="left", fill="x", expand=True, padx=(0, 10))
            ctk.CTkLabel(card, text=label, font=("Inter", 9, "bold"), text_color="#94a3b8").pack(pady=(10, 0))
            value_lbl = ctk.CTkLabel(card, text=value, font=("Inter", 18, "bold"), text_color=ModernTheme.PRIMARY)
            value_lbl.pack(pady=(2, 10))
            self.summary_cards[key] = value_lbl

    def _build_filters(self):
        filters = ctk.CTkFrame(
            self.container,
            fg_color=ModernTheme.SECONDARY,
            corner_radius=8,
        )
        filters.pack(fill="x", pady=(0, 12))

        self.search_ent = ctk.CTkEntry(
            filters,
            width=260,
            height=32,
            placeholder_text="Search TD, former TD, owner, PIN...",
            font=ModernTheme.BODY,
        )
        self.search_ent.pack(side="left", padx=(12, 8), pady=10)
        self.search_ent.bind("<Return>", lambda _e: self.refresh_table(reset=True))

        self.barangay_cmb = ctk.CTkComboBox(filters, values=["ALL"], width=170, height=32, font=ModernTheme.BODY)
        self.barangay_cmb.set("ALL")
        self.barangay_cmb.pack(side="left", padx=8, pady=10)

        self.age_cmb = ctk.CTkComboBox(
            filters,
            values=["ALL AGES", "30+ DAYS", "60+ DAYS", "90+ DAYS", "120+ DAYS"],
            width=120,
            height=32,
            font=ModernTheme.BODY,
        )
        self.age_cmb.set("ALL AGES")
        self.age_cmb.pack(side="left", padx=8, pady=10)

        self.status_cmb = ctk.CTkComboBox(
            filters,
            values=["ALL", "NO PAYMENT", "PARTIAL"],
            width=125,
            height=32,
            font=ModernTheme.BODY,
        )
        self.status_cmb.set("ALL")
        self.status_cmb.pack(side="left", padx=8, pady=10)

        self.min_balance_ent = ctk.CTkEntry(
            filters,
            width=115,
            height=32,
            placeholder_text="Min balance",
            font=ModernTheme.BODY,
        )
        self.min_balance_ent.pack(side="left", padx=8, pady=10)

        ctk.CTkButton(
            filters,
            text="APPLY",
            command=lambda: self.refresh_table(reset=True),
            width=90,
            height=32,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SUCCESS,
        ).pack(side="left", padx=(8, 12), pady=10)

    def _build_table(self):
        table_fr = ctk.CTkFrame(self.container, fg_color="transparent", corner_radius=8)
        table_fr.pack(fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Delinq.Treeview",
            rowheight=36,
            font=ModernTheme.BODY,
            background="#172033",
            fieldbackground="#172033",
            foreground="white",
            borderwidth=0,
        )
        style.configure(
            "Delinq.Treeview.Heading",
            font=ModernTheme.BODY_BOLD,
            background="#333333",
            foreground="white",
        )
        style.map("Delinq.Treeview", background=[("selected", ModernTheme.PRIMARY)])

        self.cols = (
            "ID", "TD NUMBER", "OWNER NAME", "BARANGAY", "BALANCE",
            "TOTAL PAID", "TOTAL DUE", "YEARS", "EARLIEST", "AGING", "PRIORITY",
        )
        self.tree = ttk.Treeview(table_fr, columns=self.cols, show="headings", style="Delinq.Treeview")
        for col in self.cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center", width=110)

        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.column("OWNER NAME", width=310, anchor="w")
        self.tree.column("BARANGAY", width=170, anchor="w")
        self.tree.column("BALANCE", width=140)
        self.tree.column("PRIORITY", width=130)

        scrolly = ttk.Scrollbar(table_fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrolly.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(0, 4))
        scrolly.pack(side="right", fill="y")

        self.tree.tag_configure("evenrow", background="#182235", foreground="white")
        self.tree.tag_configure("oddrow", background="#202b3f", foreground="white")
        self.tree.tag_configure("high", background="#3a2730", foreground="white")
        self.tree.tag_configure("urgent", background="#43292a", foreground="white")

        self.tree.bind("<<TreeviewSelect>>", self.on_selection_change)
        self.tree.bind("<Double-1>", lambda _e: self.open_dossier())

    def _build_footer(self):
        footer = ctk.CTkFrame(self.container, fg_color="transparent")
        footer.pack(fill="x", pady=(12, 0))

        nav = ctk.CTkFrame(footer, fg_color="transparent")
        nav.pack(side="left")
        self.prev_btn = ctk.CTkButton(nav, text="PREV", command=self.prev_page, width=85, fg_color=ModernTheme.SECONDARY)
        self.prev_btn.pack(side="left", padx=(0, 6))
        self.page_lbl = ctk.CTkLabel(nav, text="Showing 0 accounts", font=ModernTheme.BODY_BOLD, text_color=ModernTheme.TEXT_GRAY)
        self.page_lbl.pack(side="left", padx=8)
        self.next_btn = ctk.CTkButton(nav, text="NEXT", command=self.next_page, width=85, fg_color=ModernTheme.SECONDARY)
        self.next_btn.pack(side="left", padx=6)

        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.pack(side="right")

        self.export_btn = ctk.CTkButton(
            actions, text="EXPORT PAGE", command=self.export_page,
            width=125, height=40, fg_color=ModernTheme.WARNING, font=ModernTheme.BUTTON,
        )
        self.export_btn.pack(side="left", padx=5)

        self.dossier_btn = ctk.CTkButton(
            actions, text="DOSSIER", command=self.open_dossier,
            width=110, height=40, fg_color=ModernTheme.PRIMARY, font=ModernTheme.BUTTON, state="disabled",
        )
        self.dossier_btn.pack(side="left", padx=5)

        if auth.has_permission(self.user, "payment_post"):
            self.add_payment_btn = ctk.CTkButton(
                actions, text="ADD PAYMENT", command=self.add_payment,
                width=130, height=40, fg_color=ModernTheme.SUCCESS, font=ModernTheme.BUTTON, state="disabled",
            )
            self.add_payment_btn.pack(side="left", padx=5)

        self.compute_btn = ctk.CTkButton(
            actions, text="COMPUTATION", command=self.generate_computation,
            width=135, height=40, fg_color=ModernTheme.SUCCESS, font=ModernTheme.BUTTON, state="disabled",
        )
        self.compute_btn.pack(side="left", padx=5)

        self.notice_btn = ctk.CTkButton(
            actions, text="NOTICE", command=self.generate_notice,
            width=105, height=40, fg_color=ModernTheme.DANGER, font=ModernTheme.BUTTON, state="disabled",
        )
        self.notice_btn.pack(side="left", padx=5)

    def fetch_barangays(self):
        def worker():
            try:
                barangays = properties.get_barangays()
                values = ["ALL"] + list(barangays or [])
                self.container.after(0, lambda: self.barangay_cmb.configure(values=values))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def refresh_table(self, reset=False):
        if reset:
            self.current_offset = 0
        min_balance = self._min_balance()
        if min_balance == "INVALID":
            return
        filters = {
            "barangay": self.barangay_cmb.get(),
            "search": self.search_ent.get().strip(),
            "payment_status": self._status_filter(),
            "min_balance": min_balance,
            "min_age_days": self._age_filter(),
        }
        overlay = LoadingOverlay(self.container, "Loading collections workbench...")

        def worker():
            try:
                result = billing.get_collections_worklist(
                    **filters,
                    limit=self.page_size,
                    offset=self.current_offset,
                )
                self.container.after(0, lambda res=result: self._update_table(res))
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Collections", str(err)))
            finally:
                self.container.after(0, overlay.hide)

        threading.Thread(target=worker, daemon=True).start()

    def _update_table(self, result):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.current_items = {}

        items = result.get("items", []) if isinstance(result, dict) else []
        self.has_more = bool(result.get("has_more")) if isinstance(result, dict) else False
        self.next_offset = result.get("next_offset") if isinstance(result, dict) else None

        for index, item in enumerate(items):
            priority = self._priority(item)
            tag = self._row_tag(index, item, priority)
            values = (
                item.get("id"),
                item.get("td_number"),
                item.get("owner_name"),
                item.get("barangay") or item.get("location"),
                format_curr(item.get("balance", 0)),
                format_curr(item.get("total_paid", 0)),
                format_curr(item.get("total_due", 0)),
                item.get("years_billed", 0),
                item.get("earliest_year") or "-",
                item.get("aging_bucket") or "-",
                priority,
            )
            item_id = self.tree.insert("", "end", values=values, tags=(tag,))
            self.current_items[item_id] = item

        self._update_summary(result, items)
        self.on_selection_change()

    def _update_summary(self, result, items):
        summary = result.get("summary", {}) if isinstance(result, dict) else {}
        aging = summary.get("aging_totals", {}) if isinstance(summary, dict) else {}
        self.summary_cards["accounts"].configure(text=f"{summary.get('delinquent_count', 0):,}")
        self.summary_cards["balance"].configure(text=format_curr(summary.get("total_balance", 0)))
        self.summary_cards["oldest"].configure(text=format_curr(aging.get("120+", 0)))
        self.summary_cards["selected"].configure(text="0.00")

        total_matching = result.get("total_matching", len(items)) if isinstance(result, dict) else len(items)
        start = 0 if not items else self.current_offset + 1
        end = self.current_offset + len(items)
        self.page_lbl.configure(text=f"Showing {start:,}-{end:,} of {total_matching:,}")
        self.prev_btn.configure(state="normal" if self.current_offset > 0 else "disabled")
        self.next_btn.configure(state="normal" if self.has_more else "disabled")

    def on_selection_change(self, event=None):
        selected = self._selected_item()
        state = "normal" if selected else "disabled"
        self.dossier_btn.configure(state=state)
        self.compute_btn.configure(state=state)
        self.notice_btn.configure(state=state)
        if hasattr(self, "add_payment_btn"):
            self.add_payment_btn.configure(state=state)
        self.summary_cards["selected"].configure(
            text=format_curr(selected.get("balance", 0)) if selected else "0.00"
        )

    def _selected_item(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.current_items.get(sel[0])

    def _age_filter(self):
        value = self.age_cmb.get()
        if value.startswith("120"):
            return 120
        if value.startswith("90"):
            return 90
        if value.startswith("60"):
            return 60
        if value.startswith("30"):
            return 30
        return 0

    def _status_filter(self):
        value = self.status_cmb.get().strip().upper()
        if value == "NO PAYMENT":
            return "NO_PAYMENT"
        if value == "PARTIAL":
            return "PARTIAL"
        return "ALL"

    def _min_balance(self):
        raw = self.min_balance_ent.get().replace(",", "").strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            ErrorDialog(self.parent.winfo_toplevel(), "Invalid Filter", "Minimum balance must be a number.")
            return "INVALID"

    def _priority(self, item):
        balance = float(item.get("balance") or 0)
        paid = float(item.get("total_paid") or 0)
        years = int(item.get("years_billed") or 0)
        age_bucket = str(item.get("aging_bucket") or "")
        if balance >= 10000 or age_bucket == "120+":
            return "HIGH PRIORITY"
        if paid <= 0:
            return "NO PAYMENT"
        if years >= 2:
            return "MULTI-YEAR"
        return "FOLLOW UP"

    def _row_tag(self, index, item, priority):
        if priority == "HIGH PRIORITY":
            return "urgent"
        if priority in ("NO PAYMENT", "MULTI-YEAR"):
            return "high"
        return "evenrow" if index % 2 == 0 else "oddrow"

    def prev_page(self):
        if self.current_offset <= 0:
            return
        self.current_offset = max(0, self.current_offset - self.page_size)
        self.refresh_table()

    def next_page(self):
        if not self.has_more:
            return
        self.current_offset = self.next_offset if self.next_offset is not None else self.current_offset + self.page_size
        self.refresh_table()

    def open_dossier(self):
        item = self._selected_item()
        if not item:
            return
        td = str(item.get("td_number", "")).strip()
        overlay = LoadingOverlay(self.container, f"Opening dossier for {td}...")

        def worker():
            try:
                data = api.api_request("GET", f"/properties/dossier/{td}")
                self.container.after(0, lambda: PropertyDossierModal(self.parent, data))
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Dossier", str(err)))
            finally:
                self.container.after(0, overlay.hide)

        threading.Thread(target=worker, daemon=True).start()

    def add_payment(self):
        item = self._selected_item()
        if not item:
            return
        from ui.property import PropertyEditModal
        PropertyEditModal(
            self.container.winfo_toplevel(),
            "Add Payment",
            item.get("id"),
            lambda: self.refresh_table(reset=True),
            user=self.user,
            payment_mode=True,
        )

    def generate_computation(self):
        self._download_pdf("computation", billing.download_computation_pdf)

    def generate_notice(self):
        self._download_pdf("notice", billing.download_notice_pdf)

    def _download_pdf(self, label, downloader):
        item = self._selected_item()
        if not item:
            return
        prop_id = item.get("id")
        td_no = item.get("td_number")
        overlay = LoadingOverlay(self.container, f"Generating {label} for {td_no}...")

        def worker():
            try:
                pdf_path = downloader(prop_id)
                if pdf_path and os.path.exists(pdf_path):
                    os.startfile(pdf_path)
                self.container.after(0, lambda: messagebox.showinfo("Success", f"{label.title()} generated for TD: {td_no}"))
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Generation Error", str(err)))
            finally:
                self.container.after(0, overlay.hide)

        threading.Thread(target=worker, daemon=True).start()

    def export_page(self):
        rows = [self.tree.item(child)["values"] for child in self.tree.get_children()]
        if not rows:
            messagebox.showwarning("Export", "No rows to export.")
            return
        export_data_to_excel(rows, self.cols, filename_prefix="CollectionWorkbench")
