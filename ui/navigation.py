import customtkinter as ctk
import api_clients.auth_service as auth
from theme_manager import ModernTheme
from utils import tr, LocalizationManager

# ---------------------------------------------------------------------------
# Icon map — one icon per nav item key
# ---------------------------------------------------------------------------
NAV_ICONS = {
    "dashboard":     "🏠",
    "property":      "🏘️",
    "ledger":        "📋",
    "delinquencies": "⚠️",
    "reports":       "📊",
    "analytics":     "📈",
    "assessment":    "📜",
    "audit":         "🔍",
    "health":        "💻",
    "settings":      "⚙️",
    "help":          "❓",
}


class NavigationSidebar(ctk.CTkFrame):
    def __init__(self, parent, user_data, username, callbacks):
        super().__init__(parent, width=260, corner_radius=0)
        self.user_data = user_data
        self.username = username
        self.callbacks = callbacks
        self._active_key = None          # key of the currently active nav item
        self._nav_items = {}             # key → {"btn": btn, "command": fn}

        self.setup_ui()

    # -----------------------------------------------------------------------
    # Layout
    # -----------------------------------------------------------------------

    def setup_ui(self):
        # ── Brand header ────────────────────────────────────────────────────
        header_fr = ctk.CTkFrame(self, fg_color="transparent")
        header_fr.pack(fill="x", pady=(28, 12), padx=20)

        ctk.CTkLabel(
            header_fr,
            text="REVENUE SYSTEM",
            font=("Segoe UI", 18, "bold"),
            text_color="#3498db",
            anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            header_fr,
            text="MUNICIPAL PORTAL",
            font=("Segoe UI", 9, "bold"),
            text_color="gray",
            anchor="w",
        ).pack(fill="x")

        ctk.CTkFrame(self, height=1, fg_color="gray30").pack(
            fill="x", padx=20, pady=(0, 14)
        )

        # ── Profile card ────────────────────────────────────────────────────
        self._setup_profile_card()

        ctk.CTkFrame(self, height=1, fg_color="gray30").pack(
            fill="x", padx=20, pady=(0, 8)
        )

        # ── Nav links (scrollable) ───────────────────────────────────────────
        self.nav_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.nav_scroll.pack(fill="both", expand=True, padx=0)

        self._setup_nav_links()

        # ── Logout ──────────────────────────────────────────────────────────
        ctk.CTkButton(
            self,
            text=f"  {tr('dashboard.nav.logout')}",
            fg_color="#e74c3c",
            hover_color="#c0392b",
            command=self.callbacks["logout"],
            font=("Segoe UI", 13, "bold"),
            height=42,
            corner_radius=8,
        ).pack(side="bottom", pady=(0, 20), padx=20, fill="x")

    def _setup_profile_card(self):
        card = ctk.CTkFrame(
            self,
            fg_color=("#eef1f5", "#1a2634"),
            corner_radius=12,
            border_width=1,
            border_color=("#d1d8e0", "#2c3e50"),
        )
        card.pack(fill="x", padx=16, pady=(0, 14))

        id_fr = ctk.CTkFrame(card, fg_color="transparent")
        id_fr.pack(fill="x", padx=12, pady=(12, 8))

        # Avatar circle
        avatar_val = self.username[0].upper() if self.username else "U"
        avatar_fr = ctk.CTkFrame(
            id_fr, width=40, height=40, corner_radius=20, fg_color=ModernTheme.PRIMARY
        )
        avatar_fr.pack(side="left", padx=(0, 10))
        avatar_fr.pack_propagate(False)
        ctk.CTkLabel(
            avatar_fr,
            text=avatar_val,
            font=("Segoe UI", 16, "bold"),
            text_color="white",
        ).place(relx=0.5, rely=0.5, anchor="center")

        info_fr = ctk.CTkFrame(id_fr, fg_color="transparent")
        info_fr.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(
            info_fr,
            text=self.username.lower(),
            font=("Segoe UI", 13, "bold"),
            anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            info_fr,
            text=auth.get_user_role(self.user_data).upper(),
            font=("Segoe UI", 9, "bold"),
            text_color=ModernTheme.PRIMARY,
            anchor="w",
        ).pack(fill="x")

        # Theme / language toggles
        toggle_fr = ctk.CTkFrame(card, fg_color="transparent")
        toggle_fr.pack(fill="x", padx=8, pady=(0, 8))

        ctk.CTkButton(
            toggle_fr,
            text="🌓",
            command=self.callbacks["toggle_theme"],
            width=36,
            height=28,
            fg_color="transparent",
            text_color=ModernTheme.TEXT_GRAY,
            font=("Segoe UI", 13),
            hover_color=("#d1d8e0", "#2c3e50"),
        ).pack(side="left", padx=2)

        current_lang = LocalizationManager()._current_locale.upper()
        ctk.CTkButton(
            toggle_fr,
            text=f"🌏 {current_lang}",
            command=self.callbacks["toggle_language"],
            height=28,
            fg_color="transparent",
            text_color=ModernTheme.TEXT_GRAY,
            font=("Segoe UI", 10, "bold"),
            hover_color=("#d1d8e0", "#2c3e50"),
        ).pack(side="left", fill="x", expand=True)

    # -----------------------------------------------------------------------
    # Nav links
    # -----------------------------------------------------------------------

    def _setup_nav_links(self):
        from ui.property import PropertyPage
        from ui.ledger import LedgerPage
        from ui.reports import ReportsPage
        from ui.analytics_dashboard import AnalyticsDashboardPage
        from ui.assessment_roll import AssessmentRollPage
        from ui.audit_trail import AuditTrailPage
        from ui.system_admin import SystemAdminPage
        from ui.dashboard_home import DashboardHomePage
        from ui.help_page import SystemHelpPage
        from ui.delinquency_dashboard import DelinquencyDashboardPage

        self._add_nav("dashboard", tr("dashboard.nav.dashboard"),
                      lambda: self._navigate("dashboard", DashboardHomePage))

        if auth.has_permission(self.user_data, "property_view"):
            self._add_nav("property", tr("dashboard.nav.property"),
                          lambda: self._navigate("property", PropertyPage))

        if auth.has_permission(self.user_data, "ledger_view"):
            self._add_nav("ledger", tr("dashboard.nav.ledger"),
                          lambda: self._navigate("ledger", LedgerPage))

        self._add_nav("delinquencies", tr("dashboard.nav.delinquencies"),
                      lambda: self._navigate("delinquencies", DelinquencyDashboardPage))

        # ── Section label ────────────────────────────────────────────────────
        self._section_label("COLLECTION")

        if auth.has_permission(self.user_data, "report_view"):
            self._add_nav("reports", tr("dashboard.nav.reports"),
                          lambda: self._navigate("reports", ReportsPage))
            self._add_nav("analytics", tr("dashboard.nav.analytics"),
                          lambda: self._navigate("analytics", AnalyticsDashboardPage))

        if auth.has_permission(self.user_data, "property_view"):
            self._add_nav("assessment", tr("dashboard.nav.assessment"),
                          lambda: self._navigate("assessment", AssessmentRollPage))

        if auth.has_permission(self.user_data, "view_logs"):
            self._add_nav("audit", tr("dashboard.nav.audit"),
                          lambda: self._navigate("audit", AuditTrailPage))

        if any(auth.has_permission(self.user_data, p)
               for p in ["manage_users", "view_logs"]):
            from ui.system_health import SystemHealthPage
            self._add_nav("health", "SYSTEM HEALTH",
                          lambda: self._navigate("health", SystemHealthPage))
            self._add_nav("settings", tr("dashboard.nav.settings"),
                          lambda: self._navigate("settings", SystemAdminPage))

        # ── Section label ────────────────────────────────────────────────────
        self._section_label("SYSTEM HELP")

        self._add_nav("help", tr("dashboard.nav.help"),
                      lambda: self._navigate("help", SystemHelpPage))

        # Activate dashboard by default
        self._set_active("dashboard")

    def _section_label(self, text):
        ctk.CTkLabel(
            self.nav_scroll,
            text=text,
            font=("Segoe UI", 9, "bold"),
            text_color=("gray50", "gray50"),
            anchor="w",
        ).pack(fill="x", padx=20, pady=(16, 4))

    # -----------------------------------------------------------------------
    # Nav button factory
    # -----------------------------------------------------------------------

    def _add_nav(self, key, label, command):
        icon = NAV_ICONS.get(key, "•")
        full_text = f"  {icon}  {label}"

        btn = ctk.CTkButton(
            self.nav_scroll,
            text=full_text,
            anchor="w",
            fg_color="transparent",
            text_color=("gray20", "gray80"),
            hover_color=("gray85", "gray25"),
            font=("Segoe UI", 13),
            height=40,
            corner_radius=8,
            border_width=0,
            command=command,
        )
        btn.pack(fill="x", padx=10, pady=2)

        self._nav_items[key] = {"btn": btn, "command": command}

    # -----------------------------------------------------------------------
    # Active state management
    # -----------------------------------------------------------------------

    def _navigate(self, key, page_class):
        self._set_active(key)
        self.callbacks["load_page"](page_class)

    def _set_active(self, key):
        # Reset previously active button
        if self._active_key and self._active_key in self._nav_items:
            prev = self._nav_items[self._active_key]["btn"]
            prev.configure(
                fg_color="transparent",
                text_color=("gray20", "gray80"),
                font=("Segoe UI", 13),
            )

        self._active_key = key

        if key not in self._nav_items:
            return

        btn = self._nav_items[key]["btn"]

        # Active style: accent background + white text + bold
        btn.configure(
            fg_color=(ModernTheme.PRIMARY, ModernTheme.PRIMARY),
            text_color=("white", "white"),
            font=("Segoe UI", 13, "bold"),
        )

    # -----------------------------------------------------------------------
    # Legacy compatibility — kept so any code that calls create_nav_btn still works
    # -----------------------------------------------------------------------

    def create_nav_btn(self, text, command):
        """Deprecated — use _add_nav() instead. Kept for backwards compatibility."""
        key = text.lower().replace(" ", "_")
        self._add_nav(key, text, command)
