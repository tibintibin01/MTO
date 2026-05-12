from datetime import datetime
from utils import tr
import customtkinter as ctk

class SessionWatchdog:
    def __init__(self, parent, timeout_minutes, logout_callback):
        self.parent = parent
        self.timeout_minutes = timeout_minutes
        self.logout_callback = logout_callback
        self.last_activity = datetime.now()
        
    def reset(self):
        self.last_activity = datetime.now()
        
    def start_monitoring(self):
        elapsed = (datetime.now() - self.last_activity).total_seconds()
        if elapsed > (self.timeout_minutes * 60):
            self.logout_callback()
            return
        # Check every 30 seconds
        self.parent.after(30000, self.start_monitoring)

def show_session_expired_dialog(parent, on_confirm):
    expired_win = ctk.CTkToplevel(parent)
    expired_win.title(tr("common.session_expired_title"))
    expired_win.geometry("450x250")
    expired_win.attributes("-topmost", True)
    expired_win.grab_set()
    
    expired_win.update_idletasks()
    x, y = parent.winfo_x() + (parent.winfo_width() // 2) - 225, parent.winfo_y() + (parent.winfo_height() // 2) - 125
    expired_win.geometry(f"+{x}+{y}")
    
    content = ctk.CTkFrame(expired_win, fg_color="transparent")
    content.pack(expand=True, fill="both", padx=30, pady=30)
    
    ctk.CTkLabel(content, text="🚨 " + tr("common.session_expired_title"), font=("Segoe UI", 20, "bold"), text_color="#e74c3c").pack(pady=(0, 10))
    ctk.CTkLabel(content, text=tr("common.session_expired_msg"), font=("Segoe UI", 12), wraplength=350).pack(pady=10)
    ctk.CTkButton(content, text=tr("common.ok"), command=on_confirm, fg_color="#e74c3c", hover_color="#c0392b", width=120).pack(pady=(15, 0))
