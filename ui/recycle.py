import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
from theme_manager import ModernTheme
import services.property_service as prop_svc
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
        
        ctk.CTkLabel(header, text="Recycle Bin", font=ModernTheme.H2).pack(side="left")
        ctk.CTkLabel(header, text="Deleted records can be recovered here.", font=ModernTheme.BODY, text_color="gray").pack(side="left", padx=20)
        
        ctk.CTkButton(header, text="REFRESH", command=self.refresh, width=100).pack(side="right")

        # Table Area
        table_fr = ctk.CTkFrame(self.container)
        table_fr.pack(fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Recycle.Treeview", rowheight=40, font=("Segoe UI", 10), background="#2b2b2b", fieldbackground="#2b2b2b", foreground="white")
        style.configure("Recycle.Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#333333", foreground="white")
        
        self.cols = ("ID", "TD Number", "Owner Name", "Location", "Last Value")
        self.tree = ttk.Treeview(table_fr, columns=self.cols, show="headings", style="Recycle.Treeview")
        
        for col in self.cols:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, anchor="center")
        
        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.column("Owner Name", width=300, anchor="w")
        
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
        
        self.restore_btn = ctk.CTkButton(self.action_fr, text="🔄 RESTORE SELECTED", command=self.restore_selected,
                                         fg_color="#27ae60", hover_color="#219150", height=45, state="disabled")
        self.restore_btn.pack(side="left", padx=5)
        
        self.purge_btn = ctk.CTkButton(self.action_fr, text="💀 PURGE PERMANENTLY", command=self.purge_selected,
                                       fg_color="#e74c3c", hover_color="#c0392b", height=45, state="disabled")
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
                self.container.after(0, lambda: messagebox.showerror("Refresh Error", str(e)))
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
        
        if messagebox.askyesno("Confirm Restore", f"Restore property record for '{name}'?"):
            try:
                prop_svc.restore_property(prop_id)
                self.refresh()
                messagebox.showinfo("Success", "Record restored successfully.")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def purge_selected(self):
        sel = self.tree.selection()
        if not sel: return
        vals = self.tree.item(sel[0])["values"]
        prop_id = vals[0]
        name = vals[2]
        
        msg = f"WARNING: Permanent Purge\n\nYou are about to permanently delete the record for '{name}'.\n\nTHIS ACTION CANNOT BE UNDONE. ALL HISTORY WILL BE LOST.\n\nContinue?"
        if messagebox.askyesno("DANGER: PERMANENT PURGE", msg, icon="warning"):
            try:
                prop_svc.purge_property(prop_id)
                self.refresh()
                messagebox.showinfo("Success", "Record purged from database.")
            except Exception as e:
                messagebox.showerror("Error", str(e))
