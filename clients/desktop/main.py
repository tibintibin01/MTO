from pathlib import Path
import sys
import traceback
import os
import threading
import customtkinter as ctk
from PIL import Image
from datetime import datetime, timedelta
from typing import Any, Optional

# Add root folder to sys.path so nested desktop client scripts can import api_clients and utils seamlessly
if getattr(sys, "frozen", False):
    # Running from PyInstaller bundle
    # sys._MEIPASS is the temporary directory where bundled files are unpacked
    ROOT_DIR = Path(sys._MEIPASS).resolve()
    # The actual folder where the .exe is running on the host system
    EXE_DIR = Path(sys.executable).resolve().parent
    
    # Look for .env in the exe's folder or one level up (in case it is inside a dist/ subdirectory)
    env_path = EXE_DIR / ".env"
    if not env_path.exists() and (EXE_DIR.parent / ".env").exists():
        env_path = EXE_DIR.parent / ".env"
else:
    # Running from source code
    BASE_DIR = Path(__file__).resolve().parent
    ROOT_DIR = BASE_DIR.parent.parent
    env_path = ROOT_DIR / ".env"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

ASSETS_DIR = ROOT_DIR # In this repo, assets are currently in root

from dotenv import load_dotenv
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

import api_clients.auth_service as auth
import api_clients.system_service as system
from api_clients.auth_service import verify_user_login
from utils import log_error_to_file, tr
import dashboard
from theme_manager import setup_theme, ModernTheme
from ui_components import ErrorDialog

# Ensure database is up to date
try:
    import migration_manager
    print("DEBUG: Checking database migrations...")
    migration_manager.run_migrations()
    print("DEBUG: Migrations completed successfully.")
except ImportError:
    print("DEBUG: migration_manager not found (headless/standalone client mode). Skipping database migrations.")
except Exception as e:
    print(f"DEBUG: Migration manager crashed: {e}")
    log_error_to_file("Migration auto-run failed", e)

# Initialize Theme
print("DEBUG: Setting up theme...")
setup_theme("dark")

# CRITICAL SECURITY CHECK
if not os.getenv("SECRET_KEY") or len(os.getenv("SECRET_KEY", "")) < 16:
    error_msg = (
        "CRITICAL SECURITY ERROR: SECRET_KEY is missing or too weak (minimum 16 characters).\n\n"
        f"Please ensure a valid '.env' file is present at:\n{env_path.resolve() if 'env_path' in locals() else '.env'}"
    )
    print(error_msg)
    
    # Show user-friendly error popup
    try:
        from tkinter import messagebox
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Municipal Treasury System | Secure Access", error_msg)
        root.destroy()
    except Exception as popup_err:
        print(f"Failed to display popup error: {popup_err}")
    sys.exit(1)

print("DEBUG: Starting LoginApp...")

def handle_global_exception(exc_type, exc_value, exc_traceback):
    traceback_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    log_path = log_error_to_file("Unhandled application error", exc_value, traceback_text=traceback_text)
    
    # Use the new ErrorDialog
    try:
        from main import app
        ErrorDialog(app, tr("common.system_error"), f"An unexpected error occurred.\n\nLogged to: {log_path}")
    except:
        from tkinter import messagebox
        messagebox.showerror(tr("common.system_error"), "A critical system error occurred.")

sys.excepthook = handle_global_exception

class LoginApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        
        # Ensure any residual tokens are cleared on startup of login screen
        auth.logout()

        self.title(f"Treasury Management System | {tr('common.error') if not auth else 'Secure Access'}")
        self.minsize(900, 600)

        # Centre the window on the screen
        win_w, win_h = 1100, 700
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = (screen_w - win_w) // 2
        y = (screen_h - win_h) // 2
        self.geometry(f"{win_w}x{win_h}+{x}+{y}")
        
        # Step 2: Bind resize for responsiveness
        self.bind("<Configure>", self._on_resize)
        self.is_dark = True
        self.auth_result = None

        # Grid layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Sidebar / Branding ---
        # Using pure black (#000000) to match the image's deep space edges
        self.brand_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#000000", border_width=0)
        self.brand_frame.grid(row=0, column=0, sticky="nsew")

        try:
            logo_path = ASSETS_DIR / "bagongpilipinas.png"
            self.logo_img = ctk.CTkImage(
                light_image=Image.open(logo_path),
                dark_image=Image.open(logo_path),
                size=(600, 800), # Initial fit for 1100x700
            )
            # Step 11: Overscan Shield - Place the image at 110% size to eliminate rounding gaps
            self.logo_label = ctk.CTkLabel(self.brand_frame, image=self.logo_img, text="")
            self.logo_label.place(relx=0.5, rely=0.5, relwidth=1.1, relheight=1.1, anchor="center")
        except Exception as e:
            self.logo_label = ctk.CTkLabel(self.brand_frame, text="REVENUE\nSYSTEM", font=ModernTheme.H1, text_color="white")
            self.logo_label.pack(expand=True)

        # --- Login Form (right panel) ---
        # Premium dark panel with gradient feel, frosted card, and trust badges
        self.login_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#0a1628")
        self.login_frame.grid(row=0, column=1, sticky="nsew")

        # Subtle radial glow behind the form — drawn as a large dim circle
        glow = ctk.CTkFrame(
            self.login_frame,
            width=420, height=420,
            corner_radius=210,
            fg_color="#0d2044",
            border_width=0,
        )
        glow.place(relx=0.5, rely=0.45, anchor="center")

        # Thin vertical separator on the left edge — gradient feel
        sep = ctk.CTkFrame(self.login_frame, width=1, fg_color="#1a3a5c")
        sep.place(x=0, rely=0, relheight=1)

        # Centered content card — frosted glass effect
        card = ctk.CTkFrame(
            self.login_frame,
            fg_color=("#1a2744", "#1a2744"),
            corner_radius=18,
            border_width=1,
            border_color="#1f4e78",
        )
        card.place(relx=0.5, rely=0.5, anchor="center")

        self.content_frame = ctk.CTkFrame(card, fg_color="transparent")
        self.content_frame.pack(padx=40, pady=36)

        # MTO seal badge
        badge_fr = ctk.CTkFrame(
            self.content_frame,
            width=56, height=56,
            corner_radius=28,
            fg_color="#1f4e78",
            border_width=2,
            border_color="#2c6ea1",
        )
        badge_fr.pack(pady=(0, 14))
        badge_fr.pack_propagate(False)
        ctk.CTkLabel(
            badge_fr, text="🏛",
            font=("Segoe UI Emoji", 24),
            text_color="white",
        ).place(relx=0.5, rely=0.5, anchor="center")

        # Title and subtitle
        ctk.CTkLabel(
            self.content_frame,
            text=tr("login.title"),
            font=("Inter", 22, "bold"),
            text_color="#e2e8f0",
        ).pack(pady=(0, 4))
        ctk.CTkLabel(
            self.content_frame,
            text=tr("login.subtitle"),
            font=ModernTheme.BODY,
            text_color="#64748b",
        ).pack(pady=(0, 24))

        # Fields
        self.ue = ctk.CTkEntry(self.content_frame, width=320, height=50, placeholder_text=tr("login.username"), font=ModernTheme.BODY)
        self.ue.pack(pady=5)
        self.u_err = ctk.CTkLabel(self.content_frame, text="", text_color=ModernTheme.DANGER, font=ModernTheme.BODY_SMALL)
        self.u_err.pack()

        self.pe = ctk.CTkEntry(self.content_frame, width=320, height=50, placeholder_text=tr("login.password"), show="*", font=ModernTheme.BODY)
        self.pe.pack(pady=5)
        
        self.peek_lbl = ctk.CTkLabel(
            self.pe, text="👁", width=30, height=30, 
            text_color=ModernTheme.TEXT_GRAY, font=("Segoe UI", 16),
            cursor="hand2"
        )
        self.peek_lbl.place(relx=0.96, rely=0.5, anchor="e")
        
        self.peek_lbl.bind("<ButtonPress-1>", lambda e: self.pe.configure(show=""))
        self.peek_lbl.bind("<ButtonRelease-1>", lambda e: self.pe.configure(show="*"))
        
        self.p_err = ctk.CTkLabel(self.content_frame, text="", text_color=ModernTheme.DANGER, font=ModernTheme.BODY_SMALL)
        self.p_err.pack()

        # Remember Me Checkbox
        self.remember_var = ctk.BooleanVar(value=False)
        self.remember_cb = ctk.CTkCheckBox(
            self.content_frame, 
            text=tr("login.remember_me"), 
            variable=self.remember_var, 
            font=ModernTheme.BODY_SMALL,
            fg_color=ModernTheme.PRIMARY,
            hover_color=ModernTheme.PRIMARY_HOVER,
            text_color=ModernTheme.TEXT_GRAY
        )
        self.remember_cb.pack(pady=(5, 10), anchor="w")

        # Load remembered username
        from utils import ConfigManager
        ConfigManager.load()
        remembered = ConfigManager.get("remembered_username", "")
        if remembered:
            self.ue.insert(0, remembered)
            self.remember_var.set(True)

        self.login_btn = ctk.CTkButton(
            self.content_frame, text=tr("login.button"), command=self.start_login_thread,
            width=320, height=50, font=ModernTheme.BUTTON,
            fg_color="#1565c0", hover_color="#1976d2",
            corner_radius=10,
        )
        self.login_btn.pack(pady=(20, 10))

        self.theme_btn = ctk.CTkButton(
            self.content_frame, text=tr("login.toggle_theme"),
            command=self.toggle_theme, width=120, height=30,
            fg_color="transparent", text_color="#475569",
            hover_color="#1e293b",
        )
        self.theme_btn.pack(pady=(0, 4))

        # Trust badges row
        badges_fr = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        badges_fr.pack(pady=(12, 0))
        for badge_text in ("🔒 Encrypted", "📋 Audit Logged", "✅ COA Compliant"):
            ctk.CTkLabel(
                badges_fr,
                text=badge_text,
                font=("Inter", 9, "bold"),
                text_color="#334155",
                fg_color="#0f172a",
                corner_radius=6,
                padx=8, pady=3,
            ).pack(side="left", padx=4)

        # Version watermark at bottom of right panel
        ctk.CTkLabel(
            self.login_frame,
            text="Municipal Treasury Office  ·  v2.1.0",
            font=("Inter", 8),
            text_color="#1e3a5f",
        ).place(relx=0.5, rely=0.97, anchor="center")

        # Step 6: Keyboard shortcuts
        self.bind("<Return>", lambda e: self.start_login_thread())
        self.bind("<Escape>", lambda e: self.destroy())

    def _on_resize(self, event):
        """Responsive behavior: Hide sidebar on narrow screens and resize logo."""
        if event.widget == self:
            width, height = event.width, event.height
            if width < 750:
                self.brand_frame.grid_remove()
                self.login_frame.grid_configure(column=0, columnspan=2)
            else:
                self.brand_frame.grid()
                self.login_frame.grid_configure(column=1, columnspan=1)
                
                # Dynamic Image Resizing with Overscan
                try:
                    # Calculate half-width for the sidebar and add 10% overscan
                    new_w = int((width // 2) * 1.1)
                    new_h = int(height * 1.1)
                    # Update CTkImage size
                    self.logo_img.configure(size=(new_w, new_h))
                except:
                    pass

    def toggle_theme(self):
        self.is_dark = not self.is_dark
        setup_theme("dark" if self.is_dark else "light")

    def start_login_thread(self):
        # Step 4: Inline Validation
        u, p = self.ue.get().strip(), self.pe.get().strip()
        has_err = False
        
        self.u_err.configure(text="")
        self.p_err.configure(text="")
        
        if not u:
            self.u_err.configure(text=tr("login.error_required"))
            has_err = True
        if not p:
            self.p_err.configure(text=tr("login.error_required"))
            has_err = True
        
        if has_err: return

        # Step 5: Loading Overlay
        self._show_overlay()
        threading.Thread(target=self.do_login, args=(u, p), daemon=True).start()

    def _show_overlay(self):
        # Full-screen overlay with a dark gradient feel
        self.overlay = ctk.CTkFrame(
            self,
            fg_color=("#0d1117", "#0d1117"),
            corner_radius=0,
        )
        self.overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

        # ── Centered card ────────────────────────────────────────────────────
        card = ctk.CTkFrame(
            self.overlay,
            fg_color=("#161b22", "#161b22"),
            corner_radius=20,
            border_width=1,
            border_color=("#21262d", "#21262d"),
            width=420,
            height=260,
        )
        card.place(relx=0.5, rely=0.5, anchor="center")
        card.pack_propagate(False)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")

        # Seal / icon circle
        icon_fr = ctk.CTkFrame(
            inner, width=68, height=68, corner_radius=34,
            fg_color="#1f4e78",
            border_width=2,
            border_color="#2c6ea1",
        )
        icon_fr.pack(pady=(0, 18))
        icon_fr.pack_propagate(False)

        # Use a fixed-width label with center justify to avoid emoji offset
        icon_lbl = ctk.CTkLabel(
            icon_fr,
            text="🏛",
            font=("Segoe UI Emoji", 28),
            text_color="white",
            width=68,
            height=68,
            justify="center",
            anchor="center",
        )
        icon_lbl.place(relx=0.5, rely=0.5, anchor="center")

        # System name
        ctk.CTkLabel(
            inner,
            text="MUNICIPAL TREASURY SYSTEM",
            font=("Segoe UI", 13, "bold"),
            text_color="#3498db",
        ).pack()

        # Status message — updated during login steps
        self._status_lbl = ctk.CTkLabel(
            inner,
            text="Verifying credentials...",
            font=("Segoe UI", 11),
            text_color="#8b949e",
        )
        self._status_lbl.pack(pady=(6, 14))

        # Progress bar — wider, thicker, rounded
        self.progress = ctk.CTkProgressBar(
            inner,
            mode="indeterminate",
            width=300,
            height=6,
            corner_radius=3,
            progress_color="#3498db",
            fg_color="#21262d",
        )
        self.progress.pack()
        self.progress.start()

        # Subtle footer
        ctk.CTkLabel(
            self.overlay,
            text="Secure · Encrypted · Audited",
            font=("Segoe UI", 9),
            text_color="#30363d",
        ).place(relx=0.5, rely=0.95, anchor="center")

        # Cycle status messages to give feedback during the wait
        self._status_messages = [
            "Verifying credentials...",
            "Checking account status...",
            "Loading permissions...",
            "Preparing dashboard...",
        ]
        self._status_index = 0
        self._cycle_status()

    def _cycle_status(self):
        """Rotates the status message every 800ms while the overlay is visible."""
        if not hasattr(self, "overlay") or not self.overlay.winfo_exists():
            return
        if not hasattr(self, "_status_lbl") or not self._status_lbl.winfo_exists():
            return
        self._status_index = (self._status_index + 1) % len(self._status_messages)
        self._status_lbl.configure(text=self._status_messages[self._status_index])
        self.after(800, self._cycle_status)

    def do_login(self, u, p) -> None:
        try:
            auth_result = verify_user_login(u, p)
            self.after(0, self.handle_login_result, auth_result)
        except Exception as e:
            err_msg = str(e)
            log_error_to_file("Login Background Task Failed", e)
            if err_msg.startswith("Error: "):
                clean_msg = err_msg[7:]
            else:
                clean_msg = f"{tr('login.error_network')}: {err_msg}"
            self.after(0, lambda m=clean_msg: self._hide_overlay_with_error(m))

    def _hide_overlay_with_error(self, msg):
        self.overlay.destroy()
        self.p_err.configure(text=msg)

    def handle_login_result(self, auth_result):
        if auth_result:
            system.log_action(auth_result, "User login successful")
            self.auth_result = auth_result
            
            # Save or clear remembered username
            from utils import ConfigManager
            ConfigManager.load()
            if self.remember_var.get():
                ConfigManager.set("remembered_username", self.ue.get().strip())
            else:
                ConfigManager.set("remembered_username", "")
                
            self.destroy()
        else:
            self.overlay.destroy()
            self.p_err.configure(text=tr("login.error_invalid"))

if __name__ == "__main__":
    while True:
        app = LoginApp()
        app.mainloop()
        
        auth_res = getattr(app, "auth_result", None)
        if auth_res:
            should_relogin = dashboard.open_dashboard(auth_res)
            if should_relogin:
                continue
        break
