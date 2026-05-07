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

import api_clients.auth_service as auth
import api_clients.system_service as system
from api_clients.auth_service import verify_user_login
from utils import log_error_to_file
import dashboard
from theme_manager import setup_theme, ModernTheme

# Initialize Theme
setup_theme()

# CRITICAL SECURITY CHECK
if not os.getenv("SECRET_KEY") or len(os.getenv("SECRET_KEY", "")) < 16:
    print("CRITICAL SECURITY ERROR: SECRET_KEY is missing or too weak (min 16 chars).")
    print("Please set the SECRET_KEY environment variable in your .env file.")
    sys.exit(1)

def handle_global_exception(exc_type: type, exc_value: BaseException, exc_traceback: Any) -> None:
    traceback_text = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    log_path = log_error_to_file('Unhandled application error', exc_value, traceback_text=traceback_text)
    try:
        suffix = f'\n\nLogged to:\n{log_path}' if log_path else ''
        from tkinter import messagebox
        messagebox.showerror('System Error', f'An unexpected error occurred.{suffix}')
    except Exception as e:
        print(f"FAILED TO SHOW ERROR MESSAGEBOX: {e}")

sys.excepthook = handle_global_exception

class LoginApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        
        self.title("Treasury Management System | Secure Access")
        self.geometry("800x550")
        self.resizable(True, True)
        self.minsize(800, 550)
        
        # Grid layout (Mathematically Equal Split)
        self.grid_columnconfigure(0, weight=1, uniform="column") # Side image
        self.grid_columnconfigure(1, weight=1, uniform="column") # Login form
        self.grid_rowconfigure(0, weight=1)
        
        # --- Sidebar / Branding ---
        self.brand_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#1f538d", border_width=0)
        self.brand_frame.grid(row=0, column=0, sticky="nsew")
        
        try:
            self.logo_img = ctk.CTkImage(light_image=Image.open("bagongpilipinas.png"),
                                        dark_image=Image.open("bagongpilipinas.png"),
                                        size=(400, 550))
            self.logo_label = ctk.CTkLabel(self.brand_frame, image=self.logo_img, text="")
            self.logo_label.pack(fill="both", expand=True)
        except Exception as e:
            log_error_to_file("Failed to load side-branding image", e)
            self.logo_label = ctk.CTkLabel(self.brand_frame, text="REVENUE\nSYSTEM", font=("Segoe UI", 48, "bold"), text_color="white")
            self.logo_label.pack(expand=True)
            
        # --- Login Form ---
        self.login_frame = ctk.CTkFrame(self, corner_radius=0, border_width=0)
        self.login_frame.grid(row=0, column=1, sticky="nsew")
        
        self.content_frame = ctk.CTkFrame(self.login_frame, fg_color="transparent")
        self.content_frame.place(relx=0.5, rely=0.5, anchor="center")
        
        ctk.CTkLabel(self.content_frame, text="Welcome Back", font=ModernTheme.H1).pack(pady=(0, 5))
        ctk.CTkLabel(self.content_frame, text="Enter your credentials to access the system", font=ModernTheme.BODY, text_color="gray").pack(pady=(0, 30))
        
        self.ue = ctk.CTkEntry(self.content_frame, width=300, height=45, placeholder_text="Username", font=ModernTheme.BODY)
        self.ue.pack(pady=10)
        
        self.pe = ctk.CTkEntry(self.content_frame, width=300, height=45, placeholder_text="Password", show="*", font=ModernTheme.BODY)
        self.pe.pack(pady=10)
        
        self.login_btn = ctk.CTkButton(self.content_frame, text="LOG IN", command=self.start_login_thread, 
                                      width=300, height=45, font=ModernTheme.BUTTON, corner_radius=8)
        self.login_btn.pack(pady=(30, 10))
        
        self.status_label = ctk.CTkLabel(self.content_frame, text="", text_color="#e74c3c", font=ModernTheme.BODY)
        self.status_label.pack()
        
        self.bind("<Return>", lambda e: self.start_login_thread())

    def start_login_thread(self):
        """Asynchronous UI: Performs login in a thread to keep UI fluid."""
        self.login_btn.configure(state="disabled", text="AUTHENTICATING...")
        self.status_label.configure(text="")
        
        u, p = self.ue.get(), self.pe.get()
        threading.Thread(target=self.do_login, args=(u, p), daemon=True).start()

    def do_login(self, u, p) -> None:
        try:
            auth_result = verify_user_login(u, p)
            # Use after() to update UI from thread
            self.after(0, self.handle_login_result, auth_result)
        except Exception as e:
            log_error_to_file("Login Background Task Failed", e)
            self.after(0, lambda: self.status_label.configure(text=f"Connection Error: {str(e)}"))
            self.after(0, lambda: self.login_btn.configure(state="normal", text="LOG IN"))

    def handle_login_result(self, auth_result):
        if auth_result:
            system.log_action(auth_result, "User login successful")
            self.destroy()
            dashboard.open_dashboard(auth_result)
        else:
            self.status_label.configure(text="Invalid Username or Password")
            self.login_btn.configure(state="normal", text="LOG IN")

if __name__ == "__main__":
    app = LoginApp()
    app.mainloop()
