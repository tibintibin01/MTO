import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import api_clients.property_service as prop_svc
import api_clients.api_helper as api
from ui.dossier import PropertyDossierModal
from ui.import_wizard import ImportWizardModal

from theme_manager import ModernTheme
from utils import tr
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
        # Header Area
        header_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        header_fr.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            header_fr, text=tr("dashboard.nav.property").upper(), font=ModernTheme.H1
        ).pack(side="left")

        # Search Box with hint
        self.search_ent = ctk.CTkEntry(
            header_fr, placeholder_text=tr("property.search_placeholder"), width=350, font=ModernTheme.BODY
        )
        self.search_ent.pack(side="right", padx=(10, 0))
        self.search_ent.bind("<Return>", lambda e: self.refresh_table())
        self.search_ent.bind("<KP_Enter>", lambda e: self.refresh_table())

        ctk.CTkButton(
            header_fr,
            text=f"🔍 {tr('property.btn_search')}",
            command=self.refresh_table,
            width=100,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.SECONDARY,
        ).pack(side="right", padx=10)

        import api_clients.auth_service as auth

        if auth.has_permission(self.user, "property_edit"):
            ctk.CTkButton(
                header_fr,
                text=f"🧹 {tr('property.btn_cleanup')}",
                command=self.open_bulk_update,
                font=ModernTheme.BUTTON,
                fg_color=ModernTheme.WARNING,
                width=150,
            ).pack(side="right", padx=10)

            ctk.CTkButton(
                header_fr,
                text=f"+ {tr('property.btn_add')}",
                command=self.open_add_modal,
                font=ModernTheme.BUTTON,
                fg_color=ModernTheme.SUCCESS,
                width=150,
            ).pack(side="right", padx=(10, 0))

            ctk.CTkButton(
                header_fr,
                text=f"🚀 {tr('property.btn_import')}",
                command=self.open_import_wizard,
                font=ModernTheme.BUTTON,
                fg_color=ModernTheme.PRIMARY,
                width=150,
            ).pack(side="right")

        # --- ADVANCED FILTER BAR ---
        filter_bar = ctk.CTkFrame(self.container, fg_color=ModernTheme.SECONDARY, corner_radius=8)
        filter_bar.pack(fill="x", pady=(0, 15), padx=5)

        # Barangay Filter
        ctk.CTkLabel(
            filter_bar, text=tr("property.filters.barangay"), font=ModernTheme.BODY_BOLD, text_color="white"
        ).pack(side="left", padx=(15, 5))
        self.barangay_cmb = ctk.CTkComboBox(
            filter_bar, values=["ALL"], width=180, height=28, font=ModernTheme.BODY
        )
        self.barangay_cmb.pack(side="left", padx=5, pady=8)

        # Tax Year Range
        ctk.CTkLabel(
            filter_bar, text=tr("property.filters.year_from"), font=ModernTheme.BODY_BOLD, text_color="white"
        ).pack(side="left", padx=(15, 5))
        self.year_from_ent = ctk.CTkEntry(filter_bar, width=80, height=28, font=ModernTheme.BODY)
        self.year_from_ent.pack(side="left", padx=5)

        ctk.CTkLabel(
            filter_bar, text=tr("property.filters.year_to"), font=ModernTheme.BODY_BOLD, text_color="white"
        ).pack(side="left", padx=(5, 5))
        self.year_to_ent = ctk.CTkEntry(filter_bar, width=80, height=28, font=ModernTheme.BODY)
        self.year_to_ent.pack(side="left", padx=5)

        ctk.CTkButton(
            filter_bar,
            text=f"🎯 {tr('property.filters.apply')}",
            command=self.refresh_table,
            width=120,
            height=28,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SUCCESS,
        ).pack(side="right", padx=15)

        # Table Container
        table_fr = ctk.CTkFrame(self.container, fg_color="white", corner_radius=12)

        # Style Treeview
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Prop.Treeview",
            rowheight=35,
            font=ModernTheme.BODY,
            background="#1e1e1e",
            fieldbackground="#1e1e1e",
            foreground="white",
        )
        style.configure(
            "Prop.Treeview.Heading",
            font=ModernTheme.BODY_BOLD,
            background="#333333",
            foreground="white",
        )
        style.map("Prop.Treeview", background=[("selected", ModernTheme.PRIMARY)])

        self.cols = (
            tr("property.table.id"),
            tr("property.table.td"),
            tr("property.table.owner"),
            tr("property.table.location"),
            tr("property.table.value"),
            tr("property.table.penalty"),
            tr("property.table.discount"),
            tr("property.table.due"),
            tr("property.table.last_or"),
            tr("property.table.or_date"),
        )
        self.tree = ttk.Treeview(
            table_fr, columns=self.cols, show="headings", style="Prop.Treeview"
        )

        for col in self.cols:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, anchor="center", width=100)

        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.column("Owner Name", width=220, anchor="w")
        self.tree.column("Location", width=180, anchor="w")
        self.tree.column("Assessed Value", width=110)
        self.tree.column("Penalty", width=90)
        self.tree.column("Discount", width=90)
        self.tree.column("Total Due", width=110)

        scrolly = ttk.Scrollbar(table_fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrolly.set)

        scrolly = ttk.Scrollbar(table_fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrolly.set)

        # Zebra Tags
        self.tree.tag_configure("oddrow", background="#2b2b2b", foreground="white")
        self.tree.tag_configure("evenrow", background="#333333", foreground="white")

        self.tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrolly.pack(side="right", fill="y")

        # --- PAGINATION BAR ---
        self.pag_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        self.pag_fr.pack(side="bottom", fill="x", pady=10)

        self.prev_btn = ctk.CTkButton(
            self.pag_fr,
            text=f"◀ {tr('property.pagination.prev')}",
            command=self.prev_page,
            width=100,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SECONDARY,
        )
        self.prev_btn.pack(side="left", padx=10)

        self.page_lbl = ctk.CTkLabel(
            self.pag_fr, text=f"{tr('property.pagination.page')} 1", font=ModernTheme.BODY_BOLD
        )
        self.page_lbl.pack(side="left", expand=True)

        self.next_btn = ctk.CTkButton(
            self.pag_fr,
            text=f"{tr('property.pagination.next')} ▶",
            command=self.next_page,
            width=100,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SECONDARY,
        )
        self.next_btn.pack(side="right", padx=10)

        # Bottom Actions
        actions = ctk.CTkFrame(self.container, fg_color="transparent")
        actions.pack(side="bottom", fill="x", pady=(15, 0))

        import api_clients.auth_service as auth

        if auth.has_permission(self.user, "property_edit"):
            self.edit_btn = ctk.CTkButton(
                actions,
                text=f"✏️ {tr('property.actions.edit')}",
                command=self.open_edit_modal,
                font=ModernTheme.BUTTON,
                fg_color=ModernTheme.PRIMARY,
                state="disabled",
            )
            self.edit_btn.pack(side="right", padx=5)

        if auth.has_permission(self.user, "property_delete"):
            self.del_btn = ctk.CTkButton(
                actions,
                text=f"🗑️ {tr('property.actions.delete')}",
                command=self.confirm_delete,
                font=ModernTheme.BUTTON,
                fg_color=ModernTheme.DANGER,
                state="disabled",
            )
            self.del_btn.pack(side="right", padx=5)

        self.export_btn = ctk.CTkButton(
            actions,
            text=f"📊 {tr('property.actions.export')}",
            command=self.do_export,
            font=ModernTheme.BUTTON,
            fg_color=ModernTheme.WARNING,
        )
        self.export_btn.pack(side="left", padx=5)

        table_fr.pack(fill="both", expand=True) # Pack expanding table LAST

        self.tree.bind("<<TreeviewSelect>>", self.on_selection_change)
        self.tree.bind("<Double-1>", lambda e: self.open_dossier())

    def on_selection_change(self, event=None):
        has_sel = bool(self.tree.selection())
        self.edit_btn.configure(state="normal" if has_sel else "disabled")
        self.del_btn.configure(state="normal" if has_sel else "disabled")

    def do_export(self):
        from utils import export_data_to_excel

        data = []
        for child in self.tree.get_children():
            data.append(self.tree.item(child)["values"])

        if not data:
            ErrorDialog(self.parent.winfo_toplevel(), tr("property.errors.no_data"), tr("property.errors.no_data_msg"))
            return

        export_data_to_excel(data, self.cols, filename_prefix="Properties")

    def refresh_table(self, reset_page=True):
        if reset_page:
            self.current_page = 0
            
        overlay = LoadingOverlay(self.container, "Loading Properties...")

        def worker():
            try:
                term = self.search_ent.get().strip()
                brgy = self.barangay_cmb.get()
                y_from = self.year_from_ent.get().strip()
                y_to = self.year_to_ent.get().strip()

                offset = self.current_page * self.page_size
                response = prop_svc.search_properties(
                    term,
                    limit=self.page_size,
                    cursor=self.next_cursor if not reset_page else None,
                    year_start=y_from if y_from else None,
                    year_end=y_to if y_to else None,
                    barangay=brgy if brgy != "ALL" else None,
                )
                items = response.get("items", [])
                self.next_cursor = response.get("next_cursor")
                has_more = response.get("has_more", False)
                
                self.container.after(0, lambda: self._update_table(items, has_more))
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Error", str(err)))
            finally:
                self.container.after(0, lambda: overlay.hide())

        threading.Thread(target=worker, daemon=True).start()

    def fetch_barangays(self):
        """Asynchronously loads the barangay list for the dropdown."""

        def worker():
            try:
                brgys = prop_svc.get_barangays()
                if brgys:
                    self.container.after(
                        0, lambda: self.barangay_cmb.configure(values=["ALL"] + brgys)
                    )
            except:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def next_page(self):
        self.current_page += 1
        self.refresh_table(reset_page=False)

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh_table(reset_page=False)

    def _update_table(self, results, has_more=False):
        self.page_lbl.configure(text=f"PAGE {self.current_page + 1}")
        self.prev_btn.configure(state="normal" if self.current_page > 0 else "disabled")
        self.next_btn.configure(
            state="normal" if has_more else "disabled"
        )

        for item in self.tree.get_children():
            self.tree.delete(item)
        if not results and self.search_ent.get().strip():
            messagebox.showinfo(
                "Search Results", "No property record matches your search criteria."
            )
            self.on_selection_change()
            return

        for i, r in enumerate(results):
            # (id, td, owner, payor, lot, area, loc, kind, officer, av, basic, sef, pen, total, or, or_d, year, pin, blk, prev, eff, brgy)
            loc_val = r[6]  # location
            brgy_val = r[22] if len(r) > 22 else ""

            full_loc = ""
            if loc_val and brgy_val:
                if loc_val.upper() == brgy_val.upper():
                    full_loc = loc_val
                else:
                    full_loc = f"{loc_val} ({brgy_val})"
            else:
                full_loc = brgy_val or loc_val or ""

            tag = "evenrow" if i % 2 == 0 else "oddrow"
            # Backend indices: 9:AV, 12:Penalty, 13:Discount, 14:Total, 15:OR, 16:OR Date
            pen_val = f"{r[12]:,.2f}" if r[12] else "0.00"
            disc_val = f"{r[13]:,.2f}" if r[13] else "0.00"
            total_val = f"{r[14]:,.2f}" if r[14] else "0.00"

            self.tree.insert(
                "",
                "end",
                values=(
                    r[0],
                    r[1],
                    r[2],
                    full_loc,
                    f"{r[9]:,.2f}",
                    pen_val,
                    disc_val,
                    total_val,
                    r[15],
                    r[16],
                ),
                tags=(tag,),
            )
        self.on_selection_change()

    def open_add_modal(self):
        PropertyEditModal(
            self.parent, "Add Property", None, self.refresh_table, user=self.user
        )

    def open_import_wizard(self):
        ImportWizardModal(self.container.winfo_toplevel())

    def open_bulk_update(self):
        BulkBarangayUpdateModal(self.parent, self.refresh_table)

    def open_edit_modal(self):
        sel = self.tree.selection()
        if not sel:
            return
        prop_id = self.tree.item(sel[0])["values"][0]
        PropertyEditModal(
            self.parent, "Edit Property", prop_id, self.refresh_table, user=self.user
        )

    def open_dossier(self):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0])["values"]
        td_number = str(vals[1]).strip() if len(vals) > 1 else ""

        if not td_number:
            messagebox.showwarning("Dossier Error", "This property record is missing a TD Number.")
            return

        overlay = LoadingOverlay(self.container, "📂 FETCHING PROPERTY DOSSIER...")

        def worker():
            try:
                data = api.api_request("GET", f"/properties/dossier/{td_number}")
                self.container.after(
                    0,
                    lambda: [
                        overlay.hide(),
                        PropertyDossierModal(self.parent, data),
                    ],
                )
            except Exception as e:
                self.container.after(
                    0,
                    lambda e=e: [
                        overlay.hide(),
                        messagebox.showerror("Dossier Error", str(e)),
                    ],
                )

        threading.Thread(target=worker, daemon=True).start()

    def confirm_delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0])["values"]
        if messagebox.askyesno("Confirm", f"Delete property owned by {vals[2]}?"):
            try:
                prop_svc.delete_property(vals[0], user=self.user)
                self.refresh_table()
            except Exception as e:
                messagebox.showerror("Delete Error", str(e))


