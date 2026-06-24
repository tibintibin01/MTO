# -*- coding: utf-8 -*-
import customtkinter as ctk
from theme_manager import ModernTheme
import api_clients.system_service as system
import threading
import time


class SystemHealthPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.is_monitoring = True
        self._monitor_thread = None
        self.metric_labels = {}
        self.badges = {}
        self.bars = {}
        self.setup_ui()
        self.start_monitoring()

    def setup_ui(self):
        self.container = ctk.CTkScrollableFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=18, pady=18)

        header = ctk.CTkFrame(
            self.container,
            fg_color="#0f172a",
            corner_radius=14,
            border_width=1,
            border_color="#1e3a5f",
        )
        header.pack(fill="x", pady=(0, 18))
        header.grid_columnconfigure(0, weight=1)

        title_area = ctk.CTkFrame(header, fg_color="transparent")
        title_area.grid(row=0, column=0, sticky="ew", padx=26, pady=22)
        title_area.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            title_area,
            text="SYSTEM HEALTH & DIAGNOSTICS",
            font=("Segoe UI", 27, "bold"),
            text_color="#f8fafc",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            title_area,
            text="Live view of server capacity, API reliability, cache state, and audit integrity.",
            font=("Segoe UI", 12),
            text_color="#9fb6d8",
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(5, 0))

        self.overall_status = ctk.CTkLabel(
            header,
            text="CHECKING",
            font=("Segoe UI", 11, "bold"),
            text_color="#f59e0b",
            fg_color="#2b1f08",
            corner_radius=999,
            padx=14,
            pady=7,
        )
        self.overall_status.grid(row=0, column=1, padx=(0, 10), pady=22, sticky="e")

        self.refresh_btn = ctk.CTkButton(
            header,
            text="REFRESH",
            command=self.manual_refresh,
            fg_color="#38bdf8",
            hover_color="#0ea5e9",
            text_color="#06121f",
            width=130,
            height=38,
            corner_radius=9,
            font=("Segoe UI", 12, "bold"),
        )
        self.refresh_btn.grid(row=0, column=2, padx=(0, 26), pady=22, sticky="e")

        self.grid = ctk.CTkFrame(self.container, fg_color="transparent")
        self.grid.pack(fill="both", expand=True)
        self.grid.grid_columnconfigure((0, 1), weight=1, uniform="health_cols")

        self._make_card(
            key="pool",
            row=0,
            col=0,
            title="Database Connection Pool",
            subtitle="Capacity and connection pressure",
            accent="#38bdf8",
            metrics=("Active", "Idle", "Pool Size", "Overflow"),
            has_bar=True,
        )
        self._make_card(
            key="api",
            row=0,
            col=1,
            title="API Performance",
            subtitle="Latency, traffic, and error behavior",
            accent="#22c55e",
            metrics=("Average Latency", "Server Errors", "Request Issues", "Requests / min"),
            has_bar=True,
        )
        self._make_card(
            key="cache",
            row=1,
            col=0,
            title="System Cache",
            subtitle="Redis/local cache provider and hit rate",
            accent="#a78bfa",
            metrics=("Provider", "Items", "Hit Rate", "Namespaces"),
            has_bar=False,
        )
        self._make_card(
            key="security",
            row=1,
            col=1,
            title="Security & Integrity",
            subtitle="Audit log and active access posture",
            accent="#f59e0b",
            metrics=("Integrity", "Audit Logs", "Active Sessions", "Lockouts"),
            has_bar=False,
        )

        self.last_refresh_lbl = ctk.CTkLabel(
            self.container,
            text="Waiting for live diagnostics...",
            font=("Segoe UI", 10),
            text_color="#64748b",
            anchor="e",
        )
        self.last_refresh_lbl.pack(fill="x", pady=(4, 0))

    def _make_card(self, key, row, col, title, subtitle, accent, metrics, has_bar=False):
        card = ctk.CTkFrame(
            self.grid,
            fg_color="#111827",
            border_width=1,
            border_color="#26364f",
            corner_radius=12,
        )
        card.grid(row=row, column=col, padx=9, pady=9, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 7))
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            top,
            text=title,
            font=("Segoe UI", 15, "bold"),
            text_color="#f8fafc",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        self.badges[key] = ctk.CTkLabel(
            top,
            text="CHECKING",
            font=("Segoe UI", 10, "bold"),
            text_color=accent,
            fg_color="#0b1220",
            corner_radius=999,
            padx=10,
            pady=5,
        )
        self.badges[key].grid(row=0, column=1, padx=(10, 0), sticky="e")
        ctk.CTkLabel(
            card,
            text=subtitle,
            font=("Segoe UI", 10),
            text_color="#8da2bf",
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))

        ctk.CTkFrame(card, height=1, fg_color="#1f2d44").grid(row=2, column=0, sticky="ew")

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=3, column=0, sticky="ew", padx=18, pady=14)
        body.grid_columnconfigure((0, 1), weight=1)

        self.metric_labels[key] = {}
        for index, label in enumerate(metrics):
            r = index // 2
            c = index % 2
            metric = ctk.CTkFrame(body, fg_color="#0b1220", corner_radius=9, border_width=1, border_color="#1f2d44")
            metric.grid(row=r, column=c, padx=(0 if c == 0 else 7, 7 if c == 0 else 0), pady=6, sticky="nsew")
            ctk.CTkLabel(metric, text=label.upper(), font=("Segoe UI", 9, "bold"), text_color="#7f95b5", anchor="w").pack(fill="x", padx=12, pady=(9, 1))
            value = ctk.CTkLabel(metric, text="--", font=("Segoe UI", 17, "bold"), text_color="#f8fafc", anchor="w")
            value.pack(fill="x", padx=12, pady=(0, 10))
            self.metric_labels[key][label] = value

        if has_bar:
            bar = ctk.CTkProgressBar(card, height=8, progress_color=accent, fg_color="#0b1220")
            bar.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 17))
            bar.set(0)
            self.bars[key] = bar

    def _set_badge(self, key, text, color, background="#102033"):
        badge = self.badges.get(key)
        if badge and badge.winfo_exists():
            badge.configure(text=text, text_color=color, fg_color=background)

    def _set_metric(self, card_key, metric_key, value, color="#f8fafc"):
        label = self.metric_labels.get(card_key, {}).get(metric_key)
        if label and label.winfo_exists():
            label.configure(text=str(value), text_color=color)

    def manual_refresh(self):
        self.refresh_btn.configure(state="disabled", text="SCANNING...")

        def run():
            try:
                stats = system.get_system_stats()
                self.parent.after(0, lambda s=stats: self.update_stats(s))
            except Exception as e:
                self.parent.after(0, lambda err=str(e): self.show_error(err))
            finally:
                self.parent.after(0, lambda: self.refresh_btn.configure(state="normal", text="REFRESH"))

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
        if not self.metric_labels.get("pool"):
            return
        if not stats:
            self.show_error("System stats unavailable. Please check the backend server.")
            return

        p = stats.get("pool", {})
        active = int(p.get("active", 0) or 0)
        idle = int(p.get("idle", 0) or 0)
        overflow = int(p.get("overflow", 0) or 0)
        size = max(1, int(p.get("size", 0) or 1))
        pool_usage = min(1, active / size)
        pool_ok = overflow == 0 and pool_usage < 0.85
        self._set_badge("pool", "HEALTHY" if pool_ok else "STRESSED", "#22c55e" if pool_ok else "#f59e0b")
        self._set_metric("pool", "Active", active, "#f8fafc")
        self._set_metric("pool", "Idle", idle, "#bfdbfe")
        self._set_metric("pool", "Pool Size", size, "#f8fafc")
        self._set_metric("pool", "Overflow", overflow, "#22c55e" if overflow == 0 else "#f59e0b")
        self.bars["pool"].set(pool_usage)

        a = stats.get("api", {})
        latency = float(a.get("avg_latency", 0) or 0)
        legacy_error_rate = float(a.get("error_rate", 0) or 0)
        client_error_rate = float(a.get("client_error_rate", 0) or 0)
        server_error_rate = float(a.get("server_error_rate", legacy_error_rate) or 0)
        rpm = a.get("rpm", 0)
        api_ok = latency < 500 and server_error_rate < 1
        api_warn = latency >= 500 or server_error_rate >= 1
        self._set_badge("api", "STABLE" if api_ok else "SERVER REVIEW", "#22c55e" if api_ok else "#ef4444")
        self._set_metric("api", "Average Latency", f"{latency:.1f} ms", "#22c55e" if latency < 250 else "#f59e0b")
        self._set_metric("api", "Server Errors", f"{server_error_rate:.1f}%", "#22c55e" if server_error_rate < 1 else "#ef4444")
        self._set_metric("api", "Request Issues", f"{client_error_rate:.1f}%", "#f59e0b" if client_error_rate >= 5 else "#bfdbfe")
        self._set_metric("api", "Requests / min", rpm, "#f8fafc")
        self.bars["api"].set(min(1, server_error_rate / 10))

        c = stats.get("cache", {})
        namespaces_val = c.get("namespaces", 0)
        namespace_count = namespaces_val if isinstance(namespaces_val, int) else len(namespaces_val)
        hit_rate = c.get("hit_rate", 0)
        hit_rate_str = "N/A" if hit_rate == -1 else (f"{hit_rate:.1f}%" if isinstance(hit_rate, (int, float)) else str(hit_rate))
        provider = str(c.get("provider", "Local") or "Local")
        cache_is_local = "LOCAL" in provider.upper() or "MEMORY" in provider.upper()
        self._set_badge("cache", "LOCAL" if cache_is_local else "REDIS", "#a78bfa")
        self._set_metric("cache", "Provider", provider, "#c4b5fd")
        self._set_metric("cache", "Items", c.get("items", 0), "#f8fafc")
        self._set_metric("cache", "Hit Rate", hit_rate_str, "#f8fafc" if hit_rate == -1 else "#22c55e")
        self._set_metric("cache", "Namespaces", namespace_count, "#bfdbfe")

        s = stats.get("security", {})
        integrity_ok = bool(s.get("integrity_ok"))
        lockouts = int(s.get("active_lockouts", 0) or 0)
        self._set_badge("security", "VERIFIED" if integrity_ok else "REVIEW", "#22c55e" if integrity_ok else "#ef4444")
        self._set_metric("security", "Integrity", "Verified" if integrity_ok else "Needs review", "#22c55e" if integrity_ok else "#ef4444")
        self._set_metric("security", "Audit Logs", f"{int(s.get('total_logs', 0) or 0):,}", "#f8fafc")
        self._set_metric("security", "Active Sessions", int(s.get("active_sessions", 0) or 0), "#bfdbfe")
        self._set_metric("security", "Lockouts", lockouts, "#22c55e" if lockouts == 0 else "#f59e0b")

        all_ok = pool_ok and api_ok and integrity_ok
        self.overall_status.configure(
            text="SYSTEM HEALTHY" if all_ok else "NEEDS REVIEW",
            text_color="#22c55e" if all_ok else "#f59e0b",
            fg_color="#052e1a" if all_ok else "#2b1f08",
        )
        self.last_refresh_lbl.configure(text=f"Last refreshed: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    def show_error(self, message):
        if not self.metric_labels.get("pool"):
            return
        self.overall_status.configure(text="OFFLINE", text_color="#ef4444", fg_color="#3f1111")
        for key in ("pool", "api", "cache", "security"):
            self._set_badge(key, "UNAVAILABLE", "#ef4444", "#3f1111")
        self._set_metric("pool", "Active", "--", "#ef4444")
        self._set_metric("pool", "Idle", "--", "#ef4444")
        self._set_metric("pool", "Pool Size", "--", "#ef4444")
        self._set_metric("pool", "Overflow", "--", "#ef4444")
        self._set_metric("api", "Average Latency", "No response", "#ef4444")
        self._set_metric("api", "Server Errors", "--", "#ef4444")
        self._set_metric("api", "Request Issues", "--", "#ef4444")
        self._set_metric("api", "Requests / min", "--", "#ef4444")
        self._set_metric("cache", "Provider", "Unavailable", "#ef4444")
        self._set_metric("security", "Integrity", "Unknown", "#ef4444")
        self.last_refresh_lbl.configure(text=f"Diagnostics failed: {message[:120]}")

    def stop_monitoring(self):
        self.is_monitoring = False
