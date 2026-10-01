import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from theme_manager import ModernTheme
from utils import tr
from ui_components import LoadingOverlay
import api_clients.property_service as prop_svc
import api_clients.api_helper as api
import api_clients.billing_service as billing
import api_clients.auth_service as auth
import shutil
import os
from ui.dossier import PropertyDossierModal
from ui.empty_state import EmptyTableState
from ui.import_wizard import ImportWizardModal
from ui.property import PropertyEditModal, BulkBarangayUpdateModal
from ui.accessibility import bind_keyboard_activation
import threading
from utils.assessment_roll_status import assessment_roll_duplicate_status


def parse_assessment_roll_as_of_year(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    if not raw.isdigit() or len(raw) != 4:
        raise ValueError("As of Year must be a four-digit year, such as 2026.")
    year = int(raw)
    if year < 1900 or year > 2200:
        raise ValueError("As of Year must be between 1900 and 2200.")
    return year


def assessment_roll_export_dialog_options(path, export_format):
    """Build a save dialog that matches the export button the user selected."""
    formats = {
        "pdf": (".pdf", "PDF document (*.pdf)", "*.pdf"),
        "excel": (".xlsx", "Excel workbook (*.xlsx)", "*.xlsx"),
    }
    try:
        extension, label, pattern = formats[str(export_format).strip().lower()]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported Assessment Roll export: {export_format}"
        ) from exc

    source_name = os.path.basename(path)
    stem = os.path.splitext(source_name)[0] or "Assessment_Roll"
    return {
        "title": f"Save Assessment Roll as {label.split(' (', 1)[0]}",
        "initialfile": f"{stem}{extension}",
        "defaultextension": extension,
        "filetypes": [(label, pattern)],
    }


