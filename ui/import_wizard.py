import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import api_clients.system_service as system
from utils import tr
from theme_manager import ModernTheme

class ImportWizardModal(ctk.CTkToplevel):
    def __init__(self, parent, mode="property"):
        super().__init__(parent)
        self.mode = mode
        title_map = {
            "property": "Property Bulk Import Wizard",
            "assessment": "Assessment Roll Import Wizard",
            "payments": "Financial Ledger Import Wizard"
        }
        self.title(title_map.get(mode, "Bulk Import Wizard"))
        self.geometry("900x650")
        self.grab_set()
        
        self.validated_data = []
        self.raw_report = []
        self.validation_token = None
        self._closing = False
        
        self.setup_ui()

    def ui_after(self, delay_ms, callback):
        def guarded():
            try:
                exists = self.winfo_exists()
            except tk.TclError:
                return
            if self._closing or not exists:
                return
            callback()
        return self.after(delay_ms, guarded)

    def safe_destroy_widget(self, widget):
        try:
            if widget.winfo_exists():
                widget.destroy()
        except tk.TclError:
            pass

    def setup_ui(self):
        # Header
        ctk.CTkLabel(self, text="BULK IMPORT WIZARD", font=("Segoe UI", 20, "bold")).pack(pady=20)
        
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=30, pady=(0, 20))
        
        self.show_step_1()

    def show_step_1(self):
        # Step 1: File Selection
        self.clear_container()
        
        step_fr = ctk.CTkFrame(self.main_container)
        step_fr.pack(fill="both", expand=True)
        
        ctk.CTkLabel(step_fr, text="STEP 1: SELECT YOUR DATA FILE", font=("Segoe UI", 14, "bold")).pack(pady=30)
        ctk.CTkLabel(step_fr, text="Supported formats: .csv, .xlsx (Excel)", font=("Segoe UI", 11)).pack(pady=(0, 30))
        
        ctk.CTkButton(
            step_fr, 
            text="📁 BROWSE FOR FILE", 
            command=self.browse_file,
            width=250,
            height=45,
            fg_color="#3498db"
        ).pack(pady=10)
        
        ctk.CTkLabel(step_fr, text="Ensure your file has headers like: TD Number, Owner, Assessed Value", text_color="gray").pack(pady=20)

    def show_step_2(self, report_data, total, valid):
        # Step 2: Validation Preview
        self.clear_container()
        
        ctk.CTkLabel(self.main_container, text=f"STEP 2: VALIDATION PREVIEW ({valid}/{total} Rows Ready)", font=("Segoe UI", 14, "bold")).pack(pady=10)
        
        # Table
        table_fr = ctk.CTkFrame(self.main_container, fg_color="transparent", border_width=1, border_color="#334155")
        table_fr.pack(fill="both", expand=True, pady=10)
        
        if self.mode == "payments":
            cols = ("ROW", "TD NUMBER", "SYSTEM OWNER", "OR NUMBER", "YEAR", "TOTAL", "PENALTY", "DISCOUNT", "STATUS", "MESSAGE")
        else:
            cols = ("ROW", "TD NUMBER", "OWNER", "LOT", "ACTION", "STATUS", "MESSAGE")
            
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Import.Treeview",
                        rowheight=35,
                        font=ModernTheme.BODY,
                        background="#1e1e1e",
                        fieldbackground="#1e1e1e",
                        foreground="white")
        style.configure("Import.Treeview.Heading",
                        font=ModernTheme.BODY_BOLD,
                        background="#333333",
                        foreground="white")

        # ── Layout: scrollbars packed BEFORE the treeview ────────────────────
        # Pack order matters in tkinter: side="bottom" scrollbar must be packed
        # before side="left" treeview, otherwise the treeview expands over it.
        scrolly = ttk.Scrollbar(table_fr, orient="vertical")
        scrollx = ttk.Scrollbar(table_fr, orient="horizontal")
        scrolly.pack(side="right", fill="y")
        scrollx.pack(side="bottom", fill="x")   # ← must come before tree.pack

        self.tree = ttk.Treeview(
            table_fr, columns=cols, show="headings",
            style="Import.Treeview",
            yscrollcommand=scrolly.set,
            xscrollcommand=scrollx.set,
        )
        scrolly.configure(command=self.tree.yview)
        scrollx.configure(command=self.tree.xview)

        # Column widths — wide enough to show full content without truncation
        if self.mode == "payments":
            col_widths = {
                "ROW":          55,
                "TD NUMBER":    130,
                "SYSTEM OWNER": 200,
                "OR NUMBER":    100,
                "YEAR":          70,
                "TOTAL":         90,
                "PENALTY":       80,
                "DISCOUNT":      80,
                "STATUS":        90,
                "MESSAGE":      320,
            }
        else:
            col_widths = {
                "ROW":       55,
                "TD NUMBER": 130,
                "OWNER":     180,
                "LOT":       100,
                "ACTION":     80,
                "STATUS":     90,
                "MESSAGE":   280,
            }

        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center",
                             width=col_widths.get(col, 80),
                             minwidth=50)

        # Left-align text-heavy columns
        for col in ("SYSTEM OWNER", "OWNER", "MESSAGE"):
            if col in cols:
                self.tree.column(col, anchor="w")

        self.tree.tag_configure("ERROR",    background="#ffdada", foreground="black")
        self.tree.tag_configure("VALID",    background="#eaffea", foreground="black")
        self.tree.tag_configure("CONFLICT", background="#fff4d1", foreground="black")
        self.tree.tag_configure("WARNING",  background="#fff4d1", foreground="black")

        self.tree.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)

        
        # Fill table
        for r in report_data:
            if "ERROR" in r["status"]: tag = "ERROR"
            elif "CONFLICT" in r["status"]: tag = "CONFLICT"
            else: tag = "VALID"
            
            if self.mode == "payments":
                vals = (
                    r["row_index"],
                    r["td_number"],
                    r.get("system_owner", "N/A"),
                    r.get("or_number", "N/A"),
                    r.get("tax_year", "N/A"),
                    r.get("amount_paid", "0.00"),
                    r.get("penalty", "0.00"),
                    r.get("discount", "0.00"),
                    r["status"],
                    r["message"]
                )
            else:
                vals = (
                    r["row_index"],
                    r["td_number"],
                    r["owner_name"],
                    r.get("lot_number", "N/A"),
                    r.get("action", "N/A"),
                    r["status"],
                    r["message"]
                )
            self.tree.insert("", "end", values=vals, tags=(tag,))

        
        # Bottom controls
        btn_fr = ctk.CTkFrame(self.main_container, fg_color="transparent")
        btn_fr.pack(fill="x", pady=15)
        
        ctk.CTkButton(btn_fr, text="⬅ BACK", command=self.show_step_1, width=100, fg_color="gray").pack(side="left")
        
        self.commit_btn = ctk.CTkButton(
            btn_fr, 
            text=f"🚀 IMPORT {valid} RECORDS", 
            command=self.commit_import,
            fg_color="#2ecc71",
            state="normal" if valid > 0 else "disabled"
        )
        self.commit_btn.pack(side="right")
        
        if valid < total:
            ctk.CTkLabel(btn_fr, text="⚠️ Fix errors in your file and re-upload to import everything.", text_color="#e67e22").pack(side="right", padx=20)

        self.update() # Force GUI refresh

    def browse_file(self):
        fpath = filedialog.askopenfilename(filetypes=[("Data Files", "*.csv *.xlsx")])
        if not fpath: return
        
        # Loading state
        loading = ctk.CTkLabel(self.main_container, text="Validating Data... Please wait.", font=("Segoe UI", 12, "italic"))
        loading.pack(pady=20)
        
        def worker():
            try:
                res = system.validate_import(fpath, mode=self.mode)
                if res.get("success"):
                    self.validated_data = res.get("data", [])
                    self.raw_report = res.get("report", [])
                    self.validation_token = res.get("validation_token") or res.get("cache_token")
                    self.ui_after(0, lambda: self.show_step_2(self.raw_report, res["total_rows"], res["valid_rows"]))
                else:
                    self.ui_after(0, lambda err=res.get("error"): self.safe_show_error("Validation Failed", err or "Unknown error"))
            except Exception as e:
                err_str = str(e)
                self.ui_after(0, lambda err=err_str: self.safe_show_error("Error", err))

            finally:
                self.ui_after(0, lambda: self.safe_destroy_widget(loading))

        
        threading.Thread(target=worker, daemon=True).start()

    def commit_import(self):
        if not self.validated_data:
            messagebox.showwarning("No Data", "No valid rows found to import.")
            return

        count = len(self.validated_data)
        record_type = "payment" if self.mode == "payments" else "property"

        # ── Premium confirmation dialog ───────────────────────────────────────
        confirmed = tk.BooleanVar(value=False)

        dlg = ctk.CTkToplevel(self)
        dlg.title("")
        dlg.resizable(False, False)
        dlg.overrideredirect(True)
        dlg.attributes("-topmost", True)
        dlg.grab_set()

        dlg.update_idletasks()
        dw, dh = 420, 260
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        dlg.geometry(f"{dw}x{dh}+{(sw-dw)//2}+{(sh-dh)//2}")

        outer = ctk.CTkFrame(
            dlg,
            fg_color="#0f172a",
            corner_radius=16,
            border_width=1,
            border_color="#1e3a5f",
        )
        outer.pack(fill="both", expand=True, padx=2, pady=2)

        # Blue accent bar
        ctk.CTkFrame(outer, height=5, fg_color="#1d4ed8", corner_radius=0).pack(fill="x")

        # Icon
        icon_fr = ctk.CTkFrame(
            outer, width=56, height=56, corner_radius=28,
            fg_color="#1e3a5f",
            border_width=2, border_color="#3b82f6",
        )
        icon_fr.pack(pady=(20, 0))
        icon_fr.pack_propagate(False)
        ctk.CTkLabel(
            icon_fr, text="📥",
            font=("Segoe UI Emoji", 22),
            text_color="#60a5fa",
        ).place(relx=0.5, rely=0.5, anchor="center")

        # Title
        ctk.CTkLabel(
            outer,
            text="Confirm Import",
            font=("Inter", 15, "bold"),
            text_color="#f1f5f9",
        ).pack(pady=(10, 2))

        # Message
        ctk.CTkLabel(
            outer,
            text=f"You are about to import  {count:,}  {record_type} records\ninto the system. This action cannot be undone.",
            font=("Inter", 11),
            text_color="#94a3b8",
            justify="center",
        ).pack(pady=(0, 4))

        # Divider
        ctk.CTkFrame(outer, height=1, fg_color="#1e293b").pack(fill="x", padx=20, pady=(10, 0))

        # Buttons
        btn_fr = ctk.CTkFrame(outer, fg_color="transparent")
        btn_fr.pack(pady=14)

        def on_cancel():
            confirmed.set(False)
            dlg.grab_release()
            dlg.destroy()

        def on_confirm():
            confirmed.set(True)
            dlg.grab_release()
            dlg.destroy()

        ctk.CTkButton(
            btn_fr, text="CANCEL",
            command=on_cancel,
            fg_color="#1e293b",
            hover_color="#334155",
            text_color="#94a3b8",
            border_width=1,
            border_color="#334155",
            font=("Inter", 12, "bold"),
            width=130, height=38, corner_radius=8,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_fr, text=f"  IMPORT {count:,}  ",
            command=on_confirm,
            fg_color="#1d4ed8",
            hover_color="#1e40af",
            text_color="white",
            font=("Inter", 12, "bold"),
            width=150, height=38, corner_radius=8,
        ).pack(side="left")

        dlg.bind("<Return>", lambda e: on_confirm())
        dlg.bind("<Escape>", lambda e: on_cancel())
        dlg.focus_set()
        dlg.wait_window()

        if not confirmed.get():
            return

        # Disable button and show loading indicator
        self.commit_btn.configure(state="disabled", text="⏳ IMPORTING... PLEASE WAIT")
        loading = ctk.CTkLabel(self.main_container, text="Saving records to database... This may take a few moments.", font=("Segoe UI", 12, "italic", "bold"), text_color="#e67e22")
        loading.pack(pady=10)
        
        # FORCE IMMEDIATE UI REPAINT to clear the messagebox artifact
        self.update()
            
        def worker():
            try:
                if self.validation_token:
                    payload = {"validation_token": self.validation_token}
                else:
                    payload = self.validated_data
                res = system.commit_import(payload, mode=self.mode)
                if res.get("status") == "success":
                    self.ui_after(0, lambda r=res: self.finish_import(r))
                else:
                    self.ui_after(0, lambda: self.safe_show_error("Import Failed", "Database error during bulk save."))
            except Exception as e:
                err_str = str(e)
                self.ui_after(0, lambda err=err_str: self.safe_show_error("Error", err))
            finally:
                def cleanup():
                    if self.winfo_exists():
                        try:
                            loading.destroy()
                            self.commit_btn.configure(state="normal", text=f"🚀 IMPORT {len(self.validated_data)} RECORDS")
                        except:
                            pass
                self.ui_after(0, cleanup)
        
        threading.Thread(target=worker, daemon=True).start()

    def safe_show_error(self, title, msg):
        try:
            exists = self.winfo_exists()
        except tk.TclError:
            return
        if self._closing or not exists:
            return
        try:
            self.grab_release()
        except tk.TclError:
            pass
        messagebox.showerror(title, msg, parent=self.master)
        if self.winfo_exists() and not self._closing:
            try:
                self.grab_set()
            except tk.TclError:
                pass

    def finish_import(self, stats):
        try:
            exists = self.winfo_exists()
        except tk.TclError:
            return
        if self._closing or not exists:
            return

        # ── Premium success dialog ────────────────────────────────────────────
        if isinstance(stats, dict):
            if "imported" in stats and "details" not in stats and "inserted" not in stats:
                total = int(stats.get("imported") or 0)
                skipped = int(stats.get("skipped") or 0)
                detail = "Records saved to the financial ledger."
                if skipped:
                    detail += f"\n⚠️  Skipped rows: {skipped:,}"
            elif stats.get("details") and isinstance(stats["details"], dict):
                inserted = int(stats["details"].get("inserted") or stats.get("imported") or 0)
                skipped = int(stats["details"].get("skipped") or stats.get("skipped") or 0)
                total = inserted
                detail = f"Records saved to the financial ledger."
                if skipped:
                    detail += f"\n⚠️  Skipped rows: {skipped:,}"
            else:
                inserted = stats.get("inserted", 0)
                updated  = stats.get("updated", 0)
                total    = inserted + updated
                detail   = f"🆕  New records:      {inserted:,}\n🔄  Updated records:  {updated:,}"
        else:
            total  = int(stats or 0)
            detail = f"Records saved to the financial ledger."

        self._closing = True
        try:
            self.grab_release()
        except tk.TclError:
            pass

        # Build the dialog
        dlg = ctk.CTkToplevel(self.master)
        dlg.title("")
        dlg.resizable(False, False)
        dlg.overrideredirect(True)
        dlg.attributes("-topmost", True)
        dlg.grab_set()

        dlg.update_idletasks()
        dw, dh = 420, 280
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        dlg.geometry(f"{dw}x{dh}+{(sw-dw)//2}+{(sh-dh)//2}")

        # Outer frame — dark card
        outer = ctk.CTkFrame(
            dlg,
            fg_color="#0f172a",
            corner_radius=16,
            border_width=1,
            border_color="#1e3a5f",
        )
        outer.pack(fill="both", expand=True, padx=2, pady=2)

        # Green accent bar at top
        bar = ctk.CTkFrame(outer, height=5, fg_color="#10b981", corner_radius=0)
        bar.pack(fill="x")

        # Icon circle
        icon_fr = ctk.CTkFrame(
            outer, width=64, height=64, corner_radius=32,
            fg_color="#064e3b",
            border_width=2, border_color="#10b981",
        )
        icon_fr.pack(pady=(24, 0))
        icon_fr.pack_propagate(False)
        ctk.CTkLabel(
            icon_fr, text="✓",
            font=("Inter", 28, "bold"),
            text_color="#10b981",
        ).place(relx=0.5, rely=0.5, anchor="center")

        # Title
        ctk.CTkLabel(
            outer,
            text=f"Import Complete",
            font=("Inter", 16, "bold"),
            text_color="#f1f5f9",
        ).pack(pady=(12, 2))

        # Count
        ctk.CTkLabel(
            outer,
            text=f"{total:,} records imported successfully",
            font=("Inter", 13),
            text_color="#10b981",
        ).pack()

        # Detail
        ctk.CTkLabel(
            outer,
            text=detail,
            font=("Inter", 11),
            text_color="#64748b",
            justify="left",
        ).pack(pady=(6, 0))

        # Divider
        ctk.CTkFrame(outer, height=1, fg_color="#1e293b").pack(fill="x", padx=20, pady=(16, 0))

        # OK button
        def close_all():
            dlg.grab_release()
            dlg.destroy()
            if self.winfo_exists():
                self.withdraw()
                self.after(300, self.destroy)

        ctk.CTkButton(
            outer,
            text="DONE",
            command=close_all,
            fg_color="#10b981",
            hover_color="#059669",
            text_color="white",
            font=("Inter", 13, "bold"),
            width=140,
            height=38,
            corner_radius=8,
        ).pack(pady=14)

        dlg.bind("<Return>", lambda e: close_all())
        dlg.bind("<Escape>", lambda e: close_all())
        dlg.focus_set()

    def clear_container(self):
        for widget in self.main_container.winfo_children():
            widget.destroy()
