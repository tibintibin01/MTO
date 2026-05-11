import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
from theme_manager import ModernTheme
from utils import tr
import api_clients.property_service as prop_svc
import threading

class RecycleBinPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.setup_ui()
        self.refresh()

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        header = ctk.CTkFrame(self.container, fg_color="transparent")
        header.pack(fill="x", pady=(0, 20))
        
        ctk.CTkLabel(header, text=tr("recycle.title"), font=ModernTheme.H2).pack(side="left")
        ctk.CTkLabel(header, text=tr("recycle.subtitle"), font=ModernTheme.BODY, text_color=ModernTheme.TEXT_GRAY).pack(side="left", padx=20)
        
        ctk.CTkButton(header, text=f"🔄 {tr('recycle.btn_refresh')}", command=self.refresh, width=120, font=ModernTheme.BUTTON_SMALL, fg_color=ModernTheme.SECONDARY).pack(side="right")

        # Table Area
        table_fr = ctk.CTkFrame(self.container)
        table_fr.pack(fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Recycle.Treeview", rowheight=40, font=("Segoe UI", 10), background="#2b2b2b", fieldbackground="#2b2b2b", foreground="white")
        style.configure("Recycle.Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#333333", foreground="white")
        
        self.cols = (
            tr("recycle.table.id"),
            tr("recycle.table.td"),
            tr("recycle.table.owner"),
            tr("recycle.table.location"),
            tr("recycle.table.value")
        )
        self.tree = ttk.Treeview(table_fr, columns=self.cols, show="headings", style="Recycle.Treeview")
        
        for col in self.cols:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, anchor="center")
        
        self.tree.column(tr("recycle.table.id"), width=0, stretch=tk.NO)
        self.tree.column(tr("recycle.table.owner"), width=300, anchor="w")
        
        scrolly = ttk.Scrollbar(table_fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrolly.set)
        
        # Zebra Tags
        self.tree.tag_configure('oddrow', background="#2b2b2b", foreground="white")
        self.tree.tag_configure('evenrow', background="#333333", foreground="white")
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrolly.pack(side="right", fill="y")

        # Footer Action Bar
        self.action_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        self.action_fr.pack(fill="x", pady=(20, 0))
        
        self.restore_btn = ctk.CTkButton(self.action_fr, text=f"🔄 {tr('recycle.btn_restore')}", command=self.restore_selected,
                                         font=ModernTheme.BUTTON, fg_color=ModernTheme.SUCCESS, height=45, state="disabled")
        self.restore_btn.pack(side="left", padx=5)
        
        self.purge_btn = ctk.CTkButton(self.action_fr, text=f"💀 {tr('recycle.btn_purge')}", command=self.purge_selected,
                                       font=ModernTheme.BUTTON, fg_color=ModernTheme.DANGER, height=45, state="disabled")
        self.purge_btn.pack(side="right", padx=5)
        
        self.tree.bind("<<TreeviewSelect>>", self.on_selection_change)

    def on_selection_change(self, event=None):
        has_selection = bool(self.tree.selection())
        state = "normal" if has_selection else "disabled"
        self.restore_btn.configure(state=state)
        self.purge_btn.configure(state=state)

    def refresh(self):
        def worker():
            try:
                results = prop_svc.get_deleted_properties()
                self.container.after(0, lambda: self._update_table(results))
            except Exception as e:
                self.container.after(
                    0, lambda err=e: messagebox.showerror("Refresh Error", str(err))
                )
        threading.Thread(target=worker, daemon=True).start()

    def _update_table(self, rows):
        for r in self.tree.get_children(): self.tree.delete(r)
        for i, row in enumerate(rows):
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            # (id, td_number, owner_name, location, total)
            self.tree.insert("", "end", values=row, tags=(tag,))
        self.on_selection_change()

    def restore_selected(self):
        sel = self.tree.selection()
        if not sel: return
        vals = self.tree.item(sel[0])["values"]
        prop_id = vals[0]
        name = vals[2]
        
        if messagebox.askyesno(tr("recycle.messages.confirm_restore"), tr("recycle.messages.confirm_restore_msg").replace("{name}", name)):
            try:
                prop_svc.restore_property(prop_id)
                self.refresh()
                show_toast(self.container.winfo_toplevel(), tr("recycle.messages.success_restore"), type="success")
            except Exception as e:
                ErrorDialog(self.container.winfo_toplevel(), tr("common.error"), str(e))

    def purge_selected(self):
        sel = self.tree.selection()
        if not sel: return
        vals = self.tree.item(sel[0])["values"]
        prop_id = vals[0]
        name = vals[2]
        
        msg = tr("recycle.messages.confirm_purge_msg").replace("{name}", name)
        if messagebox.askyesno(tr("recycle.messages.confirm_purge"), msg, icon="warning"):
            try:
                prop_svc.purge_property(prop_id)
                self.refresh()
                show_toast(self.container.winfo_toplevel(), tr("recycle.messages.success_purge"), type="success")
            except Exception as e:
                ErrorDialog(self.container.winfo_toplevel(), tr("common.error"), str(e))
