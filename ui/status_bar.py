import customtkinter as ctk
from api_clients.api_helper import CONNECTION_STATUS
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
        
        self.update_status()

    def update_status(self):
        """Periodically updates the UI based on global connection state."""
        from api_clients.api_helper import CONNECTION_STATUS as status
        count = manager.get_queue_count()
        
        if status == "ONLINE":
            self.status_dot.configure(text_color="#2ecc71")
            self.status_lbl.configure(text="SYSTEM ONLINE & SECURED")
        elif status == "OFFLINE":
            self.status_dot.configure(text_color="#f1c40f")
            self.status_lbl.configure(text="OFFLINE MODE (LOCAL SAVE ACTIVE)")
        elif status == "SYNCING":
            self.status_dot.configure(text_color="#3498db")
            self.status_lbl.configure(text="SYNCING DATA TO SERVER...")
            
        if count > 0:
            self.queue_lbl.configure(text=f"PENDING SYNC: {count} ITEMS")
        else:
            self.queue_lbl.configure(text="")
            
        # Check every 2 seconds
        self.after(2000, self.update_status)
        
    def set_ws_status(self, connected: bool):
        """Updates the status specifically for WebSocket events."""
        if connected:
            self.status_dot.configure(text_color="#2ecc71")
            self.status_lbl.configure(text="SYSTEM ONLINE • LIVE")
        else:
            self.status_dot.configure(text_color="#e67e22")
            self.status_lbl.configure(text="SYSTEM ONLINE • DISCONNECTED")
