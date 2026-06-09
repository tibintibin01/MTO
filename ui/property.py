import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import api_clients.property_service as prop_svc
import api_clients.api_helper as api
from ui.dossier import PropertyDossierModal
from ui.import_wizard import ImportWizardModal
from theme_manager import ModernTheme
from utils import tr, format_curr
from ui_components import LoadingOverlay, ErrorDialog, AutocompleteComboBox, attach_autocomplete

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
        header_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        header_fr.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(header_fr, text=tr("dashboard.nav.property").upper(), font=ModernTheme.H1).pack(side="left")

        self.search_ent = ctk.CTkEntry(header_fr, placeholder_text=tr("property.search_placeholder"), width=350, font=ModernTheme.BODY)
        self.search_ent.pack(side="right", padx=(10, 0))
        self.search_ent.bind("<Return>", lambda e: self.refresh_table())

        ctk.CTkButton(header_fr, text=f"🔍 {tr('property.btn_search')}", command=self.refresh_table, width=100, font=ModernTheme.BUTTON, fg_color=ModernTheme.SECONDARY).pack(side="right", padx=10)

        import api_clients.auth_service as auth
        if auth.has_permission(self.user, "property_edit"):
            ctk.CTkButton(header_fr, text=f"🧹 {tr('property.btn_cleanup')}", command=self.open_bulk_update, font=ModernTheme.BUTTON, fg_color=ModernTheme.WARNING, width=150).pack(side="right", padx=10)
            ctk.CTkButton(header_fr, text=f"+ {tr('property.btn_add')}", command=self.open_add_modal, font=ModernTheme.BUTTON, fg_color=ModernTheme.SUCCESS, width=150).pack(side="right", padx=(10, 0))
            ctk.CTkButton(header_fr, text=f"🚀 {tr('property.btn_import')}", command=self.open_import_wizard, font=ModernTheme.BUTTON, fg_color=ModernTheme.PRIMARY, width=150).pack(side="right")

        filter_bar = ctk.CTkFrame(self.container, fg_color=ModernTheme.SECONDARY, corner_radius=8)
        filter_bar.pack(fill="x", pady=(0, 15), padx=5)

        # Left group — all filters together
        left_group = ctk.CTkFrame(filter_bar, fg_color="transparent")
        left_group.pack(side="left", padx=(10, 0), pady=6)

        ctk.CTkLabel(left_group, text=tr("property.filters.barangay"), font=ModernTheme.BODY_BOLD, text_color="white").pack(side="left", padx=(5, 4))
        self.barangay_cmb = ctk.CTkComboBox(left_group, values=["ALL"], width=160, height=28, font=ModernTheme.BODY)
        self.barangay_cmb.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(left_group, text="YEAR FROM:", font=ModernTheme.BODY_BOLD, text_color="white").pack(side="left", padx=(0, 4))
        self.year_start_ent = ctk.CTkEntry(left_group, width=70, height=28, placeholder_text="e.g. 2020", font=ModernTheme.BODY)
        self.year_start_ent.pack(side="left", padx=(0, 6))

        ctk.CTkLabel(left_group, text="TO:", font=ModernTheme.BODY_BOLD, text_color="white").pack(side="left", padx=(0, 4))
        self.year_end_ent = ctk.CTkEntry(left_group, width=70, height=28, placeholder_text="e.g. 2024", font=ModernTheme.BODY)
        self.year_end_ent.pack(side="left", padx=(0, 12))

        ctk.CTkButton(left_group, text=f"🎯 {tr('property.filters.apply')}", command=self.refresh_table, width=130, height=28, font=ModernTheme.BUTTON_SMALL, fg_color=ModernTheme.SUCCESS).pack(side="left", padx=(0, 5))

        table_fr = ctk.CTkFrame(self.container, fg_color="transparent", corner_radius=12)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Prop.Treeview", 
                        rowheight=35, 
                        font=ModernTheme.BODY,
                        background="#1e1e1e",
                        fieldbackground="#1e1e1e",
                        foreground="white")
        style.configure("Prop.Treeview.Heading", 
                        font=ModernTheme.BODY_BOLD,
                        background="#333333",
                        foreground="white")
        style.map("Prop.Treeview", background=[("selected", ModernTheme.PRIMARY)])
        
        self.cols = (tr("property.table.id"), tr("property.table.td"), tr("property.table.owner"), tr("property.table.location"), tr("property.table.value"), tr("property.table.penalty"), tr("property.table.discount"), tr("property.table.due"))
        self.tree = ttk.Treeview(table_fr, columns=self.cols, show="headings", style="Prop.Treeview")
        for col in self.cols:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, anchor="center", width=100)
        
        self.tree.column(tr("property.table.id"), width=0, stretch=tk.NO)
        self.tree.column(tr("property.table.owner"), width=250, anchor="w")
        
        scrolly = ttk.Scrollbar(table_fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrolly.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrolly.pack(side="right", fill="y")

        self.pag_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        self.pag_fr.pack(side="bottom", fill="x", pady=10)
        self.prev_btn = ctk.CTkButton(self.pag_fr, text="◀ PREV", command=self.prev_page, width=100, fg_color=ModernTheme.SECONDARY)
        self.prev_btn.pack(side="left", padx=10)
        self.page_lbl = ctk.CTkLabel(self.pag_fr, text="PAGE 1", font=ModernTheme.BODY_BOLD)
        self.page_lbl.pack(side="left", expand=True)
        self.next_btn = ctk.CTkButton(self.pag_fr, text="NEXT ▶", command=self.next_page, width=100, fg_color=ModernTheme.SECONDARY)
        self.next_btn.pack(side="right", padx=10)

        actions = ctk.CTkFrame(self.container, fg_color="transparent")
        actions.pack(side="bottom", fill="x", pady=(15, 0))
        if auth.has_permission(self.user, "property_edit"):
            self.edit_btn = ctk.CTkButton(actions, text="✏️ EDIT", command=self.open_edit_modal, fg_color=ModernTheme.PRIMARY, state="disabled")
            self.edit_btn.pack(side="right", padx=5)
        if auth.has_permission(self.user, "property_delete"):
            self.del_btn = ctk.CTkButton(actions, text="🗑️ DELETE", command=self.confirm_delete, fg_color=ModernTheme.DANGER, state="disabled")
            self.del_btn.pack(side="right", padx=5)

        table_fr.pack(fill="both", expand=True)
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
                res = prop_svc.search_properties(
                    term,
                    limit=self.page_size,
                    cursor=self.next_cursor if not reset_page else None,
                    barangay=brgy if brgy != "ALL" else None,
                    kind=None,
                    year_start=year_start,
                    year_end=year_end,
                )
                items = res.get("items", [])
                self.next_cursor = res.get("next_cursor")
                has_more = res.get("has_more", False)
                self.container.after(0, lambda: self._update_table(items, has_more))
            except Exception as e: self.container.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally: self.container.after(0, lambda: overlay.hide())
        threading.Thread(target=worker, daemon=True).start()

    def _update_table(self, results, has_more=False):
        self.page_lbl.configure(text=f"PAGE {self.current_page + 1}")
        self.prev_btn.configure(state="normal" if self.current_page > 0 else "disabled")
        self.next_btn.configure(state="normal" if has_more else "disabled")
        for item in self.tree.get_children(): self.tree.delete(item)
        for r in results:
            self.tree.insert("", "end", values=(r[0], r[1], r[2], r[6], format_curr(r[9]), format_curr(r[12]), format_curr(r[13]), format_curr(r[14])))
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
        td = str(self.tree.item(sel[0])["values"][1]).strip()
        overlay = LoadingOverlay(self.container, "📂 FETCHING DOSSIER...")
        def worker():
            try:
                data = api.api_request("GET", f"/properties/dossier/{td}")
                self.container.after(0, lambda: [overlay.hide(), PropertyDossierModal(self.parent, data)])
            except Exception as e: self.container.after(0, lambda: [overlay.hide(), messagebox.showerror("Error", str(e))])
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
            prop_svc.delete_property(vals[0], user=self.user)
            self.refresh_table()
        except Exception as e:
            messagebox.showerror("Error", str(e))

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
        self.barangays = ["NORTH POBLACION", "SOUTH POBLACION", "BAYABAS", "BORLONGAN", "BUENAVISTA", "CALAOCAN", "DIAMANEN", "DIANED", "DIARABASIN", "DIBUTUNAN", "DIMABUNO", "DINADIAWAN", "DITALE", "GUPA", "IPIL", "LABOY", "LIPIT", "LOBBOT", "MALIGAYA", "MIJARES", "MUCDOL", "PUANGI", "SALAY", "SAPANGKAWAYAN", "TOYTOYAN"]

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
        self.setup_ui()
        if self.property_id:
            self.load_data()
            if self.payment_mode:
                self._prepare_payment_entry()
        else: self.recompute()

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
            ("Effectivity", "effectivity_date"),
            ("Assessed Value", "assessed_value"),
        ]
        payment_fields = [
            ("Tax Year", "tax_year"),
            ("OR Number", "or_number"),
            ("OR Date", "or_date"),
            ("Penalty", "penalty"),
            ("Discount", "discount"),
            ("Amount Paid", "amount_paid"),
        ]

        for _, key in fields + payment_fields:
            self.vars[key] = tk.StringVar()

        visible_fields = fields + payment_fields if self.payment_mode else fields

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
                attach_autocomplete(entry, self.barangays, self.vars[key])
            else:
                placeholder = "e.g. 2027" if key == "effectivity_date" else ""
                entry = ctk.CTkEntry(self.scroll_form, height=40, textvariable=self.vars[key], placeholder_text=placeholder)
                entry.pack(fill="x", padx=10, pady=(0, 5))
                entry.bind("<FocusIn>", lambda e, w=entry: self.after_idle(_scroll_to_widget, w))
                if key in ["assessed_value", "penalty", "discount"]:
                    self.vars[key].trace_add("write", lambda *a: self.recompute())
                else:
                    self.vars[key].trace_add("write", lambda *a: self.validate())

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
        ctk.CTkButton(footer, text="CANCEL", command=self.destroy, fg_color="#95a5a6", width=120).pack(side="left")
        self.save_btn = ctk.CTkButton(footer, text="SAVE PROPERTY", command=self.save, fg_color="#2ecc71", width=200, state="disabled")
        self.save_btn.pack(side="right")

    def _prepare_payment_entry(self):
        """Reuse the property editor as a clean payment-posting form."""
        self.title("Add Payment")
        for key in ("or_number", "or_date", "penalty", "discount", "amount_paid"):
            if key in self.vars:
                self.vars[key].set("")
        self.save_btn.configure(text="SAVE PAYMENT")
        self._compute_lbl.configure(
            text="Enter OR Number, OR Date, Tax Year, then use AUTO-COMPUTE.",
            text_color="#64748b",
        )
        self.recompute()

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
                result = system_svc.compute_payment(av, yr, clean_date)
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

        self.vars["discount"].set(f"{discount:.2f}")
        self.vars["penalty"].set(f"{penalty:.2f}")
        self.vars["amount_paid"].set(f"{net_due:.2f}")

        breakdown = result.get("breakdown", "")
        self._compute_lbl.configure(
            text=f"✅  {breakdown}",
            text_color="#10b981",
        )
        self.recompute()

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
            if self.payment_mode and not self.property_id:
                self.vars["amount_paid"].set(f"{total:.2f}")
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
                mapping = {"td_number": prop.get("td_number"), "owner_name": prop.get("owner_name"), "pin": prop.get("pin"), "lot_number": prop.get("lot_number"), "area": prop.get("area"), "location": prop.get("location"), "kind_of_property": prop.get("kind_of_property"), "effectivity_date": prop.get("effectivity_date"), "assessed_value": str(prop.get("assessed_value", "0.00")), "penalty": str(prop.get("penalty", "0.00")), "discount": str(prop.get("discount", "0.00")), "or_number": prop.get("or_number"), "or_date": str(prop.get("or_date")) if prop.get("or_date") else "", "tax_year": prop.get("tax_year"), "amount_paid": str(prop.get("amount_paid", "0.00"))}
            else:
                mapping = {"td_number": prop[1], "owner_name": prop[2], "lot_number": prop[4], "area": prop[5], "location": prop[6], "kind_of_property": prop[7], "assessed_value": str(prop[9]), "penalty": str(prop[10]), "discount": str(prop[11]), "or_number": prop[12], "or_date": str(prop[13]) if prop[13] else "", "tax_year": prop[14], "pin": prop[18] if len(prop) > 18 else "", "effectivity_date": prop[21] if len(prop) > 21 else ""}
            for k, v in mapping.items():
                if k in self.vars: self.vars[k].set(str(v) if v is not None else "")
            self.recompute()
        except Exception as e: print(f"Load Error: {e}")

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
            "effectivity_date": "Effectivity Date",
            "assessed_value": "Assessed Value",
        }
        if self.payment_mode:
            key_map.update({
                "tax_year": "Tax Year",
                "or_number": "OR Number",
                "or_date": "OR Date",
                "penalty": "Penalty",
                "discount": "Discount",
                "amount_paid": "Amount Paid",
            })
        
        data = {}
        for internal_key, backend_key in key_map.items():
            val = self.vars[internal_key].get().strip()
            data[backend_key] = val

        # Handle Barangay specifically as it's often a duplicate of Location
        data["Barangay"] = data["Location"]

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

            prop_svc.save_property(data, editing_id=self.property_id, user=self.user, idempotency_key=key)
            success_msg = "Payment saved successfully." if self.payment_mode else "Property record saved successfully."
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
                self.tree.insert("", "end", values=(r[0], r[1], r[2], r[6]))
        except Exception as e:
            messagebox.showerror("Data Cleanup Error", str(e), parent=self)
    def do_update(self):
        sel = self.tree.selection()
        if not sel: return
        brgy = self.brgy_cmb.get()
        ids = [self.tree.item(s)["values"][0] for s in sel if self.tree.item(s)["values"][0]]
        if not ids:
            return
        try:
            prop_svc.bulk_update_barangay(ids, brgy)
            messagebox.showinfo("Success", "Properties updated.")
            self.load_unspecified()
            self.callback()
        except Exception as e: messagebox.showerror("Error", str(e))
