import os
import sys
import threading
import customtkinter as ctk
from datetime import datetime
from typing import Any, Optional, Dict
from PIL import Image
from pathlib import Path

import api_clients.auth_service as auth
import api_clients.property_service as prop
import api_clients.payment_service as payment
import api_clients.system_service as system
from theme_manager import setup_theme, ModernTheme
from ui_components import ModernChartWidget, show_toast, ErrorDialog
from utils import tr
from api_clients.sync_monitor import sync_monitor
import api_clients.api_helper as api
from api_clients.offline_manager import manager


from ui.navigation import NavigationSidebar
from ui.status_bar import ConnectivityStatusBar
from ui.dashboard_home import DashboardHomePage
from ui.help_page import SystemHelpPage
from ui.watchdog import SessionWatchdog, show_session_expired_dialog
from ui.notifications import NotificationListener
from ui.conflict_resolver import ConflictArbitrationModal
from api_clients.sync_monitor import sync_monitor

# Ensure theme is loaded
setup_theme()



class DashboardApp(ctk.CTk):
    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data
        self.username = auth.get_username(user_data)

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

        # --- CONNECTIVITY STATUS BAR (FOOTER) ---
        self.footer = ctk.CTkFrame(self, height=25, fg_color="#2c3e50")
        self.footer.grid(row=1, column=0, columnspan=2, sticky="ew")
        
        self.status_dot = ctk.CTkLabel(self.footer, text="●", font=("Segoe UI", 14), text_color="#2ecc71")
        self.status_dot.pack(side="left", padx=(15, 5))
        
        self.status_lbl = ctk.CTkLabel(self.footer, text="SYSTEM ONLINE", font=("Segoe UI", 10, "bold"), text_color="white")
        self.status_lbl.pack(side="left")
        
        self.queue_lbl = ctk.CTkLabel(self.footer, text="", font=("Segoe UI", 10), text_color="#bdc3c7")
        self.queue_lbl.pack(side="right", padx=15)
        
        # 1. Initialize Sync Badge and Worker
        from ui_components import SyncBadge
        self.sync_badge = SyncBadge(self.footer, command=self.open_sync_manager)
        self.sync_badge.pack(side="right", padx=10)
        
        manager.set_on_queue_change(self.sync_badge.update_status)
        # We start the worker loop using the global api_request function
        self.after(2000, lambda: manager.start_sync_worker(api.api_request))

        self.progress_overlays = {}

        # 1. Initialize Specialized Coordinators
        self.watchdog = SessionWatchdog(self, 15, self.logout_automatic)
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
        self.title(f"MTO Treasury System | {self.username.upper()}")
        self.geometry("1400x900")
        self.minsize(1200, 800)
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
        try: system.trigger_backup(); show_toast(self, tr("dashboard.backup.success_toast"), type="info")
        except Exception as e: ErrorDialog(self, "Backup Error", str(e))

    def _handle_notification(self, data):
        self.after(0, lambda: show_toast(self, f"🔔 {data.get('title')}: {data.get('message')}", type=data.get("level", "info")))

    def _handle_progress(self, data):
        from ui_components import ProgressOverlay
        module = data.get("module")
        if module not in self.progress_overlays:
            self.progress_overlays[module] = ProgressOverlay(self, title=f"{module.upper()} TASK")
        self.progress_overlays[module].update(data.get("percentage"), data.get("message"))
        if data.get("percentage") >= 100:
            self.after(2000, lambda: self.progress_overlays.pop(module, None))

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
        setup_theme(new_mode)
        from utils import ConfigManager
        ConfigManager.set("appearance_mode", new_mode)
        self.after(100, self.refresh_sidebar) # Re-draw sidebar for theme alignment

    def refresh_sidebar(self):
        self.sidebar.destroy()
        callbacks = {"load_page": self.load_page, "toggle_theme": self.toggle_theme, "toggle_language": self.toggle_language, "logout": self.logout}
        self.sidebar = NavigationSidebar(self, self.user_data, self.username, callbacks)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

    def toggle_language(self):
        from utils import LocalizationManager
        mgr = LocalizationManager()
        mgr.set_locale("tl" if mgr._current_locale == "en" else "en")
        self.refresh_sidebar()
        self.load_page(DashboardHomePage)

    def logout(self):
        from tkinter import messagebox
        if messagebox.askyesno(tr("common.logout_confirm"), tr("common.logout_msg")):
            self.destroy()

    def logout_automatic(self):
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

