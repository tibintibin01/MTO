import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import api_clients.system_service as system
from utils import tr

class ImportWizardModal(ctk.CTkToplevel):
    def __init__(self, parent, mode="property"):
        super().__init__(parent)
        self.mode = mode
        title_map = {
            "property": "Property Bulk Import Wizard",
            "assessment": "Assessment Roll Import Wizard"
        }
        self.title(title_map.get(mode, "Bulk Import Wizard"))
        self.geometry("900x650")
        self.attributes("-topmost", True)
        self.grab_set()
        
        self.validated_data = []
        self.raw_report = []
        
        self.setup_ui()

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
        table_fr = ctk.CTkFrame(self.main_container)
        table_fr.pack(fill="both", expand=True)
        
        cols = ("ROW", "TD NUMBER", "OWNER", "ACTION", "STATUS", "MESSAGE")
        self.tree = ttk.Treeview(table_fr, columns=cols, show="headings")
        
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center", width=80)
        
        self.tree.column("MESSAGE", width=300, anchor="w")
        self.tree.column("OWNER", width=150, anchor="w")
        
        self.tree.tag_configure("ERROR", background="#ffdada")
        self.tree.tag_configure("VALID", background="#eaffea")
        
        scrolly = ttk.Scrollbar(table_fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrolly.set)
        
        self.tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrolly.pack(side="right", fill="y")
        
        # Fill table
        for r in report_data:
            tag = "ERROR" if "ERROR" in r["status"] else "VALID"
            self.tree.insert("", "end", values=(
                r["row_index"],
                r["td_number"],
                r["owner_name"],
                r.get("action", "N/A"),
                r["status"],
                r["message"]
            ), tags=(tag,))
        
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
                    self.after(0, lambda: self.show_step_2(self.raw_report, res["total_rows"], res["valid_rows"]))
                else:
                    self.after(0, lambda: messagebox.showerror("Validation Failed", res.get("error", "Unknown error")))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self.after(0, loading.destroy)
        
        threading.Thread(target=worker, daemon=True).start()

    def commit_import(self):
        if not self.validated_data:
            messagebox.showwarning("No Data", "No valid rows found to import.")
            return
            
        if not messagebox.askyesno("Confirm Import", f"Are you sure you want to import {len(self.validated_data)} property records into the system?"):
            return
            
        def worker():
            try:
                res = system.commit_import(self.validated_data, mode=self.mode)
                if res.get("status") == "success":
                    self.after(0, lambda: self.finish_import(res["imported"]))
                else:
                    self.after(0, lambda: messagebox.showerror("Import Failed", "Database error during bulk save."))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        
        threading.Thread(target=worker, daemon=True).start()

    def finish_import(self, stats):
        if isinstance(stats, dict):
            msg = f"Import Complete!\n\n🆕 New Records: {stats.get('inserted', 0)}\n🔄 Updated Records: {stats.get('updated', 0)}"
        else:
            msg = f"Successfully imported {stats} records!"
        messagebox.showinfo("Success", msg)
        self.destroy()

    def clear_container(self):
        for widget in self.main_container.winfo_children():
            widget.destroy()
