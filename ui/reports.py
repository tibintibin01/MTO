import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
import threading
import shutil
import os
from theme_manager import ModernTheme
import api_clients.billing_service as billing
import api_clients.system_service as system
import api_clients.reports_service as reports_api
from ui_components import show_toast
from ui.empty_state import EmptyTableState, show_empty_content
from ui.report_workspace_state import ReportViewState, period_label, captured_time_label
from utils import format_curr, tr
from utils.rcd_metadata import philippine_report_date, resolve_rcd_metadata
from utils.report_labels import (
    RECEIVABLES_COVERAGE_LABEL,
    RECEIVABLES_COVERAGE_HELP,
    RECORDED_CREDIT_BALANCE_LABEL,
    RECORDED_CREDIT_BALANCE_HELP,
)


def report_export_dialog_options(path, export_format):
    """Offer only the format selected by the button, without converting bytes."""
    formats = {
        "excel": (".xlsx", "Excel workbook (*.xlsx)", "*.xlsx"),
        "pdf": (".pdf", "PDF document (*.pdf)", "*.pdf"),
    }
    try:
        extension, label, pattern = formats[str(export_format).strip().lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported report export format: {export_format}") from exc

    source_name = os.path.basename(path)
    stem, source_extension = os.path.splitext(source_name)
    if source_extension.lower() != extension:
        raise ValueError(
            f"The generated report does not match the selected {label.split(' (', 1)[0]} format. "
            "No file was saved."
        )
    return {
        "title": f"Save Report as {label.split(' (', 1)[0]}",
        "initialfile": f"{stem}{extension}",
        "defaultextension": extension,
        "filetypes": [(label, pattern)],
    }


class ReportsPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self._last_reconciliation_payload = None
        self._report_generations = {}
        self._report_pending = set()
        self._workspace_states = {}
        self._workspace_labels = {}
        self._workspace_exports = {}
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

        # A stable, equal-width report navigator is easier to scan than the
        # compact default segmented control.
        self.tabview = ctk.CTkTabview(
            self.container,
            anchor="nw",
            corner_radius=0,
            border_width=0,
            fg_color="transparent",
            segmented_button_fg_color="#334155",
            segmented_button_selected_color=ModernTheme.PRIMARY_SURFACE,
            segmented_button_selected_hover_color="#0284c7",
            segmented_button_unselected_color="#334155",
            segmented_button_unselected_hover_color="#475569",
            text_color="#f8fafc",
        )
        self.tabview.pack(fill="both", expand=True)

        self.collection_tab = self.tabview.add(tr("reports.tabs.collection"))
        self.receivables_tab = self.tabview.add(tr("reports.tabs.receivables"))
        self.barangay_tab = self.tabview.add(tr("reports.tabs.barangay"))
        self.reconciliation_tab = self.tabview.add(tr("reports.tabs.reconciliation"))

        # Keep all report destinations visually balanced and comfortably clickable.
        self.tabview._segmented_button.configure(
            width=760,
            height=42,
            corner_radius=6,
            border_width=1,
            font=("Inter", 12, "bold"),
            dynamic_resizing=False,
        )
        self.container.bind("<Configure>", self._fit_report_navigation)

        self.setup_collection_tab()
        self.setup_receivables_tab()
        self.setup_barangay_tab()
        self.setup_reconciliation_tab()

    def _fit_report_navigation(self, event):
        width = max(300, int(event.width / self.tabview._get_widget_scaling()) - 20)
        button = self.tabview._segmented_button
        if button.cget("width") != width:
            button.configure(width=width)

    @staticmethod
    def _wrap_report_label(label, width, minimum=120):
        target = max(minimum, int(width / label._get_widget_scaling()))
        if label.cget("wraplength") != target:
            label.configure(wraplength=target)

    def _selected_filters(self, kind):
        if kind == "collection":
            search = self.coll_search.get().strip() if hasattr(self, "coll_search") else ""
            order = self.coll_order_cb.get() if hasattr(self, "coll_order_cb") else "Newest posted"
            return (self.month_cb.get(), self.year_cb.get(), search, order)
        widget = getattr(self, {"receivables": "receiv_year_cb", "barangay": "brgy_year_cb",
                  "reconciliation": "recon_year_cb"}[kind])
        return (widget.get(),)

    def _workspace_register(self, kind, parent, widgets, exports):
        state = ReportViewState(selected=self._selected_filters(kind))
        self._workspace_states[kind] = state
        self._workspace_exports[kind] = exports
        label = ctk.CTkLabel(parent, text="", anchor="w", justify="left",
                             font=ModernTheme.BODY_SMALL, wraplength=900)
        label.pack(fill="x", pady=(0, 10))
        label.bind("<Configure>", lambda e: self._wrap_report_label(label, e.width))
        self._workspace_labels[kind] = label
        for widget in widgets:
            variable = tk.StringVar(value=widget.get())
            if isinstance(widget, ctk.CTkComboBox):
                widget.configure(variable=variable)
            else:
                widget.configure(textvariable=variable)
            variable.trace_add("write", lambda *args, k=kind: self._workspace_filters_changed(k))
            widget._workspace_variable = variable
        self._sync_workspace(kind)

    def _workspace_filters_changed(self, kind):
        state = self._workspace_states[kind]
        filters = self._selected_filters(kind)
        if filters != state.selected:
            self._report_generations[kind] = self._report_generations.get(kind, 0) + 1
            state.select(filters)
            if kind == "collection":
                self._coll_loading = False
                self._coll_prev_btn.configure(state="disabled")
                self._coll_next_btn.configure(state="disabled")
        self._sync_workspace(kind)

    def _sync_workspace(self, kind):
        state = getattr(self, "_workspace_states", {}).get(kind)
        if state is None:
            return
        descriptions = {
            "ready": "Ready · Select filters, then generate the report.",
            "loading": "Loading · Reading a consistent report snapshot…",
            "empty": "No matches · Try another reporting period or search.",
            "error": "Unable to load · Check the connection, then try again.",
            "changed": "Filters changed · Refresh required. Figures below still belong to the loaded period.",
            "loaded": "Loaded",
        }
        text = descriptions[state.status]
        if state.loaded:
            text += "\n" + period_label(kind, state.loaded)
            if state.captured_at:
                text += " · Captured " + captured_time_label(state.captured_at)
        self._workspace_labels[kind].configure(text=text, text_color=("#92400e", "#fbbf24") if state.status in ("changed", "error") else (ModernTheme.TEXT_SUB_LIGHT, ModernTheme.TEXT_SUB_DARK))
        for button in self._workspace_exports[kind]:
            if not getattr(button, "_workspace_export_busy", False):
                valid = state.can_export and not (kind == "collection" and state.selected[2])
                button.configure(state="normal" if valid else "disabled")

    def _workspace_accept(self, kind, report, render, has_rows=True):
        state = getattr(self, "_workspace_states", {}).get(kind)
        if state is not None:
            if not state.accept(state.selected, report, has_rows=has_rows):
                return
        render()
        self._sync_workspace(kind)

    def _workspace_fail(self, kind):
        state = getattr(self, "_workspace_states", {}).get(kind)
        if state is not None:
            state.fail()
            self._sync_workspace(kind)

    def _workspace_export_allowed(self, kind):
        state = getattr(self, "_workspace_states", {}).get(kind)
        if state is None:
            return True  # Legacy test/view callers without workspace controls.
        if state.selected != self._selected_filters(kind) or not state.can_export or (kind == "collection" and state.selected[2]):
            messagebox.showinfo("Refresh required", "Load the report for the selected filters before exporting.")
            return False
        return True

    def _view_credit_accounts(self, kind, barangay=None):
        state = self._workspace_states.get(kind)
        if not state or not state.can_export or not state.payload.get("credit_scope"):
            messagebox.showinfo("Refresh required", "Load the report before reviewing credit accounts.")
            return
        from ui.report_credit_accounts import CreditAccountsWindow
        year = state.payload.get("report_year")
        self._configure_report_tree_style("CreditReport.Treeview")
        CreditAccountsWindow(self.container, year, state.payload["credit_scope"], barangay)

    def _selected_barangay_credits(self):
        selection = self.brgy_tree.selection()
        if not selection:
            messagebox.showinfo("Select a barangay", "Select a barangay row to review its credit accounts.")
            return
        values = self.brgy_tree.item(selection[0], "values")
        self._view_credit_accounts("barangay", values[0])

    def _sort_barangays(self, column):
        rows = getattr(self, "_brgy_rows", [])
        self._brgy_sort_reverse = not getattr(self, "_brgy_sort_reverse", False)
        ordered = sorted(rows, key=lambda row: str(row[0]).casefold() if column == 0 else float(row[column] or 0), reverse=self._brgy_sort_reverse)
        self._update_brgy_table(ordered, getattr(self, "_brgy_loaded_year", None))

    def _toggle_barangay_columns(self):
        self._brgy_all_columns = not self._brgy_all_columns
        cols = self._brgy_columns
        self.brgy_tree.configure(displaycolumns=cols if self._brgy_all_columns else (cols[0], cols[2], cols[5], cols[6], cols[7]))
        self.brgy_columns_btn.configure(text="Key columns" if self._brgy_all_columns else "Show all columns")

    @staticmethod
    def _metric_cards(parent, entries):
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="x", pady=(0, 12))
        grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="report_metrics")
        labels = []
        for column, (title, value, subtitle) in enumerate(entries):
            card = ctk.CTkFrame(grid, corner_radius=10, border_width=1,
                                fg_color=(ModernTheme.CARD_LIGHT, ModernTheme.CARD_DARK),
                                border_color=(ModernTheme.BORDER_LIGHT, ModernTheme.BORDER_DARK))
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 4, 0 if column == 2 else 4))
            ctk.CTkLabel(card, text=title, anchor="w", font=ModernTheme.BODY_SMALL).pack(fill="x", padx=12, pady=(12, 4))
            label = ctk.CTkLabel(card, text=value, anchor="w", font=("Inter", 20, "bold"))
            label.pack(fill="x", padx=12)
            sub = ctk.CTkLabel(card, text=subtitle, anchor="w", justify="left", font=ModernTheme.BODY_SMALL, wraplength=230)
            sub.pack(fill="x", padx=12, pady=(4, 12))
            sub.bind("<Configure>", lambda e, w=sub: ReportsPage._wrap_report_label(w, e.width))
            labels.append(label)
        return labels

    @staticmethod
    def _disclosure_frame(parent, title):
        wrapper = ctk.CTkFrame(parent, fg_color="transparent")
        wrapper.pack(fill="x", pady=(0, 12))
        body = ctk.CTkFrame(wrapper, fg_color="transparent")
        def toggle():
            if body.winfo_manager():
                body.pack_forget()
                button.configure(text="+ " + title)
            else:
                body.pack(fill="x", pady=(10, 0))
                button.configure(text="− " + title)
        button = ctk.CTkButton(wrapper, text="+ " + title, command=toggle,
                               anchor="w", fg_color=ModernTheme.PRIMARY_SURFACE,
                               hover_color=ModernTheme.PRIMARY_SURFACE_HOVER)
        button.pack(fill="x")
        return body

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

    def _start_report_request(self, kind):
        generations = getattr(self, "_report_generations", {})
        self._report_generations = generations
        token = generations.get(kind, 0) + 1
        generations[kind] = token
        pending = getattr(self, "_report_pending", set())
        self._report_pending = pending
        pending.add((kind, token))
        state = getattr(self, "_workspace_states", {}).get(kind)
        if state is not None:
            state.begin(self._selected_filters(kind))
            self._sync_workspace(kind)
        self._show_loading()
        return token

    def _post_report_result(self, kind, token, callback):
        def apply():
            if self._report_generations.get(kind) == token and getattr(self.container, "winfo_exists", lambda: True)():
                callback()
        try:
            self.container.after(0, apply)
        except (tk.TclError, RuntimeError):
            pass  # Page closed while the read-only request was in flight.

    def _schedule_report_finish(self, kind, token):
        try:
            self.container.after(0, lambda: self._finish_report_request(kind, token))
        except (tk.TclError, RuntimeError):
            self._report_pending.discard((kind, token))

    def _finish_report_request(self, kind, token):
        self._report_pending.discard((kind, token))
        if kind == "collection" and self._report_generations.get(kind) == token:
            self._coll_loading = False
        if not self._report_pending:
            self._hide_loading()

    def _show_collection_error(self, error):
        self._workspace_fail("collection")
        for label in getattr(self, "coll_metrics", []):
            label.configure(text="—")
        for name in ("_coll_prev_btn", "_coll_next_btn"):
            if hasattr(self, name):
                getattr(self, name).configure(state="disabled")
        if hasattr(self, "_coll_page_lbl"):
            self._coll_page_lbl.configure(text="Unavailable")
        for item in self.coll_tree.get_children():
            self.coll_tree.delete(item)
        self._coll_has_more = False
        self.coll_empty_state.show(
            "No current results. Check the connection and generate the report again.",
            title="Unable to load collections",
        )
        messagebox.showerror("Error", str(error))

    def _show_barangay_error(self, error):
        self._workspace_fail("barangay")
        if hasattr(self, "brgy_year_lbl"):
            self.brgy_year_lbl.configure(text="No current report")
            self.brgy_total_lbl.configure(text="Totals unavailable")
        for item in self.brgy_tree.get_children():
            self.brgy_tree.delete(item)
        self.brgy_empty_state.show(
            "No current results. Check the connection and refresh the report again.",
            title="Unable to load barangay report",
        )
        messagebox.showerror("Error", str(error))

    @staticmethod
    def _show_content_error(parent, error, title):
        for child in parent.winfo_children():
            child.destroy()
        show_empty_content(parent, "Check the connection and try again.", title=title)
        messagebox.showerror("Error", str(error))

    def _show_reconciliation_error(self, error):
        self._workspace_fail("reconciliation")
        self._last_reconciliation_payload = None
        self.recon_export_excel_btn.configure(state="disabled")
        self.recon_export_pdf_btn.configure(state="disabled")
        self._show_content_error(
            self.recon_content, error, "Unable to load reconciliation"
        )

    def _bind_enter(self, widget, callback):
        def submit(_event=None):
            callback()
            return "break"

        try:
            widget.bind("<Return>", submit)
            widget.bind("<KP_Enter>", submit)
        except Exception:
            pass

        inner_entry = getattr(widget, "_entry", None)
        if inner_entry is not None:
            try:
                inner_entry.bind("<Return>", submit)
                inner_entry.bind("<KP_Enter>", submit)
            except Exception:
                pass

    @staticmethod
    def _configure_report_tree_style(style_name):
        """Apply the shared modern table appearance used by operational reports."""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            style_name,
            rowheight=34,
            font=("Inter", 11),
            background="#0f172a",
            fieldbackground="#0f172a",
            foreground="#e2e8f0",
            borderwidth=0,
            bordercolor="#334155",
            lightcolor="#334155",
            darkcolor="#334155",
            relief="flat",
        )
        style.configure(
            f"{style_name}.Heading",
            font=("Inter", 10, "bold"),
            background="#334155",
            foreground="#f8fafc",
            borderwidth=0,
            bordercolor="#475569",
            lightcolor="#475569",
            darkcolor="#475569",
            relief="flat",
            padding=(8, 8),
        )
        style.map(
            style_name,
            background=[("selected", "#0284c7")],
            foreground=[("selected", "#ffffff")],
        )
        style.map(f"{style_name}.Heading", background=[("active", "#475569")])
        for scrollbar_style in ("Report.Vertical.TScrollbar", "Report.Horizontal.TScrollbar"):
            style.configure(
                scrollbar_style,
                gripcount=0,
                background="#475569",
                darkcolor="#475569",
                lightcolor="#475569",
                troughcolor="#0f172a",
                bordercolor="#0f172a",
                arrowcolor="#cbd5e1",
                relief="flat",
            )
        if ctk.get_appearance_mode() == "Light":
            style.configure(style_name, background="#ffffff", fieldbackground="#ffffff", foreground="#1e293b")

    def setup_collection_tab(self):
        collection_fr = ctk.CTkFrame(self.collection_tab, fg_color="transparent")
        collection_fr.pack(fill="both", expand=True, padx=10, pady=10)

        title_fr = ctk.CTkFrame(collection_fr, fg_color="transparent")
        title_fr.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            title_fr, text="OFFICIAL COLLECTION REGISTER",
            font=ModernTheme.H3, text_color=ModernTheme.PRIMARY,
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_fr,
            text="Payment and receipt activity for the selected reporting period",
            font=ModernTheme.BODY_SMALL, text_color=ModernTheme.TEXT_GRAY,
        ).pack(anchor="w", pady=(2, 0))

        filter_fr = ctk.CTkFrame(
            collection_fr,
            fg_color=(ModernTheme.CARD_LIGHT, ModernTheme.CARD_DARK),
            corner_radius=8, border_width=1,
            border_color=(ModernTheme.BORDER_LIGHT, ModernTheme.BORDER_DARK),
        )
        filter_fr.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            filter_fr, text="MONTH", font=ModernTheme.BUTTON_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(side="left", padx=(14, 6), pady=10)
        self.month_cb = ctk.CTkComboBox(
            filter_fr, values=["All"] + [f"{m:02d}" for m in range(1, 13)],
            width=120, height=34, font=ModernTheme.BODY_SMALL,
        )
        self.month_cb.set(datetime.now().strftime("%m"))
        self.month_cb.pack(side="left", padx=(0, 12), pady=10)

        ctk.CTkLabel(
            filter_fr, text="YEAR", font=ModernTheme.BUTTON_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(side="left", padx=(0, 6), pady=10)
        current_year = datetime.now().year
        self.year_cb = ctk.CTkComboBox(
            filter_fr,
            values=["All"] + [str(y) for y in range(current_year - 10, current_year + 3)],
            width=130, height=34, font=ModernTheme.BODY_SMALL,
        )
        self.year_cb.set(str(current_year))
        self.year_cb.pack(side="left", padx=(0, 12), pady=10)
        self._bind_enter(self.month_cb, self.generate_collection_report)
        self._bind_enter(self.year_cb, self.generate_collection_report)

        ctk.CTkButton(
            filter_fr, text=tr("reports.collection.btn_generate"),
            command=self.generate_collection_report,
            font=ModernTheme.BUTTON_SMALL, fg_color=ModernTheme.PRIMARY_SURFACE,
            hover_color=ModernTheme.PRIMARY_SURFACE_HOVER, height=34, width=110,
        ).pack(side="left", padx=(0, 8), pady=10)

        actions_fr = ctk.CTkFrame(collection_fr, fg_color="transparent")
        actions_fr.pack(fill="x", pady=(0, 10))
        search_fr = ctk.CTkFrame(actions_fr, fg_color="transparent")
        search_fr.grid(row=0, column=0, sticky="w")
        utility_fr = ctk.CTkFrame(actions_fr, fg_color="transparent")
        utility_fr.grid(row=0, column=1, sticky="e")
        actions_fr.grid_columnconfigure(0, weight=1)
        def fit_actions(event):
            narrow = event.width / actions_fr._get_widget_scaling() < 700
            if getattr(actions_fr, "_workspace_narrow", None) != narrow:
                actions_fr._workspace_narrow = narrow
                utility_fr.grid(row=1 if narrow else 0, column=0 if narrow else 1, sticky="e", pady=(8, 0) if narrow else 0)
        actions_fr.bind("<Configure>", fit_actions)
        self.coll_search = ctk.CTkEntry(search_fr, placeholder_text="Search OR, TD or owner", width=210, height=34)
        self.coll_search.pack(side="left", padx=(0, 8))
        self._bind_enter(self.coll_search, self.generate_collection_report)
        self.coll_order_cb = ctk.CTkComboBox(search_fr, values=["Newest posted", "Oldest posted"], width=120, height=34, state="readonly")
        self.coll_order_cb.set("Newest posted")
        self.coll_order_cb.pack(side="left")
        self._bind_enter(self.coll_order_cb, self.generate_collection_report)

        self.manage_dep_btn = ctk.CTkButton(
            utility_fr, text="MANAGE DEPOSITS", command=self.open_manage_deposits,
            font=ModernTheme.BUTTON_SMALL, fg_color=ModernTheme.SECONDARY,
            hover_color=ModernTheme.SECONDARY_HOVER, height=34, width=150,
        )
        self.manage_dep_btn.pack(side="right", padx=(8, 0))

        self.export_rcd_btn = ctk.CTkButton(
            utility_fr, text="EXPORT COA RCD", command=self.open_export_signatories,
            font=ModernTheme.BUTTON_SMALL, fg_color=ModernTheme.WARNING,
            height=34, width=150,
        )
        role = str(self.user.get("role", "")).strip().lower() if isinstance(self.user, dict) else ""
        if role == "admin":
            self.export_rcd_btn.pack(side="right", padx=(8, 0))

        self._workspace_register("collection", collection_fr, (self.month_cb, self.year_cb, self.coll_search, self.coll_order_cb), (self.export_rcd_btn,))
        if role == "admin":
            daily_rcd_fr = ctk.CTkFrame(collection_fr, fg_color="transparent")
            daily_rcd_fr.pack(fill="x", pady=(0, 8))
            ctk.CTkButton(daily_rcd_fr, text="DAILY RCD (100 / 200)", command=self.open_daily_rcd, width=205, height=34).pack(side="left", padx=(0, 12))
            ctk.CTkLabel(daily_rcd_fr, text="Automatic collections by OR date and registered booklet owner.", wraplength=430, justify="left").pack(side="left")
        self.coll_metrics = self._metric_cards(collection_fr, (("Recorded cash", "—", "Whole selected period / search"), ("Receipts", "—", "Whole selected period / search"), ("This page", "—", "Up to 100 receipts; chosen posted order")))
        ctk.CTkLabel(collection_fr, text="COA RCD exports the whole period. Clear the search before exporting it.", anchor="w", font=ModernTheme.BODY_SMALL).pack(fill="x", pady=(0, 8))

        self._coll_page_size = 100
        self._coll_cursors = [None]
        self._coll_page = 0
        self._coll_has_more = False

        self.coll_table_fr = ctk.CTkFrame(
            collection_fr, fg_color="#0f172a", corner_radius=8,
            border_width=1, border_color=ModernTheme.BORDER_DARK,
        )
        self.coll_table_fr.pack(fill="both", expand=True)
        self._configure_report_tree_style("Collection.Treeview")

        cols = (
            tr("reports.collection.table.date"),
            tr("reports.collection.table.or"),
            tr("reports.collection.table.td"),
            tr("reports.collection.table.owner"),
            tr("reports.collection.table.kind"),
            tr("reports.collection.table.year"),
            tr("reports.collection.table.amount"),
            tr("reports.collection.table.posted"),
        )
        tree_container = tk.Frame(self.coll_table_fr, bg="#0f172a", bd=0, highlightthickness=0)
        tree_container.pack(fill="both", expand=True, padx=1, pady=1)
        scrolly = ttk.Scrollbar(
            tree_container, orient="vertical", style="Report.Vertical.TScrollbar"
        )
        scrollx = ttk.Scrollbar(
            tree_container, orient="horizontal", style="Report.Horizontal.TScrollbar"
        )
        scrolly.pack(side="right", fill="y")
        scrollx.pack(side="bottom", fill="x")
        self.coll_tree = ttk.Treeview(
            tree_container, columns=cols, show="headings",
            yscrollcommand=scrolly.set, xscrollcommand=scrollx.set,
            style="Collection.Treeview",
        )
        scrolly.configure(command=self.coll_tree.yview)
        scrollx.configure(command=self.coll_tree.xview)
        for col in cols:
            self.coll_tree.heading(col, text=col.upper())
            self.coll_tree.column(col, width=110, anchor="center")
        self.coll_tree.column(tr("reports.collection.table.owner"), width=180, anchor="w")
        self.coll_tree.column(tr("reports.collection.table.amount"), anchor="e")
        self.coll_tree.pack(side="left", fill="both", expand=True)
        self.coll_tree.tag_configure("oddrow", background="#162032", foreground="#e2e8f0")
        self.coll_tree.tag_configure("evenrow", background="#1e293b", foreground="#f8fafc")
        self.coll_empty_state = EmptyTableState(
            tree_container,
            "Select a month and year, then generate the collection report.",
            title="Ready to generate",
        )

        pag_fr = ctk.CTkFrame(
            collection_fr,
            fg_color=(ModernTheme.CARD_LIGHT, ModernTheme.CARD_DARK),
            corner_radius=8, border_width=1,
            border_color=(ModernTheme.BORDER_LIGHT, ModernTheme.BORDER_DARK),
        )
        pag_fr.pack(fill="x", pady=(8, 0))
        self._coll_prev_btn = ctk.CTkButton(
            pag_fr, text="PREVIOUS", command=self._coll_prev_page,
            width=120, height=32, font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SECONDARY, hover_color=ModernTheme.SECONDARY_HOVER,
            state="disabled",
        )
        self._coll_prev_btn.pack(side="left", padx=10, pady=8)
        self._coll_page_lbl = ctk.CTkLabel(
            pag_fr, text="Page 1", font=("Inter", 11, "bold"),
            text_color=ModernTheme.TEXT_GRAY,
        )
        self._coll_page_lbl.pack(side="left", expand=True)
        self._coll_next_btn = ctk.CTkButton(
            pag_fr, text="NEXT", command=self._coll_next_page,
            width=120, height=32, font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SECONDARY, hover_color=ModernTheme.SECONDARY_HOVER,
            state="disabled",
        )
        self._coll_next_btn.pack(side="right", padx=10, pady=8)

    def setup_receivables_tab(self):
        receiv_fr = ctk.CTkFrame(self.receivables_tab, fg_color="transparent")
        receiv_fr.pack(fill="both", expand=True, padx=10, pady=10)
        ctk.CTkLabel(receiv_fr, text="RPT RECEIVABLES SUMMARY", font=ModernTheme.H3, text_color=ModernTheme.PRIMARY).pack(anchor="w")
        ctk.CTkLabel(receiv_fr, text="Year-end balances, applied payments and separate recorded credits", font=ModernTheme.BODY_SMALL).pack(anchor="w", pady=(2, 10))

        filter_fr = ctk.CTkFrame(receiv_fr, fg_color="transparent")
        filter_fr.pack(fill="x", pady=(0, 12))

        curr_y = datetime.now().year
        self.receiv_year_cb = ctk.CTkComboBox(
            filter_fr, values=[str(y) for y in range(curr_y - 10, curr_y + 3)]
        )
        self.receiv_year_cb.set(str(curr_y))
        self.receiv_year_cb.pack(side="left", padx=10)
        self._bind_enter(self.receiv_year_cb, self.generate_receivables_report)

        ctk.CTkButton(
            filter_fr, text=tr("reports.receivables.btn_load"), command=self.generate_receivables_report,
            font=ModernTheme.BUTTON, fg_color=ModernTheme.PRIMARY_SURFACE, height=34
        ).pack(side="left", padx=(8, 0))

        self.receiv_export_excel_btn = ctk.CTkButton(
            filter_fr,
            text="EXPORT EXCEL",
            command=self._export_receivables_excel,
            font=ModernTheme.BUTTON,
            fg_color="#047857",
            height=34,
            width=130,
        )
        self.receiv_export_excel_btn.pack(side="right", padx=(8, 0))

        self.receiv_export_brgy_btn = ctk.CTkButton(
            filter_fr,
            text="BARANGAY PDF",
            command=self._export_receivables_barangay_pdf,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.SECONDARY,
            height=34,
            width=130,
        )
        # Barangay PDF belongs in the Barangay report, not the fiscal summary.
        self._workspace_register("receivables", receiv_fr, (self.receiv_year_cb,), (self.receiv_export_excel_btn,))

        self.receiv_content = ctk.CTkScrollableFrame(receiv_fr, fg_color="transparent")
        self.receiv_content.pack(fill="both", expand=True)
        show_empty_content(
            self.receiv_content,
            "Select a year, then load the receivables report.",
            title="Ready to generate",
        )

    def setup_barangay_tab(self):
        brgy_fr = ctk.CTkFrame(self.barangay_tab, fg_color="transparent")
        brgy_fr.pack(fill="both", expand=True, padx=10, pady=10)

        top_fr = ctk.CTkFrame(brgy_fr, fg_color="transparent")
        top_fr.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            top_fr,
            text=tr("reports.barangay.title"),
            font=ModernTheme.H3,
            text_color=ModernTheme.PRIMARY,
        ).pack(anchor="w")
        ctk.CTkLabel(
            top_fr,
            text="Jurisdiction-level assessment, collection, and outstanding balances",
            font=ModernTheme.BODY_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(anchor="w", pady=(2, 0))

        filter_fr = ctk.CTkFrame(
            brgy_fr,
            fg_color=(ModernTheme.CARD_LIGHT, ModernTheme.CARD_DARK),
            corner_radius=8,
            border_width=1,
            border_color=(ModernTheme.BORDER_LIGHT, ModernTheme.BORDER_DARK),
        )
        filter_fr.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            filter_fr, text="AS OF YEAR", font=ModernTheme.BUTTON_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(side="left", padx=(14, 8), pady=10)

        curr_y = datetime.now().year
        self.brgy_year_cb = ctk.CTkComboBox(
            filter_fr,
            values=["All Years"] + [str(y) for y in range(curr_y - 10, curr_y + 1)],
            width=130,
            height=34,
            font=ModernTheme.BODY_SMALL,
        )
        self.brgy_year_cb.set(str(curr_y))
        self.brgy_year_cb.pack(side="left", padx=(0, 10), pady=10)
        self._bind_enter(self.brgy_year_cb, self.generate_barangay_receivables)

        ctk.CTkButton(
            filter_fr,
            text=tr("reports.barangay.btn_refresh").upper(),
            command=self.generate_barangay_receivables,
            width=160, height=34, font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.PRIMARY_SURFACE,
            hover_color=ModernTheme.PRIMARY_SURFACE_HOVER,
        ).pack(side="left", padx=(0, 8), pady=10)

        export_fr = ctk.CTkFrame(brgy_fr, fg_color="transparent")
        export_fr.pack(fill="x", pady=(0, 8))
        self.brgy_export_pdf_btn = ctk.CTkButton(
            export_fr,
            text="EXPORT PDF",
            command=self._export_brgy_pdf,
            width=125, height=34, font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SECONDARY,
        )
        self.brgy_export_pdf_btn.pack(side="right", padx=(0, 12), pady=10)

        self.brgy_export_excel_btn = ctk.CTkButton(
            export_fr,
            text="EXPORT EXCEL",
            command=self._export_brgy_excel,
            width=135, height=34, font=ModernTheme.BUTTON_SMALL,
            fg_color="#047857",
        )
        self.brgy_export_excel_btn.pack(side="right", padx=(0, 8), pady=10)
        self._workspace_register("barangay", brgy_fr, (self.brgy_year_cb,), (self.brgy_export_pdf_btn, self.brgy_export_excel_btn))

        credit_actions = ctk.CTkFrame(brgy_fr, fg_color="transparent")
        credit_actions.pack(fill="x", pady=(0, 8))
        ctk.CTkButton(credit_actions, text="View all credit accounts", command=lambda: self._view_credit_accounts("barangay"), fg_color=ModernTheme.PRIMARY_SURFACE).pack(side="left")
        ctk.CTkButton(credit_actions, text="Selected barangay credits", command=self._selected_barangay_credits, fg_color=ModernTheme.PRIMARY_SURFACE).pack(side="left", padx=8)
        self.brgy_columns_btn = ctk.CTkButton(credit_actions, text="Show all columns", command=self._toggle_barangay_columns, width=125, fg_color=ModernTheme.SECONDARY)
        self.brgy_columns_btn.pack(side="right")

        basis_body = self._disclosure_frame(brgy_fr, "Reporting basis and credit explanation")
        info_fr = ctk.CTkFrame(
            basis_body, fg_color=("#e0f2fe", "#132238"), corner_radius=8,
            border_width=1, border_color=("#bae6fd", "#1e3a5f"),
        )
        info_fr.pack(fill="x", pady=(0, 10))
        brgy_note = ctk.CTkLabel(
            info_fr,
            text=(
                "Selected year: balances at December 31, matching the fiscal summary. "
                "All available billing years are included. All Years includes all recorded payment dates.\n"
                f"{RECORDED_CREDIT_BALANCE_LABEL}: {RECORDED_CREDIT_BALANCE_HELP}"
            ),
            font=ModernTheme.BODY_SMALL,
            text_color=("#0369a1", "#7dd3fc"),
            anchor="w",
            justify="left",
            wraplength=900,
        )
        brgy_note.pack(fill="x", padx=14, pady=9, anchor="w")
        info_fr.bind("<Configure>", lambda event: brgy_note.configure(wraplength=max(240, event.width - 28)))

        t_container = ctk.CTkFrame(
            brgy_fr, fg_color="#0f172a", corner_radius=8,
            border_width=1, border_color=ModernTheme.BORDER_DARK,
        )
        t_container.pack(fill="both", expand=True)
        self._configure_report_tree_style("BarangayReport.Treeview")

        cols = (
            tr("reports.barangay.table.barangay"),
            tr("reports.barangay.table.assessed"),
            tr("reports.barangay.table.due"),
            tr("reports.barangay.table.penalty"),
            tr("reports.barangay.table.discount"),
            tr("reports.barangay.table.collected"),
            tr("reports.barangay.table.receivable"),
            RECORDED_CREDIT_BALANCE_LABEL,
        )
        tree_host = tk.Frame(t_container, bg="#0f172a", bd=0, highlightthickness=0)
        tree_host.pack(fill="both", expand=True, padx=1, pady=1)
        self.brgy_tree = ttk.Treeview(
            tree_host, columns=cols, show="headings",
            style="BarangayReport.Treeview",
        )
        for col in cols:
            self.brgy_tree.heading(col, text=col.upper())
            self.brgy_tree.column(col, width=120, anchor="e")

        self.brgy_tree.column(cols[0], width=180, anchor="w")
        self.brgy_tree.column(cols[-1], width=200, minwidth=180)
        self._brgy_columns = cols
        self._brgy_all_columns = False
        self.brgy_tree.configure(displaycolumns=(cols[0], cols[2], cols[5], cols[6], cols[7]))
        self.brgy_tree.bind("<Double-1>", lambda e: self._selected_barangay_credits())
        self.brgy_tree.bind("<Return>", lambda e: self._selected_barangay_credits())
        for index, col in enumerate(cols):
            self.brgy_tree.heading(col, command=lambda i=index: self._sort_barangays(i))

        scrolly = ttk.Scrollbar(
            tree_host, orient="vertical", command=self.brgy_tree.yview,
            style="Report.Vertical.TScrollbar",
        )
        scrollx = ttk.Scrollbar(
            tree_host, orient="horizontal", command=self.brgy_tree.xview,
            style="Report.Horizontal.TScrollbar",
        )
        self.brgy_tree.configure(yscrollcommand=scrolly.set, xscrollcommand=scrollx.set)
        self.brgy_tree.pack(side="left", fill="both", expand=True)
        scrolly.pack(side="right", fill="y")
        scrollx.pack(side="bottom", fill="x")

        self.brgy_tree.tag_configure("oddrow", background="#162032", foreground="#e2e8f0")
        self.brgy_tree.tag_configure("evenrow", background="#1e293b", foreground="#f8fafc")
        self.brgy_empty_state = EmptyTableState(
            tree_host,
            "Select an as-of year, then refresh the barangay report.",
            title="Ready to generate",
        )

        self.brgy_summary = ctk.CTkFrame(
            brgy_fr, height=58,
            fg_color=(ModernTheme.CARD_LIGHT, ModernTheme.CARD_DARK),
            corner_radius=8, border_width=1,
            border_color=(ModernTheme.BORDER_LIGHT, ModernTheme.BORDER_DARK),
        )
        self.brgy_summary.pack(fill="x", pady=(8, 0))

        self.brgy_year_lbl = ctk.CTkLabel(
            self.brgy_summary,
            text="",
            font=ModernTheme.BODY_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        )
        self.brgy_year_lbl.pack(anchor="w", padx=16, pady=(8, 2))

        self.brgy_total_lbl = ctk.CTkLabel(
            self.brgy_summary,
            text=tr("reports.barangay.total").replace("{value}", "P 0.00"),
            font=("Inter", 16, "bold"),
            text_color=ModernTheme.PRIMARY,
            wraplength=700, justify="right",
        )
        self.brgy_total_lbl.pack(fill="x", padx=16, pady=(0, 8))
        self.brgy_summary.bind("<Configure>", lambda e: self._wrap_report_label(self.brgy_total_lbl, e.width - 32))

    def setup_reconciliation_tab(self):
        rec_fr = ctk.CTkFrame(self.reconciliation_tab, fg_color="transparent")
        rec_fr.pack(fill="both", expand=True, padx=10, pady=10)

        top_fr = ctk.CTkFrame(rec_fr, fg_color="transparent")
        top_fr.pack(fill="x", pady=(0, 12))

        title_fr = ctk.CTkFrame(top_fr, fg_color="transparent")
        title_fr.pack(fill="x", expand=True)
        ctk.CTkLabel(
            title_fr,
            text="INTER-DEPARTMENT RECONCILIATION",
            font=ModernTheme.H3,
            text_color=ModernTheme.PRIMARY,
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_fr,
            text="COA-ready check: assessed levy should equal collections plus remaining receivables.",
            font=("Inter", 11),
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(anchor="w", pady=(2, 0))

        controls = ctk.CTkFrame(top_fr, fg_color="transparent")
        controls.pack(fill="x", pady=(10, 0))
        curr_y = datetime.now().year
        self.recon_year_cb = ctk.CTkComboBox(
            controls,
            values=[str(y) for y in range(curr_y - 10, curr_y + 3)],
            width=120,
        )
        self.recon_year_cb.set(str(curr_y))
        self.recon_year_cb.pack(side="left", padx=(0, 8))
        self._bind_enter(self.recon_year_cb, self.generate_reconciliation_report)
        ctk.CTkButton(
            controls,
            text="LOAD CHECK",
            command=self.generate_reconciliation_report,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.PRIMARY_SURFACE,
            height=34,
            width=130,
        ).pack(side="left")
        self.recon_export_excel_btn = ctk.CTkButton(
            controls,
            text="EXPORT EXCEL",
            command=self._export_reconciliation_excel,
            font=ModernTheme.BUTTON,
            fg_color="#047857",
            height=34,
            width=130,
            state="disabled",
        )
        self.recon_export_excel_btn.pack(side="left", padx=(8, 0))
        self.recon_export_pdf_btn = ctk.CTkButton(
            controls,
            text="EXPORT PDF",
            command=self._export_reconciliation_pdf,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.SECONDARY,
            height=34,
            width=110,
            state="disabled",
        )
        self.recon_export_pdf_btn.pack(side="left", padx=(8, 0))
        self._workspace_register("reconciliation", rec_fr, (self.recon_year_cb,), (self.recon_export_excel_btn, self.recon_export_pdf_btn))

        self.recon_content = ctk.CTkScrollableFrame(
            rec_fr,
            fg_color="transparent",
            scrollbar_button_color="#334155",
            scrollbar_button_hover_color="#475569",
        )
        self.recon_content.pack(fill="both", expand=True)
        show_empty_content(
            self.recon_content,
            "Select a fiscal year, then load the reconciliation check.",
            title="Ready to generate",
        )

    def generate_reconciliation_report(self):
        year = self.recon_year_cb.get()
        token = self._start_report_request("reconciliation")

        def worker():
            try:
                report = billing.get_receivables_report(year, diagnostics=True)
                self._post_report_result("reconciliation", token, lambda: self._workspace_accept("reconciliation", report, lambda: self._update_reconciliation(
                    report["summary"], report["barangays"], report["metrics"], report["diagnostics"])))
            except Exception as e:
                self._post_report_result("reconciliation", token, lambda err=e: self._show_reconciliation_error(err))
            finally:
                self._schedule_report_finish("reconciliation", token)

        threading.Thread(target=worker, daemon=True).start()

    def _update_reconciliation(self, data, brgy_rows=None, metrics=None, diagnostics=None):
        for child in self.recon_content.winfo_children():
            child.destroy()

        if not data:
            self._last_reconciliation_payload = None
            self.recon_export_excel_btn.configure(state="disabled")
            self.recon_export_pdf_btn.configure(state="disabled")
            show_empty_content(
                self.recon_content,
                "Try another fiscal year or check that reconciliation data is available.",
                title="No reconciliation data",
            )
            return

        year = data.get("report_year", self.recon_year_cb.get())
        beginning = float(data.get("beginning_receivable", 0) or 0)
        current_net = float(data.get("current_year_net_collectible", data.get("current_year_assessment", 0)) or 0)
        current_penalty = float(data.get("current_year_penalty", 0) or 0)
        current_discount = float(data.get("current_year_discount", 0) or 0)
        adjustments = float(data.get("adjustments", 0) or 0)
        collections = float(data.get("collections", 0) or 0)
        calendar_applicable_collections = float(data.get("calendar_applicable_collections", collections) or 0)
        prepaid_current_year = float(data.get("prepaid_current_year", 0) or 0)
        future_year_prepayments = float(data.get("future_year_prepayments", 0) or 0)
        unpaid = float(data.get("ending_receivable", 0) or 0)
        levy = beginning + current_net + adjustments
        brgy_rows = brgy_rows or []
        metrics = metrics or {}
        diagnostics = diagnostics or {}
        self._last_reconciliation_payload = self._build_reconciliation_payload(
            data, brgy_rows, metrics, diagnostics
        )
        self.recon_export_excel_btn.configure(state="normal")
        self.recon_export_pdf_btn.configure(state="normal")
        assessor = metrics.get("assessor", {})
        treasury = metrics.get("treasury", {})
        delinquency = metrics.get("delinquency", {})

        # The reconciliation equation must use the same basis on all sides:
        # beginning receivable + net current collectible + adjustments = collections + ending receivable.
        current_levy = float(assessor.get("current_year_levy", data.get("current_year_levy", current_net)) or 0)
        current_penalty = float(assessor.get("current_year_penalty", current_penalty) or 0)
        current_discount = float(assessor.get("current_year_discount", current_discount) or 0)
        current_net = float(assessor.get("current_year_net_collectible", current_net) or 0)
        levy = beginning + current_net + adjustments
        total_collectible = levy
        cash_collected_this_year = float(treasury.get("cash_collected_this_year", collections) or 0)
        calendar_applicable_collections = float(treasury.get("calendar_applicable_collections", calendar_applicable_collections) or 0)
        prepaid_current_year = float(treasury.get("prepaid_current_year", prepaid_current_year) or 0)
        future_year_prepayments = float(treasury.get("future_year_prepayments", future_year_prepayments) or 0)
        treasury_total = float(treasury.get("total_collected", data.get("applied_collections", calendar_applicable_collections + prepaid_current_year)) or 0)
        expected_unpaid = float(data.get("expected_ending_receivable", unpaid) or 0)
        tracker_total = float(delinquency.get("total_unpaid", unpaid) or 0)
        current_receivable = float(delinquency.get("current_year_receivables", 0) or 0)
        prior_receivable = float(delinquency.get("prior_year_receivables", max(tracker_total - current_receivable, 0)) or 0)
        delinquency_total = float(delinquency.get("total_unpaid", prior_receivable + current_receivable) or 0)
        equation_variance = total_collectible - (treasury_total + delinquency_total)
        tracker_variance = float(diagnostics.get("tracker_variance", tracker_total - expected_unpaid) or 0)
        raw_tracker_variance = float(diagnostics.get("raw_tracker_variance", tracker_variance) or 0)
        variance = equation_variance if abs(equation_variance) > 0.005 else tracker_variance
        abs_variance = max(abs(equation_variance), abs(tracker_variance))
        balanced = self._build_reconciliation_payload(data, brgy_rows, metrics, diagnostics)["balanced"]
        collection_rate = (treasury_total / total_collectible * 100) if total_collectible > 0 else 0
        delinquency_rate = (expected_unpaid / total_collectible * 100) if total_collectible > 0 else 0

        def money(value):
            return f"P {float(value or 0):,.2f}"

        def stat_card(parent, col, label, value, color, subtitle):
            card = ctk.CTkFrame(
                parent,
                fg_color=("#e2e8f0", "#111827"),
                corner_radius=8,
                border_width=1,
                border_color=("#cbd5e1", "#243244"),
            )
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0 if col == 2 else 8))
            ctk.CTkLabel(card, text=label.upper(), font=("Inter", 10, "bold"), text_color=ModernTheme.TEXT_GRAY).pack(anchor="w", padx=16, pady=(14, 4))
            ctk.CTkLabel(card, text=value, font=("Inter", 22, "bold"), text_color=color).pack(anchor="w", padx=16)
            ctk.CTkLabel(card, text=subtitle, font=("Inter", 10), text_color=ModernTheme.TEXT_GRAY, wraplength=310, justify="left").pack(anchor="w", padx=16, pady=(4, 14))
            return card

        header = ctk.CTkFrame(self.recon_content, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            header,
            text=f"FISCAL YEAR {year} RECONCILIATION CHECK",
            font=ModernTheme.H2,
            text_color=ModernTheme.PRIMARY,
        ).pack(side="left")
        status_color = ModernTheme.SUCCESS if balanced else ModernTheme.DANGER
        status_text = "BALANCED" if balanced else "NEEDS REVIEW"
        ctk.CTkLabel(header, text=status_text, font=ModernTheme.H3, text_color=status_color).pack(side="right")

        def field_row(parent, label, value, color="#f8fafc"):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=(0, 10))
            ctk.CTkLabel(row, text=label, font=("Inter", 10, "bold"), text_color="#bfdbfe", anchor="w").pack(anchor="w")
            box = ctk.CTkFrame(row, fg_color="#0f172a", corner_radius=7, border_width=1, border_color="#334155")
            box.pack(fill="x", pady=(4, 0))
            ctk.CTkLabel(box, text=value, font=("Consolas", 13, "bold"), text_color=color, anchor="w").pack(fill="x", padx=12, pady=8)

        def department_card(parent, col, badge, title, accent, rows, footer_label, footer_value):
            card = ctk.CTkFrame(parent, fg_color=("#e2e8f0", "#111827"), corner_radius=8, border_width=1, border_color=("#cbd5e1", "#243244"))
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0 if col == 2 else 8))
            head = ctk.CTkFrame(card, fg_color="transparent")
            head.pack(fill="x", padx=16, pady=(14, 8))
            ctk.CTkLabel(head, text=badge, font=("Inter", 10, "bold"), text_color=accent, fg_color="#0f2747", corner_radius=5).pack(anchor="w")
            ctk.CTkLabel(card, text=title, font=("Inter", 16, "bold"), text_color="#f8fafc").pack(anchor="w", padx=16, pady=(0, 12))
            for label, value, color in rows:
                field_row(card, label, value, color)
            ctk.CTkFrame(card, height=1, fg_color="#243244").pack(fill="x", pady=(8, 0))
            footer = ctk.CTkFrame(card, fg_color="transparent")
            footer.pack(fill="x", padx=16, pady=14)
            ctk.CTkLabel(footer, text=footer_label, font=("Inter", 11), text_color="#bfdbfe").pack(side="left")
            ctk.CTkLabel(footer, text=footer_value, font=("Consolas", 13, "bold"), text_color=accent).pack(side="right")

        grid = ctk.CTkFrame(self.recon_content, fg_color="transparent")
        grid.pack(fill="x", pady=(0, 14))
        grid.grid_columnconfigure((0, 1, 2), weight=1)
        stat_card(grid, 0, "Total Collectible (A)", money(total_collectible), ModernTheme.PRIMARY, f"Beginning {money(beginning)} + net current {money(current_net)} + adjustments {money(adjustments)}")
        stat_card(grid, 1, "Collections / Credits (B)", money(treasury_total), ModernTheme.SUCCESS, f"Cash applied {money(calendar_applicable_collections)} + prepayments {money(prepaid_current_year)}")
        stat_card(grid, 2, "Ending Receivable (C)", money(delinquency_total), ModernTheme.DANGER, f"Receivable rate: {delinquency_rate:.1f}%")
        ctk.CTkButton(self.recon_content, text="View recorded credit accounts (separate from debt)", command=lambda: self._view_credit_accounts("reconciliation"), fg_color=ModernTheme.PRIMARY_SURFACE).pack(anchor="w", pady=(0, 12))
        department_body = self._disclosure_frame(self.recon_content, "Department working papers")
        department_grid = ctk.CTkFrame(department_body, fg_color="transparent")
        department_grid.pack(fill="x", pady=(0, 14))
        department_grid.grid_columnconfigure((0, 1, 2), weight=1)
        department_card(
            department_grid,
            0,
            "Assessor's office",
            "Tax levy data",
            ModernTheme.PRIMARY,
            (
                ("Total assessed value", money(assessor.get("total_assessed_value", 0)), "#f8fafc"),
                ("Basic tax rate", f"{float(assessor.get('tax_rate_percent', 0) or 0):.2f}%", "#f8fafc"),
                ("Total RPT rate", f"{float(assessor.get('total_tax_rate_percent', 0) or 0):.2f}%", "#f8fafc"),
                ("No. of taxable properties", f"{int(assessor.get('taxable_properties', 0) or 0):,}", "#f8fafc"),
                ("Penalties / interest", money(current_penalty), "#f59e0b"),
                ("Discounts", f"- {money(current_discount)}", "#22c55e"),
            ),
            "Current year levy",
            money(current_levy),
        )
        department_card(
            department_grid,
            1,
            "Treasurer's office",
            "Collection data",
            ModernTheme.SUCCESS,
            (
                ("Basic principal applied / credited", money(treasury.get("basic_tax_collected", 0)), ModernTheme.SUCCESS),
                ("Cash collected this fiscal year", money(cash_collected_this_year), "#f8fafc"),
                ("Current-year tax prepaid before year", money(prepaid_current_year), "#38bdf8"),
                ("Future prepayments excluded", money(future_year_prepayments), "#f59e0b"),
                ("No. of accounts paid", f"{int(treasury.get('accounts_paid', 0) or 0):,}", "#f8fafc"),
                ("No. of partial payments", f"{int(treasury.get('partial_payments', 0) or 0):,}", "#f8fafc"),
            ),
            "Applied collections / credits",
            money(treasury_total),
        )
        department_card(
            department_grid,
            2,
            "RPT tracker",
            "Delinquency data",
            ModernTheme.DANGER,
            (
                ("Prior-year receivables", money(prior_receivable), ModernTheme.DANGER),
                ("Current year receivables", money(current_receivable), "#f59e0b"),
                ("No. of delinquent accounts", f"{int(delinquency.get('delinquent_accounts', 0) or 0):,}", "#f8fafc"),
                ("Penalties and interest", money(delinquency.get("penalties_interest", 0)), "#f8fafc"),
            ),
            "Ending receivable",
            money(delinquency_total),
        )
        equation = ctk.CTkFrame(
            self.recon_content,
            fg_color=("#dbeafe", "#070b1a"),
            corner_radius=8,
            border_width=1,
            border_color=("#93c5fd", "#1e3a8a"),
        )
        equation.pack(fill="x", pady=(0, 14), padx=0)

        equation_top = ctk.CTkFrame(equation, fg_color="transparent")
        equation_top.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            equation_top,
            text="RECONCILIATION EQUATION",
            font=("Inter", 10, "bold"),
            text_color="#93a4c7",
        ).pack(side="left")
        ctk.CTkLabel(
            equation_top,
            text="Total collectible should equal collections plus ending receivable",
            font=("Inter", 10),
            text_color="#bfdbfe",
        ).pack(side="right")

        formula = ctk.CTkFrame(equation, fg_color="transparent")
        formula.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(
            formula,
            text=f"{money(total_collectible)}",
            font=("Consolas", 16, "bold"),
            text_color=ModernTheme.PRIMARY,
        ).pack(side="left")
        ctk.CTkLabel(formula, text="  =  ", font=("Inter", 15, "bold"), text_color="#93a4c7").pack(side="left")
        ctk.CTkLabel(
            formula,
            text=f"{money(treasury_total)}",
            font=("Consolas", 16, "bold"),
            text_color=ModernTheme.SUCCESS,
        ).pack(side="left")
        ctk.CTkLabel(formula, text="  +  ", font=("Inter", 15, "bold"), text_color="#93a4c7").pack(side="left")
        ctk.CTkLabel(
            formula,
            text=f"{money(delinquency_total)}",
            font=("Consolas", 16, "bold"),
            text_color=ModernTheme.DANGER,
        ).pack(side="left")
        ctk.CTkLabel(
            formula,
            text=f"Variance: {money(variance)}",
            font=("Consolas", 13, "bold"),
            text_color=status_color,
        ).pack(side="right")

        equation_details = self._disclosure_frame(self.recon_content, "Calculation and timing details")
        details = ctk.CTkFrame(equation_details, fg_color="transparent")
        details.pack(fill="x", pady=(0, 14))
        rows = (
            ("Equation substitution (A = B + C)", f"{money(total_collectible)} = {money(treasury_total)} + {money(delinquency_total)}"),
            ("Equation variance [A - (B + C)]", money(equation_variance)),
            ("Net current collectible", f"{money(current_levy)} + {money(current_penalty)} - {money(current_discount)} = {money(current_net)}"),
            ("Collections / credits applied", f"{money(calendar_applicable_collections)} + {money(prepaid_current_year)} = {money(treasury_total)}"),
            ("Future-year prepayments excluded from equation", money(future_year_prepayments)),
            ("Prior-year + current-year receivables", f"{money(prior_receivable)} + {money(current_receivable)} = {money(delinquency_total)}"),
            ("As-of tracker variance [tracker - expected ending]", money(tracker_variance)),
            ("All-time vs as-of difference", money(raw_tracker_variance)),
            ("Collection rate", f"{collection_rate:.1f}%"),
            ("Ending receivable rate", f"{delinquency_rate:.1f}%"),
        )
        for label, value in rows:
            row = ctk.CTkFrame(details, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=label, font=("Inter", 11), text_color="#bfdbfe", anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=value, font=("Consolas", 11, "bold"), text_color="#f8fafc", anchor="e").pack(side="right")
            ctk.CTkFrame(details, height=1, fg_color="#1f2937").pack(fill="x")

        result_color = "#10b981" if balanced else "#f59e0b"
        result_bg = "#0f302c" if balanced else "#30240f"
        result = ctk.CTkFrame(self.recon_content, fg_color=result_bg, corner_radius=8, border_width=1, border_color=result_color)
        result.pack(fill="x", pady=(0, 14))
        result_text = "Balanced - ready for Accounting review" if balanced else "Needs review before submission"
        detail_text = (
            "Equation and tracker agree to the cent; no allocation or payment-sequence issues were detected."
            if balanced else
            "Review allocation and payment-sequence issues against receipt evidence. Timing differences and genuine credits can be legitimate. Do not delete or repair records just to make the report balance."
        )
        ctk.CTkLabel(result, text=result_text, font=("Inter", 14, "bold"), text_color=result_color).pack(anchor="w", padx=18, pady=(16, 4))
        ctk.CTkLabel(result, text=f"Variance: {money(variance)}", font=("Consolas", 18, "bold"), text_color=result_color).pack(anchor="w", padx=18)
        ctk.CTkLabel(result, text=detail_text, font=("Inter", 11), text_color="#cbd5e1", wraplength=900, justify="left").pack(anchor="w", padx=18, pady=(6, 16))

        diagnostic_body = self._disclosure_frame(self.recon_content, "Diagnostic samples — full details are included in exports")
        diag = ctk.CTkFrame(diagnostic_body, fg_color=("#e2e8f0", "#111827"), corner_radius=8, border_width=1, border_color=("#cbd5e1", "#243244"))
        diag.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(diag, text="RECONCILIATION DIAGNOSTIC", font=("Inter", 11, "bold"), text_color=ModernTheme.TEXT_GRAY).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            diag,
            text=(
                "Rows and categories that can explain why collectible, collections, and receivable totals do not tie exactly. "
                "All-time vs as-of compares today's raw billing balances against the selected fiscal-year reporting view."
            ),
            font=("Inter", 10),
            text_color="#bfdbfe",
            wraplength=1100,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 10))

        diag_summary = ctk.CTkFrame(diag, fg_color="transparent")
        diag_summary.pack(fill="x", padx=16, pady=(0, 10))
        diag_summary.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        def diag_chip(parent, col, title, value, color):
            chip = ctk.CTkFrame(parent, fg_color="#0f172a", corner_radius=7, border_width=1, border_color="#334155")
            chip.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 4, 0 if col == 5 else 4))
            ctk.CTkLabel(chip, text=title.upper(), font=("Inter", 9, "bold"), text_color=ModernTheme.TEXT_GRAY).pack(anchor="w", padx=10, pady=(8, 2))
            ctk.CTkLabel(chip, text=value, font=("Consolas", 12, "bold"), text_color=color).pack(anchor="w", padx=10, pady=(0, 8))

        diag_chip(diag_summary, 0, "Equation variance", money(equation_variance), status_color)
        diag_chip(diag_summary, 1, "All-time vs as-of", money(raw_tracker_variance), "#f59e0b")
        link_issue_count = diagnostics.get("payment_link_issue_count", len(diagnostics.get("payment_link_mismatches", [])) + len(diagnostics.get("unlinked_payments", [])))
        diag_chip(diag_summary, 2, "Payment link issues", str(link_issue_count), "#f59e0b")
        diag_chip(diag_summary, 3, "Credit diagnostic rows", str(diagnostics.get("overpaid_credit_count", len(diagnostics.get("overpaid_or_credit_rows", [])))), "#22c55e")
        diag_chip(diag_summary, 4, "Payment-year gaps", str(diagnostics.get("payment_sequence_gap_count", len(diagnostics.get("payment_sequence_gaps", []))) or 0), "#ef4444")
        diag_chip(diag_summary, 5, "Timing/prepayment groups", str(len(diagnostics.get("prior_year_collections", [])) + len(diagnostics.get("future_year_collections", [])) + len(diagnostics.get("current_year_paid_outside_selected_year", []))), "#38bdf8")

        diag_rows = []
        for item in diagnostics.get("unlinked_payments", [])[:10]:
            payment_date = item.get("payment_date") or "No date"
            or_number = item.get("or_number") or "No OR"
            scope = f"{item.get('barangay') or '-'} | {payment_date} | OR {or_number}"
            diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"), scope, item.get("amount", 0)))
        for item in diagnostics.get("payment_link_mismatches", [])[:8]:
            diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"), item.get("barangay"), item.get("difference", 0)))
        for item in diagnostics.get("overpaid_or_credit_rows", [])[:8]:
            diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"), item.get("barangay"), item.get("balance", 0)))
        for item in diagnostics.get("payment_sequence_gaps", [])[:20]:
            later_year = item.get("later_paid_year") or "-"
            status = str(item.get("gap_status") or "gap").replace("_", " ").title()
            scope = f"{item.get('barangay') or '-'} | {status} | Later paid: {later_year}"
            diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"), scope, item.get("outstanding") or 0))
        for item in diagnostics.get("prior_year_collections", []):
            diag_rows.append((item.get("issue"), "Grouped", item.get("tax_year"), f"{item.get('properties', 0):,} properties", item.get("amount", 0)))
        for item in diagnostics.get("future_year_collections", []):
            diag_rows.append((item.get("issue"), "Grouped", item.get("tax_year"), f"{item.get('properties', 0):,} properties", item.get("amount", 0)))
        for item in diagnostics.get("current_year_paid_outside_details", [])[:12]:
            payment_year = item.get("payment_year") or "No date"
            payment_date = item.get("payment_date") or f"Paid in {payment_year}"
            or_number = item.get("or_number") or "No OR"
            scope = f"{item.get('barangay') or '-'} | {payment_date} | OR {or_number}"
            diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"), scope, item.get("amount", 0)))
        for item in diagnostics.get("current_year_paid_outside_selected_year", [])[:8]:
            payment_year = item.get("payment_year") or "No date"
            diag_rows.append((item.get("issue"), f"Grouped paid in {payment_year}", item.get("tax_year"), f"{item.get('properties', 0):,} properties", item.get("amount", 0)))
        if not diag_rows:
            for item in diagnostics.get("largest_open_balances", [])[:10]:
                diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"), item.get("barangay"), item.get("balance", 0)))

        cols = ("Issue", "TD / Group", "Year", "Barangay / Scope", "Amount")
        diag_table = ctk.CTkFrame(diag, fg_color="transparent")
        diag_table.pack(fill="x", padx=16, pady=(0, 14))

        diag_scroll_y = ttk.Scrollbar(diag_table, orient="vertical")
        diag_scroll_x = ttk.Scrollbar(diag_table, orient="horizontal")
        diag_tree = ttk.Treeview(
            diag_table,
            columns=cols,
            show="headings",
            height=min(7, max(3, len(diag_rows))),
            yscrollcommand=diag_scroll_y.set,
            xscrollcommand=diag_scroll_x.set,
        )
        diag_scroll_y.configure(command=diag_tree.yview)
        diag_scroll_x.configure(command=diag_tree.xview)

        widths = {"Issue": 430, "TD / Group": 170, "Year": 90, "Barangay / Scope": 360, "Amount": 150}
        for col in cols:
            diag_tree.heading(col, text=col.upper())
            diag_tree.column(col, width=widths[col], minwidth=widths[col], anchor="e" if col == "Amount" else "center", stretch=False)
        diag_tree.column("Issue", anchor="w")
        diag_tree.column("Barangay / Scope", anchor="w")
        for row in diag_rows:
            diag_tree.insert("", "end", values=(row[0], row[1], row[2], row[3], money(row[4])))

        diag_scroll_y.pack(side="right", fill="y")
        diag_tree.pack(side="top", fill="x", expand=True)
        diag_scroll_x.pack(side="bottom", fill="x")
        if brgy_rows:
            review = ctk.CTkFrame(self.recon_content, fg_color=("#e2e8f0", "#111827"), corner_radius=8, border_width=1, border_color=("#cbd5e1", "#243244"))
            review.pack(fill="both", expand=True)
            ctk.CTkLabel(review, text="TOP BARANGAYS TO REVIEW", font=("Inter", 11, "bold"), text_color=ModernTheme.TEXT_GRAY).pack(anchor="w", padx=16, pady=(14, 8))
            cols = ("Barangay", "Tax Due", "Collected", "Receivable", "Rate")
            tree = ttk.Treeview(review, columns=cols, show="headings", height=6)
            for col in cols:
                tree.heading(col, text=col.upper())
                tree.column(col, anchor="center", width=120)
            tree.column("Barangay", anchor="w", width=200)
            tree.pack(fill="both", expand=True, padx=16, pady=(0, 14))
            top_rows = sorted(brgy_rows, key=lambda row: float(row[6] or 0), reverse=True)[:6]
            for idx, row in enumerate(top_rows):
                due = float(row[2] or 0)
                collected = float(row[5] or 0)
                receivable = float(row[6] or 0)
                rate = (collected / due * 100) if due > 0 else 0
                tree.insert("", "end", values=(row[0], money(due), money(collected), money(receivable), f"{rate:.1f}%"))

    def _recon_money(self, value):
        return f"P {float(value or 0):,.2f}"

    def _build_reconciliation_diag_rows(self, diagnostics, full=False):
        diagnostics = diagnostics or {}
        diag_rows = []

        def take(items, limit):
            items = items or []
            return items if full else items[:limit]

        for item in take(diagnostics.get("unlinked_payments"), 10):
            payment_date = item.get("payment_date") or "No date"
            or_number = item.get("or_number") or "No OR"
            scope = f"{item.get('barangay') or '-'} | {payment_date} | OR {or_number}"
            diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"), scope, item.get("amount", 0)))
        for item in take(diagnostics.get("payment_link_mismatches"), 8):
            diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"), item.get("barangay"), item.get("difference", 0)))
        for item in take(diagnostics.get("receipt_allocation_mismatches"), 10):
            diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"),
                              f"Payment {item.get('payment_id')} | Wrong-account links: {item.get('wrong_account_links', 0)}",
                              item.get("difference", 0)))
        for item in take(diagnostics.get("undated_billing_adjustments"), 10):
            diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"),
                              "Recorded-charge basis requires evidence review", item.get("amount", 0)))
        for item in take(diagnostics.get("receipts_without_dates"), 10):
            diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"),
                              "Date unavailable", item.get("amount", 0)))
        for item in take(diagnostics.get("overpaid_or_credit_rows"), 8):
            diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"), item.get("barangay"), item.get("balance", 0)))
        for item in take(diagnostics.get("payment_sequence_gaps"), 20):
            later_year = item.get("later_paid_year") or "-"
            status = str(item.get("gap_status") or "gap").replace("_", " ").title()
            scope = f"{item.get('barangay') or '-'} | {status} | Later paid: {later_year}"
            diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"), scope, item.get("outstanding") or 0))
        for item in diagnostics.get("prior_year_collections", []) or []:
            diag_rows.append((item.get("issue"), "Grouped", item.get("tax_year"), f"{item.get('properties', 0):,} properties", item.get("amount", 0)))
        for item in diagnostics.get("future_year_collections", []) or []:
            diag_rows.append((item.get("issue"), "Grouped", item.get("tax_year"), f"{item.get('properties', 0):,} properties", item.get("amount", 0)))
        for item in take(diagnostics.get("current_year_paid_outside_details"), 12):
            payment_year = item.get("payment_year") or "No date"
            payment_date = item.get("payment_date") or f"Paid in {payment_year}"
            or_number = item.get("or_number") or "No OR"
            scope = f"{item.get('barangay') or '-'} | {payment_date} | OR {or_number}"
            diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"), scope, item.get("amount", 0)))
        for item in take(diagnostics.get("current_year_paid_outside_selected_year"), 8):
            payment_year = item.get("payment_year") or "No date"
            diag_rows.append((item.get("issue"), f"Grouped paid in {payment_year}", item.get("tax_year"), f"{item.get('properties', 0):,} properties", item.get("amount", 0)))
        if not diag_rows:
            for item in take(diagnostics.get("largest_open_balances"), 10):
                diag_rows.append((item.get("issue"), item.get("td_number"), item.get("tax_year"), item.get("barangay"), item.get("balance", 0)))
        return diag_rows

    def _build_reconciliation_payload(self, data, brgy_rows, metrics, diagnostics, full_diagnostics=False):
        data = data or {}
        brgy_rows = brgy_rows or []
        metrics = metrics or {}
        diagnostics = diagnostics or {}
        assessor = metrics.get("assessor", {})
        treasury = metrics.get("treasury", {})
        delinquency = metrics.get("delinquency", {})

        year = data.get("report_year", self.recon_year_cb.get())
        beginning = float(data.get("beginning_receivable", 0) or 0)
        adjustments = float(data.get("adjustments", 0) or 0)
        collections = float(data.get("collections", 0) or 0)
        current_levy = float(assessor.get("current_year_levy", data.get("current_year_levy", data.get("current_year_assessment", 0))) or 0)
        current_penalty = float(assessor.get("current_year_penalty", data.get("current_year_penalty", 0)) or 0)
        current_discount = float(assessor.get("current_year_discount", data.get("current_year_discount", 0)) or 0)
        current_net = float(assessor.get("current_year_net_collectible", data.get("current_year_net_collectible", data.get("current_year_assessment", 0))) or 0)
        total_collectible = beginning + current_net + adjustments

        calendar_applicable_collections = float(treasury.get("calendar_applicable_collections", data.get("calendar_applicable_collections", collections)) or 0)
        cash_collected_this_year = float(treasury.get("cash_collected_this_year", collections) or 0)
        prepaid_current_year = float(treasury.get("prepaid_current_year", data.get("prepaid_current_year", 0)) or 0)
        future_year_prepayments = float(treasury.get("future_year_prepayments", data.get("future_year_prepayments", 0)) or 0)
        treasury_total = float(treasury.get("total_collected", data.get("applied_collections", calendar_applicable_collections + prepaid_current_year)) or 0)

        expected_unpaid = float(data.get("expected_ending_receivable", data.get("ending_receivable", 0)) or 0)
        tracker_total = float(delinquency.get("total_unpaid", data.get("ending_receivable", 0)) or 0)
        current_receivable = float(delinquency.get("current_year_receivables", 0) or 0)
        prior_receivable = float(delinquency.get("prior_year_receivables", max(tracker_total - current_receivable, 0)) or 0)
        delinquency_total = float(delinquency.get("total_unpaid", prior_receivable + current_receivable) or 0)

        equation_variance = total_collectible - (treasury_total + delinquency_total)
        tracker_variance = float(diagnostics.get("tracker_variance", tracker_total - expected_unpaid) or 0)
        raw_tracker_variance = float(diagnostics.get("raw_tracker_variance", tracker_variance) or 0)
        variance = equation_variance if abs(equation_variance) > 0.005 else tracker_variance
        link_issues = int(diagnostics.get("payment_link_issue_count",
            len(diagnostics.get("payment_link_mismatches", [])) + len(diagnostics.get("unlinked_payments", []))
            + len(diagnostics.get("receipt_allocation_mismatches", []))))
        sequence_gaps = int(diagnostics.get("payment_sequence_gap_count", len(diagnostics.get("payment_sequence_gaps", []))))
        cash_difference = float(treasury.get("cash_allocation_difference", 0) or 0)
        undated_count = int(diagnostics.get("undated_adjustment_count", 0) or 0)
        missing_date_count = int(diagnostics.get("missing_receipt_date_count", 0) or 0)
        balanced = (max(abs(equation_variance), abs(tracker_variance), abs(cash_difference)) <= 0.005
                    and link_issues == 0 and sequence_gaps == 0 and undated_count == 0 and missing_date_count == 0)

        top_barangays = []
        for row in sorted(brgy_rows, key=lambda item: float(item[6] or 0), reverse=True)[:20]:
            due = float(row[2] or 0)
            collected = float(row[5] or 0)
            receivable = float(row[6] or 0)
            rate = (collected / due * 100) if due > 0 else 0
            top_barangays.append((row[0], due, collected, receivable, rate))

        return {
            "year": year,
            "prepared_at": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
            "status": "BALANCED" if balanced else "NEEDS REVIEW",
            "balanced": balanced,
            "adjustment_basis": data.get("adjustment_basis", "Equal shares across linked billing rows (legacy convention)"),
            "details_complete": diagnostics.get("details_complete", False),
            "assessor": {
                "total_assessed_value": float(assessor.get("total_assessed_value", 0) or 0),
                "basic_tax_rate": float(assessor.get("tax_rate_percent", 0) or 0),
                "total_rpt_rate": float(assessor.get("total_tax_rate_percent", 0) or 0),
                "taxable_properties": int(assessor.get("taxable_properties", 0) or 0),
                "current_levy": current_levy,
                "current_penalty": current_penalty,
                "current_discount": current_discount,
                "current_net": current_net,
            },
            "treasury": {
                "basic_tax_collected": float(treasury.get("basic_tax_collected", 0) or 0),
                "cash_collected_this_year": cash_collected_this_year,
                "cash_allocation_difference": cash_difference,
                "closed_account_cash_this_year": float(treasury.get("closed_account_cash_this_year", 0) or 0),
                "calendar_applicable_collections": calendar_applicable_collections,
                "prepaid_current_year": prepaid_current_year,
                "future_year_prepayments": future_year_prepayments,
                "accounts_paid": int(treasury.get("accounts_paid", 0) or 0),
                "partial_payments": int(treasury.get("partial_payments", 0) or 0),
                "total_collected": treasury_total,
            },
            "delinquency": {
                "prior_year_receivables": prior_receivable,
                "current_year_receivables": current_receivable,
                "delinquent_accounts": int(delinquency.get("delinquent_accounts", 0) or 0),
                "penalties_interest": float(delinquency.get("penalties_interest", 0) or 0),
                "ending_receivable": delinquency_total,
            },
            "equation": {
                "beginning_receivable": beginning,
                "adjustments": adjustments,
                "total_collectible": total_collectible,
                "collections": treasury_total,
                "ending_receivable": delinquency_total,
                "equation_variance": equation_variance,
                "tracker_variance": tracker_variance,
                "raw_tracker_variance": raw_tracker_variance,
                "variance": variance,
                "collection_rate": (treasury_total / total_collectible * 100) if total_collectible > 0 else 0,
                "receivable_rate": (expected_unpaid / total_collectible * 100) if total_collectible > 0 else 0,
            },
            "diagnostic_counts": {
                "payment_link_issues": link_issues,
                "overpaid_credits": int(diagnostics.get("overpaid_credit_count", len(diagnostics.get("overpaid_or_credit_rows", [])))),
                "undated_adjustments": undated_count,
                "missing_receipt_dates": missing_date_count,
                "payment_year_gaps": int(diagnostics.get("payment_sequence_gap_count", len(diagnostics.get("payment_sequence_gaps", []))) or 0),
                "timing_prepayment_groups": len(diagnostics.get("prior_year_collections", [])) + len(diagnostics.get("future_year_collections", [])) + len(diagnostics.get("current_year_paid_outside_selected_year", [])),
            },
            "diagnostic_rows": self._build_reconciliation_diag_rows(diagnostics, full=full_diagnostics),
            "top_barangays": top_barangays,
        }

    def _fetch_reconciliation_export_payload(self, year):
        report = billing.get_receivables_report(year, diagnostics=True, full_details=True)
        return self._build_reconciliation_payload(
            report["summary"], report["barangays"], report["metrics"], report["diagnostics"], full_diagnostics=True
        )

    def _export_reconciliation_excel(self):
        if not self._workspace_export_allowed("reconciliation"):
            return
        year = self.recon_year_cb.get()
        dest = filedialog.asksaveasfilename(
            title="Save Reconciliation Working Paper",
            initialfile=f"Reconciliation_Working_Paper_{year}.xlsx",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
        )
        if not dest:
            return
        self._run_reconciliation_export(
            self.recon_export_excel_btn,
            "EXPORT EXCEL",
            lambda: self._write_reconciliation_excel(self._fetch_reconciliation_export_payload(year), dest),
            dest,
        )

    def _export_reconciliation_pdf(self):
        if not self._workspace_export_allowed("reconciliation"):
            return
        year = self.recon_year_cb.get()
        dest = filedialog.asksaveasfilename(
            title="Save Reconciliation PDF",
            initialfile=f"Reconciliation_Working_Paper_{year}.pdf",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not dest:
            return
        self._run_reconciliation_export(
            self.recon_export_pdf_btn,
            "EXPORT PDF",
            lambda: self._write_reconciliation_pdf(self._fetch_reconciliation_export_payload(year), dest),
            dest,
        )

    def _run_reconciliation_export(self, button, original_text, worker_fn, dest):
        button._workspace_export_busy = True
        button.configure(text="GENERATING...", state="disabled")
        self._show_loading()

        def restore():
            button._workspace_export_busy = False
            button.configure(text=original_text, state="normal")
            self._sync_workspace("reconciliation")

        def worker():
            try:
                worker_fn()

                def done():
                    self._hide_loading()
                    restore()
                    if messagebox.askyesno("Export Successful", f"Reconciliation report saved to:\n{dest}\n\nOpen it now?"):
                        self._open_file(dest)

                self.container.after(0, done)
            except Exception as exc:
                self.container.after(
                    0,
                    lambda e=exc: (
                        self._hide_loading(),
                        restore(),
                        messagebox.showerror("Export Failed", str(e)),
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _write_reconciliation_excel(self, payload, dest):
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        wb.properties.title = f"Reconciliation Working Paper {payload['year']}"
        wb.properties.subject = "Inter-Department Reconciliation"
        wb.properties.creator = "MTO Treasury System"
        ws = wb.active
        ws.title = "Summary"

        navy = "17365D"
        blue = "1F4E78"
        light_blue = "D9EAF7"
        pale_blue = "EEF5FB"
        dark = "1F2937"
        gray = "E7E6E6"
        light_gray = "F7F9FB"
        green = "008000"
        red = "C00000"
        amber = "B45F06"
        white = "FFFFFF"
        border_color = "A6A6A6"
        thin = Side(style="thin", color=border_color)
        medium = Side(style="medium", color=navy)
        money_fmt = 'P #,##0.00;[Red]-P #,##0.00'
        number_fmt = '#,##0'
        percent_fmt = '0.0%'

        def setup_sheet(sheet, tab_color=blue):
            sheet.sheet_view.showGridLines = False
            sheet.sheet_properties.tabColor = tab_color
            sheet.freeze_panes = "A8"
            sheet.page_setup.orientation = "landscape"
            sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
            sheet.page_margins.left = 0.25
            sheet.page_margins.right = 0.25
            sheet.page_margins.top = 0.5
            sheet.page_margins.bottom = 0.5

        def border_range(sheet, cell_range, side=thin):
            rows = list(sheet[cell_range])
            for row in rows:
                for cell in row:
                    cell.border = Border(top=side, left=side, right=side, bottom=side)

        def fill_range(sheet, cell_range, fill_color):
            fill = PatternFill("solid", fgColor=fill_color)
            for row in sheet[cell_range]:
                for cell in row:
                    cell.fill = fill

        def merge_label(sheet, cell_range, text, fill_color=blue, font_color=white, size=11):
            sheet.merge_cells(cell_range)
            cell = sheet[cell_range.split(":")[0]]
            cell.value = text
            cell.font = Font(name="Calibri", size=size, bold=True, color=font_color)
            cell.fill = PatternFill("solid", fgColor=fill_color)
            cell.alignment = Alignment(horizontal="left", vertical="center")
            border_range(sheet, cell_range, medium)

        def write_value(cell, value, kind="money"):
            cell.value = value
            cell.font = Font(name="Calibri", size=10, bold=True, color=dark)
            cell.alignment = Alignment(horizontal="right", vertical="center")
            if kind == "money":
                cell.number_format = money_fmt
            elif kind == "number":
                cell.number_format = number_fmt
            elif kind == "percent":
                cell.number_format = percent_fmt

        def write_header(sheet, subtitle):
            sheet.merge_cells("A1:H1")
            sheet["A1"] = "REPUBLIC OF THE PHILIPPINES"
            sheet["A1"].font = Font(name="Calibri", size=10, bold=True, color=dark)
            sheet["A1"].alignment = Alignment(horizontal="center")
            sheet.merge_cells("A2:H2")
            sheet["A2"] = "PROVINCE OF AURORA | MUNICIPALITY OF DIPACULAO"
            sheet["A2"].font = Font(name="Calibri", size=10, bold=True, color=dark)
            sheet["A2"].alignment = Alignment(horizontal="center")
            sheet.merge_cells("A3:H3")
            sheet["A3"] = "MUNICIPAL TREASURY OFFICE"
            sheet["A3"].font = Font(name="Calibri", size=11, bold=True, color=dark)
            sheet["A3"].alignment = Alignment(horizontal="center")
            sheet.merge_cells("A4:H4")
            sheet["A4"] = "INTER-DEPARTMENT RECONCILIATION WORKING PAPER"
            sheet["A4"].font = Font(name="Calibri", size=16, bold=True, color=white)
            sheet["A4"].fill = PatternFill("solid", fgColor=navy)
            sheet["A4"].alignment = Alignment(horizontal="center", vertical="center")
            sheet.merge_cells("A5:H5")
            sheet["A5"] = subtitle
            sheet["A5"].font = Font(name="Calibri", size=10, italic=True, color="475569")
            sheet["A5"].alignment = Alignment(horizontal="center")
            sheet.row_dimensions[4].height = 24

        setup_sheet(ws)
        write_header(ws, f"Fiscal Year {payload['year']} | Generated {payload['prepared_at']}")
        for col, width in {
            "A": 28, "B": 18, "C": 3, "D": 30, "E": 18, "F": 3, "G": 30, "H": 18
        }.items():
            ws.column_dimensions[col].width = width

        merge_label(ws, "A7:H7", "CONTROL SUMMARY")
        summary_rows = [
            ("Status", payload["status"], "Variance", payload["equation"]["variance"], "Collection Rate", payload["equation"]["collection_rate"] / 100),
            ("Total Collectible (A)", payload["equation"]["total_collectible"], "Collections / Credits (B)", payload["equation"]["collections"], "Ending Receivable (C)", payload["equation"]["ending_receivable"]),
        ]
        start = 8
        for idx, row in enumerate(summary_rows, start=start):
            ws[f"A{idx}"], ws[f"D{idx}"], ws[f"G{idx}"]
            labels = (("A", row[0]), ("D", row[2]), ("G", row[4]))
            values = (("B", row[1]), ("E", row[3]), ("H", row[5]))
            for col, label in labels:
                ws[f"{col}{idx}"] = label
                ws[f"{col}{idx}"].font = Font(bold=True, color=dark)
                ws[f"{col}{idx}"].fill = PatternFill("solid", fgColor=light_blue)
            for col, value in values:
                kind = "percent" if col == "H" and idx == start else "money"
                if col == "B" and idx == start:
                    ws[f"{col}{idx}"] = value
                    ws[f"{col}{idx}"].font = Font(bold=True, color=green if payload["balanced"] else red)
                    ws[f"{col}{idx}"].alignment = Alignment(horizontal="center", vertical="center")
                else:
                    write_value(ws[f"{col}{idx}"], value, kind)
            border_range(ws, f"A{idx}:H{idx}")

        merge_label(ws, "A12:H12", "RECONCILIATION EQUATION")
        equation_rows = [
            ("Beginning receivable", payload["equation"]["beginning_receivable"]),
            ("Current year net collectible", payload["assessor"]["current_net"]),
            ("Adjustments", payload["equation"]["adjustments"]),
            ("Total collectible (A)", payload["equation"]["total_collectible"]),
            ("Collections / credits (B)", payload["equation"]["collections"]),
            ("Ending receivable (C)", payload["equation"]["ending_receivable"]),
            ("Equation variance [A - (B + C)]", payload["equation"]["equation_variance"]),
            ("As-of tracker variance", payload["equation"]["tracker_variance"]),
            ("All-time vs as-of difference", payload["equation"]["raw_tracker_variance"]),
        ]
        for idx, (label, value) in enumerate(equation_rows, start=13):
            ws.merge_cells(start_row=idx, start_column=1, end_row=idx, end_column=4)
            ws.cell(idx, 1).value = label
            ws.cell(idx, 1).font = Font(color=dark, bold=label.endswith("(A)") or label.endswith("(B)") or label.endswith("(C)"))
            ws.merge_cells(start_row=idx, start_column=5, end_row=idx, end_column=8)
            write_value(ws.cell(idx, 5), value)
            border_range(ws, f"A{idx}:H{idx}")
            if label.startswith("Total collectible") or label.startswith("Equation variance"):
                fill_range(ws, f"A{idx}:H{idx}", pale_blue)

        merge_label(ws, "A24:H24", "DEPARTMENT RECONCILIATION DATA")
        section_headers = [("A25:B25", "ASSESSOR'S OFFICE"), ("D25:E25", "TREASURER'S OFFICE"), ("G25:H25", "RPT TRACKER")]
        for cell_range, title in section_headers:
            merge_label(ws, cell_range, title, fill_color=blue, size=10)
        sections = [
            ("Total assessed value", payload["assessor"]["total_assessed_value"], "money", "Basic principal applied", payload["treasury"]["basic_tax_collected"], "money", "Prior-year receivables", payload["delinquency"]["prior_year_receivables"], "money"),
            ("Basic tax rate", payload["assessor"]["basic_tax_rate"] / 100, "percent", "Cash collected this year", payload["treasury"]["cash_collected_this_year"], "money", "Current year receivables", payload["delinquency"]["current_year_receivables"], "money"),
            ("Total RPT rate", payload["assessor"]["total_rpt_rate"] / 100, "percent", "Current-year prepayments", payload["treasury"]["prepaid_current_year"], "money", "Delinquent accounts", payload["delinquency"]["delinquent_accounts"], "number"),
            ("Taxable properties", payload["assessor"]["taxable_properties"], "number", "Future prepayments excluded", payload["treasury"]["future_year_prepayments"], "money", "Penalties and interest", payload["delinquency"]["penalties_interest"], "money"),
            ("Penalties / interest", payload["assessor"]["current_penalty"], "money", "Accounts paid", payload["treasury"]["accounts_paid"], "number", "Ending receivable", payload["delinquency"]["ending_receivable"], "money"),
            ("Discounts", payload["assessor"]["current_discount"], "money", "Partial payments", payload["treasury"]["partial_payments"], "number", "", "", "text"),
            ("Current year levy", payload["assessor"]["current_levy"], "money", "Applied collections / credits", payload["treasury"]["total_collected"], "money", "", "", "text"),
        ]
        for idx, row in enumerate(sections, start=26):
            for label_col, value_col, label, value, kind in (
                ("A", "B", row[0], row[1], row[2]),
                ("D", "E", row[3], row[4], row[5]),
                ("G", "H", row[6], row[7], row[8]),
            ):
                ws[f"{label_col}{idx}"] = label
                ws[f"{label_col}{idx}"].font = Font(color=dark)
                if kind != "text":
                    write_value(ws[f"{value_col}{idx}"], value, kind)
                else:
                    ws[f"{value_col}{idx}"] = value
            border_range(ws, f"A{idx}:B{idx}")
            border_range(ws, f"D{idx}:E{idx}")
            border_range(ws, f"G{idx}:H{idx}")

        merge_label(ws, "A35:H35", "REVIEW NOTES", fill_color="595959")
        ws.merge_cells("A36:H39")
        ws["A36"] = (
            "This working paper supports reconciliation between assessed collectible amounts, "
            "Treasury collections/credits, and RPT receivable balances. Diagnostic rows should be reviewed "
            "before Accounting or COA submission when the status is NEEDS REVIEW."
        )
        ws["A36"].alignment = Alignment(wrap_text=True, vertical="top")
        ws["A36"].font = Font(color=dark)
        border_range(ws, "A36:H39")

        ws.print_area = "A1:H39"

        diag = wb.create_sheet("Diagnostics")
        setup_sheet(diag, tab_color=amber)
        write_header(diag, "Diagnostic rows that explain timing, credit, or payment-allocation differences")
        for col, width in {"A": 48, "B": 22, "C": 12, "D": 48, "E": 18, "F": 14, "G": 30, "H": 14}.items():
            diag.column_dimensions[col].width = width
        merge_label(diag, "A7:H7", "DIAGNOSTIC SUMMARY", fill_color=amber)
        diag.append([
            "Payment link issues", payload["diagnostic_counts"]["payment_link_issues"],
            "Overpaid / credits", payload["diagnostic_counts"]["overpaid_credits"],
            "Payment-year gaps", payload["diagnostic_counts"]["payment_year_gaps"],
            "Timing / prepayment groups", payload["diagnostic_counts"]["timing_prepayment_groups"],
        ])
        border_range(diag, "A8:H8")
        fill_range(diag, "A8:H8", pale_blue)
        diag.append(["Undated adjustments", payload["diagnostic_counts"].get("undated_adjustments", 0),
                     "Missing receipt dates", payload["diagnostic_counts"].get("missing_receipt_dates", 0)])
        diag.append(["Issue", "TD / Group", "Year", "Barangay / Scope", "Amount"])
        for row in payload["diagnostic_rows"]:
            diag.append(list(row))
        for cell in diag[10]:
            cell.font = Font(bold=True, color=white)
            cell.fill = PatternFill("solid", fgColor=navy)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        diag.auto_filter.ref = f"A10:E{max(10, diag.max_row)}"
        diag.freeze_panes = "A11"
        for row in diag.iter_rows(min_row=11):
            row[4].number_format = '#,##0.00'
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = Border(top=thin, left=thin, right=thin, bottom=thin)

        brgy = wb.create_sheet("Barangay Review")
        setup_sheet(brgy, tab_color=green)
        write_header(brgy, "Top barangays sorted by ending receivable")
        for col, width in {"A": 28, "B": 18, "C": 18, "D": 18, "E": 16}.items():
            brgy.column_dimensions[col].width = width
        merge_label(brgy, "A7:E7", "TOP BARANGAYS TO REVIEW", fill_color=green)
        brgy.append(["Barangay", "Tax Due", "Collected", "Receivable", "Collection Rate"])
        for row in payload["top_barangays"]:
            brgy.append(list(row))
        for cell in brgy[8]:
            cell.font = Font(bold=True, color=white)
            cell.fill = PatternFill("solid", fgColor=navy)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        brgy.auto_filter.ref = f"A8:E{max(8, brgy.max_row)}"
        brgy.freeze_panes = "A9"
        for row in brgy.iter_rows(min_row=9):
            for cell in row[1:4]:
                cell.number_format = money_fmt
            row[4].number_format = '0.0%'
            row[4].value = (row[4].value or 0) / 100
            for cell in row:
                cell.border = Border(top=thin, left=thin, right=thin, bottom=thin)

        sign = wb.create_sheet("Certification")
        setup_sheet(sign, tab_color="595959")
        write_header(sign, "Certification and sign-off")
        for col, width in {"A": 24, "B": 24, "C": 24, "D": 24, "E": 24, "F": 24, "G": 24, "H": 24}.items():
            sign.column_dimensions[col].width = width
        merge_label(sign, "A7:H7", "CERTIFICATION", fill_color="595959")
        sign.merge_cells("A9:H11")
        sign["A9"] = (
            "I certify that this reconciliation working paper was generated from the MTO Treasury System "
            "for review by the Municipal Treasury Office, Accounting Office, and COA audit requirements."
        )
        sign["A9"].alignment = Alignment(wrap_text=True, vertical="top")
        sign["A9"].font = Font(color=dark)
        border_range(sign, "A9:H11")
        signature_rows = [
            (14, "Prepared by", "Reviewed by", "Noted by"),
            (18, "Date", "Date", "Date"),
        ]
        for row_idx, left, mid, right in signature_rows:
            for start_col, label in ((1, left), (4, mid), (7, right)):
                end_col = start_col + 1
                sign.merge_cells(start_row=row_idx, start_column=start_col, end_row=row_idx, end_column=end_col)
                sign.cell(row_idx, start_col).value = label
                sign.cell(row_idx, start_col).font = Font(bold=True, color=dark)
                sign.cell(row_idx, start_col).alignment = Alignment(horizontal="center")
                sign.merge_cells(start_row=row_idx + 1, start_column=start_col, end_row=row_idx + 1, end_column=end_col)
                border_range(sign, f"{get_column_letter(start_col)}{row_idx + 1}:{get_column_letter(end_col)}{row_idx + 1}", medium)
        merge_label(sign, "A22:H22", "REMARKS", fill_color="595959")
        sign.merge_cells("A23:H29")
        border_range(sign, "A23:H29")

        for sheet in wb.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    cell.alignment = Alignment(
                        horizontal=cell.alignment.horizontal or "left",
                        vertical=cell.alignment.vertical or "center",
                        wrap_text=cell.alignment.wrap_text,
                    )
                    if cell.font == Font():
                        cell.font = Font(name="Calibri", size=10, color=dark)

        # This report contains computed values, not spreadsheet formulas.
        # Preserve potentially hostile taxpayer strings as literal text.
        for sheet in wb.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.data_type == "f":
                        cell.data_type = "s"
        wb.save(dest)
        return dest

    def _write_reconciliation_pdf(self, payload, dest):
        from xml.sax.saxutils import escape
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        doc = SimpleDocTemplate(dest, pagesize=landscape(A4), rightMargin=12 * mm, leftMargin=12 * mm, topMargin=10 * mm, bottomMargin=10 * mm)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("ReconTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=15, textColor=colors.HexColor("#1e40af"), spaceAfter=4)
        small = ParagraphStyle("Small", parent=styles["BodyText"], fontSize=8, leading=10)
        header = ParagraphStyle("Header", parent=styles["Heading2"], fontSize=10, textColor=colors.HexColor("#0f172a"), spaceBefore=6, spaceAfter=4)

        def money(value):
            return self._recon_money(value)

        story = [
            Paragraph("INTER-DEPARTMENT RECONCILIATION WORKING PAPER", title_style),
            Paragraph(f"Fiscal Year {payload['year']} | Generated {payload['prepared_at']} | Status: <b>{payload['status']}</b>", small),
            Paragraph(escape(payload.get("adjustment_basis", "Equal shares across linked billing rows (legacy convention)")), small),
            Spacer(1, 5),
        ]

        summary_rows = [
            ["Total Collectible (A)", money(payload["equation"]["total_collectible"]), "Collections / Credits (B)", money(payload["equation"]["collections"]), "Ending Receivable (C)", money(payload["equation"]["ending_receivable"])],
            ["Equation", Paragraph(escape(f"{money(payload['equation']['total_collectible'])} = {money(payload['equation']['collections'])} + {money(payload['equation']['ending_receivable'])}"), small), "Variance", money(payload["equation"]["variance"]), "Review Status", payload["status"]],
        ]
        story.append(Table(summary_rows, colWidths=[38 * mm, 42 * mm, 38 * mm, 42 * mm, 38 * mm, 42 * mm], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])))
        story.append(Spacer(1, 6))

        story.append(Paragraph("Department Data", header))
        department_rows = [
            ["Assessor's Office", "Value", "Treasurer's Office", "Value", "RPT Tracker", "Value"],
            ["Total assessed value", money(payload["assessor"]["total_assessed_value"]), "Basic principal applied", money(payload["treasury"]["basic_tax_collected"]), "Prior-year receivables", money(payload["delinquency"]["prior_year_receivables"])],
            ["Taxable properties", f"{payload['assessor']['taxable_properties']:,}", "Accounts paid", f"{payload['treasury']['accounts_paid']:,}", "Current year receivables", money(payload["delinquency"]["current_year_receivables"])],
            ["Current year levy", money(payload["assessor"]["current_levy"]), "Applied collections / credits", money(payload["treasury"]["total_collected"]), "Ending receivable", money(payload["delinquency"]["ending_receivable"])],
            ["Penalties / discounts", f"{money(payload['assessor']['current_penalty'])} / -{money(payload['assessor']['current_discount'])}", "Future prepayments excluded", money(payload["treasury"]["future_year_prepayments"]), "Delinquent accounts", f"{payload['delinquency']['delinquent_accounts']:,}"],
            ["Ledger cash (all accounts)", money(payload["treasury"]["cash_collected_this_year"]), "Closed-account cash", money(payload["treasury"].get("closed_account_cash_this_year", 0)), "Cash/allocation difference", money(payload["treasury"].get("cash_allocation_difference", 0))],
        ]
        story.append(Table(department_rows, colWidths=[35 * mm, 42 * mm, 38 * mm, 42 * mm, 38 * mm, 42 * mm], repeatRows=1, style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#94a3b8")),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ])))
        story.append(Spacer(1, 6))

        story.append(Paragraph("Diagnostic Summary", header))
        diag_count_rows = [
            ["Payment link issues", payload["diagnostic_counts"]["payment_link_issues"], "Overpaid / credits", payload["diagnostic_counts"]["overpaid_credits"]],
            ["Payment-year gaps", payload["diagnostic_counts"]["payment_year_gaps"], "Timing / prepayment groups", payload["diagnostic_counts"]["timing_prepayment_groups"]],
            ["Undated adjustments", payload["diagnostic_counts"].get("undated_adjustments", 0), "Missing receipt dates", payload["diagnostic_counts"].get("missing_receipt_dates", 0)],
        ]
        story.append(Table(diag_count_rows, colWidths=[58 * mm, 24 * mm, 58 * mm, 24 * mm], style=TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#94a3b8")),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ])))
        story.append(Spacer(1, 4))
        if not payload.get("details_complete", False):
            story.append(Paragraph("Diagnostic detail is sampled. Full issue counts may exceed the rows shown.", small))

        diag_rows = [["Issue", "TD / Group", "Year", "Barangay / Scope", "Amount"]]
        for issue, td, tax_year, scope, amount in payload["diagnostic_rows"]:
            diag_rows.append([
                Paragraph(escape(str(issue or "")), small),
                Paragraph(escape(str(td or "")), small),
                str(tax_year or ""),
                Paragraph(escape(str(scope or "")), small),
                money(amount),
            ])
        story.append(Table(diag_rows, colWidths=[70 * mm, 32 * mm, 18 * mm, 70 * mm, 30 * mm], repeatRows=1, style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#94a3b8")),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ])))
        story.append(Spacer(1, 8))

        sign_rows = [
            ["Prepared by / Date", "", "Reviewed by / Date", "", "Noted by / Date", ""],
            ["", "", "", "", "", ""],
        ]
        story.append(KeepTogether([Paragraph("Prepared and reviewed", header), Table(sign_rows, colWidths=[35 * mm, 45 * mm, 35 * mm, 45 * mm, 35 * mm, 45 * mm], rowHeights=[8 * mm, 14 * mm], style=TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#94a3b8")),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))]))
        def footer(canvas, document):
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(285 * mm, 5 * mm, f"Page {document.page}")
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        return dest

    def generate_collection_report(self):
        # Reset to page 1 on a new search
        self._coll_cursors = [None]
        self._coll_page = 0
        self._coll_has_more = False
        self._coll_load_page()

    def _coll_load_page(self):
        month = self.month_cb.get()
        year = self.year_cb.get()
        search = self.coll_search.get().strip() if hasattr(self, "coll_search") else ""
        order_label = self.coll_order_cb.get() if hasattr(self, "coll_order_cb") else "Newest posted"
        order = "oldest" if order_label == "Oldest posted" else "newest"
        anchor = getattr(self, "_coll_anchor", None) if self._coll_page > 0 else None
        cursor = self._coll_cursors[self._coll_page]
        token = self._start_report_request("collection")
        self._coll_loading = True
        page = self._coll_page

        def worker():
            try:
                data = billing.get_report_details(
                    month, year,
                    limit=self._coll_page_size,
                    cursor=cursor,
                    search=search,
                    anchor=anchor,
                    order=order,
                )
                def apply():
                    current_search = self.coll_search.get().strip() if hasattr(self, "coll_search") else ""
                    current_order = self.coll_order_cb.get() if hasattr(self, "coll_order_cb") else "Newest posted"
                    if (month, year, search, order_label) == (self.month_cb.get(), self.year_cb.get(), current_search, current_order):
                        self._coll_page = page
                        self._coll_anchor = data.get("anchor")
                        self._workspace_accept("collection", data, lambda: self._update_coll_table(data), has_rows=bool(data.get("items", data.get("total_count", 1))))
                self._post_report_result("collection", token, apply)
            except Exception as e:
                self._post_report_result("collection", token, lambda err=e: self._show_collection_error(err))
            finally:
                self._schedule_report_finish("collection", token)

        threading.Thread(target=worker, daemon=True).start()

    def _coll_next_page(self):
        state = getattr(self, "_workspace_states", {}).get("collection")
        if self._coll_has_more and not getattr(self, "_coll_loading", False) and (state is None or state.status == "loaded"):
            self._coll_page += 1
            self._coll_load_page()

    def _coll_prev_page(self):
        state = getattr(self, "_workspace_states", {}).get("collection")
        if self._coll_page > 0 and not getattr(self, "_coll_loading", False) and (state is None or state.status == "loaded"):
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

        if hasattr(self, "coll_metrics") and isinstance(data, dict):
            for label, value in zip(self.coll_metrics, (format_curr(data.get("cash_total", 0)), f"{data.get('total_count', len(items)):,}", f"{len(items):,}")):
                label.configure(text=value)

        if not items and self._coll_page == 0:
            self._coll_has_more = False
            self.coll_empty_state.show(
                "Try another month or year, then generate the report again.",
                title="No collections found",
            )
            self._coll_page_lbl.configure(text="No results")
            self._coll_prev_btn.configure(state="disabled")
            self._coll_next_btn.configure(state="disabled")
            return

        if items:
            self.coll_empty_state.hide()
        else:
            self.coll_empty_state.show(
                "Go back a page or change the reporting period.",
                title="No records on this page",
            )

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
        token = self._start_report_request("receivables")

        def worker():
            try:
                report = billing.get_receivables_report(year)
                self._post_report_result("receivables", token, lambda: self._workspace_accept("receivables", report, lambda: self._update_receiv_summary(report["summary"], report["barangays"])))
            except Exception as e:
                self._post_report_result("receivables", token, lambda err=e: self._show_receivables_error(err))
            finally:
                self._schedule_report_finish("receivables", token)

        threading.Thread(target=worker, daemon=True).start()

    def _show_receivables_error(self, error):
        self._workspace_fail("receivables")
        self._show_content_error(self.receiv_content, error, "Unable to load receivables")

    def _update_receiv_summary(self, data, brgy_rows=None):
        for child in self.receiv_content.winfo_children():
            child.destroy()
        if not data:
            show_empty_content(self.receiv_content, "Try another fiscal year.", title="No receivables data")
            return
        applied = float(data.get("collections", 0) or 0) + float(data.get("prepaid_current_year", 0) or 0)
        self._metric_cards(self.receiv_content, (
            ("Ending receivable", format_curr(data.get("ending_receivable", 0)), "Positive unpaid balances; credits not netted"),
            ("Cash + advances applied", format_curr(applied), "Includes earlier payments applied to this year"),
            (RECORDED_CREDIT_BALANCE_LABEL, format_curr(data.get("ending_credit", 0)), "Separate positive credit on each billing"),
        ))
        ctk.CTkButton(self.receiv_content, text="View credit accounts · read only", command=lambda: self._view_credit_accounts("receivables"), fg_color=ModernTheme.PRIMARY_SURFACE).pack(anchor="w", pady=(0, 12))
        details = self._disclosure_frame(self.receiv_content, "Calculation basis, coverage and barangay comparison")
        original = self.receiv_content
        try:
            self.receiv_content = details
            self._update_receiv_summary_details(data, brgy_rows)
        finally:
            self.receiv_content = original

    def _update_receiv_summary_details(self, data, brgy_rows=None):
        for child in self.receiv_content.winfo_children():
            child.destroy()

        if not data:
            show_empty_content(
                self.receiv_content,
                "Try another year or check that receivables data is available.",
                title="No receivables data",
            )
            return

        # --- DATA PREP ---
        beg = float(data.get("beginning_receivable", 0))
        curr = float(data.get("current_year_net_collectible", data.get("current_year_assessment", 0)))
        curr_levy = float(data.get("current_year_levy", curr))
        curr_penalty = float(data.get("current_year_penalty", 0))
        curr_discount = float(data.get("current_year_discount", 0))
        coll = float(data.get("collections", 0))
        prepaid = float(data.get("prepaid_current_year", 0))
        applied = coll + prepaid
        adj = float(data.get("adjustments", 0))
        end = float(data.get("ending_receivable", 0))
        year = data.get("report_year", "N/A")
        brgy_rows = brgy_rows or []

        # Coverage includes cash applied and earlier payments applied to this
        # year's billings. It is not a current-year-only cash collection rate.
        total_target = beg + curr + adj
        efficiency = (applied / total_target * 100) if total_target > 0 else 0
        uncollected_rate = (end / total_target * 100) if total_target > 0 else 0

        def money(value):
            return format_curr(value).replace("₱", "P")

        def metric_card(parent, title, value, color, subtitle=None):
            card = ctk.CTkFrame(
                parent,
                fg_color=("#e2e8f0", "#1e293b"),
                corner_radius=8,
                border_width=1,
                border_color=("#cbd5e1", "#334155"),
            )
            ctk.CTkLabel(
                card,
                text=title.upper(),
                font=("Inter", 9, "bold"),
                text_color=ModernTheme.TEXT_GRAY,
            ).pack(anchor="w", padx=14, pady=(12, 2))
            ctk.CTkLabel(
                card,
                text=money(value),
                font=("Inter", 20, "bold"),
                text_color=color,
            ).pack(anchor="w", padx=14)
            if subtitle:
                ctk.CTkLabel(
                    card,
                    text=subtitle,
                    font=("Inter", 10),
                    text_color=ModernTheme.TEXT_GRAY,
                ).pack(anchor="w", padx=14, pady=(2, 12))
            else:
                ctk.CTkFrame(card, height=12, fg_color="transparent").pack()
            return card

        # --- HEADER ---
        header_fr = ctk.CTkFrame(self.receiv_content, fg_color="transparent")
        header_fr.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            header_fr,
            text=f"FISCAL YEAR {year} RECEIVABLES PERFORMANCE",
            font=ModernTheme.H2,
            text_color=ModernTheme.PRIMARY,
        ).pack(anchor="w")

        eff_color = ModernTheme.SUCCESS if efficiency >= 70 else ModernTheme.WARNING if efficiency >= 40 else ModernTheme.DANGER
        ctk.CTkLabel(
            header_fr,
            text=f"{RECEIVABLES_COVERAGE_LABEL}: {efficiency:.1f}%",
            font=ModernTheme.H3,
            text_color=eff_color,
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        formula_fr = ctk.CTkFrame(
            self.receiv_content,
            fg_color=("#dbeafe", "#172033"),
            border_width=1,
            border_color=("#93c5fd", "#334155"),
            corner_radius=8,
        )
        formula_fr.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            self.receiv_content,
            text="Current non-deleted registry; recorded charges, not a live SOA estimate. "
                 + data.get("adjustment_basis", "Equal shares across linked billing years (legacy convention)."),
            font=ModernTheme.BODY_SMALL, text_color=ModernTheme.TEXT_GRAY,
            wraplength=900, justify="left",
        ).pack(anchor="w", pady=(0, 8))
        formula = (
            f"{money(beg)} beginning + {money(curr_levy)} current levy "
            f"+ {money(curr_penalty)} penalties - {money(curr_discount)} discounts "
            f"+ {money(adj)} prior-year/credit movements - {money(coll)} cash applied "
            f"- {money(prepaid)} prepaid credits = {money(end)} ending receivable"
        )
        ctk.CTkLabel(
            formula_fr,
            text=formula,
            font=("Inter", 12, "bold"),
            wraplength=1100,
            justify="left",
            text_color=("#1e293b", "#cbd5e1"),
        ).pack(anchor="w", padx=14, pady=10)

        grid = ctk.CTkFrame(self.receiv_content, fg_color="transparent")
        grid.pack(fill="x", pady=(0, 12))
        for col in range(3):
            grid.grid_columnconfigure(col, weight=1)

        metric_card(grid, "Beginning Balance", beg, "#94a3b8", "Prior-year unpaid balance").grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        metric_card(grid, "Current Year Levy", curr_levy, ModernTheme.PRIMARY, "Assessed value x RPT rate").grid(row=0, column=1, sticky="nsew", padx=4, pady=(0, 8))
        metric_card(grid, "Net Current Collectible", curr, "#f59e0b", "Levy + penalties - discounts").grid(row=0, column=2, sticky="nsew", padx=(8, 0), pady=(0, 8))
        metric_card(grid, "Cash + Advance Payments Applied", applied, ModernTheme.SUCCESS, f"Cash {money(coll)} + earlier advance payments {money(prepaid)}").grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        metric_card(grid, "Penalties / Interest", curr_penalty, "#f97316", "Shown separately from levy").grid(row=1, column=1, sticky="nsew", padx=4, pady=(0, 8))
        metric_card(grid, "Discounts", curr_discount, "#22c55e", "Deducted from collectible").grid(row=1, column=2, sticky="nsew", padx=(8, 0), pady=(0, 8))
        metric_card(grid, "Prior-Year / Credit Movements", adj, "#a855f7", f"{RECORDED_CREDIT_BALANCE_LABEL}: {money(data.get('ending_credit', 0))}").grid(row=2, column=0, sticky="nsew", padx=(0, 8))
        metric_card(grid, "Total Collectible", total_target, "#f59e0b", "Beginning + net current + adjustments").grid(row=2, column=1, sticky="nsew", padx=4)
        metric_card(grid, "Ending Receivable", end, ModernTheme.DANGER, f"{uncollected_rate:.1f}% remains uncollected").grid(row=2, column=2, sticky="nsew", padx=(8, 0))

        body = ctk.CTkFrame(self.receiv_content, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=2)
        body.grid_columnconfigure(1, weight=3)
        body.grid_rowconfigure(0, weight=1)

        progress_fr = ctk.CTkFrame(
            body,
            fg_color=("#e2e8f0", "#1e293b"),
            corner_radius=8,
            border_width=1,
            border_color=("#cbd5e1", "#334155"),
        )
        progress_fr.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ctk.CTkLabel(
            progress_fr,
            text="COLLECTION TARGET PROGRESS",
            font=("Inter", 11, "bold"),
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(anchor="w", padx=16, pady=(14, 8))

        prog_bar = ctk.CTkProgressBar(progress_fr, height=14, corner_radius=7)
        prog_bar.pack(fill="x", padx=16, pady=(0, 8))
        prog_bar.set(min(1.0, max(0.0, efficiency / 100)))
        prog_bar.configure(progress_color=eff_color)

        remaining = max(0.0, total_target - applied)
        status_text = (
            "Healthy collection pace" if efficiency >= 70
            else "Needs collection follow-up" if efficiency >= 40
            else "Critical collection gap"
        )
        ctk.CTkLabel(
            progress_fr,
            text=f"{status_text}\nRemaining target: {money(remaining)}",
            font=("Inter", 13, "bold"),
            text_color=eff_color,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(6, 4))
        ctk.CTkLabel(
            progress_fr,
            text=RECEIVABLES_COVERAGE_HELP,
            font=("Inter", 10),
            text_color=ModernTheme.TEXT_GRAY,
            wraplength=430,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 14))

        brgy_fr = ctk.CTkFrame(
            body,
            fg_color=("#e2e8f0", "#1e293b"),
            corner_radius=8,
            border_width=1,
            border_color=("#cbd5e1", "#334155"),
        )
        brgy_fr.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(
            brgy_fr,
            text="TOP RECEIVABLE BARANGAYS",
            font=("Inter", 11, "bold"),
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(anchor="w", padx=16, pady=(14, 8))

        cols = ("Barangay", "Collected", "Receivable", "Rate")
        tree = ttk.Treeview(brgy_fr, columns=cols, show="headings", height=7)
        for col in cols:
            tree.heading(col, text=col.upper())
            tree.column(col, anchor="center", width=110)
        tree.column("Barangay", anchor="w", width=170)
        tree.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        tree.tag_configure("oddrow", background="#1e293b", foreground="#cbd5e1")
        tree.tag_configure("evenrow", background="#162032", foreground="#cbd5e1")

        top_rows = sorted(brgy_rows, key=lambda row: float(row[6] or 0), reverse=True)[:7]
        for idx, row in enumerate(top_rows):
            collected = float(row[5] or 0)
            receivable = float(row[6] or 0)
            due = float(row[2] or 0)
            rate = (collected / due * 100) if due > 0 else 0
            tree.insert(
                "",
                "end",
                values=(row[0], money(collected), money(receivable), f"{rate:.1f}%"),
                tags=("evenrow" if idx % 2 == 0 else "oddrow",),
            )

    def generate_barangay_receivables(self):
        selected = self.brgy_year_cb.get()
        try:
            year = None if selected == "All Years" else int(selected)
        except ValueError:
            messagebox.showerror("Invalid Year", "Select a fiscal year or All Years.")
            return
        token = self._start_report_request("barangay")

        def worker():
            try:
                report = billing.get_receivables_report(year)
                self._post_report_result("barangay", token, lambda: self._workspace_accept("barangay", report, lambda: self._update_brgy_table(report["barangays"], year), has_rows=bool(report["barangays"])))
            except Exception as e:
                self._post_report_result("barangay", token, lambda err=e: self._show_barangay_error(err))
            finally:
                self._schedule_report_finish("barangay", token)

        threading.Thread(target=worker, daemon=True).start()

    def _update_brgy_table(self, data, year=None):
        self._brgy_rows, self._brgy_loaded_year = data, year
        for item in self.brgy_tree.get_children():
            self.brgy_tree.delete(item)

        year_label = f"Fiscal-year ending: December 31, {year}" if year else "All billing years / all recorded payment dates"
        self.brgy_year_lbl.configure(text=year_label)

        if not data:
            self.brgy_empty_state.show(
                "Try another as-of year, then refresh the report.",
                title="No barangay records found",
            )
            self.brgy_total_lbl.configure(text=tr("reports.barangay.total").replace("{value}", "P 0.00"))
            return

        self.brgy_empty_state.hide()

        grand_total = 0.0
        for i, row in enumerate(data):
            f_row = list(row)
            try:
                receiv_val = float(row[6] or 0)
                grand_total += receiv_val
            except Exception:
                pass

            if len(f_row) >= 7:
                for idx in range(1, len(f_row)):
                    f_row[idx] = format_curr(f_row[idx])

            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.brgy_tree.insert("", "end", values=f_row, tags=(tag,))

        self.brgy_total_lbl.configure(
            text=tr("reports.barangay.total").replace("{value}", f"P {grand_total:,.2f}")
                 + f"  |  {RECORDED_CREDIT_BALANCE_LABEL}: P {sum(float(row[7] or 0) for row in data if len(row) > 7):,.2f}"
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

    def _export_with_feedback(self, btn, worker_fn, export_format):
        """Generate in a thread, then save on the UI thread in the chosen format."""
        original_text = btn.cget("text")
        btn._workspace_export_busy = True
        btn.configure(text="⏳ Generating...", state="disabled")

        def restore():
            btn._workspace_export_busy = False
            btn.configure(text=original_text, state="normal")
            for kind in getattr(self, "_workspace_states", {}):
                self._sync_workspace(kind)

        def _run():
            try:
                path = worker_fn()
                options = report_export_dialog_options(path, export_format)
                # Ask where to save
                def _save():
                    try:
                        dest = filedialog.asksaveasfilename(**options)
                        if dest:
                            if os.path.splitext(dest)[1].lower() != options["defaultextension"]:
                                raise ValueError(
                                    f"Save this report with the {options['defaultextension']} extension. "
                                    "Changing the filename does not convert its format. No file was saved."
                                )
                            shutil.copy2(path, dest)
                            if messagebox.askyesno("Export Successful",
                                                   f"Report saved to:\n{dest}\n\nOpen it now?"):
                                self._open_file(dest)
                    except Exception as exc:
                        messagebox.showerror("Export Failed", str(exc))
                    finally:
                        restore()

                self.container.after(0, _save)
            except Exception as exc:
                self.container.after(
                    0, lambda e=exc: (
                        messagebox.showerror("Export Failed", str(e)),
                        restore(),
                    )
                )

        threading.Thread(target=_run, daemon=True).start()

    def _export_receivables_excel(self):
        if not self._workspace_export_allowed("receivables"):
            return
        year = self.receiv_year_cb.get()
        self._export_with_feedback(
            self.receiv_export_excel_btn,
            lambda: billing.export_report_excel("receivables", year=year),
            "excel",
        )

    def _export_receivables_barangay_pdf(self):
        if not self._workspace_export_allowed("receivables"):
            return
        year = int(self.receiv_year_cb.get())
        self._export_with_feedback(
            self.receiv_export_brgy_btn,
            lambda: billing.download_receivables_by_barangay_pdf(year=year),
            "pdf",
        )

    def _export_brgy_pdf(self):
        if not self._workspace_export_allowed("barangay"):
            return
        selected = self.brgy_year_cb.get()
        try:
            year = None if selected == "All Years" else int(selected)
        except ValueError:
            messagebox.showerror("Invalid Year", "Select a fiscal year or All Years.")
            return
        self._export_with_feedback(
            self.brgy_export_pdf_btn,
            lambda: billing.download_receivables_by_barangay_pdf(year=year),
            "pdf",
        )

    def _export_brgy_excel(self):
        if not self._workspace_export_allowed("barangay"):
            return
        selected = self.brgy_year_cb.get()
        year = selected if selected != "All Years" else "All"
        self._export_with_feedback(
            self.brgy_export_excel_btn,
            lambda: billing.export_report_excel("receivables_by_barangay", year=year),
            "excel",
        )

    def open_manage_deposits(self):
        try:
            start_date, end_date = self.get_selected_date_range()
        except ValueError as error:
            messagebox.showerror("Select Reporting Period", str(error))
            return
        ManageDepositsModal(self.container, start_date, end_date)

    def open_export_signatories(self):
        if not self._workspace_export_allowed("collection"):
            return
        try:
            self.get_selected_date_range()
        except ValueError as error:
            messagebox.showerror("Select Reporting Period", str(error))
            return
        default_officer = self.user.get("full_name", "") if isinstance(self.user, dict) else ""
        SignatoriesModal(self.container, default_officer, self.export_coa_rcd)

    def open_daily_rcd(self):
        role = str(self.user.get("role", "")).strip().lower() if isinstance(self.user, dict) else ""
        if role != "admin":
            messagebox.showerror("Access denied", "Daily RCD and booklet registration require administrator access.")
            return
        from ui.rcd_daily import DailyRcdWindow
        DailyRcdWindow(self.container)

    def export_coa_rcd(
        self, liquidating_officer, treasurer, *, report_number="",
        accountable_officer="", report_date=None,
    ):
        start_date, end_date = self.get_selected_date_range()
        self._show_loading()
        
        self.export_rcd_btn.configure(state="disabled", text="⏳ Exporting...")
        
        def worker():
            try:
                path = reports_api.download_coa_rcd(
                    start_date=start_date,
                    end_date=end_date,
                    liquidating_officer=liquidating_officer,
                    treasurer=treasurer,
                    report_number=report_number,
                    accountable_officer=accountable_officer,
                    report_date=report_date,
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
                self.container.after(0, lambda err=e: messagebox.showerror("Export Failed", str(err)))
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
        if year == "All":
            if month != "All":
                raise ValueError("Select a year to export or manage deposits for a specific month.")
            return "1000-01-01", "9999-12-31"
        y = int(year)
        if not 1900 <= y <= 2100:
            raise ValueError("Select a valid year between 1900 and 2100.")
        
        if month == "All":
            start_date = f"{y}-01-01"
            end_date = f"{y}-12-31"
        else:
            m = int(month)
            if not 1 <= m <= 12:
                raise ValueError("Select a month from 01 to 12, or All.")
            _, last_day = calendar.monthrange(y, m)
            start_date = f"{y}-{m:02d}-01"
            end_date = f"{y}-{m:02d}-{last_day:02d}"
            
        return start_date, end_date


class SignatoriesModal(ctk.CTkToplevel):
    def __init__(self, parent, default_officer, callback):
        super().__init__(parent)
        self.title("RCD Report Details")
        self.geometry("520x640")
        self.minsize(460, 480)
        self.resizable(True, True)
        self.callback = callback
        
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)
        
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{max(0, (sw-520)//2)}+{max(0, (sh-640)//2)}")
        
        self.setup_ui(default_officer)
        
    def setup_ui(self, default_officer):
        self.configure(fg_color="#1a1a2e")
        ctk.CTkFrame(self, fg_color=ModernTheme.PRIMARY, height=4, corner_radius=0).pack(fill="x")
        
        body = ctk.CTkScrollableFrame(self, fg_color="#1a1a2e")
        body.pack(fill="both", expand=True, padx=24, pady=(18, 8))
        
        ctk.CTkLabel(body, text="RCD Report Details", font=("Segoe UI", 14, "bold"), text_color="white").pack(anchor="w", pady=(0, 6))
        ctk.CTkLabel(body, text="Report identity is separate from the selected collection period.", wraplength=380, justify="left", font=("Segoe UI", 11), text_color="#a0aec0").pack(anchor="w", pady=(0, 16))

        ctk.CTkLabel(body, text="Report number", font=("Segoe UI", 11, "bold"), text_color="#a0aec0").pack(anchor="w")
        self.report_number_ent = ctk.CTkEntry(body, height=36, placeholder_text="Enter your office's report number", fg_color="#2d2d4e", border_color="#4a4a6e", text_color="white")
        self.report_number_ent.pack(fill="x", pady=(4, 12))

        ctk.CTkLabel(body, text="Accountable officer (preparer)", font=("Segoe UI", 11, "bold"), text_color="#a0aec0").pack(anchor="w")
        self.accountable_officer_ent = ctk.CTkEntry(body, height=36, fg_color="#2d2d4e", border_color="#4a4a6e", text_color="white")
        self.accountable_officer_ent.insert(0, default_officer)
        self.accountable_officer_ent.pack(fill="x", pady=(4, 12))

        ctk.CTkLabel(body, text="Report date (YYYY-MM-DD, Philippine time)", font=("Segoe UI", 11, "bold"), text_color="#a0aec0").pack(anchor="w")
        self.report_date_ent = ctk.CTkEntry(body, height=36, fg_color="#2d2d4e", border_color="#4a4a6e", text_color="white")
        self.report_date_ent.insert(0, philippine_report_date().isoformat())
        self.report_date_ent.pack(fill="x", pady=(4, 4))
        ctk.CTkLabel(body, text="Filled with today's date. Change it only when preparing an earlier report.\nThe exported date stays fixed when the file is reopened.", justify="left", wraplength=380, font=("Segoe UI", 10), text_color="#a0aec0").pack(anchor="w", pady=(0, 12))
        
        ctk.CTkLabel(body, text="Liquidating Officer", font=("Segoe UI", 11, "bold"), text_color="#a0aec0").pack(anchor="w")
        self.officer_ent = ctk.CTkEntry(body, height=36, fg_color="#2d2d4e", border_color="#4a4a6e", text_color="white")
        self.officer_ent.pack(fill="x", pady=(4, 12))
        self.officer_ent.bind("<Return>", lambda _e: self.on_export())
        self.officer_ent.bind("<KP_Enter>", lambda _e: self.on_export())
        
        ctk.CTkLabel(body, text="Municipal Treasurer", font=("Segoe UI", 11, "bold"), text_color="#a0aec0").pack(anchor="w")
        self.treasurer_ent = ctk.CTkEntry(body, height=36, fg_color="#2d2d4e", border_color="#4a4a6e", text_color="white")
        self.treasurer_ent.pack(fill="x", pady=(4, 16))
        self.treasurer_ent.bind("<Return>", lambda _e: self.on_export())
        self.treasurer_ent.bind("<KP_Enter>", lambda _e: self.on_export())
        
        for entry in (self.report_number_ent, self.accountable_officer_ent, self.report_date_ent):
            entry.bind("<Return>", lambda _e: self.on_export())
            entry.bind("<KP_Enter>", lambda _e: self.on_export())

        btn_fr = ctk.CTkFrame(self, fg_color="transparent")
        btn_fr.pack(fill="x", padx=24, pady=(8, 18))
        
        ctk.CTkButton(btn_fr, text="Cancel", command=self.destroy,
                      fg_color="#2d2d4e", hover_color="#3d3d5e", text_color="#a0aec0",
                      height=38, width=100, font=("Segoe UI", 11, "bold"), corner_radius=8).pack(side="left")
                      
        ctk.CTkButton(btn_fr, text="Export Excel", command=self.on_export,
                      fg_color=ModernTheme.SUCCESS, hover_color="#1e7e34", text_color="white",
                      height=38, width=150, font=("Segoe UI", 11, "bold"), corner_radius=8).pack(side="right")
                      
    def on_export(self):
        try:
            metadata = resolve_rcd_metadata(
                self.report_number_ent.get(), self.accountable_officer_ent.get(),
                self.report_date_ent.get(), required=True,
            )
        except ValueError as error:
            messagebox.showerror("Check Report Details", str(error))
            return
        officer = self.officer_ent.get().strip()
        treasurer = self.treasurer_ent.get().strip()
        if not officer or not treasurer:
            messagebox.showerror("Check Signatories", "Enter the liquidating officer and Municipal Treasurer names.")
            return
        self.callback(
            officer, treasurer, report_number=metadata.report_number,
            accountable_officer=metadata.accountable_officer,
            report_date=metadata.report_date.isoformat(),
        )
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
        self.date_ent.bind("<Return>", lambda _e: self.save_deposit())
        self.date_ent.bind("<KP_Enter>", lambda _e: self.save_deposit())
        
        ctk.CTkLabel(form_fr, text="Bank Name / Branch", font=("Segoe UI", 10), text_color="#a0aec0").pack(anchor="w", padx=15)
        self.bank_ent = ctk.CTkEntry(form_fr, placeholder_text="e.g. Landbank", height=32, fg_color="#1a1a2e", border_color="#4a4a6e", text_color="white")
        self.bank_ent.pack(fill="x", padx=15, pady=(4, 10))
        self.bank_ent.bind("<Return>", lambda _e: self.save_deposit())
        self.bank_ent.bind("<KP_Enter>", lambda _e: self.save_deposit())
        
        ctk.CTkLabel(form_fr, text="Reference / Slip No.", font=("Segoe UI", 10), text_color="#a0aec0").pack(anchor="w", padx=15)
        self.ref_ent = ctk.CTkEntry(form_fr, placeholder_text="e.g. DS-12345", height=32, fg_color="#1a1a2e", border_color="#4a4a6e", text_color="white")
        self.ref_ent.pack(fill="x", padx=15, pady=(4, 10))
        self.ref_ent.bind("<Return>", lambda _e: self.save_deposit())
        self.ref_ent.bind("<KP_Enter>", lambda _e: self.save_deposit())
        
        ctk.CTkLabel(form_fr, text="Amount (₱)", font=("Segoe UI", 10), text_color="#a0aec0").pack(anchor="w", padx=15)
        self.amt_ent = ctk.CTkEntry(form_fr, placeholder_text="e.g. 50000.00", height=32, fg_color="#1a1a2e", border_color="#4a4a6e", text_color="white")
        self.amt_ent.pack(fill="x", padx=15, pady=(4, 15))
        self.amt_ent.bind("<Return>", lambda _e: self.save_deposit())
        self.amt_ent.bind("<KP_Enter>", lambda _e: self.save_deposit())
        
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
                self.after(0, lambda err=e: messagebox.showerror("Error", f"Failed to load deposits: {err}"))
                
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
                self.after(0, lambda err=e: messagebox.showerror("Error", str(err)))
                
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
                self.after(0, lambda err=e: messagebox.showerror("Error", str(err)))
                
        threading.Thread(target=worker, daemon=True).start()

