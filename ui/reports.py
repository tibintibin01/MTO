import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
import threading
import shutil
import os
from theme_manager import ModernTheme
import api_clients.billing_service as billing
import api_clients.property_service as prop
import api_clients.system_service as system
import api_clients.reports_service as reports_api
from ui_components import show_toast
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

        # 🏦 Manage Bank Deposits button
        self.manage_dep_btn = ctk.CTkButton(
            filter_fr, text="🏦 Manage Deposits", command=self.open_manage_deposits,
            font=ModernTheme.BUTTON, fg_color=ModernTheme.PRIMARY
        )
        self.manage_dep_btn.pack(side="left", padx=10)

        # 📊 Export COA RCD button
        self.export_rcd_btn = ctk.CTkButton(
            filter_fr, text="📊 Export COA RCD (Excel)", command=self.open_export_signatories,
            font=ModernTheme.BUTTON, fg_color=ModernTheme.WARNING
        )
        role = str(self.user.get("role", "")).strip().lower() if isinstance(self.user, dict) else ""
        if role == "admin":
            self.export_rcd_btn.pack(side="left", padx=10)

        # ── Pagination state ──────────────────────────────────────────────────
        self._coll_page_size = 100
        self._coll_cursors = [None]   # index 0 = first page cursor (None)
        self._coll_page = 0
        self._coll_has_more = False

        self.coll_table_fr = ctk.CTkFrame(self.collection_tab)
        self.coll_table_fr.pack(fill="both", expand=True, padx=10, pady=(10, 0))

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

        tree_container = tk.Frame(self.coll_table_fr, bg="#1e1e1e")
        tree_container.pack(fill="both", expand=True)

        scrolly = ttk.Scrollbar(tree_container, orient="vertical")
        scrollx = ttk.Scrollbar(tree_container, orient="horizontal")
        scrolly.pack(side="right", fill="y")
        scrollx.pack(side="bottom", fill="x")

        self.coll_tree = ttk.Treeview(
            tree_container, columns=cols, show="headings",
            yscrollcommand=scrolly.set, xscrollcommand=scrollx.set,
        )
        scrolly.configure(command=self.coll_tree.yview)
        scrollx.configure(command=self.coll_tree.xview)

        for col in cols:
            self.coll_tree.heading(col, text=col.upper())
            self.coll_tree.column(col, width=110, anchor="center")
        self.coll_tree.column(tr("reports.collection.table.owner"), width=180, anchor="w")
        self.coll_tree.pack(side="left", fill="both", expand=True)

        self.coll_tree.tag_configure("oddrow",  background="#2b2b2b", foreground="white")
        self.coll_tree.tag_configure("evenrow", background="#333333", foreground="white")

        # ── Pagination bar ────────────────────────────────────────────────────
        pag_fr = ctk.CTkFrame(self.collection_tab, fg_color="transparent")
        pag_fr.pack(fill="x", padx=10, pady=(4, 10))

        self._coll_prev_btn = ctk.CTkButton(
            pag_fr, text="◀  PREVIOUS",
            command=self._coll_prev_page,
            width=120, height=32,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SECONDARY,
            hover_color=ModernTheme.SECONDARY_HOVER,
            state="disabled",
        )
        self._coll_prev_btn.pack(side="left", padx=(0, 8))

        self._coll_page_lbl = ctk.CTkLabel(
            pag_fr, text="Page 1",
            font=("Inter", 11, "bold"),
            text_color=ModernTheme.TEXT_GRAY,
        )
        self._coll_page_lbl.pack(side="left", expand=True)

        self._coll_next_btn = ctk.CTkButton(
            pag_fr, text="NEXT  ▶",
            command=self._coll_next_page,
            width=120, height=32,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SECONDARY,
            hover_color=ModernTheme.SECONDARY_HOVER,
            state="disabled",
        )
        self._coll_next_btn.pack(side="right")

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

        # ── Header with year filter ──────────────────────────────────────────
        top_fr = ctk.CTkFrame(brgy_fr, fg_color="transparent")
        top_fr.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            top_fr,
            text=tr("reports.barangay.title"),
            font=ModernTheme.H3,
            text_color=ModernTheme.PRIMARY,
        ).pack(side="left")

        # Year filter + export buttons — right side
        filter_fr = ctk.CTkFrame(top_fr, fg_color="transparent")
        filter_fr.pack(side="right")

        ctk.CTkLabel(
            filter_fr, text="As of Year:", font=ModernTheme.BODY, text_color="gray"
        ).pack(side="left", padx=(0, 8))

        curr_y = datetime.now().year
        self.brgy_year_cb = ctk.CTkComboBox(
            filter_fr,
            values=["All Years"] + [str(y) for y in range(curr_y - 10, curr_y + 1)],
            width=130,
            command=lambda _: self.generate_barangay_receivables(),
        )
        self.brgy_year_cb.set(str(curr_y))
        self.brgy_year_cb.pack(side="left", padx=(0, 8))



        ctk.CTkButton(
            filter_fr,
            text=f"🔄 {tr('reports.barangay.btn_refresh')}",
            command=self.generate_barangay_receivables,
            width=160,
            height=35,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.SECONDARY,
        ).pack(side="left", padx=(0, 6))

        # ── Export buttons ───────────────────────────────────────────────────
        ctk.CTkButton(
            filter_fr,
            text="📄 Export PDF",
            command=self._export_brgy_pdf,
            width=130,
            height=35,
            font=ModernTheme.BUTTON,
            fg_color="#c0392b",
            hover_color="#962d22",
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            filter_fr,
            text="📊 Export Excel",
            command=self._export_brgy_excel,
            width=140,
            height=35,
            font=ModernTheme.BUTTON,
            fg_color="#1a7431",
            hover_color="#145a27",
        ).pack(side="left")

        # Info banner explaining cumulative logic
        info_fr = ctk.CTkFrame(brgy_fr, fg_color=("#1a2634", "#1a2634"), corner_radius=8)
        info_fr.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            info_fr,
            text=(
                "ℹ️  Cumulative receivables: includes all unpaid balances from prior years "
                "carried forward into the selected year."
            ),
            font=("Segoe UI", 10),
            text_color="#8b949e",
            anchor="w",
        ).pack(padx=14, pady=8, anchor="w")

        # ── Table ────────────────────────────────────────────────────────────
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

        scrolly = ttk.Scrollbar(t_container, orient="vertical", command=self.brgy_tree.yview)
        self.brgy_tree.configure(yscrollcommand=scrolly.set)
        self.brgy_tree.pack(side="left", fill="both", expand=True)
        scrolly.pack(side="right", fill="y")

        self.brgy_tree.tag_configure("oddrow", background="#2b2b2b", foreground="white")
        self.brgy_tree.tag_configure("evenrow", background="#333333", foreground="white")

        # ── Summary footer ───────────────────────────────────────────────────
        self.brgy_summary = ctk.CTkFrame(brgy_fr, height=50, fg_color="#2c3e50", corner_radius=8)
        self.brgy_summary.pack(fill="x", pady=(15, 0))

        self.brgy_year_lbl = ctk.CTkLabel(
            self.brgy_summary,
            text="",
            font=("Segoe UI", 10),
            text_color="#8b949e",
        )
        self.brgy_year_lbl.pack(side="left", padx=20, pady=10)

        self.brgy_total_lbl = ctk.CTkLabel(
            self.brgy_summary,
            text=tr("reports.barangay.total").replace("{value}", "P 0.00"),
            font=ModernTheme.H3,
            text_color="white",
        )
        self.brgy_total_lbl.pack(side="right", padx=30, pady=10)

    def generate_collection_report(self):
        # Reset to page 1 on a new search
        self._coll_cursors = [None]
        self._coll_page = 0
        self._coll_has_more = False
        self._coll_load_page()

    def _coll_load_page(self):
        month = self.month_cb.get()
        year = self.year_cb.get()
        cursor = self._coll_cursors[self._coll_page]
        self._show_loading()

        def worker():
            try:
                data = billing.get_report_details(
                    month, year,
                    limit=self._coll_page_size,
                    cursor=cursor,
                )
                self.container.after(0, lambda: self._update_coll_table(data))
            except Exception as e:
                self.container.after(
                    0, lambda err=e: messagebox.showerror("Error", str(err))
                )
            finally:
                self.container.after(0, self._hide_loading)

        threading.Thread(target=worker, daemon=True).start()

    def _coll_next_page(self):
        if self._coll_has_more:
            self._coll_page += 1
            self._coll_load_page()

    def _coll_prev_page(self):
        if self._coll_page > 0:
            self._coll_page -= 1
            self._coll_load_page()

    def _update_coll_table(self, data):
        for item in self.coll_tree.get_children():
            self.coll_tree.delete(item)

        # data may be a dict with pagination info or a plain list (legacy)
        if isinstance(data, dict):
            items = data.get("items", [])
            next_cursor = data.get("next_cursor")
            has_more = data.get("has_more", False)
        else:
            items = data or []
            next_cursor = None
            has_more = False

        if not items and self._coll_page == 0:
            self._coll_page_lbl.configure(text="No results")
            self._coll_prev_btn.configure(state="disabled")
            self._coll_next_btn.configure(state="disabled")
            return

        # Store next cursor for the next page
        self._coll_has_more = has_more
        if has_more and next_cursor is not None:
            if len(self._coll_cursors) <= self._coll_page + 1:
                self._coll_cursors.append(next_cursor)
            else:
                self._coll_cursors[self._coll_page + 1] = next_cursor

        for i, row in enumerate(items):
            formatted_row = list(row)
            if len(formatted_row) > 6:
                formatted_row[6] = format_curr(formatted_row[6])
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.coll_tree.insert("", "end", values=formatted_row, tags=(tag,))

        # Update pagination controls
        page_num = self._coll_page + 1
        count = len(items)
        self._coll_page_lbl.configure(
            text=f"Page {page_num}  ·  {count} records shown"
        )
        self._coll_prev_btn.configure(
            state="normal" if self._coll_page > 0 else "disabled"
        )
        self._coll_next_btn.configure(
            state="normal" if has_more else "disabled"
        )

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
        selected = self.brgy_year_cb.get()
        year = None if selected == "All Years" else int(selected)

        def worker():
            try:
                data = prop.get_receivables_by_barangay(year=year)
                self.container.after(0, lambda: self._update_brgy_table(data, year))
            except Exception as e:
                self.container.after(
                    0, lambda err=e: messagebox.showerror("Error", str(err))
                )
            finally:
                self.container.after(0, self._hide_loading)

        threading.Thread(target=worker, daemon=True).start()

    def _update_brgy_table(self, data, year=None):
        for item in self.brgy_tree.get_children():
            self.brgy_tree.delete(item)

        year_label = f"Cumulative as of {year}" if year else "All-time totals"
        self.brgy_year_lbl.configure(text=year_label)

        if not data:
            self.brgy_total_lbl.configure(text=tr("reports.barangay.total").replace("{value}", "P 0.00"))
            return

        grand_total = 0.0
        for i, row in enumerate(data):
            f_row = list(row)
            try:
                receiv_val = float(row[6] or 0)
                grand_total += receiv_val
            except Exception:
                pass

            if len(f_row) >= 7:
                for idx in range(1, 7):
                    f_row[idx] = format_curr(f_row[idx])

            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.brgy_tree.insert("", "end", values=f_row, tags=(tag,))

        self.brgy_total_lbl.configure(
            text=tr("reports.barangay.total").replace("{value}", f"P {grand_total:,.2f}")
        )

    # ── Export helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _open_file(path):
        """Open a file with the default OS application after saving."""
        try:
            import subprocess, sys
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.call(["open", path])
            else:
                subprocess.call(["xdg-open", path])
        except Exception:
            pass

    def _export_with_feedback(self, btn, worker_fn):
        """Run worker_fn in a thread; show progress on btn, then open the result."""
        original_text = btn.cget("text")
        btn.configure(text="⏳ Generating...", state="disabled")

        def _run():
            try:
                path = worker_fn()
                # Ask where to save
                def _save():
                    dest = filedialog.asksaveasfilename(
                        title="Save Report",
                        initialfile=os.path.basename(path),
                        defaultextension=os.path.splitext(path)[1],
                        filetypes=[
                            ("PDF files", "*.pdf"),
                            ("Excel files", "*.xlsx"),
                            ("All files", "*.*"),
                        ],
                    )
                    if dest:
                        shutil.copy2(path, dest)
                        if messagebox.askyesno("Export Successful",
                                               f"Report saved to:\n{dest}\n\nOpen it now?"):
                            self._open_file(dest)
                    btn.configure(text=original_text, state="normal")

                self.container.after(0, _save)
            except Exception as exc:
                self.container.after(
                    0, lambda e=exc: (
                        messagebox.showerror("Export Failed", str(e)),
                        btn.configure(text=original_text, state="normal"),
                    )
                )

        threading.Thread(target=_run, daemon=True).start()

    def _export_brgy_pdf(self):
        selected = self.brgy_year_cb.get()
        year = None if selected == "All Years" else int(selected)
        btn = None
        # Walk the widget tree to find our PDF button
        try:
            tab_children = self.barangay_tab.winfo_children()
            for w in tab_children:
                for w2 in w.winfo_children():
                    for w3 in w2.winfo_children():
                        if hasattr(w3, "cget") and "Export PDF" in str(w3.cget("text")):
                            btn = w3
        except Exception:
            pass
        if btn is None:
            btn = ctk.CTkButton(self.barangay_tab, text="")

        self._export_with_feedback(
            btn,
            lambda: billing.download_receivables_by_barangay_pdf(year=year)
        )

    def _export_brgy_excel(self):
        selected = self.brgy_year_cb.get()
        year_str = selected if selected != "All Years" else "All"
        btn = None
        try:
            tab_children = self.barangay_tab.winfo_children()
            for w in tab_children:
                for w2 in w.winfo_children():
                    for w3 in w2.winfo_children():
                        if hasattr(w3, "cget") and "Export Excel" in str(w3.cget("text")):
                            btn = w3
        except Exception:
            pass
        if btn is None:
            btn = ctk.CTkButton(self.barangay_tab, text="")

        self._export_with_feedback(
            btn,
            lambda: billing.export_report_excel("receivables_by_barangay", year=year_str),
        )

    def open_manage_deposits(self):
        start_date, end_date = self.get_selected_date_range()
        ManageDepositsModal(self.container, start_date, end_date)

    def open_export_signatories(self):
        default_officer = self.user.get("full_name", "") if isinstance(self.user, dict) else ""
        SignatoriesModal(self.container, default_officer, self.export_coa_rcd)

    def export_coa_rcd(self, liquidating_officer, treasurer):
        start_date, end_date = self.get_selected_date_range()
        self._show_loading()
        
        self.export_rcd_btn.configure(state="disabled", text="⏳ Exporting...")
        
        def worker():
            try:
                path = reports_api.download_coa_rcd(
                    start_date=start_date,
                    end_date=end_date,
                    liquidating_officer=liquidating_officer,
                    treasurer=treasurer
                )
                
                def save_file():
                    filename = f"COA_RCD_{start_date}_to_{end_date}.xlsx"
                    dest = filedialog.asksaveasfilename(
                        title="Save COA RCD Report",
                        initialfile=filename,
                        defaultextension=".xlsx",
                        filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")]
                    )
                    if dest:
                        shutil.copy2(path, dest)
                        if messagebox.askyesno("Export Successful", f"COA RCD report saved to:\n{dest}\n\nOpen it now?"):
                            self._open_file(dest)
                            
                self.container.after(0, save_file)
            except Exception as e:
                self.container.after(0, lambda: messagebox.showerror("Export Failed", str(e)))
            finally:
                self.container.after(0, lambda: [
                    self._hide_loading(),
                    self.export_rcd_btn.configure(state="normal", text="📊 Export COA RCD (Excel)")
                ])
                
        threading.Thread(target=worker, daemon=True).start()

    def get_selected_date_range(self):
        month = self.month_cb.get()
        year = self.year_cb.get()
        
        import calendar
        now = datetime.now()
        y = int(year) if year != "All" else now.year
        
        if month == "All":
            start_date = f"{y}-01-01"
            end_date = f"{y}-12-31"
        else:
            m = int(month)
            _, last_day = calendar.monthrange(y, m)
            start_date = f"{y}-{m:02d}-01"
            end_date = f"{y}-{m:02d}-{last_day:02d}"
            
        return start_date, end_date


