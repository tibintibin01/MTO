import customtkinter as ctk
import api_clients.auth_service as auth
from theme_manager import ModernTheme
from utils import tr, LocalizationManager

class NavigationSidebar(ctk.CTkFrame):
    def __init__(self, parent, user_data, username, callbacks):
        super().__init__(parent, width=280, corner_radius=0)
        self.user_data = user_data
        self.username = username
        self.callbacks = callbacks # Dict of functions: load_page, toggle_theme, toggle_language, logout
        
        self.setup_ui()

    def setup_ui(self):
        # Header
        header_fr = ctk.CTkFrame(self, fg_color="transparent")
        header_fr.pack(fill="x", pady=(40, 20), padx=20)

        ctk.CTkLabel(header_fr, text="REVENUE SYSTEM", font=("Segoe UI", 20, "bold"), text_color="#3498db", anchor="w").pack(fill="x")
        ctk.CTkLabel(header_fr, text="MUNICIPAL PORTAL", font=("Segoe UI", 10, "bold"), text_color="gray", anchor="w").pack(fill="x")
        
        line = ctk.CTkFrame(self, height=1, fg_color="gray30")
        line.pack(fill="x", padx=30, pady=(0, 20))

        # Profile Card
        self.setup_profile_card()

        # Navigation Buttons (Scrollable)
        self.nav_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.nav_scroll.pack(fill="both", expand=True, padx=5)
        self.nav_btns = {}

        self.setup_nav_links()

        # Logout at bottom
        self.logout_btn = ctk.CTkButton(
            self, text=tr("dashboard.nav.logout"), fg_color="#e74c3c", hover_color="#c0392b",
            command=self.callbacks["logout"], font=ModernTheme.BUTTON
        )
        self.logout_btn.pack(side="bottom", pady=30, padx=20, fill="x")

    def setup_profile_card(self):
        card = ctk.CTkFrame(self, fg_color=("#f1f2f6", "#1a2634"), corner_radius=15, border_width=1, border_color=("#d1d8e0", "#2c3e50"))
        card.pack(fill="x", padx=20, pady=(0, 25))

        id_fr = ctk.CTkFrame(card, fg_color="transparent")
        id_fr.pack(fill="x", padx=15, pady=15)

        avatar_val = self.username[0].upper() if self.username else "U"
        avatar_fr = ctk.CTkFrame(id_fr, width=42, height=42, corner_radius=21, fg_color=ModernTheme.PRIMARY)
        avatar_fr.pack(side="left", padx=(0, 12))
        avatar_fr.pack_propagate(False)
        ctk.CTkLabel(avatar_fr, text=avatar_val, font=("Segoe UI", 18, "bold"), text_color="white").place(relx=0.5, rely=0.5, anchor="center")

        info_fr = ctk.CTkFrame(id_fr, fg_color="transparent")
        info_fr.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(info_fr, text=self.username.lower(), font=("Segoe UI", 14, "bold"), anchor="w").pack(fill="x")
        ctk.CTkLabel(info_fr, text=auth.get_user_role(self.user_data).upper(), font=("Segoe UI", 9, "bold"), text_color=ModernTheme.PRIMARY, anchor="w").pack(fill="x")

        toggle_fr = ctk.CTkFrame(card, fg_color="transparent")
        toggle_fr.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkButton(toggle_fr, text="🌓", command=self.callbacks["toggle_theme"], width=40, height=32, fg_color="transparent", text_color=ModernTheme.TEXT_GRAY, font=("Segoe UI", 14, "bold"), hover_color=("#d1d8e0", "#2c3e50")).pack(side="left", padx=2)
        
        current_lang = LocalizationManager()._current_locale.upper()
        ctk.CTkButton(toggle_fr, text=f"🌏 {current_lang}", command=self.callbacks["toggle_language"], height=32, fg_color="transparent", text_color=ModernTheme.TEXT_GRAY, font=("Segoe UI", 11, "bold"), hover_color=("#d1d8e0", "#2c3e50")).pack(side="left", fill="x", expand=True)

    def setup_nav_links(self):
        from ui.property import PropertyPage
        from ui.ledger import LedgerPage
        from ui.reports import ReportsPage
        from ui.analytics_dashboard import AnalyticsDashboardPage
        from ui.assessment_roll import AssessmentRollPage
        from ui.audit_trail import AuditTrailPage
        from ui.system_admin import SystemAdminPage
        from ui.dashboard_home import DashboardHomePage
        from ui.help_page import SystemHelpPage

        self.create_nav_btn(tr("dashboard.nav.dashboard"), lambda: self.callbacks["load_page"](DashboardHomePage))

        if auth.has_permission(self.user_data, "property_view"):
            self.create_nav_btn(tr("dashboard.nav.property"), lambda: self.callbacks["load_page"](PropertyPage))
        if auth.has_permission(self.user_data, "ledger_view"):
            self.create_nav_btn(tr("dashboard.nav.ledger"), lambda: self.callbacks["load_page"](LedgerPage))

        from ui.delinquency_dashboard import DelinquencyDashboardPage
        self.create_nav_btn(tr("dashboard.nav.delinquencies"), lambda: self.callbacks["load_page"](DelinquencyDashboardPage))

        ctk.CTkLabel(self.nav_scroll, text=tr("reports.title").split()[0], font=("Segoe UI", 10, "bold"), text_color="gray").pack(pady=(20, 5))

        if auth.has_permission(self.user_data, "report_view"):
            self.create_nav_btn(tr("dashboard.nav.reports"), lambda: self.callbacks["load_page"](ReportsPage))
            self.create_nav_btn(tr("dashboard.nav.analytics"), lambda: self.callbacks["load_page"](AnalyticsDashboardPage))

        if auth.has_permission(self.user_data, "property_view"):
            self.create_nav_btn(tr("dashboard.nav.assessment"), lambda: self.callbacks["load_page"](AssessmentRollPage))

        if auth.has_permission(self.user_data, "view_logs"):
            self.create_nav_btn(tr("dashboard.nav.audit"), lambda: self.callbacks["load_page"](AuditTrailPage))

        if any(auth.has_permission(self.user_data, p) for p in ["manage_users", "view_logs"]):
            from ui.system_health import SystemHealthPage
            self.create_nav_btn("📊 SYSTEM HEALTH", lambda: self.callbacks["load_page"](SystemHealthPage))
            self.create_nav_btn(tr("dashboard.nav.settings"), lambda: self.callbacks["load_page"](SystemAdminPage))


        ctk.CTkLabel(self.nav_scroll, text=tr("dashboard.nav.help").upper(), font=("Segoe UI", 10, "bold"), text_color="gray").pack(pady=(20, 5))
        self.create_nav_btn(tr("dashboard.nav.help"), lambda: self.callbacks["load_page"](SystemHelpPage))

    def create_nav_btn(self, text, command):
        btn = ctk.CTkButton(
            self.nav_scroll, text=text, command=command, anchor="w", fg_color="transparent",
            text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"), font=ModernTheme.BODY, height=45
        )
        btn.pack(fill="x", padx=10, pady=2)
        self.nav_btns[text] = btn
