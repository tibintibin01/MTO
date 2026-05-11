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
        self.configure(fg_color="#ffffff")  # Clean white background

        m = self.data["master"]

        # --- HEADER BAR ---
        header = ctk.CTkFrame(self, fg_color="#102a43", height=90, corner_radius=0)
        header.pack(fill="x")

        info_fr = ctk.CTkFrame(header, fg_color="transparent")
        info_fr.pack(side="left", padx=30, pady=15)

        ctk.CTkLabel(
            info_fr,
            text=f"TAX DECLARATION: {m.get('td_number')}",
            font=("Segoe UI", 22, "bold"),
            text_color="#ffffff",
        ).pack(anchor="w")
        ctk.CTkLabel(
            info_fr,
            text=f"OWNER: {m.get('owner_name')}",
            font=("Segoe UI", 13),
            text_color="#bcccdc",
        ).pack(anchor="w")

        # --- MAIN PANELS ---
        main_fr = ctk.CTkFrame(self, fg_color="transparent")
        main_fr.pack(fill="both", expand=True, padx=20, pady=20)

        # LEFT: PROFILE (Deep Contrast)
        left_fr = ctk.CTkFrame(
            main_fr,
            fg_color="#f0f4f8",
            width=320,
            corner_radius=15,
            border_width=1,
            border_color="#d9e2ec",
        )
        left_fr.pack(side="left", fill="y", padx=(0, 15))
        self._setup_profile_panel(left_fr)

        # RIGHT: ANCESTRY & AUDIT
        right_fr = ctk.CTkFrame(main_fr, fg_color="transparent", width=320)
        right_fr.pack(side="right", fill="y", padx=(15, 0))
        self._setup_ancestry_panel(right_fr)

        # CENTER: TIMELINE (Payments)
        center_fr = ctk.CTkFrame(main_fr, fg_color="transparent")
        center_fr.pack(side="left", fill="both", expand=True)
        self._setup_timeline_panel(center_fr)

    def _setup_profile_panel(self, parent):
        ctk.CTkLabel(
            parent,
            text="PROPERTY SPECIFICATIONS",
            font=("Segoe UI", 13, "bold"),
            text_color="#102a43",
        ).pack(pady=(25, 15))

        m = self.data["master"]
        specs = [
            ("PROPERTY INDEX NO (PIN)", m.get("pin") or "NOT ASSIGNED"),
            ("BARANGAY", m.get("barangay") or "NOT SPECIFIED"),
            (
                "LOT / BLOCK NO.",
                f"{m.get('lot_number')} / {m.get('block_number') or '---'}",
            ),
            ("LAND AREA", f"{m.get('area')} SQM"),
            ("PROPERTY CLASSIFICATION", m.get("kind_of_property")),
            ("ASSESSED VALUATION", f"P {float(m.get('assessed_value') or 0):,.2f}"),
            ("FISCAL EFFECTIVITY", m.get("effectivity_date") or "---"),
        ]

        for label, val in specs:
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.pack(fill="x", padx=25, pady=8)
            ctk.CTkLabel(
                f, text=label, font=("Segoe UI", 9, "bold"), text_color="#486581"
            ).pack(anchor="w")
            ctk.CTkLabel(
                f, text=str(val), font=("Segoe UI", 12, "bold"), text_color="#243b53"
            ).pack(anchor="w")

    def _setup_timeline_panel(self, parent):
        ctk.CTkLabel(
            parent,
            text="PAYMENT HISTORY TIMELINE",
            font=("Segoe UI", 13, "bold"),
            text_color="#102a43",
        ).pack(anchor="w", pady=(0, 15))

        scroll = ctk.CTkScrollableFrame(
            parent,
            fg_color="#ffffff",
            corner_radius=15,
            border_width=1,
            border_color="#d9e2ec",
        )
        scroll.pack(fill="both", expand=True)

        payments = self.data["payments"]
        if not payments:
            ctk.CTkLabel(
                scroll,
                text="No collection history found for this record.",
                font=("Segoe UI", 12, "italic"),
                text_color="#627d98",
            ).pack(pady=60)
            return

        for p in payments:
            card = ctk.CTkFrame(scroll, fg_color="#f0f4f8", corner_radius=12)
            card.pack(fill="x", padx=15, pady=8)

            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", padx=20, pady=12)
            ctk.CTkLabel(
                left,
                text=str(p[0]),
                font=("Segoe UI", 13, "bold"),
                text_color="#102a43",
            ).pack(anchor="w")
            ctk.CTkLabel(
                left,
                text=f"OFFICIAL RECEIPT: {p[1]}",
                font=("Segoe UI", 10),
                text_color="#486581",
            ).pack(anchor="w")

            right = ctk.CTkFrame(card, fg_color="transparent")
            right.pack(side="right", padx=20, pady=12)
            ctk.CTkLabel(
                right,
                text=f"P {float(p[6] or 0):,.2f}",
                font=("Segoe UI", 14, "bold"),
                text_color="#22543d",
            ).pack(anchor="e")
            ctk.CTkLabel(
                right,
                text=f"TAX YEAR: {p[2]}",
                font=("Segoe UI", 10, "bold"),
                text_color="#2d3748",
            ).pack(anchor="e")

    def _setup_ancestry_panel(self, parent):
        anc_fr = ctk.CTkFrame(
            parent,
            fg_color="#ffffff",
            corner_radius=15,
            border_width=1,
            border_color="#d9e2ec",
        )
        anc_fr.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            anc_fr,
            text="OWNERSHIP GENEALOGY",
            font=("Segoe UI", 12, "bold"),
            text_color="#102a43",
        ).pack(pady=15)
        self._add_node(
            anc_fr,
            self.data["master"].get("td_number"),
            "Current Master Record",
            is_active=True,
        )

        if self.data["ancestry"]:
            ctk.CTkLabel(
                anc_fr, text="▼", font=("Segoe UI", 16), text_color="#d9e2ec"
            ).pack()
            p = self.data["ancestry"][0]
            self._add_node(
                anc_fr, p.get("td_number"), f"Derived From: {p.get('owner_name')}"
            )
        else:
            ctk.CTkLabel(
                anc_fr,
                text="End of traceable history",
                font=("Segoe UI", 10, "italic"),
                text_color="#627d98",
            ).pack(pady=15)

        audit_fr = ctk.CTkFrame(
            parent,
            fg_color="#ffffff",
            corner_radius=15,
            border_width=1,
            border_color="#d9e2ec",
        )
        audit_fr.pack(fill="both", expand=True)

        ctk.CTkLabel(
            audit_fr,
            text="ADMINISTRATIVE ACTIVITY",
            font=("Segoe UI", 12, "bold"),
            text_color="#102a43",
        ).pack(pady=15)

        for log in self.data.get("audit_summary", [])[:5]:
            f = ctk.CTkFrame(audit_fr, fg_color="transparent")
            f.pack(fill="x", padx=15, pady=6)
            ctk.CTkLabel(
                f,
                text=log.get("action", "Unknown Action"),
                font=("Segoe UI", 10),
                text_color="#243b53",
                wraplength=280,
            ).pack(anchor="w")
            ctk.CTkLabel(
                f,
                text=f"{log.get('timestamp', '---')} • {log.get('username', 'System')}",
                font=("Segoe UI", 9),
                text_color="#627d98",
            ).pack(anchor="w")

    def _add_node(self, parent, td, label, is_active=False):
        node = ctk.CTkFrame(
            parent, fg_color="#102a43" if is_active else "#f0f4f8", corner_radius=10
        )
        node.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(
            node,
            text=td,
            font=("Segoe UI", 12, "bold"),
            text_color="#ffffff" if is_active else "#102a43",
        ).pack(pady=(8, 2))
        ctk.CTkLabel(
            node,
            text=label,
            font=("Segoe UI", 10),
            text_color="#bcccdc" if is_active else "#486581",
        ).pack(pady=(0, 8))
