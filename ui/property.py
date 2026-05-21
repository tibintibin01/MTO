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
from ui_components import LoadingOverlay, ErrorDialog

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

        ctk.CTkLabel(filter_bar, text=tr("property.filters.barangay"), font=ModernTheme.BODY_BOLD, text_color="white").pack(side="left", padx=(15, 5))
        self.barangay_cmb = ctk.CTkComboBox(filter_bar, values=["ALL"], width=180, height=28, font=ModernTheme.BODY)
        self.barangay_cmb.pack(side="left", padx=5, pady=8)

        ctk.CTkButton(filter_bar, text=f"🎯 {tr('property.filters.apply')}", command=self.refresh_table, width=120, height=28, font=ModernTheme.BUTTON_SMALL, fg_color=ModernTheme.SUCCESS).pack(side="right", padx=15)

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
                res = prop_svc.search_properties(term, limit=self.page_size, cursor=self.next_cursor if not reset_page else None, barangay=brgy if brgy != "ALL" else None)
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
        if not sel: return
        vals = self.tree.item(sel[0])["values"]
        if messagebox.askyesno("Confirm", f"Delete property owned by {vals[2]}?"):
            try:
                prop_svc.delete_property(vals[0], user=self.user)
                self.refresh_table()
            except Exception as e: messagebox.showerror("Error", str(e))

