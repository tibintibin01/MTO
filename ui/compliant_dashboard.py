"""
Compliant Properties Dashboard
Shows all properties with zero outstanding balance, grouped by barangay.
Mirrors the style of DelinquencyDashboardPage.
"""
import csv
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import customtkinter as ctk

import api_clients.billing_service as billing
from theme_manager import ModernTheme
from utils import format_curr, tr
from ui_components import LoadingOverlay


class CompliantDashboardPage:
    def __init__(self, parent, user=None):
        self.parent = parent
        self.user = user
        self._summary = []          # list of barangay summary dicts
        self._selected_barangay = "ALL"

        self.container = ctk.CTkFrame(parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        self._setup_ui()
        self._load_all()

    # ── UI Construction ───────────────────────────────────────────────────────

    def _setup_ui(self):
        # ── Page header ──────────────────────────────────────────────────────
        header_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        header_fr.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            header_fr,
            text="✅  COMPLIANT PROPERTIES",
            font=ModernTheme.H1,
            text_color=ModernTheme.SUCCESS,
        ).pack(side="left")

        btn_fr = ctk.CTkFrame(header_fr, fg_color="transparent")
        btn_fr.pack(side="right")

        ctk.CTkButton(
            btn_fr,
            text="📥  EXPORT CSV",
            command=self._export_csv,
            width=140,
            font=ModernTheme.BUTTON,
            fg_color="#2e7d32",
            hover_color="#1b5e20",
            height=38,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_fr,
            text="🔄  REFRESH",
            command=self._load_all,
            width=120,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.SECONDARY,
            height=38,
        ).pack(side="right")

        # ── Info banner ───────────────────────────────────────────────────────
        info_fr = ctk.CTkFrame(
            self.container, fg_color="#1b4332", corner_radius=10
        )
        info_fr.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(
            info_fr,
            text=(
                "Properties where total amount paid ≥ total amount due across "
                "ALL billing years.  Click a barangay row to filter the list below."
            ),
            font=ModernTheme.BODY,
            text_color="#a7f3d0",
        ).pack(side="left", padx=20, pady=10)

        # ── KPI strip ─────────────────────────────────────────────────────────
        self._kpi_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        self._kpi_fr.pack(fill="x", pady=(0, 14))

        self._kpi_compliant  = self._kpi_card(self._kpi_fr, "COMPLIANT",       "0",    "#2e7d32")
        self._kpi_rate       = self._kpi_card(self._kpi_fr, "COMPLIANCE RATE", "0.0%", "#1565c0")
        self._kpi_collected  = self._kpi_card(self._kpi_fr, "TOTAL COLLECTED", "₱0",   "#6a1b9a")
        self._kpi_barangays  = self._kpi_card(self._kpi_fr, "BARANGAYS",       "0",    "#e65100")

        # ── Split pane: summary table (left) + property list (right) ─────────
        pane = ctk.CTkFrame(self.container, fg_color="transparent")
        pane.pack(fill="both", expand=True)
        pane.columnconfigure(0, weight=2)
        pane.columnconfigure(1, weight=5)
        pane.rowconfigure(0, weight=1)

        # Left — barangay summary
        left_fr = ctk.CTkFrame(pane, fg_color="transparent")
        left_fr.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self._setup_summary_table(left_fr)

        # Right — property list
        right_fr = ctk.CTkFrame(pane, fg_color="transparent")
        right_fr.grid(row=0, column=1, sticky="nsew")
        self._setup_property_table(right_fr)

    # ── KPI card helper ───────────────────────────────────────────────────────

    def _kpi_card(self, parent, label, value, color):
        card = ctk.CTkFrame(
            parent,
            fg_color=("#f0fdf4", "#1a2634"),
            corner_radius=10,
            border_width=1,
            border_color=(color, color),
        )
        card.pack(side="left", fill="both", expand=True, padx=4)

        ctk.CTkLabel(
            card,
            text=label,
            font=("Segoe UI", 9, "bold"),
            text_color="gray",
        ).pack(pady=(10, 2))

        lbl = ctk.CTkLabel(
            card,
            text=value,
            font=("Segoe UI", 20, "bold"),
            text_color=color,
        )
        lbl.pack(pady=(0, 10))
        return lbl

    # ── Barangay summary table ────────────────────────────────────────────────

    def _setup_summary_table(self, parent):
        ctk.CTkLabel(
            parent,
            text="BY BARANGAY",
            font=("Segoe UI", 11, "bold"),
            text_color=ModernTheme.PRIMARY,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        style = ttk.Style()
        style.configure(
            "Summary.Treeview",
            rowheight=34,
            font=ModernTheme.BODY,
            background="#1e1e1e",
            fieldbackground="#1e1e1e",
            foreground="white",
        )
        style.configure(
            "Summary.Treeview.Heading",
            font=ModernTheme.BODY_BOLD,
            background="#333",
            foreground="white",
        )
        style.map("Summary.Treeview", background=[("selected", "#2e7d32")])

        cols = ("BARANGAY", "TOTAL", "✅", "RATE")
        self._sum_tree = ttk.Treeview(
            parent, columns=cols, show="headings", style="Summary.Treeview"
        )
        for col in cols:
            self._sum_tree.heading(col, text=col)
        self._sum_tree.column("BARANGAY", width=140, anchor="w")
        self._sum_tree.column("TOTAL",    width=55,  anchor="center")
        self._sum_tree.column("✅",       width=55,  anchor="center")
        self._sum_tree.column("RATE",     width=65,  anchor="center")

        scrolly = ttk.Scrollbar(parent, orient="vertical", command=self._sum_tree.yview)
        self._sum_tree.configure(yscrollcommand=scrolly.set)
        self._sum_tree.pack(side="left", fill="both", expand=True)
        scrolly.pack(side="right", fill="y")

        self._sum_tree.tag_configure("oddrow",  background="#2b2b2b", foreground="white")
        self._sum_tree.tag_configure("evenrow", background="#333",    foreground="white")
        self._sum_tree.tag_configure("all_row", background="#1b4332", foreground="#a7f3d0",
                                     font=("Segoe UI", 11, "bold"))

        self._sum_tree.bind("<<TreeviewSelect>>", self._on_barangay_select)

    # ── Property list table ───────────────────────────────────────────────────

    def _setup_property_table(self, parent):
        # Header row with label + search
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 6))

        self._list_label = ctk.CTkLabel(
            hdr,
            text="ALL COMPLIANT PROPERTIES",
            font=("Segoe UI", 11, "bold"),
            text_color=ModernTheme.SUCCESS,
            anchor="w",
        )
        self._list_label.pack(side="left")

        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_search())
        ctk.CTkEntry(
            hdr,
            textvariable=self._search_var,
            placeholder_text="🔍  Filter by name or TDN...",
            width=220,
            height=32,
            font=ModernTheme.BODY,
        ).pack(side="right")

        style = ttk.Style()
        style.configure(
            "Compliant.Treeview",
            rowheight=36,
            font=ModernTheme.BODY,
            background="#1e1e1e",
            fieldbackground="#1e1e1e",
            foreground="white",
        )
        style.configure(
            "Compliant.Treeview.Heading",
            font=ModernTheme.BODY_BOLD,
            background="#333",
            foreground="white",
        )
        style.map("Compliant.Treeview", background=[("selected", "#2e7d32")])

        cols = ("ID", "TD NUMBER", "OWNER NAME", "BARANGAY", "KIND",
                "TOTAL PAID", "YEARS", "LAST OR", "LAST PAID")
        self._prop_tree = ttk.Treeview(
            parent, columns=cols, show="headings", style="Compliant.Treeview"
        )
        for col in cols:
            self._prop_tree.heading(col, text=col)

        self._prop_tree.column("ID",         width=0,   stretch=tk.NO)
        self._prop_tree.column("TD NUMBER",  width=130, anchor="w")
        self._prop_tree.column("OWNER NAME", width=200, anchor="w")
        self._prop_tree.column("BARANGAY",   width=110, anchor="w")
        self._prop_tree.column("KIND",       width=90,  anchor="center")
        self._prop_tree.column("TOTAL PAID", width=110, anchor="e")
        self._prop_tree.column("YEARS",      width=55,  anchor="center")
        self._prop_tree.column("LAST OR",    width=110, anchor="w")
        self._prop_tree.column("LAST PAID",  width=95,  anchor="center")

        scrolly = ttk.Scrollbar(parent, orient="vertical", command=self._prop_tree.yview)
        self._prop_tree.configure(yscrollcommand=scrolly.set)
        self._prop_tree.pack(side="left", fill="both", expand=True)
        scrolly.pack(side="right", fill="y")

        self._prop_tree.tag_configure("oddrow",  background="#2b2b2b", foreground="white")
        self._prop_tree.tag_configure("evenrow", background="#333",    foreground="white")

        # Store all rows for client-side search filtering
        self._all_rows: list = []

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_all(self):
        overlay = LoadingOverlay(self.container, "LOADING COMPLIANCE DATA...")

        def worker():
            try:
                summary = billing.get_compliant_summary()
                props   = billing.get_compliant_accounts(
                    barangay=None if self._selected_barangay == "ALL"
                             else self._selected_barangay
                )
                self.container.after(0, lambda: self._render(summary, props))
            except Exception as e:
                self.container.after(
                    0, lambda err=e: messagebox.showerror("Load Error", str(err))
                )
            finally:
                self.container.after(0, overlay.hide)

        threading.Thread(target=worker, daemon=True).start()

    def _render(self, summary: list, props: list):
        self._summary = summary
        self._all_rows = props

        # ── KPI cards ────────────────────────────────────────────────────────
        total_props    = sum(r["total_properties"]       for r in summary)
        total_compliant= sum(r["compliant_count"]        for r in summary)
        total_collected= sum(r["collected_from_compliant"] for r in summary)
        rate = (total_compliant / total_props * 100) if total_props else 0.0

        self._kpi_compliant.configure(text=f"{total_compliant:,}")
        self._kpi_rate.configure(text=f"{rate:.1f}%")
        self._kpi_collected.configure(text=format_curr(total_collected))
        self._kpi_barangays.configure(text=str(len(summary)))

        # ── Summary table ─────────────────────────────────────────────────────
        for item in self._sum_tree.get_children():
            self._sum_tree.delete(item)

        # ALL row
        all_rate = f"{rate:.1f}%"
        self._sum_tree.insert(
            "", "end",
            values=("ALL BARANGAYS", total_props, total_compliant, all_rate),
            tags=("all_row",),
            iid="__ALL__",
        )

        for i, row in enumerate(sorted(summary, key=lambda r: r["barangay"])):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            r_str = f"{row['compliance_rate']:.1f}%"
            self._sum_tree.insert(
                "", "end",
                values=(row["barangay"], row["total_properties"],
                        row["compliant_count"], r_str),
                tags=(tag,),
                iid=row["barangay"],
            )

        # ── Property list ─────────────────────────────────────────────────────
        self._apply_search()

    def _apply_search(self):
        """Filters _all_rows by the search box and re-renders the property table."""
        term = self._search_var.get().strip().lower()
        rows = self._all_rows

        if term:
            rows = [
                r for r in rows
                if term in str(r[1]).lower()   # td_number
                or term in str(r[2]).lower()   # owner_name
            ]

        for item in self._prop_tree.get_children():
            self._prop_tree.delete(item)

        for i, r in enumerate(rows):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            # r: (id, td, owner, barangay, kind, total_paid, years, last_or, last_paid)
            display = list(r)
            display[5] = format_curr(r[5])   # total_paid
            self._prop_tree.insert("", "end", values=display, tags=(tag,))

        # Update list label
        brgy_label = (
            "ALL COMPLIANT PROPERTIES"
            if self._selected_barangay == "ALL"
            else f"COMPLIANT — {self._selected_barangay}"
        )
        count_label = f"  ({len(rows)} shown)"
        self._list_label.configure(text=brgy_label + count_label)

    # ── Barangay filter ───────────────────────────────────────────────────────

    def _on_barangay_select(self, event=None):
        sel = self._sum_tree.selection()
        if not sel:
            return
        iid = sel[0]
        self._selected_barangay = "ALL" if iid == "__ALL__" else iid
        self._load_all()

    # ── CSV export ────────────────────────────────────────────────────────────

    def _export_csv(self):
        rows = self._all_rows
        if not rows:
            messagebox.showinfo("Export", "No data to export.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=f"compliant_{self._selected_barangay}.csv",
            title="Save Compliant Properties Report",
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "ID", "TD Number", "Owner Name", "Barangay", "Kind",
                    "Total Paid", "Years Covered", "Last OR", "Last Paid",
                ])
                for r in rows:
                    writer.writerow(r)
            messagebox.showinfo("Export Complete", f"Saved to:\n{path}")
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("Export Error", str(e))
