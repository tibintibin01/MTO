from datetime import datetime
from utils import tr
import customtkinter as ctk


class SessionWatchdog:
    """
    Monitors user inactivity and logs out after timeout_minutes of no
    keyboard or mouse activity.

    Shows a 2-minute warning dialog before logging out so the user can
    click "Stay Logged In" to reset the timer without losing their work.
    """

    WARNING_SECONDS = 120  # Show warning 2 minutes before logout

    def __init__(self, parent, timeout_minutes, logout_callback):
        self.parent = parent
        self.timeout_minutes = timeout_minutes
        self.logout_callback = logout_callback
        self.last_activity = datetime.now()
        self._warning_shown = False
        self._warning_win = None

    def reset(self):
        """Called on any keyboard or mouse event to reset the inactivity timer."""
        self.last_activity = datetime.now()
        # If the warning dialog is open, close it — user is active
        if self._warning_shown and self._warning_win:
            try:
                self._warning_win.destroy()
            except Exception:
                pass
            self._warning_shown = False
            self._warning_win = None

    def start_monitoring(self):
        # API requests clear local credentials when the server reports that
        # this workstation's session was revoked. Detect that state here so
        # the desktop returns to login instead of continuing with a dead
        # session or displaying a misleading offline indicator.
        from api_clients.api_helper import get_token

        if not get_token():
            self._warning_shown = False
            self._warning_win = None
            self.logout_callback()
            return

        elapsed = (datetime.now() - self.last_activity).total_seconds()
        timeout_secs = self.timeout_minutes * 60

        if elapsed >= timeout_secs:
            # Time's up — log out
            self._warning_shown = False
            self._warning_win = None
            self.logout_callback()
            return

        # Show warning when 2 minutes remain
        warning_threshold = timeout_secs - self.WARNING_SECONDS
        if elapsed >= warning_threshold and not self._warning_shown:
            self._warning_shown = True
            remaining = int(timeout_secs - elapsed)
            self.parent.after(0, lambda: self._show_warning(remaining))

        # Check every 30 seconds
        self.parent.after(30000, self.start_monitoring)

    def _show_warning(self, remaining_seconds):
        """Shows a non-blocking warning dialog with a countdown."""
        if self._warning_win:
            return  # Already showing

        remaining_min = max(1, remaining_seconds // 60)

        win = ctk.CTkToplevel(self.parent)
        win.title("")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.overrideredirect(True)
        self._warning_win = win

        # Center over parent
        dw, dh = 400, 220
        px = self.parent.winfo_rootx() + (self.parent.winfo_width() // 2) - (dw // 2)
        py = self.parent.winfo_rooty() + (self.parent.winfo_height() // 2) - (dh // 2)
        win.geometry(f"{dw}x{dh}+{px}+{py}")

        outer = ctk.CTkFrame(
            win,
            fg_color=("#1e2530", "#1e2530"),
            corner_radius=16,
            border_width=1,
            border_color=("#e67e22", "#e67e22"),
        )
        outer.pack(fill="both", expand=True, padx=2, pady=2)

        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.pack(fill="x", padx=22, pady=(20, 12))

        icon_fr = ctk.CTkFrame(body, width=48, height=48, corner_radius=24, fg_color="#e67e22")
        icon_fr.pack(side="left", padx=(0, 14))
        icon_fr.pack_propagate(False)
        ctk.CTkLabel(icon_fr, text="⏱", font=("Segoe UI Emoji", 20), text_color="white").place(relx=0.5, rely=0.5, anchor="center")

        text_fr = ctk.CTkFrame(body, fg_color="transparent")
        text_fr.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(text_fr, text="Session Expiring Soon", font=("Segoe UI", 13, "bold"), text_color="white", anchor="w").pack(fill="x")
        ctk.CTkLabel(
            text_fr,
            text=f"You will be logged out in ~{remaining_min} minute(s)\ndue to inactivity.",
            font=("Segoe UI", 10),
            text_color="#8b949e",
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(4, 0))

        ctk.CTkFrame(outer, height=1, fg_color="#2c3e50").pack(fill="x")

        btn_fr = ctk.CTkFrame(outer, fg_color="transparent")
        btn_fr.pack(fill="x", padx=18, pady=14)

        def stay():
            self.reset()  # reset() will close the window

        def logout_now():
            win.destroy()
            self._warning_shown = False
            self._warning_win = None
            self.logout_callback()

        ctk.CTkButton(
            btn_fr, text="Log Out Now", command=logout_now,
            fg_color="#2c3e50", hover_color="#34495e", text_color="#8b949e",
            font=("Segoe UI", 11), height=34, corner_radius=8, width=110,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_fr, text="  ✓  Stay Logged In", command=stay,
            fg_color="#e67e22", hover_color="#f39c12", text_color="white",
            font=("Segoe UI", 12, "bold"), height=34, corner_radius=8, width=160,
        ).pack(side="right")

        win.bind("<Return>", lambda e: stay())
        win.bind("<Escape>", lambda e: stay())
        win.focus_set()


def show_session_expired_dialog(parent, on_confirm):
    expired_win = ctk.CTkToplevel(parent)
    expired_win.title("")
    expired_win.resizable(False, False)
    expired_win.attributes("-topmost", True)
    expired_win.overrideredirect(True)

    dw, dh = 400, 200
    px = parent.winfo_rootx() + (parent.winfo_width() // 2) - (dw // 2)
    py = parent.winfo_rooty() + (parent.winfo_height() // 2) - (dh // 2)
    expired_win.geometry(f"{dw}x{dh}+{px}+{py}")

    outer = ctk.CTkFrame(
        expired_win,
        fg_color=("#1e2530", "#1e2530"),
        corner_radius=16,
        border_width=1,
        border_color=("#e74c3c", "#e74c3c"),
    )
    outer.pack(fill="both", expand=True, padx=2, pady=2)

    body = ctk.CTkFrame(outer, fg_color="transparent")
    body.pack(fill="x", padx=22, pady=(22, 12))

    icon_fr = ctk.CTkFrame(body, width=48, height=48, corner_radius=24, fg_color="#e74c3c")
    icon_fr.pack(side="left", padx=(0, 14))
    icon_fr.pack_propagate(False)
    ctk.CTkLabel(icon_fr, text="🔒", font=("Segoe UI Emoji", 20), text_color="white").place(relx=0.5, rely=0.5, anchor="center")

    text_fr = ctk.CTkFrame(body, fg_color="transparent")
    text_fr.pack(side="left", fill="both", expand=True)
    ctk.CTkLabel(text_fr, text=tr("common.session_expired_title"), font=("Segoe UI", 13, "bold"), text_color="white", anchor="w").pack(fill="x")
    ctk.CTkLabel(text_fr, text=tr("common.session_expired_msg"), font=("Segoe UI", 10), text_color="#8b949e", anchor="w", wraplength=240, justify="left").pack(fill="x", pady=(4, 0))

    ctk.CTkFrame(outer, height=1, fg_color="#2c3e50").pack(fill="x")

    btn_fr = ctk.CTkFrame(outer, fg_color="transparent")
    btn_fr.pack(fill="x", padx=18, pady=14)

    ctk.CTkButton(
        btn_fr, text="  Log In Again", command=on_confirm,
        fg_color="#e74c3c", hover_color="#c0392b", text_color="white",
        font=("Segoe UI", 12, "bold"), height=36, corner_radius=8,
    ).pack(fill="x")

    expired_win.bind("<Return>", lambda e: on_confirm())
    expired_win.focus_set()
