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
from ui_components import ModernChartWidget, show_toast
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
            header, text="Revenue Dashboard", font=ModernTheme.H1, text_color="white"
        ).pack(anchor="w", padx=30, pady=(25, 5))
        ctk.CTkLabel(
            header,
            text="Real-time collection monitoring and analytics",
            font=ModernTheme.BODY,
            text_color="#d1d1d1",
        ).pack(anchor="w", padx=30, pady=(0, 25))

        # Stats Cards (Grid)
        stats_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        stats_frame.pack(fill="x", pady=(0, 20))
        stats_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.stat_cards = {
            "total_properties": self._make_stat_card(
                stats_frame, 0, "Total Properties", "0", "#3498db"
            ),
            "collections_today": self._make_stat_card(
                stats_frame, 1, "Today's Collection", "P 0.00", "#2ecc71"
            ),
            "collections_month": self._make_stat_card(
                stats_frame, 2, "Monthly Total", "P 0.00", "#e67e22"
            ),
        }

        # Charts Section
        charts_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        charts_frame.pack(fill="both", expand=True)
        charts_frame.grid_columnconfigure((0, 1), weight=1)

        self.bar_chart = ModernChartWidget(charts_frame, "Revenue by Month")
        self.bar_chart.pack(row=0, column=0, padx=(0, 10), sticky="nsew")

        self.trend_chart = ModernChartWidget(charts_frame, "Collection Trend")
        self.trend_chart.pack(row=0, column=1, padx=(10, 0), sticky="nsew")

        # Backup Status Section
        backup_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        backup_frame.pack(fill="x", pady=20)

        self.backup_card = ctk.CTkFrame(backup_frame)
        self.backup_card.pack(fill="x")

        ctk.CTkLabel(
            self.backup_card,
            text="SYSTEM DATA PROTECTION STATUS",
            font=("Segoe UI", 12, "bold"),
            text_color="gray",
        ).pack(pady=(15, 10), padx=20, anchor="w")

        inner_backup = ctk.CTkFrame(self.backup_card, fg_color="transparent")
        inner_backup.pack(fill="x", padx=20, pady=(0, 15))
        inner_backup.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.backup_labels = {
            "local": self._make_backup_item(inner_backup, 0, "Local Backup", "Never"),
            "usb": self._make_backup_item(inner_backup, 1, "USB Mirror", "Never"),
            "cloud": self._make_backup_item(inner_backup, 2, "Cloud Sync", "Never"),
            "verify": self._make_backup_item(
                inner_backup, 3, "Restore Test", "Unknown"
            ),
        }

        self.backup_btn = ctk.CTkButton(
            self.backup_card,
            text="RUN HYBRID BACKUP NOW",
            command=self.trigger_manual_backup,
            width=200,
            height=35,
            font=ModernTheme.BUTTON,
        )
        self.backup_btn.pack(pady=(0, 20), padx=20, anchor="e")

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
                "Hybrid backup started in background",
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

        self.title(f"Treasury Management System | {self.username}")
        self.geometry("1400x850")
        self.resizable(True, True)
        self.minsize(1100, 700)

        # Key Bindings (Keyboard Shortcuts for UX)
        self.bind("<Control-f>", lambda e: self.open_command_palette())
        self.bind("<Control-p>", lambda e: self.open_command_palette())

        # Auto-Maximize (Fullscreen) on Startup
        self.after(0, lambda: self.state("zoomed"))

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

        # Start Sync Monitor & Status Heartbeat
        sync_monitor.start()
        self.update_connectivity_status()

        self.load_page(DashboardHomePage)

        # Bind Global Search (Ctrl+K)
        self.bind("<Control-k>", lambda e: self.open_command_palette())
        self.bind("<Control-K>", lambda e: self.open_command_palette())

    def open_command_palette(self):
        CommandPalette(self, self.user_data, self.handle_palette_selection)

    def handle_palette_selection(self, result):
        """Processes navigation or actions from the Command Palette."""
        res_type = result.get("type")
        identifier = result.get("identifier")
        command = result.get("command")

        if res_type == "property":
            # Open Dossier for this TD
            from ui.dossier import PropertyDossierWindow

            PropertyDossierWindow(self, identifier, self.user_data)

        elif res_type == "receipt":
            # Open the Unified Ledger
            self.load_page(LedgerPage)

        elif res_type == "action":
            if command == "action:backup":
                self.trigger_manual_backup_from_palette()
            elif command == "nav:new_property":
                self.load_page(PropertyPage)
            elif command == "nav:users":
                self.load_page(SystemAdminPage)
            elif command == "nav:reports":
                self.load_page(ReportsPage)

    def update_connectivity_status(self):
        """Periodically updates the UI based on global connection state."""
        status = api.CONNECTION_STATUS
        count = manager.get_queue_count()
        
        if status == "ONLINE":
            self.status_dot.configure(text_color="#2ecc71")
            self.status_lbl.configure(text="SYSTEM ONLINE & SECURED")
        elif status == "OFFLINE":
            self.status_dot.configure(text_color="#f1c40f")
            self.status_lbl.configure(text="OFFLINE MODE (LOCAL SAVE ACTIVE)")
        elif status == "SYNCING":
            self.status_dot.configure(text_color="#3498db")
            self.status_lbl.configure(text="SYNCING DATA TO SERVER...")
            
        if count > 0:
            self.queue_lbl.configure(text=f"PENDING SYNC: {count} ITEMS")
        else:
            self.queue_lbl.configure(text="")
            
        # Check every 2 seconds
        self.after(2000, self.update_connectivity_status)
            elif command == "nav:users":
                self.load_page(SystemAdminPage)
            elif command == "nav:reports":
                self.load_page(ReportsPage)
            elif command == "nav:assessment":
                self.load_page(AssessmentRollPage)

    def trigger_manual_backup_from_palette(self):
        try:
            system.trigger_backup()
            show_toast(self, "Hybrid backup started in background", type="info")
        except Exception as e:
            from tkinter import messagebox

            messagebox.showerror("Backup Error", str(e))

    def setup_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # Logo Section with Robust Path Management
        try:
            logo_path = Path(__file__).parent / "bagongpilipinas.png"
            if logo_path.exists():
                self.logo_img = ctk.CTkImage(
                    Image.open(str(logo_path)), size=(180, 180)
                )
                self.logo_lbl = ctk.CTkLabel(self.sidebar, image=self.logo_img, text="")
                self.logo_lbl.pack(pady=(30, 10))
            else:
                raise FileNotFoundError
        except:
            # Professional Fallback Placeholder
            ctk.CTkLabel(
                self.sidebar,
                text="TREASURY SYSTEM",
                font=ModernTheme.H2,
                text_color="#3498db",
            ).pack(pady=(30, 10))

        # Profile Section
        ctk.CTkLabel(self.sidebar, text=self.username, font=ModernTheme.BODY).pack()
        ctk.CTkLabel(
            self.sidebar,
            text=auth.get_user_role(self.user_data).upper(),
            font=("Segoe UI", 10, "bold"),
            text_color="gray",
        ).pack(pady=(0, 30))

        # Scrollable area for buttons
        self.nav_scroll = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.nav_scroll.pack(fill="both", expand=True, padx=5)

        self.nav_btns = {}
        self.create_nav_btn("Dashboard", lambda: self.load_page(DashboardHomePage))

        if auth.has_permission(self.user_data, "property_view"):
            self.create_nav_btn(
                "Property Records", lambda: self.load_page(PropertyPage)
            )
        if auth.has_permission(self.user_data, "ledger_view"):
            self.create_nav_btn(
                "Payment & Receipt Ledger", lambda: self.load_page(LedgerPage)
            )

        ctk.CTkLabel(
            self.nav_scroll,
            text="ADVANCED",
            font=("Segoe UI", 10, "bold"),
            text_color="gray",
        ).pack(pady=(20, 5))

        if auth.has_permission(self.user_data, "report_view"):
            self.create_nav_btn("Reports", lambda: self.load_page(ReportsPage))
            self.create_nav_btn(
                "📊 Analytics Hub", lambda: self.load_page(AnalyticsDashboardPage)
            )

        if auth.has_permission(self.user_data, "property_view"):
            self.create_nav_btn(
                "Assessment Roll", lambda: self.load_page(AssessmentRollPage)
            )

        if auth.has_permission(self.user_data, "view_logs"):
            self.create_nav_btn(
                "📑 Audit Trail", lambda: self.load_page(AuditTrailPage)
            )

        if any(
            auth.has_permission(self.user_data, p)
            for p in ["manage_users", "view_logs"]
        ):
            self.create_nav_btn(
                "System Settings", lambda: self.load_page(SystemAdminPage)
            )

        ctk.CTkLabel(
            self.nav_scroll,
            text="RESOURCES",
            font=("Segoe UI", 10, "bold"),
            text_color="gray",
        ).pack(pady=(20, 5))
        self.create_nav_btn("📖 System Help", lambda: self.load_page(SystemHelpPage))

        # Logout at bottom
        self.logout_btn = ctk.CTkButton(
            self.sidebar,
            text="LOGOUT",
            fg_color="#e74c3c",
            hover_color="#c0392b",
            command=self.logout,
            font=ModernTheme.BUTTON,
        )
        self.logout_btn.pack(side="bottom", pady=30, padx=20, fill="x")

    def create_nav_btn(self, text, command):
        btn = ctk.CTkButton(
            self.nav_scroll,
            text=text,
            command=command,
            anchor="w",
            fg_color="transparent",
            text_color=("gray10", "gray90"),
            hover_color=("gray70", "gray30"),
            font=ModernTheme.BODY,
            height=45,
        )
        btn.pack(fill="x", padx=10, pady=2)
        self.nav_btns[text] = btn

    def load_page(self, page_class):
        for widget in self.main_area.winfo_children():
            widget.destroy()
        page_class(self.main_area, self.user_data)

    def logout(self):
        from tkinter import messagebox

        if messagebox.askyesno(
            "Confirm Logout", "Are you sure you want to log out of the system?"
        ):
            self.destroy()


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
