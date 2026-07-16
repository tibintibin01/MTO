import customtkinter as ctk
import api_clients.api_helper as api
from api_clients.offline_manager import manager

class ConnectivityStatusBar(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, height=25, fg_color="#2c3e50")
        
        self.status_dot = ctk.CTkLabel(self, text="●", font=("Segoe UI", 14), text_color="#2ecc71")
        self.status_dot.pack(side="left", padx=(15, 5))
        
        self.status_lbl = ctk.CTkLabel(self, text="SYSTEM ONLINE", font=("Segoe UI", 10, "bold"), text_color="white")
        self.status_lbl.pack(side="left")
        
        self.queue_lbl = ctk.CTkLabel(self, text="", font=("Segoe UI", 10), text_color="#bdc3c7")
        self.queue_lbl.pack(side="right", padx=15)
        self._ws_connected = False
        
        self.update_status()

    def update_status(self):
        """Periodically updates the UI based on global connection state."""
        status = api.get_connection_status()
        count = manager.get_queue_count()
        
        if status == "ONLINE":
            self.status_dot.configure(text_color="#2ecc71")
            self.status_lbl.configure(text="SYSTEM ONLINE & SECURED")
        elif status == "DEGRADED":
            self.status_dot.configure(text_color="#f39c12")
            self.status_lbl.configure(text="SERVER SLOW - RETRYING...")
        elif status == "OFFLINE":
            self.status_dot.configure(text_color="#e74c3c")
            self.status_lbl.configure(text="OFFLINE MODE (LOCAL SAVE ACTIVE)")
        elif status == "SYNCING":
            self.status_dot.configure(text_color="#3498db")
            self.status_lbl.configure(text="SYNCING DATA TO SERVER...")
            
        if count > 0:
            self.queue_lbl.configure(text=f"PENDING SYNC: {count} ITEMS")
        else:
            self.queue_lbl.configure(text="")
            
        # Keep this callback lightweight; queue count is an in-memory value.
        if self.winfo_exists():
            self.after(2000, self.update_status)
        
    def set_ws_status(self, connected: bool):
        """Records optional WebSocket state without replacing API health."""
        self._ws_connected = connected
