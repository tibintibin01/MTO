import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import threading
from theme_manager import ModernTheme
import api_clients.billing_service as billing
import api_clients.property_service as prop
import api_clients.system_service as system
from utils import format_curr, tr


class ReportsPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.setup_ui()

    def setup_ui(self):
        # Progress bar at the very top (outside main container)
        self.loading_bar = ctk.CTkProgressBar(self.parent, height=2, corner_radius=0, progress_color=ModernTheme.PRIMARY)
        self.loading_bar.pack(fill="x")
        self.loading_bar.set(0)
        self.loading_bar.pack_forget()

        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        ctk.CTkLabel(
            self.container,
            text=tr("reports.title"),
            font=ModernTheme.H2,
        ).pack(anchor="w", pady=(0, 20))

        self.tabview = ctk.CTkTabview(self.container)
        self.tabview.pack(fill="both", expand=True)

        self.collection_tab = self.tabview.add(tr("reports.tabs.collection"))
        self.receivables_tab = self.tabview.add(tr("reports.tabs.receivables"))
        self.barangay_tab = self.tabview.add(tr("reports.tabs.barangay"))

        self.setup_collection_tab()
        self.setup_receivables_tab()
        self.setup_barangay_tab()

    def _show_loading(self):
        try:
            self.loading_bar.pack(fill="x", side="top", before=self.container)
            self.loading_bar.start()
        except Exception:
            pass

    def _hide_loading(self):
        try:
            self.loading_bar.stop()
            self.loading_bar.pack_forget()
        except Exception:
            pass

    def setup_collection_tab(self):
        filter_fr = ctk.CTkFrame(self.collection_tab, fg_color=ModernTheme.SECONDARY, corner_radius=8)
        filter_fr.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(
            filter_fr, text=tr("reports.collection.filter_label"), font=ModernTheme.BODY_BOLD, text_color="white"
        ).pack(side="left", padx=10)

        self.month_cb = ctk.CTkComboBox(
            filter_fr, values=["All"] + [f"{m:02d}" for m in range(1, 13)]
        )
        self.month_cb.set(datetime.now().strftime("%m"))
        self.month_cb.pack(side="left", padx=5)

        current_year = datetime.now().year
        self.year_cb = ctk.CTkComboBox(
            filter_fr,
            values=["All"]
            + [str(y) for y in range(current_year - 10, current_year + 3)],
        )
        self.year_cb.set(str(current_year))
        self.year_cb.pack(side="left", padx=5)

        ctk.CTkButton(
            filter_fr, text=tr("reports.collection.btn_generate"), command=self.generate_collection_report,
            font=ModernTheme.BUTTON, fg_color=ModernTheme.SUCCESS
        ).pack(side="left", padx=10)

        self.coll_table_fr = ctk.CTkFrame(self.collection_tab)
        self.coll_table_fr.pack(fill="both", expand=True, padx=10, pady=10)

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

        cols = (
            tr("reports.collection.table.date"),
            tr("reports.collection.table.or"),
            tr("reports.collection.table.td"),
            tr("reports.collection.table.owner"),
            tr("reports.collection.table.kind"),
            tr("reports.collection.table.year"),
            tr("reports.collection.table.amount"),
            tr("reports.collection.table.posted")
        )
        self.coll_tree = ttk.Treeview(self.coll_table_fr, columns=cols, show="headings")
        for col in cols:
            self.coll_tree.heading(col, text=col.upper())
            self.coll_tree.column(col, width=100, anchor="center")
        self.coll_tree.pack(fill="both", expand=True)

        # Zebra Tags
        self.coll_tree.tag_configure("oddrow", background="#2b2b2b", foreground="white")
        self.coll_tree.tag_configure(
            "evenrow", background="#333333", foreground="white"
        )

    def setup_receivables_tab(self):
        receiv_fr = ctk.CTkFrame(self.receivables_tab, fg_color="transparent")
        receiv_fr.pack(fill="both", expand=True, padx=10, pady=10)

        filter_fr = ctk.CTkFrame(receiv_fr)
        filter_fr.pack(fill="x", pady=10)

        curr_y = datetime.now().year
        self.receiv_year_cb = ctk.CTkComboBox(
            filter_fr, values=[str(y) for y in range(curr_y - 10, curr_y + 3)]
        )
        self.receiv_year_cb.set(str(curr_y))
        self.receiv_year_cb.pack(side="left", padx=10)

        ctk.CTkButton(
            filter_fr, text=tr("reports.receivables.btn_load"), command=self.generate_receivables_report,
            font=ModernTheme.BUTTON, fg_color=ModernTheme.PRIMARY
        ).pack(side="left")

        self.receiv_content = ctk.CTkFrame(receiv_fr, fg_color="transparent")
        self.receiv_content.pack(fill="both", expand=True)
        self.receiv_label = ctk.CTkLabel(
            self.receiv_content, text=tr("reports.receivables.hint"), font=ModernTheme.BODY, text_color=ModernTheme.TEXT_GRAY
        )
        self.receiv_label.pack(pady=50)

    def setup_barangay_tab(self):
        brgy_fr = ctk.CTkFrame(self.barangay_tab, fg_color="transparent")
        brgy_fr.pack(fill="both", expand=True, padx=20, pady=20)

        # Header Area
        top_fr = ctk.CTkFrame(brgy_fr, fg_color="transparent")
        top_fr.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            top_fr,
            text=tr("reports.barangay.title"),
            font=ModernTheme.H3,
            text_color=ModernTheme.PRIMARY,
        ).pack(side="left")
        ctk.CTkButton(
            top_fr,
            text=f"🔄 {tr('reports.barangay.btn_refresh')}",
            command=self.generate_barangay_receivables,
            width=200,
            height=35,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.SECONDARY,
        ).pack(side="right")

        # Table Container
        t_container = ctk.CTkFrame(brgy_fr)
        t_container.pack(fill="both", expand=True)

        cols = (
            tr("reports.barangay.table.barangay"),
            tr("reports.barangay.table.assessed"),
            tr("reports.barangay.table.due"),
            tr("reports.barangay.table.penalty"),
            tr("reports.barangay.table.discount"),
            tr("reports.barangay.table.collected"),
            tr("reports.barangay.table.receivable"),
        )
        self.brgy_tree = ttk.Treeview(t_container, columns=cols, show="headings")
        for col in cols:
            self.brgy_tree.heading(col, text=col.upper())
            self.brgy_tree.column(col, width=120, anchor="center")

        self.brgy_tree.column("Barangay", width=180, anchor="w")
        self.brgy_tree.column("Total Receivable", width=150)

        # Scrollbar
        scrolly = ttk.Scrollbar(
            t_container, orient="vertical", command=self.brgy_tree.yview
        )
        self.brgy_tree.configure(yscrollcommand=scrolly.set)

        self.brgy_tree.pack(side="left", fill="both", expand=True)
        scrolly.pack(side="right", fill="y")

        # Zebra Tags
        self.brgy_tree.tag_configure("oddrow", background="#2b2b2b", foreground="white")
        self.brgy_tree.tag_configure(
            "evenrow", background="#333333", foreground="white"
        )

        # --- SUMMARY FOOTER ---
        self.brgy_summary = ctk.CTkFrame(
            brgy_fr, height=50, fg_color="#2c3e50", corner_radius=8
        )
        self.brgy_summary.pack(fill="x", pady=(15, 0))

        self.brgy_total_lbl = ctk.CTkLabel(
            self.brgy_summary,
            text=tr("reports.barangay.total").replace("{value}", "P 0.00"),
            font=ModernTheme.H3,
            text_color="white",
        )
        self.brgy_total_lbl.pack(side="right", padx=30, pady=10)

    def generate_collection_report(self):
        month = self.month_cb.get()
        year = self.year_cb.get()
        self._show_loading()

        def worker():
            try:
                data = billing.get_report_details(month, year)
                self.container.after(0, lambda: self._update_coll_table(data))
            except Exception as e:
                self.container.after(
                    0, lambda err=e: messagebox.showerror("Error", str(err))
                )
            finally:
                self.container.after(0, self._hide_loading)

        threading.Thread(target=worker, daemon=True).start()

    def _update_coll_table(self, data):
        for item in self.coll_tree.get_children():
            self.coll_tree.delete(item)

        if not data:
            ErrorDialog(self.parent.winfo_toplevel(), tr("reports.tabs.collection"), tr("reports.errors.no_collection"))
            return

        for i, row in enumerate(data):
            # Format the amount (index 6)
            formatted_row = list(row)
            if len(formatted_row) > 6:
                formatted_row[6] = format_curr(formatted_row[6])

            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.coll_tree.insert("", "end", values=formatted_row, tags=(tag,))

    def generate_receivables_report(self):
        year = self.receiv_year_cb.get()
        self._show_loading()

        def worker():
            try:
                data = billing.get_rpt_receivables_summary(year)
                self.container.after(0, lambda: self._update_receiv_summary(data))
            except Exception as e:
                self.container.after(
                    0, lambda err=e: messagebox.showerror("Error", str(err))
                )
            finally:
                self.container.after(0, self._hide_loading)

        threading.Thread(target=worker, daemon=True).start()

    def _update_receiv_summary(self, data):
        for child in self.receiv_content.winfo_children():
            child.destroy()

        if not data:
            ErrorDialog(self.parent.winfo_toplevel(), tr("reports.tabs.receivables"), tr("reports.errors.no_receivables"))
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
        ctk.CTkLabel(
            header_fr,
            text=tr("reports.receivables.performance_title").replace("{year}", str(year)),
            font=ModernTheme.H2,
            text_color=ModernTheme.PRIMARY,
        ).pack(side="left")
        
        eff_color = ModernTheme.SUCCESS if efficiency > 50 else ModernTheme.WARNING
        ctk.CTkLabel(
            header_fr,
            text=tr("reports.receivables.efficiency").replace("{value}", f"{efficiency:.1f}"),
            font=ModernTheme.H3,
            text_color=eff_color,
        ).pack(side="right")

        # --- CARDS GRID ---
        grid_fr = ctk.CTkFrame(self.receiv_content, fg_color="transparent")
        grid_fr.pack(fill="x")
        grid_fr.grid_columnconfigure((0, 1, 2), weight=1)

        # Helper to make a metric card
        def make_card(parent, row, col, title, value, color, icon=""):
            card = ctk.CTkFrame(parent, height=140, corner_radius=12)
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

            ctk.CTkLabel(
                card,
                text=title.upper(),
                font=ModernTheme.BODY_BOLD,
                text_color=ModernTheme.TEXT_GRAY,
            ).pack(pady=(20, 5))
            ctk.CTkLabel(
                card,
                text=f"P {value:,.2f}",
                font=ModernTheme.H2,
                text_color=color,
            ).pack(pady=(0, 20))

            # Subtle indicator bar at the bottom of the card
            indicator = ctk.CTkFrame(card, height=4, fg_color=color, corner_radius=0)
            indicator.pack(fill="x", side="bottom")

        make_card(grid_fr, 0, 0, tr("reports.receivables.cards.beginning"), beg, ModernTheme.TEXT_GRAY)
        make_card(grid_fr, 0, 1, tr("reports.receivables.cards.assessment"), curr, ModernTheme.PRIMARY)
        make_card(grid_fr, 0, 2, tr("reports.receivables.cards.adjustments"), adj, "#9b59b6")

        # Lower Row
        grid_fr_2 = ctk.CTkFrame(self.receiv_content, fg_color="transparent")
        grid_fr_2.pack(fill="x")
        grid_fr_2.grid_columnconfigure((0, 1), weight=1)

        make_card(grid_fr_2, 0, 0, tr("reports.receivables.cards.collections"), coll, ModernTheme.SUCCESS)
        make_card(grid_fr_2, 0, 1, tr("reports.receivables.cards.ending"), end, ModernTheme.DANGER)

        # --- VISUAL EFFICIENCY METER ---
        meter_fr = ctk.CTkFrame(self.receiv_content, height=80, corner_radius=15)
        meter_fr.pack(fill="x", pady=20, padx=10)

        ctk.CTkLabel(
            meter_fr,
            text=tr("reports.receivables.target_progress"),
            font=ModernTheme.BODY_BOLD,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(pady=(15, 5), padx=30, anchor="w")

        prog_bar = ctk.CTkProgressBar(meter_fr, height=12, corner_radius=6)
        prog_bar.pack(fill="x", padx=30, pady=(5, 15))
        prog_bar.set(min(1.0, efficiency / 100))
        prog_bar.configure(progress_color=ModernTheme.SUCCESS if efficiency > 70 else ModernTheme.WARNING)

    def generate_barangay_receivables(self):
        self._show_loading()

        def worker():
            try:
                data = prop.get_receivables_by_barangay()
                self.container.after(0, lambda: self._update_brgy_table(data))
            except Exception as e:
                self.container.after(
                    0, lambda err=e: messagebox.showerror("Error", str(err))
                )
            finally:
                self.container.after(0, self._hide_loading)

        threading.Thread(target=worker, daemon=True).start()

    def _update_brgy_table(self, data):
        for item in self.brgy_tree.get_children():
            self.brgy_tree.delete(item)

        if not data:
            ErrorDialog(self.parent.winfo_toplevel(), tr("reports.tabs.barangay"), tr("reports.errors.no_barangay"))
            self.brgy_total_lbl.configure(text=tr("reports.barangay.total").replace("{value}", "P 0.00"))
            return

        grand_total = 0.0
        for i, row in enumerate(data):
            # row: 0:brgy, 1:assessed, 2:due, 3:pen, 4:disc, 5:coll, 6:receiv
            f_row = list(row)
            try:
                receiv_val = float(row[6] or 0)
                grand_total += receiv_val
            except:
                pass

            if len(f_row) >= 7:
                # Format all currency columns (1 through 6)
                for idx in range(1, 7):
                    f_row[idx] = format_curr(f_row[idx])

            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.brgy_tree.insert("", "end", values=f_row, tags=(tag,))

        self.brgy_total_lbl.configure(
            text=tr("reports.barangay.total").replace("{value}", f"P {grand_total:,.2f}")
        )
