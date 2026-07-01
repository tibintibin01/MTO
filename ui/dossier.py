import customtkinter as ctk


class PropertyDossierModal(ctk.CTkToplevel):
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
        self.configure(fg_color="#ffffff")
        master = self.data["master"]

        header = ctk.CTkFrame(self, fg_color="#102a43", height=106, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)

        info = ctk.CTkFrame(header, fg_color="transparent")
        info.pack(side="left", padx=30, pady=20)
        ctk.CTkLabel(
            info,
            text="PROPERTY DOSSIER",
            font=("Segoe UI", 24, "bold"),
            text_color="#ffffff",
        ).pack(anchor="w")
        ctk.CTkLabel(
            info,
            text=f"TD {master.get('td_number')}  |  {master.get('owner_name')}",
            font=("Segoe UI", 13),
            text_color="#bcccdc",
        ).pack(anchor="w")

        payment_count = len(self.data.get("payments", []))
        assessment_count = len(self.data.get("assessment_history", []))
        activity_text = (
            f"{payment_count} PAYMENT{'S' if payment_count != 1 else ''}  |  "
            f"{assessment_count} ASSESSMENT CHANGE"
            f"{'S' if assessment_count != 1 else ''}"
        )
        ctk.CTkLabel(
            header,
            text=activity_text,
            font=("Segoe UI", 10, "bold"),
            text_color="#d9e2ec",
            fg_color="#243b53",
            corner_radius=6,
            padx=14,
            pady=7,
        ).pack(side="right", padx=30)

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=24, pady=18)

        summary = ctk.CTkFrame(
            main,
            fg_color="#f0f4f8",
            width=250,
            corner_radius=8,
            border_width=1,
            border_color="#d9e2ec",
        )
        summary.pack(side="left", fill="y", padx=(0, 18))
        summary.pack_propagate(False)
        self._setup_summary_panel(summary)

        timeline = ctk.CTkFrame(main, fg_color="transparent")
        timeline.pack(side="left", fill="both", expand=True)
        self._setup_unified_timeline(timeline)

    def _setup_summary_panel(self, parent):
        ctk.CTkLabel(
            parent,
            text="CURRENT RECORD",
            font=("Segoe UI", 14, "bold"),
            text_color="#102a43",
        ).pack(anchor="w", padx=18, pady=(22, 4))
        ctk.CTkLabel(
            parent,
            text="Latest property information",
            font=("Segoe UI", 10),
            text_color="#627d98",
        ).pack(anchor="w", padx=18, pady=(0, 14))

        master = self.data["master"]
        specs = [
            ("BARANGAY", master.get("barangay") or "Not recorded"),
            ("CLASSIFICATION", master.get("kind_of_property") or "Not recorded"),
            ("PIN", master.get("pin") or "Not recorded"),
            ("ASSESSED VALUE", f"P {float(master.get('assessed_value') or 0):,.2f}"),
            ("EFFECTIVITY", master.get("effectivity_date") or "Not recorded"),
        ]

        for index, (label, value) in enumerate(specs):
            if index:
                ctk.CTkFrame(parent, fg_color="#d9e2ec", height=1).pack(
                    fill="x", padx=18, pady=10
                )
            ctk.CTkLabel(
                parent,
                text=label,
                font=("Segoe UI", 9, "bold"),
                text_color="#627d98",
            ).pack(anchor="w", padx=18)
            ctk.CTkLabel(
                parent,
                text=str(value),
                font=("Segoe UI", 12, "bold"),
                text_color="#243b53",
                justify="left",
                anchor="w",
                wraplength=208,
            ).pack(fill="x", anchor="w", padx=18, pady=(3, 0))

    def _setup_unified_timeline(self, parent):
        events = self._build_events()

        timeline_header = ctk.CTkFrame(parent, fg_color="transparent")
        timeline_header.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            timeline_header,
            text="ACTIVITY HISTORY",
            font=("Segoe UI", 14, "bold"),
            text_color="#102a43",
        ).pack(side="left")
        ctk.CTkLabel(
            timeline_header,
            text=f"{len(events)} meaningful event{'s' if len(events) != 1 else ''}",
            font=("Segoe UI", 10),
            text_color="#627d98",
        ).pack(side="right")

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        if not events:
            ctk.CTkLabel(
                scroll,
                text="No payment, assessment, or transfer history is recorded.",
                font=("Segoe UI", 13),
                text_color="#627d98",
            ).pack(pady=100)
            return

        for event in events:
            self._render_event(scroll, event)

    def _build_events(self):
        """Return business events only; routine edits belong in Audit Logs."""
        events = []

        for payment in self.data.get("payments", []):
            events.append(
                {
                    "date": str(payment[0])[:10],
                    "type": "PAYMENT",
                    "title": f"Official Receipt: {payment[1]}",
                    "subtitle": f"Amount paid: P {float(payment[7] or 0):,.2f}",
                    "detail": f"Tax year: {payment[2]}",
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
        row.pack(fill="x", pady=4)

        marker = ctk.CTkFrame(row, fg_color="transparent", width=98)
        marker.pack(side="left", fill="y")
        marker.pack_propagate(False)
        ctk.CTkLabel(
            marker,
            text=event["date"],
            font=("Segoe UI", 10, "bold"),
            text_color="#486581",
        ).pack(anchor="e", padx=(0, 12), pady=(14, 0))
        ctk.CTkFrame(
            marker,
            width=12,
            height=12,
            corner_radius=6,
            fg_color=event["color"],
        ).place(relx=1.0, x=-3, y=38, anchor="ne")

        card = ctk.CTkFrame(
            row,
            fg_color="#f8fafc",
            corner_radius=8,
            border_width=1,
            border_color="#d9e2ec",
        )
        card.pack(side="left", fill="x", expand=True, padx=(10, 0))

        card_header = ctk.CTkFrame(card, fg_color="transparent")
        card_header.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            card_header,
            text=event["title"],
            font=("Segoe UI", 13, "bold"),
            text_color="#102a43",
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            card_header,
            text=event["type"],
            font=("Segoe UI", 9, "bold"),
            text_color="#ffffff",
            fg_color=event["color"],
            corner_radius=4,
            padx=8,
            pady=3,
        ).pack(side="right", padx=(10, 0))

        ctk.CTkLabel(
            card,
            text=event["subtitle"],
            font=("Segoe UI", 11),
            text_color="#486581",
        ).pack(anchor="w", padx=16)
        ctk.CTkLabel(
            card,
            text=event["detail"],
            font=("Segoe UI", 10),
            text_color="#829ab1",
            anchor="w",
            justify="left",
            wraplength=680,
        ).pack(fill="x", anchor="w", padx=16, pady=(2, 12))
