import threading
import customtkinter as ctk
from theme_manager import ModernTheme
import api_clients.auth_service as auth
import api_clients.payment_service as payment
import api_clients.system_service as system
import api_clients.readiness_service as readiness_service
from ui_components import ModernChartWidget, show_toast
from utils import tr
from ui.animation_helper import WidgetAnimator


def _recent_payment_display(row):
    """Normalize the recent-payments API row for the dashboard table."""
    if isinstance(row, dict):
        date_value = row.get("date") or row.get("date_paid")
        or_number = row.get("or_number")
        td_number = row.get("td_number")
        owner = row.get("owner") or row.get("owner_name")
        tax_year = row.get("tax_year")
        amount = row.get("amount")
    else:
        values = list(row or [])
        value = lambda index, default=None: (
            values[index] if len(values) > index else default
        )
        date_value = value(0)
        or_number = value(1)
        td_number = value(2)
        owner = value(3)
        tax_year = value(4)
        amount = value(5)

    date_text = str(date_value or "")[:10]
    try:
        amount_value = float(amount or 0)
    except (TypeError, ValueError):
        amount_value = 0.0
    return {
        "date": date_text or "-",
        "or_number": str(or_number or "-"),
        "td_number": str(td_number or "-"),
        "owner_year": (
            f"{str(owner or '-').strip()} / {str(tax_year or '-').strip()}"
        ),
        "amount": amount_value,
    }


def _dashboard_month_label(value):
    text = str(value or "")
    try:
        year_text, month_text = text.split("-", 1)
        names = (
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        )
        return f"{names[int(month_text) - 1]} {year_text[-2:]}"
    except (ValueError, IndexError):
        return text




