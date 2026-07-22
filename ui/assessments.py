import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from theme_manager import ModernTheme
from utils import tr
import api_clients.property_service as prop
from ui_components import ErrorDialog


class AssessmentsPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.setup_ui()

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            self.container, text=tr("assessments.title"), font=ModernTheme.H2
        ).pack(anchor="w", pady=(0, 20))

        self.tabview = ctk.CTkTabview(self.container)
        self.tabview.pack(fill="both", expand=True)

        self.tax_roll_tab = self.tabview.add(tr("assessments.tabs.roll"))
        self.delinquency_tab = self.tabview.add(tr("assessments.tabs.delinquency"))

        self.setup_tax_roll_tab()
        self.setup_delinquency_tab()

    def setup_tax_roll_tab(self):
        filter_fr = ctk.CTkFrame(self.tax_roll_tab, fg_color=ModernTheme.SECONDARY, corner_radius=8)
        filter_fr.pack(fill="x", padx=10, pady=10)
        ctk.CTkButton(
            filter_fr, text=tr("assessments.roll.btn_load"), command=self.load_assessment_roll,
            font=ModernTheme.BUTTON, fg_color=ModernTheme.PRIMARY
        ).pack(side="left", padx=10)

        self.roll_tree_fr = ctk.CTkFrame(self.tax_roll_tab)
        self.roll_tree_fr.pack(fill="both", expand=True, padx=10, pady=10)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Treeview",
            rowheight=35,
            font=ModernTheme.BODY,
            background="#1e1e1e",
            fieldbackground="#1e1e1e",
            foreground="white",
        )
        style.configure(
            "Treeview.Heading",
            font=ModernTheme.BODY_BOLD,
            background="#333333",
            foreground="white",
        )
        style.map("Treeview", background=[("selected", ModernTheme.PRIMARY)])

        cols = (
            tr("assessments.roll.table.td"),
            tr("assessments.roll.table.owner"),
            tr("assessments.roll.table.location"),
            tr("assessments.roll.table.kind"),
            tr("assessments.roll.table.value"),
            tr("assessments.roll.table.basic"),
            tr("assessments.roll.table.sef"),
        )
        self.roll_tree = ttk.Treeview(self.roll_tree_fr, columns=cols, show="headings")
        for col in cols:
            self.roll_tree.heading(col, text=col.upper())
            self.roll_tree.column(col, width=120, anchor="center")
        self.roll_tree.pack(fill="both", expand=True)

        # Zebra Tags
        self.roll_tree.tag_configure("oddrow", background="#1e1e1e")
        self.roll_tree.tag_configure("evenrow", background="#2b2b2b")

    def setup_delinquency_tab(self):
        delinq_fr = ctk.CTkFrame(self.delinquency_tab)
        delinq_fr.pack(fill="both", expand=True, padx=10, pady=10)

        btn_fr = ctk.CTkFrame(delinq_fr, fg_color=ModernTheme.SECONDARY, corner_radius=8)
        btn_fr.pack(fill="x", pady=5)
        ctk.CTkButton(
            btn_fr,
            text=tr("assessments.delinquency.btn_fetch"),
            command=self.load_delinquent_accounts,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.DANGER,
        ).pack(side="left", padx=10, pady=8)

        cols = (
            tr("assessments.delinquency.table.td"),
            tr("assessments.delinquency.table.owner"),
            tr("assessments.delinquency.table.location"),
            tr("assessments.delinquency.table.value"),
            tr("assessments.delinquency.table.years"),
            tr("assessments.delinquency.table.total"),
        )
        self.delinq_tree = ttk.Treeview(delinq_fr, columns=cols, show="headings")
        for col in cols:
            self.delinq_tree.heading(col, text=col.upper())
            self.delinq_tree.column(col, width=130, anchor="center")
        self.delinq_tree.pack(fill="both", expand=True, pady=10)

        # Zebra Tags
        self.delinq_tree.tag_configure("oddrow", background="#1e1e1e")
        self.delinq_tree.tag_configure("evenrow", background="#2b2b2b")

    def load_assessment_roll(self):
        def worker():
            try:
                data = prop.get_assessment_roll()
                self.container.after(0, lambda: self._update_roll_table(data))
            except Exception as e:
                self.container.after(
                    0, lambda err=e: ErrorDialog(self.container.winfo_toplevel(), tr("common.system_error"), str(err))
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
                    0, lambda err=e: ErrorDialog(self.container.winfo_toplevel(), tr("common.system_error"), str(err))
                )

        threading.Thread(target=worker, daemon=True).start()

    def _update_delinq_table(self, data):
        for item in self.delinq_tree.get_children():
            self.delinq_tree.delete(item)
        for i, row in enumerate(data):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.delinq_tree.insert("", "end", values=row, tags=(tag,))
