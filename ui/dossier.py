from pathlib import Path
import sys

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageOps


NAVY = "#0b2a4a"
INK = "#102a43"
MUTED = "#6b7f95"
SURFACE = "#ffffff"
CANVAS = "#f4f7fb"
BORDER = "#d8e2ec"
ORANGE = "#e68600"
TEAL = "#0fa987"
BLUE = "#2785d8"
PURPLE = "#7857d8"


def _load_dossier_seal(size):
    root_dir = (
        Path(sys._MEIPASS).resolve()
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1]
    )
    source = Image.open(
        root_dir / "assets" / "official" / "treasurer_seal.png"
    ).convert("RGBA")
    left = round(source.width * 0.036)
    side = min(round(source.width * 0.928), round(source.height * 0.965))
    source = source.crop((left, 0, left + side, side))
    fitted = ImageOps.fit(
        source,
        (size, size),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    fitted.putalpha(mask)
    return fitted


class PropertyDossierModal(ctk.CTkToplevel):
    _header_seal_image = None

    def __init__(self, parent, data):
        super().__init__(parent)
        master = data["master"]
        self.title(f"Property Dossier | {master.get('td_number')}")

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        ww, wh = min(1200, sw - 100), min(850, sh - 100)
        self.geometry(f"{ww}x{wh}+{(sw - ww) // 2}+{(sh - wh) // 2}")

        self.data = data
        self.setup_ui()

        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)

    def setup_ui(self):
        self.configure(fg_color=CANVAS)
        master = self.data["master"]

        header = ctk.CTkFrame(self, fg_color=NAVY, height=132, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)

        identity = ctk.CTkFrame(
            header,
            width=68,
            height=68,
            corner_radius=34,
            fg_color="transparent",
        )
        identity.pack(side="left", padx=(28, 18), pady=26)
        identity.pack_propagate(False)
        try:
            if PropertyDossierModal._header_seal_image is None:
                seal = _load_dossier_seal(96)
                PropertyDossierModal._header_seal_image = ctk.CTkImage(
                    light_image=seal,
                    dark_image=seal,
                    size=(64, 64),
                )
            self.header_seal_image = PropertyDossierModal._header_seal_image
            ctk.CTkLabel(
                identity,
                image=self.header_seal_image,
                text="",
            ).place(relx=0.5, rely=0.5, anchor="center")
        except Exception:
            ctk.CTkLabel(
                identity,
                text="RPT",
                font=("Segoe UI", 16, "bold"),
                text_color=ORANGE,
            ).place(relx=0.5, rely=0.5, anchor="center")

        info = ctk.CTkFrame(header, fg_color="transparent")
        info.pack(side="left", fill="y", pady=24)
        ctk.CTkLabel(
            info,
            text="PROPERTY DOSSIER",
            font=("Segoe UI", 27, "bold"),
            text_color="#ffffff",
        ).pack(anchor="w")

        identity_line = ctk.CTkFrame(info, fg_color="transparent")
        identity_line.pack(anchor="w", pady=(7, 0))
        ctk.CTkLabel(
            identity_line,
            text=f"TD {master.get('td_number')}",
            font=("Segoe UI", 13, "bold"),
            text_color=ORANGE,
        ).pack(side="left")
        ctk.CTkLabel(
            identity_line,
            text="  |  ",
            font=("Segoe UI", 13),
            text_color="#7fa0bd",
        ).pack(side="left")
        ctk.CTkLabel(
            identity_line,
            text=str(master.get("owner_name") or "Owner not recorded"),
            font=("Segoe UI", 13),
            text_color="#c7d6e5",
            anchor="w",
            justify="left",
            wraplength=470,
        ).pack(side="left")

        payment_count = len(self.data.get("payments", []))
        assessment_count = len(self.data.get("assessment_history", []))
        counters = ctk.CTkFrame(
            header,
            width=330,
            height=72,
            corner_radius=10,
            fg_color="#163b5e",
            border_width=1,
            border_color="#315574",
        )
        counters.pack(side="right", padx=30, pady=30)
        counters.pack_propagate(False)
        counters.grid_columnconfigure((0, 2), weight=1)
        counters.grid_rowconfigure(0, weight=1)
        self._activity_counter(
            counters,
            0,
            payment_count,
            "PAYMENT" if payment_count == 1 else "PAYMENTS",
            ORANGE,
        )
        ctk.CTkFrame(counters, width=1, fg_color="#55748f").grid(
            row=0, column=1, sticky="ns", pady=14
        )
        self._activity_counter(
            counters,
            2,
            assessment_count,
            "ASSESSMENT CHANGE" if assessment_count == 1 else "ASSESSMENT CHANGES",
            "#35c5e6",
        )

        main = ctk.CTkFrame(self, fg_color=CANVAS)
        main.pack(fill="both", expand=True, padx=20, pady=20)

        summary = ctk.CTkFrame(
            main,
            fg_color=SURFACE,
            width=300,
            corner_radius=10,
            border_width=1,
            border_color=BORDER,
        )
        summary.pack(side="left", fill="y", padx=(0, 24))
        summary.pack_propagate(False)
        self._setup_summary_panel(summary)

        timeline = ctk.CTkFrame(main, fg_color="transparent")
        timeline.pack(side="left", fill="both", expand=True)
        self._setup_unified_timeline(timeline)

    def _activity_counter(self, parent, column, value, label, color):
        block = ctk.CTkFrame(parent, fg_color="transparent")
        block.grid(row=0, column=column, sticky="nsew", padx=14, pady=10)
        ctk.CTkLabel(
            block,
            text=str(value),
            font=("Segoe UI", 20, "bold"),
            text_color=color,
        ).pack(anchor="w")
        ctk.CTkLabel(
            block,
            text=label,
            font=("Segoe UI", 9, "bold"),
            text_color="#d7e3ee",
        ).pack(anchor="w")

    def _setup_summary_panel(self, parent):
        heading = ctk.CTkFrame(parent, fg_color="transparent")
        heading.pack(fill="x", padx=20, pady=(22, 2))
        icon = ctk.CTkFrame(
            heading,
            width=38,
            height=38,
            corner_radius=8,
            fg_color="#edf4fb",
            border_width=1,
            border_color="#cbdbea",
        )
        icon.pack(side="left", padx=(0, 12))
        icon.pack_propagate(False)
        ctk.CTkLabel(
            icon,
            text="R",
            font=("Segoe UI", 15, "bold"),
            text_color=NAVY,
        ).place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(
            heading,
            text="CURRENT RECORD",
            font=("Segoe UI", 15, "bold"),
            text_color=INK,
        ).pack(side="left")
        ctk.CTkLabel(
            parent,
            text="Latest property information",
            font=("Segoe UI", 10),
            text_color=MUTED,
        ).pack(anchor="w", padx=70, pady=(0, 14))
        self._summary_divider(parent)

        master = self.data["master"]
        specs = [
            ("B", "BARANGAY", master.get("barangay") or "Not recorded", TEAL),
            ("C", "CLASSIFICATION", master.get("kind_of_property") or "Not recorded", BLUE),
            ("#", "PIN", master.get("pin") or "Not recorded", PURPLE),
            ("P", "ASSESSED VALUE", f"P {float(master.get('assessed_value') or 0):,.2f}", ORANGE),
            ("E", "EFFECTIVITY", master.get("effectivity_date") or "Not recorded", BLUE),
        ]

        for index, (symbol, label, value, color) in enumerate(specs):
            row = ctk.CTkFrame(parent, fg_color="transparent", height=76)
            row.pack(fill="x", padx=20, pady=4)
            row.pack_propagate(False)
            token = ctk.CTkFrame(
                row,
                width=38,
                height=38,
                corner_radius=10,
                fg_color="#f7f9fc",
                border_width=1,
                border_color="#e2e9f0",
            )
            token.pack(side="left", padx=(0, 12))
            token.pack_propagate(False)
            ctk.CTkLabel(
                token,
                text=symbol,
                font=("Segoe UI", 13, "bold"),
                text_color=color,
            ).place(relx=0.5, rely=0.5, anchor="center")
            values = ctk.CTkFrame(row, fg_color="transparent")
            values.pack(side="left", fill="both", expand=True)
            ctk.CTkLabel(
                values,
                text=label,
                font=("Segoe UI", 9, "bold"),
                text_color=MUTED,
            ).pack(anchor="w", pady=(8, 0))
            ctk.CTkLabel(
                values,
                text=str(value),
                font=("Segoe UI", 12, "bold"),
                text_color=INK,
                justify="left",
                anchor="w",
                wraplength=190,
            ).pack(fill="x", anchor="w", pady=(2, 0))
            if index < len(specs) - 1:
                self._summary_divider(parent)

    def _summary_divider(self, parent):
        ctk.CTkFrame(
            parent,
            fg_color="#c8d5e2",
            height=2,
            corner_radius=1,
        ).pack(fill="x", padx=18, pady=3)

    def _setup_unified_timeline(self, parent):
        events = self._build_events()

        timeline_header = ctk.CTkFrame(parent, fg_color="transparent")
        timeline_header.pack(fill="x", pady=(7, 14))
        title = ctk.CTkLabel(
            timeline_header,
            text="ACTIVITY HISTORY",
            font=("Segoe UI", 16, "bold"),
            text_color=INK,
        )
        title.pack(side="left")
        ctk.CTkLabel(
            timeline_header,
            text=f"{len(events)} meaningful event{'s' if len(events) != 1 else ''}",
            font=("Segoe UI", 10),
            text_color=MUTED,
        ).pack(side="right")
        ctk.CTkFrame(
            parent,
            width=58,
            height=3,
            corner_radius=2,
            fg_color=ORANGE,
        ).pack(anchor="w", pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(
            parent,
            fg_color="transparent",
            scrollbar_button_color="#8093a5",
            scrollbar_button_hover_color="#60778b",
        )
        scroll.pack(fill="both", expand=True)

        if not events:
            ctk.CTkLabel(
                scroll,
                text="No payment, assessment, or transfer history is recorded.",
                font=("Segoe UI", 13),
                text_color=MUTED,
            ).pack(pady=100)
            return

        for event in events:
            self._render_event(scroll, event)

    def _build_events(self):
        """Return business events only; routine edits belong in Audit Logs."""
        events = []

        for payment in self.data.get("payments", []):
            remarks = str(payment[8] or "").strip() if len(payment) > 8 else ""
            detail = f"Tax year: {payment[2]}"
            if remarks:
                detail += f" | Note: {remarks}"
            events.append(
                {
                    "date": str(payment[0])[:10],
                    "type": "PAYMENT",
                    "title": f"Official Receipt: {payment[1]}",
                    "subtitle": f"Amount paid: P {float(payment[7] or 0):,.2f}",
                    "detail": detail,
                    "color": "#16a085",
                }
            )

        for ancestor in self.data.get("ancestry", []):
            events.append(
                {
                    "date": "LEGACY",
                    "type": "TRANSFER",
                    "title": f"Transferred from {ancestor.get('owner_name')}",
                    "subtitle": f"Previous TD: {ancestor.get('td_number')}",
                    "detail": "TD ownership lineage",
                    "color": "#2f80c9",
                }
            )

        seen_assessments = set()
        for history in self.data.get("assessment_history", []):
            assessed_value = float(history.get("assessed_value") or 0)
            assessment_key = (
                str(history.get("td_number") or "").strip().upper(),
                round(assessed_value, 2),
                str(history.get("tax_year") or "").strip(),
                str(history.get("kind") or "").strip().upper(),
            )
            if assessment_key in seen_assessments:
                continue
            seen_assessments.add(assessment_key)
            events.append(
                {
                    "date": str(history.get("date", ""))[:10],
                    "type": "VALUATION",
                    "title": f"Previous Assessment: {history.get('td_number')}",
                    "subtitle": f"Historical value: P {assessed_value:,.2f}",
                    "detail": (
                        f"Classification: {history.get('kind') or 'Not recorded'} | "
                        f"Effective from: {history.get('tax_year') or 'Not recorded'} | "
                        f"{history.get('change_reason') or 'Assessment update'}"
                    ),
                    "color": "#d97706",
                }
            )

        events.sort(
            key=lambda event: event["date"] if event["date"] != "LEGACY" else "0000-00-00",
            reverse=True,
        )
        return events

    def _render_event(self, parent, event):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=8)

        marker = ctk.CTkFrame(row, fg_color="transparent", width=126)
        marker.pack(side="left", fill="y")
        marker.pack_propagate(False)
        ctk.CTkLabel(
            marker,
            text=event["date"],
            font=("Segoe UI", 11, "bold"),
            text_color=INK,
        ).pack(anchor="e", padx=(0, 22), pady=(18, 0))
        ctk.CTkFrame(
            marker,
            width=2,
            fg_color="#d7e1eb",
        ).place(relx=1.0, x=-8, y=48, relheight=1.0, anchor="ne")
        ctk.CTkFrame(
            marker,
            width=16,
            height=16,
            corner_radius=8,
            fg_color=event["color"],
            border_width=3,
            border_color=CANVAS,
        ).place(relx=1.0, x=0, y=49, anchor="ne")

        card = ctk.CTkFrame(
            row,
            fg_color=SURFACE,
            corner_radius=10,
            border_width=1,
            border_color=event["color"],
        )
        card.pack(side="left", fill="x", expand=True, padx=(14, 2))

        card_header = ctk.CTkFrame(card, fg_color="transparent")
        card_header.pack(fill="x", padx=22, pady=(18, 8))
        ctk.CTkLabel(
            card_header,
            text=event["title"],
            font=("Segoe UI", 14, "bold"),
            text_color=INK,
            anchor="w",
            wraplength=520,
            justify="left",
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            card_header,
            text=event["type"],
            font=("Segoe UI", 9, "bold"),
            text_color="#ffffff",
            fg_color=event["color"],
            corner_radius=6,
            padx=12,
            pady=5,
        ).pack(side="right", padx=(10, 0))

        ctk.CTkLabel(
            card,
            text=event["subtitle"],
            font=("Segoe UI", 12),
            text_color="#4c657d",
        ).pack(anchor="w", padx=22)
        ctk.CTkLabel(
            card,
            text=event["detail"],
            font=("Segoe UI", 10),
            text_color="#7890a6",
            anchor="w",
            justify="left",
            wraplength=720,
        ).pack(fill="x", anchor="w", padx=22, pady=(6, 18))
