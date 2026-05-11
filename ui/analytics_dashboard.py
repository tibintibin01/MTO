import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import threading
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import api_clients.payment_service as payment_svc
from theme_manager import ModernTheme

class AnalyticsDashboardPage:
    def __init__(self, parent, user=None):
        self.parent = parent
        self.user = user
        
        self.container = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        # Header
        header_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        header_fr.pack(fill="x", pady=(0, 20))
        
        ctk.CTkLabel(
            header_fr, text="MUNICIPAL ANALYTICS HUB", font=("Segoe UI", 24, "bold")
        ).pack(side="left")
        
        ctk.CTkButton(
            header_fr, text="🔄 REFRESH DATA", command=self.load_data, width=150, fg_color="#3498db"
        ).pack(side="right")

        # --- KPI CARDS ---
        self.kpi_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        self.kpi_fr.pack(fill="x", pady=(0, 20))
        self.kpi_fr.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.kpi_total = self._create_kpi_card("TOTAL REVENUE", "P 0.00", "#1abc9c", 0)
        self.kpi_month = self._create_kpi_card("THIS MONTH", "P 0.00", "#3498db", 1)
        self.kpi_today = self._create_kpi_card("COLLECTED TODAY", "P 0.00", "#e67e22", 2)
        self.kpi_count = self._create_kpi_card("TOTAL PAYMENTS", "0", "#9b59b6", 3)

        # --- CHARTS AREA ---
        charts_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        charts_fr.pack(fill="both", expand=True)
        charts_fr.grid_columnconfigure((0, 1), weight=1)

        # 1. Collection Trend (Line Chart)
        self.trend_card = ctk.CTkFrame(charts_fr, fg_color="white", corner_radius=12)
        self.trend_card.grid(row=0, column=0, padx=(0, 10), sticky="nsew")
        ctk.CTkLabel(self.trend_card, text="MONTHLY COLLECTION TREND", font=("Segoe UI", 12, "bold")).pack(pady=10)
        
        # 2. Barangay Breakdown (Bar Chart)
        self.brgy_card = ctk.CTkFrame(charts_fr, fg_color="white", corner_radius=12)
        self.brgy_card.grid(row=0, column=1, padx=(10, 0), sticky="nsew")
        ctk.CTkLabel(self.brgy_card, text="REVENUE BY BARANGAY", font=("Segoe UI", 12, "bold")).pack(pady=10)

    def _create_kpi_card(self, title, value, color, col):
        card = ctk.CTkFrame(self.kpi_fr, fg_color="white", corner_radius=12)
        card.grid(row=0, column=col, padx=5, sticky="nsew")
        
        ctk.CTkLabel(card, text=title, font=("Segoe UI", 10, "bold"), text_color="gray").pack(pady=(15, 0))
        val_lbl = ctk.CTkLabel(card, text=value, font=("Segoe UI", 22, "bold"), text_color=color)
        val_lbl.pack(pady=(0, 15))
        return val_lbl

    def load_data(self):
        def worker():
            try:
                kpis = payment_svc.get_analytics_kpis()
                trends = payment_svc.get_monthly_collection_trend(months=12)
                brgy_data = payment_svc.get_barangay_breakdown()
                
                self.container.after(0, lambda: self._update_ui(kpis, trends, brgy_data))
            except Exception as e:
                self.container.after(0, lambda: messagebox.showerror("Analytics Error", f"Failed to fetch data: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _update_ui(self, kpis, trends, brgy_data):
        # Update KPIs
        self.kpi_total.configure(text=f"P {kpis['total_revenue']:,.2f}")
        self.kpi_month.configure(text=f"P {kpis['month']:,.2f}")
        self.kpi_today.configure(text=f"P {kpis['today']:,.2f}")
        self.kpi_count.configure(text=f"{kpis['payment_count']:,}")

        # Update Trend Chart
        self._plot_trend(trends)
        
        # Update Barangay Chart
        self._plot_barangay(brgy_data)

    def _plot_trend(self, trends):
        for widget in self.trend_card.winfo_children():
            if isinstance(widget, tk.Canvas): widget.destroy()
            
        fig = Figure(figsize=(5, 4), dpi=100)
        ax = fig.add_subplot(111)
        
        months = [t["month"] for t in trends]
        totals = [t["total"] for t in trends]
        
        ax.plot(months, totals, marker='o', linestyle='-', color='#3498db', linewidth=2)
        ax.fill_between(months, totals, alpha=0.2, color='#3498db')
        
        ax.set_title("")
        ax.set_ylabel("Revenue (PHP)")
        fig.autofmt_xdate()
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=self.trend_card)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

    def _plot_barangay(self, brgy_data):
        for widget in self.brgy_card.winfo_children():
            if isinstance(widget, tk.Canvas): widget.destroy()
            
        fig = Figure(figsize=(5, 4), dpi=100)
        ax = fig.add_subplot(111)
        
        # Top 10 barangays
        top_data = brgy_data[:10]
        names = [d["barangay"][:10] for d in top_data]
        values = [d["total"] for d in top_data]
        
        bars = ax.bar(names, values, color='#1abc9c')
        
        ax.set_title("")
        ax.set_ylabel("Total Collection (PHP)")
        fig.autofmt_xdate()
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=self.brgy_card)
        canvas.draw()
        canvas.get_tkwidget().pack(fill="both", expand=True, padx=10, pady=10)
