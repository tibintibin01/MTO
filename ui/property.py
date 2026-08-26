import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import sys
from pathlib import Path
import api_clients.property_service as prop_svc
import api_clients.api_helper as api
import api_clients.auth_service as auth
from ui.dossier import PropertyDossierModal
from ui.import_wizard import ImportWizardModal
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
            except Exception as e: self.container.after(0, lambda err=e: messagebox.showerror("Error", str(err)))
            finally: self.container.after(0, lambda: overlay.hide())
        threading.Thread(target=worker, daemon=True).start()

    def _update_table(self, results, has_more=False):
        self.page_lbl.configure(text=f"PAGE {self.current_page + 1}")
        self.prev_btn.configure(state="normal" if self.current_page > 0 else "disabled")
        self.next_btn.configure(state="normal" if has_more else "disabled")
        for item in self.tree.get_children(): self.tree.delete(item)
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
    def __init__(self, parent, title, property_id, callback, user=None, payment_mode=False):
        super().__init__(parent)
        self.title(title)
        self.geometry("600x750")
        self.property_id = property_id
        self.callback = callback
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
        self._last_auto_amount_paid = ""
        self._setting_auto_amount_paid = False
        self._amount_paid_manually_changed = False
        self._payment_target_timer = None
        self._resolving_payment_target = False
        self._last_resolved_target_key = None
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
        if self.property_id:
            self.load_data()
            if self.payment_mode:
                self._prepare_payment_entry()
        else: self.recompute()

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
        self.scroll_form = ctk.CTkScrollableFrame(self, fg_color=(ModernTheme.CARD_LIGHT, ModernTheme.CARD_DARK), corner_radius=10)
        self.scroll_form.pack(fill="both", expand=True, padx=20, pady=(20, 10))

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
                if key in ["assessed_value", "prior_assessed_value", "penalty", "discount"]:
                    self.vars[key].trace_add("write", lambda *a: self.recompute())
                elif key == "amount_paid":
                    self.vars[key].trace_add("write", lambda *a: self._on_amount_paid_changed())
                elif key == "tax_year" and self.payment_mode:
                    self.vars[key].trace_add("write", lambda *a: self._on_payment_tax_year_changed())
                else:
                    self.vars[key].trace_add("write", lambda *a: self.validate())
            if self._first_input is None:
                self._first_input = entry
            self._last_input = entry
            self._field_entries.append(entry)
            self._field_entries_by_key[key] = entry

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
            policy_text = (
                "Use only for an Assessor-confirmed duplicate active TD. "
                "Payments remain separate by internal property account."
                if enabled
                else "Controlled duplicate creation is installed but not activated on this server."
            )
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

        self.calc_box = ctk.CTkFrame(self.scroll_form, fg_color=(ModernTheme.BG_LIGHT, ModernTheme.BG_DARK), corner_radius=8)
        self.calc_box.pack(fill="x", padx=10, pady=15)

        # ── Auto-Compute button ───────────────────────────────────────────────
        compute_fr = ctk.CTkFrame(self.scroll_form, fg_color="transparent")
        compute_fr.pack(fill="x", padx=10, pady=(0, 6))

        self._compute_btn = ctk.CTkButton(
            compute_fr,
            text="⚡  AUTO-COMPUTE PENALTY & DISCOUNT",
            command=self._auto_compute,
            height=38,
            font=("Inter", 11, "bold"),
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            text_color="white",
        )
        self._compute_btn.pack(fill="x")

        self._compute_lbl = ctk.CTkLabel(
            compute_fr, text="Fill in Assessed Value, Tax Year, and OR Date first.",
            font=("Inter", 9), text_color="#64748b", anchor="w",
        )
        self._compute_lbl.pack(anchor="w", pady=(2, 0))

        self.total_lbl = ctk.CTkLabel(self.calc_box, text="TOTAL TAX DUE: 0.00", font=("Segoe UI", 12, "bold"), text_color="#1f538d")
        self.total_lbl.pack(pady=15)
        if not self.payment_mode:
            self.calc_box.pack_forget()
            compute_fr.pack_forget()

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=20, pady=20)
        self.cancel_btn = ctk.CTkButton(footer, text="CANCEL", command=self.destroy, fg_color="#95a5a6", width=120)
        self.cancel_btn.pack(side="left")
        self.save_btn = ctk.CTkButton(footer, text="SAVE PROPERTY", command=self.save, fg_color="#2ecc71", width=200, state="disabled")
        self.save_btn.pack(side="right")

        if self._last_input:
            self._last_input.bind("<Tab>", lambda e: self._focus_widget(self.cancel_btn))
        self.cancel_btn.bind("<Tab>", lambda e: self._focus_widget(self.save_btn))
        self.cancel_btn.bind("<Shift-Tab>", lambda e: self._focus_widget(self._last_input))
        self.save_btn.bind("<Tab>", lambda e: self._focus_widget(self._first_input))
        self.save_btn.bind("<Shift-Tab>", lambda e: self._focus_widget(self.cancel_btn))
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

    def _prepare_payment_entry(self):
        """Reuse the property editor as a clean payment-posting form."""
        self.title("Add Payment")
        self._last_auto_amount_paid = ""
        self._setting_auto_amount_paid = False
        self._amount_paid_manually_changed = False
        for key in ("or_number", "or_date", "penalty", "discount", "amount_paid", "remarks"):
            if key in self.vars:
                self.vars[key].set("")
        self.save_btn.configure(text="SAVE PAYMENT")
        self._compute_lbl.configure(
            text=(
                "Enter OR Number, OR Date, and Tax Year. For a partial payment, "
                "Amount Paid is this installment only."
            ),
            text_color="#64748b",
        )
        self.recompute()
        self._focus_and_select_field("tax_year")

    def _on_payment_tax_year_changed(self):
        self.validate()
        if not self.payment_mode or self._resolving_payment_target:
            return
        year_text = self.vars["tax_year"].get().strip()
        if not (year_text.isdigit() and len(year_text) == 4):
            return
        if self._payment_target_timer:
            try:
                self.after_cancel(self._payment_target_timer)
            except Exception:
                pass
        self._payment_target_timer = self.after(450, self._resolve_payment_target_for_tax_year)

    def _resolve_payment_target_for_tax_year(self):
        if not self.payment_mode or self._resolving_payment_target:
            return
        td_number = self.vars["td_number"].get().strip()
        year_text = self.vars["tax_year"].get().strip()
        if not td_number or not (year_text.isdigit() and len(year_text) == 4):
            return
        resolve_key = (td_number.upper(), year_text, self.property_id)
        if resolve_key == self._last_resolved_target_key:
            return
        self._last_resolved_target_key = resolve_key

        def worker():
            try:
                result = prop_svc.resolve_payment_target(
                    td_number,
                    int(year_text),
                    property_id=self.property_id,
                )
                self.after(0, lambda r=result, old_td=td_number, year=year_text: self._apply_payment_target_resolution(r, old_td, year))
            except Exception:
                # Do not interrupt typing. Save still has server-side validation.
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _apply_payment_target_resolution(self, result, old_td, year_text):
        if not self.winfo_exists() or not isinstance(result, dict):
            return
        target_id = result.get("id")
        target_td = result.get("td_number")
        if not target_id or int(target_id) == int(self.property_id or 0):
            return

        payment_values = {
            key: self.vars[key].get()
            for key in ("tax_year", "or_number", "or_date", "penalty", "discount", "amount_paid", "remarks")
            if key in self.vars
        }
        manual_amount = self._amount_paid_manually_changed
        last_auto = self._last_auto_amount_paid

        self._resolving_payment_target = True
        try:
            self.property_id = int(target_id)
            self.load_data()
            for key, value in payment_values.items():
                if key in self.vars:
                    self.vars[key].set(value)
            self._amount_paid_manually_changed = manual_amount
            self._last_auto_amount_paid = last_auto
            self._compute_lbl.configure(
                text=(
                    f"Tax year {year_text} belongs to TD {target_td}. "
                    f"The payment target was switched from {old_td}."
                ),
                text_color="#f59e0b",
            )
            self.recompute()
        finally:
            self._resolving_payment_target = False

    def _auto_compute(self):
        """
        Calls the backend compute-payment endpoint and auto-fills
        Penalty, Discount, and Amount Paid based on date_paid vs tax_year.
        """
        import threading
        import api_clients.system_service as system_svc

        # Validate required fields
        av_str   = self.vars["assessed_value"].get().replace(",", "").strip()
        yr_str   = self.vars["tax_year"].get().strip()
        date_str = self.vars["or_date"].get().strip()

        if not av_str or not yr_str or not date_str:
            self._compute_lbl.configure(
                text="⚠️  Fill in Assessed Value, Tax Year, and OR Date first.",
                text_color="#f59e0b",
            )
            return

        try:
            av = float(av_str)
            yr = int(yr_str)
        except ValueError:
            self._compute_lbl.configure(
                text="⚠️  Assessed Value and Tax Year must be numbers.",
                text_color="#f59e0b",
            )
            return

        # Normalize date to YYYY-MM-DD
        from api_clients.billing_service import normalize_date_input
        clean_date = normalize_date_input(date_str)
        if not clean_date:
            self._compute_lbl.configure(
                text="⚠️  Invalid OR Date format. Use YYYY-MM-DD.",
                text_color="#f59e0b",
            )
            return

        self._compute_btn.configure(state="disabled", text="⏳  COMPUTING...")
        self._compute_lbl.configure(text="Fetching rates from server...", text_color="#64748b")

        def worker():
            try:
                result = system_svc.compute_payment(
                    av,
                    yr,
                    clean_date,
                    property_id=self.property_id if self.payment_mode else None,
                )
                self.after(0, lambda r=result: self._apply_compute(r))
            except Exception as e:
                self.after(0, lambda err=e: self._compute_lbl.configure(
                    text=f"⚠️  {str(err)}", text_color="#ef4444"
                ))
            finally:
                if self.winfo_exists():
                    self.after(0, lambda: self._compute_btn.configure(
                        state="normal", text="⚡  AUTO-COMPUTE PENALTY & DISCOUNT"
                    ))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_compute(self, result: dict):
        """Apply computed values to the form fields."""
        discount = result.get("discount_amount", 0.0)
        penalty  = result.get("penalty_amount",  0.0)
        net_due  = result.get("net_amount_due",  0.0)
        resolved_av = result.get("assessed_value")

        if self.payment_mode and resolved_av is not None:
            self.vars["assessed_value"].set(f"{float(resolved_av):.2f}")

        self.vars["discount"].set(f"{discount:.2f}")
        self.vars["penalty"].set(f"{penalty:.2f}")
        self._set_auto_amount_paid(net_due)

        breakdown = result.get("breakdown", "")
        source = result.get("assessed_value_source")
        prefix = ""
        if self.payment_mode and source == "effective_year":
            prefix = (
                f"AV used for {self.vars['tax_year'].get().strip()}: "
                f"{float(resolved_av or 0):,.2f}. "
            )
        breakdown = f"{prefix}{breakdown}"
        self._compute_lbl.configure(
            text=f"✅  {breakdown}",
            text_color="#10b981",
        )
        self.recompute()

    def _on_amount_paid_changed(self):
        if self._setting_auto_amount_paid:
            self.validate()
            return
        current = self.vars["amount_paid"].get().strip()
        if current and current != self._last_auto_amount_paid:
            self._amount_paid_manually_changed = True
        elif not current:
            self._amount_paid_manually_changed = False
        self.validate()

    def _set_auto_amount_paid(self, amount):
        text = f"{float(amount or 0):.2f}"
        self._setting_auto_amount_paid = True
        try:
            self.vars["amount_paid"].set(text)
            self._last_auto_amount_paid = text
            self._amount_paid_manually_changed = False
        finally:
            self._setting_auto_amount_paid = False
        self.validate()

    def recompute(self, *args):
        try:
            av = float(self.vars["assessed_value"].get().replace(",", "") or 0)
            pe = float(self.vars["penalty"].get().replace(",", "") or 0)
            ds = float(self.vars["discount"].get().replace(",", "") or 0)
            # Use 2% as the display default (1% basic + 1% SEF per TaxPolicy default).
            # The AUTO-COMPUTE button fetches the exact rate from TaxPolicy for the
            # specific tax year — use that for accurate final amounts.
            total = (av * 0.02) + pe - ds
            self.total_lbl.configure(text=f"TOTAL TAX DUE: {total:,.2f}  (preview — use ⚡ AUTO-COMPUTE for exact amount)")
            if self.payment_mode:
                current_amount = self.vars["amount_paid"].get().strip()
                if (
                    not self._amount_paid_manually_changed
                    or not current_amount
                    or current_amount == self._last_auto_amount_paid
                ):
                    self._set_auto_amount_paid(total)
        except Exception:
            pass
        self.validate()

    def validate(self, *args):
        valid = bool(self.vars["td_number"].get().strip() and self.vars["owner_name"].get().strip() and self.vars["assessed_value"].get().strip())
        if self.payment_mode:
            valid = valid and all(
                self.vars[key].get().strip()
                for key in ("or_number", "or_date", "tax_year", "amount_paid")
            )
        self.save_btn.configure(state="normal" if valid else "disabled")

    def load_data(self):
        try:
            prop = prop_svc.get_property_by_id(self.property_id)
            if not prop: return
            if isinstance(prop, dict):
                self._loaded_version = prop.get("version")
                mapping = {"td_number": prop.get("td_number"), "owner_name": prop.get("owner_name"), "pin": prop.get("pin"), "lot_number": prop.get("lot_number"), "area": prop.get("area"), "location": prop.get("location"), "kind_of_property": prop.get("kind_of_property"), "prev_td_number": prop.get("prev_td_number"), "effectivity_date": prop.get("effectivity_date"), "assessed_value": str(prop.get("assessed_value", "0.00")), "penalty": str(prop.get("penalty", "0.00")), "discount": str(prop.get("discount", "0.00")), "or_number": prop.get("or_number"), "or_date": str(prop.get("or_date")) if prop.get("or_date") else "", "tax_year": prop.get("tax_year"), "amount_paid": str(prop.get("amount_paid", "0.00"))}
            else:
                mapping = {"td_number": prop[1], "owner_name": prop[2], "lot_number": prop[4], "area": prop[5], "location": prop[6], "kind_of_property": prop[7], "assessed_value": str(prop[9]), "penalty": str(prop[10]), "discount": str(prop[11]), "or_number": prop[12], "or_date": str(prop[13]) if prop[13] else "", "tax_year": prop[14], "pin": prop[18] if len(prop) > 18 else "", "prev_td_number": prop[20] if len(prop) > 20 else "", "effectivity_date": prop[21] if len(prop) > 21 else ""}
            for k, v in mapping.items():
                if k in self.vars: self.vars[k].set(str(v) if v is not None else "")
            self._original_prev_td = self.vars["prev_td_number"].get().strip().upper()
            self._original_td = self.vars["td_number"].get().strip().upper()
            if isinstance(prop, dict):
                self._selected_previous_property_id = prop.get("previous_property_id")
                self._loaded_duplicate_verified = bool(prop.get("duplicate_td_verified"))
                self.duplicate_td_var.set(self._loaded_duplicate_verified)
                self.vars["duplicate_td_reason"].set(
                    str(prop.get("duplicate_td_reason") or "")
                )
                self.vars["duplicate_td_reference"].set(
                    str(prop.get("duplicate_td_reference") or "")
                )
            self.recompute()
        except Exception as e: print(f"Load Error: {e}")

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
            messagebox.showerror(
                "Invalid Previous TD",
                "Previous TD cannot be the same as the new TD number.",
                parent=self,
            )
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
                proceed = messagebox.askyesno(
                    "Previous TD Not Found",
                    "The Previous TD was not found in the system.\n\n"
                    "Continue saving anyway?",
                    parent=self,
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
            if not self.duplicate_td_var.get():
                messagebox.showerror(
                    "Duplicate TD Requires Authorization",
                    f"{len(duplicate_matches)} active property account(s) already use TD {td_number}.\n\n"
                    "An administrator must select AUTHORIZED DUPLICATE TD and complete the reference and reason.",
                    parent=self,
                )
                return
            reference = self.vars["duplicate_td_reference"].get().strip()
            reason = self.vars["duplicate_td_reason"].get().strip()
            if len(reference) < 3 or len(reason) < 10:
                messagebox.showerror(
                    "Incomplete Duplicate Authorization",
                    "Enter the Assessor reference and a reason of at least 10 characters.",
                    parent=self,
                )
                return
            existing_summary = "\n".join(
                f"• Record #{item['id']} — {item.get('owner_name') or 'UNKNOWN OWNER'}"
                for item in duplicate_matches[:8]
            )
            confirmed = messagebox.askyesno(
                "Confirm Verified Duplicate TD",
                f"You are authorizing another active account with TD {td_number}.\n\n"
                f"Existing account(s):\n{existing_summary}\n\n"
                f"Assessor reference: {reference}\nReason: {reason}\n\n"
                "Payments, billings, and documents will remain separate by property account. Continue?",
                parent=self,
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
                messagebox.showerror(
                    "Incomplete Prior Assessment",
                    "Enter both Prior AV and Prior AV effective year, or leave both blank.",
                    parent=self,
                )
                return
            if prior_value:
                try:
                    prior_amount = float(prior_value.replace(",", ""))
                    prior_year_num = int(prior_year)
                    current_year_num = int(data.get("Effectivity Date", "")[:4])
                    if prior_amount <= 0 or prior_year_num >= current_year_num:
                        raise ValueError
                except (TypeError, ValueError):
                    messagebox.showerror(
                        "Invalid Prior Assessment",
                        "Prior AV must be positive, and its year must be earlier than the current Effectivity year.",
                        parent=self,
                    )
                    return

        if self.payment_mode:
            required_payment_fields = ("OR Number", "OR Date", "Tax Year", "Amount Paid")
            missing = [field for field in required_payment_fields if not data.get(field, "").strip()]
            if missing:
                messagebox.showerror(
                    "Missing Payment Details",
                    f"Please fill in: {', '.join(missing)}.",
                    parent=self,
                )
                return

        # Normalize Date
        from api_clients.billing_service import normalize_date_input
        raw_date = data.get("OR Date", "").strip()
        if raw_date:
            clean_date = normalize_date_input(raw_date)
            if not clean_date:
                messagebox.showerror("Invalid Date", f"Format '{raw_date}' not recognized. Use YYYY-MM-DD.", parent=self)
                return
            data["OR Date"] = clean_date

        try:
            # Only attach the idempotency key when a payment is being posted
            # (OR Number is filled). For pure property edits without payment,
            # no key is needed since those are idempotent by nature.
            has_payment = bool(data.get("OR Number", "").strip())
            key = self._idempotency_key if has_payment else None

            result = prop_svc.save_property(data, editing_id=self.property_id, user=self.user, idempotency_key=key)
            success_msg = "Payment saved successfully." if self.payment_mode else "Property record saved successfully."
            if self.payment_mode and isinstance(result, dict) and result.get("target_changed"):
                success_msg += (
                    f"\n\nApplied to TD {result.get('td_number')} because that TD is effective "
                    f"for tax year {data.get('Tax Year')}."
                )
            prior_sync = result.get("prior_assessment_sync", {}) if isinstance(result, dict) else {}
            corrected_years = prior_sync.get("years", [])
            if corrected_years:
                success_msg += (
                    "\n\nHistorical billing AV corrected for: "
                    + ", ".join(str(year) for year in corrected_years)
                    + ". Payment records were not changed."
                )
            messagebox.showinfo("Success", success_msg, parent=self)
            if self.callback:
                self.callback()
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)


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
