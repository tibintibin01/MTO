import customtkinter as ctk
from tkinter import messagebox
import api_clients.auth_service as auth
from ui.users import UserAccessPage
from ui.logs import AuditLogsPage
from ui.recycle import RecycleBinPage
from ui.batch_delete_payments import BatchDeletePaymentsModal
from ui_components import ErrorDialog, show_toast
from theme_manager import ModernTheme
from utils import tr

# Module-level variable — survives page navigation because the module
# stays loaded even when SystemAdminPage is destroyed and recreated.
_active_sync_job_id: str | None = None


# ---------------------------------------------------------------------------
# Premium dialog helpers used by the DB tab
# ---------------------------------------------------------------------------

def _make_premium_dialog(parent, width=460, height=None):
    """Creates a borderless, dark, centered CTkToplevel."""
    dialog = ctk.CTkToplevel(parent)
    dialog.title("")
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    dialog.grab_set()
    dialog.overrideredirect(True)

    dialog.update_idletasks()
    dw = width
    dh = height or 260
    px = parent.winfo_rootx() + (parent.winfo_width() // 2) - (dw // 2)
    py = parent.winfo_rooty() + (parent.winfo_height() // 2) - (dh // 2)
    dialog.geometry(f"{dw}x{dh}+{px}+{py}")

    outer = ctk.CTkFrame(
        dialog,
        fg_color=("#1e2530", "#1e2530"),
        corner_radius=16,
        border_width=1,
        border_color=("#2c3e50", "#2c3e50"),
    )
    outer.pack(fill="both", expand=True, padx=2, pady=2)
    return dialog, outer



def _show_portal_publish_result(parent, title, message, accent="#10b981"):
    """Shows a clear publish result without relying on native message boxes."""
    dialog, outer = _make_premium_dialog(parent, width=500, height=290)

    ctk.CTkFrame(outer, height=5, fg_color=accent, corner_radius=0).pack(fill="x")

    body = ctk.CTkFrame(outer, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=26, pady=(22, 12))

    icon = ctk.CTkFrame(body, width=58, height=58, corner_radius=29, fg_color="#122033", border_width=2, border_color=accent)
    icon.pack(pady=(0, 12))
    icon.pack_propagate(False)
    ctk.CTkLabel(icon, text="OK", font=("Segoe UI", 15, "bold"), text_color=accent).place(relx=0.5, rely=0.5, anchor="center")

    ctk.CTkLabel(body, text=title, font=("Segoe UI", 17, "bold"), text_color="white").pack()
    ctk.CTkLabel(
        body,
        text=message,
        font=("Segoe UI", 11),
        text_color="#a8b3c7",
        justify="center",
        wraplength=430,
    ).pack(pady=(10, 0))

    ctk.CTkFrame(outer, height=1, fg_color="#2c3e50").pack(fill="x")
    btn_fr = ctk.CTkFrame(outer, fg_color="transparent")
    btn_fr.pack(fill="x", padx=20, pady=14)
    ctk.CTkButton(btn_fr, text="DONE", command=dialog.destroy, fg_color=accent, hover_color=accent, text_color="white", font=("Segoe UI", 12, "bold"), height=36, corner_radius=8, width=120).pack(side="right")
    dialog.bind("<Return>", lambda e: dialog.destroy())
    dialog.bind("<Escape>", lambda e: dialog.destroy())
    dialog.focus_force()


def _confirm_portal_publish(parent) -> bool:
    """Premium confirmation dialog for one-way public portal publishing."""
    result = {"confirmed": False}
    dialog, outer = _make_premium_dialog(parent, width=540, height=340)

    ctk.CTkFrame(outer, height=5, fg_color="#0ea5e9", corner_radius=0).pack(fill="x")

    header = ctk.CTkFrame(outer, fg_color="transparent")
    header.pack(fill="x", padx=26, pady=(22, 10))

    icon = ctk.CTkFrame(
        header,
        width=62,
        height=62,
        corner_radius=31,
        fg_color="#082f49",
        border_width=2,
        border_color="#38bdf8",
    )
    icon.pack(side="left", padx=(0, 16))
    icon.pack_propagate(False)
    ctk.CTkLabel(icon, text="WEB", font=("Segoe UI", 13, "bold"), text_color="#7dd3fc").place(relx=0.5, rely=0.5, anchor="center")

    title_fr = ctk.CTkFrame(header, fg_color="transparent")
    title_fr.pack(side="left", fill="both", expand=True)
    ctk.CTkLabel(
        title_fr,
        text="Publish Web Portal Data",
        font=("Segoe UI", 18, "bold"),
        text_color="#f8fafc",
        anchor="w",
    ).pack(fill="x")
    ctk.CTkLabel(
        title_fr,
        text="Create a public, read-only snapshot from the current office database.",
        font=("Segoe UI", 11),
        text_color="#94a3b8",
        anchor="w",
        wraplength=390,
        justify="left",
    ).pack(fill="x", pady=(4, 0))

    summary = ctk.CTkFrame(outer, fg_color="#111827", corner_radius=12, border_width=1, border_color="#1f2937")
    summary.pack(fill="x", padx=26, pady=(8, 14))

    for item_text, color in (
        ("Sanitized taxpayer data only", "#38bdf8"),
        ("The web portal cannot edit office records", "#10b981"),
        ("A checksum and publish result will be shown after completion", "#f59e0b"),
    ):
        row = ctk.CTkFrame(summary, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(10 if item_text.startswith("Sanitized") else 4, 6))
        ctk.CTkFrame(row, width=8, height=8, corner_radius=4, fg_color=color).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(row, text=item_text, font=("Segoe UI", 11), text_color="#cbd5e1", anchor="w").pack(side="left", fill="x", expand=True)

    ctk.CTkFrame(outer, height=1, fg_color="#243244").pack(fill="x")
    btn_fr = ctk.CTkFrame(outer, fg_color="transparent")
    btn_fr.pack(fill="x", padx=22, pady=16)

    def cancel():
        result["confirmed"] = False
        dialog.destroy()

    def confirm():
        result["confirmed"] = True
        dialog.destroy()

    ctk.CTkButton(
        btn_fr,
        text="CANCEL",
        command=cancel,
        width=130,
        height=40,
        corner_radius=9,
        fg_color="#1f2937",
        hover_color="#334155",
        border_width=1,
        border_color="#475569",
        text_color="#cbd5e1",
        font=("Segoe UI", 12, "bold"),
    ).pack(side="right", padx=(10, 0))
    publish_btn = ctk.CTkButton(
        btn_fr,
        text="PUBLISH PORTAL",
        command=confirm,
        width=170,
        height=40,
        corner_radius=9,
        fg_color="#0ea5e9",
        hover_color="#0284c7",
        text_color="white",
        font=("Segoe UI", 12, "bold"),
    )
    publish_btn.pack(side="right")

    dialog.bind("<Return>", lambda _e: confirm())
    dialog.bind("<Escape>", lambda _e: cancel())
    dialog.protocol("WM_DELETE_WINDOW", cancel)
    dialog.focus_force()
    publish_btn.focus_set()
    parent.wait_window(dialog)
    return result["confirmed"]

def _show_sync_info(parent, scanned, created, skipped):
    """Premium 'nothing to do' info dialog."""
    dialog, outer = _make_premium_dialog(parent, width=400, height=220)

    body = ctk.CTkFrame(outer, fg_color="transparent")
    body.pack(fill="x", padx=24, pady=(24, 16))

    icon_fr = ctk.CTkFrame(body, width=48, height=48, corner_radius=24, fg_color="#27ae60")
    icon_fr.pack(side="left", padx=(0, 16))
    icon_fr.pack_propagate(False)
    ctk.CTkLabel(icon_fr, text="✓", font=("Segoe UI", 22, "bold"), text_color="white").place(relx=0.5, rely=0.5, anchor="center")

    text_fr = ctk.CTkFrame(body, fg_color="transparent")
    text_fr.pack(side="left", fill="both", expand=True)
    ctk.CTkLabel(text_fr, text="Already Up to Date", font=("Segoe UI", 14, "bold"), text_color="white", anchor="w").pack(fill="x")
    ctk.CTkLabel(text_fr, text=f"All {scanned:,} properties have complete billing records.\nNo new records needed.", font=("Segoe UI", 10), text_color="#8b949e", anchor="w", justify="left").pack(fill="x", pady=(4, 0))

    ctk.CTkFrame(outer, height=1, fg_color="#2c3e50").pack(fill="x")
    btn_fr = ctk.CTkFrame(outer, fg_color="transparent")
    btn_fr.pack(fill="x", padx=20, pady=14)
    ctk.CTkButton(btn_fr, text="OK", command=dialog.destroy, fg_color="#27ae60", hover_color="#2ecc71", text_color="white", font=("Segoe UI", 12, "bold"), height=36, corner_radius=8, width=100).pack(side="right")
    dialog.bind("<Return>", lambda e: dialog.destroy())
    dialog.bind("<Escape>", lambda e: dialog.destroy())
    dialog.focus_set()


def _show_sync_confirm(parent, scanned, created, skipped, on_confirm):
    """Premium sync confirmation dialog with stats."""
    dialog, outer = _make_premium_dialog(parent, width=460, height=300)

    # Header row
    header = ctk.CTkFrame(outer, fg_color="transparent")
    header.pack(fill="x", padx=24, pady=(22, 0))

    icon_fr = ctk.CTkFrame(header, width=52, height=52, corner_radius=26, fg_color="#8e44ad", border_width=2, border_color="#9b59b6")
    icon_fr.pack(side="left", padx=(0, 16))
    icon_fr.pack_propagate(False)
    ctk.CTkLabel(icon_fr, text="📅", font=("Segoe UI Emoji", 22), text_color="white").place(relx=0.5, rely=0.5, anchor="center")

    title_fr = ctk.CTkFrame(header, fg_color="transparent")
    title_fr.pack(side="left", fill="both", expand=True)
    ctk.CTkLabel(title_fr, text="Billing Year Sync", font=("Segoe UI", 15, "bold"), text_color="white", anchor="w").pack(fill="x")
    ctk.CTkLabel(title_fr, text="Preview of changes before committing", font=("Segoe UI", 10), text_color="#8b949e", anchor="w").pack(fill="x", pady=(2, 0))

    # Stats cards
    stats_fr = ctk.CTkFrame(outer, fg_color="#161b22", corner_radius=10)
    stats_fr.pack(fill="x", padx=20, pady=14)
    stats_fr.grid_columnconfigure((0, 1, 2), weight=1)

    def stat_card(parent, col, label, value, color):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=0, column=col, padx=8, pady=10, sticky="nsew")
        ctk.CTkLabel(f, text=f"{value:,}", font=("Segoe UI", 18, "bold"), text_color=color).pack()
        ctk.CTkLabel(f, text=label, font=("Segoe UI", 9), text_color="#8b949e").pack()

    stat_card(stats_fr, 0, "Properties", scanned, "#3498db")
    stat_card(stats_fr, 1, "To Create", created, "#e67e22")
    stat_card(stats_fr, 2, "Skipped", skipped, "#27ae60")

    ctk.CTkLabel(outer, text=f"This will create {created:,} missing billing records covering\nunpaid years for {scanned:,} properties. This cannot be undone.", font=("Segoe UI", 10), text_color="#8b949e", justify="center").pack(padx=20, pady=(0, 10))

    ctk.CTkFrame(outer, height=1, fg_color="#2c3e50").pack(fill="x")
    btn_fr = ctk.CTkFrame(outer, fg_color="transparent")
    btn_fr.pack(fill="x", padx=20, pady=14)

    def cancel():
        dialog.destroy()

    def confirm():
        dialog.destroy()
        on_confirm()

    ctk.CTkButton(btn_fr, text="Cancel", command=cancel, fg_color="#2c3e50", hover_color="#34495e", text_color="white", font=("Segoe UI", 12, "bold"), height=36, corner_radius=8, width=110).pack(side="right", padx=(8, 0))
    ctk.CTkButton(btn_fr, text="  📅  Proceed", command=confirm, fg_color="#8e44ad", hover_color="#9b59b6", text_color="white", font=("Segoe UI", 12, "bold"), height=36, corner_radius=8, width=140).pack(side="right")

    dialog.bind("<Return>", lambda e: confirm())
    dialog.bind("<space>", lambda e: confirm())
    dialog.bind("<Escape>", lambda e: cancel())
    dialog.focus_set()


class SystemAdminPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.pages = []
        self.setup_ui()

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            self.container, text=tr("admin.title"), font=ModernTheme.H2
        ).pack(anchor="w", pady=(0, 20))

        self.tabview = ctk.CTkTabview(self.container)
        self.tabview.pack(fill="both", expand=True)

        # User Management
        if auth.has_permission(self.user, "manage_users"):
            tab = self.tabview.add(tr("admin.tabs.users"))
            self.user_page = UserAccessPage(tab, self.user)
            self.pages.append(self.user_page)

        # Audit Logs
        if auth.has_permission(self.user, "view_logs"):
            tab = self.tabview.add(tr("admin.tabs.audit"))
            self.logs_page = AuditLogsPage(tab, self.user)
            self.pages.append(self.logs_page)

        # Recycle Bin
        if auth.has_permission(self.user, "recycle_manage"):
            tab = self.tabview.add(tr("admin.tabs.recycle"))
            self.recycle_page = RecycleBinPage(tab, self.user)
            self.pages.append(self.recycle_page)

        # Database Tab
        if auth.has_permission(self.user, "backup_restore"):
            tab = self.tabview.add(tr("admin.tabs.db"))
            self.setup_db_tab(tab)

        # System Health and Rate Limits are admin tools; keep them inside Settings.
        if any(auth.has_permission(self.user, p) for p in ["manage_users", "view_logs"]):
            from ui.system_health import SystemHealthPage
            tab = self.tabview.add("System Health")
            self.health_page = SystemHealthPage(tab, self.user)
            self.pages.append(self.health_page)

        if auth.get_user_role(self.user).lower() == "admin":
            from ui.rate_limiting import RateLimitingPage
            tab = self.tabview.add("Rate Limits")
            self.rate_limit_page = RateLimitingPage(tab, self.user)
            self.pages.append(self.rate_limit_page)

        # Tax Policy Tab — Admin only
        if auth.has_permission(self.user, "manage_users"):
            tab = self.tabview.add("Tax Policy")
            self.setup_tax_policy_tab(tab)

    def setup_db_tab(self, parent):
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=40, pady=20)

        # Main Action Card
        card = ctk.CTkFrame(
            container,
            fg_color=("#ffffff", "#2b2b2b"),
            corner_radius=15,
            border_width=1,
            border_color=("#e0e0e0", "#333333"),
        )
        card.pack(fill="x", pady=10)

        ctk.CTkLabel(
            card,
            text=tr("admin.db.title"),
            font=ModernTheme.H3,
            text_color=ModernTheme.PRIMARY,
        ).pack(pady=(20, 5))
        ctk.CTkLabel(
            card,
            text=tr("admin.db.subtitle"),
            font=ModernTheme.BODY,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(pady=(0, 20))

        actions_fr = ctk.CTkFrame(card, fg_color="transparent")
        actions_fr.pack(fill="x", padx=24, pady=(0, 18))
        actions_fr.grid_columnconfigure((0, 1), weight=1, uniform="db_action_groups")

        button_height = 38
        grouped_button_width = 235

        def action_group(row, col, title, subtitle):
            group = ctk.CTkFrame(
                actions_fr,
                fg_color=("#f8fafc", "#111827"),
                corner_radius=12,
                border_width=1,
                border_color=("#d6dde8", "#243244"),
            )
            group.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
            group.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                group,
                text=title.upper(),
                font=("Segoe UI", 11, "bold"),
                text_color=ModernTheme.PRIMARY,
                anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 2))
            ctk.CTkLabel(
                group,
                text=subtitle,
                font=("Segoe UI", 10),
                text_color=ModernTheme.TEXT_GRAY,
                anchor="w",
                wraplength=430,
                justify="left",
            ).grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))

            btn_grid = ctk.CTkFrame(group, fg_color="transparent")
            btn_grid.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 14))
            btn_grid.grid_columnconfigure((0, 1), weight=1, uniform="db_buttons")
            return btn_grid

        backup_tools = action_group(
            0,
            0,
            "Backup & Recovery",
            "Protect the database, restore from backup, or restart the server after updates.",
        )
        data_tools = action_group(
            0,
            1,
            "Data Integrity",
            "Repair records that affect billing, payments, and reconciliation accuracy.",
        )
        publish_tools = action_group(
            1,
            0,
            "Portal Publishing",
            "Create the read-only taxpayer snapshot for the public web portal.",
        )
        correction_tools = action_group(
            1,
            1,
            "Correction Tools",
            "Use these only when investigating imports, TD formats, or payment cleanup.",
        )

        self.backup_btn = ctk.CTkButton(
            backup_tools,
            text="START HYBRID BACKUP",
            command=self.trigger_backup,
            height=button_height,
            width=grouped_button_width,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.SUCCESS,
        )
        self.backup_btn.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        self.restore_btn = ctk.CTkButton(
            backup_tools,
            text="RESTORE BACKUP",
            command=self.restore_backup,
            height=button_height,
            width=grouped_button_width,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.TEXT_GRAY,
        )
        self.restore_btn.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # Restart Server button lets admin apply updates from any client PC.
        self.restart_btn = ctk.CTkButton(
            backup_tools,
            text="RESTART SERVER",
            command=self.restart_server,
            height=button_height,
            width=grouped_button_width,
            font=ModernTheme.BUTTON,
            fg_color="#c0392b",
            hover_color="#e74c3c",
        )
        self.restart_btn.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

        self.sync_btn = ctk.CTkButton(
            data_tools,
            text="SYNC BILLING YEARS",
            command=self.sync_billing_years,
            height=button_height,
            width=grouped_button_width,
            font=ModernTheme.BUTTON,
            fg_color="#8e44ad",
            hover_color="#9b59b6",
        )
        self.sync_btn.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        self.repair_av_btn = ctk.CTkButton(
            data_tools,
            text="REPAIR BILLING AV",
            command=self.repair_billing_av,
            height=button_height,
            width=grouped_button_width,
            font=ModernTheme.BUTTON,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
        )
        self.repair_av_btn.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        self.repair_links_btn = ctk.CTkButton(
            data_tools,
            text="REPAIR PAYMENT ALLOCATION DRIFT",
            command=self.repair_payment_links,
            height=button_height,
            width=grouped_button_width,
            font=ModernTheme.BUTTON,
            fg_color="#0891b2",
            hover_color="#0e7490",
        )
        self.repair_links_btn.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

        self.portal_publish_btn = ctk.CTkButton(
            publish_tools,
            text="PUBLISH PORTAL",
            command=self.publish_portal_snapshot,
            height=button_height,
            width=grouped_button_width,
            font=ModernTheme.BUTTON,
            fg_color="#0f766e",
            hover_color="#115e59",
        )
        self.portal_publish_btn.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

        self.portal_publish_status_lbl = ctk.CTkLabel(
            publish_tools,
            text="Portal publish: not run in this session",
            font=("Segoe UI", 10),
            text_color=ModernTheme.TEXT_GRAY,
            anchor="w",
        )
        self.portal_publish_status_lbl.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 6))

        self.td_audit_btn = ctk.CTkButton(
            correction_tools,
            text="AUDIT TD NUMBERS",
            command=self.audit_td_numbers,
            height=button_height,
            width=grouped_button_width,
            font=ModernTheme.BUTTON,
            fg_color="#c0392b",
            hover_color="#e74c3c",
        )
        self.td_audit_btn.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        self.batch_del_btn = ctk.CTkButton(
            correction_tools,
            text="BATCH DELETE PAYMENTS",
            command=lambda: BatchDeletePaymentsModal(self.container, self.user),
            height=button_height,
            width=grouped_button_width,
            font=ModernTheme.BUTTON,
            fg_color="#7c3aed",
            hover_color="#6d28d9",
        )
        self.batch_del_btn.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # If a sync was running when the user navigated away, resume monitoring
        if _active_sync_job_id:
            self.sync_btn.configure(state="disabled", text="SYNCING...")
            import threading
            threading.Thread(
                target=self._resume_sync_monitoring,
                args=(_active_sync_job_id,),
                daemon=True
            ).start()

        # Status Panel
        status_fr = ctk.CTkFrame(
            container, fg_color=("#f8f9fa", "#1e1e1e"), corner_radius=12
        )
        status_fr.pack(fill="both", expand=True, pady=10)

        ctk.CTkLabel(
            status_fr,
            text=tr("admin.db.status_title"),
            font=ModernTheme.BODY_BOLD,
            text_color=ModernTheme.PRIMARY,
        ).pack(anchor="w", padx=20, pady=(15, 10))

        self.status_labels = {}
        status_items = [
            (tr("admin.db.items.latest"), "last_backup"),
            (tr("admin.db.items.verify"), "last_verify"),
            (tr("admin.db.items.checksum"), "last_checksum_short"),
            (tr("admin.db.items.storage"), "storage_status"),
        ]

        for label, key in status_items:
            row = ctk.CTkFrame(status_fr, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=5)
            # Use dynamic text color for the label
            ctk.CTkLabel(
                row,
                text=label,
                font=ModernTheme.BODY,
                text_color=ModernTheme.TEXT_GRAY,
            ).pack(side="left")
            self.status_labels[key] = ctk.CTkLabel(
                row,
                text=tr("admin.db.scanning"),
                font=ModernTheme.BODY_BOLD,
                text_color=ModernTheme.PRIMARY,
            )
            self.status_labels[key].pack(side="right", padx=(10, 20))

        self.update_status_display()

    def update_status_display(self):
        try:
            import api_clients.system_service as system_svc
            # Fetch from API to ensure we see the server's state, not the local process state
            status = system_svc.get_backup_verification_status()
            if status:
                for key, lbl in self.status_labels.items():
                    val = str(status.get(key, "Unknown") or "Unknown")
                    upper_val = val.upper()
                    if status.get("is_running"):
                        color = "#f59e0b"
                    elif any(word in upper_val for word in ("FAILED", "ERROR", "ISSUE")):
                        color = "#e74c3c"
                    elif key == "last_checksum_short" and upper_val not in ("NONE", "UNKNOWN"):
                        color = ModernTheme.SUCCESS
                    elif key in ("last_backup", "storage_status") and upper_val not in ("NEVER", "UNKNOWN", "NO VERIFIED BACKUP YET"):
                        color = ModernTheme.SUCCESS
                    elif any(word in upper_val for word in ("SUCCESS", "OK", "PASSED")) or ":" in upper_val:
                        color = ModernTheme.SUCCESS
                    else:
                        color = "#f59e0b"
                    lbl.configure(text=val, text_color=color)
        except Exception as e:
            print(f"DEBUG: Status update failed: {e}")
            pass
            
        # Refresh every 3 seconds while the widget exists
        if self.container.winfo_exists():
            self.container.after(3000, self.update_status_display)

    def trigger_backup(self):
        import threading
        import time

        if self.backup_btn.cget("state") == "disabled":
            return

        self.backup_btn.configure(
            state="disabled", text=f"🛡️ {tr('admin.db.progress')}", fg_color=ModernTheme.TEXT_GRAY
        )

        def run():
            try:
                import api_clients.system_service as system_svc

                res = system_svc.trigger_backup()
                job_id = res.get("job_id")

                if job_id:
                    deadline = time.time() + 900
                    while time.time() < deadline:
                        job = system_svc.get_job_status(job_id) or {}
                        status = str(job.get("status", "")).upper()
                        progress = int(job.get("progress") or 0)
                        progress_msg = job.get("progress_message") or "Backup queued..."

                        if self.container.winfo_exists():
                            self.container.after(
                                0,
                                lambda p=progress, m=progress_msg: self.backup_btn.configure(
                                    text=f"BACKUP {p}% - {m[:38]}"
                                )
                            )

                        if status == "COMPLETED":
                            result = job.get("result") or {}
                            msg = result.get("message") or job.get("progress_message") or "Backup completed successfully."
                            if self.container.winfo_exists():
                                self.container.after(0, lambda: self._finalize_backup(True, msg))
                            return

                        if status == "FAILED":
                            msg = job.get("error") or job.get("progress_message") or "Backup failed."
                            if self.container.winfo_exists():
                                self.container.after(0, lambda: self._finalize_backup(False, msg))
                            return

                        time.sleep(1.5)

                    if self.container.winfo_exists():
                        self.container.after(0, lambda: self._finalize_backup(False, "Backup did not finish within 15 minutes. Check System Health."))
                    return

                # Check if the UI still exists before updating
                if self.container.winfo_exists():
                    # API returns status: 'backup_started'
                    is_ok = res.get("status") == "backup_started"
                    msg = res.get("message", "Backup trigger failed")
                    self.container.after(0, lambda: self._finalize_backup(is_ok, msg))
            except Exception as e:
                err_msg = str(e)
                try:
                    if self.container.winfo_exists():
                        self.container.after(
                            0,
                            lambda: self._finalize_backup(
                                False, f"Thread Crash: {err_msg}"
                            ),
                        )
                except:
                    pass

        threading.Thread(target=run, daemon=True).start()

    def publish_portal_snapshot(self):
        import threading

        if self.portal_publish_btn.cget("state") == "disabled":
            return

        proceed = _confirm_portal_publish(self.container.winfo_toplevel())
        if not proceed:
            return

        self.portal_publish_btn.configure(state="disabled", text="PUBLISHING...")
        self.portal_publish_status_lbl.configure(
            text="Portal publish: generating snapshot and uploading...",
            text_color="#38bdf8",
        )

        def run():
            try:
                import api_clients.system_service as system_svc
                res = system_svc.publish_portal_snapshot(dry_run=False) or {}
                status = str(res.get("status") or "unknown")
                uploaded = bool(res.get("uploaded")) or status == "uploaded"
                checksum = str(res.get("checksum") or "")
                short_checksum = checksum[:12] if checksum else "None"
                records = int(res.get("record_count") or 0)
                saved_path = res.get("latest_path") or res.get("snapshot_path") or "Unknown"
                published_at = res.get("published_at") or "Unknown"
                server_msg = res.get("message", "Snapshot prepared successfully.")

                if uploaded:
                    title = "Uploaded to Web Portal"
                    accent = "#10b981"
                    status_text = f"Portal publish: uploaded | {records:,} records | checksum {short_checksum}"
                    detail = (
                        f"The public portal received the latest read-only data.\n\n"
                        f"Records: {records:,}\nChecksum: {short_checksum}\nPublished: {published_at}"
                    )
                elif status == "saved_not_uploaded":
                    title = "Saved Locally Only"
                    accent = "#f59e0b"
                    status_text = f"Portal publish: saved locally only | {records:,} records | checksum {short_checksum}"
                    detail = (
                        "The snapshot was created, but it was not pushed to the web portal because "
                        "publish URL/token is not configured on the server.\n\n"
                        f"Saved file: {saved_path}\n\n{server_msg}"
                    )
                else:
                    title = "Portal Upload Failed"
                    accent = "#ef4444"
                    status_text = f"Portal publish: failed | status {status}"
                    detail = (
                        f"The snapshot may have been saved locally, but the web portal did not confirm upload.\n\n"
                        f"Status: {status}\nRecords: {records:,}\nChecksum: {short_checksum}\n\n{server_msg}"
                    )

                def done():
                    self.portal_publish_btn.configure(state="normal", text="PUBLISH PORTAL")
                    self.portal_publish_status_lbl.configure(text=status_text, text_color=accent)
                    _show_portal_publish_result(self.container.winfo_toplevel(), title, detail, accent=accent)

                if self.container.winfo_exists():
                    self.container.after(0, done)
            except Exception as exc:
                err = str(exc)

                def failed():
                    self.portal_publish_btn.configure(state="normal", text="PUBLISH PORTAL")
                    self.portal_publish_status_lbl.configure(text="Portal publish: request failed", text_color="#ef4444")
                    ErrorDialog(self.container.winfo_toplevel(), "Portal Publish Failed", err)

                if self.container.winfo_exists():
                    self.container.after(0, failed)

        threading.Thread(target=run, daemon=True).start()

    def _finalize_backup(self, success, msg):
        self.backup_btn.configure(
            state="normal", text=f"🚀 {tr('admin.db.btn_start')}", fg_color=ModernTheme.SUCCESS
        )
        self.update_status_display()
        if success:
            show_toast(self.container.winfo_toplevel(), tr("admin.db.success"), type="success")
        else:
            ErrorDialog(self.container.winfo_toplevel(), tr("admin.db.failed"), tr("admin.db.failed_msg").replace("{msg}", msg))

    def open_backup_folder(self):
        import os
        import subprocess
        import sys

        try:
            import api_clients.system_service as system_svc
            status = system_svc.get_backup_verification_status() or {}
            path = status.get("local_dir")
        except Exception:
            path = None

        if not path:
            backup_base = os.getenv(
                "MTO_BACKUP_DIR",
                os.path.join(os.path.expanduser("~"), "mto_backups"),
            )
            path = os.path.join(backup_base, "local")

        if not os.path.exists(path):
            # Check if we are running on a remote client
            import urllib.parse
            server_ip = "127.0.0.1"
            try:
                with open("server_config.json", "r") as config_file:
                    import json
                    cfg = json.load(config_file)
                    server_url = cfg.get("server_url", "")
                    parsed = urllib.parse.urlparse(server_url)
                    server_ip = parsed.hostname or "127.0.0.1"
            except Exception:
                pass

            is_remote = server_ip not in ("localhost", "127.0.0.1", "::1")

            if is_remote:
                messagebox.showinfo(
                    "Remote Server Backup",
                    f"The backup files are stored securely on the Server PC ({server_ip}) at:\n"
                    f"{path}\n\n"
                    f"Since you are on a remote Cashier PC, you cannot open this directory directly.\n"
                    f"To view it from here, please access the files directly on the Server PC or share that folder over the office network."
                )
            else:
                messagebox.showerror("Error", f"Backup folder not found:\n{path}")
            return

        # Open the folder in the platform's file manager
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def restore_backup(self):
        from tkinter import filedialog, simpledialog
        import os

        try:
            import api_clients.system_service as system_svc
            status = system_svc.get_backup_verification_status() or {}
            initial_dir = status.get("local_dir")
        except Exception:
            initial_dir = None

        if not initial_dir:
            backup_base = os.getenv(
                "MTO_BACKUP_DIR",
                os.path.join(os.path.expanduser("~"), "mto_backups"),
            )
            initial_dir = os.path.join(backup_base, "local")

        # 1. Pick the file
        file_path = filedialog.askopenfilename(
            title=tr("admin.db.restore.title"),
            initialdir=initial_dir if os.path.exists(initial_dir) else os.path.expanduser("~"),
            filetypes=[("SQL Backup", "*.sql"), ("All Files", "*.*")]
        )
        
        if not file_path:
            return
            
        # 2. Critical Warning
        confirm = messagebox.askyesno(
            tr("admin.db.restore.warning"),
            tr("admin.db.restore.warning_msg"),
            icon="warning"
        )
        
        if not confirm:
            return
            
        # 3. Double-Lock Confirmation
        user_input = simpledialog.askstring(
            tr("admin.db.restore.verify"),
            tr("admin.db.restore.verify_msg"),
            parent=self.container
        )
        
        if user_input != "RESTORE":
            messagebox.showinfo(tr("admin.db.restore.cancelled"), tr("admin.db.restore.cancelled_msg"))
            return
            
        # 4. Trigger Restore
        self.restore_btn.configure(state="disabled", text="⏮️ RESTORING...")
        
        def run_restore():
            try:
                import api_clients.system_service as system_svc
                res = system_svc.restore_backup(file_path)
                
                if res.get("status") == "success":
                    data = res.get("data", {})
                    safety = data.get("safety_backup", "Unknown")
                    messagebox.showinfo(
                        tr("admin.db.restore.success_title"),
                        tr("admin.db.restore.success_msg").replace("{path}", file_path).replace("{safety}", safety)
                    )
                else:
                    messagebox.showerror("Restore Error", f"The server failed to restore: {res.get('detail', 'Unknown error')}")
            except Exception as e:
                messagebox.showerror("Disaster Recovery Error", f"CRITICAL FAILURE: {str(e)}")
            finally:
                if self.container.winfo_exists():
                    self.restore_btn.configure(state="normal", text="⏮️ RESTORE")

        import threading
        threading.Thread(target=run_restore, daemon=True).start()

    def restart_server(self):
        """
        Sends a restart command to the backend server.
        Use this after copying updated files to the server PC via the
        shared network folder — no physical access to the server needed.
        """
        confirm = messagebox.askyesno(
            "Restart Server",
            "This will restart the backend server.\n\n"
            "All connected users will be disconnected for ~10 seconds.\n\n"
            "Make sure you have copied your updated files first.\n\n"
            "Continue?",
            icon="warning"
        )
        if not confirm:
            return

        self.restart_btn.configure(state="disabled", text="⏳ RESTARTING...")

        def run():
            try:
                import api_clients.system_service as system_svc
                res = system_svc.restart_server()
                msg = res.get("message", "Server is restarting...")
                self.container.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Restart Initiated",
                        f"{msg}\n\nThe app will reconnect automatically.\n"
                        "If it doesn't, close and reopen the desktop app."
                    )
                )
            except Exception as e:
                # A connection error here is expected — the server shut down
                # before it could send a full response.
                err = str(e)
                if "Connection" in err or "refused" in err.lower() or "reset" in err.lower():
                    self.container.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Restart Initiated",
                            "Server is restarting.\n\n"
                            "Wait 10 seconds then the app will reconnect."
                        )
                    )
                else:
                    self.container.after(
                        0,
                        lambda: messagebox.showerror("Restart Error", err)
                    )
            finally:
                if self.container.winfo_exists():
                    self.container.after(
                        0,
                        lambda: self.restart_btn.configure(
                            state="normal", text="🔄 RESTART SERVER"
                        )
                    )

        import threading
        threading.Thread(target=run, daemon=True).start()

    def sync_billing_years(self):
        """
        Syncs missing billing year records for all properties.
        First runs a dry-run preview, then asks for confirmation before committing.
        """
        import threading
        import api_clients.system_service as system_svc

        self.sync_btn.configure(state="disabled", text="🔍 PREVIEWING...")

        def preview():
            try:
                # Dry run first — show what will be created
                res = system_svc.sync_billing_years(dry_run=True)
                created = res.get("records_created", 0)
                scanned = res.get("properties_scanned", 0)
                skipped = res.get("records_skipped", 0)

                msg = (
                    f"Billing Year Sync Preview\n\n"
                    f"Properties scanned:    {scanned}\n"
                    f"Records to create:     {created}\n"
                    f"Already exist (skip):  {skipped}\n\n"
                )

                if created == 0:
                    # Nothing to do — show a simple premium info dialog
                    self.container.after(0, lambda: _show_sync_info(
                        self.container.winfo_toplevel(),
                        scanned, created, skipped
                    ))
                    return

                def confirm_and_run():
                    _show_sync_confirm(
                        self.container.winfo_toplevel(),
                        scanned, created, skipped,
                        on_confirm=lambda: (
                            self.sync_btn.configure(text="⏳ SYNCING..."),
                            threading.Thread(target=run_live, daemon=True).start()
                        )
                    )

                self.container.after(0, confirm_and_run)

            except Exception as e:
                self.container.after(
                    0, lambda: messagebox.showerror("Sync Error", str(e))
                )
            finally:
                if self.container.winfo_exists():
                    self.container.after(
                        0,
                        lambda: self.sync_btn.configure(
                            state="normal", text="📅 SYNC BILLING YEARS"
                        )
                    )

        def run_live():
            global _active_sync_job_id
            try:
                res = system_svc.sync_billing_years(dry_run=False)

                if "job_id" in res:
                    job_id = res["job_id"]
                    _active_sync_job_id = job_id  # persist across navigation
                    self._resume_sync_monitoring(job_id)
                else:
                    _active_sync_job_id = None
                    created = res.get("records_created", 0)
                    try:
                        top = self.parent.winfo_toplevel()
                        top.after(0, lambda c=created: messagebox.showinfo(
                            "Sync Complete",
                            f"✅ Billing sync complete!\n\n{c} billing records created.\n\n"
                            f"The Delinquency Dashboard will now show\nthe correct multi-year balances."
                        ))
                    except Exception:
                        pass
            except Exception as e:
                _active_sync_job_id = None
                try:
                    top = self.parent.winfo_toplevel()
                    top.after(0, lambda err=str(e): messagebox.showerror("Sync Error", err))
                except Exception:
                    pass
            finally:
                _active_sync_job_id = None
                try:
                    if self.container.winfo_exists():
                        self.container.after(0, lambda: self.sync_btn.configure(
                            state="normal", text="📅 SYNC BILLING YEARS"
                        ))
                except Exception:
                    pass

        threading.Thread(target=preview, daemon=True).start()


    def repair_billing_av(self):
        """Preview and repair stale PropertyBilling assessed-value snapshots."""
        import threading
        import api_clients.system_service as system_svc

        def reset_button():
            if self.container.winfo_exists():
                self.repair_av_btn.configure(state="normal", text="REPAIR BILLING AV")

        self.repair_av_btn.configure(state="disabled", text="PREVIEWING...")

        def preview():
            try:
                res = system_svc.repair_billing_av(dry_run=True)
                rows = int(res.get("rows_to_update", 0) or 0)
                props = int(res.get("properties_affected", 0) or 0)
                scanned = int(res.get("properties_scanned", 0) or 0)
                sample = res.get("sample", []) or []

                if rows <= 0:
                    def show_none():
                        messagebox.showinfo(
                            "Billing AV Repair",
                            f"No stale billing AV snapshots found.\n\nProperties scanned: {scanned:,}",
                            parent=self.container.winfo_toplevel(),
                        )
                        reset_button()
                    self.container.after(0, show_none)
                    return

                examples = []
                for item in sample[:5]:
                    examples.append(
                        f"{item.get('td_number')} | {item.get('tax_year')} | "
                        f"{item.get('old_assessed_value', 0):,.2f} -> "
                        f"{item.get('new_assessed_value', 0):,.2f}"
                    )
                example_text = "\n".join(examples)
                msg = (
                    "Repair stale billing assessed values?\n\n"
                    f"Properties scanned: {scanned:,}\n"
                    f"Properties affected: {props:,}\n"
                    f"Billing rows to update: {rows:,}\n\n"
                    "Examples:\n"
                    f"{example_text}\n\n"
                    "This updates billing assessed values only. Payments, OR numbers, "
                    "penalties, and discounts will not be changed."
                )

                def ask_confirm():
                    if messagebox.askyesno("Confirm Billing AV Repair", msg, parent=self.container.winfo_toplevel()):
                        self.repair_av_btn.configure(state="disabled", text="REPAIRING...")
                        threading.Thread(target=apply_repair, daemon=True).start()
                    else:
                        reset_button()

                self.container.after(0, ask_confirm)
            except Exception as e:
                def show_error(err=str(e)):
                    messagebox.showerror("Billing AV Repair", err)
                    reset_button()
                self.container.after(0, show_error)

        def apply_repair():
            try:
                res = system_svc.repair_billing_av(dry_run=False)
                updated = int(res.get("rows_updated", 0) or 0)
                props = int(res.get("properties_affected", 0) or 0)
                def show_done():
                    messagebox.showinfo(
                        "Billing AV Repair Complete",
                        f"Updated {updated:,} billing row(s) across {props:,} property/properties.\n\n"
                        "Reload Reconciliation to confirm the variance list.",
                        parent=self.container.winfo_toplevel(),
                    )
                    reset_button()
                self.container.after(0, show_done)
            except Exception as e:
                def show_error(err=str(e)):
                    messagebox.showerror("Billing AV Repair", err)
                    reset_button()
                self.container.after(0, show_error)

        threading.Thread(target=preview, daemon=True).start()

    def repair_payment_links(self):
        """Preview and repair stale payment allocations and stored paid totals."""
        import threading
        import api_clients.system_service as system_svc

        def reset_button():
            if self.container.winfo_exists():
                self.repair_links_btn.configure(state="normal", text="REPAIR PAYMENT ALLOCATION DRIFT")

        self.repair_links_btn.configure(state="disabled", text="PREVIEWING...")

        def preview():
            try:
                res = system_svc.repair_payment_links(dry_run=True)
                missing = int(res.get("missing_links", 0) or 0)
                stale_links = int(res.get("stale_link_amounts", 0) or 0)
                stale_summaries = int(res.get("stale_billing_summaries", 0) or 0)
                recalc = int(res.get("billing_rows_to_recalculate", 0) or 0)
                skipped = int(res.get("ambiguous_payments_skipped", 0) or 0)
                props = int(res.get("properties_affected", 0) or 0)
                sample = res.get("sample", []) or []

                if missing <= 0 and stale_links <= 0 and stale_summaries <= 0 and recalc <= 0:
                    def show_none():
                        messagebox.showinfo(
                            "Payment Allocation Drift Repair",
                            "No payment allocation drift found.\n\n"
                            "The stored billing paid totals already match the linked payment allocations.",
                            parent=self.container.winfo_toplevel(),
                        )
                        reset_button()
                    self.container.after(0, show_none)
                    return

                examples = []
                for item in sample[:6]:
                    examples.append(
                        f"{item.get('td_number')} | OR {item.get('or_number') or '-'} | "
                        f"{item.get('tax_year') or '-'} | {float(item.get('amount', 0) or 0):,.2f}"
                    )
                example_text = "\n".join(examples) or "No examples available."
                msg = (
                    "Repair Payment Allocation Drift?\n\n"
                    "This fixes payment-link issues where stored billing paid totals "
                    "do not match the real payment allocation links.\n\n"
                    f"Missing payment links: {missing:,}\n"
                    f"Stale link amounts: {stale_links:,}\n"
                    f"Stale billing summaries: {stale_summaries:,}\n"
                    f"Billing paid totals to recalculate: {recalc:,}\n"
                    f"Properties affected: {props:,}\n"
                    f"Ambiguous payments skipped: {skipped:,}\n\n"
                    "Examples:\n"
                    f"{example_text}\n\n"
                    "This does not change OR numbers, payment dates, or payment amounts. "
                    "It rebuilds payment-to-billing links where safe and recalculates billing paid totals."
                )

                def ask_confirm():
                    if messagebox.askyesno("Confirm Payment Allocation Drift Repair", msg, parent=self.container.winfo_toplevel()):
                        self.repair_links_btn.configure(state="disabled", text="REPAIRING...")
                        threading.Thread(target=apply_repair, daemon=True).start()
                    else:
                        reset_button()

                self.container.after(0, ask_confirm)
            except Exception as e:
                def show_error(err=str(e)):
                    messagebox.showerror("Payment Allocation Drift Repair", err, parent=self.container.winfo_toplevel())
                    reset_button()
                self.container.after(0, show_error)

        def apply_repair():
            try:
                res = system_svc.repair_payment_links(dry_run=False)
                missing = int(res.get("missing_links", 0) or 0)
                stale_links = int(res.get("stale_link_amounts", 0) or 0)
                stale_summaries = int(res.get("stale_billing_summaries", 0) or 0)
                recalc = int(res.get("billing_rows_recalculated", 0) or 0)
                created = int(res.get("billing_rows_created", 0) or 0)
                props = int(res.get("properties_affected", 0) or 0)

                def show_done():
                    messagebox.showinfo(
                        "Payment Allocation Drift Repair Complete",
                        f"Created {missing:,} payment link(s).\n"
                        f"Fixed {stale_links:,} stale link amount(s).\n"
                        f"Fixed {stale_summaries:,} stale billing summary row(s).\n"
                        f"Created {created:,} missing billing row(s).\n"
                        f"Recalculated {recalc:,} billing paid total(s).\n"
                        f"Properties affected: {props:,}.\n\n"
                        "Reload Reconciliation to confirm payment-link issues are reduced or cleared.",
                        parent=self.container.winfo_toplevel(),
                    )
                    reset_button()
                self.container.after(0, show_done)
            except Exception as e:
                def show_error(err=str(e)):
                    messagebox.showerror("Payment Allocation Drift Repair", err, parent=self.container.winfo_toplevel())
                    reset_button()
                self.container.after(0, show_error)

        threading.Thread(target=preview, daemon=True).start()

    def audit_td_numbers(self):
        """
        Calls the backend TD number audit endpoint and shows results
        in a tabbed dialog with three sections:
          1. Malformed TD numbers
          2. Duplicate TD numbers (two properties share the same TD)
          3. Duplicate payments (same OR number + same tax year)
        """
        import threading
        import tkinter as tk
        from tkinter import ttk
        import api_clients.system_service as system_svc

        self.td_audit_btn.configure(state="disabled", text="🔍 SCANNING...")

        def run():
            try:
                result = system_svc.audit_td_numbers()
                self.container.after(0, lambda: show_results(result))
            except Exception as e:
                self.container.after(
                    0, lambda err=e: messagebox.showerror("Audit Error", str(err))
                )
            finally:
                if self.container.winfo_exists():
                    self.container.after(
                        0, lambda: self.td_audit_btn.configure(
                            state="normal", text="🔍 AUDIT TD NUMBERS"
                        )
                    )

        def show_results(result):
            total         = result.get("total_scanned", 0)
            total_pay     = result.get("total_payments_scanned", 0)
            invalid       = result.get("invalid", [])
            dup_tds       = result.get("duplicate_tds", [])
            dup_pays      = result.get("duplicate_payments", [])
            shadows       = result.get("shadow_duplicates", [])
            fmt_count     = result.get("invalid_count", 0)
            dup_td_count  = result.get("duplicate_td_count", 0)
            dup_pay_count = result.get("duplicate_payment_count", 0)
            shadow_count  = result.get("shadow_duplicate_count", 0)
            total_issues  = fmt_count + dup_td_count + dup_pay_count + shadow_count

            # ── Result window ─────────────────────────────────────────────
            win = ctk.CTkToplevel(self.container)
            win.title(f"Data Integrity Audit — {total_issues} issues found")
            win.geometry("1020x640")
            win.attributes("-topmost", True)
            win.grab_set()
            sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
            win.geometry(f"+{(sw-1020)//2}+{(sh-640)//2}")

            # ── Header ────────────────────────────────────────────────────
            hdr = ctk.CTkFrame(win, fg_color="transparent")
            hdr.pack(fill="x", padx=20, pady=(16, 6))
            ctk.CTkLabel(
                hdr, text="🔍  DATA INTEGRITY AUDIT",
                font=ModernTheme.H3, text_color=ModernTheme.PRIMARY, anchor="w",
            ).pack(side="left")
            summary_color = "#2ecc71" if total_issues == 0 else "#e74c3c"
            ctk.CTkLabel(
                hdr,
                text=(f"Properties: {total:,}   |   Payments: {total_pay:,}   |   "
                      f"Issues: {total_issues:,}"),
                font=ModernTheme.BODY_BOLD, text_color=summary_color,
            ).pack(side="right")

            # ── Summary badges ────────────────────────────────────────────
            badges = ctk.CTkFrame(win, fg_color="transparent")
            badges.pack(fill="x", padx=20, pady=(0, 8))

            def badge(parent, label, count, color):
                f = ctk.CTkFrame(parent, fg_color=color, corner_radius=8)
                f.pack(side="left", padx=(0, 8))
                ctk.CTkLabel(
                    f,
                    text=f"  {label}: {count:,}  ",
                    font=("Inter", 11, "bold"), text_color="white",
                ).pack(padx=6, pady=4)

            badge(badges, "Format Issues",      fmt_count,     "#c0392b" if fmt_count     else "#27ae60")
            badge(badges, "Duplicate TDs",      dup_td_count,  "#e67e22" if dup_td_count  else "#27ae60")
            badge(badges, "Duplicate Payments", dup_pay_count, "#8e44ad" if dup_pay_count else "#27ae60")
            badge(badges, "Shadow Duplicates",  shadow_count,  "#c0392b" if shadow_count  else "#27ae60")

            if total_issues == 0:
                ctk.CTkLabel(
                    win,
                    text="✅  No issues found. All TD numbers and payments are clean.",
                    font=("Inter", 16, "bold"), text_color="#2ecc71",
                ).pack(expand=True)
                ctk.CTkButton(win, text="CLOSE", command=win.destroy,
                              fg_color=ModernTheme.SECONDARY, width=120).pack(pady=20)
                return

            # ── Shared treeview style ─────────────────────────────────────
            style = ttk.Style()
            style.configure(
                "Audit.Treeview",
                rowheight=30, font=("Inter", 11),
                background="#1e293b", fieldbackground="#1e293b", foreground="#cbd5e1",
            )
            style.configure(
                "Audit.Treeview.Heading",
                font=("Inter", 11, "bold"), background="#0f172a", foreground="#64748b",
            )
            style.map("Audit.Treeview", background=[("selected", "#1d4ed8")])

            # ── Tabview ───────────────────────────────────────────────────
            tabview = ctk.CTkTabview(win)
            tabview.pack(fill="both", expand=True, padx=20, pady=(0, 8))

            def make_tree(parent, cols, col_widths):
                """Helper: create a scrollable treeview inside a tab."""
                fr = tk.Frame(parent, bg="#1e293b")
                fr.pack(fill="both", expand=True, padx=4, pady=4)
                tree = ttk.Treeview(fr, columns=cols, show="headings",
                                    style="Audit.Treeview")
                for col, w in zip(cols, col_widths):
                    tree.heading(col, text=col)
                    tree.column(col, width=w, anchor="w")
                sy = ttk.Scrollbar(fr, orient="vertical",   command=tree.yview)
                sx = ttk.Scrollbar(fr, orient="horizontal", command=tree.xview)
                tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
                sy.pack(side="right", fill="y")
                sx.pack(side="bottom", fill="x")
                tree.pack(side="left", fill="both", expand=True)
                tree.tag_configure("oddrow",  background="#1e293b", foreground="#cbd5e1")
                tree.tag_configure("evenrow", background="#162032", foreground="#cbd5e1")
                tree.tag_configure("duprow",  background="#2d1b4e", foreground="#c4b5fd")
                tree.tag_configure("paydup",  background="#1e1b4b", foreground="#a5b4fc")
                return tree

            # ── Tab 1: Format Issues ──────────────────────────────────────
            tab1 = tabview.add(f"⚠️ Format Issues ({fmt_count})")
            if invalid:
                t1 = make_tree(tab1,
                    ("ID", "TD NUMBER", "OWNER NAME", "REASON"),
                    (60, 160, 260, 400))
                for i, row in enumerate(invalid):
                    tag = "evenrow" if i % 2 == 0 else "oddrow"
                    t1.insert("", "end", tags=(tag,),
                              values=(row["id"], row["td_number"],
                                      row["owner_name"], row["reason"]))
            else:
                ctk.CTkLabel(tab1, text="✅  No format issues found.",
                             font=("Inter", 13, "bold"), text_color="#2ecc71").pack(expand=True)

            # ── Tab 2: Duplicate TDs ──────────────────────────────────────
            tab2 = tabview.add(f"🔁 Duplicate TDs ({dup_td_count})")
            if dup_tds:
                t2 = make_tree(tab2,
                    ("ID", "TD NUMBER", "OWNER NAME", "NOTE"),
                    (60, 160, 260, 420))
                for i, row in enumerate(dup_tds):
                    t2.insert("", "end", tags=("duprow",),
                              values=(row["id"], row["td_number"],
                                      row["owner_name"], row["reason"]))
            else:
                ctk.CTkLabel(tab2, text="✅  No duplicate TD numbers found.",
                             font=("Inter", 13, "bold"), text_color="#2ecc71").pack(expand=True)

            # ── Tab 3: Duplicate Payments ─────────────────────────────────
            tab3 = tabview.add(f"💳 Duplicate Payments ({dup_pay_count})")
            if dup_pays:
                t3 = make_tree(tab3,
                    ("PAY ID", "OR NUMBER", "TAX YEAR", "TD NUMBER", "OWNER", "AMOUNT", "DATE", "NOTE"),
                    (65, 110, 75, 140, 200, 90, 95, 200))
                for i, row in enumerate(dup_pays):
                    t3.insert("", "end", tags=("paydup",),
                              values=(
                                  row["payment_id"],
                                  row["or_number"],
                                  row["tax_year"],
                                  row["td_number"],
                                  row["owner_name"],
                                  f"₱{row['amount']:,.2f}",
                                  row["date_paid"],
                                  row["reason"],
                              ))
            else:
                ctk.CTkLabel(tab3, text="✅  No duplicate payments found.",
                             font=("Inter", 13, "bold"), text_color="#2ecc71").pack(expand=True)

            # ── Tab 4: Shadow Duplicates ──────────────────────────────────
            tab4 = tabview.add(f"👥 Shadow Duplicates ({shadow_count})")
            if shadows:
                info4 = ctk.CTkFrame(
                    tab4, fg_color=("#fff3e0", "#2d1b00"),
                    corner_radius=8, border_width=1, border_color=("#ffcc80", "#92400e"),
                )
                info4.pack(fill="x", padx=4, pady=(4, 0))
                ctk.CTkLabel(
                    info4,
                    text=(
                        "⚠️  These malformed TDs cannot be auto-fixed because a correct-format version already exists.\n"
                        "Review each pair — verify which property has the correct payments, then delete the bad one via Recycle Bin."
                    ),
                    font=("Inter", 10), text_color=("#92400e", "#fbbf24"),
                    wraplength=860, justify="left",
                ).pack(padx=12, pady=6, anchor="w")

                t4 = make_tree(tab4,
                    ("BAD ID", "BAD TD", "BAD OWNER", "CORRECT ID", "CORRECT TD", "CORRECT OWNER", "ACTION"),
                    (65, 140, 200, 80, 140, 200, 280))
                t4.tag_configure("shadowrow", background="#2d1b00", foreground="#fbbf24")
                for row in shadows:
                    t4.insert("", "end", tags=("shadowrow",),
                              values=(
                                  row["bad_id"],
                                  row["bad_td"],
                                  row["bad_owner"],
                                  row["correct_id"],
                                  row["correct_td"],
                                  row["correct_owner"],
                                  row["action"],
                              ))
            else:
                ctk.CTkLabel(tab4, text="✅  No shadow duplicates found.",
                             font=("Inter", 13, "bold"), text_color="#2ecc71").pack(expand=True)

            # ── Footer ────────────────────────────────────────────────────
            foot = ctk.CTkFrame(win, fg_color="transparent")
            foot.pack(fill="x", padx=20, pady=(0, 14))

            def run_shadow_cleanup():
                if not shadows:
                    return
                bad_ids = [s["bad_id"] for s in shadows]
                count = len(bad_ids)

                # Premium confirm dialog
                confirmed = tk.BooleanVar(value=False)
                dlg = ctk.CTkToplevel(win)
                dlg.title("")
                dlg.resizable(False, False)
                dlg.overrideredirect(True)
                dlg.attributes("-topmost", True)

                dw, dh = 460, 340
                sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
                dlg.geometry(f"{dw}x{dh}+{(sw-dw)//2}+{(sh-dh)//2}")

                outer = ctk.CTkFrame(dlg, fg_color="#0f172a", corner_radius=16,
                                     border_width=1, border_color="#1e293b")
                outer.pack(fill="both", expand=True, padx=2, pady=2)
                ctk.CTkFrame(outer, height=5, fg_color="#dc2626", corner_radius=0).pack(fill="x")

                # Centered icon
                icon_row = ctk.CTkFrame(outer, fg_color="transparent")
                icon_row.pack(pady=(18, 0))
                icon_fr = ctk.CTkFrame(icon_row, width=52, height=52, corner_radius=26,
                                       fg_color="#1e293b", border_width=2, border_color="#ef4444")
                icon_fr.pack()
                icon_fr.pack_propagate(False)
                ctk.CTkLabel(icon_fr, text="🗑️", font=("Segoe UI Emoji", 20),
                             text_color="#ef4444").place(relx=0.5, rely=0.5, anchor="center")

                ctk.CTkLabel(outer, text="Batch Delete Shadow Duplicates",
                             font=("Inter", 14, "bold"), text_color="#f1f5f9").pack(pady=(10, 2))

                body = ctk.CTkFrame(outer, fg_color="#161b22", corner_radius=8)
                body.pack(fill="x", padx=20, pady=(6, 0))
                lines = [
                    (f"Up to {count:,} bad TD properties will be processed.", "#94a3b8"),
                    ("✓  Properties WITH payments → SKIPPED (safe)", "#10b981"),
                    ("✓  Deleted records go to Recycle Bin (recoverable)", "#10b981"),
                    ("✓  All deletions logged in the Audit Trail", "#10b981"),
                    ("✗  Properties WITHOUT payments → soft-deleted", "#f87171"),
                ]
                for text, color in lines:
                    ctk.CTkLabel(body, text=text, font=("Inter", 10),
                                 text_color=color, anchor="w").pack(anchor="w", padx=12, pady=2)

                ctk.CTkFrame(outer, height=1, fg_color="#1e293b").pack(fill="x", padx=20, pady=(10, 0))

                btn_fr = ctk.CTkFrame(outer, fg_color="transparent")
                btn_fr.pack(pady=12)

                def on_cancel():
                    confirmed.set(False)
                    dlg.grab_release()
                    dlg.destroy()

                def on_confirm():
                    confirmed.set(True)
                    dlg.grab_release()
                    dlg.destroy()

                ctk.CTkButton(btn_fr, text="CANCEL", command=on_cancel,
                              fg_color="#1e293b", hover_color="#334155", text_color="#94a3b8",
                              border_width=1, border_color="#334155",
                              font=("Inter", 12, "bold"), width=130, height=36, corner_radius=8,
                              ).pack(side="left", padx=(0, 10))
                ctk.CTkButton(btn_fr, text=f"DELETE {count:,} BAD TDs", command=on_confirm,
                              fg_color="#dc2626", hover_color="#b91c1c", text_color="white",
                              font=("Inter", 12, "bold"), width=180, height=36, corner_radius=8,
                              ).pack(side="left")

                dlg.bind("<Return>", lambda e: on_confirm())
                dlg.bind("<Escape>", lambda e: on_cancel())
                dlg.update_idletasks()
                dlg.lift()
                dlg.focus_force()
                dlg.grab_set()
                dlg.wait_window()

                if not confirmed.get():
                    return

                def do_cleanup():
                    try:
                        res = system_svc.shadow_duplicate_cleanup(bad_ids)
                        deleted = res.get("deleted", 0)
                        skipped = res.get("skipped", 0)
                        skipped_list = res.get("skipped_list", [])

                        # Premium result dialog
                        def show_result():
                            color = "#10b981" if skipped == 0 else "#f59e0b"
                            rdlg = ctk.CTkToplevel(win)
                            rdlg.title("")
                            rdlg.resizable(False, False)
                            rdlg.overrideredirect(True)
                            rdlg.attributes("-topmost", True)
                            dw2, dh2 = 400, 240
                            sw2, sh2 = rdlg.winfo_screenwidth(), rdlg.winfo_screenheight()
                            rdlg.geometry(f"{dw2}x{dh2}+{(sw2-dw2)//2}+{(sh2-dh2)//2}")

                            ro = ctk.CTkFrame(rdlg, fg_color="#0f172a", corner_radius=16,
                                             border_width=1, border_color="#1e293b")
                            ro.pack(fill="both", expand=True, padx=2, pady=2)
                            ctk.CTkFrame(ro, height=5, fg_color=color, corner_radius=0).pack(fill="x")

                            icon2 = ctk.CTkFrame(ro, width=48, height=48, corner_radius=24,
                                                 fg_color="#1e293b", border_width=2, border_color=color)
                            icon2.pack(pady=(14, 0))
                            icon2.pack_propagate(False)
                            ctk.CTkLabel(icon2, text="✓", font=("Inter", 20, "bold"),
                                         text_color=color).place(relx=0.5, rely=0.5, anchor="center")

                            ctk.CTkLabel(ro, text="Cleanup Complete",
                                         font=("Inter", 14, "bold"), text_color="#f1f5f9").pack(pady=(8, 2))
                            ctk.CTkLabel(ro,
                                         text=f"Deleted: {deleted:,} bad TD properties\n"
                                              f"Skipped: {skipped:,} (have payments — review manually)",
                                         font=("Inter", 11), text_color="#94a3b8", justify="center").pack()
                            ctk.CTkFrame(ro, height=1, fg_color="#1e293b").pack(fill="x", padx=20, pady=(10, 0))

                            def close_result():
                                rdlg.grab_release()
                                rdlg.destroy()

                            ctk.CTkButton(ro, text="DONE", command=close_result,
                                          fg_color=color,
                                          hover_color="#047857" if skipped == 0 else "#d97706",
                                          text_color="white", font=("Inter", 12, "bold"),
                                          width=120, height=34, corner_radius=8).pack(pady=10)
                            rdlg.bind("<Return>", lambda e: close_result())
                            rdlg.update_idletasks()
                            rdlg.lift()
                            rdlg.focus_force()
                            rdlg.grab_set()

                        self.container.after(0, show_result)
                    except Exception as e:
                        self.container.after(0, lambda err=e: messagebox.showerror("Error", str(err)))

                threading.Thread(target=do_cleanup, daemon=True).start()

            if shadow_count > 0:
                ctk.CTkButton(
                    foot,
                    text=f"🗑️  BATCH DELETE {shadow_count:,} BAD TDs",
                    command=run_shadow_cleanup,
                    fg_color="#c0392b", hover_color="#e74c3c",
                    width=240, height=36, font=ModernTheme.BUTTON_SMALL,
                ).pack(side="left", padx=(0, 8))

            def export_csv():
                from tkinter import filedialog
                import csv
                path = filedialog.asksaveasfilename(
                    parent=win,
                    defaultextension=".csv",
                    filetypes=[("CSV", "*.csv")],
                    initialfile="data_integrity_audit.csv",
                    title="Save Audit Report",
                )
                if not path:
                    win.lift()
                    win.focus_force()
                    return
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    # Section 1
                    writer.writerow(["=== FORMAT ISSUES ==="])
                    writer.writerow(["ID", "TD Number", "Owner Name", "Reason"])
                    for row in invalid:
                        writer.writerow([row["id"], row["td_number"],
                                         row["owner_name"], row["reason"]])
                    writer.writerow([])
                    # Section 2
                    writer.writerow(["=== DUPLICATE TD NUMBERS ==="])
                    writer.writerow(["ID", "TD Number", "Owner Name", "Note"])
                    for row in dup_tds:
                        writer.writerow([row["id"], row["td_number"],
                                         row["owner_name"], row["reason"]])
                    writer.writerow([])
                    # Section 3
                    writer.writerow(["=== DUPLICATE PAYMENTS ==="])
                    writer.writerow(["Payment ID", "OR Number", "Tax Year",
                                     "TD Number", "Owner", "Amount", "Date", "Note"])
                    for row in dup_pays:
                        writer.writerow([
                            row["payment_id"], row["or_number"], row["tax_year"],
                            row["td_number"], row["owner_name"],
                            row["amount"], row["date_paid"], row["reason"],
                        ])
                    writer.writerow([])
                    # Section 4
                    writer.writerow(["=== SHADOW DUPLICATES (malformed TD + correct TD both exist) ==="])
                    writer.writerow(["Bad ID", "Bad TD", "Bad Owner",
                                     "Correct ID", "Correct TD", "Correct Owner", "Action"])
                    for row in shadows:
                        writer.writerow([
                            row["bad_id"], row["bad_td"], row["bad_owner"],
                            row["correct_id"], row["correct_td"], row["correct_owner"],
                            row["action"],
                        ])
                import os
                os.startfile(path)
                # Bring audit window back to front after file dialog closes
                win.lift()
                win.focus_force()
                win.attributes("-topmost", True)

            ctk.CTkButton(
                foot, text="📥  EXPORT CSV", command=export_csv,
                fg_color="#059669", hover_color="#047857",
                width=140, height=36, font=ModernTheme.BUTTON_SMALL,
            ).pack(side="left")

            def run_fix(dry: bool):
                win.grab_release()
                win.destroy()
                self.td_audit_btn.configure(state="disabled", text="⚙️ FIXING...")

                def do_fix():
                    try:
                        res = system_svc.fix_td_numbers(dry_run=dry)
                        self.container.after(0, lambda r=res: show_fix_result(r, dry))
                    except Exception as e:
                        self.container.after(
                            0, lambda err=e: messagebox.showerror("Fix Error", str(err))
                        )
                    finally:
                        if self.container.winfo_exists():
                            self.container.after(
                                0, lambda: self.td_audit_btn.configure(
                                    state="normal", text="🔍 AUDIT TD NUMBERS"
                                )
                            )

                threading.Thread(target=do_fix, daemon=True).start()

            def show_fix_result(res, was_dry):
                if was_dry:
                    will_fix  = res.get("will_fix", 0)
                    unfixable = res.get("unfixable", 0)
                    fixes     = res.get("fixes", [])
                    msg = (
                        f"DRY RUN PREVIEW\n\n"
                        f"Will fix:   {will_fix:,} TD numbers\n"
                        f"Unfixable:  {unfixable:,} TD numbers\n\n"
                        f"First 5 fixes:\n"
                    )
                    for f in fixes[:5]:
                        msg += f"  {f['original']}  →  {f['fixed']}  ({f['rule']})\n"
                    msg += "\nClick OK to apply the fixes, or Cancel to abort."
                    if messagebox.askokcancel("Preview — Apply Fixes?", msg):
                        self.td_audit_btn.configure(state="disabled", text="⚙️ APPLYING...")
                        def apply():
                            try:
                                r2 = system_svc.fix_td_numbers(dry_run=False)
                                self.container.after(0, lambda: show_fix_result(r2, False))
                            except Exception as e:
                                self.container.after(0, lambda err=e: messagebox.showerror("Fix Error", str(err)))
                            finally:
                                if self.container.winfo_exists():
                                    self.container.after(0, lambda: self.td_audit_btn.configure(
                                        state="normal", text="🔍 AUDIT TD NUMBERS"))
                        threading.Thread(target=apply, daemon=True).start()
                else:
                    fixed      = res.get("fixed", 0)
                    unfixable  = res.get("unfixable", 0)
                    collisions = res.get("collisions", 0)
                    msg = (
                        f"✅ TD Number Fix Complete\n\n"
                        f"Fixed:      {fixed:,} TD numbers\n"
                        f"Unfixable:  {unfixable:,} (need manual correction)\n"
                    )
                    if collisions:
                        msg += (
                            f"Skipped:    {collisions:,} (would create duplicates)\n\n"
                            f"The skipped TDs already exist in the database.\n"
                            f"Run the Audit again to see which ones remain."
                        )
                    else:
                        msg += "\nAll changes are logged in the Audit Trail."
                    messagebox.showinfo("Fix Complete", msg)

            # Only show AUTO-FIX if there are format issues (fix only applies to format)
            if fmt_count > 0:
                ctk.CTkButton(
                    foot, text="⚙️  AUTO-FIX FORMAT ISSUES",
                    command=lambda: run_fix(dry=True),
                    fg_color="#c0392b", hover_color="#e74c3c",
                    width=200, height=36, font=ModernTheme.BUTTON_SMALL,
                ).pack(side="left", padx=(8, 0))

            ctk.CTkButton(
                foot, text="CLOSE", command=win.destroy,
                fg_color=ModernTheme.SECONDARY, width=100, height=36,
                font=ModernTheme.BUTTON_SMALL,
            ).pack(side="right")

        threading.Thread(target=run, daemon=True).start()

    def setup_tax_policy_tab(self, parent):
        """
        Tax Policy configuration tab.
        Allows Admin to view and update RPT rates (Basic, SEF, Penalty) per tax year.
        Changes take effect immediately for all new computations.
        """
        import tkinter as tk
        from tkinter import ttk
        import threading
        import api_clients.system_service as system_svc

        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=20, pady=16)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(container, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            hdr,
            text="⚙️  TAX POLICY CONFIGURATION",
            font=ModernTheme.H3,
            text_color=ModernTheme.PRIMARY,
            anchor="w",
        ).pack(side="left")

        ctk.CTkButton(
            hdr,
            text="🔄  REFRESH",
            command=lambda: threading.Thread(target=load_policies, daemon=True).start(),
            width=110,
            height=34,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SECONDARY,
            hover_color=ModernTheme.SECONDARY_HOVER,
        ).pack(side="right")

        # ── Info banner ───────────────────────────────────────────────────────
        info = ctk.CTkFrame(
            container,
            fg_color=("#dbeafe", "#1e293b"),
            corner_radius=8,
            border_width=1,
            border_color=("#93c5fd", "#334155"),
        )
        info.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            info,
            text=(
                "Configure Basic Rate, SEF Rate, and Penalty Rate per tax year.  "
                "Default: 1% Basic + 1% SEF = 2% total annual tax, 2% monthly penalty.  "
                "Changes take effect immediately for all new computations."
            ),
            font=ModernTheme.BODY,
            text_color=ModernTheme.TEXT_GRAY,
            wraplength=700,
            justify="left",
        ).pack(side="left", padx=14, pady=8)

        # ── Policy table ──────────────────────────────────────────────────────
        style = ttk.Style()
        style.configure(
            "TaxPolicy.Treeview",
            rowheight=34,
            font=("Inter", 12),
            background="#1e293b",
            fieldbackground="#1e293b",
            foreground="#cbd5e1",
        )
        style.configure(
            "TaxPolicy.Treeview.Heading",
            font=("Inter", 11, "bold"),
            background="#0f172a",
            foreground="#64748b",
        )
        style.map("TaxPolicy.Treeview", background=[("selected", "#1d4ed8")])

        tree_fr = tk.Frame(container, bg="#1e293b")
        tree_fr.pack(fill="both", expand=True, pady=(0, 12))

        cols = ("TAX YEAR", "BASIC RATE", "SEF RATE", "PENALTY RATE/MO", "TOTAL ANNUAL")
        self._tax_tree = ttk.Treeview(
            tree_fr, columns=cols, show="headings", style="TaxPolicy.Treeview"
        )
        for col in cols:
            self._tax_tree.heading(col, text=col)
        self._tax_tree.column("TAX YEAR",        width=100, anchor="center")
        self._tax_tree.column("BASIC RATE",       width=120, anchor="center")
        self._tax_tree.column("SEF RATE",         width=120, anchor="center")
        self._tax_tree.column("PENALTY RATE/MO",  width=150, anchor="center")
        self._tax_tree.column("TOTAL ANNUAL",     width=130, anchor="center")

        scrolly = ttk.Scrollbar(tree_fr, orient="vertical", command=self._tax_tree.yview)
        self._tax_tree.configure(yscrollcommand=scrolly.set)
        self._tax_tree.pack(side="left", fill="both", expand=True)
        scrolly.pack(side="right", fill="y")

        self._tax_tree.tag_configure("oddrow",  background="#1e293b", foreground="#cbd5e1")
        self._tax_tree.tag_configure("evenrow", background="#162032", foreground="#cbd5e1")
        self._tax_tree.bind("<<TreeviewSelect>>", self._on_tax_row_select)

        # ── Edit panel ────────────────────────────────────────────────────────
        edit_card = ctk.CTkFrame(
            container,
            fg_color=("#f8fafc", "#1e293b"),
            corner_radius=10,
            border_width=1,
            border_color=("#cbd5e1", "#334155"),
        )
        edit_card.pack(fill="x")

        ctk.CTkLabel(
            edit_card,
            text="EDIT SELECTED YEAR",
            font=("Inter", 10, "bold"),
            text_color=ModernTheme.TEXT_GRAY,
            anchor="w",
        ).pack(anchor="w", padx=16, pady=(12, 6))

        fields_fr = ctk.CTkFrame(edit_card, fg_color="transparent")
        fields_fr.pack(fill="x", padx=16, pady=(0, 12))

        # Year label
        ctk.CTkLabel(fields_fr, text="Tax Year:", font=ModernTheme.BODY_BOLD,
                     text_color=ModernTheme.TEXT_GRAY).grid(row=0, column=0, padx=(0, 8), pady=4, sticky="e")
        self._tax_year_lbl = ctk.CTkLabel(fields_fr, text="—", font=("Inter", 14, "bold"),
                                           text_color=ModernTheme.PRIMARY)
        self._tax_year_lbl.grid(row=0, column=1, padx=(0, 24), pady=4, sticky="w")

        # Basic rate
        ctk.CTkLabel(fields_fr, text="Basic Rate (%):", font=ModernTheme.BODY_BOLD,
                     text_color=ModernTheme.TEXT_GRAY).grid(row=0, column=2, padx=(0, 8), pady=4, sticky="e")
        self._basic_var = tk.StringVar(value="1.00")
        ctk.CTkEntry(fields_fr, textvariable=self._basic_var, width=90, height=32,
                     font=ModernTheme.BODY).grid(row=0, column=3, padx=(0, 24), pady=4)

        # SEF rate
        ctk.CTkLabel(fields_fr, text="SEF Rate (%):", font=ModernTheme.BODY_BOLD,
                     text_color=ModernTheme.TEXT_GRAY).grid(row=0, column=4, padx=(0, 8), pady=4, sticky="e")
        self._sef_var = tk.StringVar(value="1.00")
        ctk.CTkEntry(fields_fr, textvariable=self._sef_var, width=90, height=32,
                     font=ModernTheme.BODY).grid(row=0, column=5, padx=(0, 24), pady=4)

        # Penalty rate
        ctk.CTkLabel(fields_fr, text="Penalty Rate/mo (%):", font=ModernTheme.BODY_BOLD,
                     text_color=ModernTheme.TEXT_GRAY).grid(row=0, column=6, padx=(0, 8), pady=4, sticky="e")
        self._penalty_var = tk.StringVar(value="2.00")
        ctk.CTkEntry(fields_fr, textvariable=self._penalty_var, width=90, height=32,
                     font=ModernTheme.BODY).grid(row=0, column=7, padx=(0, 24), pady=4)

        # Save button
        self._tax_save_btn = ctk.CTkButton(
            fields_fr,
            text="💾  SAVE",
            command=lambda: threading.Thread(target=save_policy, daemon=True).start(),
            width=100,
            height=34,
            font=ModernTheme.BUTTON_SMALL,
            fg_color="#059669",
            hover_color="#047857",
            state="disabled",
        )
        self._tax_save_btn.grid(row=0, column=8, padx=(0, 8), pady=4)

        self._tax_selected_year: int | None = None

        # ── Data functions ────────────────────────────────────────────────────

        def load_policies():
            try:
                policies = system_svc.get_tax_policies()
                container.after(0, lambda: render_policies(policies))
            except Exception as e:
                container.after(0, lambda err=e: messagebox.showerror("Load Error", str(err)))

        def render_policies(policies):
            for item in self._tax_tree.get_children():
                self._tax_tree.delete(item)
            for i, p in enumerate(policies):
                tag = "evenrow" if i % 2 == 0 else "oddrow"
                basic = p["basic_rate"] * 100
                sef = p["sef_rate"] * 100
                penalty = p["penalty_rate"] * 100
                total = (basic + sef)
                self._tax_tree.insert(
                    "", "end",
                    values=(
                        p["tax_year"],
                        f"{basic:.2f}%",
                        f"{sef:.2f}%",
                        f"{penalty:.2f}%",
                        f"{total:.2f}%",
                    ),
                    tags=(tag,),
                    iid=str(p["tax_year"]),
                )

        def save_policy():
            if self._tax_selected_year is None:
                return
            try:
                basic = float(self._basic_var.get()) / 100
                sef = float(self._sef_var.get()) / 100
                penalty = float(self._penalty_var.get()) / 100
            except ValueError:
                container.after(0, lambda: messagebox.showerror(
                    "Invalid Input", "Rates must be numbers (e.g. 1.00 for 1%)."
                ))
                return

            try:
                system_svc.update_tax_policy(self._tax_selected_year, basic, sef, penalty)
                container.after(0, lambda: messagebox.showinfo(
                    "Saved",
                    f"Tax policy for {self._tax_selected_year} updated successfully.\n\n"
                    f"Basic: {basic*100:.2f}%  SEF: {sef*100:.2f}%  Penalty: {penalty*100:.2f}%/mo"
                ))
                threading.Thread(target=load_policies, daemon=True).start()
            except Exception as e:
                container.after(0, lambda err=e: messagebox.showerror("Save Error", str(err)))

        # Load on open
        threading.Thread(target=load_policies, daemon=True).start()

    def _on_tax_row_select(self, event=None):
        """Populate the edit fields when a tax year row is selected."""
        sel = self._tax_tree.selection()
        if not sel:
            return
        iid = sel[0]
        try:
            self._tax_selected_year = int(iid)
            vals = self._tax_tree.item(iid)["values"]
            # vals: (year, basic%, sef%, penalty%, total%)
            self._tax_year_lbl.configure(text=str(vals[0]))
            self._basic_var.set(str(float(vals[1].replace("%", ""))))
            self._sef_var.set(str(float(vals[2].replace("%", ""))))
            self._penalty_var.set(str(float(vals[3].replace("%", ""))))
            self._tax_save_btn.configure(state="normal")
        except Exception:
            pass

    def _resume_sync_monitoring(self, job_id: str):
        """
        Polls a running sync job until it completes.
        Called both when a new sync starts AND when the user navigates back
        to System Settings while a sync is already in progress.
        """
        global _active_sync_job_id
        import time
        import api_clients.system_service as system_svc

        while True:
            status = system_svc.get_job_status(job_id)
            if not status:
                break

            job_status = status.get("status")

            if job_status == "COMPLETED":
                _active_sync_job_id = None
                result = status.get("result") or {}
                created = result.get("records_created", 0)
                try:
                    top = self.parent.winfo_toplevel()
                    top.after(0, lambda c=created: messagebox.showinfo(
                        "Sync Complete",
                        f"✅ Billing sync complete!\n\n{c} billing records created.\n\n"
                        f"The Delinquency Dashboard will now show\nthe correct multi-year balances."
                    ))
                except Exception:
                    pass
                break

            elif job_status == "FAILED":
                _active_sync_job_id = None
                err = status.get("error", "Unknown error")
                try:
                    top = self.parent.winfo_toplevel()
                    top.after(0, lambda e=err: messagebox.showerror("Sync Failed", e))
                except Exception:
                    pass
                break

            time.sleep(2)

        # Reset button when done
        _active_sync_job_id = None
        try:
            if self.container.winfo_exists():
                self.container.after(0, lambda: self.sync_btn.configure(
                    state="normal", text="📅 SYNC BILLING YEARS"
                ))
        except Exception:
            pass
