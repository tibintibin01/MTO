# -*- coding: utf-8 -*-
import customtkinter as ctk
from theme_manager import ModernTheme
import api_clients.system_service as system
from ui_components import show_toast
import threading
import time

class SystemHealthPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.is_monitoring = True
        self._monitor_thread = None
        self.setup_ui()
        self.start_monitoring()

    def setup_ui(self):
        self.container = ctk.CTkScrollableFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        header = ctk.CTkFrame(self.container, fg_color=ModernTheme.PRIMARY, corner_radius=15)
        header.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(header, text="🏛️ SYSTEM HEALTH & DIAGNOSTICS", font=ModernTheme.H1, text_color="white").pack(anchor="w", padx=30, pady=(25, 5))
        ctk.CTkLabel(header, text="Real-time monitoring of database connections, cache efficiency, and API latency.", font=ModernTheme.BODY, text_color="#f0f9ff").pack(anchor="w", padx=30, pady=(0, 25))
        
        self.refresh_btn = ctk.CTkButton(header, text="🔄 REFRESH DIAGNOSTICS", command=self.manual_refresh, fg_color="white", text_color=ModernTheme.PRIMARY, hover_color="#f0f9ff", width=200, height=35, font=ModernTheme.BODY_BOLD)
        self.refresh_btn.place(relx=0.95, rely=0.5, anchor="e")


        # Main Grid
        self.grid = ctk.CTkFrame(self.container, fg_color="transparent")
        self.grid.pack(fill="both", expand=True)
        self.grid.grid_columnconfigure((0, 1), weight=1)

        # 1. Database Pool Health
        self.pool_card = self._make_card(self.grid, 0, 0, "DATABASE CONNECTION POOL", "Monitor active and idle connections.")
        self.pool_stats = ctk.CTkLabel(self.pool_card, text="Loading...", font=("Consolas", 14), justify="left")
        self.pool_stats.pack(padx=20, pady=20, anchor="w")

        # 2. API Performance
        self.api_card = self._make_card(self.grid, 0, 1, "API PERFORMANCE (LATENCY)", "Average response time and error rates.")
        self.api_stats = ctk.CTkLabel(self.api_card, text="Loading...", font=("Consolas", 14), justify="left")
        self.api_stats.pack(padx=20, pady=20, anchor="w")

        # 3. Cache & Memory
        self.cache_card = self._make_card(self.grid, 1, 0, "SYSTEM CACHE (REDIS/LOCAL)", "Hit rates and memory usage.")
        self.cache_stats = ctk.CTkLabel(self.cache_card, text="Loading...", font=("Consolas", 14), justify="left")
        self.cache_stats.pack(padx=20, pady=20, anchor="w")

        # 4. Security & Audit
        self.sec_card = self._make_card(self.grid, 1, 1, "SECURITY & INTEGRITY", "Audit log health and session stats.")
        self.sec_stats = ctk.CTkLabel(self.sec_card, text="Loading...", font=("Consolas", 14), justify="left")
        self.sec_stats.pack(padx=20, pady=20, anchor="w")

    def _make_card(self, parent, row, col, title, subtitle):
        card = ctk.CTkFrame(parent, border_width=1, border_color=ModernTheme.BORDER_DARK)
        card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
        
        ctk.CTkLabel(card, text=title, font=ModernTheme.BODY_BOLD, text_color=ModernTheme.PRIMARY).pack(pady=(15, 2), padx=20, anchor="w")
        ctk.CTkLabel(card, text=subtitle, font=("Segoe UI", 10), text_color="gray").pack(padx=20, anchor="w")
        
        return card

    def manual_refresh(self):
        self.refresh_btn.configure(state="disabled", text="SCANNING...")
        def run():
            try:
                stats = system.get_system_stats()
                self.parent.after(0, lambda s=stats: self.update_stats(s))
            except Exception as e:
                self.parent.after(0, lambda err=str(e): self.show_error(err))
            finally:
                self.parent.after(0, lambda: self.refresh_btn.configure(state="normal", text="🔄 REFRESH DIAGNOSTICS"))
        
        threading.Thread(target=run, daemon=True).start()

    def start_monitoring(self):
        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        def monitor_loop():
            while self.is_monitoring:
                try:
                    stats = system.get_system_stats()
                    self.parent.after(0, lambda s=stats: self.update_stats(s))
                except Exception as e:
                    self.parent.after(0, lambda err=str(e): self.show_error(err))
                time.sleep(15)


        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()

    def update_stats(self, stats):
        if not self.pool_stats.winfo_exists(): return
        if not stats:
            self.show_error("System stats unavailable. Please check the backend server.")
            return
        
        # Reset colors
        self.pool_stats.configure(text_color=("gray10", "gray90"))
        self.api_stats.configure(text_color=("gray10", "gray90"))
        self.cache_stats.configure(text_color=("gray10", "gray90"))
        self.sec_stats.configure(text_color=("gray10", "gray90"))
        
        p = stats.get("pool", {})

        self.pool_stats.configure(text=(
            f"Active:    {p.get('active', 0)}\n"
            f"Idle:      {p.get('idle', 0)}\n"
            f"Overflow:  {p.get('overflow', 0)}\n"
            f"Size:      {p.get('size', 0)}\n"
            f"Status:    {'🟢 HEALTHY' if p.get('overflow', 0) == 0 else '🟠 STRESSED'}"
        ))

        a = stats.get("api", {})
        self.api_stats.configure(text=(
            f"Avg Latency: {a.get('avg_latency', 0):.2f}ms\n"
            f"Error Rate:  {a.get('error_rate', 0):.1f}%\n"
            f"Requests/m:  {a.get('rpm', 0)}\n"
            f"Uptime:      {stats.get('uptime', 'N/A')}"
        ))

        c = stats.get("cache", {})
        namespaces_val = c.get('namespaces', 0)
        # namespaces may be an int (count) or a list — handle both
        namespace_count = namespaces_val if isinstance(namespaces_val, int) else len(namespaces_val)
        hit_rate = c.get('hit_rate', 0)
        hit_rate_str = "N/A" if hit_rate == -1 else (f"{hit_rate:.1f}%" if isinstance(hit_rate, (int, float)) else str(hit_rate))
        self.cache_stats.configure(text=(
            f"Items:      {c.get('items', 0)}\n"
            f"Hit Rate:   {hit_rate_str}\n"
            f"Provider:   {c.get('provider', 'Local')}\n"
            f"Namespaces: {namespace_count}"
        ))

        s = stats.get("security", {})
        self.sec_stats.configure(text=(
            f"Audit Logs: {s.get('total_logs', 0)}\n"
            f"Integrity:  {'✅ VERIFIED' if s.get('integrity_ok') else '❌ COMPROMISED'}\n"
            f"Active Ses: {s.get('active_sessions', 0)}\n"
            f"Lockouts:   {s.get('active_lockouts', 0)}"
        ))

    def show_error(self, message):
        if not self.pool_stats.winfo_exists(): return
        err_text = f"⚠️ ERROR: {message[:50]}..." if len(message) > 50 else f"⚠️ {message}"
        self.pool_stats.configure(text=err_text, text_color="#e74c3c")
        self.api_stats.configure(text="Connection lost...", text_color="#e74c3c")
        self.cache_stats.configure(text="Check server status", text_color="#e74c3c")
        self.sec_stats.configure(text="Access Denied?", text_color="#e74c3c")

    def stop_monitoring(self):

        self.is_monitoring = False
