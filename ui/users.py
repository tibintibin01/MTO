import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from theme_manager import ModernTheme
from utils import tr
import api_clients.auth_service as auth
import api_clients.system_service as system
import threading
from ui_components import show_toast, ErrorDialog


def _user_creation_confirmation_message(full_name, username, role):
    """Build a password-free summary for the administrator to confirm."""
    return (
        "Please verify the new account before creating it.\n\n"
        f"Full name: {full_name}\n"
        f"Username: {username}\n"
        f"Role: {str(role or '').upper()}\n\n"
        "The password is intentionally not displayed."
    )



# ---------------------------------------------------------------------------
# Premium confirmation dialog — replaces native messagebox.askyesno
# ---------------------------------------------------------------------------

class ConfirmDialog(ctk.CTkToplevel):
    """
    A styled confirmation dialog that matches the app's dark theme.

    Usage:
        dlg = ConfirmDialog(parent, title, message, confirm_text, cancel_text, danger)
        parent.wait_window(dlg)
        if dlg.result: ...   # True = confirmed, False = cancelled
    """

    def __init__(
        self,
        parent,
        title: str,
        message: str,
        confirm_text: str = "Confirm",
        cancel_text: str = "Cancel",
        danger: bool = False,
        icon: str = "❓",
    ):
        super().__init__(parent)
        self.result = False
        self.title(title)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)

        self._build(title, message, confirm_text, cancel_text, danger, icon)

        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def _build(self, title, message, confirm_text, cancel_text, danger, icon):
        self.configure(fg_color="#1a1a2e")

        # ── Top accent bar ──────────────────────────────────────────────────
        accent_color = "#c0392b" if danger else ModernTheme.PRIMARY
        bar = ctk.CTkFrame(self, fg_color=accent_color, height=4, corner_radius=0)
        bar.pack(fill="x")

        # ── Body ────────────────────────────────────────────────────────────
        body = ctk.CTkFrame(self, fg_color="#1a1a2e")
        body.pack(fill="both", expand=True, padx=30, pady=24)

        # Icon + message row
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", pady=(0, 20))

        icon_bg = "#3d1a1a" if danger else "#1a2a3d"
        icon_fg = "#e74c3c" if danger else "#4ca2ff"
        icon_fr = ctk.CTkFrame(row, fg_color=icon_bg, width=52, height=52,
                               corner_radius=26)
        icon_fr.pack(side="left", padx=(0, 16))
        icon_fr.pack_propagate(False)
        ctk.CTkLabel(icon_fr, text=icon, font=("Segoe UI Emoji", 22),
                     text_color=icon_fg).place(relx=0.5, rely=0.5, anchor="center")

        msg_fr = ctk.CTkFrame(row, fg_color="transparent")
        msg_fr.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(msg_fr, text=title,
                     font=("Segoe UI", 13, "bold"), text_color="white",
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(msg_fr, text=message,
                     font=("Segoe UI", 11), text_color="#a0aec0",
                     wraplength=300, justify="left", anchor="w").pack(anchor="w", pady=(4, 0))

        # Divider
        ctk.CTkFrame(body, fg_color="#2d2d4e", height=1).pack(fill="x", pady=(0, 16))

        # Buttons
        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.pack(fill="x")

        ctk.CTkButton(
            btn_row, text=cancel_text,
            command=self._cancel,
            fg_color="#2d2d4e", hover_color="#3d3d5e",
            text_color="#a0aec0", height=38, width=110,
            font=("Segoe UI", 11, "bold"), corner_radius=8,
        ).pack(side="left")

        confirm_color = "#c0392b" if danger else ModernTheme.PRIMARY
        confirm_hover  = "#a93226" if danger else "#2c6ea1"
        ctk.CTkButton(
            btn_row, text=confirm_text,
            command=self._confirm,
            fg_color=confirm_color, hover_color=confirm_hover,
            text_color="white", height=38, width=160,
            font=("Segoe UI", 11, "bold"), corner_radius=8,
        ).pack(side="right")

    def _confirm(self):
        self.result = True
        self.destroy()

    def _cancel(self):
        self.result = False
        self.destroy()


class InputDialog(ctk.CTkToplevel):
    """Styled single-line input dialog — replaces simpledialog.askstring."""

    def __init__(self, parent, title: str, prompt: str, placeholder: str = ""):
        super().__init__(parent)
        self.result: str | None = None
        self.title(title)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)
        self._build(title, prompt, placeholder)
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def _build(self, title, prompt, placeholder):
        self.configure(fg_color="#1a1a2e")
        ctk.CTkFrame(self, fg_color="#c0392b", height=4, corner_radius=0).pack(fill="x")

        body = ctk.CTkFrame(self, fg_color="#1a1a2e")
        body.pack(fill="both", expand=True, padx=30, pady=24)

        ctk.CTkLabel(body, text=title, font=("Segoe UI", 13, "bold"),
                     text_color="white").pack(anchor="w", pady=(0, 6))
        ctk.CTkLabel(body, text=prompt, font=("Segoe UI", 11),
                     text_color="#a0aec0", wraplength=320,
                     justify="left").pack(anchor="w", pady=(0, 12))

        self.entry = ctk.CTkEntry(body, placeholder_text=placeholder,
                                  height=40, font=("Segoe UI", 11),
                                  fg_color="#2d2d4e", border_color="#4a4a6e",
                                  text_color="white")
        self.entry.pack(fill="x", pady=(0, 16))
        self.entry.bind("<Return>", lambda e: self._ok())

        ctk.CTkFrame(body, fg_color="#2d2d4e", height=1).pack(fill="x", pady=(0, 14))

        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.pack(fill="x")
        ctk.CTkButton(btn_row, text="Cancel", command=self._cancel,
                      fg_color="#2d2d4e", hover_color="#3d3d5e",
                      text_color="#a0aec0", height=38, width=110,
                      font=("Segoe UI", 11, "bold"), corner_radius=8).pack(side="left")
        ctk.CTkButton(btn_row, text="Confirm", command=self._ok,
                      fg_color="#c0392b", hover_color="#a93226",
                      text_color="white", height=38, width=160,
                      font=("Segoe UI", 11, "bold"), corner_radius=8).pack(side="right")

    def _ok(self):
        self.result = self.entry.get().strip()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class SessionManagerDialog(ctk.CTkToplevel):
    """Administrator view of active workstation sessions for one user."""

    def __init__(self, parent, user_record):
        super().__init__(parent)
        self.user_record = user_record
        self._sessions = {}
        self.title(f"Active Sessions - {user_record['username']}")
        self.geometry("940x560")
        self.minsize(780, 480)
        self.configure(fg_color="#101827")
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)
        self._build()
        self.after(80, self.refresh_sessions)

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="#13243a", corner_radius=0, height=92)
        header.pack(fill="x")
        header.pack_propagate(False)

        title_fr = ctk.CTkFrame(header, fg_color="transparent")
        title_fr.pack(side="left", fill="y", padx=26, pady=16)
        ctk.CTkLabel(
            title_fr,
            text="ACTIVE SESSIONS",
            font=("Segoe UI", 19, "bold"),
            text_color="white",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_fr,
            text=f"{self.user_record['full_name']}  |  {self.user_record['username']}",
            font=("Segoe UI", 11),
            text_color="#9fb3cc",
        ).pack(anchor="w", pady=(4, 0))

        self.summary_lbl = ctk.CTkLabel(
            header,
            text="Loading...",
            font=("Segoe UI", 11, "bold"),
            text_color="#38bdf8",
        )
        self.summary_lbl.pack(side="right", padx=26)

        info = ctk.CTkFrame(self, fg_color="#17243a", corner_radius=7)
        info.pack(fill="x", padx=22, pady=(18, 12))
        ctk.CTkLabel(
            info,
            text=(
                "Each login is listed as a separate workstation session. "
                "Revoking one signs out that device on its next request."
            ),
            font=("Segoe UI", 10),
            text_color="#b7c6da",
            anchor="w",
        ).pack(fill="x", padx=16, pady=10)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Session.Treeview",
            rowheight=38,
            font=("Segoe UI", 10),
            background="#111c30",
            fieldbackground="#111c30",
            foreground="white",
            borderwidth=0,
        )
        style.configure(
            "Session.Treeview.Heading",
            font=("Segoe UI", 9, "bold"),
            background="#263955",
            foreground="white",
            relief="flat",
        )
        style.map("Session.Treeview", background=[("selected", "#1679b8")])

        table_fr = ctk.CTkFrame(self, fg_color="#111c30", corner_radius=6)
        table_fr.pack(fill="both", expand=True, padx=22, pady=(0, 12))
        columns = ("id", "device", "ip", "signed_in", "last_seen", "expires", "status")
        self.tree = ttk.Treeview(
            table_fr, columns=columns, show="headings", style="Session.Treeview"
        )
        headings = {
            "device": "WORKSTATION",
            "ip": "IP ADDRESS",
            "signed_in": "SIGNED IN",
            "last_seen": "LAST USED",
            "expires": "EXPIRES",
            "status": "STATUS",
        }
        self.tree.heading("id", text="")
        self.tree.column("id", width=0, stretch=tk.NO)
        for key, text_value in headings.items():
            self.tree.heading(key, text=text_value)
        self.tree.column("device", width=190)
        self.tree.column("ip", width=110, anchor="center")
        self.tree.column("signed_in", width=145, anchor="center")
        self.tree.column("last_seen", width=145, anchor="center")
        self.tree.column("expires", width=145, anchor="center")
        self.tree.column("status", width=90, anchor="center")
        self.tree.tag_configure("current", background="#12374b", foreground="#7dd3fc")
        self.tree.tag_configure("other", background="#111c30", foreground="white")
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(table_fr, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=22, pady=(0, 18))
        ctk.CTkButton(
            actions,
            text="CLOSE",
            command=self.destroy,
            width=100,
            height=38,
            fg_color="#334155",
            hover_color="#475569",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left")
        self.refresh_btn = ctk.CTkButton(
            actions,
            text="REFRESH",
            command=self.refresh_sessions,
            width=110,
            height=38,
            fg_color="#2563a8",
            hover_color="#1d4f87",
            font=("Segoe UI", 10, "bold"),
        )
        self.refresh_btn.pack(side="right", padx=(8, 0))
        self.revoke_btn = ctk.CTkButton(
            actions,
            text="REVOKE SELECTED",
            command=self.revoke_selected,
            width=155,
            height=38,
            fg_color="#c0392b",
            hover_color="#9f2f24",
            font=("Segoe UI", 10, "bold"),
        )
        self.revoke_btn.pack(side="right", padx=(8, 0))
        self.revoke_others_btn = ctk.CTkButton(
            actions,
            text="SIGN OUT OTHER SESSIONS",
            command=self.revoke_others,
            width=205,
            height=38,
            fg_color="#d97706",
            hover_color="#b45309",
            font=("Segoe UI", 10, "bold"),
        )
        self.revoke_others_btn.pack(side="right")

    @staticmethod
    def _format_timestamp(value):
        if not value:
            return "Not recorded"
        return str(value).replace("T", " ")[:16]

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.refresh_btn.configure(state=state)
        self.revoke_btn.configure(state=state)
        self.revoke_others_btn.configure(state=state)
        if busy:
            self.summary_lbl.configure(text="Contacting server...")

    def refresh_sessions(self):
        self._set_busy(True)

        def worker():
            try:
                rows = auth.get_active_sessions(self.user_record["id"])
                self.after(0, lambda: self._show_sessions(rows))
            except Exception as exc:
                self.after(0, lambda err=exc: self._show_error("Session Error", err))

        threading.Thread(target=worker, daemon=True).start()

    def _show_sessions(self, rows):
        self._set_busy(False)
        self._sessions = {int(row["id"]): row for row in rows}
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in rows:
            is_current = bool(row.get("is_current"))
            self.tree.insert(
                "",
                "end",
                values=(
                    row["id"],
                    row.get("device_name") or "Unknown workstation",
                    row.get("client_ip") or "Unknown",
                    self._format_timestamp(row.get("created_at")),
                    self._format_timestamp(row.get("last_used_at")),
                    self._format_timestamp(row.get("expires_at")),
                    "CURRENT" if is_current else "ACTIVE",
                ),
                tags=("current" if is_current else "other",),
            )
        count = len(rows)
        self.summary_lbl.configure(
            text=f"{count} active session{'s' if count != 1 else ''}"
        )

    def _show_error(self, title, error):
        self._set_busy(False)
        self.summary_lbl.configure(text="Unable to load sessions", text_color="#f87171")
        ErrorDialog(self, title, str(error))

    def revoke_selected(self):
        selection = self.tree.selection()
        if not selection:
            ErrorDialog(self, "Select Session", "Select a workstation session first.")
            return
        session_id = int(self.tree.item(selection[0])["values"][0])
        row = self._sessions.get(session_id, {})
        if row.get("is_current"):
            ErrorDialog(
                self,
                "Current Session",
                "Use Log Out to close the workstation session you are currently using.",
            )
            return
        dlg = ConfirmDialog(
            self,
            "Revoke Workstation Session",
            f"Sign out {row.get('device_name') or 'this workstation'}?",
            confirm_text="Sign Out Device",
            danger=True,
            icon="!",
        )
        self.wait_window(dlg)
        if not dlg.result:
            return
        self._run_revoke(lambda: auth.revoke_active_session(session_id))

    def revoke_others(self):
        dlg = ConfirmDialog(
            self,
            "Sign Out Other Sessions",
            (
                "Revoke every active session for this account except the current "
                "administrator session, when applicable?"
            ),
            confirm_text="Sign Out Others",
            danger=True,
            icon="!",
        )
        self.wait_window(dlg)
        if not dlg.result:
            return
        self._run_revoke(
            lambda: auth.revoke_other_sessions(self.user_record["id"])
        )

    def _run_revoke(self, operation):
        self._set_busy(True)

        def worker():
            try:
                operation()
                self.after(0, self.refresh_sessions)
            except Exception as exc:
                self.after(0, lambda err=exc: self._show_error("Revoke Failed", err))

        threading.Thread(target=worker, daemon=True).start()


class UserAccessPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.selected_user = None
        self.can_manage_users = auth.has_permission(user, "manage_users")
        self.setup_ui()
        self.refresh_users()

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Main Layout: Two columns
        self.container.grid_columnconfigure(0, weight=3) # User Directory
        self.container.grid_columnconfigure(1, weight=1) # Admin Action Panel
        self.container.grid_rowconfigure(0, weight=1)

        # --- LEFT COLUMN: USER DIRECTORY ---
        directory_fr = ctk.CTkFrame(self.container)
        directory_fr.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        
        ctk.CTkLabel(directory_fr, text=tr("users.title"), font=ModernTheme.BODY_BOLD).pack(anchor="w", padx=20, pady=(15, 10))
        
        # Action Bar in directory
        dir_actions = ctk.CTkFrame(directory_fr, fg_color="transparent")
        dir_actions.pack(fill="x", padx=20, pady=(0, 10))
        
        if self.can_manage_users:
            ctk.CTkButton(dir_actions, text=f"+ {tr('users.btn_register')}", command=self.open_register_modal,
                          fg_color=ModernTheme.PRIMARY, height=32, font=ModernTheme.BUTTON_SMALL).pack(side="left")

        ctk.CTkButton(dir_actions, text=f"🔄 {tr('users.btn_refresh')}", command=self.refresh_users,
                      fg_color="transparent", border_width=1, border_color=ModernTheme.SECONDARY, 
                      text_color=ModernTheme.PRIMARY, width=100, height=32, font=ModernTheme.BUTTON_SMALL).pack(side="right")
        
        # Table Styling
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("User.Treeview", rowheight=40, font=("Segoe UI", 10), background="#2b2b2b", fieldbackground="#2b2b2b", foreground="white")
        style.configure("User.Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#333333", foreground="white")

        self.tree = ttk.Treeview(directory_fr, columns=(
            "id", "status", "name", "username", "role", "login"
        ), show="headings", style="User.Treeview")
        
        col_map = {
            "id": tr("users.table.id"),
            "status": tr("users.table.status"),
            "name": tr("users.table.name"),
            "username": tr("users.table.username"),
            "role": tr("users.table.role"),
            "login": tr("users.table.login")
        }

        for cid, label in col_map.items():
            self.tree.heading(cid, text=label.upper())
        
        self.tree.column("id", width=0, stretch=tk.NO)
        self.tree.column("status", width=100, anchor="center")
        self.tree.column("name", width=250)
        self.tree.column("username", width=150)
        self.tree.column("role", width=120, anchor="center")
        
        scrolly = ttk.Scrollbar(directory_fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrolly.set)

        # Zebra Tags
        self.tree.tag_configure('oddrow', background="#2b2b2b", foreground="white")
        self.tree.tag_configure('evenrow', background="#333333", foreground="white")

        self.tree.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=(0, 20))
        scrolly.pack(side="right", fill="y", padx=(0, 20), pady=(0, 20))
        
        self.tree.bind("<<TreeviewSelect>>", self.on_user_selected)

        # --- RIGHT COLUMN: ADMIN ACTION PANEL ---
        self.admin_panel = ctk.CTkFrame(self.container, fg_color="#f1f2f6" if not self.can_manage_users else "transparent")
        self.admin_panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        
        if not self.can_manage_users:
            ctk.CTkLabel(self.admin_panel, text=tr("users.admin_panel.restricted"), font=ModernTheme.BODY_BOLD, text_color=ModernTheme.TEXT_GRAY).pack(pady=50)
            return

        ctk.CTkLabel(self.admin_panel, text=tr("users.admin_panel.title"), font=ModernTheme.BODY_BOLD, text_color=ModernTheme.PRIMARY).pack(pady=(15, 20))

        # Selected User Info Card
        self.user_card = ctk.CTkFrame(self.admin_panel)
        self.user_card.pack(fill="x", padx=15, pady=(0, 20))
        
        self.name_lbl = ctk.CTkLabel(self.user_card, text=tr("users.admin_panel.hint"), font=ModernTheme.H3)
        self.name_lbl.pack(pady=(15, 5))
        self.role_lbl = ctk.CTkLabel(self.user_card, text="", font=ModernTheme.BODY, text_color=ModernTheme.TEXT_GRAY)
        self.role_lbl.pack(pady=(0, 15))

        # Action Panel Inner
        self.action_fr = ctk.CTkFrame(self.admin_panel, fg_color="transparent")
        self.action_fr.pack(fill="both", expand=True, padx=15)
        
        # Role Change
        ctk.CTkLabel(self.action_fr, text=tr("users.admin_panel.role_label"), font=ModernTheme.BODY_BOLD, text_color=ModernTheme.TEXT_GRAY).pack(anchor="w")
        self.role_cb = ctk.CTkComboBox(self.action_fr, values=["admin", "cashier", "encoder", "viewer"], height=35, font=ModernTheme.BODY)
        self.role_cb.pack(fill="x", pady=(5, 15))
        
        # Account Status
        ctk.CTkLabel(self.action_fr, text=tr("users.admin_panel.status_label"), font=ModernTheme.BODY_BOLD, text_color=ModernTheme.TEXT_GRAY).pack(anchor="w")
        self.status_var = tk.BooleanVar(value=True)
        self.status_sw = ctk.CTkSwitch(self.action_fr, text=tr("users.admin_panel.status_sw"), variable=self.status_var, command=self.toggle_account_status, font=ModernTheme.BODY)
        self.status_sw.pack(anchor="w", pady=(5, 25))

        # High-Security Actions
        ctk.CTkLabel(self.action_fr, text=tr("users.admin_panel.security_label"), font=ModernTheme.BODY_BOLD, text_color=ModernTheme.TEXT_GRAY).pack(anchor="w")
        
        ctk.CTkButton(self.action_fr, text=tr("users.admin_panel.btn_reset"), command=self.reset_password,
                      font=ModernTheme.BUTTON, fg_color=ModernTheme.WARNING).pack(fill="x", pady=(10, 10))

        self.sessions_btn = ctk.CTkButton(
            self.action_fr,
            text="MANAGE ACTIVE SESSIONS",
            command=self.open_session_manager,
            font=ModernTheme.BUTTON,
            fg_color="#2563a8",
            hover_color="#1d4f87",
        )
        self.sessions_btn.pack(fill="x", pady=(0, 10))
        
        self.delete_btn = ctk.CTkButton(self.action_fr, text=f"🗑️ {tr('users.admin_panel.btn_delete')}", command=self.delete_user_account,
                                       font=ModernTheme.BUTTON, fg_color="#c0392b") # Red for danger
        self.delete_btn.pack(fill="x", pady=(0, 10))

        self.save_changes_btn = ctk.CTkButton(self.action_fr, text=tr("users.admin_panel.btn_apply"), command=self.apply_role_change,
                                               font=ModernTheme.BUTTON, fg_color=ModernTheme.SUCCESS)
        self.save_changes_btn.pack(fill="x", pady=(10, 30))

        # Mini Activity Trace (Audit Logs for this user)
        ctk.CTkLabel(self.action_fr, text=tr("users.admin_panel.activity_label"), font=ModernTheme.BODY_BOLD, text_color=ModernTheme.TEXT_GRAY).pack(anchor="w")
        self.audit_tree = ttk.Treeview(self.action_fr, columns=("Action"), show="", height=5)
        self.audit_tree.column("#0", width=0, stretch=tk.NO)
        self.audit_tree.column("Action", width=200)
        self.audit_tree.pack(fill="x", pady=5)
        
        # Disable Admin UI by default
        self.set_admin_ui_state("disabled")

    def set_admin_ui_state(self, state):
        self.role_cb.configure(state=state)
        self.status_sw.configure(state=state)
        self.save_changes_btn.configure(state=state)
        self.delete_btn.configure(state=state)
        self.sessions_btn.configure(state=state)
        # Note: Password reset is special, handled in its own func

    def refresh_users(self, select_username=None):
        def worker():
            try:
                users = auth.get_all_users()
                self.container.after(
                    0,
                    lambda rows=users, username=select_username: self._update_user_table(
                        rows, username
                    ),
                )
            except Exception as e:
                self.container.after(
                    0, lambda err=e: ErrorDialog(self.container, "Refresh Error", str(err))
                )
        threading.Thread(target=worker, daemon=True).start()

    def _update_user_table(self, users, select_username=None):
        for row in self.tree.get_children(): self.tree.delete(row)
        target_username = str(select_username or "").strip().lower()
        selected_item = None
        for i, u in enumerate(users):
            status_text = tr("users.table.status_active") if u["is_active"] else tr("users.table.status_disabled")
            ts_raw = u.get("last_login")
            if isinstance(ts_raw, str):
                login_time = ts_raw.replace("T", " ")[:16]
            elif ts_raw:
                login_time = ts_raw.strftime("%Y-%m-%d %H:%M")
            else:
                login_time = "Never"
            
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            item_id = self.tree.insert("", "end", values=(u["id"], status_text, u["full_name"], u["username"], u["role"].upper(), login_time), tags=(tag,))
            if str(u.get("username") or "").strip().lower() == target_username:
                selected_item = item_id

        if selected_item:
            self.tree.selection_set(selected_item)
            self.tree.focus(selected_item)
            self.tree.see(selected_item)
            self.on_user_selected()

    def on_user_selected(self, event=None):
        if not self.can_manage_users: return
        
        sel = self.tree.selection()
        if not sel: return
        
        vals = self.tree.item(sel[0])["values"]
        self.selected_user = {
            "id": vals[0],
            "status": vals[1],
            "full_name": vals[2],
            "username": vals[3],
            "role": vals[4].lower()
        }
        
        # Update Admin Panel
        self.name_lbl.configure(text=self.selected_user["full_name"])
        self.role_lbl.configure(text=f"Username: {self.selected_user['username']}")
        self.role_cb.set(self.selected_user["role"])
        self.status_var.set("ACTIVE" in self.selected_user["status"])
        
        self.set_admin_ui_state("normal")
        
        # Prevent self-disabling
        current_id = self.user.get("id") if isinstance(self.user, dict) else None
        if current_id and int(self.selected_user["id"]) == int(current_id):
            self.status_sw.configure(state="disabled")
            self.role_cb.configure(state="disabled")
            self.save_changes_btn.configure(state="disabled")
            self.delete_btn.configure(state="disabled")
        
        # Load Audit History for this user
        self.refresh_audit_trace(self.selected_user["id"])

    def toggle_account_status(self):
        if not self.selected_user: return
        new_status = self.status_var.get()
        msg = "Enable this account?" if new_status else "Disable this account?\nUser will be blocked from logging in."
        dlg = ConfirmDialog(
            self.container, tr("users.messages.confirm_status"), msg,
            confirm_text="Yes, Update", icon="🔄",
        )
        self.container.wait_window(dlg)
        if not dlg.result:
            self.status_var.set(not new_status)
            return
        
        try:
            auth.update_user(self.selected_user["id"], is_active=new_status)
            self.refresh_users()
            self.refresh_audit_trace(self.selected_user["id"])
        except Exception as e:
            ErrorDialog(self.container, "Update Error", str(e))

    def apply_role_change(self):
        if not self.selected_user: return
        new_role = self.role_cb.get()
        dlg = ConfirmDialog(
            self.container,
            tr("users.messages.confirm_role"),
            tr("users.messages.confirm_role_msg")
                .replace("{user}", self.selected_user['username'])
                .replace("{role}", new_role.upper()),
            confirm_text="Yes, Change Role",
            icon="🛡️",
        )
        self.container.wait_window(dlg)
        if not dlg.result:
            return
        
        try:
            auth.update_user(self.selected_user["id"], role=new_role)
            self.refresh_users()
            self.refresh_audit_trace(self.selected_user["id"])
            show_toast(self.container.winfo_toplevel(), tr("users.messages.success_role"), type="success")
        except Exception as e:
            ErrorDialog(self.container.winfo_toplevel(), tr("common.error"), str(e))

    def reset_password(self):
        if not self.selected_user: return
        ResetPasswordModal(
            self.container, 
            self.selected_user['username'], 
            self.selected_user['id'], 
            self.refresh_users, 
            self.refresh_audit_trace
        )

    def open_session_manager(self):
        if not self.selected_user:
            return
        SessionManagerDialog(self.container, dict(self.selected_user))

    def delete_user_account(self):
        if not self.selected_user: return
        
        # 1. First Confirmation
        dlg1 = ConfirmDialog(
            self.container,
            "⚠️ Permanent Deletion",
            f"Are you absolutely sure you want to permanently delete the account for '{self.selected_user['full_name']}'?\n\nThis cannot be undone.",
            confirm_text="Yes, Delete",
            cancel_text="Cancel",
            danger=True,
            icon="🗑️",
        )
        self.container.wait_window(dlg1)
        if not dlg1.result:
            return

        # 2. Final Confirmation — type DELETE
        dlg2 = InputDialog(
            self.container,
            "Final Verification",
            f"Type  DELETE  to confirm removal of account:\n{self.selected_user['username']}",
            placeholder="Type DELETE here",
        )
        self.container.wait_window(dlg2)
        if dlg2.result != "DELETE":
            show_toast(self.container.winfo_toplevel(), "Account deletion cancelled.", type="info")
            return
            
        try:
            auth.delete_user(self.selected_user["id"])
            show_toast(self.container.winfo_toplevel(), f"Account '{self.selected_user['username']}' has been removed.", type="success")
            self.selected_user = None
            self.name_lbl.configure(text=tr("users.admin_panel.hint"))
            self.role_lbl.configure(text="")
            self.set_admin_ui_state("disabled")
            self.refresh_users()
        except Exception as e:
            ErrorDialog(self.container.winfo_toplevel(), "Deletion Failed", str(e))

    def refresh_audit_trace(self, user_id):
        def worker():
            try:
                logs = auth.get_audit_logs(user_id=user_id)
                self.container.after(0, lambda: self._update_audit_trace(logs))
            except: pass # Silent fail for mini-trace
        threading.Thread(target=worker, daemon=True).start()

    def _update_audit_trace(self, logs):
        for row in self.audit_tree.get_children(): self.audit_tree.delete(row)
        for log in logs[:10]: # Only show last 10
            ts = log["timestamp"]
            # Formatting timestamp or using a short action description
            desc = f"{log['action']}"
            self.audit_tree.insert("", "end", values=(desc,))

    def open_register_modal(self):
        RegisterUserModal(self.container, self.refresh_users)