class PropertyEditModal(ctk.CTkToplevel):
    def __init__(self, parent, title, property_id, callback, user=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("600x750")
        self.resizable(False, False)

        self.property_id = property_id
        self.callback = callback
        self.user = user
        self.vars = {}
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

        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-600)//2}+{(sh-750)//2}")

        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)

        self.setup_ui()
        if self.property_id:
            self.load_data()
        else:
            self.recompute()

    def setup_ui(self):
        self.configure(fg_color="#f5f6fa")

        self.scroll_form = ctk.CTkScrollableFrame(
            self, fg_color="white", corner_radius=10
        )
        self.scroll_form.pack(fill="both", expand=True, padx=20, pady=(20, 10))

        fields = [
            (tr("property.fields.td_number"), "td_number"),
            (tr("property.fields.owner_name"), "owner_name"),
            (tr("property.fields.payor_name"), "payor_name"),
            (tr("property.fields.lot_number"), "lot_number"),
            (tr("property.fields.area"), "area"),
            (tr("property.fields.location"), "location"),
            (tr("property.fields.kind"), "kind_of_property"),
            (tr("property.fields.tax_year"), "tax_year"),
            (tr("property.fields.or_number"), "or_number"),
            (tr("property.fields.or_date"), "or_date"),
            (tr("property.fields.value"), "assessed_value"),
            (tr("property.fields.penalty"), "penalty"),
            (tr("property.fields.discount"), "discount"),
            (tr("property.fields.paid"), "amount_paid"),
        ]

        placeholders = {
            "or_date": "YYYY-MM-DD (e.g. 2024-01-25)",
            "tax_year": "YYYY or YYYY-YYYY (e.g. 2023-2025)",
            "area": "Numeric value only",
            "assessed_value": "0.00",
            "penalty": "0.00",
            "discount": "0.00",
        }

        for label, key in fields:
            lbl = ctk.CTkLabel(
                self.scroll_form,
                text=label.upper(),
                font=("Segoe UI", 9, "bold"),
                text_color="gray",
            )
            lbl.pack(anchor="w", padx=10, pady=(10, 0))

            self.vars[key] = tk.StringVar()

            if key == "location":
                self.vars[key].set(tr("property.fields.location"))
                drop = ctk.CTkComboBox(
                    self.scroll_form,
                    values=self.barangays,
                    variable=self.vars[key],
                    height=40,
                )
                drop.pack(fill="x", padx=10, pady=(0, 5))
                drop.bind("<Key>", lambda e, d=drop: self._on_combo_key(e, d))
                drop.bind("<FocusIn>", lambda e, w=drop: self._scroll_to_widget(w))
            else:
                ph = placeholders.get(key, "")
                entry = ctk.CTkEntry(
                    self.scroll_form,
                    height=40,
                    textvariable=self.vars[key],
                    placeholder_text=ph,
                )
                entry.pack(fill="x", padx=10, pady=(0, 5))
                entry.bind("<FocusIn>", lambda e, w=entry: self._scroll_to_widget(w))

                if key in ["assessed_value", "penalty", "discount"]:
                    self.vars[key].trace_add("write", lambda *args: self.recompute())
                else:
                    self.vars[key].trace_add("write", lambda *args: self.validate())

        self.calc_box = ctk.CTkFrame(
            self.scroll_form, fg_color="#f1f2f6", corner_radius=8
        )
        self.calc_box.pack(fill="x", padx=10, pady=15)
        self.total_lbl = ctk.CTkLabel(
            self.calc_box,
            text=f"{tr('property.fields.total')}: 0.00",
            font=("Segoe UI", 12, "bold"),
            text_color="#1f538d",
        )
        self.total_lbl.pack(pady=15)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=20, pady=20)
        ctk.CTkButton(
            footer, text=tr("common.cancel").upper(), command=self.destroy, fg_color="#95a5a6", width=120
        ).pack(side="left")
        self.save_btn = ctk.CTkButton(
            footer,
            text=tr("property.fields.btn_save"),
            command=self.save,
            fg_color="#2ecc71",
            width=200,
            state="disabled",
        )
        self.save_btn.pack(side="right")

    def recompute(self, *args):
        try:
            val_str = self.vars["assessed_value"].get().replace(",", "").strip()
            pen_str = self.vars["penalty"].get().replace(",", "").strip()
            dsc_str = self.vars["discount"].get().replace(",", "").strip()
            av = float(val_str) if val_str else 0.0
            pe = float(pen_str) if pen_str else 0.0
            ds = float(dsc_str) if dsc_str else 0.0
            total = (av * 0.02) + pe - ds
            self.total_lbl.configure(text=f"TOTAL TAX DUE: {total:,.2f}")
            if not self.property_id:
                self.vars["amount_paid"].set(f"{total:.2f}")
        except:
            pass
        self.validate()

    def validate(self, *args):
        try:
            valid = all(
                [
                    self.vars["td_number"].get().strip(),
                    self.vars["owner_name"].get().strip(),
                    self.vars["assessed_value"].get().strip(),
                ]
            )
            self.save_btn.configure(state="normal" if valid else "disabled")
        except:
            pass

    def load_data(self):
        try:
            prop = prop_svc.get_property_by_id(self.property_id)
            if not prop:
                return
            mapping = {
                "td_number": prop[1],
                "owner_name": prop[2],
                "payor_name": prop[3],
                "lot_number": prop[4],
                "area": prop[5],
                "location": prop[6],
                "kind_of_property": prop[7],
                "assessed_value": str(prop[9]),
                "penalty": str(prop[10]),
                "discount": str(prop[11]),
                "or_number": prop[12],
                "or_date": str(prop[13]) if prop[13] else "",
                "tax_year": prop[14],
            }
            for k, v in mapping.items():
                if k in self.vars:
                    self.vars[k].set(str(v) if v is not None else "")
            self.recompute()
        except:
            pass

    def save(self):
        # 1. Standardize the Date Format
        raw_date = self.vars["or_date"].get().strip()
        clean_date = ""
        from api_clients.billing_service import normalize_date_input

        if raw_date:
            clean_date = normalize_date_input(raw_date)
            if not clean_date:
                messagebox.showerror(
                    "Invalid Date",
                    f"The OR Date '{raw_date}' is not in a recognized format.\nPlease use YYYY-MM-DD.",
                    parent=self,
                )
                return

        def clean_num(v):
            if not v: return "0.00"
            return v.replace(",", "").replace("₱", "").strip() or "0.00"

        data = {
            "TD Number": self.vars["td_number"].get().strip(),
            "Owner Name": self.vars["owner_name"].get().strip(),
            "Payor": self.vars["payor_name"].get().strip()
            or self.vars["owner_name"].get().strip(),
            "Lot Number": self.vars["lot_number"].get().strip(),
            "Area": self.vars["area"].get().strip(),
            "Location": self.vars["location"].get().strip(),
            "Barangay": self.vars["location"].get().strip(), # Also set Barangay for the new filter
            "Kind of Property": self.vars["kind_of_property"].get().strip(),
            "Tax Year": self.vars["tax_year"].get().strip(),
            "OR Number": self.vars["or_number"].get().strip(),
            "OR Date": clean_date,
            "Assessed Value": clean_num(self.vars["assessed_value"].get()),
            "Penalty": clean_num(self.vars["penalty"].get()),
            "Discount": clean_num(self.vars["discount"].get()),
            "Amount Paid": clean_num(self.vars["amount_paid"].get()),
        }
        try:
            prop_svc.save_property(data, editing_id=self.property_id, user=self.user)
            self.attributes("-topmost", False)
            messagebox.showinfo(
                "Success", "Property record saved successfully.", parent=self
            )
            self.callback()
            self.destroy()
        except Exception as e:
            self.attributes("-topmost", False)
            messagebox.showerror("Error", str(e), parent=self)
            self.attributes("-topmost", True)

    def _on_combo_key(self, event, combo):
        """Intelligent search for barangay."""
        char = event.char.upper()
        if not char or not char.isalpha():
            return

        # Prevent the character from being typed into the combobox display incorrectly
        # We handle the selection manually
        for v in self.barangays:
            if v.startswith(char):
                self.vars["location"].set(v)
                combo.set(v)  # Sync both variable and visual
                break
        return "break"  # Stop default processing

    def _scroll_to_widget(self, widget):
        """Precision auto-scrolling."""
        self.update_idletasks()
        try:
            # We need the position relative to the scrollable frame's internal frame
            y_pos = widget.winfo_y()
            canvas = self.scroll_form._parent_canvas
            interior = self.scroll_form._child_frame
            total_height = interior.winfo_reqheight()
            visible_height = canvas.winfo_height()
            if total_height > visible_height:
                target_fraction = max(0, (y_pos - 40) / total_height)
                canvas.yview_moveto(target_fraction)
        except Exception as e:
            print(f"Scroll Error: {e}")


