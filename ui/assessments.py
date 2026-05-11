import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from theme_manager import ModernTheme
import api_clients.property_service as prop


class AssessmentsPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.setup_ui()

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            self.container, text="ASSESSMENTS AND TAX ROLL", font=ModernTheme.H2
        ).pack(anchor="w", pady=(0, 20))

        self.tabview = ctk.CTkTabview(self.container)
        self.tabview.pack(fill="both", expand=True)

        self.tax_roll_tab = self.tabview.add("Assessment Roll")
        self.delinquency_tab = self.tabview.add("Delinquency Management")

        self.setup_tax_roll_tab()
        self.setup_delinquency_tab()

    def setup_tax_roll_tab(self):
        filter_fr = ctk.CTkFrame(self.tax_roll_tab)
        filter_fr.pack(fill="x", padx=10, pady=10)
        ctk.CTkButton(
            filter_fr, text="LOAD ASSESSMENT ROLL", command=self.load_assessment_roll
        ).pack(side="left", padx=10)

        self.roll_tree_fr = ctk.CTkFrame(self.tax_roll_tab)
        self.roll_tree_fr.pack(fill="both", expand=True, padx=10, pady=10)

        cols = (
            "TD Number",
            "Owner Name",
            "Location",
            "Kind",
            "Assessed Value",
            "Basic Tax",
            "SEF Tax",
        )
        self.roll_tree = ttk.Treeview(self.roll_tree_fr, columns=cols, show="headings")
        for col in cols:
            self.roll_tree.heading(col, text=col)
            self.roll_tree.column(col, width=120, anchor="center")
        self.roll_tree.pack(fill="both", expand=True)

        # Zebra Tags
        self.roll_tree.tag_configure("oddrow", background="#2b2b2b")
        self.roll_tree.tag_configure("evenrow", background="#333333")

    def setup_delinquency_tab(self):
        delinq_fr = ctk.CTkFrame(self.delinquency_tab)
        delinq_fr.pack(fill="both", expand=True, padx=10, pady=10)

        btn_fr = ctk.CTkFrame(delinq_fr)
        btn_fr.pack(fill="x", pady=5)
        ctk.CTkButton(
            btn_fr,
            text="FETCH DELINQUENT ACCOUNTS",
            command=self.load_delinquent_accounts,
        ).pack(side="left", padx=10)

        cols = (
            "TD Number",
            "Owner Name",
            "Location",
            "Assessed Value",
            "Years Delinq",
            "Total Due",
        )
        self.delinq_tree = ttk.Treeview(delinq_fr, columns=cols, show="headings")
        for col in cols:
            self.delinq_tree.heading(col, text=col)
            self.delinq_tree.column(col, width=130, anchor="center")
        self.delinq_tree.pack(fill="both", expand=True, pady=10)

        # Zebra Tags
        self.delinq_tree.tag_configure("oddrow", background="#2b2b2b")
        self.delinq_tree.tag_configure("evenrow", background="#333333")

    def load_assessment_roll(self):
        def worker():
            try:
                data = prop.get_assessment_roll()
                self.container.after(0, lambda: self._update_roll_table(data))
            except Exception as e:
                self.container.after(
                    0, lambda err=e: messagebox.showerror("Error", str(err))
                )

        threading.Thread(target=worker, daemon=True).start()

    def _update_roll_table(self, data):
        for item in self.roll_tree.get_children():
            self.roll_tree.delete(item)
        for i, row in enumerate(data):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.roll_tree.insert("", "end", values=row, tags=(tag,))

    def load_delinquent_accounts(self):
        def worker():
            try:
                data = prop.get_delinquent_accounts()
                self.container.after(0, lambda: self._update_delinq_table(data))
            except Exception as e:
                self.container.after(
                    0, lambda err=e: messagebox.showerror("Error", str(err))
                )

        threading.Thread(target=worker, daemon=True).start()

    def _update_delinq_table(self, data):
        for item in self.delinq_tree.get_children():
            self.delinq_tree.delete(item)
        for i, row in enumerate(data):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.delinq_tree.insert("", "end", values=row, tags=(tag,))