class DashboardHomePage:
    def __init__(self, parent, user, callbacks):
        self.parent = parent
        self.user = user
        self.callbacks = callbacks
        self._backup_status_loaded = False
        self.setup_ui()
        self.start_data_refresh()

    def setup_ui(self):
        # Progress bar at the very top (outside scrollable frame)
        self.loading_bar = ctk.CTkProgressBar(
            self.parent, height=2, corner_radius=0, progress_color=ModernTheme.PRIMARY
        )
        self.loading_bar.pack(fill="x")
        self.loading_bar.set(0)
        self.loading_bar.pack_forget()

        self.container = ctk.CTkScrollableFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header Section - Gradient-like effect using primary colors
        header = ctk.CTkFrame(
            self.container, fg_color=ModernTheme.PRIMARY, corner_radius=15
        )
        header.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            header, text=tr("dashboard.title"), font=ModernTheme.H1, text_color="white"
        ).pack(anchor="w", padx=30, pady=(25, 5))
        ctk.CTkLabel(
            header,
            text=tr("dashboard.subtitle"),
            font=ModernTheme.BODY,
            text_color="#f0f9ff",
        ).pack(anchor="w", padx=30, pady=(0, 25))

        self._setup_tax_year_readiness_banner()

        # Stats Cards (Grid)
        self.stats_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.stats_frame.pack(fill="x", pady=(0, 20))
        self.stats_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.stat_cards = {
            "total_properties": self._make_stat_card(
                self.stats_frame,
                0,
                tr("dashboard.stats.total_properties"),
                "0",
                ModernTheme.INFO,
            ),
            "collections_today": self._make_stat_card(
                self.stats_frame,
                1,
                tr("dashboard.stats.collections_today"),
                "P 0.00",
                ModernTheme.SUCCESS,
            ),
            "receipts_today": self._make_stat_card(
                self.stats_frame,
                2,
                tr("dashboard.stats.receipts_today"),
                "0",
                ModernTheme.INFO,
            ),
            "collections_month": self._make_stat_card(
                self.stats_frame,
                3,
                tr("dashboard.stats.collections_month"),
                "P 0.00",
                ModernTheme.WARNING,
            ),
        }

        # Charts Section

        charts_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        charts_frame.pack(fill="both", expand=True)
        charts_frame.grid_columnconfigure(0, weight=3)
        charts_frame.grid_columnconfigure(1, weight=2)
        charts_frame.grid_rowconfigure(0, weight=1)

        self.bar_chart = ModernChartWidget(
            charts_frame, tr("dashboard.charts.revenue_month")
        )
        self.bar_chart.pack(row=0, column=0, padx=(0, 10), sticky="nsew")

        self._setup_recent_collections(charts_frame)

        # Compact monitoring strip. Backup execution remains in System Settings.
        backup_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        backup_frame.pack(fill="x", pady=18)

        self.backup_card = ctk.CTkFrame(
            backup_frame,
            border_width=1,
            border_color=("#cbd5e1", "#334155"),
            corner_radius=10,
        )
        self.backup_card.pack(fill="x")

        protection_header = ctk.CTkFrame(
            self.backup_card, fg_color="transparent"
        )
        protection_header.pack(fill="x", padx=18, pady=(13, 8))
        ctk.CTkLabel(
            protection_header,
            text="\u2713",
            width=34,
            height=34,
            corner_radius=17,
            fg_color=("#dbeafe", "#1e3a5f"),
            text_color=ModernTheme.INFO,
            font=("Segoe UI", 16),
        ).pack(side="left", padx=(0, 10))

        protection_copy = ctk.CTkFrame(
            protection_header, fg_color="transparent"
        )
        protection_copy.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            protection_copy,
            text=tr("dashboard.backup.title"),
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).pack(fill="x")
        self.backup_summary_lbl = ctk.CTkLabel(
            protection_copy,
            text="Loading live protection status...",
            font=("Segoe UI", 10, "bold"),
            text_color="gray",
            anchor="w",
        )
        self.backup_summary_lbl.pack(fill="x", pady=(2, 0))

        if auth.has_permission(self.user, "backup_restore"):
            ctk.CTkButton(
                protection_header,
                text=tr("dashboard.backup.review_settings"),
                command=self._open_backup_settings,
                width=190,
                height=34,
                fg_color=ModernTheme.SECONDARY,
                font=("Segoe UI", 9, "bold"),
            ).pack(side="right", padx=(12, 0))

        inner_backup = ctk.CTkFrame(
            self.backup_card,
            fg_color=("#f8fafc", "#111827"),
            corner_radius=7,
        )
        inner_backup.pack(fill="x", padx=18, pady=(0, 8))
        inner_backup.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.backup_labels = {
            "local": self._make_backup_item(
                inner_backup, 0, tr("dashboard.backup.local"), "Loading..."
            ),
            "usb": self._make_backup_item(
                inner_backup, 1, tr("dashboard.backup.usb"), "Loading..."
            ),
            "cloud": self._make_backup_item(
                inner_backup, 2, tr("dashboard.backup.cloud"), "Loading..."
            ),
            "verify": self._make_backup_item(
                inner_backup, 3, tr("dashboard.backup.verify"), "Loading..."
            ),
        }

        self.backup_detail_lbl = ctk.CTkLabel(
            self.backup_card,
            text="Contacting the server.",
            font=("Segoe UI", 8),
            text_color="gray",
            anchor="w",
        )
        self.backup_detail_lbl.pack(fill="x", padx=20, pady=(0, 10))

    def _setup_recent_collections(self, parent):
        self.recent_card = ctk.CTkFrame(
            parent,
            corner_radius=10,
            border_width=1,
            border_color=("#cbd5e1", "#334155"),
        )
        self.recent_card.grid(
            row=0, column=1, padx=(10, 0), sticky="nsew"
        )

        recent_header = ctk.CTkFrame(
            self.recent_card, fg_color="transparent"
        )
        recent_header.pack(fill="x", padx=16, pady=(14, 2))
        ctk.CTkLabel(
            recent_header,
            text=tr("dashboard.charts.recent_collections"),
            font=ModernTheme.H2,
            anchor="w",
        ).pack(side="left")
        if auth.has_permission(self.user, "ledger_view"):
            ctk.CTkButton(
                recent_header,
                text="VIEW LEDGER",
                command=self._open_payment_ledger,
                width=100,
                height=28,
                fg_color="transparent",
                border_width=1,
                border_color=("#94a3b8", "#475569"),
                text_color=("#334155", "#cbd5e1"),
                hover_color=("#e2e8f0", "#334155"),
                font=("Segoe UI", 8, "bold"),
            ).pack(side="right")
        ctk.CTkLabel(
            self.recent_card,
            text="Latest successfully posted payment records",
            font=("Segoe UI", 9),
            text_color="gray",
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 9))

        self.recent_rows = ctk.CTkFrame(
            self.recent_card, fg_color="transparent"
        )
        self.recent_rows.pack(
            fill="both", expand=True, padx=12, pady=(0, 12)
        )
        self._render_recent_collections([])

    def _render_recent_collections(self, rows, load_error=None):
        for child in self.recent_rows.winfo_children():
            child.destroy()

        columns = (
            ("DATE", 72),
            ("OR NO.", 88),
            ("TD NO.", 105),
            ("OWNER / TAX YEAR", 0),
            ("AMOUNT", 92),
        )
        header = ctk.CTkFrame(
            self.recent_rows,
            fg_color=("#e2e8f0", "#1e293b"),
            corner_radius=4,
        )
        header.pack(fill="x", pady=(0, 3))
        for column, (title, width) in enumerate(columns):
            header.grid_columnconfigure(column, weight=1 if width == 0 else 0)
            ctk.CTkLabel(
                header,
                text=title,
                width=width,
                anchor="e" if column == 4 else "w",
                font=("Segoe UI", 8, "bold"),
                text_color=("#475569", "#94a3b8"),
            ).grid(
                row=0, column=column, sticky="ew", padx=6, pady=6
            )

        if load_error:
            ctk.CTkLabel(
                self.recent_rows,
                text=(
                    "Recent collections could not be loaded.\n"
                    "Reopen the Dashboard or check the server connection."
                ),
                font=("Segoe UI", 10),
                text_color=ModernTheme.WARNING,
                justify="center",
            ).pack(expand=True, pady=52)
            return

        if not rows:
            ctk.CTkLabel(
                self.recent_rows,
                text="No recent collections found.",
                font=("Segoe UI", 10),
                text_color="gray",
            ).pack(expand=True, pady=52)
            return

        for index, raw_row in enumerate(rows[:6]):
            row = _recent_payment_display(raw_row)
            frame = ctk.CTkFrame(
                self.recent_rows,
                fg_color=(
                    ("#f8fafc", "#111827")
                    if index % 2 == 0
                    else ("#f1f5f9", "#172033")
                ),
                corner_radius=0,
            )
            frame.pack(fill="x")
            values = (
                row["date"],
                row["or_number"],
                row["td_number"],
                row["owner_year"][:30],
                f"P {row['amount']:,.2f}",
            )
            for column, value in enumerate(values):
                width = columns[column][1]
                frame.grid_columnconfigure(
                    column, weight=1 if width == 0 else 0
                )
                ctk.CTkLabel(
                    frame,
                    text=value,
                    width=width,
                    anchor="e" if column == 4 else "w",
                    font=(
                        ("Segoe UI", 8, "bold")
                        if column == 4
                        else ("Segoe UI", 8)
                    ),
                    text_color=(
                        ModernTheme.SUCCESS
                        if column == 4
                        else ("#1e293b", "#e2e8f0")
                    ),
                ).grid(
                    row=0, column=column, sticky="ew", padx=6, pady=7
                )

    def _open_payment_ledger(self):
        top = self.parent.winfo_toplevel()
        from ui.ledger import LedgerPage

        top.sidebar._set_active("ledger")
        top.load_page(LedgerPage)

    def _open_backup_settings(self):
        top = self.parent.winfo_toplevel()
        from ui.system_admin import SystemAdminPage

        top.sidebar._set_active("settings")
        top.load_page(SystemAdminPage)
        top.current_page.tabview.set(tr("admin.tabs.db"))

    def _setup_tax_year_readiness_banner(self):
        self._tax_year_recommended_tab = "Database & Backup"
        self.tax_year_banner = ctk.CTkFrame(
            self.container,
            fg_color=("#fff7ed", "#3b2413"),
            border_width=1,
            border_color="#f59e0b",
            corner_radius=10,
        )

        ctk.CTkLabel(
            self.tax_year_banner,
            text="NEW YEAR",
            width=90,
            font=("Segoe UI", 10, "bold"),
            text_color="#f59e0b",
        ).pack(side="left", padx=(16, 10), pady=14)

        text_frame = ctk.CTkFrame(self.tax_year_banner, fg_color="transparent")
        text_frame.pack(side="left", fill="x", expand=True, pady=10)
        self.tax_year_title = ctk.CTkLabel(
            text_frame,
            text="New Tax Year Readiness",
            font=("Segoe UI", 13, "bold"),
            anchor="w",
        )
        self.tax_year_title.pack(fill="x")
        self.tax_year_message = ctk.CTkLabel(
            text_frame,
            text="",
            font=("Segoe UI", 10),
            text_color=("#7c2d12", "#fed7aa"),
            anchor="w",
            justify="left",
            wraplength=760,
        )
        self.tax_year_message.pack(fill="x", pady=(3, 0))

        self.tax_year_action = ctk.CTkButton(
            self.tax_year_banner,
            text="OPEN SYSTEM SETTINGS",
            command=self._open_tax_year_settings,
            width=185,
            height=36,
            fg_color="#d97706",
            hover_color="#b45309",
            font=("Segoe UI", 10, "bold"),
        )
        self.tax_year_action.pack(side="right", padx=16, pady=14)
        self.tax_year_banner.pack_forget()

    def refresh_tax_year_readiness(self):
        """Load the admin-only, read-only December/January readiness state."""
        if auth.get_user_role(self.user) != "admin":
            return
        try:
            readiness = readiness_service.get_tax_year_readiness() or {}
            self.parent.after(
                0,
                lambda data=readiness: self._update_tax_year_readiness(data),
            )
        except Exception:
            # Connectivity failures are already shown by the global status bar.
            # Never turn a network problem into a false billing warning.
            return

    def _update_tax_year_readiness(self, readiness):
        if not self.tax_year_banner.winfo_exists():
            return
        if not readiness.get("season_active") or not readiness.get("action_required"):
            self.tax_year_banner.pack_forget()
            return

        severity = readiness.get("severity", "warning")
        is_error = severity == "error"
        accent = "#dc2626" if is_error else "#d97706"
        panel = ("#fef2f2", "#3b1515") if is_error else ("#fff7ed", "#3b2413")
        self._tax_year_recommended_tab = readiness.get(
            "recommended_tab", "Database & Backup"
        )
        self.tax_year_banner.configure(fg_color=panel, border_color=accent)
        self.tax_year_title.configure(
            text=readiness.get("title", "New Tax Year Readiness"),
            text_color=accent,
        )
        self.tax_year_message.configure(text=readiness.get("message", ""))
        self.tax_year_action.configure(
            text=(
                "OPEN TAX POLICY"
                if self._tax_year_recommended_tab == "Tax Policy"
                else "OPEN BILLING TOOLS"
            ),
            fg_color=accent,
            hover_color="#991b1b" if is_error else "#b45309",
        )
        self.tax_year_banner.pack(
            fill="x",
            pady=(0, 20),
            before=self.stats_frame,
        )

    def _open_tax_year_settings(self):
        top = self.parent.winfo_toplevel()
        from ui.system_admin import SystemAdminPage

        top.sidebar._set_active("settings")
        top.load_page(SystemAdminPage)
        tab_name = (
            "Tax Policy"
            if self._tax_year_recommended_tab == "Tax Policy"
            else tr("admin.tabs.db")
        )
        top.current_page.tabview.set(tab_name)

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
        card = ctk.CTkFrame(
            parent,
            height=120,
            border_width=1,
            border_color=(
                ModernTheme.BORDER_DARK
                if ctk.get_appearance_mode().lower() == "dark"
                else ModernTheme.BORDER_LIGHT
            ),
        )
        card.grid(row=0, column=col, padx=10, sticky="nsew")

        ctk.CTkLabel(
            card,
            text=title,
            font=ModernTheme.BODY_BOLD,
            text_color=(
                ModernTheme.TEXT_SUB_DARK
                if ctk.get_appearance_mode().lower() == "dark"
                else ModernTheme.TEXT_SUB_LIGHT
            ),
        ).pack(pady=(20, 5))
        val_label = ctk.CTkLabel(
            card, text=value, font=ModernTheme.H2, text_color=color
        )
        val_label.pack(pady=(0, 20))

        # Entrance Animation
        card.after(
            100 + (col * 100),
            lambda: WidgetAnimator.pulse(
                card, card.cget("fg_color"), ModernTheme.PRIMARY_HOVER, 200
            ),
        )

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
        self._show_loading()
        self._backup_status_loaded = False
        threading.Thread(target=self.refresh_data, daemon=True).start()
        threading.Thread(target=self.refresh_backup_status, daemon=True).start()
        threading.Thread(target=self.refresh_tax_year_readiness, daemon=True).start()
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
            recent_rows = []
            recent_error = None
            get_recent = self.callbacks.get("get_recent")
            if callable(get_recent):
                try:
                    recent_rows = get_recent(6) or []
                except Exception as exc:
                    from utils import log_error_to_file

                    log_error_to_file("Dashboard recent payments fetch failed", exc)
                    recent_error = str(exc)
            self.parent.after(
                0,
                lambda: self._update_ui(
                    summary, trend_rows, recent_rows, recent_error
                ),
            )
        except Exception as e:
            print(f"Dashboard refresh error: {e}")
            self.parent.after(0, self._hide_loading)

    def _update_ui(self, summary, trend_rows, recent_rows, recent_error=None):
        self._hide_loading()
        if not self.stat_cards["total_properties"].winfo_exists():
            return

        self.stat_cards["total_properties"].configure(
            text=str(summary.get("total_properties", 0))
        )
        self.stat_cards["collections_today"].configure(
            text=f"P {float(summary.get('collections_today', 0) or 0):,.2f}"
        )
        self.stat_cards["receipts_today"].configure(
            text=f"{int(summary.get('receipts_today', 0) or 0):,}"
        )
        self.stat_cards["collections_month"].configure(
            text=f"P {float(summary.get('collections_month', 0) or 0):,.2f}"
        )

        months = [_dashboard_month_label(row.get("month")) for row in trend_rows]
        totals = [row["total"] for row in trend_rows]
        self.bar_chart.draw(months, totals, chart_type="bar")
        self._render_recent_collections(recent_rows, load_error=recent_error)

        b = summary.get("backup")
        if b:
            self._update_backup_ui(b)

        # Update Infrastructure Health (New Phase 4 Hardening)
        stats = summary.get("infra_stats")
        if stats:
            self._update_infra_ui(stats)

        show_toast(
            self.parent.winfo_toplevel(), "Dashboard data refreshed", type="info"
        )

    def _expire_backup_loading(self):
        """Guarantees the backup card never remains in an endless loading state."""
        if not self._backup_status_loaded:
            self._show_backup_status_error(
                "The server did not answer the backup health check within 15 seconds."
            )

    def refresh_backup_status(self):
        """Loads backup health independently so a slow check cannot block the dashboard."""
        try:
            status = system.get_backup_verification_status() or {}
            self.parent.after(0, lambda b=status: self._update_backup_ui(b))
        except Exception as exc:
            self.parent.after(
                0, lambda message=str(exc): self._show_backup_status_error(message)
            )

    def _backup_color(self, value, is_running=False):
        upper_val = str(value or "").upper()
        if is_running:
            return "#f59e0b"
        if any(
            word in upper_val
            for word in ("FAILED", "ERROR", "ISSUE", "UNAVAILABLE", "MISSING")
        ):
            return "#e74c3c"
        if any(word in upper_val for word in ("SUCCESS", "OK", "PROTECTED")) or (
            ":" in upper_val and "READY:" not in upper_val
        ):
            return ModernTheme.SUCCESS
        return "gray"

    def _update_backup_ui(self, backup):
        if not self.backup_card.winfo_exists():
            return
        self._backup_status_loaded = True
        is_running = bool(backup.get("is_running"))
        for key, fallback in (
            ("local", "Status unavailable"),
            ("usb", "Status unavailable"),
            ("cloud", "Status unavailable"),
            ("verify", "Status unavailable"),
        ):
            field = "last_verify" if key == "verify" else f"last_{key}"
            value = backup.get(field, fallback)
            self.backup_labels[key].configure(
                text=value, text_color=self._backup_color(value, is_running)
            )

        summary_text = backup.get("storage_status") or "Backup health unavailable"
        checked_at = backup.get("checked_at") or "unknown time"
        last_backup = backup.get("last_backup") or "No recorded backup"
        checksum = backup.get("last_checksum_short") or "None"
        self.backup_summary_lbl.configure(
            text=summary_text, text_color=self._backup_color(summary_text, is_running)
        )
        self.backup_detail_lbl.configure(
            text=f"Latest: {last_backup}   |   Checksum: {checksum}   |   Checked: {checked_at}"
        )

    def _show_backup_status_error(self, message):
        if not self.backup_card.winfo_exists():
            return
        self._backup_status_loaded = True
        for label in self.backup_labels.values():
            label.configure(text="Unavailable", text_color="#e74c3c")
        self.backup_summary_lbl.configure(
            text="Backup status unavailable", text_color="#e74c3c"
        )
        detail = (
            "The server did not answer the backup health check within 15 seconds."
            if "timed out" in message.lower()
            else message
        )
        self.backup_detail_lbl.configure(text=detail)

    def _update_infra_ui(self, stats):
        """Updates the new infrastructure health indicators."""
        if not hasattr(self, "infra_section"):
            self._setup_infra_section()

        p = stats.get("pool", {})
        c = stats.get("cache", {})

        self.pool_lbl.configure(
            text=f"POOL: {p.get('active', 0)} ACTIVE | {p.get('idle', 0)} IDLE | {p.get('overflow', 0)} OVERFLOW"
        )
        self.cache_lbl.configure(
            text=f"CACHE: {c.get('items', 0)} ITEMS | NAMESPACES: {', '.join(c.get('namespaces', []))}"
        )

        # Color coding for pool health
        if p.get("overflow", 0) > 0:
            self.pool_lbl.configure(text_color="#e67e22")
        elif p.get("active", 0) > 40:
            self.pool_lbl.configure(text_color="#e74c3c")
        else:
            self.pool_lbl.configure(text_color="#2ecc71")

    def _setup_infra_section(self):
        """Creates the layout for infra diagnostics."""
        self.infra_section = ctk.CTkFrame(self.container, fg_color="transparent")
        self.infra_section.pack(fill="x", pady=(0, 20))

        f = ctk.CTkFrame(self.infra_section, border_width=1, border_color="#34495e")
        f.pack(fill="x")

        ctk.CTkLabel(
            f,
            text="🏛️ INFRASTRUCTURE HEALTH (REAL-TIME)",
            font=("Segoe UI", 10, "bold"),
            text_color="gray",
        ).pack(pady=(10, 5), padx=20, anchor="w")

        inner = ctk.CTkFrame(f, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=(0, 10))

        self.pool_lbl = ctk.CTkLabel(
            inner,
            text="POOL: LOADING...",
            font=("Segoe UI", 11, "bold"),
            text_color="#2ecc71",
        )
        self.pool_lbl.pack(side="left")

        self.cache_lbl = ctk.CTkLabel(
            inner, text="CACHE: LOADING...", font=("Segoe UI", 11), text_color="gray"
        )
        self.cache_lbl.pack(side="right")
