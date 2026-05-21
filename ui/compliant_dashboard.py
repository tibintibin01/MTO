"""
Compliant Properties Dashboard
Shows all properties with zero outstanding balance, grouped by barangay.
Matches the Midnight Slate dark theme used throughout the desktop app.
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


# ── Muted accent colours that sit comfortably in the dark theme ──────────────
_GREEN   = "#10b981"   # ModernTheme.SUCCESS — used sparingly
_GREEN_DIM = "#064e3b" # very dark green for banner bg
_BLUE    = "#38bdf8"   # ModernTheme.PRIMARY
_SLATE   = "#64748b"   # ModernTheme.SECONDARY
_CARD_BG = ("#e2e8f0", "#1e293b")   # light / dark card background
_BORDER  = ("#cbd5e1", "#334155")   # light / dark border


class CompliantDashboardPage:
    def __init__(self, parent, user=None):
        self.parent = parent
        self.user = user
        self._summary = []
        self._selected_barangay = "ALL"
        self._all_rows: list = []

        self.container = ctk.CTkFrame(parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        self._setup_ui()
        self._load_all()

    # ── UI Construction ───────────────────────────────────────────────────────

    def _setup_ui(self):
        # ── Page header ──────────────────────────────────────────────────────
        header_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        header_fr.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(
            header_fr,
            text="✅  COMPLIANT PROPERTIES",
            font=ModernTheme.H1,
            text_color=ModernTheme.PRIMARY,   # sky blue — matches other page titles
        ).pack(side="left")

        btn_fr = ctk.CTkFrame(header_fr, fg_color="transparent")
        btn_fr.pack(side="right")

        ctk.CTkButton(
            btn_fr,
            text="📥  EXPORT CSV",
            command=self._export_csv,
            width=140,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.SECONDARY,
            hover_color=ModernTheme.SECONDARY_HOVER,
            height=38,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_fr,
            text="🔄  REFRESH",
            command=self._load_all,
            width=120,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.SECONDARY,
            hover_color=ModernTheme.SECONDARY_HOVER,
            height=38,
        ).pack(side="right")

        # ── Info banner — muted, not bright green ─────────────────────────────
        info_fr = ctk.CTkFrame(
            self.container,
            fg_color=("#dbeafe", "#1e293b"),   # light blue tint / dark slate
            corner_radius=8,
            border_width=1,
            border_color=("#93c5fd", "#334155"),
        )
        info_fr.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(
            info_fr,
            text=(
                "Properties where total amount paid ≥ total amount due across "
                "ALL billing years.  Click a barangay row to filter the list below."
            ),
            font=ModernTheme.BODY,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(side="left", padx=16, pady=8)

        # ── KPI strip — plain cards, no coloured borders ──────────────────────
        kpi_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        kpi_fr.pack(fill="x", pady=(0, 14))

        self._kpi_compliant  = self._kpi_card(kpi_fr, "COMPLIANT",       "—")
        self._kpi_rate       = self._kpi_card(kpi_fr, "COMPLIANCE RATE", "—")
        self._kpi_collected  = self._kpi_card(kpi_fr, "TOTAL COLLECTED", "—")
        self._kpi_barangays  = self._kpi_card(kpi_fr, "BARANGAYS",       "—")

        # ── Split pane ────────────────────────────────────────────────────────
        pane = ctk.CTkFrame(self.container, fg_color="transparent")
        pane.pack(fill="both", expand=True)
        pane.columnconfigure(0, weight=2)
        pane.columnconfigure(1, weight=5)
        pane.rowconfigure(0, weight=1)

        left_fr = ctk.CTkFrame(pane, fg_color="transparent")
        left_fr.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self._setup_summary_table(left_fr)

        right_fr = ctk.CTkFrame(pane, fg_color="transparent")
        right_fr.grid(row=0, column=1, sticky="nsew")
        self._setup_property_table(right_fr)

    # ── KPI card — plain dark card, no coloured border ───────────────────────

    def _kpi_card(self, parent, label: str, value: str):
        card = ctk.CTkFrame(
            parent,
            fg_color=_CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=_BORDER,
        )
        card.pack(side="left", fill="both", expand=True, padx=4)

        ctk.CTkLabel(
            card,
            text=label,
            font=("Inter", 9, "bold"),
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(pady=(10, 2))

        lbl = ctk.CTkLabel(
            card,
            text=value,
            font=("Inter", 18, "bold"),
            text_color=ModernTheme.PRIMARY,   # sky blue — consistent with app
        )
        lbl.pack(pady=(0, 10))
        return lbl

    # ── Barangay summary table ────────────────────────────────────────────────

    def _setup_summary_table(self, parent):
        ctk.CTkLabel(
            parent,
            text="BY BARANGAY",
            font=("Inter", 11, "bold"),
            text_color=ModernTheme.TEXT_GRAY,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        style = ttk.Style()
        style.configure(
            "Summary.Treeview",
            rowheight=32,
            font=("Inter", 12),
            background="#1e293b",
            fieldbackground="#1e293b",
            foreground="#f1f5f9",
        )
        style.configure(
            "Summary.Treeview.Heading",
            font=("Inter", 11, "bold"),
            background="#0f172a",
            foreground="#94a3b8",
        )
        style.map("Summary.Treeview", background=[("selected", "#1d4ed8")])

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

        self._sum_tree.tag_configure("oddrow",  background="#1e293b", foreground="#f1f5f9")
        self._sum_tree.tag_configure("evenrow", background="#0f172a", foreground="#f1f5f9")
        self._sum_tree.tag_configure(
            "all_row",
            background="#1d4ed8",   # blue highlight for the ALL row
            foreground="#ffffff",
            font=("Inter", 11, "bold"),
        )

        self._sum_tree.bind("<<TreeviewSelect>>", self._on_barangay_select)

    # ── Property list table ───────────────────────────────────────────────────

    def _setup_property_table(self, parent):
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 6))

        self._list_label = ctk.CTkLabel(
            hdr,
            text="ALL COMPLIANT PROPERTIES",
            font=("Inter", 11, "bold"),
            text_color=ModernTheme.TEXT_GRAY,
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
            rowheight=34,
            font=("Inter", 12),
            background="#1e293b",
            fieldbackground="#1e293b",
            foreground="#f1f5f9",
        )
        style.configure(
            "Compliant.Treeview.Heading",
            font=("Inter", 11, "bold"),
            background="#0f172a",
            foreground="#94a3b8",
        )
        style.map("Compliant.Treeview", background=[("selected", "#1d4ed8")])

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

        self._prop_tree.tag_configure("oddrow",  background="#1e293b", foreground="#f1f5f9")
        self._prop_tree.tag_configure("evenrow", background="#0f172a", foreground="#f1f5f9")

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_all(self):
        overlay = LoadingOverlay(self.container, "LOADING COMPLIANCE DATA...")

        def worker():
            try:
                summary = billing.get_compliant_summary()
                props = billing.get_compliant_accounts(
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

        # ── KPI cards ─────────────────────────────────────────────────────────
        total_props     = sum(r.get("total_properties", 0)         for r in summary)
        total_compliant = sum(r.get("compliant_count", 0)          for r in summary)
        # Derive total collected directly from the property rows — more reliable
        # than the summary endpoint's collected_from_compliant which can be 0
        # when the payment subquery returns no matches.
        total_collected = sum(r[5] for r in props)   # index 5 = total_paid
        rate = (total_compliant / total_props * 100) if total_props else 0.0

        self._kpi_compliant.configure(text=f"{total_compliant:,}")
        self._kpi_rate.configure(text=f"{rate:.1f}%")
        self._kpi_collected.configure(text=format_curr(total_collected))
        self._kpi_barangays.configure(text=str(len(summary)))

        # ── Summary table ──────────────────────────────────────────────────────
        for item in self._sum_tree.get_children():
            self._sum_tree.delete(item)

        all_rate = f"{rate:.1f}%"
        self._sum_tree.insert(
            "", "end",
            values=("ALL BARANGAYS", total_props, total_compliant, all_rate),
            tags=("all_row",),
            iid="__ALL__",
        )

        for i, row in enumerate(sorted(summary, key=lambda r: r.get("barangay", ""))):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            r_str = f"{row.get('compliance_rate', 0):.1f}%"
            self._sum_tree.insert(
                "", "end",
                values=(
                    row.get("barangay", "—"),
                    row.get("total_properties", 0),
                    row.get("compliant_count", 0),
                    r_str,
                ),
                tags=(tag,),
                iid=row.get("barangay", str(i)),
            )

        self._apply_search()

    def _apply_search(self):
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
            display = list(r)
            display[5] = format_curr(r[5])   # total_paid
            # Ensure last_or and last_paid show "—" when None/empty
            display[7] = r[7] if r[7] and r[7] != "None" else "—"
            display[8] = r[8] if r[8] and r[8] != "None" else "—"
            self._prop_tree.insert("", "end", values=display, tags=(tag,))

        brgy_label = (
            "ALL COMPLIANT PROPERTIES"
            if self._selected_barangay == "ALL"
            else f"COMPLIANT — {self._selected_barangay}"
        )
        self._list_label.configure(text=f"{brgy_label}  ({len(rows)} shown)")

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
        if not self._all_rows:
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
                for r in self._all_rows:
                    writer.writerow(r)
            messagebox.showinfo("Export Complete", f"Saved to:\n{path}")
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("Export Error", str(e))