class RegisterUserModal(ctk.CTkToplevel):
    def __init__(self, parent, callback):
        super().__init__(parent)
        self.title(tr("users.modal.title"))
        dialog_width = 500
        dialog_height = min(690, max(600, self.winfo_screenheight() - 100))
        self.geometry(f"{dialog_width}x{dialog_height}")
        self.resizable(False, True)
        self.callback = callback
        self._creating = False

        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)

        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(
            f"+{max((sw-dialog_width)//2, 0)}+"
            f"{max((sh-dialog_height)//2, 10)}"
        )

        self.setup_ui()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def setup_ui(self):
        import re
        self._re = re

        self.configure(fg_color="white")

        header_fr = ctk.CTkFrame(
            self, fg_color=ModernTheme.PRIMARY, height=88, corner_radius=0
        )
        header_fr.pack(fill="x", side="top")
        header_fr.pack_propagate(False)
        ctk.CTkLabel(header_fr, text=f"👤 {tr('users.modal.header')}",
                     font=ModernTheme.H3, text_color="white").pack(expand=True)

        # Keep actions outside the scrolling form so they never fall below the
        # screen on smaller displays or with increased Windows display scaling.
        btn_fr = ctk.CTkFrame(
            self, fg_color="#f1f5f9", height=72, corner_radius=0
        )
        btn_fr.pack(fill="x", side="bottom")
        btn_fr.pack_propagate(False)
        self.cancel_btn = ctk.CTkButton(
            btn_fr,
            text=tr("users.modal.btn_cancel"),
            command=self._cancel,
            fg_color=ModernTheme.SECONDARY,
            height=40,
            width=120,
            font=ModernTheme.BUTTON,
        )
        self.cancel_btn.pack(side="left", padx=(28, 8), pady=16)
        self.create_btn = ctk.CTkButton(
            btn_fr,
            text=tr("users.modal.btn_create"),
            command=self.save,
            fg_color=ModernTheme.SUCCESS,
            height=40,
            width=280,
            font=ModernTheme.BUTTON,
            state="disabled",
        )
        self.create_btn.pack(side="right", padx=(8, 28), pady=16)

        form = ctk.CTkScrollableFrame(
            self,
            fg_color="white",
            corner_radius=0,
            scrollbar_button_color="#cbd5e1",
            scrollbar_button_hover_color="#94a3b8",
        )
        form.pack(
            fill="both", expand=True, side="top", padx=(34, 24), pady=14
        )

        # Full Name
        ctk.CTkLabel(form, text=tr("users.modal.fields.name"),
                     font=ModernTheme.BODY_BOLD, text_color=ModernTheme.TEXT_GRAY).pack(anchor="w")
        self.name_ent = ctk.CTkEntry(form, placeholder_text="e.g. Juan Dela Cruz",
                                     height=40, font=ModernTheme.BODY)
        self.name_ent.pack(fill="x", pady=(5, 12))
        self.name_ent.bind("<KeyRelease>", self._on_key)

        # Username
        ctk.CTkLabel(form, text=tr("users.modal.fields.username"),
                     font=ModernTheme.BODY_BOLD, text_color=ModernTheme.TEXT_GRAY).pack(anchor="w")
        self.user_ent = ctk.CTkEntry(form, placeholder_text="e.g. juandc",
                                     height=40, font=ModernTheme.BODY)
        self.user_ent.pack(fill="x", pady=(5, 12))
        self.user_ent.bind("<KeyRelease>", self._on_key)

        # Role
        ctk.CTkLabel(form, text=tr("users.modal.fields.role"),
                     font=ModernTheme.BODY_BOLD, text_color=ModernTheme.TEXT_GRAY).pack(anchor="w")
        self.role_cb = ctk.CTkComboBox(form, values=["cashier", "encoder", "viewer", "admin"],
                                       height=40, font=ModernTheme.BODY)
        self.role_cb.set("cashier")
        self.role_cb.pack(fill="x", pady=(5, 12))

        # Password
        ctk.CTkLabel(form, text=tr("users.modal.fields.password"),
                     font=ModernTheme.BODY_BOLD, text_color=ModernTheme.TEXT_GRAY).pack(anchor="w")
        self.pass_ent = ctk.CTkEntry(form, placeholder_text="Enter password",
                                     height=40, show="*", font=ModernTheme.BODY)
        self.pass_ent.pack(fill="x", pady=(5, 8))

        peek = ctk.CTkLabel(self.pass_ent, text="👁", width=30, height=30,
                            text_color=ModernTheme.TEXT_GRAY, font=("Segoe UI", 14),
                            cursor="hand2")
        peek.place(relx=0.97, rely=0.5, anchor="e")
        peek.bind("<ButtonPress-1>",   lambda e: self.pass_ent.configure(show=""))
        peek.bind("<ButtonRelease-1>", lambda e: self.pass_ent.configure(show="*"))

        # ── Live requirement checklist ──────────────────────────────────────
        req_fr = ctk.CTkFrame(form, fg_color="#f8f9fa", corner_radius=6)
        req_fr.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(req_fr, text="Password requirements:",
                     font=("Segoe UI", 9, "bold"), text_color="#555").pack(
                     anchor="w", padx=10, pady=(8, 2))

        self._req_labels = {}
        requirements = [
            ("length",  "At least 12 characters"),
            ("upper",   "At least one uppercase letter (A–Z)"),
            ("lower",   "At least one lowercase letter (a–z)"),
            ("digit",   "At least one digit (0–9)"),
            ("special", "At least one special character (!@#$%^&*…)"),
        ]
        for key, text in requirements:
            lbl = ctk.CTkLabel(req_fr, text=f"  ✗  {text}",
                               font=("Segoe UI", 9), text_color="#cc0000", anchor="w")
            lbl.pack(fill="x", padx=10, pady=1)
            self._req_labels[key] = lbl
        ctk.CTkLabel(req_fr, text="", height=4).pack()

        self.pass_ent.bind("<KeyRelease>", self._on_key)

        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<Return>", lambda _event: self.save())
        self.after(100, self.name_ent.focus_set)

    def _check_requirements(self, pwd: str) -> dict:
        re = self._re
        return {
            "length":  len(pwd) >= 12,
            "upper":   bool(re.search(r"[A-Z]", pwd)),
            "lower":   bool(re.search(r"[a-z]", pwd)),
            "digit":   bool(re.search(r"\d", pwd)),
            "special": bool(re.search(r"[!@#$%^&*()\-_=+\[\]{}|;:',.<>?/`~\"\\]", pwd)),
        }

    def _on_key(self, event=None):
        pwd = self.pass_ent.get()
        results = self._check_requirements(pwd)
        all_ok = all(results.values())

        for key, ok in results.items():
            lbl = self._req_labels[key]
            body = lbl.cget("text")[4:]
            lbl.configure(
                text=f"  {'✓' if ok else '✗'}  {body}",
                text_color="#1a7a1a" if ok else "#cc0000",
            )

        # Only enable Create when password is valid AND name/username are filled
        name_ok = bool(self.name_ent.get().strip())
        user_ok = bool(self.user_ent.get().strip())
        self.create_btn.configure(state="normal" if (all_ok and name_ok and user_ok) else "disabled")

    def _cancel(self):
        if not self._creating:
            self.destroy()

    def _set_creation_state(self, creating):
        self._creating = bool(creating)
        field_state = "disabled" if self._creating else "normal"
        for widget in (
            self.name_ent,
            self.user_ent,
            self.role_cb,
            self.pass_ent,
        ):
            widget.configure(state=field_state)

        self.cancel_btn.configure(
            state="disabled" if self._creating else "normal"
        )
        self.create_btn.configure(
            text="CREATING..." if self._creating else tr("users.modal.btn_create"),
            state="disabled",
        )
        if not self._creating:
            self._on_key()

    def save(self):
        if self._creating:
            return

        name = self.name_ent.get().strip()
        user = self.user_ent.get().strip().lower()
        role = self.role_cb.get()
        pwd = self.pass_ent.get().strip()

        if not name or not user or not pwd:
            ErrorDialog(
                self,
                tr("common.error"),
                tr("users.messages.error_fields"),
            )
            return

        results = self._check_requirements(pwd)
        if not all(results.values()):
            ErrorDialog(
                self,
                tr("common.error"),
                "Password does not meet all requirements.",
            )
            return

        confirmation = ConfirmDialog(
            self,
            "Confirm New User",
            _user_creation_confirmation_message(name, user, role),
            confirm_text="CONFIRM & CREATE",
            cancel_text="REVIEW DETAILS",
        )
        self.wait_window(confirmation)
        if not confirmation.result:
            return

        self._set_creation_state(True)

        def worker():
            try:
                result = auth.create_user(name, user, pwd, role)
                self.after(
                    0,
                    lambda response=result: self._creation_succeeded(
                        response,
                        name,
                        user,
                        role,
                    ),
                )
            except Exception as exc:
                self.after(
                    0,
                    lambda error=exc: self._creation_failed(error),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _creation_succeeded(self, response, full_name, username, role):
        if not isinstance(response, dict) or response.get("status") != "created":
            self._creation_failed(
                RuntimeError(
                    "The server did not confirm that the account was created."
                )
            )
            return

        parent = self.master.winfo_toplevel()
        self.callback(username)
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        messagebox.showinfo(
            "User Created",
            (
                f"User account created successfully.\n\n"
                f"Full name: {full_name}\n"
                f"Username: {username}\n"
                f"Role: {str(role or '').upper()}"
            ),
            parent=parent,
        )

    def _creation_failed(self, error):
        self._set_creation_state(False)
        ErrorDialog(self, "User Creation Failed", str(error))


class ResetPasswordModal(ctk.CTkToplevel):
    def __init__(self, parent, username, user_id, callback, refresh_audit_cb):
        super().__init__(parent)
        self.title(tr("users.messages.reset_title"))
        self.geometry("450x480")
        self.resizable(False, False)
        self.username = username
        self.user_id = user_id
        self.callback = callback
        self.refresh_audit_cb = refresh_audit_cb

        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)

        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-450)//2}+{(sh-480)//2}")

        self.setup_ui()

    def setup_ui(self):
        import re
        self._re = re

        self.configure(fg_color="white")

        # Header
        header_fr = ctk.CTkFrame(self, fg_color=ModernTheme.WARNING, height=70, corner_radius=0)
        header_fr.pack(fill="x")
        ctk.CTkLabel(header_fr, text=f"🔑 Reset Password: {self.username}",
                     font=ModernTheme.H3, text_color="white").pack(pady=20)

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=40, pady=15)

        ctk.CTkLabel(form,
                     text=tr("users.messages.reset_prompt").replace("{user}", self.username),
                     font=ModernTheme.BODY, text_color=ModernTheme.TEXT_GRAY,
                     wraplength=370, justify="left").pack(anchor="w", pady=(0, 10))

        # Password entry with peek toggle
        ctk.CTkLabel(form, text=tr("users.modal.fields.password"),
                     font=ModernTheme.BODY_BOLD, text_color=ModernTheme.TEXT_GRAY).pack(anchor="w")

        self.pass_ent = ctk.CTkEntry(form, placeholder_text="Enter new password",
                                     height=40, show="*", font=ModernTheme.BODY)
        self.pass_ent.pack(fill="x", pady=(5, 8))

        peek = ctk.CTkLabel(self.pass_ent, text="👁", width=30, height=30,
                            text_color=ModernTheme.TEXT_GRAY, font=("Segoe UI", 14),
                            cursor="hand2")
        peek.place(relx=0.97, rely=0.5, anchor="e")
        peek.bind("<ButtonPress-1>",   lambda e: self.pass_ent.configure(show=""))
        peek.bind("<ButtonRelease-1>", lambda e: self.pass_ent.configure(show="*"))

        # ── Live requirement checklist ──────────────────────────────────────
        req_fr = ctk.CTkFrame(form, fg_color="#f8f9fa", corner_radius=6)
        req_fr.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(req_fr, text="Password requirements:",
                     font=("Segoe UI", 9, "bold"),
                     text_color="#555").pack(anchor="w", padx=10, pady=(8, 2))

        self._req_labels = {}
        requirements = [
            ("length",    "At least 12 characters"),
            ("upper",     "At least one uppercase letter (A–Z)"),
            ("lower",     "At least one lowercase letter (a–z)"),
            ("digit",     "At least one digit (0–9)"),
            ("special",   "At least one special character (!@#$%^&*…)"),
        ]
        for key, text in requirements:
            lbl = ctk.CTkLabel(req_fr, text=f"  ✗  {text}",
                               font=("Segoe UI", 9), text_color="#cc0000",
                               anchor="w")
            lbl.pack(fill="x", padx=10, pady=1)
            self._req_labels[key] = lbl

        ctk.CTkLabel(req_fr, text="", height=4).pack()   # bottom padding

        # Wire up live validation
        self.pass_ent.bind("<KeyRelease>", self._on_key)

        # Save button — disabled until all requirements met
        btn_fr = ctk.CTkFrame(self, fg_color="transparent")
        btn_fr.pack(fill="x", side="bottom", pady=15, padx=40)

        ctk.CTkButton(btn_fr, text=tr("users.modal.btn_cancel"),
                      command=self.destroy,
                      fg_color=ModernTheme.SECONDARY, height=40, width=100,
                      font=ModernTheme.BUTTON).pack(side="left")

        self.save_btn = ctk.CTkButton(btn_fr, text=tr("users.messages.reset_title"),
                                      command=self.save,
                                      fg_color=ModernTheme.SUCCESS, height=40, width=250,
                                      font=ModernTheme.BUTTON, state="disabled")
        self.save_btn.pack(side="right")

    def _check_requirements(self, pwd: str) -> dict[str, bool]:
        re = self._re
        return {
            "length":  len(pwd) >= 12,
            "upper":   bool(re.search(r"[A-Z]", pwd)),
            "lower":   bool(re.search(r"[a-z]", pwd)),
            "digit":   bool(re.search(r"\d", pwd)),
            "special": bool(re.search(r"[!@#$%^&*()\-_=+\[\]{}|;:',.<>?/`~\"\\]", pwd)),
        }

    def _on_key(self, event=None):
        pwd = self.pass_ent.get()
        results = self._check_requirements(pwd)
        all_ok = all(results.values())

        for key, ok in results.items():
            lbl = self._req_labels[key]
            text_body = lbl.cget("text")[4:]   # strip the icon prefix
            if ok:
                lbl.configure(text=f"  ✓  {text_body}", text_color="#1a7a1a")
            else:
                lbl.configure(text=f"  ✗  {text_body}", text_color="#cc0000")

        self.save_btn.configure(state="normal" if all_ok else "disabled")

    def save(self):
        pwd = self.pass_ent.get().strip()
        results = self._check_requirements(pwd)
        if not all(results.values()):
            ErrorDialog(self, tr("common.error"),
                        "Password does not meet all requirements.")
            return

        try:
            auth.reset_user_password(self.user_id, pwd)
            show_toast(self.master.winfo_toplevel(),
                       tr("users.messages.success_reset"), type="success")
            self.refresh_audit_cb(self.user_id)
            self.callback()
            self.destroy()
        except Exception as e:
            ErrorDialog(self, tr("common.error"), str(e))
