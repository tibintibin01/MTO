import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import api_clients.billing_service as billing
from theme_manager import ModernTheme
from utils import format_curr, tr
from ui_components import LoadingOverlay, ErrorDialog
import os
from ui.computation_wizard import ComputationWizard


class DelinquencyDashboardPage:
    def __init__(self, parent, user=None):
        self.parent = parent
        self.user = user
        self.current_page = 0
        self.page_size = 50
        
        self.container = ctk.CTkFrame(parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)
        self.setup_ui()
        self.refresh_table()

    def setup_ui(self):
        # Header Area
        header_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        header_fr.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            header_fr, text="DELINQUENCY COMMAND CENTER", font=ModernTheme.H1, text_color=ModernTheme.PRIMARY
        ).pack(side="left")

        ctk.CTkButton(
            header_fr,
            text="🔄 REFRESH LIST",
            command=self.refresh_table,
            width=150,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.SECONDARY,
        ).pack(side="right", padx=10)

        # Info Card
        info_fr = ctk.CTkFrame(self.container, fg_color=ModernTheme.SECONDARY, corner_radius=10)
        info_fr.pack(fill="x", pady=(0, 15))
        
        ctk.CTkLabel(
            info_fr, 
            text="Showing properties with outstanding balances. Use the buttons below to generate official computations or notices.",
            font=ModernTheme.BODY,
            text_color="white"
        ).pack(side="left", padx=20, pady=10)

        # Table Container
        table_fr = ctk.CTkFrame(self.container, fg_color="white", corner_radius=12)
        table_fr.pack(fill="both", expand=True)

        # Style Treeview
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Delinq.Treeview",
            rowheight=40,
            font=ModernTheme.BODY,
            background="#1e1e1e",
            fieldbackground="#1e1e1e",
            foreground="white",
        )
        style.configure(
            "Delinq.Treeview.Heading",
            font=ModernTheme.BODY_BOLD,
            background="#333333",
            foreground="white",
        )
        style.map("Delinq.Treeview", background=[("selected", ModernTheme.PRIMARY)])

        self.cols = ("ID", "TD NUMBER", "OWNER NAME", "LOCATION", "TOTAL DUE", "TOTAL PAID", "BALANCE")
        self.tree = ttk.Treeview(
            table_fr, columns=self.cols, show="headings", style="Delinq.Treeview"
        )

        for col in self.cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center", width=120)

        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.column("OWNER NAME", width=250, anchor="w")
        self.tree.column("LOCATION", width=200, anchor="w")
        self.tree.column("BALANCE", width=150)

        scrolly = ttk.Scrollbar(table_fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrolly.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrolly.pack(side="right", fill="y")

        # Zebra Tags
        self.tree.tag_configure("oddrow", background="#2b2b2b", foreground="white")
        self.tree.tag_configure("evenrow", background="#333333", foreground="white")

        # --- ACTION BAR ---
        self.actions = ctk.CTkFrame(self.container, fg_color="transparent")
        self.actions.pack(side="bottom", fill="x", pady=(15, 0))

        self.compute_btn = ctk.CTkButton(
            self.actions,
            text="📊 GENERATE COMPUTATION",
            command=self.generate_computation,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.SUCCESS,
            state="disabled",
            height=45
        )
        self.compute_btn.pack(side="right", padx=5)

        self.notice_btn = ctk.CTkButton(
            self.actions,
            text="⚠️ GENERATE NOTICE",
            command=self.generate_notice,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.DANGER,
            state="disabled",
            height=45
        )
        self.notice_btn.pack(side="right", padx=5)

        self.tree.bind("<<TreeviewSelect>>", self.on_selection_change)

    def on_selection_change(self, event=None):
        has_sel = bool(self.tree.selection())
        self.compute_btn.configure(state="normal" if has_sel else "disabled")
        self.notice_btn.configure(state="normal" if has_sel else "disabled")

    def refresh_table(self):
        overlay = LoadingOverlay(self.container, "FETCHING DELINQUENT ACCOUNTS...")

        def worker():
            try:
                offset = self.current_page * self.page_size
                items = billing.get_delinquent_accounts(limit=self.page_size, offset=offset)
                self.container.after(0, lambda: self._update_table(items))
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Error", str(err)))
            finally:
                self.container.after(0, lambda: overlay.hide())

        threading.Thread(target=worker, daemon=True).start()

    def _update_table(self, results):
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not results:
            return

        for i, r in enumerate(results):
            # r: (id, td, owner, loc, total_due, total_paid, balance)
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            formatted_vals = list(r)
            formatted_vals[4] = format_curr(r[4]) # Total Due
            formatted_vals[5] = format_curr(r[5]) # Total Paid
            formatted_vals[6] = format_curr(r[6]) # Balance

            self.tree.insert("", "end", values=formatted_vals, tags=(tag,))
        self.on_selection_change()

    def generate_computation(self):
        sel = self.tree.selection()
        initial_search = ""
        if sel:
            initial_search = self.tree.item(sel[0])["values"][2]
            
        wizard = ComputationWizard(self.container, initial_search=initial_search)
        wizard.focus_set()

        
        overlay = LoadingOverlay(self.container, f"GENERATING COMPUTATION FOR {td_no}...")
        
        def worker():
            try:
                # Trigger the backend PDF generation and get the local temp path
                pdf_path = billing.download_computation_pdf(prop_id)
                
                # Open the PDF automatically (Windows specific)
                if pdf_path and os.path.exists(pdf_path):
                    os.startfile(pdf_path)
                    
                self.container.after(0, lambda: messagebox.showinfo("Success", f"Computation generated successfully for TD: {td_no}"))
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Generation Error", str(err)))
            finally:
                self.container.after(0, lambda: overlay.hide())

        threading.Thread(target=worker, daemon=True).start()

    def generate_notice(self):
        sel = self.tree.selection()
        if not sel: return
        prop_id = self.tree.item(sel[0])["values"][0]
        td_no = self.tree.item(sel[0])["values"][1]
        
        overlay = LoadingOverlay(self.container, f"GENERATING NOTICE FOR {td_no}...")
        
        def worker():
            try:
                # Call the dedicated notice-pdf endpoint
                pdf_path = billing.download_notice_pdf(prop_id)
                
                # Open the PDF automatically (Windows specific)
                if pdf_path and os.path.exists(pdf_path):
                    os.startfile(pdf_path)
                    
                self.container.after(0, lambda: messagebox.showinfo("Success", f"Delinquency Notice generated successfully for TD: {td_no}"))
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Generation Error", str(err)))
            finally:
                self.container.after(0, lambda: overlay.hide())

        threading.Thread(target=worker, daemon=True).start()
