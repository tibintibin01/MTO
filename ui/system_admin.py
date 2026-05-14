import customtkinter as ctk
from tkinter import messagebox
import api_clients.auth_service as auth
from ui.users import UserAccessPage
from ui.logs import AuditLogsPage
from ui.recycle import RecycleBinPage
from theme_manager import ModernTheme
from utils import tr


class SystemAdminPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.pages = []
        self.setup_ui()

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            self.container, text=tr("admin.title"), font=ModernTheme.H2
        ).pack(anchor="w", pady=(0, 20))

        self.tabview = ctk.CTkTabview(self.container)
        self.tabview.pack(fill="both", expand=True)

        # User Management
        if auth.has_permission(self.user, "manage_users"):
            tab = self.tabview.add(tr("admin.tabs.users"))
            self.user_page = UserAccessPage(tab, self.user)
            self.pages.append(self.user_page)

        # Audit Logs
        if auth.has_permission(self.user, "view_logs"):
            tab = self.tabview.add(tr("admin.tabs.audit"))
            self.logs_page = AuditLogsPage(tab, self.user)
            self.pages.append(self.logs_page)

        # Recycle Bin
        if auth.has_permission(self.user, "recycle_manage"):
            tab = self.tabview.add(tr("admin.tabs.recycle"))
            self.recycle_page = RecycleBinPage(tab, self.user)
            self.pages.append(self.recycle_page)

        # Database Tab
        if auth.has_permission(self.user, "backup_restore"):
            tab = self.tabview.add(tr("admin.tabs.db"))
            self.setup_db_tab(tab)

    def setup_db_tab(self, parent):
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=40, pady=20)

        # Main Action Card
        card = ctk.CTkFrame(
            container,
            fg_color=("#ffffff", "#2b2b2b"),
            corner_radius=15,
            border_width=1,
            border_color=("#e0e0e0", "#333333"),
        )
        card.pack(fill="x", pady=10)

        ctk.CTkLabel(
            card,
            text=tr("admin.db.title"),
            font=ModernTheme.H3,
            text_color=ModernTheme.PRIMARY,
        ).pack(pady=(20, 5))
        ctk.CTkLabel(
            card,
            text=tr("admin.db.subtitle"),
            font=ModernTheme.BODY,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(pady=(0, 20))

        btn_fr = ctk.CTkFrame(card, fg_color="transparent")
        btn_fr.pack(pady=(0, 30))

        self.backup_btn = ctk.CTkButton(
            btn_fr,
            text=f"🚀 {tr('admin.db.btn_start')}",
            command=self.trigger_backup,
            height=45,
            width=220,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.SUCCESS,
        )
        self.backup_btn.pack(side="left", padx=5)

        self.view_btn = ctk.CTkButton(
            btn_fr,
            text=f"📁 {tr('admin.db.btn_view')}",
            command=self.open_backup_folder,
            height=45,
            width=150,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.SECONDARY,
        )
        self.view_btn.pack(side="left", padx=5)

        self.restore_btn = ctk.CTkButton(
            btn_fr,
            text=f"⏮️ {tr('admin.db.btn_restore')}",
            command=self.restore_backup,
            height=45,
            width=120,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.TEXT_GRAY,
        )
        self.restore_btn.pack(side="left", padx=5)

        # Status Panel
        status_fr = ctk.CTkFrame(
            container, fg_color=("#f8f9fa", "#1e1e1e"), corner_radius=12
        )
        status_fr.pack(fill="both", expand=True, pady=10)

        ctk.CTkLabel(
            status_fr,
            text=tr("admin.db.status_title"),
            font=ModernTheme.BODY_BOLD,
            text_color=ModernTheme.PRIMARY,
        ).pack(anchor="w", padx=20, pady=(15, 10))

        self.status_labels = {}
        status_items = [
            (tr("admin.db.items.local"), "last_local"),
            (tr("admin.db.items.usb"), "last_usb"),
            (tr("admin.db.items.cloud"), "last_cloud"),
            (tr("admin.db.items.verify"), "last_verify"),
        ]

        for label, key in status_items:
            row = ctk.CTkFrame(status_fr, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=5)
            # Use dynamic text color for the label
            ctk.CTkLabel(
                row,
                text=label,
                font=ModernTheme.BODY,
                text_color=ModernTheme.TEXT_GRAY,
            ).pack(side="left")
            self.status_labels[key] = ctk.CTkLabel(
                row,
                text=tr("admin.db.scanning"),
                font=ModernTheme.BODY_BOLD,
                text_color=ModernTheme.PRIMARY,
            )
            self.status_labels[key].pack(side="right", padx=(10, 20))

        self.update_status_display()

    def update_status_display(self):
        try:
            import api_clients.system_service as system_svc
            # Fetch from API to ensure we see the server's state, not the local process state
            status = system_svc.get_backup_verification_status()
            if status:
                for key, lbl in self.status_labels.items():
                    val = status.get(key, "Unknown")
                    # Highlight green for success/timestamps, orange for unknown/failed
                    # Highlight green for SUCCESS/OK/timestamps, orange for failures
                    upper_val = val.upper()
                    color = ModernTheme.SUCCESS if ("SUCCESS" in upper_val or ":" in upper_val or "OK" in upper_val) else ModernTheme.WARNING
                    lbl.configure(text=val, text_color=color)
        except Exception as e:
            print(f"DEBUG: Status update failed: {e}")
            pass
            
        # Refresh every 3 seconds while the widget exists
        if self.container.winfo_exists():
            self.container.after(3000, self.update_status_display)

    def trigger_backup(self):
        import threading

        if self.backup_btn.cget("state") == "disabled":
            return

        self.backup_btn.configure(
            state="disabled", text=f"🛡️ {tr('admin.db.progress')}", fg_color=ModernTheme.TEXT_GRAY
        )

        def run():
            try:
                import api_clients.system_service as system_svc

                # Call the API endpoint instead of direct backend service
                res = system_svc.trigger_backup()

                # Check if the UI still exists before updating
                if self.container.winfo_exists():
                    # API returns status: 'backup_started'
                    is_ok = res.get("status") == "backup_started"
                    msg = res.get("message", "Backup trigger failed")
                    self.container.after(0, lambda: self._finalize_backup(is_ok, msg))
            except Exception as e:
                err_msg = str(e)
                try:
                    if self.container.winfo_exists():
                        self.container.after(
                            0,
                            lambda: self._finalize_backup(
                                False, f"Thread Crash: {err_msg}"
                            ),
                        )
                except:
                    pass

        threading.Thread(target=run, daemon=True).start()

    def _finalize_backup(self, success, msg):
        self.backup_btn.configure(
            state="normal", text=f"🚀 {tr('admin.db.btn_start')}", fg_color=ModernTheme.SUCCESS
        )
        self.update_status_display()
        if success:
            show_toast(self.container.winfo_toplevel(), tr("admin.db.success"), type="success")
            self.open_backup_folder()
        else:
            ErrorDialog(self.container.winfo_toplevel(), tr("admin.db.failed"), tr("admin.db.failed_msg").replace("{msg}", msg))

    def open_backup_folder(self):
        import os

        path = r"C:\RevenueSystem\backups\local"
        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showerror("Error", f"Backup folder not found at {path}")

    def restore_backup(self):
        from tkinter import filedialog, simpledialog
        
        # 1. Pick the file
        file_path = filedialog.askopenfilename(
            title=tr("admin.db.restore.title"),
            initialdir=r"C:\RevenueSystem\backups\local",
            filetypes=[("SQL Backup", "*.sql"), ("All Files", "*.*")]
        )
        
        if not file_path:
            return
            
        # 2. Critical Warning
        confirm = messagebox.askyesno(
            tr("admin.db.restore.warning"),
            tr("admin.db.restore.warning_msg"),
            icon="warning"
        )
        
        if not confirm:
            return
            
        # 3. Double-Lock Confirmation
        user_input = simpledialog.askstring(
            tr("admin.db.restore.verify"),
            tr("admin.db.restore.verify_msg"),
            parent=self.container
        )
        
        if user_input != "RESTORE":
            messagebox.showinfo(tr("admin.db.restore.cancelled"), tr("admin.db.restore.cancelled_msg"))
            return
            
        # 4. Trigger Restore
        self.restore_btn.configure(state="disabled", text="⏮️ RESTORING...")
        
        def run_restore():
            try:
                import api_clients.system_service as system_svc
                res = system_svc.restore_backup(file_path)
                
                if res.get("status") == "success":
                    data = res.get("data", {})
                    safety = data.get("safety_backup", "Unknown")
                    messagebox.showinfo(
                        tr("admin.db.restore.success_title"),
                        tr("admin.db.restore.success_msg").replace("{path}", file_path).replace("{safety}", safety)
                    )
                else:
                    messagebox.showerror("Restore Error", f"The server failed to restore: {res.get('detail', 'Unknown error')}")
            except Exception as e:
                messagebox.showerror("Disaster Recovery Error", f"CRITICAL FAILURE: {str(e)}")
            finally:
                if self.container.winfo_exists():
                    self.restore_btn.configure(state="normal", text="⏮️ RESTORE")

        import threading
        threading.Thread(target=run_restore, daemon=True).start()
