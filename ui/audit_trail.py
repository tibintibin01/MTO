import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from datetime import datetime
import api_clients.system_service as sys_svc
from theme_manager import ModernTheme
from utils import tr

class AuditTrailPage:
    def __init__(self, parent, user=None):
        self.parent = parent
        self.user = user
        self.current_page = 0
        self.page_size = 50
        self.next_cursor = None
        
        self.container = ctk.CTkFrame(parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.setup_ui()
        self.fetch_users()
        self.refresh_table()

    def setup_ui(self):
        # Header Area
        header_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        header_fr.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            header_fr, text=tr("audit.title"), font=ModernTheme.H2
        ).pack(side="left")

        self.export_btn = ctk.CTkButton(
            header_fr,
            text=f"📊 {tr('audit.btn_export')}",
            command=self.export_to_excel,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.WARNING,
            width=150
        )
        self.export_btn.pack(side="right")

        # --- ADVANCED FILTER BAR ---
        filter_bar = ctk.CTkFrame(self.container, fg_color=ModernTheme.SECONDARY, corner_radius=8)
        filter_bar.pack(fill="x", pady=(0, 15), padx=5)

        # User Filter
        ctk.CTkLabel(
            filter_bar, text=tr("audit.filters.user"), font=ModernTheme.BODY_BOLD, text_color="white"
        ).pack(side="left", padx=(15, 5))
        self.user_cmb = ctk.CTkComboBox(
            filter_bar, values=["ALL"], width=150, height=28, font=ModernTheme.BODY
        )
        self.user_cmb.pack(side="left", padx=5, pady=8)

        # Keyword Search
        ctk.CTkLabel(
            filter_bar, text=tr("audit.filters.search"), font=ModernTheme.BODY_BOLD, text_color="white"
        ).pack(side="left", padx=(15, 5))
        self.search_ent = ctk.CTkEntry(filter_bar, placeholder_text=tr("audit.filters.search_placeholder"), width=200, height=28, font=ModernTheme.BODY)
        self.search_ent.pack(side="left", padx=5)
        self.search_ent.bind("<Return>", lambda e: self.refresh_table())

        # Date Range
        ctk.CTkLabel(
            filter_bar, text=tr("audit.filters.from"), font=ModernTheme.BODY_BOLD, text_color="white"
        ).pack(side="left", padx=(15, 5))
        self.date_from_ent = ctk.CTkEntry(filter_bar, placeholder_text="YYYY-MM-DD", width=100, height=28, font=ModernTheme.BODY)
        self.date_from_ent.pack(side="left", padx=5)

        ctk.CTkLabel(
            filter_bar, text=tr("audit.filters.to"), font=ModernTheme.BODY_BOLD, text_color="white"
        ).pack(side="left", padx=(5, 5))
        self.date_to_ent = ctk.CTkEntry(filter_bar, placeholder_text="YYYY-MM-DD", width=100, height=28, font=ModernTheme.BODY)
        self.date_to_ent.pack(side="left", padx=5)

        ctk.CTkButton(
            filter_bar,
            text=f"🔍 {tr('audit.filters.btn_filter')}",
            command=self.refresh_table,
            width=100,
            height=28,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SUCCESS,
        ).pack(side="right", padx=15)

        # --- TABLE ---
        table_fr = ctk.CTkFrame(self.container, fg_color="white", corner_radius=12)
        table_fr.pack(fill="both", expand=True)

        self.cols = (
            tr("audit.table.timestamp"),
            tr("audit.table.user"),
            tr("audit.table.action"),
            tr("audit.table.table"),
            tr("audit.table.id"),
            tr("audit.table.ip"),
        )
        
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Custom.Treeview",
            rowheight=35,
            font=ModernTheme.BODY,
            background="#1e1e1e",
            fieldbackground="#1e1e1e",
            foreground="white",
        )
        style.configure(
            "Custom.Treeview.Heading",
            font=ModernTheme.BODY_BOLD,
            background="#333333",
            foreground="white",
        )
        style.map("Custom.Treeview", background=[("selected", ModernTheme.PRIMARY)])

        self.tree = ttk.Treeview(table_fr, columns=self.cols, show="headings", style="Custom.Treeview")
        
        # Configure columns
        col_widths = [160, 100, 350, 100, 60, 120]
        for i, col in enumerate(self.cols):
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=col_widths[i], anchor="center")
        
        self.tree.column(tr("audit.table.action"), anchor="w") # Action should be left-aligned
        
        # Scrollbar
        scrolly = ttk.Scrollbar(table_fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrolly.set)
        
        self.tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrolly.pack(side="right", fill="y")

        # --- PAGINATION ---
        self.pag_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        self.pag_fr.pack(fill="x", pady=10)

        self.prev_btn = ctk.CTkButton(self.pag_fr, text=f"◀ {tr('audit.pagination.prev')}", command=self.prev_page, width=80, font=ModernTheme.BUTTON_SMALL, fg_color=ModernTheme.SECONDARY)
        self.prev_btn.pack(side="left")

        self.page_lbl = ctk.CTkLabel(self.pag_fr, text=f"{tr('audit.pagination.page')} 1", font=ModernTheme.BODY_BOLD)
        self.page_lbl.pack(side="left", expand=True)

        self.next_btn = ctk.CTkButton(self.pag_fr, text=f"{tr('audit.pagination.next')} ▶", command=self.next_page, width=80, font=ModernTheme.BUTTON_SMALL, fg_color=ModernTheme.SECONDARY)
        self.next_btn.pack(side="right")

    def refresh_table(self, reset_page=True):
        if reset_page: self.current_page = 0
        
        def worker():
            try:
                user = self.user_cmb.get()
                search = self.search_ent.get().strip()
                d_from = self.date_from_ent.get().strip()
                d_to = self.date_to_ent.get().strip()
                
                offset = self.current_page * self.page_size
                response = sys_svc.get_audit_logs(
                    username=user if user != "ALL" else None,
                    search=search,
                    date_from=d_from if d_from else None,
                    date_to=d_to if d_to else None,
                    limit=self.page_size,
                    cursor=self.next_cursor if not reset_page else None
                )
                items = response.get("items", [])
                self.next_cursor = response.get("next_cursor")
                has_more = response.get("has_more", False)
                
                self.container.after(0, lambda: self._update_table(items, has_more))
            except Exception as e:
                self.container.after(0, lambda err=e: ErrorDialog(self.parent.winfo_toplevel(), tr("common.system_error"), tr("audit.messages.load_error").replace("{err}", str(err))))

        threading.Thread(target=worker, daemon=True).start()

    def _update_table(self, logs, has_more=False):
        self.page_lbl.configure(text=f"{tr('audit.pagination.page')} {self.current_page + 1}")
        self.prev_btn.configure(state="normal" if self.current_page > 0 else "disabled")
        self.next_btn.configure(state="normal" if has_more else "disabled")

        for item in self.tree.get_children():
            self.tree.delete(item)
            
        for log in logs:
            self.tree.insert("", "end", values=(
                log["timestamp"],
                log["username"],
                log["action"],
                log["table_name"],
                log["record_id"],
                log["ip_address"]
            ))

    def fetch_users(self):
        def worker():
            try:
                users = sys_svc.get_audit_users()
                if users:
                    self.container.after(0, lambda: self.user_cmb.configure(values=["ALL"] + users))
            except: pass
        threading.Thread(target=worker, daemon=True).start()

    def next_page(self):
        self.current_page += 1
        self.refresh_table(reset_page=False)

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh_table(reset_page=False)

    def export_to_excel(self):
        from utils import export_data_to_excel
        data = []
        for child in self.tree.get_children():
            data.append(self.tree.item(child)["values"])
            
        if not data:
            ErrorDialog(self.parent.winfo_toplevel(), tr("audit.messages.export_error"), tr("property.errors.no_data_msg"))
            return
            
        try:
            export_data_to_excel(data, self.cols, filename_prefix="AuditLogs")
            show_toast(self.parent.winfo_toplevel(), tr("audit.messages.export_success"), type="success")
        except Exception as e:
            ErrorDialog(self.parent.winfo_toplevel(), tr("audit.messages.export_error"), str(e))
