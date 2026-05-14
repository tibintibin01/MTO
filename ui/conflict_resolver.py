import customtkinter as ctk
from theme_manager import ModernTheme
from utils import tr

class ConflictArbitrationModal(ctk.CTkToplevel):
    def __init__(self, parent, action_id, local_data, server_data, resolve_callback):
        super().__init__(parent)
        self.title("🏛️ MTO | CONFLICT ARBITRATION")
        self.geometry("900x600")
        self.attributes("-topmost", True)
        self.grab_set()
        
        self.action_id = action_id
        self.local_data = local_data
        self.server_data = server_data
        self.resolve_callback = resolve_callback
        
        self.setup_ui()
        self._center_window()

    def setup_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color="#e67e22", corner_radius=0, height=80)
        header.pack(fill="x")
        
        ctk.CTkLabel(header, text="🚨 DATA COLLISION DETECTED", font=("Segoe UI", 24, "bold"), text_color="white").pack(pady=(15, 5))
        ctk.CTkLabel(header, text="Version mismatch found during municipal synchronization. Choose the authoritative version.", font=("Segoe UI", 12), text_color="white").pack(pady=(0, 15))

        # Comparison Area
        comparison_fr = ctk.CTkFrame(self, fg_color="transparent")
        comparison_fr.pack(fill="both", expand=True, padx=20, pady=20)
        comparison_fr.grid_columnconfigure((0, 1), weight=1)
        comparison_fr.grid_rowconfigure(0, weight=1)

        # Local Version
        self._make_version_card(comparison_fr, 0, "YOUR LOCAL EDITS (OFFLINE)", self.local_data, "#3498db")
        
        # Server Version
        self._make_version_card(comparison_fr, 1, "SERVER TRUTH (OFFICE)", self.server_data, "#2ecc71")

        # Actions
        btn_fr = ctk.CTkFrame(self, fg_color="transparent")
        btn_fr.pack(fill="x", padx=20, pady=20)
        
        ctk.CTkButton(btn_fr, text="KEEP MY LOCAL CHANGES", command=lambda: self.resolve("LOCAL"), fg_color="#3498db", hover_color="#2980b9", width=250, height=45, font=ModernTheme.BUTTON).pack(side="left", padx=10)
        ctk.CTkButton(btn_fr, text="ADOPT SERVER VERSION", command=lambda: self.resolve("SERVER"), fg_color="#2ecc71", hover_color="#27ae60", width=250, height=45, font=ModernTheme.BUTTON).pack(side="left", padx=10)
        ctk.CTkButton(btn_fr, text="CANCEL & RESOLVE LATER", command=self.destroy, fg_color="gray", width=200, height=45, font=ModernTheme.BUTTON).pack(side="right", padx=10)

    def _make_version_card(self, parent, col, title, data, color):
        card = ctk.CTkFrame(parent, border_width=2, border_color=color)
        card.grid(row=0, column=col, padx=10, sticky="nsew")
        
        ctk.CTkLabel(card, text=title, font=("Segoe UI", 14, "bold"), text_color=color).pack(pady=15)
        
        # Data View
        text_area = ctk.CTkTextbox(card, font=("Consolas", 12))
        text_area.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        
        other_data = self.server_data if col == 0 else self.local_data
        
        import json
        for key, val in data.items():
            line = f"{key}: {val}\n"
            if key in other_data and other_data[key] != val:
                # Highlight difference
                text_area.insert("end", f"▶ {line}", "diff")
            else:
                text_area.insert("end", f"  {line}")
        
        text_area.tag_config("diff", foreground="#e74c3c", font=("Consolas", 12, "bold"))
        text_area.configure(state="disabled")


    def resolve(self, choice):
        """Signals the coordinator to resolve the conflict."""
        self.resolve_callback(self.action_id, choice)
        self.destroy()

    def _center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")