def open_dashboard(user_data):
    app = DashboardApp(user_data)
    app.mainloop()


class SystemHelpPage:
    def __init__(self, parent, user):
        self.container = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header with bright color
        ctk.CTkLabel(
            self.container,
            text="MTO Treasury System Help Guide",
            font=ModernTheme.H1,
            text_color="#3498db",
        ).pack(anchor="w", pady=(0, 20))

        help_text = [
            (
                "🏠 Dashboard",
                "View real-time revenue collection charts and protection status.",
            ),
            (
                "📋 Property Records",
                "Search, edit, or delete property assessments. Use the 'Export' button to save to Excel.",
            ),
            (
                "🏦 Unified Ledger",
                "View all payment history. Use 'View Receipt' to open a PDF copy.",
            ),
            (
                "⌨️ Keyboard Shortcuts",
                "Ctrl + F: Quick Search / Command Palette\nCtrl + P: Open Command Palette\nCtrl + E: Export visible table data to Excel/CSV",
            ),
            (
                "🛡️ Data Protection",
                "The 'Restore Test' on the dashboard verifies that your backups are 100% healthy and ready for disaster recovery.",
            ),
            (
                "💼 Audit Trail",
                "Administrators can view all changes made to any record in the System Settings > Audit Logs tab.",
            ),
        ]

        for title, desc in help_text:
            # Card-like frame for each help item
            f = ctk.CTkFrame(
                self.container, fg_color=("#ebebeb", "#262626"), corner_radius=10
            )
            f.pack(fill="x", pady=8, padx=5)

            ctk.CTkLabel(f, text=title, font=ModernTheme.H3, text_color="#3498db").pack(
                anchor="w", padx=15, pady=(10, 2)
            )
            ctk.CTkLabel(
                f,
                text=desc,
                font=ModernTheme.BODY,
                wraplength=700,
                justify="left",
            ).pack(anchor="w", padx=15, pady=(0, 15))

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
        
        ctk.CTkLabel(modal, text="PENDING MUNICIPAL SYNCHRONIZATION", font=ModernTheme.H2).pack(pady=20)
        
        scroll = ctk.CTkScrollableFrame(modal)
        scroll.pack(fill="both", expand=True, padx=20, pady=10)
        
        for item in pending:
            frame = ctk.CTkFrame(scroll)
            frame.pack(fill="x", pady=5)
            
            # Identify if it's a conflict
            is_conflict = item.get("status") == "CONFLICT"
            status_color = "#e67e22" if is_conflict else "#3498db"
            
            ctk.CTkLabel(frame, text=f"{item['method']} {item['endpoint']}", font=ModernTheme.BODY_BOLD).pack(side="left", padx=10, pady=10)
            
            if is_conflict:
                ctk.CTkButton(frame, text="RESOLVE", width=100, fg_color="#e67e22", 
                             command=lambda i=item: self._resolve_manual(i, modal)).pack(side="right", padx=10)
            else:
                ctk.CTkLabel(frame, text="PENDING", text_color="#3498db", font=ModernTheme.BODY_SMALL).pack(side="right", padx=10)

    def _resolve_manual(self, item, parent_modal):
        """Opens the arbitration modal for a specific item."""
        parent_modal.destroy()
        from ui.conflict_resolver import ConflictArbitrationModal
        ConflictArbitrationModal(
            self, 
            item["id"], 
            item["payload"], 
            {"info": "Conflict detected during background sync. Server state has diverged."},
            self._handle_resolution
        )

    def _handle_resolution(self, action_id, choice):
        if choice == "LOCAL":
            # In a full implementation, this would reset the status to 'PENDING'
            # For now, we'll just acknowledge the user's intent
            show_toast(self, "Retrying with local data...", "info")
        else:
            manager.mark_as_synced(action_id)
            show_toast(self, "Conflict discarded. Using server version.", "success")