class SignatoriesModal(ctk.CTkToplevel):
    def __init__(self, parent, default_officer, callback):
        super().__init__(parent)
        self.title("RCD Signatories")
        self.geometry("400x320")
        self.resizable(False, False)
        self.callback = callback
        
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)
        
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-400)//2}+{(sh-320)//2}")
        
        self.setup_ui(default_officer)
        
    def setup_ui(self, default_officer):
        self.configure(fg_color="#1a1a2e")
        ctk.CTkFrame(self, fg_color=ModernTheme.PRIMARY, height=4, corner_radius=0).pack(fill="x")
        
        body = ctk.CTkFrame(self, fg_color="#1a1a2e")
        body.pack(fill="both", expand=True, padx=30, pady=24)
        
        ctk.CTkLabel(body, text="COA RCD Signatories", font=("Segoe UI", 14, "bold"), text_color="white").pack(anchor="w", pady=(0, 6))
        ctk.CTkLabel(body, text="Enter the names of the signing officers for this report.", font=("Segoe UI", 11), text_color="#a0aec0").pack(anchor="w", pady=(0, 16))
        
        ctk.CTkLabel(body, text="Liquidating Officer", font=("Segoe UI", 11, "bold"), text_color="#a0aec0").pack(anchor="w")
        self.officer_ent = ctk.CTkEntry(body, height=36, fg_color="#2d2d4e", border_color="#4a4a6e", text_color="white")
        self.officer_ent.insert(0, default_officer)
        self.officer_ent.pack(fill="x", pady=(4, 12))
        
        ctk.CTkLabel(body, text="Municipal Treasurer", font=("Segoe UI", 11, "bold"), text_color="#a0aec0").pack(anchor="w")
        self.treasurer_ent = ctk.CTkEntry(body, height=36, fg_color="#2d2d4e", border_color="#4a4a6e", text_color="white")
        self.treasurer_ent.pack(fill="x", pady=(4, 16))
        
        btn_fr = ctk.CTkFrame(body, fg_color="transparent")
        btn_fr.pack(fill="x")
        
        ctk.CTkButton(btn_fr, text="Cancel", command=self.destroy,
                      fg_color="#2d2d4e", hover_color="#3d3d5e", text_color="#a0aec0",
                      height=38, width=100, font=("Segoe UI", 11, "bold"), corner_radius=8).pack(side="left")
                      
        ctk.CTkButton(btn_fr, text="Export Excel", command=self.on_export,
                      fg_color=ModernTheme.SUCCESS, hover_color="#1e7e34", text_color="white",
                      height=38, width=150, font=("Segoe UI", 11, "bold"), corner_radius=8).pack(side="right")
                      
    def on_export(self):
        officer = self.officer_ent.get().strip()
        treasurer = self.treasurer_ent.get().strip()
        if not officer or not treasurer:
            messagebox.showerror("Error", "Both fields are required.")
            return
        self.callback(officer, treasurer)
        self.destroy()


