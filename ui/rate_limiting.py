# -*- coding: utf-8 -*-
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import api_clients.system_service as system
from theme_manager import ModernTheme
from ui_components import show_toast

class RateLimitingPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.next_cursor = None
        self.all_loaded = False
        self.is_loading = False
        self.setup_ui()
        self.refresh()

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        header_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        header_fr.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(header_fr, text="🛑 API RATE LIMITING DASHBOARD", font=ModernTheme.H2).pack(side="left", anchor="w")

        # Stats Area (4 KPI cards)
        stats_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        stats_fr.pack(fill="x", pady=(0, 20))
        stats_fr.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.total_blocks_lbl = self._create_stat_card(stats_fr, "TOTAL BLOCKED REQS", ModernTheme.DANGER, 0)
        self.today_blocks_lbl = self._create_stat_card(stats_fr, "BLOCKED TODAY", ModernTheme.PRIMARY, 1)
        self.top_ip_lbl = self._create_stat_card(stats_fr, "TOP VIOLATING IP", ModernTheme.WARNING, 2)
        self.top_user_lbl = self._create_stat_card(stats_fr, "TOP VIOLATING USER", ModernTheme.SUCCESS, 3)

        # Main Layout (Split: Left is unblock form, Right is logs table)
        main_fr = ctk.CTkFrame(self.container, fg_color="transparent")
        main_fr.pack(fill="both", expand=True)
        main_fr.grid_columnconfigure(0, weight=1)
        main_fr.grid_columnconfigure(1, weight=3)
        main_fr.grid_rowconfigure(0, weight=1)

        # Left Column: Unblock Tools
        left_col = ctk.CTkFrame(main_fr, fg_color=ModernTheme.SECONDARY, corner_radius=10, width=280)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 15))
        left_col.pack_propagate(False)

        ctk.CTkLabel(left_col, text="⚡ QUICK MANUAL UNBLOCK", font=ModernTheme.BODY_BOLD, text_color=ModernTheme.PRIMARY).pack(pady=(15, 10), padx=15, anchor="w")
        ctk.CTkLabel(left_col, text="Enter a client IP address or username to clear all active rate limit blocks from memory/Redis storage.", font=("Segoe UI", 11), text_color="gray", justify="left", wraplength=250).pack(padx=15, anchor="w")

        ctk.CTkLabel(left_col, text="CLIENT IDENTIFIER", font=ModernTheme.BUTTON_SMALL, text_color=ModernTheme.TEXT_GRAY).pack(pady=(20, 2), padx=15, anchor="w")
        self.unblock_entry = ctk.CTkEntry(left_col, placeholder_text="e.g. 192.168.1.1 or user:kevin", height=35, font=ModernTheme.BODY)
        self.unblock_entry.pack(fill="x", padx=15, pady=(0, 15))

        self.unblock_btn = ctk.CTkButton(
            left_col, 
            text="🔓 UNBLOCK CLIENT", 
            command=self.unblock_client_manual, 
            fg_color=ModernTheme.SUCCESS, 
            hover_color="#2e7d32", 
            height=40, 
            font=ModernTheme.BODY_BOLD
        )
        self.unblock_btn.pack(fill="x", padx=15)

        # Info card explaining key structure
        info_card = ctk.CTkFrame(left_col, fg_color="#1e1e1e", corner_radius=5)
        info_card.pack(fill="x", padx=15, pady=25)
        ctk.CTkLabel(info_card, text="💡 Key Format Tips:", font=ModernTheme.BODY_BOLD, text_color="orange").pack(pady=(8, 2), padx=10, anchor="w")
        tips_text = (
            "• IP Format: e.g. 127.0.0.1\n"
            "• User Format: username (e.g. cashier1)\n"
            "• Unblocking is instant across all endpoints.\n"
            "• Hitting logs table rows twice will trigger a quick unblock prompt."
        )
        ctk.CTkLabel(info_card, text=tips_text, font=("Segoe UI", 10), text_color="gray", justify="left").pack(pady=(0, 8), padx=10, anchor="w")

        # Right Column: Toolbar & Table
        right_col = ctk.CTkFrame(main_fr, fg_color="transparent")
        right_col.grid(row=0, column=1, sticky="nsew")
        right_col.grid_rowconfigure(0, weight=0) # Toolbar
        right_col.grid_rowconfigure(1, weight=1) # Table
        right_col.grid_columnconfigure(0, weight=1)

        # Toolbar
        toolbar = ctk.CTkFrame(right_col, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ctk.CTkLabel(toolbar, text="🕒 AUDIT LOG OF BLOCKED REQUESTS (429s)", font=ModernTheme.BODY_BOLD).pack(side="left", anchor="w")

        self.load_more_btn = ctk.CTkButton(toolbar, text="📥 LOAD MORE", command=self.load_more, fg_color=ModernTheme.SECONDARY, width=120, height=30, font=ModernTheme.BUTTON_SMALL)
        self.load_more_btn.pack(side="right", padx=(5, 0))

        self.refresh_btn = ctk.CTkButton(toolbar, text="🔄 REFRESH", command=self.refresh, fg_color=ModernTheme.PRIMARY, width=100, height=30, font=ModernTheme.BUTTON_SMALL)
        self.refresh_btn.pack(side="right", padx=(5, 0))

        self.table_unblock_btn = ctk.CTkButton(
            toolbar, 
            text="🗑️ UNBLOCK SELECTED", 
            command=self.unblock_client_selected, 
            fg_color=ModernTheme.DANGER, 
            width=150, 
            height=30, 
            font=ModernTheme.BUTTON_SMALL
        )
        self.table_unblock_btn.pack(side="right", padx=(5, 0))

        # Table Grid
        table_container = ctk.CTkFrame(right_col)
        table_container.grid(row=1, column=0, sticky="nsew")
        table_container.grid_rowconfigure(0, weight=1)
        table_container.grid_columnconfigure(0, weight=1)

        # Stylize Treeview
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", rowheight=35, font=("Segoe UI", 10), background="#2b2b2b", fieldbackground="#2b2b2b", foreground="white")
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#333333", foreground="white")

        self.cols = ("ID", "TIMESTAMP", "IP ADDRESS", "USERNAME", "ENDPOINT", "TRIGGERED RULE", "RETRY AFTER (S)")
        self.tree = ttk.Treeview(table_container, columns=self.cols, show="headings", height=15)
        
        for col in self.cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center", width=120)
        
        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.column("TIMESTAMP", width=140)
        self.tree.column("IP ADDRESS", width=110)
        self.tree.column("USERNAME", width=110)
        self.tree.column("ENDPOINT", width=180, anchor="w")
        self.tree.column("TRIGGERED RULE", width=150)
        self.tree.column("RETRY AFTER (S)", width=110)

        # Zebra Tags
        self.tree.tag_configure('oddrow', background="#2b2b2b", foreground="white")
        self.tree.tag_configure('evenrow', background="#333333", foreground="white")

        scrolly = ttk.Scrollbar(table_container, orient="vertical", command=self.tree.yview)
        scrollx = ttk.Scrollbar(table_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrolly.set, xscrollcommand=scrollx.set)
        
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrolly.grid(row=0, column=1, sticky="ns")
        scrollx.grid(row=1, column=0, sticky="ew")

        self.tree.bind("<Double-1>", self.on_row_double_click)

    def _create_stat_card(self, parent, title, color, col):
        card = ctk.CTkFrame(parent, fg_color=ModernTheme.SECONDARY)
        card.grid(row=0, column=col, padx=8, sticky="nsew")
        ctk.CTkLabel(card, text=title, font=("Segoe UI", 10, "bold"), text_color=ModernTheme.TEXT_GRAY).pack(pady=(12, 0))
        value_lbl = ctk.CTkLabel(card, text="0", font=ModernTheme.H2, text_color=color)
        value_lbl.pack(pady=(0, 12))
        return value_lbl

    def refresh(self):
        self.next_cursor = None
        self.all_loaded = False
        self._load_data(append=False)

    def load_more(self):
        if not self.all_loaded and not self.is_loading:
            self._load_data(append=True)

    def _load_data(self, append=False):
        if self.is_loading:
            return
        self.is_loading = True

        self.refresh_btn.configure(state="disabled", text="LOADING...")
        if self.load_more_btn.winfo_exists():
            self.load_more_btn.configure(state="disabled", text="LOADING...")

        def worker():
            try:
                # 1. Fetch Stats
                stats = system.get_rate_limiting_stats()
                
                # 2. Fetch Paginated Blocks
                blocks_resp = system.get_rate_limiting_blocks(
                    limit=50,
                    cursor=self.next_cursor if append else None
                )
                blocks = blocks_resp.get("blocks", [])
                self.next_cursor = blocks_resp.get("next_cursor")
                if not self.next_cursor:
                    self.all_loaded = True

                def update_ui():
                    try:
                        self._update_stats_display(stats)
                        self._update_table_display(blocks, append=append)
                    except Exception as e:
                        print(f"UI Update error: {e}")

                self.container.after(0, update_ui)
            except Exception as e:
                self.container.after(0, lambda err=str(e): messagebox.showerror("Rate Limit Engine Error", err))
            finally:
                self.is_loading = False
                def reset_buttons():
                    try:
                        self.refresh_btn.configure(state="normal", text="🔄 REFRESH")
                        state = "disabled" if self.all_loaded else "normal"
                        lbl = "DONE" if self.all_loaded else "📥 LOAD MORE"
                        self.load_more_btn.configure(state=state, text=lbl)
                    except:
                        pass
                self.container.after(0, reset_buttons)

        threading.Thread(target=worker, daemon=True).start()

    def _update_stats_display(self, stats):
        if not self.total_blocks_lbl.winfo_exists():
            return
            
        self.total_blocks_lbl.configure(text=str(stats.get("total_blocks", 0)))
        self.today_blocks_lbl.configure(text=str(stats.get("blocks_today", 0)))
        
        top_ips = stats.get("top_blocked_ips", [])
        if top_ips:
            top_ip = f"{top_ips[0]['ip_address']} ({top_ips[0]['count']})"
        else:
            top_ip = "None"
        self.top_ip_lbl.configure(text=top_ip)
        
        top_users = stats.get("top_blocked_users", [])
        if top_users:
            top_user = f"{top_users[0]['username']} ({top_users[0]['count']})"
        else:
            top_user = "None"
        self.top_user_lbl.configure(text=top_user)

    def _update_table_display(self, blocks, append=False):
        if not self.tree.winfo_exists():
            return
            
        if not append:
            for row in self.tree.get_children():
                self.tree.delete(row)

        for i, b in enumerate(blocks):
            ts = b.get("timestamp", "").replace("T", " ").replace("Z", "")[:19]
            ip = b.get("ip_address") or "unknown"
            user = b.get("username") or ""
            endpoint = b.get("endpoint") or ""
            rule = b.get("limit_rule") or ""
            retry = b.get("retry_after") or 0
            
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            self.tree.insert("", "end", values=(b["id"], ts, ip, user, endpoint, rule, retry), tags=(tag,))

    def unblock_client_manual(self):
        identifier = self.unblock_entry.get().strip()
        if not identifier:
            messagebox.showwarning("Validation Error", "Please enter a client IP address or username.")
            return
        self._run_unblock(identifier)

    def unblock_client_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Selection Error", "Please select a record from the table to unblock.")
            return
            
        vals = self.tree.item(sel[0])["values"]
        ip = vals[2]
        user = vals[3]
        
        # Decide which identifier to unblock
        if ip and user:
            prompt = f"This record contains both IP '{ip}' and Username '{user}'. Which one would you like to unblock?"
            choice = messagebox.askyesnocancel("Unblock Choice", f"{prompt}\n\nClick 'Yes' to unblock both IP and Username.\nClick 'No' to unblock IP only.")
            if choice is True:
                # Unblock both
                self._run_unblock(ip, and_also=user)
            elif choice is False:
                # Unblock IP only
                self._run_unblock(ip)
        elif ip:
            self._run_unblock(ip)
        elif user:
            self._run_unblock(user)

    def on_row_double_click(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        self.unblock_client_selected()

    def _run_unblock(self, identifier, and_also=None):
        self.unblock_btn.configure(state="disabled", text="UNBLOCKING...")
        self.table_unblock_btn.configure(state="disabled")

        def task():
            try:
                res1 = system.reset_rate_limits(identifier)
                msg = f"Cleared rate limits for '{identifier}' (cleared {res1.get('cleared_keys_count', 0)} keys)."
                
                if and_also:
                    res2 = system.reset_rate_limits(and_also)
                    msg += f"\nAnd also cleared for '{and_also}' (cleared {res2.get('cleared_keys_count', 0)} keys)."

                def success_ui():
                    show_toast(self.container.winfo_toplevel(), "Client(s) successfully unblocked!", type="success")
                    self.unblock_entry.delete(0, tk.END)
                    self.refresh()

                self.container.after(0, success_ui)
            except Exception as e:
                self.container.after(0, lambda err=str(e): messagebox.showerror("Unblock Failed", err))
            finally:
                def reenable():
                    try:
                        self.unblock_btn.configure(state="normal", text="🔓 UNBLOCK CLIENT")
                        self.table_unblock_btn.configure(state="normal")
                    except:
                        pass
                self.container.after(0, reenable)

        threading.Thread(target=task, daemon=True).start()
