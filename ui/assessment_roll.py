import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from theme_manager import ModernTheme
from utils import tr
import api_clients.property_service as prop_svc
import api_clients.api_helper as api
from ui.dossier import PropertyDossierModal
from ui.import_wizard import ImportWizardModal
import threading


class AssessmentRollPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.next_cursor = None
        self.cursor_history = [] # For going back if we want
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
        self.search_ent.bind("<KeyRelease>", self.on_search_key)

        # Kind of Property Filter
        ctk.CTkLabel(
            filters_fr, text="KIND:", font=("Segoe UI", 10, "bold"), text_color="gray"
        ).pack(side="left", padx=(20, 5))
        self.kind_var = tk.StringVar(value="ALL")
        self.kind_cb = ctk.CTkComboBox(
            filters_fr,
            values=["ALL", "LAND", "BUILDING", "MACHINERY", "OTHERS"],
            variable=self.kind_var,
            width=140,
        )
        self.kind_cb.pack(side="left")
        self.kind_cb.configure(command=lambda e: self.refresh_table())

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
        self.year_start_ent.bind("<KeyRelease>", self.on_search_key)

        ctk.CTkLabel(
            filters_fr, text="TO:", font=("Segoe UI", 10, "bold"), text_color="gray"
        ).pack(side="left", padx=(5, 5))
        self.year_end_ent = ctk.CTkEntry(filters_fr, width=80, placeholder_text="YYYY")
        self.year_end_ent.pack(side="left")
        self.year_end_ent.bind("<KeyRelease>", self.on_search_key)

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
            filters_fr,
            text="📄 BULK PRINT SOA",
            command=lambda: self.start_bulk_print("SOA"),
            fg_color="#e67e22",
            width=130,
        ).pack(side="right", padx=5)

        ctk.CTkButton(
            filters_fr,
            text="⚠️ BULK NOTICES",
            command=lambda: self.start_bulk_print("NOTICE"),
            fg_color="#c0392b",
            width=130,
        ).pack(side="right", padx=5)
        ctk.CTkButton(
            header,
            text="+ ADD RECORD",
            command=self.open_modal,
            fg_color="#27ae60",
            width=120,
        ).pack(side="right")

        # --- TABLE ---
        table_fr = ctk.CTkFrame(self.container, fg_color="white", corner_radius=12)
        table_fr.pack(fill="both", expand=True)

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
        self.tree.column("LOCATION", anchor="w")

        scrolly = ttk.Scrollbar(table_fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrolly.set)

        # Zebra Tags
        self.tree.tag_configure("oddrow", background="#2b2b2b", foreground="white")
        self.tree.tag_configure("evenrow", background="#333333", foreground="white")

        self.tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrolly.pack(side="right", fill="y")
        
        # Bind scroll event for lazy loading
        self.tree.bind("<MouseWheel>", self.handle_scroll)
        self.tree.bind("<Button-4>", self.handle_scroll) # Linux
        self.tree.bind("<Button-5>", self.handle_scroll) # Linux

        # --- PAGINATION BAR ---
        self.pag_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        self.pag_fr.pack(fill="x", pady=10)

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
        
        # Initially hidden as we move to infinite scroll, but kept for manual overrides
        self.pag_fr.pack_forget()

        self.tree.bind("<Double-1>", lambda e: self.open_dossier())

    def handle_scroll(self, event=None):
        """Detects if the user has reached the bottom of the table to trigger lazy loading."""
        if self.is_loading or self.all_loaded:
            return
            
        # Get scroll position (0 to 1)
        # If at the bottom (~90%), fetch next page
        if self.tree.yview()[1] > 0.9:
            self.next_page()

    def on_search_key(self, event=None):
        if self.search_timer:
            self.container.after_cancel(self.search_timer)
        self.search_timer = self.container.after(500, self.refresh_table)

    def refresh_table(self, reset_page=True):
        if reset_page:
            self.next_cursor = None
            self.cursor_history = []
            self.all_loaded = False
            
        if self.is_loading:
            return
            
        self.is_loading = True

        def worker():
            try:
                term = self.search_ent.get().strip()
                kind = self.kind_var.get()
                y_start = self.year_start_ent.get().strip()
                y_end = self.year_end_ent.get().strip()
                
                response = prop_svc.search_properties(
                    term,
                    limit=self.page_size,
                    cursor=self.next_cursor if not reset_page else None,
                    kind=kind,
                    year_start=y_start,
                    year_end=y_end,
                )
                
                results = response.get("items", [])
                self.next_cursor = response.get("next_cursor")
                if not response.get("has_more"):
                    self.all_loaded = True

                self.container.after(0, lambda: self._update_table(results, append=not reset_page))
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Error", str(err)))
            finally:
                self.is_loading = False

        threading.Thread(target=worker, daemon=True).start()

    def next_page(self):
        if not self.all_loaded:
            self.refresh_table(reset_page=False)

    def prev_page(self):
        # We use infinite scroll with append=True, so 'Back' is naturally handled by scrolling up.
        pass

    def _update_table(self, results, append=False):
        self.page_lbl.configure(text="INFINITE ROLL" if append else "ASSESSMENT ROLL")
        self.prev_btn.configure(state="disabled") # Disabled for cursor mode
        
        if not results:
            if not append:
                # Silently clear table without annoying pop-ups during live search
                for item in self.tree.get_children():
                    self.tree.delete(item)
            else:
                self.all_loaded = True
            return

        if len(results) < self.page_size:
            self.all_loaded = True
            self.next_btn.configure(state="disabled")
        else:
            self.next_btn.configure(state="normal")

        if not append:
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
        td_number = vals[2]  # TD Number is index 2 in this table

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

    def start_bulk_print(self, mode="SOA"):
        """Orchestrates the bulk generation process with a progress overlay."""
        sel_count = len(self.tree.get_children())
        if sel_count == 0:
            messagebox.showwarning("Bulk Print", "No records found in the current view. Please search or refresh first.")
            return

        if not messagebox.askyesno("Bulk Print", f"Are you sure you want to generate {mode}s for all {sel_count} properties in the current view? This may take a moment."):
            return

        # 1. Loading Overlay
        overlay = ctk.CTkToplevel(self.parent)
        overlay.overrideredirect(True)
        overlay.geometry("400x150")
        overlay.attributes("-topmost", True)
        
        sw, sh = overlay.winfo_screenwidth(), overlay.winfo_screenheight()
        overlay.geometry(f"+{(sw-400)//2}+{(sh-150)//2}")

        ctk.CTkLabel(overlay, text=f"⚡ GENERATING BULK {mode}s...", font=("Segoe UI", 14, "bold"), text_color="#d35400").pack(pady=(20, 5))
        prog = ctk.CTkProgressBar(overlay, width=300)
        prog.pack(pady=10)
        prog.set(0)
        status_lbl = ctk.CTkLabel(overlay, text="Initializing engine...", font=("Segoe UI", 10))
        status_lbl.pack()

        def worker():
            try:
                # 1. Collect IDs for properties in the current view
                property_ids = []
                for child in self.tree.get_children():
                    property_ids.append(int(self.tree.item(child)["values"][0]))
                
                if not property_ids:
                    raise Exception("No property IDs found for generation.")

                self.container.after(0, lambda: [prog.set(0.3), status_lbl.configure(text="Requesting server-side generation...")])
                
                # 2. Call the new API endpoint
                payload = {
                    "property_ids": property_ids,
                    "filename_prefix": "BULK_SOA" if mode == "SOA" else "BULK_NOTICES"
                }
                
                # Request raw response to get bytes
                response = api.api_request("POST", "/billing/bulk-soa", data=payload, raw_response=True)
                
                self.container.after(0, lambda: [prog.set(0.8), status_lbl.configure(text="Downloading document...")])
                
                # 3. Save the received file locally
                import os
                if not os.path.exists("receipts"):
                    os.makedirs("receipts")
                
                filename = response.headers.get("Content-Disposition", f"attachment; filename=bulk_{mode.lower()}.pdf").split("filename=")[-1]
                output_path = os.path.join("receipts", filename)
                
                with open(output_path, "wb") as f:
                    f.write(response.content)
                
                self.container.after(0, lambda: [
                    overlay.destroy(), 
                    os.startfile(os.path.abspath(output_path)), 
                    messagebox.showinfo("Success", f"Bulk {mode} generation complete!\n\nFile saved to: {output_path}")
                ])
                
            except Exception as e:
                self.container.after(0, lambda err=e: [overlay.destroy(), messagebox.showerror("Bulk Print Error", str(err))])

        threading.Thread(target=worker, daemon=True).start()


