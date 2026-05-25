import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from theme_manager import ModernTheme
from utils import tr
from ui_components import LoadingOverlay, AutocompleteComboBox
import api_clients.property_service as prop_svc
import api_clients.api_helper as api
from ui.dossier import PropertyDossierModal
from ui.import_wizard import ImportWizardModal
import threading


class AssessmentRollPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.page_cursors = [None]
        self.current_page = 0
        self.page_size = 50
        self.is_loading = False
        self.all_loaded = False
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

        # --- HEADER ---
        header = ctk.CTkFrame(self.container, fg_color="transparent")
        header.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(header, text="ASSESSMENT ROLL", font=ModernTheme.H2).pack(
            side="left"
        )

        # --- FILTERS ---
        filters_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        filters_fr.pack(fill="x", pady=(0, 15))

        # Search Box
        self.search_ent = ctk.CTkEntry(
            filters_fr, placeholder_text="Search PIN, TD, or Owner...", width=250
        )
        self.search_ent.pack(side="left")
        self.search_ent.bind("<Return>", lambda e: self.refresh_table())
        self.search_ent.bind("<KP_Enter>", lambda e: self.refresh_table())

        # Barangay Filter
        ctk.CTkLabel(
            filters_fr, text="BARANGAY:", font=("Segoe UI", 10, "bold"), text_color="gray"
        ).pack(side="left", padx=(20, 5))
        self.brgy_var = tk.StringVar(value="ALL")
        self.brgy_cb = ctk.CTkComboBox(
            filters_fr,
            values=["ALL"] + sorted(self.barangays),
            variable=self.brgy_var,
            width=180,
        )
        self.brgy_cb.pack(side="left")
        self.brgy_cb.configure(command=lambda e: self.refresh_table())

        # Year Range
        ctk.CTkLabel(
            filters_fr,
            text="YEAR FROM:",
            font=("Segoe UI", 10, "bold"),
            text_color="gray",
        ).pack(side="left", padx=(20, 5))
        self.year_start_ent = ctk.CTkEntry(
            filters_fr, width=80, placeholder_text="YYYY"
        )
        self.year_start_ent.pack(side="left")

        ctk.CTkLabel(
            filters_fr, text="TO:", font=("Segoe UI", 10, "bold"), text_color="gray"
        ).pack(side="left", padx=(5, 5))
        self.year_end_ent = ctk.CTkEntry(filters_fr, width=80, placeholder_text="YYYY")
        self.year_end_ent.pack(side="left")

        ctk.CTkButton(
            filters_fr,
            text="🔍 REFRESH",
            command=self.refresh_table,
            width=100,
            fg_color="#34495e",
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            filters_fr,
            text="🚀 BULK IMPORT",
            command=self.open_import_wizard,
            fg_color="#3498db",
            width=120,
        ).pack(side="right", padx=5)


        ctk.CTkButton(
            header,
            text="+ ADD RECORD",
            command=self.open_modal,
            fg_color="#27ae60",
            width=120,
        ).pack(side="right")

        # --- TABLE ---
        table_fr = ctk.CTkFrame(self.container, fg_color="transparent", corner_radius=12)


        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Roll.Treeview",
            rowheight=35,
            font=("Segoe UI", 10),
            background="#2b2b2b",
            fieldbackground="#2b2b2b",
            foreground="white",
        )
        style.configure(
            "Roll.Treeview.Heading",
            font=("Segoe UI", 10, "bold"),
            background="#333333",
            foreground="white",
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
        )
        self.tree = ttk.Treeview(
            table_fr, columns=self.cols, show="headings", style="Roll.Treeview"
        )

        # Column Config
        col_widths = {
            "ID": 0,
            "TD NO.": 110,
            "PIN": 130,
            "LOT & BLK": 100,
            "PROPERTY OWNER": 200,
            "LOCATION": 130,
            "CLASSIFICATION": 120,
            "ASSESSED VALUE": 120,
            "PREVIOUS TD": 110,
            "EFFECTIVITY": 100,
        }

        for col in self.cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center", width=col_widths.get(col, 100))

        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.column("PROPERTY OWNER", anchor="w")
        self.tree.column("LOCATION", anchor="center")


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
            text="◀ PREVIOUS",
            command=self.prev_page,
            width=100,
            fg_color="#34495e",
        )
        self.prev_btn.pack(side="left", padx=10)

        self.page_lbl = ctk.CTkLabel(
            self.pag_fr, text="Page 1", font=("Segoe UI", 12, "bold")
        )
        self.page_lbl.pack(side="left", expand=True)

        self.next_btn = ctk.CTkButton(
            self.pag_fr,
            text="LOAD MORE ▶",
            command=self.next_page,
            width=120,
            fg_color="#34495e",
        )
        self.next_btn.pack(side="right", padx=10)
        
        table_fr.pack(fill="both", expand=True) # Pack expanding table LAST

        self.tree.bind("<Double-1>", lambda e: self.open_dossier())

    def next_page(self):
        if not self.all_loaded:
            self.current_page += 1
            self.refresh_table(reset_page=False)

    def refresh_table(self, reset_page=True):
        if reset_page:
            self.page_cursors = [None]
            self.current_page = 0
            self.all_loaded = False
            
        self.is_loading = True
        overlay = LoadingOverlay(self.container, "Loading Assessment Roll...")

        def worker():
            try:
                term = self.search_ent.get().strip()
                brgy = self.brgy_var.get()
                y_start = self.year_start_ent.get().strip()
                y_end = self.year_end_ent.get().strip()
                
                cursor_to_use = self.page_cursors[self.current_page]
                
                response = prop_svc.search_properties(
                    term,
                    limit=self.page_size,
                    cursor=cursor_to_use,
                    barangay=brgy if brgy != "ALL" else None,
                    year_start=y_start,
                    year_end=y_end,
                )
                
                results = response.get("items", [])
                next_cur = response.get("next_cursor")
                
                # Store the next cursor for the next page
                if len(self.page_cursors) <= self.current_page + 1:
                    self.page_cursors.append(next_cur)
                else:
                    self.page_cursors[self.current_page + 1] = next_cur
                
                if not response.get("has_more"):
                    self.all_loaded = True

                self.container.after(0, lambda: self._update_table(results))
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Error", str(err)))
            finally:
                self.is_loading = False
                self.container.after(0, lambda: overlay.hide())

        threading.Thread(target=worker, daemon=True).start()

    def next_page(self):
        if not self.all_loaded:
            self.current_page += 1
            self.refresh_table(reset_page=False)

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.all_loaded = False
            self.refresh_table(reset_page=False)

    def _update_table(self, results):
        self.page_lbl.configure(text=f"PAGE {self.current_page + 1}")
        self.prev_btn.configure(state="normal" if self.current_page > 0 else "disabled")
        
        if not results and self.current_page == 0:
            for item in self.tree.get_children():
                self.tree.delete(item)
            return

        if len(results) < self.page_size:
            self.all_loaded = True
            self.next_btn.configure(state="disabled")
        else:
            self.next_btn.configure(state="normal")

        # Always clear table for true page-by-page pagination
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Get current row count for zebra tagging
        current_count = len(self.tree.get_children())

        for i, r in enumerate(results):
            # Indices from backend search_properties:
            # 0:id, 1:td, 2:owner, 4:lot, 6:loc, 7:kind, 9:av, 18:pin, 19:blk, 20:prev, 21:eff, 22:brgy
            td = r[1]
            pin = r[18] if len(r) > 18 else ""
            lot_blk = f"{r[4]} / {r[19]}" if len(r) > 19 and r[19] else str(r[4])
            owner = r[2]
            loc = r[22] if len(r) > 22 and r[22] else r[6]  # Barangay or Location
            kind = r[7]
            av = f"{r[9]:,.2f}"
            prev = r[20] if len(r) > 20 else ""
            eff = r[21] if len(r) > 21 else ""

            # If it's a full date string like 2023-01-01, just show the year
            if eff and len(str(eff)) >= 4:
                eff = str(eff)[:4]

            tag = "evenrow" if (current_count + i) % 2 == 0 else "oddrow"
            self.tree.insert(
                "",
                "end",
                values=(r[0], td, pin, lot_blk, owner, loc, kind, av, prev, eff),
                tags=(tag,),
            )

    def open_import_wizard(self):
        ImportWizardModal(self.container.winfo_toplevel(), mode="assessment")

    def _show_import_summary(self, res):
        if "error" in res:
            messagebox.showerror("Import Failed", res["error"])
            return

        msg = f"✅ Import Complete!\n\nInserted: {res['inserted']}\nUpdated: {res['updated']}\nFailed: {res['failed']}"
        if res["errors"]:
            msg += f"\n\nFirst 5 Errors:\n" + "\n".join(res["errors"][:5])

        messagebox.showinfo("Import Summary", msg)
        self.refresh_table()

    def open_modal(self):
        AssessmentModal(self.container, self.refresh_table, user=self.user)

    def open_dossier(self):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0])["values"]
        td_number = str(vals[1]).strip() if len(vals) > 1 else ""

        if not td_number:
            messagebox.showwarning("Dossier Error", "This property record is missing a TD Number.")
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

        def worker():
            try:
                # Use centralized API helper
                data = api.api_request("GET", f"/properties/dossier/{td_number}")
                self.container.after(
                    0,
                    lambda: [
                        loading.destroy(),
                        PropertyDossierModal(self.parent, data),
                    ],
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




class AssessmentModal(ctk.CTkToplevel):
    def __init__(self, parent, callback, user=None):
        super().__init__(parent)
        self.title("Add Assessment Record")
        self.geometry("600x750")
        self.resizable(False, True)
        self.callback = callback
        self.user = user
        self.vars = {}

        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)

        # Centre on screen
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-600)//2}+{(sh-750)//2}")

        self.setup_ui()

    def setup_ui(self):
        # ── Match the dark theme used by PropertyEditModal ────────────────────
        self.configure(fg_color=(ModernTheme.BG_LIGHT, ModernTheme.BG_DARK))

        # Scrollable form — same style as Add Property
        self.scroll_form = ctk.CTkScrollableFrame(
            self,
            fg_color=(ModernTheme.CARD_LIGHT, ModernTheme.CARD_DARK),
            corner_radius=10,
        )
        self.scroll_form.pack(fill="both", expand=True, padx=20, pady=(20, 10))

        # ── Auto-scroll helper (same as PropertyEditModal) ────────────────────
        def _scroll_to_widget(widget):
            try:
                canvas = self.scroll_form._parent_canvas
                widget.update_idletasks()
                wy = widget.winfo_y()
                wh = widget.winfo_height()
                ch = canvas.winfo_height()
                scroll_region = canvas.cget("scrollregion")
                if not scroll_region:
                    return
                total_h = float(scroll_region.split()[3])
                if total_h <= 0:
                    return
                target_top = wy - (ch // 2) + (wh // 2)
                target_top = max(0, min(target_top, total_h - ch))
                canvas.yview_moveto(target_top / total_h)
            except Exception:
                pass

        # ── Fields ────────────────────────────────────────────────────────────
        fields = [
            ("PIN (Property Index Number)", "pin"),
            ("TD Number *",                 "td_number"),
            ("Lot Number",                  "lot_number"),
            ("Block Number",                "block_number"),
            ("Owner Name *",                "owner_name"),
            ("Assessed Value *",            "assessed_value"),
            ("Previous TD Number",          "prev_td_number"),
            ("Effectivity Year (e.g. 2024)","effectivity_date"),
        ]

        for label, key in fields:
            ctk.CTkLabel(
                self.scroll_form,
                text=label.upper(),
                font=("Segoe UI", 9, "bold"),
                text_color="gray",
            ).pack(anchor="w", padx=10, pady=(10, 0))
            var = tk.StringVar()
            entry = ctk.CTkEntry(self.scroll_form, height=40, textvariable=var)
            entry.pack(fill="x", padx=10, pady=(0, 5))
            entry.bind("<FocusIn>", lambda e, w=entry: self.after_idle(_scroll_to_widget, w))
            self.vars[key] = var

        # Barangay autocomplete
        ctk.CTkLabel(
            self.scroll_form,
            text="BARANGAY *",
            font=("Segoe UI", 9, "bold"),
            text_color="gray",
        ).pack(anchor="w", padx=10, pady=(10, 0))
        self.brgy_var = ctk.StringVar(value="")
        brgy_drop = AutocompleteComboBox(
            self.scroll_form,
            values=[
                "NORTH POBLACION", "SOUTH POBLACION", "BAYABAS", "BORLONGAN",
                "BUENAVISTA", "CALAOCAN", "DIAMANEN", "DIANED", "DIARABASIN",
                "DIBUTUNAN", "DIMABUNO", "DINADIAWAN", "DITALE", "GUPA",
                "IPIL", "LABOY", "LIPIT", "LOBBOT", "MALIGAYA", "MIJARES",
                "MUCDOL", "PUANGI", "SALAY", "SAPANGKAWAYAN", "TOYTOYAN",
            ],
            variable=self.brgy_var,
            height=40,
            placeholder="Type barangay name...",
        )
        brgy_drop.pack(fill="x", padx=10, pady=(0, 5))
        brgy_drop.bind("<FocusIn>", lambda e, w=brgy_drop: self.after_idle(_scroll_to_widget, w))

        # ── Footer — same layout as PropertyEditModal ─────────────────────────
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=20, pady=20)

        ctk.CTkButton(
            footer,
            text="CANCEL",
            command=self.destroy,
            fg_color="#95a5a6",
            hover_color="#7f8c8d",
            width=120,
            height=44,
        ).pack(side="left")

        ctk.CTkButton(
            footer,
            text="SAVE TO ROLL",
            command=self.save,
            fg_color="#2ecc71",
            hover_color="#27ae60",
            width=200,
            height=44,
            state="normal",
        ).pack(side="right")

    def save(self):
        data = {k: v.get().strip() for k, v in self.vars.items()}
        data["barangay"] = self.brgy_var.get()

        if (
            not data["td_number"]
            or not data["owner_name"]
            or not data["barangay"]
        ):
            messagebox.showerror(
                "Validation Error",
                "TD Number, Owner Name, and Barangay are required.",
                parent=self,
            )
            return

        api_payload = {
            "PIN":              data["pin"],
            "TD Number":        data["td_number"],
            "Lot Number":       data["lot_number"],
            "Block Number":     data["block_number"],
            "Owner Name":       data["owner_name"],
            "Assessed Value":   data["assessed_value"],
            "Previous TD Number": data["prev_td_number"],
            "Effectivity Date": data["effectivity_date"],
            "Barangay":         data["barangay"],
        }

        try:
            prop_svc.save_property(api_payload, user=self.user)
            self.attributes("-topmost", False)
            messagebox.showinfo(
                "Success",
                "Assessment record successfully added to the Roll.",
                parent=self,
            )
            self.callback()
            self.destroy()
        except Exception as e:
            self.attributes("-topmost", False)
            messagebox.showerror("Error", str(e), parent=self)
            self.attributes("-topmost", True)
