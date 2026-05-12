import threading
import customtkinter as ctk
from theme_manager import ModernTheme
import api_clients.auth_service as auth
import api_clients.payment_service as payment
import api_clients.system_service as system
from ui_components import ModernChartWidget, show_toast, ErrorDialog
from utils import tr
from ui.animation_helper import WidgetAnimator

class DashboardHomePage:
    def __init__(self, parent, user, callbacks):
        self.parent = parent
        self.user = user
        self.callbacks = callbacks # Dict: trigger_backup, get_summary, get_trend
        self.setup_ui()
        self.start_data_refresh()

    def setup_ui(self):
        self.container = ctk.CTkScrollableFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header Section - Gradient-like effect using primary colors
        header = ctk.CTkFrame(self.container, fg_color=ModernTheme.PRIMARY, corner_radius=15)
        header.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(header, text=tr("dashboard.title"), font=ModernTheme.H1, text_color="white").pack(anchor="w", padx=30, pady=(25, 5))
        ctk.CTkLabel(header, text=tr("dashboard.subtitle"), font=ModernTheme.BODY, text_color="#f0f9ff").pack(anchor="w", padx=30, pady=(0, 25))

        # Stats Cards (Grid)
        stats_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        stats_frame.pack(fill="x", pady=(0, 20))
        stats_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.stat_cards = {
            "total_properties": self._make_stat_card(stats_frame, 0, tr("dashboard.stats.total_properties"), "0", ModernTheme.INFO),
            "collections_today": self._make_stat_card(stats_frame, 1, tr("dashboard.stats.collections_today"), "P 0.00", ModernTheme.SUCCESS),
            "collections_month": self._make_stat_card(stats_frame, 2, tr("dashboard.stats.collections_month"), "P 0.00", ModernTheme.WARNING),
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

        ctk.CTkLabel(self.backup_card, text=tr("dashboard.backup.title"), font=("Segoe UI", 12, "bold"), text_color="gray").pack(pady=(15, 10), padx=20, anchor="w")

        inner_backup = ctk.CTkFrame(self.backup_card, fg_color="transparent")
        inner_backup.pack(fill="x", padx=20, pady=(0, 15))
        inner_backup.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.backup_labels = {
            "local": self._make_backup_item(inner_backup, 0, tr("dashboard.backup.local"), "Never"),
            "usb": self._make_backup_item(inner_backup, 1, tr("dashboard.backup.usb"), "Never"),
            "cloud": self._make_backup_item(inner_backup, 2, tr("dashboard.backup.cloud"), "Never"),
            "verify": self._make_backup_item(inner_backup, 3, tr("dashboard.backup.verify"), "Unknown"),
        }

        if auth.has_permission(self.user, "backup_restore"):
            self.backup_btn = ctk.CTkButton(self.backup_card, text=tr("dashboard.backup.run_now"), command=self.trigger_manual_backup, width=200, height=35, font=ModernTheme.BUTTON)
            self.backup_btn.pack(pady=(0, 20), padx=20, anchor="e")
        else:
            self.backup_btn = None
            ctk.CTkLabel(self.backup_card, text="🛡️ Administrative credentials required to trigger manual backup.", font=("Segoe UI", 10, "italic"), text_color="gray").pack(pady=(0, 20), padx=20, anchor="e")

    def _make_stat_card(self, parent, col, title, value, color):
        card = ctk.CTkFrame(parent, height=120, border_width=1, border_color=ModernTheme.BORDER_DARK if ctk.get_appearance_mode().lower() == "dark" else ModernTheme.BORDER_LIGHT)
        card.grid(row=0, column=col, padx=10, sticky="nsew")
        
        ctk.CTkLabel(card, text=title, font=ModernTheme.BODY_BOLD, text_color=ModernTheme.TEXT_SUB_DARK if ctk.get_appearance_mode().lower() == "dark" else ModernTheme.TEXT_SUB_LIGHT).pack(pady=(20, 5))
        val_label = ctk.CTkLabel(card, text=value, font=ModernTheme.H2, text_color=color)
        val_label.pack(pady=(0, 20))
        
        # Entrance Animation
        card.after(100 + (col * 100), lambda: WidgetAnimator.pulse(card, card.cget("fg_color"), ModernTheme.PRIMARY_HOVER, 200))
        
        return val_label

    def _make_backup_item(self, parent, col, title, value):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=0, column=col, sticky="nsew")
        ctk.CTkLabel(f, text=title, font=("Segoe UI", 10, "bold"), text_color="gray").pack()
        lbl = ctk.CTkLabel(f, text=value, font=ModernTheme.BODY)
        lbl.pack()
        return lbl

    def start_data_refresh(self):
        threading.Thread(target=self.refresh_data, daemon=True).start()

    def refresh_data(self):
        try:
            summary = self.callbacks["get_summary"]() or {}
            trend_rows = self.callbacks["get_trend"](6) or []
            self.parent.after(0, lambda: self._update_ui(summary, trend_rows))
        except Exception as e:
            print(f"Dashboard refresh error: {e}")

    def _update_ui(self, summary, trend_rows):
        if not self.stat_cards["total_properties"].winfo_exists(): return
        self.stat_cards["total_properties"].configure(text=str(summary.get("total_properties", 0)))
        self.stat_cards["collections_today"].configure(text=f"P {float(summary.get('collections_today', 0) or 0):,.2f}")
        self.stat_cards["collections_month"].configure(text=f"P {float(summary.get('collections_month', 0) or 0):,.2f}")

        months = [row["month"][5:] for row in trend_rows]
        totals = [row["total"] for row in trend_rows]
        self.bar_chart.draw(months, totals, chart_type="bar")
        self.trend_chart.draw(months, totals, chart_type="line")

        b = summary.get("backup", {})
        self.backup_labels["local"].configure(text=b.get("last_local", "Never"))
        self.backup_labels["usb"].configure(text=b.get("last_usb", "Never"))
        self.backup_labels["cloud"].configure(text=b.get("last_cloud", "Never"))
        v = b.get("last_verify", "Unknown")
        v_color = "#2ecc71" if "Success" in v else "#e74c3c" if "Failed" in v else "gray"
        self.backup_labels["verify"].configure(text=v, text_color=v_color)

        if self.backup_btn:
            if b.get("is_running"): self.backup_btn.configure(state="disabled", text="BACKUP IN PROGRESS...")
            else: self.backup_btn.configure(state="normal", text="RUN HYBRID BACKUP NOW")
        show_toast(self.parent.winfo_toplevel(), "Dashboard data refreshed", type="info")

    def trigger_manual_backup(self):
        try:
            self.callbacks["trigger_backup"]()
            self.parent.after(1000, self.start_data_refresh)
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Backup Error", str(e))