class AssessmentRollPage:
    CURRENT_MODE = "Current Records"
    HISTORY_MODE = "As-of-Year View"

    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.page_cursors = [None]
        self.current_page = 0
        self.page_size = 50
        self.is_loading = False
        self.all_loaded = False
        self._refresh_generation = 0
        self.view_mode = self.CURRENT_MODE
        self._rows_current = False
        self._loaded_query = None
        self.barangays = [
            "NORTH POBLACION",
            "SOUTH POBLACION",
            "BAYABAS",
            "BORLONGAN",
            "BUENAVISTA",
            "CALAOCAN",
            "DIAMANEN",
            "DIANED",
            "DIARABASIN",
            "DIBUTUNAN",
            "DIMABUNO",
            "DINADIAWAN",
            "DITALE",
            "GUPA",
            "IPIL",
            "LABOY",
            "LIPIT",
            "LOBBOT",
            "MALIGAYA",
            "MIJARES",
            "MUCDOL",
            "PUANGI",
            "SALAY",
            "SAPANGKAWAYAN",
            "TOYTOYAN",
        ]
        self.search_timer = None
        self.setup_ui()
        # Keep table clear initially for performance (Search-First logic)

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        header = ctk.CTkFrame(self.container, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))

        title_fr = ctk.CTkFrame(header, fg_color="transparent")
        title_fr.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            title_fr,
            text="ASSESSMENT ROLL",
            font=ModernTheme.H2,
            text_color=(ModernTheme.TEXT_MAIN_LIGHT, ModernTheme.TEXT_MAIN_DARK),
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_fr,
            text="Manage current property accounts or review historical assessments",
            font=ModernTheme.BODY_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(anchor="w", pady=(2, 0))

        mode_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        mode_fr.pack(fill="x", pady=(0, 10))
        self.mode_control = ctk.CTkSegmentedButton(
            mode_fr,
            values=[self.CURRENT_MODE, self.HISTORY_MODE],
            command=self._change_mode,
            height=34,
            font=ModernTheme.BODY_SMALL,
            selected_color=ModernTheme.PRIMARY_SURFACE,
            selected_hover_color=ModernTheme.PRIMARY_SURFACE_HOVER,
            unselected_color="#334155",
            unselected_hover_color="#475569",
            text_color="#ffffff",
        )
        self.mode_control.set(self.CURRENT_MODE)
        self.mode_control.pack(side="left")
        for mode, button in self.mode_control._buttons_dict.items():
            bind_keyboard_activation(
                button, lambda value=mode: self._choose_mode(value)
            )
        self.mode_hint = ctk.CTkLabel(
            mode_fr,
            text="CURRENT RECORDS — Changes affect the live property registry.",
            font=ModernTheme.BODY_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
            wraplength=520,
            justify="left",
        )
        self.mode_hint.pack(side="left", padx=16)

        management_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        management_fr.pack(fill="x", pady=(0, 10))
        self.add_btn = self.import_btn = self.cleanup_btn = None
        if auth.has_permission(self.user, "property_edit"):
            self.add_btn = self._action_button(
                management_fr, "ADD PROPERTY", self.open_add_modal, ModernTheme.SUCCESS
            )
            self.cleanup_btn = self._action_button(
                management_fr,
                "DATA CLEANUP",
                self.open_bulk_update,
                ModernTheme.SECONDARY,
            )
        if auth.has_permission(self.user, "import_data"):
            self.import_btn = self._action_button(
                management_fr,
                "BULK IMPORT",
                self.open_import_wizard,
                ModernTheme.PRIMARY,
            )

        filters_fr = ctk.CTkFrame(
            self.container,
            fg_color=(ModernTheme.CARD_LIGHT, ModernTheme.CARD_DARK),
            corner_radius=8,
            border_width=1,
            border_color=(ModernTheme.BORDER_LIGHT, ModernTheme.BORDER_DARK),
        )
        filters_fr.pack(fill="x", pady=(0, 10))
        search_fr = ctk.CTkFrame(filters_fr, fg_color="transparent")
        search_fr.pack(fill="x", padx=12, pady=(8, 0))
        scope_fr = ctk.CTkFrame(filters_fr, fg_color="transparent")
        scope_fr.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkLabel(
            search_fr,
            text="FIND PROPERTY",
            font=ModernTheme.BUTTON_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(side="left", padx=(0, 7), pady=4)
        self.search_ent = ctk.CTkEntry(
            search_fr,
            placeholder_text="Search PIN, TD, Former TD, or Owner...",
            width=330,
            height=34,
            font=ModernTheme.BODY_SMALL,
        )
        self.search_ent.pack(side="left", fill="x", expand=True, pady=4)
        self.search_ent.bind("<Return>", lambda e: self.refresh_table())
        self.search_ent.bind("<KP_Enter>", lambda e: self.refresh_table())
        self.search_ent.bind("<KeyRelease>", self._filters_edited, add="+")

        ctk.CTkLabel(
            scope_fr,
            text="BARANGAY",
            font=ModernTheme.BUTTON_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(side="left", padx=(0, 7), pady=4)
        self.brgy_var = tk.StringVar(value="ALL")
        self.brgy_cb = ctk.CTkComboBox(
            scope_fr,
            values=["ALL"] + sorted(self.barangays),
            variable=self.brgy_var,
            width=160,
            height=34,
            font=ModernTheme.BODY_SMALL,
        )
        self.brgy_cb.pack(side="left", pady=4)
        self.brgy_cb.configure(command=lambda e: self.refresh_table())
        self.brgy_cb.bind("<Return>", lambda e: self.refresh_table())
        self.brgy_cb.bind("<KP_Enter>", lambda e: self.refresh_table())

        ctk.CTkLabel(
            scope_fr,
            text="AS OF YEAR",
            font=ModernTheme.BUTTON_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(side="left", padx=(16, 7), pady=4)
        self.as_of_year_ent = ctk.CTkEntry(
            scope_fr,
            width=80,
            height=34,
            placeholder_text="YYYY",
            font=ModernTheme.BODY_SMALL,
            state="disabled",
        )
        self.as_of_year_ent.pack(side="left", pady=4)
        self.as_of_year_ent.bind("<Return>", lambda e: self.refresh_table())
        self.as_of_year_ent.bind("<KP_Enter>", lambda e: self.refresh_table())
        self.as_of_year_ent.bind("<KeyRelease>", self._filters_edited, add="+")

        ctk.CTkLabel(
            scope_fr,
            text="EFFECTIVITY YEAR",
            font=ModernTheme.BUTTON_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(side="left", padx=(16, 7), pady=4)
        self.year_from_ent = ctk.CTkEntry(
            scope_fr, width=75, height=34, placeholder_text="From"
        )
        self.year_to_ent = ctk.CTkEntry(
            scope_fr, width=75, height=34, placeholder_text="To"
        )
        for entry in (self.year_from_ent, self.year_to_ent):
            entry.pack(side="left", padx=(0, 6), pady=4)
            entry.bind("<Return>", lambda e: self.refresh_table())
            entry.bind("<KP_Enter>", lambda e: self.refresh_table())
            entry.bind("<KeyRelease>", self._filters_edited, add="+")

        self.refresh_btn = ctk.CTkButton(
            search_fr,
            text="REFRESH",
            command=self.refresh_table,
            width=105,
            height=34,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.PRIMARY_SURFACE,
            hover_color=ModernTheme.PRIMARY_SURFACE_HOVER,
            text_color="#ffffff",
        )
        self.refresh_btn.pack(side="right", padx=(12, 0), pady=4)
        bind_keyboard_activation(self.refresh_btn, self.refresh_table)

        self._pdf_btn = ctk.CTkButton(
            header,
            text="EXPORT PDF",
            command=self._export_roll_pdf,
            fg_color=ModernTheme.DANGER_SURFACE,
            hover_color=ModernTheme.DANGER_SURFACE_HOVER,
            text_color="#ffffff",
            width=125,
            height=34,
            font=ModernTheme.BUTTON_SMALL,
        )
        self._pdf_btn.pack(side="right", padx=(8, 0))

        self._excel_btn = ctk.CTkButton(
            header,
            text="EXPORT EXCEL",
            command=self._export_roll_excel,
            fg_color="#047857",
            hover_color="#065f46",
            text_color="#ffffff",
            width=135,
            height=34,
            font=ModernTheme.BUTTON_SMALL,
        )
        self._excel_btn.pack(side="right")
        bind_keyboard_activation(self._pdf_btn, self._export_roll_pdf)
        bind_keyboard_activation(self._excel_btn, self._export_roll_excel)
        ctk.CTkLabel(
            self.container,
            text="Exports cover the complete barangay roll and selected as-of year, not the search or current year range.",
            font=ModernTheme.BODY_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(anchor="w", pady=(0, 6))

        duplicate_legend = ctk.CTkFrame(
            self.container,
            fg_color="#3b2a16",
            corner_radius=7,
            border_width=1,
            border_color="#b45309",
        )
        duplicate_legend.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            duplicate_legend,
            text=(
                "AMBER ROWS — Authorized duplicate TD accounts. "
                "Each row remains a separate property account."
            ),
            font=ModernTheme.BUTTON_SMALL,
            text_color="#fef3c7",
        ).pack(anchor="w", padx=12, pady=7)

        table_fr = ctk.CTkFrame(
            self.container,
            fg_color="#0f172a",
            corner_radius=8,
            border_width=1,
            border_color=ModernTheme.BORDER_DARK,
        )
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Roll.Treeview",
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
            "Roll.Treeview.Heading",
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
            "Roll.Treeview",
            background=[("selected", "#0284c7")],
            foreground=[("selected", "#ffffff")],
        )
        style.map("Roll.Treeview.Heading", background=[("active", "#475569")])
        for scrollbar_style in (
            "Roll.Vertical.TScrollbar",
            "Roll.Horizontal.TScrollbar",
        ):
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

        self.cols = (
            "ID",
            "TD NO.",
            "PIN",
            "LOT & BLK",
            "PROPERTY OWNER",
            "LOCATION",
            "CLASSIFICATION",
            "ASSESSED VALUE",
            "PREVIOUS TD",
            "EFFECTIVITY",
            "STATUS",
        )
        tree_host = tk.Frame(table_fr, bg="#0f172a", bd=0, highlightthickness=0)
        tree_host.pack(fill="both", expand=True, padx=1, pady=1)
        self.tree = ttk.Treeview(
            tree_host,
            columns=self.cols,
            show="headings",
            style="Roll.Treeview",
            selectmode="browse",
        )

        # Column Config
        col_widths = {
            "ID": 0,
            "TD NO.": 110,
            "PIN": 130,
            "LOT & BLK": 100,
            "PROPERTY OWNER": 270,
            "LOCATION": 130,
            "CLASSIFICATION": 120,
            "ASSESSED VALUE": 120,
            "PREVIOUS TD": 110,
            "EFFECTIVITY": 100,
            "STATUS": 145,
        }

        for col in self.cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center", width=col_widths.get(col, 100))

        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.column("PROPERTY OWNER", anchor="w")
        self.tree.column("LOCATION", anchor="center")

        scrolly = ttk.Scrollbar(
            tree_host,
            orient="vertical",
            command=self.tree.yview,
            style="Roll.Vertical.TScrollbar",
        )
        scrollx = ttk.Scrollbar(
            tree_host,
            orient="horizontal",
            command=self.tree.xview,
            style="Roll.Horizontal.TScrollbar",
        )
        self.tree.configure(yscrollcommand=scrolly.set, xscrollcommand=scrollx.set)

        # Zebra Tags
        self.tree.tag_configure("oddrow", background="#162032", foreground="#e2e8f0")
        self.tree.tag_configure("evenrow", background="#1e293b", foreground="#f8fafc")
        self.tree.tag_configure(
            "verified_duplicate",
            background="#3b2a16",
            foreground="#fef3c7",
        )

        scrolly.pack(side="right", fill="y")
        scrollx.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        self.empty_state = EmptyTableState(
            tree_host,
            "Search by PIN, TD number, previous TD, or owner, then press Refresh.",
        )

        # --- PAGINATION BAR ---
        self.pag_fr = ctk.CTkFrame(
            self.container,
            fg_color=(ModernTheme.CARD_LIGHT, ModernTheme.CARD_DARK),
            corner_radius=8,
            border_width=1,
            border_color=(ModernTheme.BORDER_LIGHT, ModernTheme.BORDER_DARK),
        )
        self.pag_fr.pack(side="bottom", fill="x", pady=(8, 0))

        self.prev_btn = ctk.CTkButton(
            self.pag_fr,
            text="PREVIOUS",
            command=self.prev_page,
            width=110,
            height=32,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SECONDARY,
            hover_color=ModernTheme.SECONDARY_HOVER,
            state="disabled",
        )
        self.prev_btn.pack(side="left", padx=10, pady=8)

        self.page_lbl = ctk.CTkLabel(
            self.pag_fr,
            text="Page 1",
            font=("Inter", 11, "bold"),
            text_color=ModernTheme.TEXT_GRAY,
        )
        self.page_lbl.pack(side="left", expand=True)

        self.next_btn = ctk.CTkButton(
            self.pag_fr,
            text="NEXT",
            command=self.next_page,
            width=110,
            height=32,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SECONDARY,
            hover_color=ModernTheme.SECONDARY_HOVER,
            state="disabled",
        )
        self.next_btn.pack(side="right", padx=10, pady=8)

        self.edit_btn = self.delete_btn = None
        self.details_btn = self._action_button(
            self.pag_fr,
            "VIEW DETAILS",
            self.open_dossier,
            ModernTheme.SECONDARY,
            side="right",
        )
        if auth.has_permission(self.user, "property_edit"):
            self.edit_btn = self._action_button(
                self.pag_fr,
                "EDIT",
                self.open_edit_modal,
                ModernTheme.PRIMARY,
                side="right",
            )
        if auth.has_permission(self.user, "property_delete"):
            self.delete_btn = self._action_button(
                self.pag_fr,
                "DELETE",
                self.confirm_delete,
                ModernTheme.DANGER,
                side="right",
            )
        bind_keyboard_activation(self.prev_btn, self.prev_page)
        bind_keyboard_activation(self.next_btn, self.next_page)

        table_fr.pack(fill="both", expand=True)  # Pack expanding table LAST

        self.tree.bind("<Double-1>", lambda e: self.open_dossier())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_action_states())
        self._update_action_states()

    def _action_button(self, parent, text, command, color, side="left"):
        color, hover = {
            ModernTheme.PRIMARY: (
                ModernTheme.PRIMARY_SURFACE,
                ModernTheme.PRIMARY_SURFACE_HOVER,
            ),
            ModernTheme.SUCCESS: ("#047857", "#065f46"),
            ModernTheme.DANGER: (
                ModernTheme.DANGER_SURFACE,
                ModernTheme.DANGER_SURFACE_HOVER,
            ),
        }.get(color, (color, ModernTheme.SECONDARY_HOVER))
        button = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            fg_color=color,
            hover_color=hover,
            text_color="#ffffff",
            width=115,
            height=34,
            font=ModernTheme.BUTTON_SMALL,
        )
        button.pack(side=side, padx=5, pady=6)
        bind_keyboard_activation(button, command)
        return button

    def _choose_mode(self, mode):
        self.mode_control.set(mode)
        self._change_mode(mode)

    def _query_as_of_year(self):
        if self.view_mode == self.CURRENT_MODE:
            return None
        year = parse_assessment_roll_as_of_year(self.as_of_year_ent.get())
        if year is None:
            raise ValueError(
                "Enter an As of Year before refreshing or exporting this read-only view."
            )
        return year

    def _query_context(self):
        return (
            self.view_mode,
            self.search_ent.get().strip(),
            self.brgy_var.get(),
            self._query_as_of_year(),
            *self._query_year_range(),
        )

    def _query_year_range(self):
        if self.view_mode != self.CURRENT_MODE:
            return None, None
        years = []
        for name in ("year_from_ent", "year_to_ent"):
            entry = getattr(self, name, None)
            years.append(
                parse_assessment_roll_as_of_year(entry.get())
                if entry is not None
                else None
            )
        start, end = years
        if start is not None and end is not None and start > end:
            raise ValueError("From year cannot be later than To year.")
        return start, end

    def _invalidate_selection(self):
        self._refresh_generation += 1
        self._rows_current = False
        self._loaded_query = None
        self.is_loading = False
        selected = self.tree.selection()
        if selected:
            self.tree.selection_remove(*selected)
        self.prev_btn.configure(state="disabled")
        self.next_btn.configure(state="disabled")
        self._update_action_states()

    def _filters_edited(self, event=None):
        if event is None or event.keysym not in (
            "Return",
            "KP_Enter",
            "Tab",
            "Shift_L",
            "Shift_R",
        ):
            self._invalidate_selection()

    def _change_mode(self, mode):
        if mode not in (self.CURRENT_MODE, self.HISTORY_MODE) or mode == self.view_mode:
            return
        self.view_mode = mode
        self._invalidate_selection()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.page_cursors = [None]
        self.current_page = 0
        self.all_loaded = False
        self.page_lbl.configure(text="PAGE 1")
        historical = mode == self.HISTORY_MODE
        self.as_of_year_ent.configure(state="normal" if historical else "disabled")
        for name in ("year_from_ent", "year_to_ent"):
            entry = getattr(self, name, None)
            if entry is not None:
                entry.configure(state="disabled" if historical else "normal")
        self.mode_hint.configure(
            text=(
                "READ ONLY — Assessment values as of the selected year; no record changes."
                if historical
                else "CURRENT RECORDS — Changes affect the live property registry."
            )
        )
        self.empty_state.show(
            (
                "Enter an As of Year, then press Refresh. Management is disabled here."
                if historical
                else "Search by PIN, TD number, previous TD, or owner, then press Refresh."
            ),
            title=(
                "Historical assessment view" if historical else "No records to display"
            ),
        )
        if not historical and (
            self.search_ent.get().strip() or self.brgy_var.get() != "ALL"
        ):
            self.refresh_table()

    def _can_manage(self, permission):
        return (
            getattr(self, "view_mode", None) == self.CURRENT_MODE
            and not getattr(self, "is_loading", False)
            and auth.has_permission(getattr(self, "user", None), permission)
        )

    def _selected_property(self):
        if (
            getattr(self, "view_mode", None) != self.CURRENT_MODE
            or getattr(self, "is_loading", False)
            or not getattr(self, "_rows_current", False)
        ):
            return None
        try:
            if self._loaded_query != self._query_context():
                return None
            selected = self.tree.selection()
            if len(selected) != 1:
                return None
            values = self.tree.item(selected[0])["values"]
            property_id = int(values[0])
            if property_id <= 0:
                return None
            return property_id, str(values[1]), str(values[4])
        except (ValueError, TypeError, IndexError, KeyError, tk.TclError):
            return None

    def _update_action_states(self):
        selected = self._selected_property() is not None
        for name, permission, needs_selection in (
            ("add_btn", "property_edit", False),
            ("cleanup_btn", "property_edit", False),
            ("import_btn", "import_data", False),
            ("edit_btn", "property_edit", True),
            ("delete_btn", "property_delete", True),
            ("details_btn", "property_view", True),
        ):
            button = getattr(self, name, None)
            if button is not None:
                allowed = self._can_manage(permission) and (
                    selected or not needs_selection
                )
                button.configure(state="normal" if allowed else "disabled")

    def open_add_modal(self):
        if self._can_manage("property_edit"):
            PropertyEditModal(
                self.parent, "Add Property", None, self.refresh_table, user=self.user
            )

    def open_edit_modal(self):
        selected = self._selected_property()
        if selected and self._can_manage("property_edit"):
            # Existing modal fetches the latest account by ID and preserves its version.
            PropertyEditModal(
                self.parent,
                "Edit Property",
                selected[0],
                self.refresh_table,
                user=self.user,
            )

    def open_bulk_update(self):
        if self._can_manage("property_edit"):
            BulkBarangayUpdateModal(self.parent, self.refresh_table)

    def confirm_delete(self):
        selected = self._selected_property()
        if not selected or not self._can_manage("property_delete"):
            return
        property_id, td_number, owner = selected
        if not messagebox.askyesno(
            "Move to Recycle Bin?",
            f"{owner}\nTD: {td_number}\nAccount ID: {property_id}\n\n"
            "Only this property account will be moved to the Recycle Bin.\n"
            "It will not be permanently erased. Continue?",
            parent=self.container,
        ):
            return
        # A mode/filter/selection change while the confirmation is open must fail closed.
        if selected != self._selected_property() or not self._can_manage(
            "property_delete"
        ):
            return
        try:
            result = prop_svc.delete_property(property_id, user=self.user)
            if not isinstance(result, dict) or result.get("status") != "deleted":
                raise ValueError(
                    "Delete was not confirmed by the server. Refresh before trying again."
                )
            self.refresh_table()
            messagebox.showinfo("Moved to Recycle Bin", f"{owner}\n{td_number}")
        except Exception as exc:
            messagebox.showerror("Delete Failed", str(exc))

    def _is_current_refresh(self, generation):
        return generation == self._refresh_generation

    def refresh_table(self, reset_page=True):
        self._invalidate_selection()
        try:
            as_of_year = self._query_as_of_year()
            year_start, year_end = self._query_year_range()
        except ValueError as exc:
            messagebox.showerror("Invalid Year Filter", str(exc))
            return

        term = self.search_ent.get().strip()
        brgy = self.brgy_var.get()
        query_context = self._query_context()

        if reset_page:
            self.page_cursors = [None]
            self.current_page = 0
            self.all_loaded = False

        page_index = self.current_page
        cursor_to_use = self.page_cursors[page_index]
        self._refresh_generation += 1
        request_generation = self._refresh_generation
        self.is_loading = True
        self._update_action_states()
        overlay = LoadingOverlay(self.container, "Loading Assessment Roll...")

        def apply_response(response):
            if not self._is_current_refresh(request_generation):
                return

            results = response.get("items", [])
            next_cursor = response.get("next_cursor")
            has_more = bool(response.get("has_more"))

            if len(self.page_cursors) <= page_index + 1:
                self.page_cursors.append(next_cursor)
            else:
                self.page_cursors[page_index + 1] = next_cursor

            self.all_loaded = not has_more
            self._loaded_query = query_context
            self._rows_current = True
            self._update_table(results, has_more=has_more)

        def show_error(error):
            if self._is_current_refresh(request_generation):
                if not self.tree.get_children():
                    self.empty_state.show(
                        "Check the connection and try Refresh again.",
                        title="Unable to load assessment roll",
                    )
                messagebox.showerror("Error", str(error))

        def finish_request():
            overlay.hide()
            if self._is_current_refresh(request_generation):
                self.is_loading = False
                self._update_action_states()

        def worker():
            try:
                response = prop_svc.search_properties(
                    term,
                    limit=self.page_size,
                    cursor=cursor_to_use,
                    barangay=brgy if brgy != "ALL" else None,
                    as_of_year=as_of_year,
                    year_start=year_start,
                    year_end=year_end,
                )
                self.container.after(
                    0, lambda response=response: apply_response(response)
                )
            except Exception as exc:
                self.container.after(0, lambda error=exc: show_error(error))
            finally:
                self.container.after(0, finish_request)

        threading.Thread(target=worker, daemon=True).start()

    def next_page(self):
        if self._rows_current and not self.is_loading and not self.all_loaded:
            self.current_page += 1
            self.refresh_table(reset_page=False)

    def prev_page(self):
        if self._rows_current and not self.is_loading and self.current_page > 0:
            self.current_page -= 1
            self.all_loaded = False
            self.refresh_table(reset_page=False)

    def _update_table(self, results, has_more=None):
        selected = self.tree.selection()
        if selected:
            self.tree.selection_remove(*selected)
        self._update_action_states()
        self.page_lbl.configure(text=f"PAGE {self.current_page + 1}")
        self.prev_btn.configure(state="normal" if self.current_page > 0 else "disabled")

        if has_more is None:
            has_more = len(results) >= self.page_size
        self.all_loaded = not has_more
        self.next_btn.configure(state="normal" if has_more else "disabled")

        if not results and self.current_page == 0:
            for item in self.tree.get_children():
                self.tree.delete(item)
            self.empty_state.show(
                "Try another PIN, TD, owner, barangay, or as-of year.",
                title="No matching assessments",
            )
            return

        # Always clear table for true page-by-page pagination
        for item in self.tree.get_children():
            self.tree.delete(item)
        if results:
            self.empty_state.hide()
        else:
            self.empty_state.show(
                "Go back a page or change the search filters.",
                title="No records on this page",
            )

        # Get current row count for zebra tagging
        current_count = len(self.tree.get_children())

        for i, r in enumerate(results):
            # Indices from backend search_properties:
            # 0:id, 1:td, 2:owner, 4:lot, 6:loc, 7:kind, 9:av,
            # 18:pin, 19:blk, 20:prev, 21:eff, 22:brgy, 23:verified duplicate
            td = r[1]
            pin = r[18] if len(r) > 18 else ""
            lot_blk = f"{r[4]} / {r[19]}" if len(r) > 19 and r[19] else str(r[4])
            owner = r[2]
            loc = r[22] if len(r) > 22 and r[22] else r[6]  # Barangay or Location
            kind = r[7]
            av = f"{r[9]:,.2f}"
            prev = r[20] if len(r) > 20 else ""
            eff = r[21] if len(r) > 21 else ""
            duplicate_status = assessment_roll_duplicate_status(r)

            # If it's a full date string like 2023-01-01, just show the year
            if eff and len(str(eff)) >= 4:
                eff = str(eff)[:4]

            tag = (
                "verified_duplicate"
                if duplicate_status
                else ("evenrow" if (current_count + i) % 2 == 0 else "oddrow")
            )
            self.tree.insert(
                "",
                "end",
                values=(
                    r[0],
                    td,
                    pin,
                    lot_blk,
                    owner,
                    loc,
                    kind,
                    av,
                    prev,
                    eff,
                    duplicate_status,
                ),
                tags=(tag,),
            )

    def open_import_wizard(self):
        if not self._can_manage("import_data"):
            return
        chooser = ctk.CTkToplevel(self.container)
        chooser.title("Choose Bulk Import")
        chooser.geometry("470x260")
        chooser.transient(self.container.winfo_toplevel())
        chooser.grab_set()
        ctk.CTkLabel(
            chooser,
            text="Choose the existing import format",
            font=ModernTheme.H3,
        ).pack(pady=(20, 8))
        ctk.CTkLabel(
            chooser,
            text="Both imports can change current accounts.\n"
            "Use the matching template and review the validation preview.",
            font=ModernTheme.BODY_SMALL,
        ).pack(pady=(0, 12))
        for label, mode in (
            ("PROPERTY RECORDS TEMPLATE", "property"),
            ("ASSESSMENT ROLL TEMPLATE", "assessment"),
        ):
            button = ctk.CTkButton(
                chooser,
                text=label,
                width=300,
                fg_color=ModernTheme.PRIMARY_SURFACE,
                hover_color=ModernTheme.PRIMARY_SURFACE_HOVER,
                text_color="#ffffff",
                command=lambda m=mode: self._launch_import(m, chooser),
            )
            button.pack(pady=6)
            bind_keyboard_activation(
                button, lambda m=mode: self._launch_import(m, chooser)
            )
        chooser.bind("<Escape>", lambda e: chooser.destroy())

    def _launch_import(self, mode, chooser):
        if mode not in ("property", "assessment") or not self._can_manage(
            "import_data"
        ):
            return
        chooser.destroy()
        ImportWizardModal(
            self.container.winfo_toplevel(),
            mode=mode,
            on_complete=self.refresh_table,
        )

    def _show_import_summary(self, res):
        if "error" in res:
            messagebox.showerror("Import Failed", res["error"])
            return

        msg = f"✅ Import Complete!\n\nInserted: {res['inserted']}\nUpdated: {res['updated']}\nFailed: {res['failed']}"
        if res["errors"]:
            msg += f"\n\nFirst 5 Errors:\n" + "\n".join(res["errors"][:5])

        messagebox.showinfo("Import Summary", msg)
        self.refresh_table()

    def open_dossier(self):
        selected = self._selected_property()
        if not selected or not self._can_manage("property_view"):
            return
        property_id, td_number, _owner = selected

        if not td_number:
            messagebox.showwarning(
                "Dossier Error", "This property record is missing a TD Number."
            )
            return

        # 1. Create a subtle loading overlay
        loading = ctk.CTkToplevel(self.parent)
        loading.overrideredirect(True)
        loading.geometry("300x100")
        loading.attributes("-topmost", True)

        # Center
        sw, sh = loading.winfo_screenwidth(), loading.winfo_screenheight()
        loading.geometry(f"+{(sw-300)//2}+{(sh-100)//2}")

        ctk.CTkLabel(
            loading,
            text="📂 FETCHING PROPERTY DOSSIER...",
            font=("Segoe UI", 12, "bold"),
            text_color="#1f538d",
        ).pack(expand=True)
        loading.update()

        def show_dossier(data):
            loading.destroy()
            if selected == self._selected_property() and self._can_manage(
                "property_view"
            ):
                PropertyDossierModal(self.parent, data)

        def worker():
            try:
                # Use centralized API helper
                data = prop_svc.get_property_dossier(property_id)
                self.container.after(
                    0,
                    lambda data=data: show_dossier(data),
                )
            except Exception as e:
                self.container.after(
                    0,
                    lambda e=e: [
                        loading.destroy(),
                        messagebox.showerror("Dossier Error", str(e)),
                    ],
                )

        threading.Thread(target=worker, daemon=True).start()

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
        """Run worker_fn in a thread; show progress on btn, then open the result."""
        original_text = btn.cget("text")
        btn.configure(text="⏳ Generating...", state="disabled")

        def _run():
            try:
                path = worker_fn()

                # Ask where to save
                def _save():
                    dialog_options = assessment_roll_export_dialog_options(
                        path, export_format
                    )
                    dest = filedialog.asksaveasfilename(**dialog_options)
                    if dest:
                        shutil.copy2(path, dest)
                        if messagebox.askyesno(
                            "Export Successful",
                            f"Assessment roll saved to:\n{dest}\n\nOpen it now?",
                        ):
                            self._open_file(dest)
                    btn.configure(text=original_text, state="normal")

                self.container.after(0, _save)
            except Exception as exc:
                self.container.after(
                    0,
                    lambda e=exc: (
                        messagebox.showerror("Export Failed", str(e)),
                        btn.configure(text=original_text, state="normal"),
                    ),
                )

        threading.Thread(target=_run, daemon=True).start()

    def _export_roll_pdf(self):
        brgy = self.brgy_var.get()
        try:
            as_of_year = self._query_as_of_year()
        except ValueError as exc:
            messagebox.showerror("Invalid As of Year", str(exc))
            return

        self._export_with_feedback(
            self._pdf_btn,
            lambda: billing.download_assessment_roll_pdf(
                barangay=brgy if brgy != "ALL" else None,
                as_of_year=as_of_year,
            ),
            "pdf",
        )

    def _export_roll_excel(self):
        brgy = self.brgy_var.get()
        try:
            as_of_year = self._query_as_of_year()
        except ValueError as exc:
            messagebox.showerror("Invalid As of Year", str(exc))
            return

        self._export_with_feedback(
            self._excel_btn,
            lambda: billing.export_report_excel(
                "assessment_roll",
                barangay=brgy if brgy != "ALL" else None,
                as_of_year=as_of_year,
            ),
            "excel",
        )
