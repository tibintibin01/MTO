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


from ui.ledger import LedgerPage
from ui.property import PropertyPage
from ui.recycle import RecycleBinPage
from ui.reports import ReportsPage
from ui.assessment_roll import AssessmentRollPage
from ui.system_admin import SystemAdminPage
from ui.audit_trail import AuditTrailPage
from ui.analytics_dashboard import AnalyticsDashboardPage
from ui.command_palette import CommandPalette

# Ensure theme is loaded
setup_theme()


class DashboardHomePage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.setup_ui()
        self.start_data_refresh()

    def setup_ui(self):
        self.container = ctk.CTkScrollableFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header Section
        header = ctk.CTkFrame(self.container, fg_color="#1f538d", corner_radius=15)
        header.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            header, text=tr("dashboard.title"), font=ModernTheme.H1, text_color="white"
        ).pack(anchor="w", padx=30, pady=(25, 5))
        ctk.CTkLabel(
            header,
            text=tr("dashboard.subtitle"),
            font=ModernTheme.BODY,
            text_color="#d1d1d1",
        ).pack(anchor="w", padx=30, pady=(0, 25))

        # Stats Cards (Grid)
        stats_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        stats_frame.pack(fill="x", pady=(0, 20))
        stats_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.stat_cards = {
            "total_properties": self._make_stat_card(
                stats_frame, 0, tr("dashboard.stats.total_properties"), "0", "#3498db"
            ),
            "collections_today": self._make_stat_card(
                stats_frame, 1, tr("dashboard.stats.collections_today"), "P 0.00", "#2ecc71"
            ),
            "collections_month": self._make_stat_card(
                stats_frame, 2, tr("dashboard.stats.collections_month"), "P 0.00", "#e67e22"
            ),
        }

        # Charts Section
        charts_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        charts_frame.pack(fill="both", expand=True)
        charts_frame.grid_columnconfigure((0, 1), weight=1)

        self.bar_chart = ModernChartWidget(charts_frame, tr("dashboard.charts.revenue_month"))
        self.bar_chart.pack(row=0, column=0, padx=(0, 10), sticky="nsew")

        self.trend_chart = ModernChartWidget(charts_frame, tr("dashboard.charts.collection_trend"))
        self.trend_chart.pack(row=0, column=1, padx=(10, 0), sticky="nsew")

        # Backup Status Section
        backup_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        backup_frame.pack(fill="x", pady=20)

        self.backup_card = ctk.CTkFrame(backup_frame)
        self.backup_card.pack(fill="x")

        ctk.CTkLabel(
            self.backup_card,
            text=tr("dashboard.backup.title"),
            font=("Segoe UI", 12, "bold"),
            text_color="gray",
        ).pack(pady=(15, 10), padx=20, anchor="w")

        inner_backup = ctk.CTkFrame(self.backup_card, fg_color="transparent")
        inner_backup.pack(fill="x", padx=20, pady=(0, 15))
        inner_backup.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.backup_labels = {
            "local": self._make_backup_item(inner_backup, 0, tr("dashboard.backup.local"), "Never"),
            "usb": self._make_backup_item(inner_backup, 1, tr("dashboard.backup.usb"), "Never"),
            "cloud": self._make_backup_item(inner_backup, 2, tr("dashboard.backup.cloud"), "Never"),
            "verify": self._make_backup_item(
                inner_backup, 3, tr("dashboard.backup.verify"), "Unknown"
            ),
        }

        # Only show backup button for users with permission
        if auth.has_permission(self.user, "backup_restore"):
            self.backup_btn = ctk.CTkButton(
                self.backup_card,
                text=tr("dashboard.backup.run_now"),
                command=self.trigger_manual_backup,
                width=200,
                height=35,
                font=ModernTheme.BUTTON,
            )
            self.backup_btn.pack(pady=(0, 20), padx=20, anchor="e")
        else:
            self.backup_btn = None
            ctk.CTkLabel(
                self.backup_card,
                text="🛡️ Administrative credentials required to trigger manual backup.",
                font=("Segoe UI", 10, "italic"),
                text_color="gray"
            ).pack(pady=(0, 20), padx=20, anchor="e")

    def _make_stat_card(self, parent, col, title, value, color):
        card = ctk.CTkFrame(parent, height=120)
        card.grid(row=0, column=col, padx=10, sticky="nsew")

        ctk.CTkLabel(card, text=title, font=ModernTheme.BODY, text_color="gray").pack(
            pady=(20, 5)
        )
        val_label = ctk.CTkLabel(
            card, text=value, font=ModernTheme.H2, text_color=color
        )
        val_label.pack(pady=(0, 20))
        return val_label

    def _make_backup_item(self, parent, col, title, value):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=0, column=col, sticky="nsew")
        ctk.CTkLabel(
            f, text=title, font=("Segoe UI", 10, "bold"), text_color="gray"
        ).pack()
        lbl = ctk.CTkLabel(f, text=value, font=ModernTheme.BODY)
        lbl.pack()
        return lbl

    def start_data_refresh(self):
        # Asynchronous data loading
        threading.Thread(target=self.refresh_data, daemon=True).start()

    def refresh_data(self):
        try:
            summary = system.get_dashboard_summary() or {}
            trend_rows = payment.get_monthly_collection_trend(6) or []

            # Update UI in main thread
            self.parent.after(0, lambda: self._update_ui(summary, trend_rows))
        except Exception as e:
            # We don't want to spam the file for every refresh error, but we should log it
            print(f"Dashboard refresh error: {e}")

    def _update_ui(self, summary, trend_rows):
        if not self.stat_cards["total_properties"].winfo_exists():
            return

        self.stat_cards["total_properties"].configure(
            text=str(summary.get("total_properties", 0))
        )
        self.stat_cards["collections_today"].configure(
            text=f"P {float(summary.get('collections_today', 0) or 0):,.2f}"
        )
        self.stat_cards["collections_month"].configure(
            text=f"P {float(summary.get('collections_month', 0) or 0):,.2f}"
        )

        months = [row["month"][5:] for row in trend_rows]
        totals = [row["total"] for row in trend_rows]
        self.bar_chart.draw(months, totals, chart_type="bar")
        self.trend_chart.draw(months, totals, chart_type="line")

        # Update Backup Status
        b = summary.get("backup", {})
        self.backup_labels["local"].configure(text=b.get("last_local", "Never"))
        self.backup_labels["usb"].configure(text=b.get("last_usb", "Never"))
        self.backup_labels["cloud"].configure(text=b.get("last_cloud", "Never"))

        v = b.get("last_verify", "Unknown")
        v_color = (
            "#2ecc71" if "Success" in v else "#e74c3c" if "Failed" in v else "gray"
        )
        self.backup_labels["verify"].configure(text=v, text_color=v_color)

        if self.backup_btn:
            if b.get("is_running"):
                self.backup_btn.configure(state="disabled", text="BACKUP IN PROGRESS...")
            else:
                self.backup_btn.configure(state="normal", text="RUN HYBRID BACKUP NOW")

        # Show a subtle update toast
        show_toast(
            self.parent.winfo_toplevel(), "Dashboard data refreshed", type="info"
        )

    def trigger_manual_backup(self):
        try:
            system.trigger_backup()
            show_toast(
                self.parent.winfo_toplevel(),
                tr("dashboard.backup.success_toast"),
                type="info",
            )
            # Refresh data soon to show "In Progress"
            self.parent.after(1000, self.start_data_refresh)
        except Exception as e:
            from tkinter import messagebox

            messagebox.showerror("Backup Error", str(e))


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

        self.setup_sidebar()
        self.main_area = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_area.grid(row=0, column=1, sticky="nsew")

        # --- CONNECTIVITY STATUS BAR (FOOTER) ---
        self.footer = ctk.CTkFrame(self, height=25, fg_color="#2c3e50")
        self.footer.grid(row=1, column=0, columnspan=2, sticky="ew")
        
        self.status_dot = ctk.CTkLabel(self.footer, text="●", font=("Segoe UI", 14), text_color="#2ecc71")
        self.status_dot.pack(side="left", padx=(15, 5))
        
        self.status_lbl = ctk.CTkLabel(self.footer, text="SYSTEM ONLINE", font=("Segoe UI", 10, "bold"), text_color="white")
        self.status_lbl.pack(side="left")
        
        self.queue_lbl = ctk.CTkLabel(self.footer, text="", font=("Segoe UI", 10), text_color="#bdc3c7")
        self.queue_lbl.pack(side="right", padx=15)
        self.progress_overlays = {}

        # 1. Initialize Specialized Coordinators
        self.watchdog = SessionWatchdog(self, 15, self.logout_automatic)
        self.notifier = NotificationListener({
            "on_open": lambda: self.status_bar.set_ws_status(True),
            "on_close": lambda: self.status_bar.set_ws_status(False),
            "on_notification": self._handle_notification,
            "on_progress": self._handle_progress
        })

        self.setup_main_window()
        self.setup_ui()
        
        # 2. Launch Background Services
        self.watchdog.start_monitoring()
        self.notifier.start()
        
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
                text_color=("#333333", "#cccccc"),
                wraplength=800,
                justify="left",
            ).pack(anchor="w", padx=20, pady=(0, 15))
