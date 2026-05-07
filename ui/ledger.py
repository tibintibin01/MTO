import os
import threading
import customtkinter as ctk
from tkinter import messagebox, ttk
import tkinter as tk
from theme_manager import ModernTheme
import services.payment_service as payment
import services.auth_service as auth
import services.system_service as system
from utils import format_curr
from receipt_generator import generate_or_receipt

class LedgerPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.is_loading = False
        self.setup_ui()

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        header = ctk.CTkFrame(self.container, fg_color="transparent")
        header.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(header, text="Unified Financial Ledger", font=ModernTheme.H2).pack(side="left")
        ctk.CTkLabel(header, text="Integrated Payment & Receipt History", font=ModernTheme.BODY, text_color="gray").pack(side="left", padx=20)

        # Toolbar
        toolbar = ctk.CTkFrame(self.container, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, 15))

        self.search_ent = ctk.CTkEntry(toolbar, placeholder_text="Search TD Number, Owner, or OR Number...", width=450, height=35)
        self.search_ent.pack(side="left")
        self.search_ent.bind("<Return>", lambda e: self.load_ledger())

        self.search_btn = ctk.CTkButton(toolbar, text="🔍 FETCH HISTORY", command=self.load_ledger, width=150, height=35)
        self.search_btn.pack(side="left", padx=10)

        # Action Buttons
        self.view_btn = ctk.CTkButton(toolbar, text="📄 VIEW RECEIPT", command=self.open_receipt, 
                                     fg_color="#3498db", hover_color="#2980b9", width=120, height=35, state="disabled")
        self.view_btn.pack(side="right", padx=5)
        
        self.regen_btn = ctk.CTkButton(toolbar, text="♻️ REGENERATE", command=self.regenerate_receipt,
                                      fg_color="#27ae60", hover_color="#219150", width=120, height=35, state="disabled")
        self.regen_btn.pack(side="right", padx=5)

        # --- THE LEDGER TABLE ---
        t_frame = ctk.CTkFrame(self.container)
        t_frame.pack(fill="both", expand=True, pady=(0, 20))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", rowheight=35, font=("Segoe UI", 10), background="#2b2b2b", fieldbackground="#2b2b2b", foreground="white")
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#333333", foreground="white")

        # Internal ID, Date, OR, Year, Basic, SEF, Penalty, Discount, Total, PostedBy, FilePath
        self.cols = ("ID", "Date", "OR Number", "Tax Year", "Basic", "SEF", "Penalty", "Discount", "Total Paid", "Posted By", "File Status")
        self.tree = ttk.Treeview(t_frame, columns=self.cols, show="headings")
        
        for col in self.cols:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=100, anchor="center")

        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.column("OR Number", width=120)
        self.tree.column("Total Paid", width=130)
        self.tree.column("Posted By", width=150)
        self.tree.column("File Status", width=120)

        scrolly = ttk.Scrollbar(t_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrolly.set)
        
        # Zebra Tags
        self.tree.tag_configure('oddrow', background="#2b2b2b", foreground="white")
        self.tree.tag_configure('evenrow', background="#333333", foreground="white")
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrolly.pack(side="right", fill="y")
        
        self.tree.bind("<<TreeviewSelect>>", self.on_selection_change)
        self.tree.bind("<Double-1>", lambda e: self.open_receipt())

        # --- FOOTER SUMMARY ---
        self.footer = ctk.CTkFrame(self.container, height=60, fg_color="#2ecc71", corner_radius=8)
        self.footer.pack(fill="x", side="bottom")
        
        self.total_lbl = ctk.CTkLabel(self.footer, text="Lifetime Payments: ₱ 0.00", 
                                      font=("Segoe UI", 15, "bold"), text_color="white")
        self.total_lbl.pack(side="right", padx=30, pady=15)

    def on_selection_change(self, event=None):
        sel = self.tree.selection()
        state = "normal" if sel else "disabled"
        self.view_btn.configure(state=state)
        regen_state = state if auth.has_permission(self.user, "receipt_generate") else "disabled"
        self.regen_btn.configure(state=regen_state)

    def load_ledger(self):
        term = self.search_ent.get().strip()
        if not term:
            messagebox.showwarning("Input Required", "Please enter a TD Number, Owner Name, or OR Number.")
            return

        if self.is_loading: return
        self.is_loading = True
        self.search_btn.configure(state="disabled")

        for r in self.tree.get_children(): self.tree.delete(r)

        def worker():
            try:
                # Unified query returns: payment_id(0), date_paid(1), or_number(2), tax_year(3), 
                # basic(4), sef(5), penalty(6), amount(7), posted_by(8), file_path(9), receipt_id(10)
                rows = payment.get_unified_payment_history(term)
                self.container.after(0, lambda: self._update_ui(rows, term))
            except Exception as e:
                self.container.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self.is_loading = False
                self.container.after(0, lambda: self.search_btn.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _update_ui(self, rows, term):
        grand_total = 0.0
        if rows:
            for i, r in enumerate(rows):
                # r: 0:pay_id, 1:date, 2:or, 3:year, 4:basic, 5:sef, 6:pen, 7:disc, 8:amt, 9:user, 10:path, 11:rid
                f_r = list(r[:10]) # Get core 10 columns (ID to Posted By)
                # Status based on file_path (which is index 10 in r)
                status = "📄 READY" if r[10] and os.path.exists(r[10]) else "❌ MISSING"
                f_r.append(status)
                
                # Format Currencies
                f_r[4] = format_curr(f_r[4]) # Basic
                f_r[5] = format_curr(f_r[5]) # SEF
                f_r[6] = format_curr(f_r[6]) # Penalty
                f_r[7] = format_curr(f_r[7]) # Discount
                f_r[8] = format_curr(f_r[8]) # Total
                
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                self.tree.insert("", "end", values=f_r, tags=(r[10], tag)) # Store path and zebra tag
                try: grand_total += float(r[8])
                except: pass
            self.total_lbl.configure(text=f"Lifetime Payments for Record: ₱ {grand_total:,.2f}")
        else:
            messagebox.showinfo("Not Found", f"No financial history found for '{term}'.")
            self.total_lbl.configure(text="Lifetime Payments: ₱ 0.00")
        self.on_selection_change()

    def open_receipt(self):
        sel = self.tree.selection()
        if not sel: return
        
        item = self.tree.item(sel[0])
        pay_id = item["values"][0]
        file_path = item["tags"][0] if item["tags"] else None
        
        if file_path and os.path.exists(str(file_path)):
            try: os.startfile(file_path)
            except Exception as e: messagebox.showerror("Error", f"Could not open PDF: {e}")
        else:
            if messagebox.askyesno("Receipt Missing", "PDF file not found. Generate it now?"):
                self.regenerate_receipt()

    def regenerate_receipt(self):
        sel = self.tree.selection()
        if not sel: return
        
        pay_id = self.tree.item(sel[0])["values"][0]
        
        def worker():
            try:
                details = payment.get_payment_receipt_details(pay_id)
                if not details: raise Exception("Payment details not found.")
                
                base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                new_path = generate_or_receipt(details, base_dir)
                
                # Persist path
                payment.save_receipt_record(details["property_id"], pay_id, details, new_path, self.user)
                system.log_action(self.user, f"Regenerated receipt OR {details['or_number']}")
                
                self.container.after(0, lambda: [self.load_ledger(), os.startfile(new_path)])
            except Exception as e:
                err_msg = str(e)
                self.container.after(0, lambda: messagebox.showerror("Generation Error", err_msg))

        threading.Thread(target=worker, daemon=True).start()
