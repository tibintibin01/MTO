import re
import sys
import threading
import tkinter as tk
from math import isfinite
from pathlib import Path
from decimal import Decimal, InvalidOperation
from queue import Empty, SimpleQueue
from tkinter import ttk, messagebox

import customtkinter as ctk

import api_clients.property_service as prop_svc
import api_clients.system_service as system_svc
import api_clients.payment_service as payment_svc
import api_clients.api_helper as api
import api_clients.auth_service as auth
from api_clients.billing_service import normalize_date_input, normalize_tax_years
from ui.dossier import PropertyDossierModal
from ui.accessibility import bind_keyboard_activation
from ui.empty_state import EmptyTableState
from ui.import_wizard import ImportWizardModal
from ui.operation_feedback import (
    PALETTES, OperationBanner, SavedRecord, SaveFeedback, confirm_action,
    save_failure_feedback,
)
from theme_manager import ModernTheme
from utils import tr, format_curr
from ui_components import LoadingOverlay, ErrorDialog, AutocompleteComboBox, attach_autocomplete

def _resource_path(relative_path: str) -> Path:
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base_dir / relative_path

class PropertyPage:
    def __init__(self, parent, user=None):
        self.parent = parent
        self.user = user
        self.current_page = 0
        self.page_size = 50
        self.next_cursor = None
        self.container = ctk.CTkFrame(parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)
        self.setup_ui()
        self.fetch_barangays()

    def setup_ui(self):
        colors = {
            "panel": "#111827", "panel_alt": "#0f172a", "border": "#334155",
            "muted": "#94a3b8", "text": "#f8fafc", "blue": "#0284c7",
            "blue_hover": "#0369a1", "green": "#059669", "green_hover": "#047857",
            "amber": "#d97706", "amber_hover": "#b45309", "red": "#dc2626",
        }

        header_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        header_fr.pack(fill="x", pady=(0, 14))
        title_group = ctk.CTkFrame(header_fr, fg_color="transparent")
        title_group.pack(side="left")
        ctk.CTkLabel(title_group, text=tr("dashboard.nav.property").upper(), font=("Inter", 25, "bold"), text_color=colors["text"]).pack(anchor="w")
        ctk.CTkLabel(title_group, text="Search, review, and maintain the municipal property registry", font=("Inter", 11), text_color=colors["muted"]).pack(anchor="w", pady=(2, 0))

        import api_clients.auth_service as auth
        if auth.has_permission(self.user, "property_edit"):
            header_actions = ctk.CTkFrame(header_fr, fg_color="transparent")
            header_actions.pack(side="right")
            ctk.CTkButton(header_actions, text="BULK IMPORT", command=self.open_import_wizard, font=("Inter", 11, "bold"), fg_color=colors["blue"], hover_color=colors["blue_hover"], width=130, height=36, corner_radius=6).pack(side="left", padx=(0, 8))
            ctk.CTkButton(header_actions, text="ADD PROPERTY", command=self.open_add_modal, font=("Inter", 11, "bold"), fg_color=colors["green"], hover_color=colors["green_hover"], width=135, height=36, corner_radius=6).pack(side="left", padx=(0, 8))
            ctk.CTkButton(header_actions, text="DATA CLEANUP", command=self.open_bulk_update, font=("Inter", 11, "bold"), fg_color=colors["amber"], hover_color=colors["amber_hover"], width=135, height=36, corner_radius=6).pack(side="left")

        filter_bar = ctk.CTkFrame(self.container, fg_color=colors["panel"], corner_radius=8, border_width=1, border_color=colors["border"])
        filter_bar.pack(fill="x", pady=(0, 12))
        search_group = ctk.CTkFrame(filter_bar, fg_color="transparent")
        search_group.pack(side="left", padx=(14, 10), pady=12)
        ctk.CTkLabel(search_group, text="FIND PROPERTY", font=("Inter", 10, "bold"), text_color=colors["muted"]).pack(side="left", padx=(0, 8))
        self.search_ent = ctk.CTkEntry(search_group, placeholder_text="TD number, previous TD, or owner name...", width=330, height=34, font=("Inter", 11), fg_color=colors["panel_alt"], border_color=colors["border"])
        self.search_ent.pack(side="left")
        self.search_ent.bind("<Return>", lambda e: self.refresh_table())
        self.search_ent.bind("<KP_Enter>", lambda e: self.refresh_table())
        ctk.CTkButton(search_group, text="SEARCH", command=self.refresh_table, width=92, height=34, font=("Inter", 10, "bold"), fg_color=colors["blue"], hover_color=colors["blue_hover"], corner_radius=6).pack(side="left", padx=(7, 0))

        ctk.CTkFrame(filter_bar, width=1, height=32, fg_color=colors["border"]).pack(side="left", padx=(0, 10), pady=12)
        filter_group = ctk.CTkFrame(filter_bar, fg_color="transparent")
        filter_group.pack(side="left", pady=12)
        ctk.CTkLabel(filter_group, text=tr("property.filters.barangay").upper(), font=("Inter", 9, "bold"), text_color=colors["muted"]).pack(side="left", padx=(0, 5))
        self.barangay_cmb = ctk.CTkComboBox(filter_group, values=["ALL"], width=155, height=34, font=("Inter", 10), fg_color=colors["panel_alt"], border_color=colors["border"], button_color=colors["border"])
        self.barangay_cmb.pack(side="left", padx=(0, 12))
        self.barangay_cmb.bind("<Return>", lambda e: self.refresh_table())
        self.barangay_cmb.bind("<KP_Enter>", lambda e: self.refresh_table())
        ctk.CTkLabel(filter_group, text="YEAR", font=("Inter", 9, "bold"), text_color=colors["muted"]).pack(side="left", padx=(0, 5))
        self.year_start_ent = ctk.CTkEntry(filter_group, width=76, height=34, placeholder_text="From", font=("Inter", 10), fg_color=colors["panel_alt"], border_color=colors["border"])
        self.year_start_ent.pack(side="left")
        self.year_start_ent.bind("<Return>", lambda e: self.refresh_table())
        self.year_start_ent.bind("<KP_Enter>", lambda e: self.refresh_table())
        ctk.CTkLabel(filter_group, text="TO", font=("Inter", 9, "bold"), text_color=colors["muted"]).pack(side="left", padx=6)
        self.year_end_ent = ctk.CTkEntry(filter_group, width=76, height=34, placeholder_text="To", font=("Inter", 10), fg_color=colors["panel_alt"], border_color=colors["border"])
        self.year_end_ent.pack(side="left", padx=(0, 8))
        self.year_end_ent.bind("<Return>", lambda e: self.refresh_table())
        self.year_end_ent.bind("<KP_Enter>", lambda e: self.refresh_table())
        ctk.CTkButton(filter_group, text="APPLY", command=self.refresh_table, width=80, height=34, font=("Inter", 10, "bold"), fg_color=colors["green"], hover_color=colors["green_hover"], corner_radius=6).pack(side="left")

        table_fr = ctk.CTkFrame(self.container, fg_color=colors["panel_alt"], corner_radius=8, border_width=1, border_color=colors["border"])
        table_fr.pack(fill="both", expand=True)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Prop.Treeview", rowheight=34, font=("Inter", 11), background="#0f172a", fieldbackground="#0f172a", foreground="#e2e8f0", borderwidth=0)
        style.configure("Prop.Treeview.Heading", font=("Inter", 10, "bold"), background="#334155", foreground="#f8fafc", borderwidth=0, relief="flat", padding=(8, 8))
        style.map("Prop.Treeview", background=[("selected", colors["blue"])], foreground=[("selected", "#ffffff")])
        style.configure("Prop.Vertical.TScrollbar", background="#475569", troughcolor="#0f172a", bordercolor="#0f172a", arrowcolor="#cbd5e1")

        self.cols = (tr("property.table.id"), tr("property.table.td"), tr("property.table.owner"), tr("property.table.location"), tr("property.table.value"), tr("property.table.penalty"), tr("property.table.discount"), tr("property.table.due"), "STATUS")
        self.tree = ttk.Treeview(table_fr, columns=self.cols, show="headings", style="Prop.Treeview")
        for col in self.cols:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, anchor="center", width=110)
        self.tree.column(tr("property.table.id"), width=0, stretch=tk.NO)
        self.tree.column(tr("property.table.td"), width=155)
        self.tree.column(tr("property.table.owner"), width=300, anchor="w")
        self.tree.column(tr("property.table.location"), width=160, anchor="w")
        self.tree.column("STATUS", width=175, anchor="center")
        scrolly = ttk.Scrollbar(table_fr, orient="vertical", command=self.tree.yview, style="Prop.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrolly.set)
        self.tree.tag_configure(
            "duplicate_td", background="#3b2a16", foreground="#fef3c7"
        )
        scrolly.pack(side="right", fill="y", pady=1, padx=(0, 1))
        self.tree.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        self.empty_state = EmptyTableState(
            table_fr,
            "Search by TD number, previous TD, or owner name to view properties.",
        )

        footer = ctk.CTkFrame(self.container, fg_color=colors["panel"], corner_radius=8, border_width=1, border_color=colors["border"])
        footer.pack(fill="x", pady=(12, 0))
        self.prev_btn = ctk.CTkButton(footer, text="PREVIOUS", command=self.prev_page, width=105, height=34, fg_color="#334155", hover_color="#475569", font=("Inter", 10, "bold"), corner_radius=6)
        self.prev_btn.pack(side="left", padx=12, pady=10)
        self.page_lbl = ctk.CTkLabel(footer, text="PAGE 1", font=("Inter", 10, "bold"), text_color="#cbd5e1")
        self.page_lbl.pack(side="left", expand=True)
        self.next_btn = ctk.CTkButton(footer, text="NEXT", command=self.next_page, width=105, height=34, fg_color="#334155", hover_color="#475569", font=("Inter", 10, "bold"), corner_radius=6)
        self.next_btn.pack(side="right", padx=(8, 12), pady=10)
        if auth.has_permission(self.user, "property_edit"):
            self.edit_btn = ctk.CTkButton(footer, text="EDIT", command=self.open_edit_modal, width=100, height=34, fg_color=colors["blue"], hover_color=colors["blue_hover"], font=("Inter", 10, "bold"), corner_radius=6, state="disabled")
            self.edit_btn.pack(side="right", pady=10)
        if auth.has_permission(self.user, "property_delete"):
            self.del_btn = ctk.CTkButton(footer, text="DELETE", command=self.confirm_delete, width=100, height=34, fg_color=colors["red"], hover_color="#b91c1c", font=("Inter", 10, "bold"), corner_radius=6, state="disabled")
            self.del_btn.pack(side="right", padx=(8, 8), pady=10)

        self.tree.bind("<<TreeviewSelect>>", self.on_selection_change)
        self.tree.bind("<Double-1>", lambda e: self.open_dossier())

    def on_selection_change(self, event=None):
        has_sel = bool(self.tree.selection())
        if hasattr(self, "edit_btn"): self.edit_btn.configure(state="normal" if has_sel else "disabled")
        if hasattr(self, "del_btn"): self.del_btn.configure(state="normal" if has_sel else "disabled")

    def refresh_table(self, reset_page=True):
        if reset_page: self.current_page = 0
        overlay = LoadingOverlay(self.container, "Loading Properties...")
        def worker():
            try:
                term = self.search_ent.get().strip()
                brgy = self.barangay_cmb.get()
                year_start_raw = self.year_start_ent.get().strip() if hasattr(self, "year_start_ent") else ""
                year_end_raw = self.year_end_ent.get().strip() if hasattr(self, "year_end_ent") else ""
                year_start = int(year_start_raw) if year_start_raw.isdigit() else None
                year_end = int(year_end_raw) if year_end_raw.isdigit() else None
                exact_td_search = "-" in term
                res = prop_svc.search_properties(
                    term,
                    limit=self.page_size,
                    cursor=self.next_cursor if not reset_page else None,
                    barangay=None if exact_td_search else brgy if brgy != "ALL" else None,
                    kind=None,
                    year_start=None if exact_td_search else year_start,
                    year_end=None if exact_td_search else year_end,
                )
                items = res.get("items", [])
                self.next_cursor = res.get("next_cursor")
                has_more = res.get("has_more", False)
                self.container.after(0, lambda: self._update_table(items, has_more))
            except Exception as e:
                def show_error(err=e):
                    if not self.tree.get_children():
                        self.empty_state.show(
                            "Check the connection and try the search again.",
                            title="Unable to load properties",
                        )
                    messagebox.showerror("Error", str(err))
                self.container.after(0, show_error)
            finally: self.container.after(0, lambda: overlay.hide())
        threading.Thread(target=worker, daemon=True).start()

    def _update_table(self, results, has_more=False):
        self.page_lbl.configure(text=f"PAGE {self.current_page + 1}")
        self.prev_btn.configure(state="normal" if self.current_page > 0 else "disabled")
        self.next_btn.configure(state="normal" if has_more else "disabled")
        for item in self.tree.get_children(): self.tree.delete(item)
        if results:
            self.empty_state.hide()
        else:
            self.empty_state.show(
                "Try another TD number, owner name, barangay, or year filter."
                if self.current_page == 0 else "Go back a page or change the search filters.",
                title="No matching properties" if self.current_page == 0 else "No records on this page",
            )
        td_counts = {}
        for row in results:
            normalized_td = str(row[1] or "").strip().upper()
            td_counts[normalized_td] = td_counts.get(normalized_td, 0) + 1
        for r in results:
            normalized_td = str(r[1] or "").strip().upper()
            verified = bool(r[23]) if len(r) > 23 else False
            duplicate_on_page = td_counts.get(normalized_td, 0) > 1
            tags = ("duplicate_td",) if verified or duplicate_on_page else ()
            status = (
                "⚠ VERIFIED DUPLICATE"
                if verified
                else "⚠ REVIEW DUPLICATE"
                if duplicate_on_page
                else "STANDARD"
            )
            self.tree.insert("", "end", values=(r[0], r[1], r[2], r[6], format_curr(r[9]), format_curr(r[12]), format_curr(r[13]), format_curr(r[14]), status), tags=tags)
        self.on_selection_change()

    def fetch_barangays(self):
        def worker():
            try:
                brgys = prop_svc.get_barangays()
                if brgys: self.container.after(0, lambda: self.barangay_cmb.configure(values=["ALL"] + brgys))
            except: pass
        threading.Thread(target=worker, daemon=True).start()

    def next_page(self):
        self.current_page += 1
        self.refresh_table(reset_page=False)

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh_table(reset_page=False)

    def open_add_modal(self): PropertyEditModal(self.parent, "Add Property", None, self.refresh_table, user=self.user)
    def open_edit_modal(self):
        sel = self.tree.selection()
        if sel: PropertyEditModal(self.parent, "Edit Property", self.tree.item(sel[0])["values"][0], self.refresh_table, user=self.user)
    def open_import_wizard(self): ImportWizardModal(self.container.winfo_toplevel())
    def open_bulk_update(self): BulkBarangayUpdateModal(self.parent, self.refresh_table)
    def open_dossier(self):
        sel = self.tree.selection()
        if not sel: return
        values = self.tree.item(sel[0])["values"]
        property_id = int(values[0])
        td = str(values[1]).strip()
        overlay = LoadingOverlay(self.container, "📂 FETCHING DOSSIER...")
        def worker():
            try:
                data = prop_svc.get_property_dossier(property_id)
                self.container.after(0, lambda: [overlay.hide(), PropertyDossierModal(self.parent, data)])
            except Exception as e: self.container.after(0, lambda err=e: [overlay.hide(), messagebox.showerror("Error", str(err))])
        threading.Thread(target=worker, daemon=True).start()

    def confirm_delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0])["values"]
        owner_name = vals[2] if len(vals) > 2 else "this property"
        td_number  = vals[1] if len(vals) > 1 else ""

        # Premium confirm dialog
        result = tk.BooleanVar(value=False)
        dlg = ctk.CTkToplevel(self.container)
        dlg.title("")
        dlg.resizable(False, False)
        dlg.overrideredirect(True)
        dlg.attributes("-topmost", True)

        dw, dh = 420, 260
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"{dw}x{dh}+{(sw-dw)//2}+{(sh-dh)//2}")

        outer = ctk.CTkFrame(dlg, fg_color="#0f172a", corner_radius=16,
                             border_width=1, border_color="#1e293b")
        outer.pack(fill="both", expand=True, padx=2, pady=2)
        ctk.CTkFrame(outer, height=5, fg_color="#dc2626", corner_radius=0).pack(fill="x")

        icon_row = ctk.CTkFrame(outer, fg_color="transparent")
        icon_row.pack(pady=(16, 0))
        icon_fr = ctk.CTkFrame(icon_row, width=50, height=50, corner_radius=25,
                               fg_color="#1e293b", border_width=2, border_color="#ef4444")
        icon_fr.pack()
        icon_fr.pack_propagate(False)
        ctk.CTkLabel(icon_fr, text="🗑️", font=("Segoe UI Emoji", 18),
                     text_color="#ef4444").place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(outer, text="Delete Property",
                     font=("Inter", 14, "bold"), text_color="#f1f5f9").pack(pady=(8, 2))
        ctk.CTkLabel(outer,
                     text=f"{owner_name}\n{td_number}",
                     font=("Inter", 11), text_color="#94a3b8", justify="center").pack()
        ctk.CTkLabel(outer,
                     text="This property will be moved to the Recycle Bin.",
                     font=("Inter", 10), text_color="#64748b", justify="center").pack(pady=(4, 0))

        ctk.CTkFrame(outer, height=1, fg_color="#1e293b").pack(fill="x", padx=20, pady=(10, 0))

        btn_fr = ctk.CTkFrame(outer, fg_color="transparent")
        btn_fr.pack(pady=12)

        def on_cancel():
            result.set(False)
            dlg.grab_release()
            dlg.destroy()

        def on_confirm():
            result.set(True)
            dlg.grab_release()
            dlg.destroy()

        ctk.CTkButton(btn_fr, text="CANCEL", command=on_cancel,
                      fg_color="#1e293b", hover_color="#334155", text_color="#94a3b8",
                      border_width=1, border_color="#334155",
                      font=("Inter", 12, "bold"), width=120, height=36, corner_radius=8,
                      ).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_fr, text="DELETE", command=on_confirm,
                      fg_color="#dc2626", hover_color="#b91c1c", text_color="white",
                      font=("Inter", 12, "bold"), width=120, height=36, corner_radius=8,
                      ).pack(side="left")

        dlg.bind("<Return>", lambda e: on_confirm())
        dlg.bind("<Escape>", lambda e: on_cancel())
        dlg.update_idletasks()
        dlg.lift()
        dlg.focus_force()
        dlg.grab_set()
        dlg.wait_window()

        if not result.get():
            return

        try:
            res = prop_svc.delete_property(vals[0], user=self.user)
            if not isinstance(res, dict) or res.get("status") != "deleted":
                raise Exception("Delete was not confirmed by the server. Please try again.")
            self.refresh_table()
            deleted_at = res.get("deleted_at") or "now"
            messagebox.showinfo(
                "Moved to Recycle Bin",
                f"{owner_name}\n{td_number}\n\nDeleted at: {deleted_at}",
            )
        except Exception as e:
            messagebox.showerror("Delete Failed", str(e))

