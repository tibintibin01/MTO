import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import threading
from theme_manager import ModernTheme
import services.billing_service as billing
import services.property_service as prop
import services.system_service as system
from utils import format_curr

class ReportsPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.setup_ui()

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        ctk.CTkLabel(self.container, text="COLLECTION AND RECEIVABLES ANALYTICS", font=ModernTheme.H2).pack(anchor="w", pady=(0, 20))

        self.tabview = ctk.CTkTabview(self.container)
        self.tabview.pack(fill="both", expand=True)

        self.collection_tab = self.tabview.add("Collection Report")
        self.receivables_tab = self.tabview.add("RPT Receivables Summary")
        self.barangay_tab = self.tabview.add("Receivables by Barangay")

        self.setup_collection_tab()
        self.setup_receivables_tab()
        self.setup_barangay_tab()

    def setup_collection_tab(self):
        filter_fr = ctk.CTkFrame(self.collection_tab)
        filter_fr.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(filter_fr, text="Filter by Month/Year", font=("Segoe UI", 12, "bold")).pack(side="left", padx=10)
        
        self.month_cb = ctk.CTkComboBox(filter_fr, values=["All"] + [f"{m:02d}" for m in range(1, 13)])
        self.month_cb.set(datetime.now().strftime("%m"))
        self.month_cb.pack(side="left", padx=5)
        
        current_year = datetime.now().year
        self.year_cb = ctk.CTkComboBox(filter_fr, values=["All"] + [str(y) for y in range(current_year-10, current_year+3)])
        self.year_cb.set(str(current_year))
        self.year_cb.pack(side="left", padx=5)
        
        ctk.CTkButton(filter_fr, text="GENERATE", command=self.generate_collection_report).pack(side="left", padx=10)

        self.coll_table_fr = ctk.CTkFrame(self.collection_tab)
        self.coll_table_fr.pack(fill="both", expand=True, padx=10, pady=10)
        
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", rowheight=35, font=("Segoe UI", 10), background="#2b2b2b", fieldbackground="#2b2b2b", foreground="white")
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#333333", foreground="white")

        cols = ("Date", "OR", "TD", "Owner", "Kind", "Year", "Amount", "Posted By")
        self.coll_tree = ttk.Treeview(self.coll_table_fr, columns=cols, show="headings")
        for col in cols:
            self.coll_tree.heading(col, text=col)
            self.coll_tree.column(col, width=100, anchor="center")
        self.coll_tree.pack(fill="both", expand=True)
        
        # Zebra Tags
        self.coll_tree.tag_configure('oddrow', background="#2b2b2b", foreground="white")
        self.coll_tree.tag_configure('evenrow', background="#333333", foreground="white")

    def setup_receivables_tab(self):
        receiv_fr = ctk.CTkFrame(self.receivables_tab, fg_color="transparent")
        receiv_fr.pack(fill="both", expand=True, padx=10, pady=10)
        
        filter_fr = ctk.CTkFrame(receiv_fr)
        filter_fr.pack(fill="x", pady=10)
        
        curr_y = datetime.now().year
        self.receiv_year_cb = ctk.CTkComboBox(filter_fr, values=[str(y) for y in range(curr_y-10, curr_y+3)])
        self.receiv_year_cb.set(str(curr_y))
        self.receiv_year_cb.pack(side="left", padx=10)
        
        ctk.CTkButton(filter_fr, text="LOAD SUMMARY", command=self.generate_receivables_report).pack(side="left")

        self.receiv_content = ctk.CTkFrame(receiv_fr)
        self.receiv_content.pack(fill="both", expand=True)
        self.receiv_label = ctk.CTkLabel(self.receiv_content, text="Click Load Summary to view report.")
        self.receiv_label.pack(pady=50)

    def setup_barangay_tab(self):
        brgy_fr = ctk.CTkFrame(self.barangay_tab, fg_color="transparent")
        brgy_fr.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Header Area
        top_fr = ctk.CTkFrame(brgy_fr, fg_color="transparent")
        top_fr.pack(fill="x", pady=(0, 15))
        
        ctk.CTkLabel(top_fr, text="JURISDICTION BREAKDOWN", font=("Segoe UI", 16, "bold"), text_color="#3498db").pack(side="left")
        ctk.CTkButton(top_fr, text="🔄 REFRESH BREAKDOWN", command=self.generate_barangay_receivables, 
                       width=200, height=35, font=ModernTheme.BUTTON).pack(side="right")
        
        # Table Container
        t_container = ctk.CTkFrame(brgy_fr)
        t_container.pack(fill="both", expand=True)
        
        cols = ("Barangay", "Total Assessed", "Total Due", "Total Penalty", "Total Discount", "Total Collected", "Total Receivable")
        self.brgy_tree = ttk.Treeview(t_container, columns=cols, show="headings")
        for col in cols:
            self.brgy_tree.heading(col, text=col.upper())
            self.brgy_tree.column(col, width=120, anchor="center")
        
        self.brgy_tree.column("Barangay", width=180, anchor="w")
        self.brgy_tree.column("Total Receivable", width=150)
        
        # Scrollbar
        scrolly = ttk.Scrollbar(t_container, orient="vertical", command=self.brgy_tree.yview)
        self.brgy_tree.configure(yscrollcommand=scrolly.set)
        
        self.brgy_tree.pack(side="left", fill="both", expand=True)
        scrolly.pack(side="right", fill="y")
        
        # Zebra Tags
        self.brgy_tree.tag_configure('oddrow', background="#2b2b2b", foreground="white")
        self.brgy_tree.tag_configure('evenrow', background="#333333", foreground="white")

        # --- SUMMARY FOOTER ---
        self.brgy_summary = ctk.CTkFrame(brgy_fr, height=50, fg_color="#2c3e50", corner_radius=8)
        self.brgy_summary.pack(fill="x", pady=(15, 0))
        
        self.brgy_total_lbl = ctk.CTkLabel(self.brgy_summary, text="Total Jurisdiction Receivable: P 0.00", 
                                          font=("Segoe UI", 13, "bold"), text_color="#ecf0f1")
        self.brgy_total_lbl.pack(side="right", padx=30, pady=10)

    def generate_collection_report(self):
        month = self.month_cb.get()
        year = self.year_cb.get()
        
        def worker():
            try:
                data = billing.get_report_details(month, year)
                self.container.after(0, lambda: self._update_coll_table(data))
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Error", str(err)))
        
        threading.Thread(target=worker, daemon=True).start()

    def _update_coll_table(self, data):
        for item in self.coll_tree.get_children():
            self.coll_tree.delete(item)
            
        if not data:
            messagebox.showinfo("Report", "No collection records found for the selected period.")
            return

        for i, row in enumerate(data):
            # Format the amount (index 6)
            formatted_row = list(row)
            if len(formatted_row) > 6:
                formatted_row[6] = format_curr(formatted_row[6])
            
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            self.coll_tree.insert("", "end", values=formatted_row, tags=(tag,))

    def generate_receivables_report(self):
        year = self.receiv_year_cb.get()
        def worker():
            try:
                data = billing.get_rpt_receivables_summary(year)
                self.container.after(0, lambda: self._update_receiv_summary(data))
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Error", str(err)))
        threading.Thread(target=worker, daemon=True).start()

    def _update_receiv_summary(self, data):
        for child in self.receiv_content.winfo_children():
            child.destroy()
        
        if not data: 
            messagebox.showinfo("Report", "No assessment data available for the selected year.")
            return

        # --- DATA PREP ---
        beg = float(data.get("beginning_receivable", 0))
        curr = float(data.get("current_year_assessment", 0))
        coll = float(data.get("collections", 0))
        adj = float(data.get("adjustments", 0))
        end = float(data.get("ending_receivable", 0))
        year = data.get("report_year", "N/A")
        
        # Calculate Efficiency (Collections / (Beginning + Current))
        total_target = beg + curr
        efficiency = (coll / total_target * 100) if total_target > 0 else 0
        
        # --- HEADER ---
        header_fr = ctk.CTkFrame(self.receiv_content, fg_color="transparent")
        header_fr.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(header_fr, text=f"FISCAL YEAR {year} PERFORMANCE", font=("Segoe UI", 18, "bold"), text_color="#3498db").pack(side="left")
        ctk.CTkLabel(header_fr, text=f"Efficiency: {efficiency:.1f}%", font=("Segoe UI", 16, "bold"), text_color="#2ecc71" if efficiency > 50 else "#e67e22").pack(side="right")

        # --- CARDS GRID ---
        grid_fr = ctk.CTkFrame(self.receiv_content, fg_color="transparent")
        grid_fr.pack(fill="x")
        grid_fr.grid_columnconfigure((0, 1, 2), weight=1)

        # Helper to make a metric card
        def make_card(parent, row, col, title, value, color, icon=""):
            card = ctk.CTkFrame(parent, height=140, corner_radius=12)
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
            
            ctk.CTkLabel(card, text=title.upper(), font=("Segoe UI", 10, "bold"), text_color="gray").pack(pady=(20, 5))
            ctk.CTkLabel(card, text=f"P {value:,.2f}", font=("Segoe UI", 20, "bold"), text_color=color).pack(pady=(0, 20))
            
            # Subtle indicator bar at the bottom of the card
            indicator = ctk.CTkFrame(card, height=4, fg_color=color, corner_radius=0)
            indicator.pack(fill="x", side="bottom")

        make_card(grid_fr, 0, 0, "Beginning Balance", beg, "#7f8c8d")
        make_card(grid_fr, 0, 1, "Current Assessment", curr, "#3498db")
        make_card(grid_fr, 0, 2, "Adjustments", adj, "#9b59b6")
        
        # Lower Row
        grid_fr_2 = ctk.CTkFrame(self.receiv_content, fg_color="transparent")
        grid_fr_2.pack(fill="x")
        grid_fr_2.grid_columnconfigure((0, 1), weight=1)

        make_card(grid_fr_2, 0, 0, "Total Collections", coll, "#2ecc71")
        make_card(grid_fr_2, 0, 1, "Ending Receivable", end, "#e74c3c")

        # --- VISUAL EFFICIENCY METER ---
        meter_fr = ctk.CTkFrame(self.receiv_content, height=80, corner_radius=15)
        meter_fr.pack(fill="x", pady=20, padx=10)
        
        ctk.CTkLabel(meter_fr, text="COLLECTION TARGET PROGRESS", font=("Segoe UI", 11, "bold"), text_color="gray").pack(pady=(15, 5), padx=30, anchor="w")
        
        prog_bar = ctk.CTkProgressBar(meter_fr, height=12, corner_radius=6)
        prog_bar.pack(fill="x", padx=30, pady=(5, 15))
        prog_bar.set(min(1.0, efficiency / 100))
        prog_bar.configure(progress_color="#2ecc71" if efficiency > 70 else "#f1c40f")

    def generate_barangay_receivables(self):
        def worker():
            try:
                data = prop.get_receivables_by_barangay()
                self.container.after(0, lambda: self._update_brgy_table(data))
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Error", str(err)))
        threading.Thread(target=worker, daemon=True).start()

    def _update_brgy_table(self, data):
        for item in self.brgy_tree.get_children():
            self.brgy_tree.delete(item)
            
        if not data:
            messagebox.showinfo("Report", "No barangay-level receivables data found.")
            self.brgy_total_lbl.configure(text="Total Jurisdiction Receivable: P 0.00")
            return

        grand_total = 0.0
        for i, row in enumerate(data):
            # row: 0:brgy, 1:assessed, 2:due, 3:pen, 4:disc, 5:coll, 6:receiv
            f_row = list(row)
            try:
                receiv_val = float(row[6] or 0)
                grand_total += receiv_val
            except: pass

            if len(f_row) >= 7:
                # Format all currency columns (1 through 6)
                for idx in range(1, 7):
                    f_row[idx] = format_curr(f_row[idx])
            
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            self.brgy_tree.insert("", "end", values=f_row, tags=(tag,))
        
        self.brgy_total_lbl.configure(text=f"Total Jurisdiction Receivable: P {grand_total:,.2f}")