class PropertyEditModal(ctk.CTkToplevel):
    def __init__(self, parent, title, property_id, callback, user=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("600x750")
        self.property_id = property_id
        self.callback = callback
        self.user = user
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
        if self.property_id: self.load_data()
        else: self.recompute()

    def setup_ui(self):
        self.configure(fg_color=(ModernTheme.BG_LIGHT, ModernTheme.BG_DARK))
        self.scroll_form = ctk.CTkScrollableFrame(self, fg_color=(ModernTheme.CARD_LIGHT, ModernTheme.CARD_DARK), corner_radius=10)
        self.scroll_form.pack(fill="both", expand=True, padx=20, pady=(20, 10))

        fields = [("TD Number", "td_number"), ("Owner Name", "owner_name"), ("Payor", "payor_name"), ("Lot Number", "lot_number"), ("Area", "area"), ("Location", "location"), ("Kind", "kind_of_property"), ("Tax Year", "tax_year"), ("OR Number", "or_number"), ("OR Date", "or_date"), ("Assessed Value", "assessed_value"), ("Penalty", "penalty"), ("Discount", "discount"), ("Amount Paid", "amount_paid")]

        for label, key in fields:
            ctk.CTkLabel(self.scroll_form, text=label.upper(), font=("Segoe UI", 9, "bold"), text_color="gray").pack(anchor="w", padx=10, pady=(10, 0))
            self.vars[key] = tk.StringVar()
            if key == "location":
                drop = ctk.CTkComboBox(self.scroll_form, values=self.barangays, variable=self.vars[key], height=40)
                drop.pack(fill="x", padx=10, pady=(0, 5))
            else:
                ctk.CTkEntry(self.scroll_form, height=40, textvariable=self.vars[key]).pack(fill="x", padx=10, pady=(0, 5))
                if key in ["assessed_value", "penalty", "discount"]: self.vars[key].trace_add("write", lambda *a: self.recompute())
                else: self.vars[key].trace_add("write", lambda *a: self.validate())

        self.calc_box = ctk.CTkFrame(self.scroll_form, fg_color=(ModernTheme.BG_LIGHT, ModernTheme.BG_DARK), corner_radius=8)
        self.calc_box.pack(fill="x", padx=10, pady=15)
        self.total_lbl = ctk.CTkLabel(self.calc_box, text="TOTAL TAX DUE: 0.00", font=("Segoe UI", 12, "bold"), text_color="#1f538d")
        self.total_lbl.pack(pady=15)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=20, pady=20)
        ctk.CTkButton(footer, text="CANCEL", command=self.destroy, fg_color="#95a5a6", width=120).pack(side="left")
        self.save_btn = ctk.CTkButton(footer, text="SAVE PROPERTY", command=self.save, fg_color="#2ecc71", width=200, state="disabled")
        self.save_btn.pack(side="right")

    def recompute(self, *args):
        try:
            av = float(self.vars["assessed_value"].get().replace(",", "") or 0)
            pe = float(self.vars["penalty"].get().replace(",", "") or 0)
            ds = float(self.vars["discount"].get().replace(",", "") or 0)
            total = (av * 0.02) + pe - ds
            self.total_lbl.configure(text=f"TOTAL TAX DUE: {total:,.2f}")
            if not self.property_id: self.vars["amount_paid"].set(f"{total:.2f}")
        except: pass
        self.validate()

    def validate(self, *args):
        valid = bool(self.vars["td_number"].get().strip() and self.vars["owner_name"].get().strip() and self.vars["assessed_value"].get().strip())
        self.save_btn.configure(state="normal" if valid else "disabled")

    def load_data(self):
        try:
            prop = prop_svc.get_property_by_id(self.property_id)
            if not prop: return
            if isinstance(prop, dict):
                mapping = {"td_number": prop.get("td_number"), "owner_name": prop.get("owner_name"), "payor_name": prop.get("payor_name"), "lot_number": prop.get("lot_number"), "area": prop.get("area"), "location": prop.get("location"), "kind_of_property": prop.get("kind_of_property"), "assessed_value": str(prop.get("assessed_value", "0.00")), "penalty": str(prop.get("penalty", "0.00")), "discount": str(prop.get("discount", "0.00")), "or_number": prop.get("or_number"), "or_date": str(prop.get("or_date")) if prop.get("or_date") else "", "tax_year": prop.get("tax_year"), "amount_paid": str(prop.get("amount_paid", "0.00"))}
            else:
                mapping = {"td_number": prop[1], "owner_name": prop[2], "payor_name": prop[3], "lot_number": prop[4], "area": prop[5], "location": prop[6], "kind_of_property": prop[7], "assessed_value": str(prop[9]), "penalty": str(prop[10]), "discount": str(prop[11]), "or_number": prop[12], "or_date": str(prop[13]) if prop[13] else "", "tax_year": prop[14]}
            for k, v in mapping.items():
                if k in self.vars: self.vars[k].set(str(v) if v is not None else "")
            self.recompute()
        except Exception as e: print(f"Load Error: {e}")

    def save(self):
        # Map the internal var keys to the Title Case keys the backend expects
        key_map = {
            "td_number": "TD Number",
            "owner_name": "Owner Name",
            "payor_name": "Payor",
            "lot_number": "Lot Number",
            "area": "Area",
            "location": "Location",
            "kind_of_property": "Kind of Property",
            "tax_year": "Tax Year",
            "or_number": "OR Number",
            "or_date": "OR Date",
            "assessed_value": "Assessed Value",
            "penalty": "Penalty",
            "discount": "Discount",
            "amount_paid": "Amount Paid"
        }
        
        data = {}
        for internal_key, backend_key in key_map.items():
            val = self.vars[internal_key].get().strip()
            data[backend_key] = val

        # Handle Barangay specifically as it's often a duplicate of Location
        data["Barangay"] = data["Location"]

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
            messagebox.showinfo("Success", "Property record saved successfully.", parent=self)
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
            res = prop_svc.get_unspecified_properties()
            for item in self.tree.get_children(): self.tree.delete(item)
            for r in res: self.tree.insert("", "end", values=(r[0], r[1], r[2], r[6]))
        except: pass

    def do_update(self):
        sel = self.tree.selection()
        if not sel: return
        brgy = self.brgy_cmb.get()
        ids = [self.tree.item(s)["values"][0] for s in sel]
        try:
            prop_svc.bulk_update_barangay(ids, brgy)
            messagebox.showinfo("Success", "Properties updated.")
            self.load_unspecified()
            self.callback()
        except Exception as e: messagebox.showerror("Error", str(e))
