import os
import sys
import threading
import customtkinter as ctk
from datetime import datetime
from typing import Any, Optional, Dict
from PIL import Image
from pathlib import Path

# Add root folder to sys.path so nested desktop client scripts can import api_clients and utils seamlessly
BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import api_clients.auth_service as auth
import api_clients.property_service as prop
import api_clients.payment_service as payment
import api_clients.system_service as system
from theme_manager import setup_theme, ModernTheme
from ui_components import ModernChartWidget, show_toast, ErrorDialog
from utils import tr
from api_clients.sync_monitor import sync_monitor
from api_clients.offline_manager import manager


from ui.navigation import NavigationSidebar
from ui.status_bar import ConnectivityStatusBar
from ui.dashboard_home import DashboardHomePage
from ui.help_page import SystemHelpPage
from ui.watchdog import SessionWatchdog, show_session_expired_dialog
from ui.notifications import NotificationListener
from ui.conflict_resolver import ConflictArbitrationModal

# Ensure theme is loaded
setup_theme()



class DashboardApp(ctk.CTk):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data
        self.username = auth.get_username(user_data)
        self.logged_out = False

        # --- LOAD PERSISTED CONFIGURATION ---
        from utils import ConfigManager
        ConfigManager.load()
        appearance = ConfigManager.get("appearance_mode", "dark")
        ctk.set_appearance_mode(appearance)

        self.title(f"Treasury Management System | {self.username}")
        self.geometry("1400x850")
        
        # --- TASK TRACKING ---
        self.progress_overlays = {} # Track active progress windows
        self.resizable(True, True)
        self.minsize(1100, 700)

        # Key Bindings (Keyboard Shortcuts for UX)
        self.bind("<Control-f>", lambda e: self.open_command_palette())
        self.bind("<Control-p>", lambda e: self.open_command_palette())

        # Auto-Maximize (Fullscreen) on Startup
        self.after(0, lambda: self.state("zoomed"))

        # --- GLOBAL HOTKEYS ---
        self.bind("<Control-n>", lambda e: self.dispatch_hotkey("new"))
        self.bind("<Control-N>", lambda e: self.dispatch_hotkey("new"))
        self.bind("<Control-s>", lambda e: self.dispatch_hotkey("save"))
        self.bind("<Control-S>", lambda e: self.dispatch_hotkey("save"))
        self.bind("<Escape>", lambda e: self.dispatch_hotkey("cancel"))

        # Responsive Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.progress_overlays = {}

        # 1. Initialize Specialized Coordinators
        self.watchdog = SessionWatchdog(self, 60, self.logout_automatic)
        self.notifier = NotificationListener({
            "on_open": lambda: self.status_bar.set_ws_status(True),
            "on_close": lambda: self.status_bar.set_ws_status(False),
            "on_notification": self._handle_notification,
            "on_progress": self._handle_progress
        })
        
        # Phase 4: Sync Monitor with Conflict Arbitration
        sync_monitor.on_conflict = self._handle_sync_conflict

        self.setup_main_window()
        self.setup_ui()
        
        # 2. Launch Background Services
        self.watchdog.start_monitoring()
        self.notifier.start()
        sync_monitor.start()
        
        # 3. Initial State
        self.load_page(DashboardHomePage)

        # Bind Global Search
        self.bind("<Control-k>", lambda e: self.open_command_palette())
        self.bind("<Control-K>", lambda e: self.open_command_palette())
        
        # Bind global interactions to reset the watchdog
        self.bind_all("<Any-KeyPress>", lambda e: self.watchdog.reset())
        self.bind_all("<Any-Button>", lambda e: self.watchdog.reset())

    def setup_main_window(self):
        self.title(f"Municipal Revenue System | {self.username.upper()}")
        self.minsize(1200, 800)

        # Centre the dashboard on the screen
        win_w, win_h = 1400, 900
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = (screen_w - win_w) // 2
        y = (screen_h - win_h) // 2
        self.geometry(f"{win_w}x{win_h}+{x}+{y}")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

    def setup_ui(self):
        callbacks = {
            "load_page": self.load_page,
            "toggle_theme": self.toggle_theme,
            "toggle_language": self.toggle_language,
            "logout": self.logout
        }
        self.sidebar = NavigationSidebar(self, self.user_data, self.username, callbacks)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        self.main_area = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_area.grid(row=0, column=1, sticky="nsew")

        self.status_bar = ConnectivityStatusBar(self)
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")

    def load_page(self, page_class):
        try:
            for widget in self.main_area.winfo_children():
                widget.destroy()
            
            # Context-Aware Page Loading
            if page_class == DashboardHomePage:
                cb = {"trigger_backup": self.trigger_backup_action, "get_summary": system.get_dashboard_summary, "get_trend": payment.get_monthly_collection_trend}
                self.current_page = page_class(self.main_area, self.user_data, cb)
            else:
                self.current_page = page_class(self.main_area, self.user_data)
            
            self.watchdog.reset()
        except Exception as e:
            ErrorDialog(self, tr("common.system_error"), f"Failed to load page: {str(e)}")

    def _handle_sync_conflict(self, action_id, local_payload, server_snapshot):
        """Launches the arbitration UI on the main thread."""
        self.after(0, lambda: ConflictArbitrationModal(
            self, action_id, local_payload, server_snapshot, self._resolve_conflict_action
        ))

    def _resolve_conflict_action(self, action_id, resolution):
        """Processes the final arbitration decision from the modal."""
        from api_clients.offline_manager import manager
        if resolution == "LOCAL":
            show_toast(self, "Resolving: Overriding server with local version...", type="info")
        else:
            manager.resolve_conflict(action_id, resolution="DISCARD")
            show_toast(self, "Resolving: Discarded local version. Using server data.", type="success")

    def trigger_backup_action(self):
        try:
            res = system.trigger_backup()
            job_id = res.get("job_id") if isinstance(res, dict) else None
            show_toast(
                self,
                res.get("message", tr("dashboard.backup.success_toast")) if isinstance(res, dict) else tr("dashboard.backup.success_toast"),
                type="info",
            )
            if job_id:
                threading.Thread(
                    target=self._poll_backup_job,
                    args=(job_id,),
                    daemon=True,
                ).start()
        except Exception as e:
            ErrorDialog(self, "Backup Error", str(e))

    def _poll_backup_job(self, job_id: str):
        """Poll backup job until completion and refresh dashboard status."""
        import time

        for _ in range(180):  # up to ~15 minutes at 5s intervals
            time.sleep(5)
            try:
                job = system.get_job_status(job_id)
            except Exception:
                continue
            if not job:
                continue

            status = job.get("status")
            if status == "COMPLETED":
                msg = (job.get("result") or {}).get("message", "Backup completed successfully.")
                self.after(0, lambda m=msg: show_toast(self, m, type="success"))
                self.after(0, self._refresh_dashboard_if_active)
                return
            if status == "FAILED":
                err = job.get("error") or job.get("progress_message") or "Backup failed."
                self.after(0, lambda e=err: ErrorDialog(self, "Backup Failed", e))
                self.after(0, self._refresh_dashboard_if_active)
                return

        self.after(
            0,
            lambda: show_toast(
                self,
                "Backup is still running. Refresh the dashboard in a few minutes.",
                type="warning",
            ),
        )

    def _refresh_dashboard_if_active(self):
        from ui.dashboard_home import DashboardHomePage

        if isinstance(getattr(self, "current_page", None), DashboardHomePage):
            self.current_page.start_data_refresh()

    def _handle_notification(self, data):
        self.after(0, lambda: show_toast(self, f"🔔 {data.get('title')}: {data.get('message')}", type=data.get("level", "info")))

    def _handle_progress(self, data):
        """Thread-safe handler for background task progress updates."""
        def update_ui():
            from ui_components import ProgressOverlay
            module = data.get("module", "system")
            if module not in self.progress_overlays:
                self.progress_overlays[module] = ProgressOverlay(self, title=f"{module.upper()} TASK")
            
            percentage = data.get("percentage", 0)
            message = data.get("message", "Processing...")
            
            self.progress_overlays[module].update(percentage, message)
            
            if percentage >= 100:
                # Keep it visible for a moment before clearing
                self.after(3000, lambda: self.progress_overlays.pop(module, None).destroy() if module in self.progress_overlays else None)
        
        self.after(0, update_ui)

    def open_command_palette(self):
        CommandPalette(self, self.user_data, self.handle_palette_selection)

    def handle_palette_selection(self, result):
        res_type, identifier, command = result.get("type"), result.get("identifier"), result.get("command")
        
        if res_type == "property":
            from ui.dossier import PropertyDossierWindow
            PropertyDossierWindow(self, identifier, self.user_data)
        elif res_type == "receipt":
            from ui.ledger import LedgerPage
            self.load_page(LedgerPage)
        elif res_type == "action":
            self._handle_palette_action(command)

    def _handle_palette_action(self, command):
        mapping = {
            "action:backup": self.trigger_backup_action,
            "nav:new_property": lambda: [self.load_page(__import__("ui.property", fromlist=["PropertyPage"]).PropertyPage)],
            "nav:users": lambda: [self.load_page(__import__("ui.system_admin", fromlist=["SystemAdminPage"]).SystemAdminPage)],
            "nav:reports": lambda: [self.load_page(__import__("ui.reports", fromlist=["ReportsPage"]).ReportsPage)]
        }
        if command in mapping: mapping[command]()

    def toggle_theme(self):
        current = ctk.get_appearance_mode()
        new_mode = "light" if current == "Dark" else "dark"

        # Save window state so withdraw/deiconify doesn't exit fullscreen/zoomed.
        win_state = self.state()
        self.withdraw()
        try:
            setup_theme(new_mode)
            from utils import ConfigManager
            ConfigManager.set("appearance_mode", new_mode)
            self.update_idletasks()
        finally:
            self.deiconify()
            if win_state == "zoomed":
                self.state("zoomed")

    def toggle_language(self):
        from utils import LocalizationManager
        mgr = LocalizationManager()
        mgr.set_locale("tl" if mgr._current_locale == "en" else "en")

        # Save window state so withdraw/deiconify doesn't exit fullscreen/zoomed.
        win_state = self.state()
        self.withdraw()
        try:
            self.sidebar.destroy()
            callbacks = {"load_page": self.load_page, "toggle_theme": self.toggle_theme, "toggle_language": self.toggle_language, "logout": self.logout}
            self.sidebar = NavigationSidebar(self, self.user_data, self.username, callbacks)
            self.sidebar.grid(row=0, column=0, sticky="nsew")
            self.load_page(DashboardHomePage)
            self.update_idletasks()
        finally:
            self.deiconify()
            if win_state == "zoomed":
                self.state("zoomed")

    def logout(self):
        """Shows a premium custom logout confirmation dialog instead of the OS native dialog."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        dialog.overrideredirect(True)  # Borderless for premium feel

        # Size and center over the main window
        dw, dh = 420, 200
        px = self.winfo_rootx() + (self.winfo_width() // 2) - (dw // 2)
        py = self.winfo_rooty() + (self.winfo_height() // 2) - (dh // 2)
        dialog.geometry(f"{dw}x{dh}+{px}+{py}")

        # Outer frame with border
        outer = ctk.CTkFrame(
            dialog,
            fg_color=("#1e2530", "#1e2530"),
            corner_radius=16,
            border_width=1,
            border_color=("#2c3e50", "#2c3e50"),
        )
        outer.pack(fill="both", expand=True, padx=2, pady=2)

        # Icon + message row
        msg_fr = ctk.CTkFrame(outer, fg_color="transparent")
        msg_fr.pack(fill="x", padx=28, pady=(28, 16))

        # Red logout icon circle
        icon_fr = ctk.CTkFrame(
            msg_fr, width=48, height=48, corner_radius=24,
            fg_color="#e74c3c",
        )
        icon_fr.pack(side="left", padx=(0, 16))
        icon_fr.pack_propagate(False)
        ctk.CTkLabel(
            icon_fr, text="⏻", font=("Segoe UI", 20, "bold"), text_color="white"
        ).place(relx=0.5, rely=0.5, anchor="center")

        text_fr = ctk.CTkFrame(msg_fr, fg_color="transparent")
        text_fr.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(
            text_fr,
            text=tr("common.logout_confirm"),
            font=("Segoe UI", 15, "bold"),
            text_color="white",
            anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            text_fr,
            text=tr("common.logout_msg"),
            font=("Segoe UI", 11),
            text_color="gray60",
            anchor="w",
            wraplength=260,
        ).pack(fill="x", pady=(4, 0))

        # Divider
        ctk.CTkFrame(outer, height=1, fg_color="#2c3e50").pack(fill="x", padx=0)

        # Button row
        btn_fr = ctk.CTkFrame(outer, fg_color="transparent")
        btn_fr.pack(fill="x", padx=20, pady=16)

        def confirm():
            dialog.destroy()
            auth.logout()
            self.logged_out = True
            self.destroy()

        def cancel():
            dialog.destroy()

        ctk.CTkButton(
            btn_fr,
            text="Cancel",
            command=cancel,
            fg_color=("#2c3e50", "#2c3e50"),
            hover_color=("#34495e", "#34495e"),
            text_color="white",
            font=("Segoe UI", 12, "bold"),
            height=38,
            corner_radius=8,
            width=120,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_fr,
            text="  ⏻  Log Out",
            command=confirm,
            fg_color="#e74c3c",
            hover_color="#c0392b",
            text_color="white",
            font=("Segoe UI", 12, "bold"),
            height=38,
            corner_radius=8,
            width=140,
        ).pack(side="right")

        # Allow Escape to cancel, Enter/Space to confirm
        dialog.bind("<Escape>", lambda e: cancel())
        dialog.bind("<Return>", lambda e: confirm())
        dialog.bind("<space>", lambda e: confirm())
        # Force keyboard focus to the dialog so bindings fire immediately
        dialog.focus_set()

    def logout_automatic(self):
        auth.logout()
        self.logged_out = True
        expired_win = ctk.CTkToplevel(self)
        expired_win.title(tr("common.session_expired_title"))
        expired_win.geometry("450x250")
        expired_win.attributes("-topmost", True)
        expired_win.grab_set()
        expired_win.update_idletasks()
        x, y = self.winfo_x() + (self.winfo_width() // 2) - 225, self.winfo_y() + (self.winfo_height() // 2) - 125
        expired_win.geometry(f"+{x}+{y}")
        content = ctk.CTkFrame(expired_win, fg_color="transparent")
        content.pack(expand=True, fill="both", padx=30, pady=30)
        ctk.CTkLabel(content, text="🚨 " + tr("common.session_expired_title"), font=("Segoe UI", 20, "bold"), text_color="#e74c3c").pack(pady=(0, 10))
        ctk.CTkLabel(content, text=tr("common.session_expired_msg"), font=("Segoe UI", 12), wraplength=350).pack(pady=10)
        ctk.CTkButton(content, text=tr("common.ok"), command=self.destroy, fg_color="#e74c3c", hover_color="#c0392b", width=120).pack(pady=(15, 0))

    def open_sync_manager(self):
        """Opens a modal to view and manage the offline sync queue."""
        pending = manager.get_pending_actions(include_conflicts=True)
        if not pending:
            show_toast(self, "Offline queue is empty.", "info")
            return
            
        modal = ctk.CTkToplevel(self)
        modal.title("📊 SYNC QUEUE MANAGER")
        modal.geometry("700x500")
        modal.attributes("-topmost", True)
        modal.grab_set()
        
        modal.update_idletasks()
        
        scroll = ctk.CTkScrollableFrame(modal)
        scroll.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Ensure scroll frame is ready before adding children
        modal.update_idletasks()
        
        if not pending:
            ctk.CTkLabel(scroll, text="No pending synchronizations found.").pack(pady=20)
            return

        for item in pending:
            frame = ctk.CTkFrame(master=scroll)
            frame.pack(fill="x", pady=5, padx=5)
            
            # Identify if it's a conflict
            is_conflict = item.get("status") == "CONFLICT"
            
            method_lbl = ctk.CTkLabel(frame, text=f"{item.get('method', 'REQ')} {item.get('endpoint', '')}", font=("Segoe UI", 12, "bold"))
            method_lbl.pack(side="left", padx=15, pady=12)
            
            if is_conflict:
                res_btn = ctk.CTkButton(frame, text="RESOLVE CONFLICT", width=140, fg_color="#e67e22", hover_color="#d35400",
                             command=lambda i=item: self._resolve_manual(i, modal))
                res_btn.pack(side="right", padx=15)
            else:
                status_lbl = ctk.CTkLabel(frame, text="PENDING SYNC", text_color="#3498db", font=("Segoe UI", 10, "bold"))
                status_lbl.pack(side="right", padx=15)

    def _resolve_manual(self, item, parent_modal):
        """Opens the arbitration modal for a specific item."""
        parent_modal.destroy()
        from ui.conflict_resolver import ConflictArbitrationModal
        ConflictArbitrationModal(
            self, 
            item["id"], 
            item["payload"], 
            {"info": "Conflict detected during background sync. Server state has diverged."},
            self._handle_resolution_callback
        )

    def _handle_resolution_callback(self, action_id, resolution):
        """Bridge for manual resolution from the Sync Manager."""
        from api_clients.offline_manager import manager
        if resolution == "LOCAL":
            manager.resolve_conflict(action_id, resolution="LOCAL")
            show_toast(self, "Resolved: Local version forced.", "success")
        else:
            manager.resolve_conflict(action_id, resolution="DISCARD")
            show_toast(self, "Resolved: Local version discarded.", "info")

def open_dashboard(user_data):
    app = DashboardApp(user_data)
    app.mainloop()
    return getattr(app, "logged_out", False)


class SystemHelpPage:
    def __init__(self, parent, user_data=None):
        self.container = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        ctk.CTkLabel(
            self.container,
            text="MTO Treasury System Help Guide",
            font=("Segoe UI", 28, "bold"),
            text_color="#3498db",
        ).pack(anchor="w", pady=(0, 20))

        help_text = [
            ("🏠 Dashboard", "View real-time revenue collection charts and protection status."),
            ("📋 Property Records", "Search, edit, or delete property assessments. Use the 'Export' button to save to Excel."),
            ("🏦 Unified Ledger", "View all payment history. Use 'View Receipt' to open a PDF copy."),
            ("⌨️ Shortcuts", "Ctrl+F: Quick Search | Ctrl+P: Command Palette | Ctrl+K: Global Search"),
            ("🛡️ Data Protection", "The 'Restore Test' on the dashboard verifies that your backups are 100% healthy."),
            ("💼 Audit Trail", "Administrators can view all changes made to any record in the System Settings."),
        ]

        for title, desc in help_text:
            f = ctk.CTkFrame(self.container, fg_color=("#ebebeb", "#262626"), corner_radius=10)
            f.pack(fill="x", pady=8, padx=5)
            ctk.CTkLabel(f, text=title, font=("Segoe UI", 16, "bold"), text_color="#3498db").pack(anchor="w", padx=15, pady=(10, 2))
            ctk.CTkLabel(f, text=desc, font=("Segoe UI", 12), wraplength=700, justify="left").pack(anchor="w", padx=15, pady=(0, 15))

    def _handle_resolution(self, action_id, choice):
        if choice == "LOCAL":
            # In a full implementation, this would reset the status to 'PENDING'
            # For now, we'll just acknowledge the user's intent
            show_toast(self, "Retrying with local data...", "info")
        else:
            manager.mark_as_synced(action_id)
            show_toast(self, "Conflict discarded. Using server version.", "success")
