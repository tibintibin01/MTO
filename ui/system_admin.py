import customtkinter as ctk
from tkinter import messagebox
import api_clients.auth_service as auth
from ui.users import UserAccessPage
from ui.logs import AuditLogsPage
from ui.recycle import RecycleBinPage
from theme_manager import ModernTheme

class SystemAdminPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.pages = []
        self.setup_ui()

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(self.container, text="SYSTEM ADMINISTRATION", font=ModernTheme.H2).pack(anchor="w", pady=(0, 20))

        self.tabview = ctk.CTkTabview(self.container)
        self.tabview.pack(fill="both", expand=True)

        # User Management
        if auth.has_permission(self.user, "manage_users"):
            tab = self.tabview.add("User Management")
            self.user_page = UserAccessPage(tab, self.user)
            self.pages.append(self.user_page)

        # Audit Logs
        if auth.has_permission(self.user, "view_logs"):
            tab = self.tabview.add("Audit Logs")
            self.logs_page = AuditLogsPage(tab, self.user)
            self.pages.append(self.logs_page)

        # Recycle Bin
        if auth.has_permission(self.user, "recycle_manage"):
            tab = self.tabview.add("Recycle Bin")
            self.recycle_page = RecycleBinPage(tab, self.user)
            self.pages.append(self.recycle_page)

        # Database Tab
        if auth.has_permission(self.user, "backup_restore"):
            tab = self.tabview.add("Database & Backup")
            self.setup_db_tab(tab)

    def setup_db_tab(self, parent):
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=40, pady=20)

        # Main Action Card
        card = ctk.CTkFrame(container, fg_color=("#ffffff", "#2b2b2b"), corner_radius=15, border_width=1, border_color=("#e0e0e0", "#333333"))
        card.pack(fill="x", pady=10)
        
        ctk.CTkLabel(card, text="HYBRID BACKUP ORCHESTRATOR", font=("Segoe UI", 16, "bold"), text_color=("#1f538d", "#3498db")).pack(pady=(20, 5))
        ctk.CTkLabel(card, text="Secures your database to Local Storage, USB Drive, and Cloud Sync.", font=("Segoe UI", 11), text_color=("#7f8c8d", "#bdc3c7")).pack(pady=(0, 20))
        
        btn_fr = ctk.CTkFrame(card, fg_color="transparent")
        btn_fr.pack(pady=(0, 30))
        
        self.backup_btn = ctk.CTkButton(btn_fr, text="🚀 START HYBRID BACKUP", command=self.trigger_backup, 
                                        height=45, width=220, font=("Segoe UI", 12, "bold"), fg_color="#27ae60", hover_color="#219150")
        self.backup_btn.pack(side="left", padx=5)
        
        self.view_btn = ctk.CTkButton(btn_fr, text="📁 VIEW BACKUPS", command=self.open_backup_folder,
                                       height=45, width=150, font=("Segoe UI", 12, "bold"), fg_color="#34495e")
        self.view_btn.pack(side="left", padx=5)

        self.restore_btn = ctk.CTkButton(btn_fr, text="⏮️ RESTORE", command=self.restore_backup, 
                                         height=45, width=120, font=("Segoe UI", 12, "bold"), fg_color="#7f8c8d")
        self.restore_btn.pack(side="left", padx=5)
 
        # Status Panel
        status_fr = ctk.CTkFrame(container, fg_color=("#f8f9fa", "#1e1e1e"), corner_radius=12)
        status_fr.pack(fill="both", expand=True, pady=10)
        
        ctk.CTkLabel(status_fr, text="BACKUP ECOSYSTEM STATUS", font=("Segoe UI", 11, "bold"), text_color=("#2f3640", "#ecf0f1")).pack(anchor="w", padx=20, pady=(15, 10))
        
        self.status_labels = {}
        status_items = [
            ("Local SQL Dump", "last_local"),
            ("USB Drive Mirror", "last_usb"),
            ("Cloud Synchronization", "last_cloud"),
            ("Data Integrity Check", "last_verify")
        ]
        
        for label, key in status_items:
            row = ctk.CTkFrame(status_fr, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=5)
            # Use dynamic text color for the label
            ctk.CTkLabel(row, text=label, font=("Segoe UI", 11), text_color=("#2c3e50", "#ecf0f1")).pack(side="left")
            self.status_labels[key] = ctk.CTkLabel(row, text="Scanning...", font=("Segoe UI", 11, "bold"), text_color=("#34495e", "#bdc3c7"))
            self.status_labels[key].pack(side="right")
            
        self.update_status_display()

    def update_status_display(self):
        import backend.services.backup_service as backup_svc
        status = backup_svc.get_backup_status()
        for key, lbl in self.status_labels.items():
            val = status.get(key, "Unknown")
            color = "#27ae60" if "Success" in val or ":" in val else "#e67e22"
            lbl.configure(text=val, text_color=color)

    def trigger_backup(self):
        import backend.services.backup_service as backup_svc
        import threading
        
        if self.backup_btn.cget("state") == "disabled": return
        
        self.backup_btn.configure(state="disabled", text="🛡️ BACKUP IN PROGRESS...", fg_color="#95a5a6")
        
        def run():
            try:
                success, msg = backup_svc.run_hybrid_backup(user=self.user)
                # Check if the UI still exists before updating
                if self.container.winfo_exists():
                    self.container.after(0, lambda: self._finalize_backup(success, msg))
            except Exception as e:
                err_msg = str(e)
                try:
                    if self.container.winfo_exists():
                        self.container.after(0, lambda: self._finalize_backup(False, f"Thread Crash: {err_msg}"))
                except:
                    pass
            finally:
                import db_manager as db
                db.close_thread_connection()
            
        threading.Thread(target=run, daemon=True).start()

    def _finalize_backup(self, success, msg):
        self.backup_btn.configure(state="normal", text="🚀 START HYBRID BACKUP", fg_color="#27ae60")
        self.update_status_display()
        if success:
            messagebox.showinfo("Backup Success", "🎉 All systems secured!\n\nLocation: C:\\MTO\\backups\\local\n\n1. Local SQL Dump Created\n2. USB Drive Synced\n3. Cloud Push Completed")
            self.open_backup_folder()
        else:
            messagebox.showerror("Backup Failed", f"Critical Error: {msg}")

    def open_backup_folder(self):
        import os
        path = r"C:\MTO\backups\local"
        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showerror("Error", f"Backup folder not found at {path}")

    def restore_backup(self):
        messagebox.showwarning("Access Restricted", "Restoring a database is a high-risk operation.\n\nPlease contact System Support to verify the SQL manifest.")
