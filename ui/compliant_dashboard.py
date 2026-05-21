"""
Compliant Properties Dashboard
Shows all properties with zero outstanding balance, grouped by barangay.
"""
import csv
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import customtkinter as ctk

import api_clients.billing_service as billing
from theme_manager import ModernTheme
from utils import format_curr
from ui_components import LoadingOverlay

# ── Row colours — softer than pure white on dark bg ──────────────────────────
_ROW_ODD   = "#1e293b"
_ROW_EVEN  = "#162032"
_ROW_FG    = "#cbd5e1"   # slate-300 — readable but not glaring white
_ROW_SEL   = "#1d4ed8"
_HDR_BG    = "#0f172a"
_HDR_FG    = "#64748b"   # slate-500 — muted heading text

# ── Button colours ────────────────────────────────────────────────────────────
_BTN_REFRESH = ("#2563eb", "#1d4ed8")   # blue
_BTN_EXPORT  = ("#059669", "#047857")   # green
_BTN_SEARCH  = ("#475569", "#334155")   # slate

# ── Card colours ─────────────────────────────────────────────────────────────
_CARD_BG  = ("#e2e8f0", "#1e293b")
_CARD_BDR = ("#cbd5e1", "#334155")


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

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        # ── Header ───────────────────────────────────────────────────────────
        header_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        header_fr.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            header_fr,
            text="✅  COMPLIANT PROPERTIES",
            font=ModernTheme.H1,
            text_color=ModernTheme.PRIMARY,
        ).pack(side="left")

        btn_fr = ctk.CTkFrame(header_fr, fg_color="transparent")
        btn_fr.pack(side="right")

        # FIX 3 — stronger, clearly visible button colours
        ctk.CTkButton(
            btn_fr,
            text="📥  EXPORT CSV",
            command=self._export_csv,
            width=148,
            font=ModernTheme.BUTTON,
            fg_color=_BTN_EXPORT[0],
            hover_color=_BTN_EXPORT[1],
            text_color="white",
            height=40,
            corner_radius=8,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_fr,
            text="🔄  REFRESH",
            command=self._load_all,
            width=130,
            font=ModernTheme.BUTTON,
            fg_color=_BTN_REFRESH[0],
            hover_color=_BTN_REFRESH[1],
            text_color="white",
            height=40,
            corner_radius=8,
        ).pack(side="right")

        # ── Info banner ───────────────────────────────────────────────────────
        info_fr = ctk.CTkFrame(
            self.container,
            fg_color=("#dbeafe", "#1e293b"),
            corner_radius=8,
            border_width=1,
            border_color=("#93c5fd", "#334155"),
        )
        info_fr.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            info_fr,
            text=(
                "Properties where total amount paid ≥ total amount due across "
                "ALL billing years.  Click a barangay row to filter the list below."
            ),
            font=ModernTheme.BODY,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(side="left", padx=16, pady=8)

        # ── KPI strip ─────────────────────────────────────────────────────────
        kpi_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        kpi_fr.pack(fill="x", pady=(0, 12))

        self._kpi_compliant = self._kpi_card(kpi_fr, "COMPLIANT",       "—")
        self._kpi_rate      = self._kpi_card(kpi_fr, "COMPLIANCE RATE", "—")
        self._kpi_collected = self._kpi_card(kpi_fr, "TOTAL COLLECTED", "—")
        self._kpi_barangays = self._kpi_card(kpi_fr, "BARANGAYS",       "—")

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

    # ── KPI card ──────────────────────────────────────────────────────────────

    def _kpi_card(self, parent, label: str, value: str):
        card = ctk.CTkFrame(
            parent,
            fg_color=_CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=_CARD_BDR,
        )
        card.pack(side="left", fill="both", expand=True, padx=4)

        ctk.CTkLabel(
            card,
            text=label,
            font=("Inter", 9, "bold"),
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(pady=(10, 2))

        # FIX 2 — larger font for the KPI number
        lbl = ctk.CTkLabel(
            card,
            text=value,
            font=("Inter", 26, "bold"),
            text_color=ModernTheme.PRIMARY,
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
        # FIX 1 — softer foreground colour, not pure white
        style.configure(
            "Summary.Treeview",
            rowheight=32,
            font=("Inter", 12),
            background=_ROW_ODD,
            fieldbackground=_ROW_ODD,
            foreground=_ROW_FG,
        )
        style.configure(
            "Summary.Treeview.Heading",
            font=("Inter", 11, "bold"),
            background=_HDR_BG,
            foreground=_HDR_FG,
        )
        style.map("Summary.Treeview", background=[("selected", _ROW_SEL)])

        # Wrap in dark frame so empty area below rows matches row background
        sum_container = tk.Frame(parent, bg=_ROW_ODD)
        sum_container.pack(fill="both", expand=True)

        cols = ("BARANGAY", "TOTAL", "✅", "RATE")
        self._sum_tree = ttk.Treeview(
            sum_container, columns=cols, show="headings", style="Summary.Treeview"
        )
        for col in cols:
            self._sum_tree.heading(col, text=col)
        self._sum_tree.column("BARANGAY", width=140, anchor="w")
        self._sum_tree.column("TOTAL",    width=55,  anchor="center")
        self._sum_tree.column("✅",       width=55,  anchor="center")
        self._sum_tree.column("RATE",     width=65,  anchor="center")

        scrolly = ttk.Scrollbar(sum_container, orient="vertical", command=self._sum_tree.yview)
        self._sum_tree.configure(yscrollcommand=scrolly.set)
        self._sum_tree.pack(side="left", fill="both", expand=True)
        scrolly.pack(side="right", fill="y")

        self._sum_tree.tag_configure("oddrow",  background=_ROW_ODD,  foreground=_ROW_FG)
        self._sum_tree.tag_configure("evenrow", background=_ROW_EVEN, foreground=_ROW_FG)
        self._sum_tree.tag_configure(
            "all_row",
            background=_ROW_SEL,
            foreground="#e0f2fe",
            font=("Inter", 11, "bold"),
        )

        self._sum_tree.bind("<<TreeviewSelect>>", self._on_barangay_select)

    # ── Property list table ───────────────────────────────────────────────────

    def _setup_property_table(self, parent):
        # FIX 4 — search row with visible entry + Search button
        search_fr = ctk.CTkFrame(parent, fg_color="transparent")
        search_fr.pack(fill="x", pady=(0, 6))

        self._list_label = ctk.CTkLabel(
            search_fr,
            text="ALL COMPLIANT PROPERTIES",
            font=("Inter", 11, "bold"),
            text_color=ModernTheme.TEXT_GRAY,
            anchor="w",
        )
        self._list_label.pack(side="left")

        # Search button on the right
        ctk.CTkButton(
            search_fr,
            text="🔍 SEARCH",
            command=self._apply_search,
            width=100,
            height=32,
            font=("Inter", 11, "bold"),
            fg_color=_BTN_SEARCH[0],
            hover_color=_BTN_SEARCH[1],
            text_color="white",
            corner_radius=6,
        ).pack(side="right", padx=(6, 0))

        # Visible search entry with explicit border and bg
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_search())
        self._search_entry = ctk.CTkEntry(
            search_fr,
            textvariable=self._search_var,
            placeholder_text="Filter by name or TDN...",
            width=210,
            height=32,
            font=ModernTheme.BODY,
            fg_color=("#f1f5f9", "#0f172a"),
            border_color=("#94a3b8", "#475569"),
            border_width=2,
            text_color=("#1e293b", "#e2e8f0"),
        )
        self._search_entry.pack(side="right")

        # Property treeview — wrap in a dark frame so the empty area below
        # rows matches the row background instead of showing white
        tree_container = tk.Frame(parent, bg=_ROW_ODD)
        tree_container.pack(fill="both", expand=True)

        style = ttk.Style()
        # FIX 1 — softer foreground colour
        style.configure(
            "Compliant.Treeview",
            rowheight=34,
            font=("Inter", 12),
            background=_ROW_ODD,
            fieldbackground=_ROW_ODD,
            foreground=_ROW_FG,
        )
        style.configure(
            "Compliant.Treeview.Heading",
            font=("Inter", 11, "bold"),
            background=_HDR_BG,
            foreground=_HDR_FG,
        )
        style.map("Compliant.Treeview", background=[("selected", _ROW_SEL)])

        cols = ("ID", "TD NUMBER", "OWNER NAME", "BARANGAY", "KIND",
                "TOTAL PAID", "YEARS", "LAST OR", "LAST PAID")
        self._prop_tree = ttk.Treeview(
            tree_container, columns=cols, show="headings", style="Compliant.Treeview"
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

        scrolly = ttk.Scrollbar(tree_container, orient="vertical", command=self._prop_tree.yview)
        self._prop_tree.configure(yscrollcommand=scrolly.set)
        self._prop_tree.pack(side="left", fill="both", expand=True)
        scrolly.pack(side="right", fill="y")

        self._prop_tree.tag_configure("oddrow",  background=_ROW_ODD,  foreground=_ROW_FG)
        self._prop_tree.tag_configure("evenrow", background=_ROW_EVEN, foreground=_ROW_FG)

        # Fill the empty space below data rows with the same dark background
        # so the white gap doesn't appear when there are fewer rows than the
        # visible height of the widget.
        style.configure("Compliant.Treeview", rowheight=34)
        self._prop_tree.configure(style="Compliant.Treeview")

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

        total_props     = sum(r.get("total_properties", 0) for r in summary)
        total_compliant = sum(r.get("compliant_count", 0)  for r in summary)
        total_collected = sum(r[5] for r in props)
        rate = (total_compliant / total_props * 100) if total_props else 0.0

        self._kpi_compliant.configure(text=f"{total_compliant:,}")
        self._kpi_rate.configure(text=f"{rate:.1f}%")
        self._kpi_collected.configure(text=format_curr(total_collected))
        self._kpi_barangays.configure(text=str(len(summary)))

        # Summary table
        for item in self._sum_tree.get_children():
            self._sum_tree.delete(item)

        self._sum_tree.insert(
            "", "end",
            values=("ALL BARANGAYS", total_props, total_compliant, f"{rate:.1f}%"),
            tags=("all_row",),
            iid="__ALL__",
        )
        for i, row in enumerate(sorted(summary, key=lambda r: r.get("barangay", ""))):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self._sum_tree.insert(
                "", "end",
                values=(
                    row.get("barangay", "—"),
                    row.get("total_properties", 0),
                    row.get("compliant_count", 0),
                    f"{row.get('compliance_rate', 0):.1f}%",
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
                if term in str(r[1]).lower()
                or term in str(r[2]).lower()
            ]

        for item in self._prop_tree.get_children():
            self._prop_tree.delete(item)

        for i, r in enumerate(rows):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            display = list(r)
            display[5] = format_curr(r[5])
            display[7] = r[7] if r[7] and str(r[7]) != "None" else "—"
            display[8] = r[8] if r[8] and str(r[8]) != "None" else "—"
            self._prop_tree.insert("", "end", values=display, tags=(tag,))

        brgy = (
            "ALL COMPLIANT PROPERTIES"
            if self._selected_barangay == "ALL"
            else f"COMPLIANT — {self._selected_barangay}"
        )
        self._list_label.configure(text=f"{brgy}  ({len(rows)} shown)")

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
