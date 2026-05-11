from pathlib import Path
import sys
import traceback
import os
import threading
import customtkinter as ctk
from PIL import Image
from datetime import datetime, timedelta
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

# Step 1: Define absolute paths
BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR # In this repo, assets are currently in root

import api_clients.auth_service as auth
import api_clients.system_service as system
from api_clients.auth_service import verify_user_login
from utils import log_error_to_file, tr
import dashboard
from theme_manager import setup_theme, ModernTheme
from ui_components import ErrorDialog

# Initialize Theme
setup_theme("dark")

# CRITICAL SECURITY CHECK
if not os.getenv("SECRET_KEY") or len(os.getenv("SECRET_KEY", "")) < 16:
    print("CRITICAL SECURITY ERROR: SECRET_KEY is missing or too weak (min 16 chars).")
    sys.exit(1)

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

        self.title(f"Treasury Management System | {tr('common.error') if not auth else 'Secure Access'}")
        self.geometry("900x600")
        self.minsize(500, 500)
        
        # Step 2: Bind resize for responsiveness
        self.bind("<Configure>", self._on_resize)
        self.is_dark = True

        # Grid layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Sidebar / Branding ---
        # Using a deeper shadow color (#050c17) for perfect blending
        self.brand_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#050c17", border_width=0)
        self.brand_frame.grid(row=0, column=0, sticky="nsew")

        try:
            logo_path = ASSETS_DIR / "bagongpilipinas.png"
            self.logo_img = ctk.CTkImage(
                light_image=Image.open(logo_path),
                dark_image=Image.open(logo_path),
                size=(600, 800), # Massive overfill to guarantee zero gaps on high-DPI screens
            )
            # Removed visible 'MTO Logo' text to fix the hanging text issue
            self.logo_label = ctk.CTkLabel(self.brand_frame, image=self.logo_img, text="")
            self.logo_label.pack(fill="both", expand=True, padx=0, pady=0)
        except Exception as e:
            self.logo_label = ctk.CTkLabel(self.brand_frame, text="MTO\nTREASURY", font=ModernTheme.H1, text_color="white")
            self.logo_label.pack(expand=True)

        # --- Login Form ---
        self.login_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.login_frame.grid(row=0, column=1, sticky="nsew")

        self.content_frame = ctk.CTkFrame(self.login_frame, fg_color="transparent")
        self.content_frame.place(relx=0.5, rely=0.5, anchor="center")

        # Step 7: Use tr() for all strings
        ctk.CTkLabel(self.content_frame, text=tr("login.title"), font=ModernTheme.H1).pack(pady=(0, 5))
        ctk.CTkLabel(self.content_frame, text=tr("login.subtitle"), font=ModernTheme.BODY, text_color=ModernTheme.TEXT_GRAY).pack(pady=(0, 30))

        # Fields
        self.ue = ctk.CTkEntry(self.content_frame, width=320, height=50, placeholder_text=tr("login.username"), font=ModernTheme.BODY)
        self.ue.pack(pady=5)
        self.u_err = ctk.CTkLabel(self.content_frame, text="", text_color=ModernTheme.DANGER, font=ModernTheme.BODY_SMALL)
        self.u_err.pack()

        self.pe = ctk.CTkEntry(self.content_frame, width=320, height=50, placeholder_text=tr("login.password"), show="*", font=ModernTheme.BODY)
        self.pe.pack(pady=5)
        self.p_err = ctk.CTkLabel(self.content_frame, text="", text_color=ModernTheme.DANGER, font=ModernTheme.BODY_SMALL)
        self.p_err.pack()

        self.login_btn = ctk.CTkButton(
            self.content_frame, text=tr("login.button"), command=self.start_login_thread,
            width=320, height=50, font=ModernTheme.BUTTON, fg_color=ModernTheme.PRIMARY, hover_color=ModernTheme.PRIMARY_HOVER
        )
        self.login_btn.pack(pady=(20, 10))
        
        self.theme_btn = ctk.CTkButton(self.content_frame, text=tr("login.toggle_theme"), command=self.toggle_theme, width=120, height=30, fg_color="transparent", text_color=ModernTheme.TEXT_GRAY)
        self.theme_btn.pack()

        # Step 6: Keyboard shortcuts
        self.bind("<Return>", lambda e: self.start_login_thread())
        self.bind("<Escape>", lambda e: self.destroy())

    def _on_resize(self, event):
        """Responsive behavior: Hide sidebar on narrow screens."""
        if event.widget == self:
            width, height = event.width, event.height
            if width < 750:
                self.brand_frame.grid_remove()
                self.login_frame.grid_configure(column=0, columnspan=2)
            else:
                self.brand_frame.grid()
                self.login_frame.grid_configure(column=1, columnspan=1)

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
        self.overlay = ctk.CTkFrame(self, fg_color=("white", "black"), corner_radius=0)
        self.overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.overlay.configure(background_corner_colors=(None, None, None, None))
        
        inner = ctk.CTkFrame(self.overlay, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")
        
        ctk.CTkLabel(inner, text=tr("login.authenticating"), font=ModernTheme.H2).pack(pady=10)
        self.progress = ctk.CTkProgressBar(inner, mode="indeterminate", width=250)
        self.progress.pack(pady=10)
        self.progress.start()

    def do_login(self, u, p) -> None:
        try:
            auth_result = verify_user_login(u, p)
            self.after(0, self.handle_login_result, auth_result)
        except Exception as e:
            log_error_to_file("Login Background Task Failed", e)
            self.after(0, lambda: self._hide_overlay_with_error(f"{tr('login.error_network')}: {str(e)}"))

    def _hide_overlay_with_error(self, msg):
        self.overlay.destroy()
        self.p_err.configure(text=msg)

    def handle_login_result(self, auth_result):
        if auth_result:
            system.log_action(auth_result, "User login successful")
            self.destroy()
            dashboard.open_dashboard(auth_result)
        else:
            self.overlay.destroy()
            self.p_err.configure(text=tr("login.error_invalid"))

if __name__ == "__main__":
    app = LoginApp()
    app.mainloop()