class AssessmentModal(ctk.CTkToplevel):
    def __init__(self, parent, callback, user=None):
        super().__init__(parent)
        self.title("Assessment Record Entry")
        self.geometry("600x800")
        self.resizable(False, False)
        self.callback = callback
        self.user = user
        self.vars = {}

        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)

        # Center
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-600)//2}+{(sh-800)//2}")

        self.setup_ui()

    def setup_ui(self):
        self.configure(fg_color="#f8f9fa")

        # Header
        ctk.CTkLabel(
            self,
            text="📜 NEW ASSESSMENT RECORD",
            font=("Segoe UI", 16, "bold"),
            text_color="#1f538d",
        ).pack(pady=20)

        container = ctk.CTkScrollableFrame(self, fg_color="white", corner_radius=15)
        container.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        fields = [
            ("PIN (Property Index Number)", "pin"),
            ("TD Number *", "td_number"),
            ("Lot Number", "lot_number"),
            ("Block Number", "block_number"),
            ("Owner Name *", "owner_name"),
            ("Assessed Value *", "assessed_value"),
            ("Previous TD Number", "prev_td_number"),
            ("Effectivity Year (e.g., 2024)", "effectivity_date"),
        ]

        for label, key in fields:
            ctk.CTkLabel(
                container,
                text=label.upper(),
                font=("Segoe UI", 9, "bold"),
                text_color="gray",
            ).pack(anchor="w", padx=15, pady=(10, 0))
            var = tk.StringVar()
            ent = ctk.CTkEntry(container, height=38, textvariable=var)
            ent.pack(fill="x", padx=15, pady=(0, 5))
            self.vars[key] = var

        # Barangay Dropdown
        ctk.CTkLabel(
            container,
            text="BARANGAY *",
            font=("Segoe UI", 9, "bold"),
            text_color="gray",
        ).pack(anchor="w", padx=15, pady=(10, 0))
        self.brgy_var = ctk.StringVar(value="SELECT BARANGAY")
        self.brgy_drop = ctk.CTkComboBox(
            container,
            values=[
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
            ],
            variable=self.brgy_var,
            height=38,
        )
        self.brgy_drop.pack(fill="x", padx=15, pady=(0, 20))

        # Footer
        footer = ctk.CTkFrame(
            self, fg_color="white", height=80, border_width=1, border_color="#e0e0e0"
        )
        footer.pack(side="bottom", fill="x")

        ctk.CTkButton(
            footer,
            text="CANCEL",
            command=self.destroy,
            fg_color="#95a5a6",
            width=120,
            height=45,
        ).pack(side="left", padx=30, pady=15)
        ctk.CTkButton(
            footer,
            text="SAVE TO ROLL",
            command=self.save,
            fg_color="#2ecc71",
            width=250,
            height=45,
        ).pack(side="right", padx=30, pady=15)

    def save(self):
        data = {k: v.get().strip() for k, v in self.vars.items()}
        data["barangay"] = self.brgy_var.get()

        # Mandatory Check (PIN removed from mandatory)
        if (
            not data["td_number"]
            or not data["owner_name"]
            or data["barangay"] == "SELECT BARANGAY"
        ):
            messagebox.showerror(
                "Error", "TD Number, Owner, and Barangay are required!"
            )
            return

        # Standardize keys for service
        api_payload = {
            "PIN": data["pin"],
            "TD Number": data["td_number"],
            "Lot Number": data["lot_number"],
            "Block Number": data["block_number"],
            "Owner Name": data["owner_name"],
            "Assessed Value": data["assessed_value"],
            "Previous TD Number": data["prev_td_number"],
            "Effectivity Date": data["effectivity_date"],
            "Barangay": data["barangay"],
        }

        try:
            # Pass user for audit logging and RBAC
            prop_svc.save_property(api_payload, user=self.user)
            self.attributes("-topmost", False)
            messagebox.showinfo(
                "Success",
                "Assessment Record successfully added to the Roll.",
                parent=self,
            )
            self.callback()
            self.destroy()
        except Exception as e:
            self.attributes("-topmost", False)
            messagebox.showerror("Error", str(e), parent=self)
            self.attributes("-topmost", True)
