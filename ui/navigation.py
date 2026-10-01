import customtkinter as ctk
import api_clients.auth_service as auth
from theme_manager import ModernTheme
from utils import tr, LocalizationManager
from ui.accessibility import bind_keyboard_activation

# ---------------------------------------------------------------------------
# Icon map — one icon per nav item key
# ---------------------------------------------------------------------------
NAV_ICONS = {
    "dashboard": "🏠",
    "property": "🏢",
    "portfolios": "\U0001f5c2",
    "ledger": "📋",
    "delinquencies": "⚠️",
    "compliant": "✅",
    "reports": "📊",
    "analytics": "📈",
    "assessment": "📜",
    "audit": "🔍",
    "health": "💻",
    "settings": "⚙️",
    "help": "❓",
    "rate_limiting": "🛑",
}

# Navigation colors deliberately use explicit light/dark pairs so inactive
# rows remain visible as controls in either appearance mode.  The active blue
# is the existing WCAG-AA surface token used throughout the desktop client.
NAV_IDLE_BG = ("#eef3f8", "#172338")
NAV_IDLE_HOVER = ("#dde8f2", "#22334d")
NAV_IDLE_BORDER = ("#d5e0eb", "#2b405c")
NAV_IDLE_TEXT = ("#24364b", "#dbeafe")
NAV_ACTIVE_BG = (ModernTheme.PRIMARY_SURFACE, ModernTheme.PRIMARY_SURFACE)