class ManageDepositsModal(ctk.CTkToplevel):
    def __init__(self, parent, start_date: str, end_date: str):
        super().__init__(parent)
        self.title("Manage Bank Deposits")
        self.geometry("750x550")
        self.resizable(False, False)
        self.start_date = start_date
        self.end_date = end_date
        
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)
        
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-750)//2}+{(sh-550)//2}")
        
        self.setup_ui()
        self.refresh_deposits()
        
    def setup_ui(self):
        self.configure(fg_color="#1a1a2e")
        ctk.CTkFrame(self, fg_color=ModernTheme.PRIMARY, height=4, corner_radius=0).pack(fill="x")
        
        main_fr = ctk.CTkFrame(self, fg_color="transparent")
        main_fr.pack(fill="both", expand=True, padx=20, pady=20)
        
        title_fr = ctk.CTkFrame(main_fr, fg_color="transparent")
        title_fr.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(title_fr, text="🏦 Bank Deposit Slips", font=("Segoe UI", 16, "bold"), text_color="white").pack(anchor="w")
        ctk.CTkLabel(title_fr, text=f"Date Range: {self.start_date} to {self.end_date}", font=("Segoe UI", 11), text_color="#a0aec0").pack(anchor="w")
        
        content_fr = ctk.CTkFrame(main_fr, fg_color="transparent")
        content_fr.pack(fill="both", expand=True, pady=10)
        content_fr.grid_columnconfigure(0, weight=1)
        content_fr.grid_columnconfigure(1, weight=2)
        content_fr.grid_rowconfigure(0, weight=1)
        
        # --- LEFT: FORM ---
        form_fr = ctk.CTkFrame(content_fr, fg_color="#252538", corner_radius=8)
        form_fr.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        
        ctk.CTkLabel(form_fr, text="Log New Deposit", font=("Segoe UI", 12, "bold"), text_color="white").pack(anchor="w", padx=15, pady=(15, 10))
        
        ctk.CTkLabel(form_fr, text="Date Deposited (YYYY-MM-DD)", font=("Segoe UI", 10), text_color="#a0aec0").pack(anchor="w", padx=15)
        self.date_ent = ctk.CTkEntry(form_fr, height=32, fg_color="#1a1a2e", border_color="#4a4a6e", text_color="white")
        self.date_ent.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self.date_ent.pack(fill="x", padx=15, pady=(4, 10))
        
        ctk.CTkLabel(form_fr, text="Bank Name / Branch", font=("Segoe UI", 10), text_color="#a0aec0").pack(anchor="w", padx=15)
        self.bank_ent = ctk.CTkEntry(form_fr, placeholder_text="e.g. Landbank", height=32, fg_color="#1a1a2e", border_color="#4a4a6e", text_color="white")
        self.bank_ent.pack(fill="x", padx=15, pady=(4, 10))
        
        ctk.CTkLabel(form_fr, text="Reference / Slip No.", font=("Segoe UI", 10), text_color="#a0aec0").pack(anchor="w", padx=15)
        self.ref_ent = ctk.CTkEntry(form_fr, placeholder_text="e.g. DS-12345", height=32, fg_color="#1a1a2e", border_color="#4a4a6e", text_color="white")
        self.ref_ent.pack(fill="x", padx=15, pady=(4, 10))
        
        ctk.CTkLabel(form_fr, text="Amount (₱)", font=("Segoe UI", 10), text_color="#a0aec0").pack(anchor="w", padx=15)
        self.amt_ent = ctk.CTkEntry(form_fr, placeholder_text="e.g. 50000.00", height=32, fg_color="#1a1a2e", border_color="#4a4a6e", text_color="white")
        self.amt_ent.pack(fill="x", padx=15, pady=(4, 15))
        
        ctk.CTkButton(form_fr, text="➕ Save Deposit", command=self.save_deposit,
                      fg_color=ModernTheme.PRIMARY, hover_color="#2c6ea1", text_color="white",
                      height=36, font=("Segoe UI", 11, "bold")).pack(fill="x", padx=15, pady=(0, 15))
        
        # --- RIGHT: TABLE ---
        table_container = ctk.CTkFrame(content_fr, fg_color="#252538", corner_radius=8)
        table_container.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        
        ctk.CTkLabel(table_container, text="Existing Deposits", font=("Segoe UI", 12, "bold"), text_color="white").pack(anchor="w", padx=15, pady=(15, 10))
        
        tree_fr = ctk.CTkFrame(table_container, fg_color="transparent")
        tree_fr.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        
        scrolly = ttk.Scrollbar(tree_fr, orient="vertical")
        scrolly.pack(side="right", fill="y")
        
        cols = ("ID", "Date", "Bank", "Ref No", "Amount", "Logged By")
        self.tree = ttk.Treeview(tree_fr, columns=cols, show="headings", yscrollcommand=scrolly.set, height=10)
        scrolly.configure(command=self.tree.yview)
        
        self.tree.heading("ID", text="ID")
        self.tree.heading("Date", text="DATE")
        self.tree.heading("Bank", text="BANK")
        self.tree.heading("Ref No", text="REF NO")
        self.tree.heading("Amount", text="AMOUNT")
        self.tree.heading("Logged By", text="BY")
        
        self.tree.column("ID", width=40, anchor="center")
        self.tree.column("Date", width=90, anchor="center")
        self.tree.column("Bank", width=120, anchor="w")
        self.tree.column("Ref No", width=90, anchor="center")
        self.tree.column("Amount", width=100, anchor="right")
        self.tree.column("Logged By", width=80, anchor="center")
        
        self.tree.pack(fill="both", expand=True)
        
        self.tree.tag_configure("oddrow", background="#2b2b2b", foreground="white")
        self.tree.tag_configure("evenrow", background="#333333", foreground="white")
        
        btn_fr = ctk.CTkFrame(table_container, fg_color="transparent")
        btn_fr.pack(fill="x", padx=15, pady=(0, 15))
        
        ctk.CTkButton(btn_fr, text="🗑️ Delete Selected", command=self.delete_deposit,
                      fg_color="#c0392b", hover_color="#962d22", text_color="white",
                      width=150, height=32, font=("Segoe UI", 11, "bold")).pack(side="right")

        close_fr = ctk.CTkFrame(main_fr, fg_color="transparent")
        close_fr.pack(fill="x", pady=(10, 0))
        ctk.CTkButton(close_fr, text="Close", command=self.destroy,
                      fg_color="#2d2d4e", hover_color="#3d3d5e", text_color="#a0aec0",
                      width=100, height=36, font=("Segoe UI", 11, "bold"), corner_radius=8).pack(side="right")
                      
    def refresh_deposits(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        def worker():
            try:
                data = reports_api.list_bank_deposits(self.start_date, self.end_date)
                self.after(0, lambda: self._update_table(data))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Failed to load deposits: {e}"))
                
        threading.Thread(target=worker, daemon=True).start()
        
    def _update_table(self, data):
        for i, d in enumerate(data):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.tree.insert("", "end", values=(
                d["id"],
                d["date_deposited"],
                d["bank_name"],
                d["reference_number"],
                format_curr(d["amount"]),
                d["deposited_by"]
            ), tags=(tag,))
            
    def save_deposit(self):
        date_val = self.date_ent.get().strip()
        bank_val = self.bank_ent.get().strip()
        ref_val = self.ref_ent.get().strip()
        amt_val = self.amt_ent.get().strip()
        
        if not date_val or not bank_val or not ref_val or not amt_val:
            messagebox.showerror("Error", "All fields are required.")
            return
            
        try:
            amt = float(amt_val)
            if amt <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Error", "Amount must be a positive number.")
            return
            
        try:
            datetime.strptime(date_val, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Error", "Invalid Date format. Use YYYY-MM-DD.")
            return
            
        def worker():
            try:
                reports_api.log_bank_deposit(date_val, bank_val, ref_val, amt)
                self.after(0, lambda: [
                    self.bank_ent.delete(0, tk.END),
                    self.ref_ent.delete(0, tk.END),
                    self.amt_ent.delete(0, tk.END),
                    self.refresh_deposits(),
                    show_toast(self.winfo_toplevel(), "Deposit logged successfully.", type="success")
                ])
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
                
        threading.Thread(target=worker, daemon=True).start()
        
    def delete_deposit(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showerror("Error", "Please select a deposit slip to delete.")
            return
            
        vals = self.tree.item(sel[0])["values"]
        dep_id = int(vals[0])
        bank = vals[2]
        ref = vals[3]
        
        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete deposit Ref {ref} to {bank}?"):
            return
            
        def worker():
            try:
                reports_api.delete_bank_deposit(dep_id)
                self.after(0, lambda: [
                    self.refresh_deposits(),
                    show_toast(self.winfo_toplevel(), "Deposit deleted.", type="info")
                ])
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
                
        threading.Thread(target=worker, daemon=True).start()

