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
        name = str(vals[2])

        confirmed = self._confirm_dialog(
            title="Restore Property",
            icon="🔄",
            icon_color="#059669",
            border_color="#10b981",
            message=f"Restore this property back to active records?",
            detail=name,
            confirm_text="RESTORE",
            confirm_color="#059669",
            confirm_hover="#047857",
        )
        if not confirmed:
            return
        try:
            prop_svc.restore_property(prop_id)
            self.refresh()
            self._success_dialog("Property Restored", f"{name}\nhas been restored to active records.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def purge_selected(self):
        sel = self.tree.selection()
        if not sel: return
        vals = self.tree.item(sel[0])["values"]
        prop_id = vals[0]
        name = str(vals[2])

        confirmed = self._confirm_dialog(
            title="Permanently Delete",
            icon="💀",
            icon_color="#ef4444",
            border_color="#ef4444",
            message="This will PERMANENTLY delete the property and\nall its payment records. This cannot be undone.",
            detail=name,
            confirm_text="DELETE PERMANENTLY",
            confirm_color="#dc2626",
            confirm_hover="#b91c1c",
        )
        if not confirmed:
            return
        try:
            prop_svc.purge_property(prop_id)
            self.refresh()
            self._success_dialog("Property Deleted", f"{name}\nhas been permanently removed.", success=False)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ── Premium dialog helpers ─────────────────────────────────────────────────

    def _confirm_dialog(self, title, icon, icon_color, border_color,
                        message, detail, confirm_text, confirm_color, confirm_hover):
        """
        Borderless dark confirmation dialog.
        Returns True if confirmed, False if cancelled.
        """
        result = tk.BooleanVar(value=False)

        dlg = ctk.CTkToplevel(self.container)
        dlg.title("")
        dlg.resizable(False, False)
        dlg.overrideredirect(True)
        dlg.attributes("-topmost", True)
        dlg.grab_set()

        dlg.update_idletasks()
        dw, dh = 440, 280
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        dlg.geometry(f"{dw}x{dh}+{(sw-dw)//2}+{(sh-dh)//2}")

        outer = ctk.CTkFrame(
            dlg, fg_color="#0f172a", corner_radius=16,
            border_width=1, border_color="#1e293b",
        )
        outer.pack(fill="both", expand=True, padx=2, pady=2)

        # Accent bar
        ctk.CTkFrame(outer, height=5, fg_color=border_color, corner_radius=0).pack(fill="x")

        # Icon
        icon_fr = ctk.CTkFrame(
            outer, width=56, height=56, corner_radius=28,
            fg_color="#1e293b", border_width=2, border_color=border_color,
        )
        icon_fr.pack(pady=(18, 0))
        icon_fr.pack_propagate(False)
        ctk.CTkLabel(
            icon_fr, text=icon,
            font=("Segoe UI Emoji", 22), text_color=icon_color,
        ).place(relx=0.5, rely=0.5, anchor="center")

        # Title
        ctk.CTkLabel(
            outer, text=title,
            font=("Inter", 15, "bold"), text_color="#f1f5f9",
        ).pack(pady=(10, 2))

        # Message
        ctk.CTkLabel(
            outer, text=message,
            font=("Inter", 11), text_color="#94a3b8", justify="center",
        ).pack()

        # Detail (property name)
        ctk.CTkLabel(
            outer, text=detail,
            font=("Inter", 11, "bold"), text_color="#e2e8f0", justify="center",
            wraplength=380,
        ).pack(pady=(4, 0))

        # Divider
        ctk.CTkFrame(outer, height=1, fg_color="#1e293b").pack(fill="x", padx=20, pady=(12, 0))

        # Buttons
        btn_fr = ctk.CTkFrame(outer, fg_color="transparent")
        btn_fr.pack(pady=12)

        def on_cancel():
            result.set(False)
            dlg.grab_release()
            dlg.destroy()

        def on_confirm():
            result.set(True)
            dlg.grab_release()
            dlg.destroy()

        ctk.CTkButton(
            btn_fr, text="CANCEL", command=on_cancel,
            fg_color="#1e293b", hover_color="#334155",
            text_color="#94a3b8", border_width=1, border_color="#334155",
            font=("Inter", 12, "bold"), width=130, height=36, corner_radius=8,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_fr, text=confirm_text, command=on_confirm,
            fg_color=confirm_color, hover_color=confirm_hover,
            text_color="white",
            font=("Inter", 12, "bold"), width=170, height=36, corner_radius=8,
        ).pack(side="left")

        dlg.bind("<Return>", lambda e: on_confirm())
        dlg.bind("<Escape>", lambda e: on_cancel())
        dlg.focus_set()
        dlg.wait_window()
        return result.get()

    def _success_dialog(self, title, message, success=True):
        """Borderless dark success/info dialog."""
        color = "#10b981" if success else "#64748b"
        icon  = "✓" if success else "✕"

        dlg = ctk.CTkToplevel(self.container)
        dlg.title("")
        dlg.resizable(False, False)
        dlg.overrideredirect(True)
        dlg.attributes("-topmost", True)
        dlg.grab_set()

        dlg.update_idletasks()
        dw, dh = 380, 230
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        dlg.geometry(f"{dw}x{dh}+{(sw-dw)//2}+{(sh-dh)//2}")

        outer = ctk.CTkFrame(
            dlg, fg_color="#0f172a", corner_radius=16,
            border_width=1, border_color="#1e293b",
        )
        outer.pack(fill="both", expand=True, padx=2, pady=2)

        ctk.CTkFrame(outer, height=5, fg_color=color, corner_radius=0).pack(fill="x")

        icon_fr = ctk.CTkFrame(
            outer, width=52, height=52, corner_radius=26,
            fg_color="#1e293b", border_width=2, border_color=color,
        )
        icon_fr.pack(pady=(16, 0))
        icon_fr.pack_propagate(False)
        ctk.CTkLabel(
            icon_fr, text=icon,
            font=("Inter", 22, "bold"), text_color=color,
        ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            outer, text=title,
            font=("Inter", 14, "bold"), text_color="#f1f5f9",
        ).pack(pady=(10, 2))

        ctk.CTkLabel(
            outer, text=message,
            font=("Inter", 11), text_color="#94a3b8", justify="center",
        ).pack()

        ctk.CTkFrame(outer, height=1, fg_color="#1e293b").pack(fill="x", padx=20, pady=(10, 0))

        def close():
            dlg.grab_release()
            dlg.destroy()

        ctk.CTkButton(
            outer, text="OK", command=close,
            fg_color=color, hover_color="#047857" if success else "#475569",
            text_color="white",
            font=("Inter", 12, "bold"), width=120, height=34, corner_radius=8,
        ).pack(pady=10)

        dlg.bind("<Return>", lambda e: close())
        dlg.bind("<Escape>", lambda e: close())
        dlg.focus_set()
        dlg.wait_window()