class NavigationSidebar(ctk.CTkFrame):
    def __init__(self, parent, user_data, username, callbacks):
        super().__init__(
            parent,
            width=260,
            corner_radius=0,
            fg_color=("#f8fafc", "#0b1626"),
        )
        self.user_data = user_data
        self.username = username
        self.callbacks = callbacks
        self._active_key = None  # key of the currently active nav item
        self._nav_items = {}  # key → {"btn": btn, "command": fn}

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
        self.logout_btn = ctk.CTkButton(
            self,
            text=f"⏻  {tr('dashboard.nav.logout').upper()}",
            fg_color=ModernTheme.DANGER_SURFACE,
            hover_color=ModernTheme.DANGER_SURFACE_HOVER,
            command=self.callbacks["logout"],
            font=("Segoe UI", 13, "bold"),
            height=44,
            corner_radius=8,
            border_width=1,
            border_color=(ModernTheme.DANGER_SURFACE, "#ef4444"),
        )
        self.logout_btn.pack(side="bottom", pady=(0, 20), padx=20, fill="x")
        bind_keyboard_activation(
            self.logout_btn,
            self.callbacks["logout"],
            focus_color=ModernTheme.FOCUS_RING,
        )

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
            id_fr,
            width=40,
            height=40,
            corner_radius=20,
            fg_color=ModernTheme.PRIMARY_SURFACE,
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
            text_color=(ModernTheme.PRIMARY_SURFACE, ModernTheme.PRIMARY),
            anchor="w",
        ).pack(fill="x")

        # Theme / language toggles
        toggle_fr = ctk.CTkFrame(card, fg_color="transparent")
        toggle_fr.pack(fill="x", padx=8, pady=(0, 8))

        self.theme_btn = ctk.CTkButton(
            toggle_fr,
            text="🌙  Theme  ⌄",
            command=self.callbacks["toggle_theme"],
            width=104,
            height=32,
            fg_color=("#e6edf5", "#14243a"),
            text_color=("#334155", "#93c5fd"),
            font=("Segoe UI", 11, "bold"),
            hover_color=("#d7e3ef", "#203653"),
            corner_radius=7,
        )
        self.theme_btn.pack(side="left", fill="x", expand=True, padx=(0, 3))
        bind_keyboard_activation(
            self.theme_btn,
            self.callbacks["toggle_theme"],
            focus_color=ModernTheme.FOCUS_RING,
        )

        current_lang = LocalizationManager()._current_locale.upper()
        self.language_btn = ctk.CTkButton(
            toggle_fr,
            text=f"🌐  Language: {current_lang}  ⌄",
            command=self.callbacks["toggle_language"],
            height=32,
            fg_color=("#e6edf5", "#14243a"),
            text_color=("#334155", "#93c5fd"),
            font=("Segoe UI", 11, "bold"),
            hover_color=("#d7e3ef", "#203653"),
            corner_radius=7,
        )
        self.language_btn.pack(side="left", fill="x", expand=True, padx=(3, 0))
        bind_keyboard_activation(
            self.language_btn,
            self.callbacks["toggle_language"],
            focus_color=ModernTheme.FOCUS_RING,
        )

    # -----------------------------------------------------------------------
    # Nav links
    # -----------------------------------------------------------------------

    def _setup_nav_links(self):
        from ui.ledger import LedgerPage
        from ui.reports import ReportsPage
        from ui.analytics_dashboard import AnalyticsDashboardPage
        from ui.assessment_roll import AssessmentRollPage
        from ui.audit_trail import AuditTrailPage
        from ui.system_admin import SystemAdminPage
        from ui.dashboard_home import DashboardHomePage
        from ui.help_page import SystemHelpPage
        from ui.delinquency_dashboard import DelinquencyDashboardPage
        from ui.compliant_dashboard import CompliantDashboardPage
        from ui.portfolio import PortfolioPage

        self._section_label("MAIN")

        self._add_nav(
            "dashboard",
            tr("dashboard.nav.dashboard"),
            lambda: self._navigate("dashboard", DashboardHomePage),
        )

        if auth.has_permission(self.user_data, "property_view"):
            self._add_nav(
                "assessment",
                tr("dashboard.nav.assessment"),
                lambda: self._navigate("assessment", AssessmentRollPage),
            )
            self._add_nav(
                "portfolios",
                "Property Portfolios",
                lambda: self._navigate("portfolios", PortfolioPage),
            )

        if auth.has_permission(self.user_data, "ledger_view"):
            self._add_nav(
                "ledger",
                tr("dashboard.nav.ledger"),
                lambda: self._navigate("ledger", LedgerPage),
            )

        self._add_nav(
            "delinquencies",
            tr("dashboard.nav.delinquencies"),
            lambda: self._navigate("delinquencies", DelinquencyDashboardPage),
        )

        # Compliant Properties — visible to all roles with property_view permission
        if auth.has_permission(self.user_data, "property_view"):
            self._add_nav(
                "compliant",
                "Compliant Properties",
                lambda: self._navigate("compliant", CompliantDashboardPage),
            )

        # ── Section label ────────────────────────────────────────────────────
        self._section_label("REPORTS & TOOLS")

        if auth.has_permission(self.user_data, "report_view"):
            self._add_nav(
                "reports",
                tr("dashboard.nav.reports"),
                lambda: self._navigate("reports", ReportsPage),
            )
            self._add_nav(
                "analytics",
                tr("dashboard.nav.analytics"),
                lambda: self._navigate("analytics", AnalyticsDashboardPage),
            )

        if any(
            auth.has_permission(self.user_data, p)
            for p in ["manage_users", "view_logs", "recycle_manage", "backup_restore"]
        ):
            self._add_nav(
                "settings",
                tr("dashboard.nav.settings"),
                lambda: self._navigate("settings", SystemAdminPage),
            )

        # ── Section label ────────────────────────────────────────────────────
        self._section_label("SUPPORT")

        self._add_nav(
            "help",
            tr("dashboard.nav.help"),
            lambda: self._navigate("help", SystemHelpPage),
        )

        # Activate dashboard by default
        self._set_active("dashboard")

    def _section_label(self, text):
        ctk.CTkLabel(
            self.nav_scroll,
            text=text,
            font=("Segoe UI", 9, "bold"),
            text_color=("#64748b", "#7890ad"),
            anchor="w",
        ).pack(fill="x", padx=18, pady=(14, 5))

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
            fg_color=NAV_IDLE_BG,
            text_color=NAV_IDLE_TEXT,
            hover_color=NAV_IDLE_HOVER,
            font=("Segoe UI", 13),
            height=42,
            corner_radius=8,
            border_width=1,
            border_color=NAV_IDLE_BORDER,
            command=command,
        )
        btn.pack(fill="x", padx=14, pady=2)
        bind_keyboard_activation(
            btn,
            command,
            focus_color=ModernTheme.FOCUS_RING,
        )

        self._nav_items[key] = {"btn": btn, "command": command}
        return btn

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
                fg_color=NAV_IDLE_BG,
                text_color=NAV_IDLE_TEXT,
                hover_color=NAV_IDLE_HOVER,
                font=("Segoe UI", 13),
                border_width=1,
                border_color=NAV_IDLE_BORDER,
            )

        self._active_key = key

        if key not in self._nav_items:
            return

        btn = self._nav_items[key]["btn"]

        # Active style: accent background + white text + bold
        btn.configure(
            fg_color=NAV_ACTIVE_BG,
            text_color=("white", "white"),
            hover_color=(ModernTheme.PRIMARY_SURFACE_HOVER,) * 2,
            font=("Segoe UI", 13, "bold"),
            border_width=1,
            border_color=(ModernTheme.PRIMARY, ModernTheme.PRIMARY),
        )

    # -----------------------------------------------------------------------
    # Legacy compatibility — kept so any code that calls create_nav_btn still works
    # -----------------------------------------------------------------------

    def create_nav_btn(self, text, command):
        """Deprecated — use _add_nav() instead. Kept for backwards compatibility."""
        key = text.lower().replace(" ", "_")
        return self._add_nav(key, text, command)
