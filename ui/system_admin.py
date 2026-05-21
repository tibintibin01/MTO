import customtkinter as ctk
from tkinter import messagebox
import api_clients.auth_service as auth
from ui.users import UserAccessPage
from ui.logs import AuditLogsPage
from ui.recycle import RecycleBinPage
from theme_manager import ModernTheme
from utils import tr

# Module-level variable — survives page navigation because the module
# stays loaded even when SystemAdminPage is destroyed and recreated.
_active_sync_job_id: str | None = None


# ---------------------------------------------------------------------------
# Premium dialog helpers used by the DB tab
# ---------------------------------------------------------------------------

def _make_premium_dialog(parent, width=460, height=None):
    """Creates a borderless, dark, centered CTkToplevel."""
    dialog = ctk.CTkToplevel(parent)
    dialog.title("")
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    dialog.grab_set()
    dialog.overrideredirect(True)

    dialog.update_idletasks()
    dw = width
    dh = height or 260
    px = parent.winfo_rootx() + (parent.winfo_width() // 2) - (dw // 2)
    py = parent.winfo_rooty() + (parent.winfo_height() // 2) - (dh // 2)
    dialog.geometry(f"{dw}x{dh}+{px}+{py}")

    outer = ctk.CTkFrame(
        dialog,
        fg_color=("#1e2530", "#1e2530"),
        corner_radius=16,
        border_width=1,
        border_color=("#2c3e50", "#2c3e50"),
    )
    outer.pack(fill="both", expand=True, padx=2, pady=2)
    return dialog, outer


def _show_sync_info(parent, scanned, created, skipped):
    """Premium 'nothing to do' info dialog."""
    dialog, outer = _make_premium_dialog(parent, width=400, height=220)

    body = ctk.CTkFrame(outer, fg_color="transparent")
    body.pack(fill="x", padx=24, pady=(24, 16))

    icon_fr = ctk.CTkFrame(body, width=48, height=48, corner_radius=24, fg_color="#27ae60")
    icon_fr.pack(side="left", padx=(0, 16))
    icon_fr.pack_propagate(False)
    ctk.CTkLabel(icon_fr, text="✓", font=("Segoe UI", 22, "bold"), text_color="white").place(relx=0.5, rely=0.5, anchor="center")

    text_fr = ctk.CTkFrame(body, fg_color="transparent")
    text_fr.pack(side="left", fill="both", expand=True)
    ctk.CTkLabel(text_fr, text="Already Up to Date", font=("Segoe UI", 14, "bold"), text_color="white", anchor="w").pack(fill="x")
    ctk.CTkLabel(text_fr, text=f"All {scanned:,} properties have complete billing records.\nNo new records needed.", font=("Segoe UI", 10), text_color="#8b949e", anchor="w", justify="left").pack(fill="x", pady=(4, 0))

    ctk.CTkFrame(outer, height=1, fg_color="#2c3e50").pack(fill="x")
    btn_fr = ctk.CTkFrame(outer, fg_color="transparent")
    btn_fr.pack(fill="x", padx=20, pady=14)
    ctk.CTkButton(btn_fr, text="OK", command=dialog.destroy, fg_color="#27ae60", hover_color="#2ecc71", text_color="white", font=("Segoe UI", 12, "bold"), height=36, corner_radius=8, width=100).pack(side="right")
    dialog.bind("<Return>", lambda e: dialog.destroy())
    dialog.bind("<Escape>", lambda e: dialog.destroy())
    dialog.focus_set()


def _show_sync_confirm(parent, scanned, created, skipped, on_confirm):
    """Premium sync confirmation dialog with stats."""
    dialog, outer = _make_premium_dialog(parent, width=460, height=300)

    # Header row
    header = ctk.CTkFrame(outer, fg_color="transparent")
    header.pack(fill="x", padx=24, pady=(22, 0))

    icon_fr = ctk.CTkFrame(header, width=52, height=52, corner_radius=26, fg_color="#8e44ad", border_width=2, border_color="#9b59b6")
    icon_fr.pack(side="left", padx=(0, 16))
    icon_fr.pack_propagate(False)
    ctk.CTkLabel(icon_fr, text="📅", font=("Segoe UI Emoji", 22), text_color="white").place(relx=0.5, rely=0.5, anchor="center")

    title_fr = ctk.CTkFrame(header, fg_color="transparent")
    title_fr.pack(side="left", fill="both", expand=True)
    ctk.CTkLabel(title_fr, text="Billing Year Sync", font=("Segoe UI", 15, "bold"), text_color="white", anchor="w").pack(fill="x")
    ctk.CTkLabel(title_fr, text="Preview of changes before committing", font=("Segoe UI", 10), text_color="#8b949e", anchor="w").pack(fill="x", pady=(2, 0))

    # Stats cards
    stats_fr = ctk.CTkFrame(outer, fg_color="#161b22", corner_radius=10)
    stats_fr.pack(fill="x", padx=20, pady=14)
    stats_fr.grid_columnconfigure((0, 1, 2), weight=1)

    def stat_card(parent, col, label, value, color):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=0, column=col, padx=8, pady=10, sticky="nsew")
        ctk.CTkLabel(f, text=f"{value:,}", font=("Segoe UI", 18, "bold"), text_color=color).pack()
        ctk.CTkLabel(f, text=label, font=("Segoe UI", 9), text_color="#8b949e").pack()

    stat_card(stats_fr, 0, "Properties", scanned, "#3498db")
    stat_card(stats_fr, 1, "To Create", created, "#e67e22")
    stat_card(stats_fr, 2, "Skipped", skipped, "#27ae60")

    ctk.CTkLabel(outer, text=f"This will create {created:,} missing billing records covering\nunpaid years for {scanned:,} properties. This cannot be undone.", font=("Segoe UI", 10), text_color="#8b949e", justify="center").pack(padx=20, pady=(0, 10))

    ctk.CTkFrame(outer, height=1, fg_color="#2c3e50").pack(fill="x")
    btn_fr = ctk.CTkFrame(outer, fg_color="transparent")
    btn_fr.pack(fill="x", padx=20, pady=14)

    def cancel():
        dialog.destroy()

    def confirm():
        dialog.destroy()
        on_confirm()

    ctk.CTkButton(btn_fr, text="Cancel", command=cancel, fg_color="#2c3e50", hover_color="#34495e", text_color="white", font=("Segoe UI", 12, "bold"), height=36, corner_radius=8, width=110).pack(side="right", padx=(8, 0))
    ctk.CTkButton(btn_fr, text="  📅  Proceed", command=confirm, fg_color="#8e44ad", hover_color="#9b59b6", text_color="white", font=("Segoe UI", 12, "bold"), height=36, corner_radius=8, width=140).pack(side="right")

    dialog.bind("<Return>", lambda e: confirm())
    dialog.bind("<space>", lambda e: confirm())
    dialog.bind("<Escape>", lambda e: cancel())
    dialog.focus_set()


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

        # Restart Server button — lets admin apply updates from any client PC
        # without needing physical access to the server machine.
        self.restart_btn = ctk.CTkButton(
            btn_fr,
            text="🔄 RESTART SERVER",
            command=self.restart_server,
            height=45,
            width=180,
            font=ModernTheme.BUTTON,
            fg_color="#c0392b",
            hover_color="#e74c3c",
        )
        self.restart_btn.pack(side="left", padx=5)

        self.sync_btn = ctk.CTkButton(
            btn_fr,
            text="📅 SYNC BILLING YEARS",
            command=self.sync_billing_years,
            height=45,
            width=200,
            font=ModernTheme.BUTTON,
            fg_color="#8e44ad",
            hover_color="#9b59b6",
        )
        self.sync_btn.pack(side="left", padx=5)

        # If a sync was running when the user navigated away, resume monitoring
        if _active_sync_job_id:
            self.sync_btn.configure(state="disabled", text="⏳ SYNCING...")
            import threading
            threading.Thread(
                target=self._resume_sync_monitoring,
                args=(_active_sync_job_id,),
                daemon=True
            ).start()

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
        import subprocess
        import sys

        # Read from the same env var used by backup_service so the path
        # is consistent regardless of where the desktop app is installed.
        backup_base = os.getenv(
            "MTO_BACKUP_DIR",
            os.path.join(os.path.expanduser("~"), "mto_backups"),
        )
        path = os.path.join(backup_base, "local")

        if not os.path.exists(path):
            messagebox.showerror("Error", f"Backup folder not found:\n{path}")
            return

        # Open the folder in the platform's file manager
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def restore_backup(self):
        from tkinter import filedialog, simpledialog
        import os

        backup_base = os.getenv(
            "MTO_BACKUP_DIR",
            os.path.join(os.path.expanduser("~"), "mto_backups"),
        )
        initial_dir = os.path.join(backup_base, "local")

        # 1. Pick the file
        file_path = filedialog.askopenfilename(
            title=tr("admin.db.restore.title"),
            initialdir=initial_dir if os.path.exists(initial_dir) else os.path.expanduser("~"),
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

    def restart_server(self):
        """
        Sends a restart command to the backend server.
        Use this after copying updated files to the server PC via the
        shared network folder — no physical access to the server needed.
        """
        confirm = messagebox.askyesno(
            "Restart Server",
            "This will restart the backend server.\n\n"
            "All connected users will be disconnected for ~10 seconds.\n\n"
            "Make sure you have copied your updated files first.\n\n"
            "Continue?",
            icon="warning"
        )
        if not confirm:
            return

        self.restart_btn.configure(state="disabled", text="⏳ RESTARTING...")

        def run():
            try:
                import api_clients.system_service as system_svc
                res = system_svc.restart_server()
                msg = res.get("message", "Server is restarting...")
                self.container.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Restart Initiated",
                        f"{msg}\n\nThe app will reconnect automatically.\n"
                        "If it doesn't, close and reopen the desktop app."
                    )
                )
            except Exception as e:
                # A connection error here is expected — the server shut down
                # before it could send a full response.
                err = str(e)
                if "Connection" in err or "refused" in err.lower() or "reset" in err.lower():
                    self.container.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Restart Initiated",
                            "Server is restarting.\n\n"
                            "Wait 10 seconds then the app will reconnect."
                        )
                    )
                else:
                    self.container.after(
                        0,
                        lambda: messagebox.showerror("Restart Error", err)
                    )
            finally:
                if self.container.winfo_exists():
                    self.container.after(
                        0,
                        lambda: self.restart_btn.configure(
                            state="normal", text="🔄 RESTART SERVER"
                        )
                    )

        import threading
        threading.Thread(target=run, daemon=True).start()

    def sync_billing_years(self):
        """
        Syncs missing billing year records for all properties.
        First runs a dry-run preview, then asks for confirmation before committing.
        """
        import threading
        import api_clients.system_service as system_svc

        self.sync_btn.configure(state="disabled", text="🔍 PREVIEWING...")

        def preview():
            try:
                # Dry run first — show what will be created
                res = system_svc.sync_billing_years(dry_run=True)
                created = res.get("records_created", 0)
                scanned = res.get("properties_scanned", 0)
                skipped = res.get("records_skipped", 0)

                msg = (
                    f"Billing Year Sync Preview\n\n"
                    f"Properties scanned:    {scanned}\n"
                    f"Records to create:     {created}\n"
                    f"Already exist (skip):  {skipped}\n\n"
                )

                if created == 0:
                    # Nothing to do — show a simple premium info dialog
                    self.container.after(0, lambda: _show_sync_info(
                        self.container.winfo_toplevel(),
                        scanned, created, skipped
                    ))
                    return

                def confirm_and_run():
                    _show_sync_confirm(
                        self.container.winfo_toplevel(),
                        scanned, created, skipped,
                        on_confirm=lambda: (
                            self.sync_btn.configure(text="⏳ SYNCING..."),
                            threading.Thread(target=run_live, daemon=True).start()
                        )
                    )

                self.container.after(0, confirm_and_run)

            except Exception as e:
                self.container.after(
                    0, lambda: messagebox.showerror("Sync Error", str(e))
                )
            finally:
                if self.container.winfo_exists():
                    self.container.after(
                        0,
                        lambda: self.sync_btn.configure(
                            state="normal", text="📅 SYNC BILLING YEARS"
                        )
                    )

        def run_live():
            global _active_sync_job_id
            try:
                res = system_svc.sync_billing_years(dry_run=False)

                if "job_id" in res:
                    job_id = res["job_id"]
                    _active_sync_job_id = job_id  # persist across navigation
                    self._resume_sync_monitoring(job_id)
                else:
                    _active_sync_job_id = None
                    created = res.get("records_created", 0)
                    try:
                        top = self.parent.winfo_toplevel()
                        top.after(0, lambda c=created: messagebox.showinfo(
                            "Sync Complete",
                            f"✅ Billing sync complete!\n\n{c} billing records created.\n\n"
                            f"The Delinquency Dashboard will now show\nthe correct multi-year balances."
                        ))
                    except Exception:
                        pass
            except Exception as e:
                _active_sync_job_id = None
                try:
                    top = self.parent.winfo_toplevel()
                    top.after(0, lambda err=str(e): messagebox.showerror("Sync Error", err))
                except Exception:
                    pass
            finally:
                _active_sync_job_id = None
                try:
                    if self.container.winfo_exists():
                        self.container.after(0, lambda: self.sync_btn.configure(
                            state="normal", text="📅 SYNC BILLING YEARS"
                        ))
                except Exception:
                    pass

        threading.Thread(target=preview, daemon=True).start()

    def _resume_sync_monitoring(self, job_id: str):
        """
        Polls a running sync job until it completes.
        Called both when a new sync starts AND when the user navigates back
        to System Settings while a sync is already in progress.
        """
        global _active_sync_job_id
        import time
        import api_clients.system_service as system_svc

        while True:
            status = system_svc.get_job_status(job_id)
            if not status:
                break

            job_status = status.get("status")

            if job_status == "COMPLETED":
                _active_sync_job_id = None
                result = status.get("result") or {}
                created = result.get("records_created", 0)
                try:
                    top = self.parent.winfo_toplevel()
                    top.after(0, lambda c=created: messagebox.showinfo(
                        "Sync Complete",
                        f"✅ Billing sync complete!\n\n{c} billing records created.\n\n"
                        f"The Delinquency Dashboard will now show\nthe correct multi-year balances."
                    ))
                except Exception:
                    pass
                break

            elif job_status == "FAILED":
                _active_sync_job_id = None
                err = status.get("error", "Unknown error")
                try:
                    top = self.parent.winfo_toplevel()
                    top.after(0, lambda e=err: messagebox.showerror("Sync Failed", e))
                except Exception:
                    pass
                break

            time.sleep(2)

        # Reset button when done
        _active_sync_job_id = None
        try:
            if self.container.winfo_exists():
                self.container.after(0, lambda: self.sync_btn.configure(
                    state="normal", text="📅 SYNC BILLING YEARS"
                ))
        except Exception:
            pass
