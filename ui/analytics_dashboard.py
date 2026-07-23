# -*- coding: utf-8 -*-
from datetime import datetime
import threading
import webbrowser
from urllib.parse import quote

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.ticker as mticker
from tkinter import messagebox

import api_clients.payment_service as payment_svc
from api_clients.offline_manager import manager as offline_manager
from theme_manager import ModernTheme


class AnalyticsDashboardPage:
    """Operational RPT collection dashboard for municipal staff."""

    PAGE_BG = "#0b1220"
    CARD_BG = "#111c31"
    PANEL_BG = "#0d1729"
    BORDER = "#263b5a"
    TEXT = "#f8fafc"
    MUTED = "#9fb2cc"
    BLUE = "#38bdf8"
    GREEN = "#10b981"
    AMBER = "#f59e0b"
    PURPLE = "#a78bfa"
    RED = "#ef4444"

    def __init__(self, parent, user=None):
        self.parent = parent
        self.user = user
        self._loading = False
        self._chart_canvases = {}
        self._filters_ready = False

        self.container = ctk.CTkScrollableFrame(
            parent,
            fg_color=self.PAGE_BG,
            corner_radius=0,
        )
        self.container.pack(fill="both", expand=True)
        self.content = ctk.CTkFrame(self.container, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=22, pady=18)

        self.setup_ui()
        self.load_data()

    def open_external_dashboard(self):
        """Open the detailed authenticated web analytics view."""
        from api_clients.api_helper import BASE_URL, get_token

        token = get_token()
        if not token:
            messagebox.showerror("Session Expired", "Please sign in again to continue.")
            return
        # Keep the bearer token out of HTTP request logs and referrer headers.
        # The page immediately removes this fragment from the address bar.
        webbrowser.open(f"{BASE_URL}/analytics#t={quote(token, safe='')}")

    def setup_ui(self):
        header = ctk.CTkFrame(self.content, fg_color="transparent")
        header.pack(fill="x", pady=(0, 14))

        title_group = ctk.CTkFrame(header, fg_color="transparent")
        title_group.pack(side="left")
        ctk.CTkLabel(
            title_group,
            text="MUNICIPAL ANALYTICS HUB",
            font=(ModernTheme.FONT_FAMILY, 25, "bold"),
            text_color=self.TEXT,
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_group,
            text="Verified collection performance from linked payment allocations.",
            font=(ModernTheme.FONT_FAMILY, 11),
            text_color=self.MUTED,
        ).pack(anchor="w", pady=(2, 0))

        self.last_refresh_label = ctk.CTkLabel(
            header,
            text="Loading current data...",
            font=(ModernTheme.FONT_FAMILY, 10),
            text_color=self.MUTED,
        )
        self.last_refresh_label.pack(side="right", padx=(12, 0), anchor="s")

        self._build_filter_bar()
        self._build_kpis()
        self._build_charts()
        self._build_operational_row()

    def _build_filter_bar(self):
        bar = ctk.CTkFrame(
            self.content,
            fg_color=self.CARD_BG,
            border_width=1,
            border_color=self.BORDER,
            corner_radius=7,
        )
        bar.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            bar,
            text="COLLECTION YEAR",
            font=(ModernTheme.FONT_FAMILY, 9, "bold"),
            text_color=self.MUTED,
        ).pack(side="left", padx=(14, 7), pady=11)
        self.year_combo = ctk.CTkComboBox(
            bar,
            values=[str(datetime.now().year)],
            width=110,
            height=32,
            state="readonly",
            fg_color=self.PANEL_BG,
            border_color=self.BORDER,
            button_color="#1d4f78",
            button_hover_color="#25658f",
            dropdown_fg_color=self.CARD_BG,
        )
        self.year_combo.set(str(datetime.now().year))
        self.year_combo.pack(side="left", pady=10)

        ctk.CTkLabel(
            bar,
            text="BARANGAY",
            font=(ModernTheme.FONT_FAMILY, 9, "bold"),
            text_color=self.MUTED,
        ).pack(side="left", padx=(16, 7), pady=11)
        self.barangay_combo = ctk.CTkComboBox(
            bar,
            values=["ALL"],
            width=205,
            height=32,
            state="readonly",
            fg_color=self.PANEL_BG,
            border_color=self.BORDER,
            button_color="#1d4f78",
            button_hover_color="#25658f",
            dropdown_fg_color=self.CARD_BG,
        )
        self.barangay_combo.set("ALL")
        self.barangay_combo.pack(side="left", pady=10)

        self.refresh_button = ctk.CTkButton(
            bar,
            text="REFRESH DATA",
            command=self.load_data,
            width=125,
            height=32,
            fg_color="#0284c7",
            hover_color="#0369a1",
            font=(ModernTheme.FONT_FAMILY, 10, "bold"),
        )
        self.refresh_button.pack(side="left", padx=(12, 0), pady=10)

        ctk.CTkButton(
            bar,
            text="DETAILED ANALYTICS",
            command=self.open_external_dashboard,
            width=145,
            height=32,
            fg_color="#243853",
            hover_color="#304967",
            border_width=1,
            border_color="#426080",
            font=(ModernTheme.FONT_FAMILY, 10, "bold"),
        ).pack(side="right", padx=12, pady=10)

        self.year_combo.bind("<Return>", lambda _event: self.load_data())
        self.barangay_combo.bind("<Return>", lambda _event: self.load_data())

    def _build_kpis(self):
        self.kpi_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.kpi_frame.pack(fill="x", pady=(0, 12))
        for column in range(4):
            self.kpi_frame.grid_columnconfigure(column, weight=1, uniform="kpi")

        self.kpis = {}
        definitions = [
            ("total", "TOTAL COLLECTED", self.BLUE),
            ("transactions", "PAYMENT TRANSACTIONS", self.PURPLE),
            ("properties", "PROPERTIES PAID", self.GREEN),
            ("average", "AVERAGE RECEIPT", self.AMBER),
        ]
        for column, (key, title, color) in enumerate(definitions):
            self.kpis[key] = self._create_kpi_card(column, title, color)

    def _create_kpi_card(self, column, title, color):
        card = ctk.CTkFrame(
            self.kpi_frame,
            fg_color=self.CARD_BG,
            border_width=1,
            border_color=self.BORDER,
            corner_radius=7,
            height=112,
        )
        card.grid(row=0, column=column, padx=(0 if column == 0 else 6, 0), sticky="nsew")
        card.grid_propagate(False)

        ctk.CTkLabel(
            card,
            text=title,
            font=(ModernTheme.FONT_FAMILY, 9, "bold"),
            text_color=self.MUTED,
        ).pack(anchor="w", padx=14, pady=(14, 2))
        value = ctk.CTkLabel(
            card,
            text="--",
            font=(ModernTheme.FONT_FAMILY, 21, "bold"),
            text_color=color,
        )
        value.pack(anchor="w", padx=14)
        context = ctk.CTkLabel(
            card,
            text="Loading...",
            font=(ModernTheme.FONT_FAMILY, 9),
            text_color=self.MUTED,
        )
        context.pack(anchor="w", padx=14, pady=(3, 0))
        return {"value": value, "context": context}

    def _build_charts(self):
        charts = ctk.CTkFrame(self.content, fg_color="transparent")
        charts.pack(fill="x", pady=(0, 12))
        charts.grid_columnconfigure((0, 1), weight=1, uniform="chart")

        self.trend_plot_frame = self._create_chart_card(
            charts,
            0,
            "MONTHLY COLLECTION TREND",
            "Cash posted during the selected collection year",
        )
        self.barangay_plot_frame = self._create_chart_card(
            charts,
            1,
            "TOP BARANGAYS BY COLLECTION",
            "Linked collections ranked by property location",
        )

    def _create_chart_card(self, parent, column, title, subtitle):
        card = ctk.CTkFrame(
            parent,
            fg_color=self.CARD_BG,
            border_width=1,
            border_color=self.BORDER,
            corner_radius=7,
            height=330,
        )
        card.grid(row=0, column=column, padx=(0 if column == 0 else 6, 0), sticky="nsew")
        card.grid_propagate(False)

        heading = ctk.CTkFrame(card, fg_color="transparent")
        heading.pack(fill="x", padx=14, pady=(12, 0))
        ctk.CTkLabel(
            heading,
            text=title,
            font=(ModernTheme.FONT_FAMILY, 11, "bold"),
            text_color=self.TEXT,
        ).pack(anchor="w")
        ctk.CTkLabel(
            heading,
            text=subtitle,
            font=(ModernTheme.FONT_FAMILY, 9),
            text_color=self.MUTED,
        ).pack(anchor="w", pady=(1, 0))

        plot_frame = ctk.CTkFrame(card, fg_color=self.PANEL_BG, corner_radius=5)
        plot_frame.pack(fill="both", expand=True, padx=12, pady=10)
        return plot_frame

    def _build_operational_row(self):
        row = ctk.CTkFrame(self.content, fg_color="transparent")
        row.pack(fill="x")
        row.grid_columnconfigure(0, weight=3)
        row.grid_columnconfigure(1, weight=1)

        recent_card = ctk.CTkFrame(
            row,
            fg_color=self.CARD_BG,
            border_width=1,
            border_color=self.BORDER,
            corner_radius=7,
            height=250,
        )
        recent_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        recent_card.grid_propagate(False)
        ctk.CTkLabel(
            recent_card,
            text="RECENT RECEIPTS IN SELECTED PERIOD",
            font=(ModernTheme.FONT_FAMILY, 11, "bold"),
            text_color=self.TEXT,
        ).pack(anchor="w", padx=14, pady=(13, 7))
        self.recent_rows = ctk.CTkFrame(recent_card, fg_color="transparent")
        self.recent_rows.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        status_card = ctk.CTkFrame(
            row,
            fg_color=self.CARD_BG,
            border_width=1,
            border_color=self.BORDER,
            corner_radius=7,
            height=250,
        )
        status_card.grid(row=0, column=1, sticky="nsew")
        status_card.grid_propagate(False)
        ctk.CTkLabel(
            status_card,
            text="SYSTEM STATUS",
            font=(ModernTheme.FONT_FAMILY, 11, "bold"),
            text_color=self.TEXT,
        ).pack(anchor="w", padx=14, pady=(13, 10))

        self.sync_status = self._status_line(status_card, "SYNC QUEUE")
        self.date_status = self._status_line(status_card, "DATE QUALITY")
        self.source_status = self._status_line(status_card, "DATA SOURCE")

    def _status_line(self, parent, title):
        frame = ctk.CTkFrame(parent, fg_color=self.PANEL_BG, corner_radius=5)
        frame.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(
            frame,
            text=title,
            width=88,
            anchor="w",
            font=(ModernTheme.FONT_FAMILY, 8, "bold"),
            text_color=self.MUTED,
        ).pack(side="left", padx=(10, 3), pady=10)
        value = ctk.CTkLabel(
            frame,
            text="Checking...",
            anchor="w",
            font=(ModernTheme.FONT_FAMILY, 9, "bold"),
            text_color=self.TEXT,
        )
        value.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=10)
        return value

    def load_data(self):
        if self._loading:
            return
        self._loading = True
        self.refresh_button.configure(state="disabled", text="LOADING...")
        self.last_refresh_label.configure(text="Refreshing verified data...")

        year = self.year_combo.get().strip()
        barangay = self.barangay_combo.get().strip() or "ALL"

        def worker():
            try:
                data = payment_svc.get_operational_analytics(
                    year=year,
                    barangay=barangay,
                )
                self.container.after(0, lambda: self._update_ui(data))
            except Exception as exc:
                self.container.after(0, lambda err=exc: self._handle_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_error(self, exc):
        self._loading = False
        self.refresh_button.configure(state="normal", text="REFRESH DATA")
        self.last_refresh_label.configure(text="Refresh failed")
        messagebox.showerror("Analytics Error", f"Unable to load analytics data.\n\n{exc}")

    def _update_ui(self, data):
        filters = data.get("filters", {})
        kpis = data.get("kpis", {})
        selected_year = int(filters.get("year", datetime.now().year))

        years = [str(value) for value in filters.get("years", [selected_year])]
        barangays = filters.get("barangays", ["ALL"])
        self.year_combo.configure(values=years)
        self.barangay_combo.configure(values=barangays)
        self.year_combo.set(str(selected_year))
        self.barangay_combo.set(filters.get("barangay", "ALL"))
        self._filters_ready = True

        self.kpis["total"]["value"].configure(
            text=self._money(kpis.get("total_collected", 0))
        )
        self.kpis["total"]["context"].configure(
            text=self._comparison(kpis.get("total_change_pct"), selected_year - 1)
        )
        self.kpis["transactions"]["value"].configure(
            text=f"{int(kpis.get('transactions', 0)):,}"
        )
        self.kpis["transactions"]["context"].configure(
            text=self._comparison(kpis.get("transaction_change_pct"), selected_year - 1)
        )
        self.kpis["properties"]["value"].configure(
            text=f"{int(kpis.get('properties_paid', 0)):,}"
        )
        self.kpis["properties"]["context"].configure(
            text="Unique properties with allocated payments"
        )
        self.kpis["average"]["value"].configure(
            text=self._money(kpis.get("average_receipt", 0))
        )
        self.kpis["average"]["context"].configure(text="Per payment transaction")

        self._plot_trend(data.get("trend", []), filters.get("period_end", ""))
        self._plot_barangay(data.get("barangays", []))
        self._render_recent(data.get("recent", []))
        self._render_status(data.get("quality", {}))

        self._loading = False
        self.refresh_button.configure(state="normal", text="REFRESH DATA")
        self.last_refresh_label.configure(
            text=f"Last refreshed: {datetime.now():%b %d, %Y  %I:%M %p}"
        )

    @staticmethod
    def _money(value):
        return f"P {float(value or 0):,.2f}"

    @staticmethod
    def _comparison(change, prior_year):
        if change is None:
            return f"No {prior_year} baseline available"
        direction = "up" if change >= 0 else "down"
        return f"{abs(float(change)):.1f}% {direction} vs {prior_year}"

    @staticmethod
    def _axis_money(value, _position=None):
        absolute = abs(value)
        if absolute >= 1_000_000:
            return f"P {value / 1_000_000:.1f}M"
        if absolute >= 1_000:
            return f"P {value / 1_000:.0f}K"
        return f"P {value:.0f}"

    def _prepare_axis(self, figure, axis):
        figure.patch.set_facecolor(self.PANEL_BG)
        axis.set_facecolor(self.PANEL_BG)
        axis.tick_params(colors=self.MUTED, labelsize=8, length=0)
        axis.grid(axis="y", color="#2a3c55", alpha=0.55, linewidth=0.6)
        axis.set_axisbelow(True)
        for spine in axis.spines.values():
            spine.set_visible(False)

    def _replace_chart(self, key, frame, figure):
        old_canvas = self._chart_canvases.get(key)
        if old_canvas is not None:
            try:
                old_canvas.get_tk_widget().destroy()
            except Exception:
                pass
        canvas = FigureCanvasTkAgg(figure, master=frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=5, pady=5)
        self._chart_canvases[key] = canvas

    def _plot_trend(self, trends, period_end):
        labels = [row.get("label", "") for row in trends]
        totals = [float(row.get("total", 0) or 0) for row in trends]

        figure = Figure(figsize=(7.2, 3.0), dpi=90)
        axis = figure.add_subplot(111)
        self._prepare_axis(figure, axis)
        x_values = list(range(len(labels)))
        axis.plot(
            x_values,
            totals,
            color=self.BLUE,
            linewidth=2.1,
            marker="o",
            markersize=4,
            markerfacecolor=self.PAGE_BG,
            markeredgewidth=1.4,
        )
        axis.fill_between(x_values, totals, color=self.BLUE, alpha=0.12)
        axis.set_xticks(x_values)
        axis.set_xticklabels(labels)
        axis.yaxis.set_major_formatter(mticker.FuncFormatter(self._axis_money))
        if period_end:
            try:
                current_index = datetime.strptime(period_end, "%Y-%m-%d").month - 1
                axis.axvspan(current_index - 0.38, current_index + 0.38, color=self.AMBER, alpha=0.08)
            except ValueError:
                pass
        if not any(totals):
            axis.set_ylim(0, 1)
        figure.tight_layout(pad=1.0)
        self._replace_chart("trend", self.trend_plot_frame, figure)

    def _plot_barangay(self, rows):
        rows = list(reversed(rows[:10]))
        names = [str(row.get("barangay", "UNSPECIFIED"))[:22] for row in rows]
        totals = [float(row.get("total", 0) or 0) for row in rows]

        figure = Figure(figsize=(7.2, 3.0), dpi=90)
        axis = figure.add_subplot(111)
        self._prepare_axis(figure, axis)
        axis.grid(axis="x", color="#2a3c55", alpha=0.55, linewidth=0.6)
        axis.grid(axis="y", visible=False)
        axis.barh(names, totals, color=self.GREEN, height=0.55, alpha=0.9)
        axis.xaxis.set_major_formatter(mticker.FuncFormatter(self._axis_money))
        axis.tick_params(axis="y", labelsize=7.5)
        if not rows:
            axis.text(
                0.5,
                0.5,
                "No allocated collections in this period",
                transform=axis.transAxes,
                ha="center",
                va="center",
                color=self.MUTED,
                fontsize=9,
            )
        figure.tight_layout(pad=1.0)
        self._replace_chart("barangay", self.barangay_plot_frame, figure)

    def _render_recent(self, rows):
        for child in self.recent_rows.winfo_children():
            child.destroy()

        widths = (90, 100, 120, 1, 105)
        headers = ("DATE", "OR NUMBER", "TD NUMBER", "OWNER", "AMOUNT")
        header = ctk.CTkFrame(self.recent_rows, fg_color="#1b2c45", corner_radius=3)
        header.pack(fill="x", pady=(0, 3))
        for column, title in enumerate(headers):
            header.grid_columnconfigure(column, weight=1 if widths[column] == 1 else 0)
            ctk.CTkLabel(
                header,
                text=title,
                width=widths[column] if widths[column] != 1 else 0,
                anchor="w",
                font=(ModernTheme.FONT_FAMILY, 8, "bold"),
                text_color=self.MUTED,
            ).grid(row=0, column=column, sticky="ew", padx=8, pady=6)

        if not rows:
            ctk.CTkLabel(
                self.recent_rows,
                text="No receipts found for the selected period.",
                font=(ModernTheme.FONT_FAMILY, 10),
                text_color=self.MUTED,
            ).pack(pady=42)
            return

        for index, row in enumerate(rows[:6]):
            frame = ctk.CTkFrame(
                self.recent_rows,
                fg_color=self.PANEL_BG if index % 2 == 0 else "#132139",
                corner_radius=0,
            )
            frame.pack(fill="x")
            values = (
                str(row.get("date", ""))[:10],
                str(row.get("or_number", "-")),
                str(row.get("td_number", "-")),
                str(row.get("owner", "-"))[:34],
                self._money(row.get("amount", 0)),
            )
            for column, value in enumerate(values):
                frame.grid_columnconfigure(column, weight=1 if widths[column] == 1 else 0)
                ctk.CTkLabel(
                    frame,
                    text=value,
                    width=widths[column] if widths[column] != 1 else 0,
                    anchor="e" if column == 4 else "w",
                    font=(ModernTheme.FONT_FAMILY, 9, "bold" if column == 4 else "normal"),
                    text_color=self.TEXT if column != 4 else self.GREEN,
                ).grid(row=0, column=column, sticky="ew", padx=8, pady=6)

    def _render_status(self, quality):
        pending = int(offline_manager.get_queue_count() or 0)
        future_count = int(quality.get("future_dated_payments", 0) or 0)

        self.sync_status.configure(
            text="Queue clear" if pending == 0 else f"{pending} pending item{'s' if pending != 1 else ''}",
            text_color=self.GREEN if pending == 0 else self.AMBER,
        )
        self.date_status.configure(
            text=(
                "No future-dated receipts"
                if future_count == 0
                else f"Review {future_count} future-dated receipt{'s' if future_count != 1 else ''}"
            ),
            text_color=self.GREEN if future_count == 0 else self.RED,
        )
        self.source_status.configure(
            text="Linked payment allocations",
            text_color=self.BLUE,
        )
