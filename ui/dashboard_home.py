import threading
import time
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
        self._backup_status_loaded = False
        self.setup_ui()
        self.start_data_refresh()

    def setup_ui(self):
        # Progress bar at the very top (outside scrollable frame)
        self.loading_bar = ctk.CTkProgressBar(self.parent, height=2, corner_radius=0, progress_color=ModernTheme.PRIMARY)
        self.loading_bar.pack(fill="x")
        self.loading_bar.set(0)
        self.loading_bar.pack_forget()

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
            "local": self._make_backup_item(inner_backup, 0, tr("dashboard.backup.local"), "Loading..."),
            "usb": self._make_backup_item(inner_backup, 1, tr("dashboard.backup.usb"), "Loading..."),
            "cloud": self._make_backup_item(inner_backup, 2, tr("dashboard.backup.cloud"), "Loading..."),
            "verify": self._make_backup_item(inner_backup, 3, tr("dashboard.backup.verify"), "Loading..."),
        }

        self.backup_summary = ctk.CTkFrame(self.backup_card, fg_color=("#eef6ff", "#162235"), corner_radius=8)
        self.backup_summary.pack(fill="x", padx=20, pady=(0, 12))
        self.backup_summary_lbl = ctk.CTkLabel(
            self.backup_summary,
            text="Loading live backup health...",
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        )
        self.backup_summary_lbl.pack(fill="x", padx=12, pady=(8, 2))
        self.backup_detail_lbl = ctk.CTkLabel(
            self.backup_summary,
            text="Contacting the server.",
            font=("Segoe UI", 9),
            text_color="gray",
            anchor="w",
        )
        self.backup_detail_lbl.pack(fill="x", padx=12, pady=(0, 8))

        backup_actions = ctk.CTkFrame(self.backup_card, fg_color="transparent")
        backup_actions.pack(fill="x", padx=20, pady=(0, 20))
        if auth.has_permission(self.user, "backup_restore"):
            self.backup_btn = ctk.CTkButton(
                backup_actions,
                text=tr("dashboard.backup.run_now"),
                command=self.trigger_manual_backup,
                width=220,
                height=38,
                font=ModernTheme.BUTTON,
            )
            self.backup_btn.pack(side="left")
        else:
            self.backup_btn = None
            ctk.CTkLabel(
                backup_actions,
                text="Administrative credentials required to trigger manual backup.",
                font=("Segoe UI", 10, "italic"),
                text_color="gray",
            ).pack(side="left")


    def _show_loading(self):
        try:
            self.loading_bar.pack(fill="x", side="top", before=self.container)
            self.loading_bar.start()
        except Exception:
            pass

    def _hide_loading(self):
        try:
            self.loading_bar.stop()
            self.loading_bar.pack_forget()
        except Exception:
            pass


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
        self._show_loading()
        self._backup_status_loaded = False
        threading.Thread(target=self.refresh_data, daemon=True).start()
        threading.Thread(target=self.refresh_backup_status, daemon=True).start()
        self.parent.after(16000, self._expire_backup_loading)

    def refresh_data(self):
        try:
            summary = self.callbacks["get_summary"]() or {}
            
            # Inject Infrastructure Stats
            try:
                summary["infra_stats"] = system.get_system_stats()
            except Exception as e:
                from utils import log_error_to_file
                log_error_to_file("Dashboard infra_stats fetch failed", e)
                summary["infra_stats"] = None
            
            trend_rows = self.callbacks["get_trend"](6) or []
            self.parent.after(0, lambda: self._update_ui(summary, trend_rows))
        except Exception as e:
            print(f"Dashboard refresh error: {e}")
            self.parent.after(0, self._hide_loading)

    def _update_ui(self, summary, trend_rows):
        self._hide_loading()
        if not self.stat_cards["total_properties"].winfo_exists(): return

        self.stat_cards["total_properties"].configure(text=str(summary.get("total_properties", 0)))
        self.stat_cards["collections_today"].configure(text=f"P {float(summary.get('collections_today', 0) or 0):,.2f}")
        self.stat_cards["collections_month"].configure(text=f"P {float(summary.get('collections_month', 0) or 0):,.2f}")

        months = [row["month"][5:] for row in trend_rows]
        totals = [row["total"] for row in trend_rows]
        self.bar_chart.draw(months, totals, chart_type="bar")
        self.trend_chart.draw(months, totals, chart_type="line")

        b = summary.get("backup")
        if b:
            self._update_backup_ui(b)


        # Update Infrastructure Health (New Phase 4 Hardening)
        stats = summary.get("infra_stats")
        if stats:
            self._update_infra_ui(stats)

        show_toast(self.parent.winfo_toplevel(), "Dashboard data refreshed", type="info")

    def _expire_backup_loading(self):
        """Guarantees the backup card never remains in an endless loading state."""
        if not self._backup_status_loaded:
            self._show_backup_status_error("The server did not answer the backup health check within 15 seconds.")


    def refresh_backup_status(self):
        """Loads backup health independently so a slow check cannot block the dashboard."""
        try:
            status = system.get_backup_verification_status() or {}
            self.parent.after(0, lambda b=status: self._update_backup_ui(b))
        except Exception as exc:
            self.parent.after(0, lambda message=str(exc): self._show_backup_status_error(message))

    def _backup_color(self, value, is_running=False):
        upper_val = str(value or "").upper()
        if is_running:
            return "#f59e0b"
        if any(word in upper_val for word in ("FAILED", "ERROR", "ISSUE", "UNAVAILABLE", "MISSING")):
            return "#e74c3c"
        if any(word in upper_val for word in ("SUCCESS", "OK", "PROTECTED")) or (":" in upper_val and "READY:" not in upper_val):
            return ModernTheme.SUCCESS
        return "gray"

    def _update_backup_ui(self, backup):
        if not self.backup_card.winfo_exists():
            return
        self._backup_status_loaded = True
        is_running = bool(backup.get("is_running"))
        for key, fallback in (("local", "Status unavailable"), ("usb", "Status unavailable"), ("cloud", "Status unavailable"), ("verify", "Status unavailable")):
            field = "last_verify" if key == "verify" else f"last_{key}"
            value = backup.get(field, fallback)
            self.backup_labels[key].configure(text=value, text_color=self._backup_color(value, is_running))

        summary_text = backup.get("storage_status") or "Backup health unavailable"
        checked_at = backup.get("checked_at") or "unknown time"
        last_backup = backup.get("last_backup") or "No recorded backup"
        checksum = backup.get("last_checksum_short") or "None"
        self.backup_summary_lbl.configure(text=summary_text, text_color=self._backup_color(summary_text, is_running))
        self.backup_detail_lbl.configure(text=f"Latest: {last_backup}   |   Checksum: {checksum}   |   Checked: {checked_at}")
        if self.backup_btn:
            if is_running:
                self.backup_btn.configure(state="disabled", text="BACKUP IN PROGRESS...")
            else:
                self.backup_btn.configure(state="normal", text="RUN HYBRID BACKUP NOW")

    def _show_backup_status_error(self, message):
        if not self.backup_card.winfo_exists():
            return
        self._backup_status_loaded = True
        for label in self.backup_labels.values():
            label.configure(text="Unavailable", text_color="#e74c3c")
        self.backup_summary_lbl.configure(text="Backup status unavailable", text_color="#e74c3c")
        detail = "The server did not answer the backup health check within 15 seconds." if "timed out" in message.lower() else message
        self.backup_detail_lbl.configure(text=detail)
        if self.backup_btn:
            self.backup_btn.configure(state="normal", text="RUN HYBRID BACKUP NOW")


    def _update_infra_ui(self, stats):
        """Updates the new infrastructure health indicators."""
        if not hasattr(self, "infra_section"):
            self._setup_infra_section()
        
        p = stats.get("pool", {})
        c = stats.get("cache", {})
        
        self.pool_lbl.configure(text=f"POOL: {p.get('active', 0)} ACTIVE | {p.get('idle', 0)} IDLE | {p.get('overflow', 0)} OVERFLOW")
        self.cache_lbl.configure(text=f"CACHE: {c.get('items', 0)} ITEMS | NAMESPACES: {', '.join(c.get('namespaces', []))}")
        
        # Color coding for pool health
        if p.get('overflow', 0) > 0: self.pool_lbl.configure(text_color="#e67e22")
        elif p.get('active', 0) > 40: self.pool_lbl.configure(text_color="#e74c3c")
        else: self.pool_lbl.configure(text_color="#2ecc71")

    def _setup_infra_section(self):
        """Creates the layout for infra diagnostics."""
        self.infra_section = ctk.CTkFrame(self.container, fg_color="transparent")
        self.infra_section.pack(fill="x", pady=(0, 20))
        
        f = ctk.CTkFrame(self.infra_section, border_width=1, border_color="#34495e")
        f.pack(fill="x")
        
        ctk.CTkLabel(f, text="🏛️ INFRASTRUCTURE HEALTH (REAL-TIME)", font=("Segoe UI", 10, "bold"), text_color="gray").pack(pady=(10, 5), padx=20, anchor="w")
        
        inner = ctk.CTkFrame(f, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=(0, 10))
        
        self.pool_lbl = ctk.CTkLabel(inner, text="POOL: LOADING...", font=("Segoe UI", 11, "bold"), text_color="#2ecc71")
        self.pool_lbl.pack(side="left")
        
        self.cache_lbl = ctk.CTkLabel(inner, text="CACHE: LOADING...", font=("Segoe UI", 11), text_color="gray")
        self.cache_lbl.pack(side="right")

    def trigger_manual_backup(self):
        if self.backup_btn and self.backup_btn.cget("state") == "disabled":
            return

        if self.backup_btn:
            self.backup_btn.configure(state="disabled", text="STARTING BACKUP...")

        def run():
            try:
                res = self.callbacks["trigger_backup"]() or {}
                job_id = res.get("job_id")
                if not job_id:
                    self.parent.after(0, self.start_data_refresh)
                    return

                deadline = time.time() + 900
                while time.time() < deadline:
                    job = system.get_job_status(job_id) or {}
                    status = str(job.get("status", "")).upper()
                    progress = int(job.get("progress") or 0)

                    if self.backup_btn:
                        self.parent.after(
                            0,
                            lambda p=progress: self.backup_btn.configure(
                                state="disabled",
                                text=f"BACKUP {p}%..."
                            )
                        )

                    if status == "COMPLETED":
                        self.parent.after(0, self.start_data_refresh)
                        return
                    if status == "FAILED":
                        msg = job.get("error") or job.get("progress_message") or "Backup failed."
                        self.parent.after(0, lambda m=msg: ErrorDialog(self.parent.winfo_toplevel(), "Backup Failed", m))
                        self.parent.after(0, self.start_data_refresh)
                        return

                    time.sleep(1.5)

                self.parent.after(0, lambda: ErrorDialog(self.parent.winfo_toplevel(), "Backup Timeout", "Backup did not finish within 15 minutes."))
                self.parent.after(0, self.start_data_refresh)
            except Exception as e:
                from tkinter import messagebox
                err = str(e)
                self.parent.after(0, lambda: messagebox.showerror("Backup Error", err))
                self.parent.after(0, self.start_data_refresh)

        threading.Thread(target=run, daemon=True).start()
