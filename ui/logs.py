import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
from theme_manager import ModernTheme
import threading
import services.auth_service as auth
import services.system_service as system
import json

class AuditLogsPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.setup_ui()
        self.refresh()

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        ctk.CTkLabel(self.container, text="System Audit Engine", font=ModernTheme.H2).pack(anchor="w", pady=(0, 20))

        # Stats Area
        stats_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        stats_fr.pack(fill="x", pady=(0, 15))
        stats_fr.grid_columnconfigure((0, 1, 2), weight=1)

        self.total_logs_lbl = self._create_stat_card(stats_fr, "TOTAL ACTIONS", "#34495e", 0)
        self.today_logs_lbl = self._create_stat_card(stats_fr, "TODAY", "#27ae60", 1)
        self.active_users_lbl = self._create_stat_card(stats_fr, "AUDITED ENTITIES", "#2980b9", 2)

        # Toolbar
        toolbar = ctk.CTkFrame(self.container, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(toolbar, text="FILTER BY USER", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 10))
        self.user_cb = ctk.CTkComboBox(toolbar, values=["All Users"], width=200, height=35)
        self.user_cb.set("All Users")
        self.user_cb.pack(side="left")
        
        self.refresh_btn = ctk.CTkButton(toolbar, text="REFRESH TRACE", command=self.refresh, fg_color="#3498db", width=120, height=35)
        self.refresh_btn.pack(side="left", padx=10)

        # Table Area
        table_fr = ctk.CTkFrame(self.container)
        table_fr.pack(fill="both", expand=True, pady=(0, 15))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", rowheight=35, font=("Segoe UI", 10), background="#2b2b2b", fieldbackground="#2b2b2b", foreground="white")
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#333333", foreground="white")

        self.cols = ("ID", "Timestamp", "User", "Action", "Target", "Old Values", "New Values")
        self.tree = ttk.Treeview(table_fr, columns=self.cols, show="headings", height=15)
        
        for col in self.cols:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, anchor="center", width=120)
        
        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.column("Action", width=300, anchor="w")
        self.tree.column("Old Values", width=200)
        self.tree.column("New Values", width=200)

        # Zebra Tags
        self.tree.tag_configure('oddrow', background="#2b2b2b", foreground="white")
        self.tree.tag_configure('evenrow', background="#333333", foreground="white")

        scrolly = ttk.Scrollbar(table_fr, orient="vertical", command=self.tree.yview)
        scrollx = ttk.Scrollbar(table_fr, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrolly.set, xscrollcommand=scrollx.set)
        
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrolly.grid(row=0, column=1, sticky="ns")
        scrollx.grid(row=1, column=0, sticky="ew")
        
        table_fr.grid_rowconfigure(0, weight=1)
        table_fr.grid_columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self.show_detailed_diff)

    def _create_stat_card(self, parent, title, color, col):
        card = ctk.CTkFrame(parent)
        card.grid(row=0, column=col, padx=10, sticky="nsew")
        ctk.CTkLabel(card, text=title, font=("Segoe UI", 10, "bold"), text_color="gray").pack(pady=(15, 0))
        value_lbl = ctk.CTkLabel(card, text="0", font=("Segoe UI", 24, "bold"), text_color=color)
        value_lbl.pack(pady=(0, 15))
        return value_lbl

    def refresh(self):
        def worker():
            try:
                # Load stats
                stats = system.get_audit_stats()
                self.container.after(0, lambda: self._update_stats(stats))
                
                # Load users for filter
                users = auth.get_all_users()
                user_list = ["All Users"] + [u["username"] for u in users]
                
                # Zombie Fix: Guard against destroyed widget if user switched pages
                def update_cb():
                    try: self.user_cb.configure(values=user_list)
                    except: pass
                self.container.after(0, update_cb)
                
                # Load logs
                selected_username = self.user_cb.get()
                user_id = None
                if selected_username != "All Users":
                    user_match = next((u for u in users if u["username"] == selected_username), None)
                    if user_match: user_id = user_match["id"]
                
                logs = auth.get_audit_logs(user_id=user_id)
                self.container.after(0, lambda: self._update_table(logs))
            except Exception as e:
                # Lambda Scope Fix: Pass e=e to lock the error object in memory
                self.container.after(0, lambda e=e: messagebox.showerror("Audit Engine Error", str(e)))
        
        threading.Thread(target=worker, daemon=True).start()

    def _update_stats(self, stats):
        self.total_logs_lbl.configure(text=str(stats.get("total", 0)))
        self.today_logs_lbl.configure(text=str(stats.get("today", 0)))
        self.active_users_lbl.configure(text=str(stats.get("active_users", 0)))

    def _update_table(self, logs):
        for row in self.tree.get_children(): self.tree.delete(row)
        for i, l in enumerate(logs):
            ts_raw = l.get("timestamp")
            if isinstance(ts_raw, str):
                ts = ts_raw.replace("T", " ")[:19]
            elif ts_raw:
                ts = ts_raw.strftime("%Y-%m-%d %H:%M:%S")
            else:
                ts = ""
            
            target = f"{l['table_name'] or ''} #{l['record_id'] or ''}"
            old_v = l["old_values"] if l["old_values"] else ""
            new_v = l["new_values"] if l["new_values"] else ""
            
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            self.tree.insert("", "end", values=(l["id"], ts, l["username"], l["action"], target, old_v, new_v), tags=(tag,))

    def show_detailed_diff(self, event):
        sel = self.tree.selection()
        if not sel: return
        
        vals = self.tree.item(sel[0])["values"]
        old_v = vals[5]
        new_v = vals[6]
        
        if not old_v and not new_v: return
        
        diff_window = ctk.CTkToplevel(self.container)
        diff_window.title("Activity Detail: Before vs After")
        diff_window.geometry("600x400")
        diff_window.attributes("-topmost", True)
        
        ctk.CTkLabel(diff_window, text="DATA TRACEBACK", font=("Segoe UI", 12, "bold")).pack(pady=15)
        
        main_fr = ctk.CTkFrame(diff_window, fg_color="transparent")
        main_fr.pack(fill="both", expand=True, padx=20, pady=10)
        main_fr.grid_columnconfigure((0, 1), weight=1)
        
        # Old values
        old_fr = ctk.CTkFrame(main_fr)
        old_fr.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        ctk.CTkLabel(old_fr, text="ORIGINAL STATE", font=("Segoe UI", 9, "bold"), text_color="#e74c3c").pack(pady=5)
        old_txt = tk.Text(old_fr, font=("Consolas", 9), wrap="word", bg="#2d3436", fg="white", bd=0)
        old_txt.insert("1.0", self._format_json(old_v))
        old_txt.configure(state="disabled")
        old_txt.pack(fill="both", expand=True, padx=5, pady=5)
        
        # New values
        new_fr = ctk.CTkFrame(main_fr)
        new_fr.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ctk.CTkLabel(new_fr, text="MODIFIED STATE", font=("Segoe UI", 9, "bold"), text_color="#2ecc71").pack(pady=5)
        new_txt = tk.Text(new_fr, font=("Consolas", 9), wrap="word", bg="#2d3436", fg="white", bd=0)
        new_txt.insert("1.0", self._format_json(new_v))
        new_txt.configure(state="disabled")
        new_txt.pack(fill="both", expand=True, padx=5, pady=5)

    def _format_json(self, val):
        if not val: return "No data recorded."
        try:
            data = json.loads(val) if isinstance(val, str) else val
            return json.dumps(data, indent=2)
        except:
            return str(val)