class BulkBarangayUpdateModal(ctk.CTkToplevel):
    def __init__(self, parent, callback):
        super().__init__(parent)
        self.title("🧹 Bulk Barangay Update Tool")
        self.geometry("800x600")
        self.callback = callback
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

        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-800)//2}+{(sh-600)//2}")
        self.attributes("-topmost", True)
        self.grab_set()

        self.setup_ui()
        self.load_unspecified()

    def setup_ui(self):
        self.configure(fg_color="#f5f6fa")

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=20)
        ctk.CTkLabel(
            header, text="UNSPECIFIED PROPERTIES", font=("Segoe UI", 18, "bold")
        ).pack(side="left")
        ctk.CTkLabel(
            header, text="Select records to assign a barangay", text_color="gray"
        ).pack(side="left", padx=20)

        # Table
        table_fr = ctk.CTkFrame(self)
        table_fr.pack(fill="both", expand=True, padx=20)

        self.cols = ("ID", "TD Number", "Owner Name", "Location", "Current Brgy")
        self.tree = ttk.Treeview(
            table_fr, columns=self.cols, show="headings", selectmode="extended"
        )

        for col in self.cols:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, anchor="center", width=120)

        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.column("Owner Name", width=250, anchor="w")

        scrolly = ttk.Scrollbar(table_fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrolly.set)

        # Zebra Tags
        self.tree.tag_configure("oddrow", background="#2b2b2b", foreground="white")
        self.tree.tag_configure("evenrow", background="#333333", foreground="white")

        self.tree.pack(side="left", fill="both", expand=True)
        scrolly.pack(side="right", fill="y")

        # Footer
        footer = ctk.CTkFrame(self, fg_color="#f1f2f6")
        footer.pack(fill="x", side="bottom", padx=20, pady=20)

        ctk.CTkLabel(footer, text="ASSIGN TO:", font=("Segoe UI", 10, "bold")).pack(
            side="left", padx=20
        )

        self.brgy_var = tk.StringVar(value="SELECT BARANGAY")
        self.brgy_cb = ctk.CTkComboBox(
            footer, values=self.barangays, variable=self.brgy_var, width=250, height=40
        )
        self.brgy_cb.pack(side="left", padx=10)

        ctk.CTkButton(
            footer,
            text="✅ UPDATE SELECTED",
            command=self.apply_update,
            fg_color="#2ecc71",
            width=180,
            height=40,
        ).pack(side="right", padx=20)

    def load_unspecified(self):
        for r in self.tree.get_children():
            self.tree.delete(r)

        def worker():
            try:
                results = prop_svc.get_unspecified_properties()
                # If results is None, force it to an empty list
                safe_results = results if results is not None else []
                self.after(0, lambda: self._fill_table(safe_results))
            except Exception as e:
                # Capture more detailed error info
                err_msg = str(e) if str(e) else "Unknown API Error (Empty response)"
                self.after(
                    0,
                    lambda: messagebox.showerror("Cleanup Error", err_msg, parent=self),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _fill_table(self, results):
        if not results:
            # We don't necessarily want a popup here as it might be annoying on every load,
            # but for the "Cleanup" tool, let's show one so the user knows why it's empty.
            messagebox.showinfo(
                "Data Cleanup",
                "Great news! No 'UNSPECIFIED' properties were found in the database. All records are properly assigned.",
                parent=self,
            )
            return

        for i, r in enumerate(results):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.tree.insert("", "end", values=r, tags=(tag,))

    def apply_update(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning(
                "Selection Required",
                "Please select at least one property.",
                parent=self,
            )
            return

        new_brgy = self.brgy_var.get()
        if new_brgy == "SELECT BARANGAY":
            messagebox.showwarning(
                "Input Required", "Please select a target Barangay.", parent=self
            )
            return

        ids = [self.tree.item(s)["values"][0] for s in sel]

        if messagebox.askyesno(
            "Confirm Bulk Update",
            f"Are you sure you want to assign {len(ids)} properties to {new_brgy}?",
            parent=self,
        ):
            try:
                res = prop_svc.bulk_update_barangay(ids, new_brgy)
                messagebox.showinfo(
                    "Success", f"Successfully updated {res} records.", parent=self
                )
                self.callback()
                self.load_unspecified()
            except Exception as e:
                messagebox.showerror("Update Error", str(e), parent=self)
