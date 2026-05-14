import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from theme_manager import ModernTheme
from utils import format_curr
import api_clients.property_service as prop_service
import api_clients.billing_service as billing_service
from ui_components import LoadingOverlay

class ComputationWizard(ctk.CTkToplevel):
    def __init__(self, parent, initial_search=""):
        super().__init__(parent)
        self.title("COMPUTATION COMMAND CENTER")
        self.geometry("1100x800")
        self.attributes("-topmost", True)
        self.grab_set()
        
        self.selected_properties = [] # List of property data dicts
        self.computation_results = {}
        
        self.setup_ui()
        
        if initial_search:
            self.search_entry.insert(0, initial_search)
            self.perform_search()

    def setup_ui(self):
        # Main Layout: Sidebar (Search/Selection) + Content (Computation)
        self.grid_columnconfigure(0, weight=1) # Search Area
        self.grid_columnconfigure(1, weight=2) # Computation Area
        self.grid_rowconfigure(0, weight=1)

        # --- LEFT SIDEBAR: SEARCH & SELECTION ---
        sidebar = ctk.CTkFrame(self, width=400, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        
        ctk.CTkLabel(sidebar, text="🔍 SEARCH OWNER", font=ModernTheme.H2).pack(pady=(20, 10))
        
        search_fr = ctk.CTkFrame(sidebar, fg_color="transparent")
        search_fr.pack(fill="x", padx=15)
        
        self.search_entry = ctk.CTkEntry(search_fr, placeholder_text="Owner Name or TD No...", height=40)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.search_entry.bind("<Return>", lambda e: self.perform_search())
        
        ctk.CTkButton(search_fr, text="GO", width=60, height=40, command=self.perform_search).pack(side="right")

        # Results Tree
        ctk.CTkLabel(sidebar, text="AVAILABLE PROPERTIES", font=ModernTheme.BODY_BOLD).pack(pady=(20, 5))
        
        tree_fr = ctk.CTkFrame(sidebar, fg_color="white")
        tree_fr.pack(fill="both", expand=True, padx=15, pady=5)
        
        style = ttk.Style()
        style.configure("Wizard.Treeview", rowheight=35, font=ModernTheme.BODY)
        
        cols = ("TD NO.", "OWNER")
        self.search_tree = ttk.Treeview(tree_fr, columns=cols, show="headings", style="Wizard.Treeview")
        self.search_tree.heading("TD NO.", text="TD NUMBER")
        self.search_tree.heading("OWNER", text="OWNER NAME")
        self.search_tree.column("TD NO.", width=120)
        self.search_tree.column("OWNER", width=180)
        
        self.search_tree.pack(side="left", fill="both", expand=True)
        scrolly = ttk.Scrollbar(tree_fr, orient="vertical", command=self.search_tree.yview)
        self.search_tree.configure(yscrollcommand=scrolly.set)
        scrolly.pack(side="right", fill="y")
        
        self.search_tree.bind("<Double-1>", self.add_to_selection)
        
        ctk.CTkButton(sidebar, text="➕ ADD SELECTED", fg_color=ModernTheme.SUCCESS, command=self.add_to_selection).pack(pady=10, padx=15, fill="x")

        # Selection Tree
        ctk.CTkLabel(sidebar, text="SELECTED FOR COMPUTATION", font=ModernTheme.BODY_BOLD).pack(pady=(10, 5))
        sel_fr = ctk.CTkFrame(sidebar, fg_color="white")
        sel_fr.pack(fill="both", expand=True, padx=15, pady=5)
        
        self.sel_tree = ttk.Treeview(sel_fr, columns=cols, show="headings", style="Wizard.Treeview")
        self.sel_tree.heading("TD NO.", text="TD NUMBER")
        self.sel_tree.heading("OWNER", text="OWNER NAME")
        self.sel_tree.pack(side="left", fill="both", expand=True)
        
        ctk.CTkButton(sidebar, text="🗑️ REMOVE SELECTED", fg_color=ModernTheme.DANGER, command=self.remove_from_selection).pack(pady=10, padx=15, fill="x")

        # --- RIGHT CONTENT: COMPUTATION ---
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        
        ctk.CTkLabel(content, text="COMPUTATION SUMMARY", font=ModernTheme.H1, text_color=ModernTheme.PRIMARY).pack(anchor="w")
        self.last_pay_lbl = ctk.CTkLabel(content, text="LAST PAYMENT: N/A", font=ModernTheme.BODY_BOLD, text_color="gray")
        self.last_pay_lbl.pack(anchor="w", pady=(0, 10))

        
        # Adjustment Panel
        adj_fr = ctk.CTkFrame(content, corner_radius=12)
        adj_fr.pack(fill="x", pady=20, padx=5)
        
        ctk.CTkLabel(adj_fr, text="CALCULATION SETTINGS", font=ModernTheme.BODY_BOLD).grid(row=0, column=0, columnspan=4, pady=10, padx=20, sticky="w")
        
        ctk.CTkLabel(adj_fr, text="Penalty Rate (%):").grid(row=1, column=0, padx=20, pady=10, sticky="e")
        self.penalty_entry = ctk.CTkEntry(adj_fr, width=80)
        self.penalty_entry.insert(0, "2")
        self.penalty_entry.grid(row=1, column=1, sticky="w")
        
        ctk.CTkLabel(adj_fr, text="Discount Rate (%):").grid(row=1, column=2, padx=20, pady=10, sticky="e")
        self.discount_entry = ctk.CTkEntry(adj_fr, width=80)
        self.discount_entry.insert(0, "0")
        self.discount_entry.grid(row=1, column=3, sticky="w")

        ctk.CTkLabel(adj_fr, text="Amnesty Until:").grid(row=2, column=0, padx=20, pady=10, sticky="e")
        self.amnesty_entry = ctk.CTkEntry(adj_fr, width=80)
        self.amnesty_entry.insert(0, "2023")
        self.amnesty_entry.grid(row=2, column=1, sticky="w")

        # Added Projection Overrides
        ctk.CTkLabel(adj_fr, text="Last Year Paid:").grid(row=1, column=4, padx=20, pady=10, sticky="e")
        self.last_year_entry = ctk.CTkEntry(adj_fr, width=80, placeholder_text="Auto")
        self.last_year_entry.grid(row=1, column=5, sticky="w")

        ctk.CTkLabel(adj_fr, text="Project Until:").grid(row=2, column=2, padx=20, pady=10, sticky="e")
        self.project_until_entry = ctk.CTkEntry(adj_fr, width=80)
        self.project_until_entry.insert(0, "2026")
        self.project_until_entry.grid(row=2, column=3, sticky="w")

        ctk.CTkButton(adj_fr, text="🔄 RECALCULATE", command=self.recalculate, fg_color=ModernTheme.PRIMARY, height=40).grid(row=2, column=4, columnspan=2, padx=20, pady=10, sticky="e")



        # Computation Table
        comp_fr = ctk.CTkFrame(content, fg_color="white", corner_radius=12)
        comp_fr.pack(fill="both", expand=True, pady=(0, 20))
        
        comp_cols = ("TD", "YEAR RANGE", "ASSESSED VALUE", "BASIC", "SEF", "PENALTY", "DISCOUNT", "TOTAL")
        self.comp_tree = ttk.Treeview(comp_fr, columns=comp_cols, show="headings", style="Wizard.Treeview")
        for c in comp_cols:
            self.comp_tree.heading(c, text=c)
            self.comp_tree.column(c, width=90, anchor="center")
        
        self.comp_tree.column("TD", width=110)
        self.comp_tree.column("YEAR RANGE", width=120)
        self.comp_tree.column("ASSESSED VALUE", width=120)

        self.comp_tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        
        # Grand Total Bar
        self.total_lbl = ctk.CTkLabel(content, text="GRAND TOTAL DUE: ₱ 0.00", font=("Segoe UI", 24, "bold"), text_color=ModernTheme.SUCCESS)
        self.total_lbl.pack(anchor="e", pady=10)
        
        # Action Buttons
        actions = ctk.CTkFrame(content, fg_color="transparent")
        actions.pack(fill="x", side="bottom")
        
        ctk.CTkButton(actions, text="📄 EXCEL-STYLE PDF", command=self.export_pdf, height=50, font=ModernTheme.BUTTON, fg_color=ModernTheme.PRIMARY).pack(side="right", padx=5)
        ctk.CTkButton(actions, text="❌ CANCEL", command=self.destroy, height=50, font=ModernTheme.BUTTON, fg_color="gray").pack(side="right", padx=5)

    def perform_search(self):
        term = self.search_entry.get().strip()
        if not term: return
        
        overlay = LoadingOverlay(self, "SEARCHING...")
        def worker():
            try:
                res = prop_service.search_properties(term)
                items = res.get("items", [])
                self.after(0, lambda: self._update_search_results(items))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Search Error", str(e)))
            finally:
                self.after(0, lambda: overlay.hide())
        threading.Thread(target=worker, daemon=True).start()

    def _update_search_results(self, items):
        for item in self.search_tree.get_children():
            self.search_tree.delete(item)
        for i in items:
            self.search_tree.insert("", "end", values=(i[1], i[2]), tags=(i[0],)) # ID is in tags

    def add_to_selection(self, event=None):
        sel = self.search_tree.selection()
        for item in sel:
            vals = self.search_tree.item(item)["values"]
            prop_id = self.search_tree.item(item)["tags"][0]
            # Check if already in sel_tree
            exists = False
            for s_item in self.sel_tree.get_children():
                if self.sel_tree.item(s_item)["tags"][0] == prop_id:
                    exists = True
                    break
            if not exists:
                self.sel_tree.insert("", "end", values=vals, tags=(prop_id,))
        self.recalculate()

    def remove_from_selection(self):
        sel = self.sel_tree.selection()
        for item in sel:
            self.sel_tree.delete(item)
        self.recalculate()

    def recalculate(self):
        prop_ids = [self.sel_tree.item(i)["tags"][0] for i in self.sel_tree.get_children()]
        if not prop_ids:
            for i in self.comp_tree.get_children(): self.comp_tree.delete(i)
            self.total_lbl.configure(text="GRAND TOTAL DUE: ₱ 0.00")
            return

        try:
            penalty_rate = float(self.penalty_entry.get() or 0) / 100
            discount_rate = float(self.discount_entry.get() or 0) / 100
            amnesty_year = int(self.amnesty_entry.get() or 0)
            lp_year_raw = self.last_year_entry.get().strip()
            lp_year = int(lp_year_raw) if lp_year_raw.isdigit() else None
            project_until = int(self.project_until_entry.get() or 2026)
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter valid numeric rates and years.")
            return
        
        overlay = LoadingOverlay(self, "CALCULATING...")
        def worker():
            try:
                res = billing_service.get_custom_computation_preview(
                    prop_ids, 
                    penalty_rate=penalty_rate, 
                    discount_rate=discount_rate,
                    amnesty_year=amnesty_year,
                    last_payment_year=lp_year,
                    project_until=project_until
                )


                
                all_rows = []
                for prop in res.get("properties", []):
                    td = prop["td_number"]
                    for row in prop["rows"]:
                        all_rows.append((
                            td, 
                            row["year_from"], 
                            row["year_to"], 
                            row["assessed_value"],
                            row["basic"], 
                            row["sef"], 
                            row["penalty"], 
                            row["discount"], 
                            row["total"]
                        ))

                
                self.after(0, lambda r=res: self._update_comp_table(all_rows, r.get("grand_total", 0), r.get("properties", [])))

            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror("Calculation Error", str(err)))

            finally:
                self.after(0, lambda: overlay.hide())
        
        threading.Thread(target=worker, daemon=True).start()


    def _update_comp_table(self, rows, total, properties=[]):
        for item in self.comp_tree.get_children():
            self.comp_tree.delete(item)
            
        # Update Last Payment Label from the first property
        if properties:
            lp = properties[0].get("last_payment", {})
            self.last_pay_lbl.configure(text=f"LAST PAYMENT: {lp.get('year', 'N/A')} | DATE: {lp.get('date', 'N/A')} | OR: {lp.get('or_number', 'N/A')}")

            
        for r in rows:
            # r = (td, year_from, year_to, av, basic, sef, penalty, discount, total)
            year_display = str(r[1])
            if r[1] != r[2]:
                year_display += f" - {r[2]}"
            
            formatted = [
                r[0], # TD
                year_display, 
                format_curr(r[3]), # AV
                format_curr(r[4]), # Basic
                format_curr(r[5]), # SEF
                format_curr(r[6]), # Penalty
                format_curr(r[7]), # Discount
                format_curr(r[8])  # Total
            ]
            self.comp_tree.insert("", "end", values=formatted)
        self.total_lbl.configure(text=f"GRAND TOTAL DUE: {format_curr(total)}")


    def export_pdf(self):
        prop_ids = [self.sel_tree.item(i)["tags"][0] for i in self.sel_tree.get_children()]
        if not prop_ids:
            messagebox.showwarning("Empty Selection", "Please add at least one property to compute.")
            return

        try:
            penalty_rate = float(self.penalty_entry.get() or 0) / 100
            discount_rate = float(self.discount_entry.get() or 0) / 100
            amnesty_year = int(self.amnesty_entry.get() or 0)
            lp_year_raw = self.last_year_entry.get().strip()
            lp_year = int(lp_year_raw) if lp_year_raw.isdigit() else None
            project_until = int(self.project_until_entry.get() or 2026)
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter valid numeric rates and years.")
            return

        overlay = LoadingOverlay(self, "GENERATING PDF...")
        def worker():
            try:
                path = billing_service.export_custom_computation(
                    prop_ids, 
                    penalty_rate=penalty_rate, 
                    discount_rate=discount_rate,
                    amnesty_year=amnesty_year,
                    last_payment_year=lp_year,
                    project_until=project_until
                )

                if path:
                    self.after(0, lambda: messagebox.showinfo("Success", f"Professional Computation PDF generated!\n\nLocation: {path}"))
                    # Optional: Open the file automatically
                    import os
                    os.startfile(path)
                else:
                    self.after(0, lambda: messagebox.showerror("Error", "Failed to generate PDF. Check server logs."))
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror("Export Error", str(err)))
            finally:
                self.after(0, lambda: overlay.hide())

        threading.Thread(target=worker, daemon=True).start()

