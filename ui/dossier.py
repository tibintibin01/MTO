import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from theme_manager import ModernTheme


class PropertyDossierModal(ctk.CTkToplevel):
    def __init__(self, parent, data):
        super().__init__(parent)
        self.title(f"Property Dossier | {data['master'].get('td_number')}")

        # Responsive sizing
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        ww, wh = min(1200, sw - 100), min(850, sh - 100)
        self.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")

        self.data = data
        self.setup_ui()

        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)

    def setup_ui(self):
        self.configure(fg_color="#ffffff")

        m = self.data["master"]

        # --- HEADER BAR (DARK) ---
        header = ctk.CTkFrame(self, fg_color="#102a43", height=100, corner_radius=0)
        header.pack(fill="x")

        info_fr = ctk.CTkFrame(header, fg_color="transparent")
        info_fr.pack(side="left", padx=30, pady=20)

        ctk.CTkLabel(
            info_fr,
            text=f"PROPERTY HISTORY TIMELINE",
            font=("Segoe UI", 24, "bold"),
            text_color="#ffffff",
        ).pack(anchor="w")
        ctk.CTkLabel(
            info_fr,
            text=f"TD NUMBER: {m.get('td_number')} • OWNER: {m.get('owner_name')}",
            font=("Segoe UI", 13),
            text_color="#bcccdc",
        ).pack(anchor="w")

        # --- MAIN CONTAINER ---
        main_fr = ctk.CTkFrame(self, fg_color="transparent")
        main_fr.pack(fill="both", expand=True, padx=40, pady=20)

        # LEFT: SUMMARY CARD
        left_fr = ctk.CTkFrame(main_fr, fg_color="#f0f4f8", width=300, corner_radius=15)
        left_fr.pack(side="left", fill="y", padx=(0, 20))
        self._setup_summary_panel(left_fr)

        # RIGHT: UNIFIED TIMELINE (The Big Scroll)
        right_fr = ctk.CTkFrame(main_fr, fg_color="transparent")
        right_fr.pack(side="left", fill="both", expand=True)
        self._setup_unified_timeline(right_fr)

    def _setup_summary_panel(self, parent):
        ctk.CTkLabel(
            parent, text="CURRENT STATUS", font=("Segoe UI", 14, "bold"), text_color="#102a43"
        ).pack(pady=(25, 20))

        m = self.data["master"]
        specs = [
            ("BARANGAY", m.get("barangay")),
            ("CLASS", m.get("kind_of_property")),
            ("VALUATION", f"P {float(m.get('assessed_value') or 0):,.2f}"),
            ("EFFECTIVITY", m.get("effectivity_date") or "---"),
        ]

        for label, val in specs:
            f = ctk.CTkFrame(parent, fg_color="white", corner_radius=10)
            f.pack(fill="x", padx=20, pady=6)
            ctk.CTkLabel(f, text=label, font=("Segoe UI", 9, "bold"), text_color="#627d98").pack(pady=(10, 0))
            ctk.CTkLabel(f, text=str(val), font=("Segoe UI", 12, "bold"), text_color="#243b53").pack(pady=(0, 10))

    def _setup_unified_timeline(self, parent):
        # 1. Gather all events
        events = []
        
        # Payments
        for p in self.data.get("payments", []):
            events.append({
                "date": str(p[0]),
                "type": "PAYMENT",
                "title": f"Official Receipt: {p[1]}",
                "subtitle": f"Amount Paid: P {float(p[6] or 0):,.2f}",
                "detail": f"Tax Year: {p[2]}",
                "color": "#2ecc71" # Green
            })

        # Ancestry (Ownership Transfers)
        for a in self.data.get("ancestry", []):
            events.append({
                "date": "LEGACY",
                "type": "TRANSFER",
                "title": f"Transferred from {a.get('owner_name')}",
                "subtitle": f"Previous TD: {a.get('td_number')}",
                "detail": "Genealogical Transition",
                "color": "#3498db" # Blue
            })

        # Audit (Value Reassessments / Updates)
        for log in self.data.get("audit_summary", []):
            if "UPDATE" in log.get("action", ""):
                events.append({
                    "date": str(log.get("timestamp", ""))[:10],
                    "type": "ASSESSMENT",
                    "title": "Property Detail Update",
                    "subtitle": f"Modified by: {log.get('username')}",
                    "detail": "Data Integrity Snapshot",
                    "color": "#9b59b6" # Purple
                })

        # 2. Sort Events (Newest First)
        # Handle 'LEGACY' dates as very old
        def sort_key(e):
            return e["date"] if e["date"] != "LEGACY" else "0000-00-00"
        
        events.sort(key=sort_key, reverse=True)

        # 3. Render Timeline
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        if not events:
            ctk.CTkLabel(scroll, text="No historical data found.", font=("Segoe UI", 14, "italic")).pack(pady=100)
            return

        for e in events:
            # Timeline Container (Row)
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", pady=5)

            # Left side: Date & Marker
            marker_fr = ctk.CTkFrame(row, fg_color="transparent", width=120)
            marker_fr.pack(side="left", fill="y")
            
            ctk.CTkLabel(marker_fr, text=e["date"], font=("Segoe UI", 10, "bold"), text_color="#627d98").pack(pady=(15, 0))
            
            # Dot & Line
            dot = ctk.CTkFrame(marker_fr, width=12, height=12, corner_radius=6, fg_color=e["color"])
            dot.pack(pady=10)
            
            # Right side: Content Card
            card = ctk.CTkFrame(row, fg_color="#f0f4f8", corner_radius=15, border_width=1, border_color="#d9e2ec")
            card.pack(side="left", fill="x", expand=True, padx=(10, 0))

            header_fr = ctk.CTkFrame(card, fg_color="transparent")
            header_fr.pack(fill="x", padx=20, pady=(15, 5))
            
            ctk.CTkLabel(header_fr, text=e["title"], font=("Segoe UI", 13, "bold"), text_color="#102a43").pack(side="left")
            ctk.CTkLabel(header_fr, text=e["type"], font=("Segoe UI", 9, "bold"), text_color="#ffffff", fg_color=e["color"], corner_radius=4, padx=8).pack(side="right")

            ctk.CTkLabel(card, text=e["subtitle"], font=("Segoe UI", 11), text_color="#486581").pack(anchor="w", padx=20)
            ctk.CTkLabel(card, text=e["detail"], font=("Segoe UI", 10, "italic"), text_color="#829ab1").pack(anchor="w", padx=20, pady=(0, 15))