class PropertyEditModal(ctk.CTkToplevel):
    def __init__(self, parent, title, property_id, callback, user=None, payment_mode=False, *, on_saved=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("600x750")
        self.property_id = property_id
        self.callback = callback
        self.on_saved = on_saved
        self.user = user
        self.payment_mode = payment_mode
        self.vars = {}
        self._loaded_version = None
        self._original_prev_td = ""
        self._original_td = ""
        self._loaded_duplicate_verified = False
        self._selected_previous_property_id = None
        self._first_input = None
        self._last_input = None
        self._field_entries = []
        self._field_entries_by_key = {}
        self._payment_origin = None
        self._payment_revision = 0
        self._payment_preview_timer = None
        self._payment_poll_timer = None
        self._payment_preview_pending = False
        self._payment_results = SimpleQueue()
        self._payment_date_finished = False
        self._payment_net_due = None
        self._applying_payment_preview = False
        self._suggested_amount = False
        self._edited_adjustments = False
        self._save_feedback = None
        self._save_field_hint = None
        self._save_locked = False
        self._duplicate_check_timer = None
        self.barangays = ["NORTH POBLACION", "SOUTH POBLACION", "BAYABAS", "BORLONGAN", "BUENAVISTA", "CALAOCAN", "DIAMANEN", "DIANED", "DIARABASIN", "DIBUTUNAN", "DIMABUNO", "DINADIAWAN", "DITALE", "GUPA", "IPIL", "LABOY", "LIPIT", "LOBBOT", "MALIGAYA", "MIJARES", "MUCDOL", "PUANGI", "SALAY", "SAPANGKAWAYAN", "TOYTOYAN"]
        self.duplicate_policy = {"enabled": False, "admin_authorized": False}
        if not self.payment_mode and auth.get_user_role(self.user) == "admin":
            try:
                self.duplicate_policy = prop_svc.get_duplicate_td_policy() or self.duplicate_policy
            except Exception:
                pass

        # Generate a fresh idempotency key when the form opens — NOT on submit.
        # This ensures every submission attempt for this form session uses the
        # same key, so double-clicks and retries are deduplicated by the server.
        import uuid
        self._idempotency_key = str(uuid.uuid4())
        
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-600)//2}+{(sh-750)//2}")
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)
        self._apply_window_icon()
        self.setup_ui()
        self._bind_keyboard_shortcuts()
        prop = self.load_data() if self.property_id else None
        if self.payment_mode:
            self._prepare_payment_entry(prop)
        elif not self.property_id:
            self.validate()
        elif prop is None:
            self._save_locked = True
            self.validate()
            self._show_save_feedback(SaveFeedback(
                "error", "Property could not be loaded",
                "Close this form, refresh the Assessment Roll, and reopen the property before editing.",
            ))
        self._initial_input_values = self._form_input_values()
        self.protocol("WM_DELETE_WINDOW", self._request_close)
        self.bind("<Escape>", self._request_close)

    def _apply_window_icon(self):
        icon_path = _resource_path("assets/official/app_icon.ico")
        if not icon_path.exists():
            return

        def set_icon():
            if self.winfo_exists():
                try:
                    self.iconbitmap(str(icon_path))
                except Exception:
                    pass

        self.after(50, set_icon)

    def _focus_widget(self, widget):
        if widget and widget.winfo_exists():
            widget.focus_set()
        return "break"

    def setup_ui(self):
        self.configure(fg_color=(ModernTheme.BG_LIGHT, ModernTheme.BG_DARK))
        # A scrollable frame packs its outer wrapper, not the inner canvas child.
        # Use our own packed sibling as the status banner's insertion anchor.
        scroll_host = ctk.CTkFrame(self, fg_color="transparent")
        scroll_host.pack(fill="both", expand=True, padx=20, pady=(20, 10))
        self.scroll_form = ctk.CTkScrollableFrame(scroll_host, fg_color=(ModernTheme.CARD_LIGHT, ModernTheme.CARD_DARK), corner_radius=10)
        self.scroll_form.pack(fill="both", expand=True)

        fields = [
            ("TD Number", "td_number"),
            ("Owner Name", "owner_name"),
            ("PIN", "pin"),
            ("Lot Number", "lot_number"),
            ("Area", "area"),
            ("Location", "location"),
            ("Kind", "kind_of_property"),
            ("Previous TD", "prev_td_number"),
            ("Effectivity", "effectivity_date"),
            ("Assessed Value", "assessed_value"),
        ]
        correction_fields = [
            ("Prior AV (before effectivity)", "prior_assessed_value"),
            ("Prior AV effective year", "prior_effectivity_year"),
        ]
        payment_fields = [
            ("Tax Year", "tax_year"),
            ("OR Number", "or_number"),
            ("OR Date", "or_date"),
            ("Penalty", "penalty"),
            ("Discount", "discount"),
            ("Amount Paid", "amount_paid"),
            ("Remarks", "remarks"),
        ]

        for _, key in fields + correction_fields + payment_fields:
            self.vars[key] = tk.StringVar()
        self.vars["duplicate_td_reason"] = tk.StringVar()
        self.vars["duplicate_td_reference"] = tk.StringVar()
        self.duplicate_td_var = tk.BooleanVar(value=False)

        visible_fields = fields + payment_fields if self.payment_mode else fields + correction_fields

        def _scroll_to_widget(widget):
            """
            Scrolls the CTkScrollableFrame so the focused widget is fully visible.
            Called on FocusIn so tabbing to any field — especially Tax Year at
            the bottom — automatically brings it into view without mouse scrolling.
            """
            try:
                # CTkScrollableFrame wraps a tk.Canvas internally
                canvas = self.scroll_form._parent_canvas
                # Get widget position relative to the canvas
                widget.update_idletasks()
                wy = widget.winfo_y()
                wh = widget.winfo_height()
                ch = canvas.winfo_height()
                # Total scrollable height
                scroll_region = canvas.cget("scrollregion")
                if not scroll_region:
                    return
                total_h = float(scroll_region.split()[3])
                if total_h <= 0:
                    return
                # Target: centre the widget vertically in the visible area
                target_top = wy - (ch // 2) + (wh // 2)
                target_top = max(0, min(target_top, total_h - ch))
                canvas.yview_moveto(target_top / total_h)
            except Exception:
                pass

        for label, key in visible_fields:
            ctk.CTkLabel(self.scroll_form, text=label.upper(), font=("Segoe UI", 9, "bold"), text_color="gray").pack(anchor="w", padx=10, pady=(10, 0))
            if key == "location":
                entry = ctk.CTkEntry(self.scroll_form, height=40, textvariable=self.vars[key],
                                     placeholder_text="Type barangay name...")
                entry.pack(fill="x", padx=10, pady=(0, 5))
                entry.bind("<FocusIn>", lambda e, w=entry: self.after_idle(_scroll_to_widget, w))
                if not self.payment_mode:
                    attach_autocomplete(entry, self.barangays, self.vars[key])
            else:
                placeholder = (
                    "e.g. 2027"
                    if key in ("effectivity_date", "prior_effectivity_year")
                    else "e.g. 06-0012-01780"
                    if key == "prev_td_number"
                    else "Optional; corrects years before current effectivity"
                    if key == "prior_assessed_value"
                    else ""
                )
                entry = ctk.CTkEntry(self.scroll_form, height=40, textvariable=self.vars[key], placeholder_text=placeholder)
                entry.pack(fill="x", padx=10, pady=(0, 5))
                entry.bind("<FocusIn>", lambda e, w=entry: self.after_idle(_scroll_to_widget, w))
            if self.payment_mode:
                if key in {"tax_year", "or_number", "or_date"}:
                    self.vars[key].trace_add("write", lambda *a, field=key: self._payment_input_changed(field))
                elif key in {"penalty", "discount", "amount_paid"}:
                    self.vars[key].trace_add("write", lambda *a, field=key: self._payment_amount_changed(field))
                elif key != "remarks":
                    # These fields identify the account; payment posting does not edit them.
                    entry.configure(state="readonly")
                if key == "or_date":
                    entry.bind("<FocusOut>", self._finish_payment_date)
                    self._setup_payment_preview_status()
                elif key == "amount_paid":
                    ctk.CTkLabel(
                        self.scroll_form,
                        text="Enter the actual cash received. For a partial payment, enter this installment only.",
                        wraplength=480, justify="left", font=("Segoe UI", 10),
                    ).pack(anchor="w", padx=10, pady=(0, 3))
            else:
                self.vars[key].trace_add("write", self.validate)
            if self._first_input is None:
                self._first_input = entry
            self._last_input = entry
            self._field_entries.append(entry)
            self._field_entries_by_key[key] = entry
            self.vars[key].trace_add("write", lambda *args, field=key: self._clear_save_feedback_for(field))

        if not self.payment_mode and auth.get_user_role(self.user) == "admin":
            enabled = bool(self.duplicate_policy.get("enabled"))
            duplicate_box = ctk.CTkFrame(
                self.scroll_form,
                fg_color="#3b2a16",
                border_width=1,
                border_color="#d97706",
                corner_radius=8,
            )
            duplicate_box.pack(fill="x", padx=10, pady=(14, 4))
            self.duplicate_checkbox = ctk.CTkCheckBox(
                duplicate_box,
                text="AUTHORIZED DUPLICATE TD (ADMIN ONLY)",
                variable=self.duplicate_td_var,
                font=("Inter", 10, "bold"),
                text_color="#fbbf24",
                state="normal" if enabled else "disabled",
            )
            self.duplicate_checkbox.pack(anchor="w", padx=12, pady=(10, 4))
            pilot_td = str(self.duplicate_policy.get("pilot_td") or "").strip()
            if enabled and pilot_td:
                policy_text = (
                    f"CONTROLLED PILOT: only TD {pilot_td} may be authorized. "
                    "All other duplicate TDs remain blocked until pilot approval."
                )
            elif enabled:
                policy_text = (
                    "Use only for an Assessor-confirmed duplicate active TD. "
                    "Payments remain separate by internal property account."
                )
            else:
                policy_text = "Controlled duplicate creation is installed but not activated on this server."
            ctk.CTkLabel(
                duplicate_box,
                text=policy_text,
                wraplength=500,
                justify="left",
                font=("Inter", 9),
                text_color="#fde68a",
            ).pack(anchor="w", padx=12, pady=(0, 8))
            for label, key, placeholder in (
                ("ASSESSOR REFERENCE", "duplicate_td_reference", "Assessment record, memo, or reference number"),
                ("REASON", "duplicate_td_reason", "Explain why the duplicate active TD is legitimate"),
            ):
                ctk.CTkLabel(
                    duplicate_box,
                    text=label,
                    font=("Inter", 9, "bold"),
                    text_color="#fef3c7",
                ).pack(anchor="w", padx=12)
                entry = ctk.CTkEntry(
                    duplicate_box,
                    textvariable=self.vars[key],
                    placeholder_text=placeholder,
                    height=36,
                    state="normal" if enabled else "disabled",
                )
                entry.pack(fill="x", padx=12, pady=(2, 8))

        if self.payment_mode:
            calc_box = ctk.CTkFrame(self.scroll_form, fg_color=(ModernTheme.BG_LIGHT, ModernTheme.BG_DARK), corner_radius=8)
            calc_box.pack(fill="x", padx=10, pady=15)
            self.total_lbl = ctk.CTkLabel(calc_box, text="CALCULATED ANNUAL DUE: —", font=("Segoe UI", 12, "bold"))
            self.total_lbl.pack(anchor="w", padx=10, pady=(10, 2))
            self._payment_breakdown = ctk.CTkLabel(
                calc_box, text="", wraplength=490, justify="left", anchor="w",
                font=("Segoe UI", 10),
            )
            self._payment_breakdown.pack(fill="x", padx=10, pady=(0, 8))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=20, pady=20)
        self.cancel_btn = ctk.CTkButton(footer, text="CANCEL", command=self._request_close, fg_color="#95a5a6", width=120)
        self.cancel_btn.pack(side="left")
        self.save_btn = ctk.CTkButton(footer, text="SAVE PROPERTY", command=self.save, fg_color="#2ecc71", width=200, state="disabled")
        self.save_btn.pack(side="right")
        self._save_banner = OperationBanner(
            self, before=footer if self.payment_mode else scroll_host, padx=20
        )
        cancel_focus = bind_keyboard_activation(self.cancel_btn, self._request_close)
        cancel_focus.bind("<KP_Enter>", self._request_close)
        action_focus = self._save_banner.action_focus
        action_focus.bind("<Tab>", lambda e: self._focus_widget(cancel_focus))
        action_focus.bind("<Shift-Tab>", lambda e: self._focus_widget(self._last_input))

        if self._last_input:
            self._last_input.bind("<Tab>", lambda e: self._focus_widget(
                action_focus if self._save_banner.has_action else cancel_focus
            ))
        cancel_focus.bind("<Tab>", lambda e: self._focus_widget(self.save_btn))
        cancel_focus.bind("<Shift-Tab>", lambda e: self._focus_widget(
            action_focus if self._save_banner.has_action else self._last_input
        ))
        self.save_btn.bind("<Tab>", lambda e: self._focus_widget(self._first_input))
        self.save_btn.bind("<Shift-Tab>", lambda e: self._focus_widget(cancel_focus))
        self.save_btn.bind("<Return>", lambda e: self._submit_from_keyboard())
        self.save_btn.bind("<KP_Enter>", lambda e: self._submit_from_keyboard())
        self._bind_enter_navigation()

    def _bind_keyboard_shortcuts(self):
        self.bind("<Return>", lambda e: self._submit_from_keyboard())
        self.bind("<KP_Enter>", lambda e: self._submit_from_keyboard())

    def _bind_enter_navigation(self):
        for entry in self._field_entries:
            for widget in (entry, getattr(entry, "_entry", None)):
                if widget:
                    widget.bind("<Return>", lambda e, w=entry: self._focus_next_entry(w))
                    widget.bind("<KP_Enter>", lambda e, w=entry: self._focus_next_entry(w))

    def _focus_next_entry(self, current):
        ordered = [w for w in self._field_entries if w and w.winfo_exists()]
        try:
            index = ordered.index(current)
        except ValueError:
            return "break"

        if index + 1 < len(ordered):
            next_widget = ordered[index + 1]
        else:
            next_widget = self.save_btn

        self.after_idle(lambda: self._focus_widget(next_widget))
        return "break"

    def _focus_and_select_field(self, key):
        entry = self._field_entries_by_key.get(key)
        if not entry:
            return

        def apply_focus():
            if not self.winfo_exists() or not entry.winfo_exists():
                return
            self._focus_widget(entry)
            for widget in (entry, getattr(entry, "_entry", None)):
                if not widget:
                    continue
                try:
                    widget.select_range(0, "end")
                    widget.icursor("end")
                except Exception:
                    try:
                        widget.selection_range(0, "end")
                        widget.icursor("end")
                    except Exception:
                        pass

        self.after(150, apply_focus)

    def _submit_from_keyboard(self):
        try:
            if self.save_btn.cget("state") == "disabled":
                return "break"
        except Exception:
            pass
        self.save()
        return "break"

    def _setup_payment_preview_status(self):
        row = ctk.CTkFrame(self.scroll_form, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 4))
        self._compute_lbl = ctk.CTkLabel(
            row, text="", wraplength=390, anchor="w", justify="left",
            font=("Segoe UI", 11),
        )
        self._compute_lbl.pack(side="left", fill="x", expand=True)
        self._compute_btn = ctk.CTkButton(
            row, text="Recalculate", command=self._recalculate_payment,
            width=100, height=28, state="disabled",
        )
        self._compute_btn.pack(side="right", padx=(8, 0))
        self._compute_btn.bind("<Return>", lambda e: self._recalculate_from_keyboard())
        self._compute_btn.bind("<KP_Enter>", lambda e: self._recalculate_from_keyboard())

    def _recalculate_from_keyboard(self):
        if self._compute_btn.cget("state") == "normal":
            self._recalculate_payment()
        return "break"

    def _prepare_payment_entry(self, prop):
        """Start with blank receipt fields and retain the original account selection."""
        self.title("Add Payment")
        self.save_btn.configure(text="SAVE PAYMENT")
        if (
            isinstance(prop, dict)
            and prop.get("id") == int(self.property_id or 0)
            and self.vars["td_number"].get().strip()
        ):
            self._payment_origin = prop
        self._queue_payment_preview()
        self._focus_and_select_field("tax_year")

    @staticmethod
    def _payment_number(value):
        return float(str(value).replace(",", "").strip())

    def _payment_preview_inputs(self):
        if not self._payment_origin:
            return (), "", "No property account is loaded. Close and reopen Add Payment."
        year_text = self.vars["tax_year"].get().strip()
        or_number = self.vars["or_number"].get().strip()
        date_text = self.vars["or_date"].get().strip()
        if not re.fullmatch(r"[0-9,;\s-]+", year_text):
            return (), "", "Enter a valid Tax Year to calculate."
        years = normalize_tax_years(year_text)
        if not years or not all(re.fullmatch(r"[0-9]{4}", year) and int(year) for year in years):
            return (), "", "Enter a valid Tax Year to calculate."
        if not or_number or not date_text:
            return (), "", "Enter OR Number and OR Date to calculate."
        date = normalize_date_input(date_text)
        if not date:
            return (), "", "Enter a valid OR Date (YYYY-MM-DD)."
        return tuple(int(year) for year in years), date, ""

    def _finish_payment_date(self, event=None):
        if self._payment_date_finished:
            return
        self._payment_date_finished = True
        self._queue_payment_preview()

    def _payment_input_changed(self, field):
        if field == "or_date":
            self._payment_date_finished = False
        self._invalidate_payment_preview()
        if field == "tax_year" and self._payment_origin:
            # Resolve every new year from the original selection, not a previously
            # redirected account that could have its own same-year billing.
            origin_id = self._payment_origin["id"]
            if self.property_id != origin_id:
                self.property_id = origin_id
                self._apply_property_data(self._payment_origin)
        self._queue_payment_preview()

    def _invalidate_payment_preview(self):
        self._payment_revision += 1
        self._payment_preview_pending = False
        if self._payment_preview_timer is not None:
            self.after_cancel(self._payment_preview_timer)
            self._payment_preview_timer = None
        self._payment_net_due = None
        self._edited_adjustments = False
        self._applying_payment_preview = True
        try:
            for key in ("penalty", "discount"):
                self.vars[key].set("")
            self._clear_suggested_amount()
        finally:
            self._applying_payment_preview = False
        self.total_lbl.configure(text="CALCULATED ANNUAL DUE: —")
        self._payment_breakdown.configure(text="")

    def _clear_suggested_amount(self):
        if self._suggested_amount:
            self._suggested_amount = False
            self.vars["amount_paid"].set("")

    def _queue_payment_preview(self):
        years, date, problem = self._payment_preview_inputs()
        self._update_payment_preview_controls(years)
        if problem:
            self._compute_lbl.configure(text=problem)
        elif not self._payment_date_finished:
            self._compute_lbl.configure(text="Press Tab or leave OR Date to calculate.")
        elif len(years) > 1:
            self._compute_lbl.configure(text="Multiple tax years: enter adjustments and Amount Paid manually.")
            self.total_lbl.configure(text="NO AUTOMATIC TOTAL FOR MULTIPLE TAX YEARS")
        else:
            self._compute_lbl.configure(text="Calculating…")
            self._payment_preview_timer = self.after(
                300, self._start_payment_preview, self._payment_revision, years[0], date,
            )

    def _recalculate_payment(self):
        years, date, _ = self._payment_preview_inputs()
        if len(years) != 1 or self._payment_preview_pending:
            return
        self._payment_date_finished = True
        self._invalidate_payment_preview()
        self._start_payment_preview(self._payment_revision, years[0], date)

    def _start_payment_preview(self, revision, year, date):
        self._payment_preview_timer = None
        self._payment_preview_pending = True
        self._compute_lbl.configure(text="Calculating…")
        self._update_payment_preview_controls((year,))
        origin = self._payment_origin
        results = self._payment_results

        def worker():
            # No Tk access from this thread. Only the main loop renders results.
            try:
                target = prop_svc.resolve_payment_target(
                    origin["td_number"], year, property_id=int(origin["id"]),
                )
                target_id = int(target["id"])
                prop = origin if target_id == int(origin["id"]) else (
                    prop_svc.get_property_by_id(target_id, require_fresh=True)
                )
                if target_id <= 0 or int(prop["id"]) != target_id or prop["td_number"] != target["td_number"]:
                    raise ValueError("Payment account could not be verified.")
                av = PropertyEditModal._payment_number(prop["assessed_value"])
                if not isfinite(av) or av < 0:
                    raise ValueError("Invalid assessed value.")
                preview = system_svc.compute_payment(av, year, date, property_id=target_id)
                amounts = tuple(
                    float(preview[key])
                    for key in ("penalty_amount", "discount_amount", "net_amount_due")
                )
                if any(not isfinite(amount) or amount < 0 for amount in amounts):
                    raise ValueError("Invalid calculated amount.")
                results.put((revision, (prop, amounts, str(preview.get("breakdown") or ""))))
            except Exception:
                results.put((revision, None))

        threading.Thread(target=worker, daemon=True).start()
        if self._payment_poll_timer is None:
            self._payment_poll_timer = self.after(75, self._poll_payment_preview)

    def _poll_payment_preview(self):
        self._payment_poll_timer = None
        while True:
            try:
                revision, preview = self._payment_results.get_nowait()
            except Empty:
                break
            if revision != self._payment_revision:
                continue
            self._payment_preview_pending = False
            if preview is None:
                self._compute_lbl.configure(
                    text="Could not calculate. Check the account and year, then choose Recalculate."
                )
            else:
                self._apply_payment_preview(*preview)
            self._update_payment_preview_controls(self._payment_preview_inputs()[0])
        if self._payment_preview_pending:
            self._payment_poll_timer = self.after(75, self._poll_payment_preview)

    def _apply_payment_preview(self, prop, amounts, breakdown):
        if int(prop["id"]) != int(self.property_id):
            self.property_id = int(prop["id"])
            self._apply_property_data(prop)
        penalty, discount, net_due = amounts
        self._payment_net_due = net_due
        kept_amount = bool(self.vars["amount_paid"].get().strip())
        self._applying_payment_preview = True
        try:
            self.vars["penalty"].set(f"{penalty:.2f}")
            self.vars["discount"].set(f"{discount:.2f}")
            if not kept_amount:
                self._suggested_amount = True
                self.vars["amount_paid"].set(f"{net_due:.2f}")
        finally:
            self._applying_payment_preview = False
        changed_account = int(self.property_id) != int(self._payment_origin["id"])
        msg = f"Updated for account #{self.property_id}."
        if changed_account:
            msg = f"Matched tax year to TD {prop['td_number']} (account #{self.property_id})."
        if kept_amount:
            msg += " Amount Paid kept; review it."
        self._compute_lbl.configure(text=msg)
        self.total_lbl.configure(text=f"CALCULATED ANNUAL DUE: {net_due:,.2f}")
        self._payment_breakdown.configure(
            text=f"{breakdown}\nPrevious payments are not deducted from this calculation.".strip()
        )

    def _update_payment_preview_controls(self, years):
        self._compute_btn.configure(
            state="normal" if len(years) == 1 and not self._payment_preview_pending else "disabled"
        )
        can_edit = self._payment_date_finished and (len(years) > 1 or self._payment_net_due is not None)
        for key in ("penalty", "discount"):
            self._field_entries_by_key[key].configure(state="normal" if can_edit else "disabled")
        self.validate()

    def _payment_amount_changed(self, field):
        if self._applying_payment_preview:
            return
        if field == "amount_paid":
            self._suggested_amount = False
        elif self._payment_net_due is not None:
            if not self._edited_adjustments:
                self._edited_adjustments = True
                self._clear_suggested_amount()
            self.total_lbl.configure(
                text=f"CALCULATED ANNUAL DUE: {self._payment_net_due:,.2f} (before edits)"
            )
            self._compute_lbl.configure(text="Adjustments edited. Review Amount Paid before saving.")
        self.validate()

    def _payment_can_save(self):
        years, _, problem = self._payment_preview_inputs()
        if problem or not self._payment_date_finished or self._payment_preview_pending:
            return False
        if len(years) == 1 and self._payment_net_due is None:
            return False
        try:
            paid = self._payment_number(self.vars["amount_paid"].get())
            adjustments = [
                self._payment_number(self.vars[key].get() or "0")
                for key in ("penalty", "discount")
            ]
        except ValueError:
            return False
        return isfinite(paid) and paid > 0 and all(isfinite(a) and a >= 0 for a in adjustments)

    def validate(self, *args):
        valid = bool(self.vars["td_number"].get().strip() and self.vars["owner_name"].get().strip() and self.vars["assessed_value"].get().strip())
        if self.payment_mode:
            valid = valid and self._payment_can_save()
        if getattr(self, "_save_locked", False):
            valid = False
        self.save_btn.configure(state="normal" if valid else "disabled")

    def destroy(self):
        for timer in (self._payment_preview_timer, self._payment_poll_timer, self._duplicate_check_timer):
            if timer is not None:
                self.after_cancel(timer)
        super().destroy()

    def _form_input_values(self):
        if self.payment_mode:
            # Server suggestions alone are not unsaved operator input.
            keys = ("tax_year", "or_number", "or_date", "remarks")
        else:
            keys = self.vars
        return tuple(self.vars[key].get() for key in keys) + (self.duplicate_td_var.get(),)

    def _request_close(self, _event=None):
        if self._form_input_values() != self._initial_input_values:
            if not confirm_action(
                self, "Discard unsaved input?",
                "Close the form and discard the values you entered. This does not undo any action already saved on the server.",
                action="Discard Input", destructive=True,
            ):
                return "break"
        self.destroy()
        return "break"

    def _clear_save_feedback_for(self, field):
        feedback = self._save_feedback
        if feedback and not self._save_locked and (
            feedback.field == field
            or (feedback.title == "Payment already recorded" and field in {"or_number", "or_date", "tax_year"})
        ):
            self._save_feedback = None
            self._save_banner.clear()
            if self._save_field_hint is not None:
                self._save_field_hint.destroy()
                self._save_field_hint = None

    def _show_save_feedback(self, feedback, *, entry=None):
        self._save_feedback = feedback
        if self._save_field_hint is not None:
            self._save_field_hint.destroy()
            self._save_field_hint = None
        field_widget = self._field_entries_by_key.get(feedback.field)
        if field_widget is not None:
            self._save_field_hint = ctk.CTkLabel(
                self.scroll_form, text=feedback.detail, text_color=PALETTES[feedback.level][1],
                wraplength=475, anchor="w", justify="left",
            )
            self._save_field_hint.pack(after=field_widget, fill="x", padx=10, pady=(0, 6))
            self._focus_and_select_field(feedback.field)
        action = None
        message = "Review the highlighted field before saving." if field_widget is not None else feedback.detail
        if feedback.duplicate_id and entry is not None:
            action = ("View Existing Payment", lambda: self._view_duplicate_payment(feedback, entry))
        elif feedback.title == "Payment already recorded":
            message += " Search for this OR in the ledger."
        self._save_banner.show(feedback.level, feedback.title, message, action=action)

    def _view_duplicate_payment(self, feedback, entry):
        if self._duplicate_check_timer is not None:
            return
        account_id, or_number, date, years = entry
        inbox = SimpleQueue()

        def fetch():
            try:
                detail = payment_svc.get_payment_receipt_details(feedback.duplicate_id, require_fresh=True)
                if (
                    str(detail.get("payment_id")) != str(feedback.duplicate_id)
                    or str(detail.get("property_id")) != str(account_id)
                    or str(detail.get("or_number")) != or_number
                    or str(detail.get("date_paid") or "")[:10] != date
                    or normalize_tax_years(detail.get("tax_year")) != years
                ):
                    raise ValueError("Receipt identity did not match the submitted entry")
                amount = Decimal(str(detail.get("amount")))
                if not amount.is_finite():
                    raise ValueError("Invalid stored amount")
                inbox.put(
                    f"On file: OR {or_number} · {date} · Tax year {', '.join(years)}\n"
                    f"Account #{account_id} · Recorded amount ₱{amount:,.2f}. No new payment was saved."
                )
            except Exception:
                inbox.put("No new payment was saved. The existing entry could not be verified here; review the ledger for this OR.")

        def poll():
            self._duplicate_check_timer = None
            if self._save_feedback is not feedback:
                return
            try:
                detail = inbox.get_nowait()
            except Empty:
                self._duplicate_check_timer = self.after(60, poll)
                return
            self._save_banner.show("warning", feedback.title, detail)

        self._save_banner.show("warning", feedback.title, "Checking the existing payment…")
        self._duplicate_check_timer = self.after(60, poll)
        threading.Thread(target=fetch, daemon=True).start()

    def load_data(self):
        try:
            prop = prop_svc.get_property_by_id(self.property_id, require_fresh=True)
            if not prop:
                return None
            self._apply_property_data(prop)
            self.validate()
            return prop
        except Exception as e: print(f"Load Error: {e}")

    def _apply_property_data(self, prop):
        fields = (
            "td_number", "owner_name", "pin", "lot_number", "area", "location",
            "kind_of_property", "prev_td_number", "effectivity_date", "assessed_value",
        )
        if isinstance(prop, dict):
            self._loaded_version = prop.get("version")
            mapping = {key: prop.get(key) for key in fields}
            self._selected_previous_property_id = prop.get("previous_property_id")
            self._loaded_duplicate_verified = bool(prop.get("duplicate_td_verified"))
            self.duplicate_td_var.set(self._loaded_duplicate_verified)
            for key in ("duplicate_td_reason", "duplicate_td_reference"):
                self.vars[key].set(str(prop.get(key) or ""))
        else:
            # Older server responses used a positional property row.
            indices = (1, 2, 18, 4, 5, 6, 7, 20, 21, 9)
            mapping = {key: prop[i] for key, i in zip(fields, indices) if len(prop) > i}
        for key, value in mapping.items():
            self.vars[key].set(str(value) if value is not None else "")
        self._original_prev_td = self.vars["prev_td_number"].get().strip().upper()
        self._original_td = self.vars["td_number"].get().strip().upper()

    def _choose_previous_property(self, td_number, matches):
        """Return the explicitly selected predecessor ID, or None on cancel."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Select Previous Property")
        dialog.geometry("900x430")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color="#0f172a")
        selected = {"id": None}

        ctk.CTkLabel(
            dialog,
            text="SELECT THE EXACT PREVIOUS PROPERTY ACCOUNT",
            font=("Inter", 17, "bold"),
            text_color="#fbbf24",
        ).pack(anchor="w", padx=20, pady=(18, 4))
        ctk.CTkLabel(
            dialog,
            text=(
                f"{len(matches)} active accounts use Previous TD {td_number}. "
                "This selection controls lineage only; it never combines payments."
            ),
            font=("Inter", 10),
            text_color="#cbd5e1",
        ).pack(anchor="w", padx=20, pady=(0, 12))

        frame = ctk.CTkFrame(dialog, fg_color="#111827")
        frame.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        columns = ("ID", "OWNER", "PIN", "LOT / BLOCK", "BARANGAY", "CLASSIFICATION")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=8)
        widths = (70, 250, 130, 120, 130, 170)
        for column, width in zip(columns, widths):
            tree.heading(column, text=column)
            tree.column(column, width=width, anchor="w" if column == "OWNER" else "center")
        for match in matches:
            lot_block = " / ".join(
                value for value in (
                    str(match.get("lot_number") or "").strip(),
                    str(match.get("block_number") or "").strip(),
                ) if value
            ) or "—"
            tree.insert(
                "", "end", iid=str(match["id"]),
                values=(
                    match["id"], match.get("owner_name") or "UNKNOWN",
                    match.get("pin") or "—", lot_block,
                    match.get("barangay") or match.get("location") or "—",
                    match.get("kind_of_property") or "—",
                ),
            )
        tree.pack(fill="both", expand=True, padx=8, pady=8)

        def confirm():
            choice = tree.selection()
            if not choice:
                messagebox.showwarning(
                    "Selection Required",
                    "Select the exact previous property account.",
                    parent=dialog,
                )
                return
            selected["id"] = int(choice[0])
            dialog.destroy()

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=(0, 16))
        ctk.CTkButton(
            buttons, text="CANCEL", command=dialog.destroy,
            fg_color="#475569", width=120,
        ).pack(side="right")
        ctk.CTkButton(
            buttons, text="USE SELECTED PROPERTY", command=confirm,
            fg_color="#d97706", hover_color="#b45309", width=210,
        ).pack(side="right", padx=(0, 8))
        tree.bind("<Double-1>", lambda _event: confirm())
        self.wait_window(dialog)
        return selected["id"]

    def save(self):
        if getattr(self, "_save_locked", False):
            return
        if self.payment_mode and not self._payment_can_save():
            return
        # Map the internal var keys to the Title Case keys the backend expects
        key_map = {
            "td_number": "TD Number",
            "owner_name": "Owner Name",
            "pin": "PIN",
            "lot_number": "Lot Number",
            "area": "Area",
            "location": "Location",
            "kind_of_property": "Kind of Property",
            "prev_td_number": "Previous TD Number",
            "effectivity_date": "Effectivity Date",
            "assessed_value": "Assessed Value",
        }
        if not self.payment_mode:
            key_map.update({
                "prior_assessed_value": "Prior Assessed Value",
                "prior_effectivity_year": "Prior Effectivity Year",
            })
        if self.payment_mode:
            key_map.update({
                "tax_year": "Tax Year",
                "or_number": "OR Number",
                "or_date": "OR Date",
                "penalty": "Penalty",
                "discount": "Discount",
                "amount_paid": "Amount Paid",
                "remarks": "Remarks",
            })
        
        data = {}
        for internal_key, backend_key in key_map.items():
            val = self.vars[internal_key].get().strip()
            data[backend_key] = val

        # Handle Barangay specifically as it's often a duplicate of Location
        data["Barangay"] = data["Location"]

        prev_td = data.get("Previous TD Number", "").strip()
        td_number = data.get("TD Number", "").strip()
        if prev_td and td_number and prev_td.upper() == td_number.upper():
            self._show_save_feedback(SaveFeedback(
                "error", "Invalid Previous TD",
                "Previous TD cannot be the same as the new TD number.",
                "prev_td_number",
            ))
            return

        if prev_td and prev_td.upper() != self._original_prev_td:
            try:
                previous_matches = prop_svc.find_properties_by_td_number(
                    prev_td, exclude_id=self.property_id
                )
            except Exception:
                previous_matches = []
            if len(previous_matches) > 1:
                selected_previous_id = self._choose_previous_property(
                    prev_td, previous_matches
                )
                if selected_previous_id is None:
                    return
                self._selected_previous_property_id = selected_previous_id
            elif len(previous_matches) == 1:
                self._selected_previous_property_id = previous_matches[0]["id"]
            else:
                proceed = confirm_action(
                    self, "Previous TD not found",
                    "The Previous TD was not found in the system.\n\n"
                    "Continue without linking a previous property account?",
                    action="Continue Saving",
                )
                if not proceed:
                    return
                self._selected_previous_property_id = None
        elif not prev_td:
            self._selected_previous_property_id = None

        if self._selected_previous_property_id is not None:
            data["Previous Property ID"] = int(self._selected_previous_property_id)

        duplicate_matches = []
        try:
            duplicate_matches = prop_svc.find_properties_by_td_number(
                td_number, exclude_id=self.property_id
            )
        except Exception:
            duplicate_matches = []
        unchanged_verified = bool(
            self._loaded_duplicate_verified
            and td_number.upper() == self._original_td
            and duplicate_matches
        )
        if duplicate_matches and not unchanged_verified:
            pilot_td = str(self.duplicate_policy.get("pilot_td") or "").strip().upper()
            if pilot_td and td_number.upper() != pilot_td:
                self._show_save_feedback(SaveFeedback(
                    "warning", "Duplicate TD pilot restriction",
                    f"The controlled pilot currently allows only TD {pilot_td}.\n\n"
                    f"TD {td_number.upper()} remains blocked until the pilot is accepted and rollout is expanded.",
                    "td_number",
                ))
                return
            if not self.duplicate_td_var.get():
                self._show_save_feedback(SaveFeedback(
                    "warning", "Duplicate TD requires authorization",
                    f"{len(duplicate_matches)} active property account(s) already use TD {td_number}.\n\n"
                    "An administrator must select AUTHORIZED DUPLICATE TD and complete the reference and reason.",
                    "td_number",
                ))
                return
            reference = self.vars["duplicate_td_reference"].get().strip()
            reason = self.vars["duplicate_td_reason"].get().strip()
            if len(reference) < 3 or len(reason) < 10:
                self._show_save_feedback(SaveFeedback(
                    "error", "Incomplete duplicate authorization",
                    "Enter the Assessor reference and a reason of at least 10 characters.",
                ))
                return
            existing_summary = "\n".join(
                f"• Record #{item['id']} — {item.get('owner_name') or 'UNKNOWN OWNER'}"
                for item in duplicate_matches[:8]
            )
            confirmed = confirm_action(
                self, "Confirm verified duplicate TD",
                f"You are authorizing another active account with TD {td_number}.\n\n"
                f"Existing account(s):\n{existing_summary}\n\n"
                f"Assessor reference: {reference}\nReason: {reason}\n\n"
                "Payments, billings, and documents will remain separate by property account.",
                action="Authorize Duplicate TD",
            )
            if not confirmed:
                return
            data["Verified Duplicate TD"] = True
            data["Assessor Reference"] = reference
            data["Duplicate TD Reason"] = reason
            data["Duplicate TD Confirmation"] = td_number

        if self.property_id is not None and self._loaded_version is not None:
            data["version"] = self._loaded_version

        if not self.payment_mode:
            prior_value = data.get("Prior Assessed Value", "").strip()
            prior_year = data.get("Prior Effectivity Year", "").strip()
            if bool(prior_value) != bool(prior_year):
                self._show_save_feedback(SaveFeedback(
                    "error", "Incomplete prior assessment",
                    "Enter both Prior AV and Prior AV effective year, or leave both blank.",
                    "prior_effectivity_year" if prior_value else "prior_assessed_value",
                ))
                return
            if prior_value:
                try:
                    prior_amount = float(prior_value.replace(",", ""))
                    prior_year_num = int(prior_year)
                    current_year_num = int(data.get("Effectivity Date", "")[:4])
                    if prior_amount <= 0 or prior_year_num >= current_year_num:
                        raise ValueError
                except (TypeError, ValueError):
                    self._show_save_feedback(SaveFeedback(
                        "error", "Invalid prior assessment",
                        "Prior AV must be positive, and its year must be earlier than the current Effectivity year.",
                        "prior_assessed_value",
                    ))
                    return

        if self.payment_mode:
            required_payment_fields = ("OR Number", "OR Date", "Tax Year", "Amount Paid")
            missing = [field for field in required_payment_fields if not data.get(field, "").strip()]
            if missing:
                self._show_save_feedback(SaveFeedback(
                    "error", "Missing payment details",
                    f"Please fill in: {', '.join(missing)}.",
                    missing[0].lower().replace(" ", "_"),
                ))
                return

        # Normalize Date
        raw_date = data.get("OR Date", "").strip()
        if raw_date:
            clean_date = normalize_date_input(raw_date)
            if not clean_date:
                self._show_save_feedback(SaveFeedback(
                    "error", "Invalid OR Date", "Enter a valid date, such as YYYY-MM-DD.", "or_date"
                ))
                return
            data["OR Date"] = clean_date

        try:
            # Only attach the idempotency key when a payment is being posted
            # (OR Number is filled). For pure property edits without payment,
            # no key is needed since those are idempotent by nature.
            has_payment = bool(data.get("OR Number", "").strip())
            key = self._idempotency_key if has_payment else None

            result = prop_svc.save_property(data, editing_id=self.property_id, user=self.user, idempotency_key=key)
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise ValueError("The server did not confirm the save")
        except Exception as e:
            feedback = save_failure_feedback(e, payment=self.payment_mode)
            if feedback.uncertain:
                self._save_locked = True
                self.validate()
            entry = (
                self.property_id, data.get("OR Number"), data.get("OR Date"),
                normalize_tax_years(data.get("Tax Year")),
            ) if self.payment_mode else None
            self._show_save_feedback(feedback, entry=entry)
            return

        # UI refresh is not part of the write. Never turn a refresh failure into
        # a misleading "not saved" message or leave the form ready to resubmit.
        self._save_locked = True
        self.save_btn.configure(state="disabled")
        td_number = result.get("td_number") or td_number
        if self.payment_mode:
            title = "Payment saved"
            try:
                amount = f"₱{Decimal(data['Amount Paid'].replace(',', '')):,.2f}"
            except (InvalidOperation, ValueError):
                amount = ""
            summary = " · ".join(filter(None, (f"OR {data['OR Number']}", amount, f"TD {td_number}")))
            if result.get("target_changed"):
                summary += f"\nApplied to the effective account for tax year {data.get('Tax Year')}."
        else:
            title = "Property updated" if self.property_id is not None else "Property added"
            summary = f"TD {td_number}"
        prior_sync = result.get("prior_assessment_sync")
        corrected_years = prior_sync.get("years") if isinstance(prior_sync, dict) else None
        if isinstance(corrected_years, list) and corrected_years:
            summary += (
                "\nHistorical billing AV corrected for: " + ", ".join(map(str, corrected_years))
                + ". Payment records were not changed."
            )
        on_saved = getattr(self, "on_saved", None)
        if on_saved:
            record = SavedRecord(title, summary, result.get("property_id") or self.property_id, td_number)
            self.destroy()
            on_saved(record)
        else:
            # Other screens still use the original callback contract.
            messagebox.showinfo(title, summary, parent=self)
            self.destroy()
            if self.callback:
                self.callback()


class BulkBarangayUpdateModal(ctk.CTkToplevel):
    def __init__(self, parent, callback):
        super().__init__(parent)
        self.title("🧹 Bulk Barangay Update Tool")
        self.geometry("800x600")
        self.callback = callback
        self.barangays = ["NORTH POBLACION", "SOUTH POBLACION", "BAYABAS", "BORLONGAN", "BUENAVISTA", "CALAOCAN", "DIAMANEN", "DIANED", "DIARABASIN", "DIBUTUNAN", "DIMABUNO", "DINADIAWAN", "DITALE", "GUPA", "IPIL", "LABOY", "LIPIT", "LOBBOT", "MALIGAYA", "MIJARES", "MUCDOL", "PUANGI", "SALAY", "SAPANGKAWAYAN", "TOYTOYAN"]
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-800)//2}+{(sh-600)//2}")
        self.attributes("-topmost", True)
        self.grab_set()
        self.setup_ui()
        self.load_unspecified()

    def setup_ui(self):
        self.configure(fg_color=(ModernTheme.BG_LIGHT, ModernTheme.BG_DARK))
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=20)
        ctk.CTkLabel(header, text="UNSPECIFIED PROPERTIES", font=("Segoe UI", 18, "bold")).pack(side="left")
        
        table_fr = ctk.CTkFrame(self, fg_color="transparent", corner_radius=12)
        table_fr.pack(fill="both", expand=True, padx=20, pady=10)
        self.tree = ttk.Treeview(table_fr, columns=("ID", "TD", "Owner", "Location"), show="headings")
        for c in ("ID", "TD", "Owner", "Location"):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=150)
        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.pack(side="left", fill="both", expand=True)
        
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=20, pady=20)
        self.brgy_cmb = ctk.CTkComboBox(footer, values=self.barangays, width=200)
        self.brgy_cmb.pack(side="left")
        ctk.CTkButton(footer, text="UPDATE SELECTED", command=self.do_update, fg_color=ModernTheme.PRIMARY).pack(side="right")

    def load_unspecified(self):
        try:
            res = prop_svc.get_unspecified_properties() or []
            for item in self.tree.get_children():
                self.tree.delete(item)
            if not res:
                self.tree.insert("", "end", values=("", "No cleanup needed", "All properties have barangay values", ""))
                return
            for r in res:
                row = list(r)
                prop_id = row[0] if len(row) > 0 else ""
                td_number = row[1] if len(row) > 1 else ""
                owner = row[2] if len(row) > 2 else ""
                location = row[3] if len(row) > 3 else ""
                self.tree.insert("", "end", values=(prop_id, td_number, owner, location))
        except Exception as e:
            self._show_error("Data Cleanup Error", str(e))

    def _bring_to_front(self):
        try:
            self.lift()
            self.focus_force()
            self.attributes("-topmost", True)
        except Exception:
            pass

    def _show_error(self, title, message):
        self._bring_to_front()
        messagebox.showerror(title, message, parent=self)
        self.after(50, self._bring_to_front)

    def _show_success(self, updated_count, barangay):
        try:
            self.attributes("-topmost", False)
        except Exception:
            pass

        dlg = ctk.CTkToplevel(self)
        dlg.title("Update Complete")
        dlg.geometry("420x300")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.attributes("-topmost", True)
        dlg.configure(fg_color="#08111f")

        self.update_idletasks()
        sw, sh = self.winfo_width(), self.winfo_height()
        sx, sy = self.winfo_rootx(), self.winfo_rooty()
        dw, dh = 420, 300
        dlg.geometry(f"{dw}x{dh}+{sx + max((sw - dw) // 2, 0)}+{sy + max((sh - dh) // 2, 0)}")

        shell = ctk.CTkFrame(dlg, fg_color="#0f1b2d", corner_radius=18, border_width=1, border_color="#24344f")
        shell.pack(fill="both", expand=True, padx=14, pady=14)
        ctk.CTkFrame(shell, height=4, fg_color="#10b981", corner_radius=2).pack(fill="x", padx=20, pady=(18, 0))

        icon = ctk.CTkFrame(shell, width=76, height=76, corner_radius=38, fg_color="#063c32", border_width=2, border_color="#10b981")
        icon.pack(pady=(22, 12))
        icon.pack_propagate(False)
        ctk.CTkLabel(icon, text="OK", font=("Segoe UI", 20, "bold"), text_color="#34d399").place(relx=0.5, rely=0.48, anchor="center")

        ctk.CTkLabel(shell, text="Barangay Updated", font=("Inter", 18, "bold"), text_color="#f8fafc").pack()
        ctk.CTkLabel(
            shell,
            text=f"{updated_count} propert{'y' if updated_count == 1 else 'ies'} assigned to {barangay}.",
            font=("Inter", 12),
            text_color="#a8bdd8",
            wraplength=340,
            justify="center",
        ).pack(pady=(8, 0))
        ctk.CTkLabel(shell, text="The cleanup list has been refreshed.", font=("Inter", 10), text_color="#64748b").pack(pady=(6, 0))

        def close_dialog():
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()

        btn = ctk.CTkButton(
            shell,
            text="DONE",
            command=close_dialog,
            width=160,
            height=40,
            corner_radius=10,
            fg_color="#10b981",
            hover_color="#059669",
            font=("Inter", 12, "bold"),
        )
        btn.pack(pady=(20, 0))

        def keep_dialog_front():
            try:
                if dlg.winfo_exists():
                    dlg.lift()
                    dlg.attributes("-topmost", True)
                    dlg.after(250, keep_dialog_front)
            except Exception:
                pass

        dlg.protocol("WM_DELETE_WINDOW", close_dialog)
        dlg.bind("<Return>", lambda _e: close_dialog())
        dlg.bind("<Escape>", lambda _e: close_dialog())
        dlg.update_idletasks()
        dlg.lift()
        dlg.focus_force()
        dlg.grab_set()
        btn.focus_set()
        keep_dialog_front()
        self.wait_window(dlg)
        self._bring_to_front()

    def do_update(self):
        sel = self.tree.selection()
        if not sel:
            self._show_error("No Selection", "Select one or more properties to update.")
            return
        brgy = self.brgy_cmb.get()
        ids = [self.tree.item(s)["values"][0] for s in sel if self.tree.item(s)["values"][0]]
        if not ids:
            self._show_error("No Valid Properties", "The selected row cannot be updated.")
            return
        try:
            prop_svc.bulk_update_barangay(ids, brgy)
            updated_count = len(ids)
            self.load_unspecified()
            self.callback()
            self._show_success(updated_count, brgy)
        except Exception as e:
            self._show_error("Update Failed", str(e))
