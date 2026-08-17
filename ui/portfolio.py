# -*- coding: utf-8 -*-
"""Organizational Property Portfolios desktop page.

A portfolio is only a folder of links to existing properties. This page never
edits property records, posts payments, or performs financial calculations.
"""

import os
import threading
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import customtkinter as ctk

import api_clients.auth_service as auth
import api_clients.billing_service as billing
import api_clients.portfolio_service as portfolio_api
import api_clients.property_service as property_api
from ui_components import ErrorDialog, LoadingOverlay, show_toast
from utils import format_curr


COLORS = {
    "panel": "#111827",
    "panel_alt": "#0f172a",
    "border": "#334155",
    "muted": "#94a3b8",
    "text": "#f8fafc",
    "blue": "#0284c7",
    "blue_hover": "#0369a1",
    "green": "#059669",
    "green_hover": "#047857",
    "amber": "#d97706",
    "amber_hover": "#b45309",
    "red": "#dc2626",
    "red_hover": "#b91c1c",
    "slate": "#475569",
    "slate_hover": "#64748b",
}


def _property_candidate(row):
    """Normalize the existing tuple-based property search response."""
    if isinstance(row, dict):
        return {
            "property_id": row.get("id") or row.get("property_id"),
            "td_number": row.get("td_number"),
            "owner_name": row.get("owner_name"),
            "barangay": row.get("barangay") or row.get("location"),
            "kind_of_property": row.get("kind_of_property"),
            "previous_td": row.get("previous_td"),
        }
    values = list(row or [])
    value = lambda index, default=None: values[index] if len(values) > index else default
    return {
        "property_id": value(0),
        "td_number": value(1),
        "owner_name": value(2),
        "barangay": value(22) or value(6),
        "kind_of_property": value(7),
        "previous_td": value(20),
    }


class PropertyLinkDialog(ctk.CTkToplevel):
    """Search and select one existing property to link."""

    def __init__(self, master, on_link):
        super().__init__(master)
        self.on_link = on_link
        self.rows = {}
        self.title("Link Existing Property")
        self.geometry("1050x590")
        self.minsize(850, 500)
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)

        ctk.CTkLabel(
            self,
            text="LINK EXISTING PROPERTY",
            font=("Inter", 20, "bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w", padx=24, pady=(22, 2))
        ctk.CTkLabel(
            self,
            text=(
                "Search by TD number, previous TD, or owner. Linking only adds "
                "the property to this folder."
            ),
            font=("Inter", 11),
            text_color=COLORS["muted"],
        ).pack(anchor="w", padx=24, pady=(0, 16))

        search_bar = ctk.CTkFrame(
            self,
            fg_color=COLORS["panel"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
        )
        search_bar.pack(fill="x", padx=24, pady=(0, 12))
        self.search_entry = ctk.CTkEntry(
            search_bar,
            placeholder_text="TD number, previous TD, or owner name...",
            height=36,
            fg_color=COLORS["panel_alt"],
            border_color=COLORS["border"],
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=12, pady=12)
        self.search_entry.bind("<Return>", lambda _event: self.search())
        ctk.CTkButton(
            search_bar,
            text="SEARCH",
            command=self.search,
            width=110,
            height=36,
            fg_color=COLORS["blue"],
            hover_color=COLORS["blue_hover"],
            font=("Inter", 10, "bold"),
        ).pack(side="right", padx=(0, 12), pady=12)

        table_frame = ctk.CTkFrame(
            self,
            fg_color=COLORS["panel_alt"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
        )
        table_frame.pack(fill="both", expand=True, padx=24)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "PortfolioSearch.Treeview",
            rowheight=34,
            font=("Inter", 10),
            background=COLORS["panel_alt"],
            fieldbackground=COLORS["panel_alt"],
            foreground="#e2e8f0",
            borderwidth=0,
        )
        style.configure(
            "PortfolioSearch.Treeview.Heading",
            font=("Inter", 10, "bold"),
            background="#334155",
            foreground="#f8fafc",
            borderwidth=0,
        )
        style.map(
            "PortfolioSearch.Treeview",
            background=[("selected", COLORS["blue"])],
            foreground=[("selected", "#ffffff")],
        )

        columns = ("id", "td", "owner", "barangay", "kind", "previous")
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            style="PortfolioSearch.Treeview",
        )
        headings = {
            "id": "ID",
            "td": "TD NUMBER",
            "owner": "OWNER NAME",
            "barangay": "BARANGAY",
            "kind": "PROPERTY TYPE",
            "previous": "PREVIOUS TD",
        }
        for column, heading in headings.items():
            self.tree.heading(column, text=heading)
            self.tree.column(column, anchor="w")
        self.tree.column("id", width=0, stretch=tk.NO)
        self.tree.column("td", width=145)
        self.tree.column("owner", width=290)
        self.tree.column("barangay", width=150)
        self.tree.column("kind", width=190)
        self.tree.column("previous", width=140)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.tree.bind("<Double-1>", lambda _event: self.link_selected())

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=24, pady=18)
        self.status_label = ctk.CTkLabel(
            footer,
            text="Enter a search term to find a property.",
            font=("Inter", 10),
            text_color=COLORS["muted"],
        )
        self.status_label.pack(side="left")
        ctk.CTkButton(
            footer,
            text="CANCEL",
            command=self.destroy,
            width=110,
            fg_color=COLORS["slate"],
            hover_color=COLORS["slate_hover"],
        ).pack(side="right", padx=(8, 0))
        self.link_button = ctk.CTkButton(
            footer,
            text="LINK SELECTED",
            command=self.link_selected,
            width=150,
            state="disabled",
            fg_color=COLORS["green"],
            hover_color=COLORS["green_hover"],
        )
        self.link_button.pack(side="right")

        self.after(100, self.search_entry.focus_set)

    def _schedule(self, callback):
        try:
            if self.winfo_exists():
                self.after(0, callback)
        except (tk.TclError, RuntimeError):
            pass

    def search(self):
        term = self.search_entry.get().strip()
        if not term:
            ErrorDialog(self, "Search Required", "Enter a TD number, previous TD, or owner name.")
            return
        overlay = LoadingOverlay(self, "Searching existing properties...")

        def worker():
            try:
                response = property_api.search_properties(term, limit=100)
                items = response.get("items", []) if isinstance(response, dict) else response
                self._schedule(lambda: self._finish_search(overlay, items or [], None))
            except Exception as exc:
                self._schedule(lambda error=exc: self._finish_search(overlay, [], error))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_search(self, overlay, rows, error):
        try:
            overlay.hide()
        except (tk.TclError, RuntimeError):
            pass
        if error:
            ErrorDialog(self, "Property Search", str(error))
            return

        self.rows = {}
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, raw in enumerate(rows):
            row = _property_candidate(raw)
            if not row.get("property_id"):
                continue
            iid = f"candidate-{row['property_id']}-{index}"
            self.rows[iid] = row
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    row.get("property_id"),
                    row.get("td_number") or "-",
                    row.get("owner_name") or "UNKNOWN",
                    row.get("barangay") or "-",
                    row.get("kind_of_property") or "-",
                    row.get("previous_td") or "-",
                ),
            )
        count = len(self.rows)
        self.status_label.configure(
            text=f"{count} matching propert{'y' if count == 1 else 'ies'} found."
        )
        self.link_button.configure(state="disabled")

    def _selection_changed(self, _event=None):
        self.link_button.configure(
            state="normal" if self.tree.selection() else "disabled"
        )

    def link_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        row = self.rows.get(selection[0])
        if row:
            self.on_link(int(row["property_id"]), self)


class PortfolioPage:
    """View and manage organizational folders of existing properties."""

    def __init__(self, parent, user=None, callbacks=None):
        self.parent = parent
        self.user = user or {}
        self.callbacks = callbacks or {}
        self.can_edit = auth.has_permission(self.user, "property_edit")
        self.selected_portfolio = None
        self.linked_properties = {}

        self.container = ctk.CTkFrame(parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)
        self._setup_ui()
        self.refresh_portfolios()

    def _setup_ui(self):
        header = ctk.CTkFrame(self.container, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        title_group = ctk.CTkFrame(header, fg_color="transparent")
        title_group.pack(side="left")
        ctk.CTkLabel(
            title_group,
            text="PROPERTY PORTFOLIOS",
            font=("Inter", 25, "bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_group,
            text="Organize related properties without changing their official records.",
            font=("Inter", 11),
            text_color=COLORS["muted"],
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkButton(
            header,
            text="REFRESH",
            command=self.refresh_portfolios,
            width=110,
            height=36,
            fg_color=COLORS["blue"],
            hover_color=COLORS["blue_hover"],
            font=("Inter", 10, "bold"),
        ).pack(side="right")

        notice = ctk.CTkFrame(
            self.container,
            fg_color="#172554",
            border_width=1,
            border_color="#1d4ed8",
            corner_radius=8,
        )
        notice.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            notice,
            text=(
                "ORGANIZATIONAL ONLY: Linking or unlinking never changes ownership, "
                "assessment, billing, payment history, or compliance status."
            ),
            font=("Inter", 10, "bold"),
            text_color="#bfdbfe",
            anchor="w",
        ).pack(fill="x", padx=14, pady=10)

        body = ctk.CTkFrame(self.container, fg_color="transparent")
        body.pack(fill="both", expand=True)

        left = ctk.CTkFrame(
            body,
            width=340,
            fg_color=COLORS["panel"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
        )
        left.pack(side="left", fill="y", padx=(0, 12))
        left.pack_propagate(False)

        ctk.CTkLabel(
            left,
            text="PORTFOLIO FOLDERS",
            font=("Inter", 12, "bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w", padx=14, pady=(14, 8))
        self.search_entry = ctk.CTkEntry(
            left,
            placeholder_text="Search portfolio name...",
            height=34,
            fg_color=COLORS["panel_alt"],
            border_color=COLORS["border"],
        )
        self.search_entry.pack(fill="x", padx=14)
        self.search_entry.bind("<Return>", lambda _event: self.refresh_portfolios())

        options = ctk.CTkFrame(left, fg_color="transparent")
        options.pack(fill="x", padx=14, pady=8)
        self.include_inactive = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            options,
            text="Show inactive",
            variable=self.include_inactive,
            command=self.refresh_portfolios,
            font=("Inter", 10),
            checkbox_width=18,
            checkbox_height=18,
        ).pack(side="left")
        ctk.CTkButton(
            options,
            text="SEARCH",
            command=self.refresh_portfolios,
            width=82,
            height=28,
            fg_color=COLORS["blue"],
            hover_color=COLORS["blue_hover"],
            font=("Inter", 9, "bold"),
        ).pack(side="right")

        portfolio_table = ctk.CTkFrame(left, fg_color=COLORS["panel_alt"])
        portfolio_table.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self._configure_tree_style("Portfolio.Treeview")
        self.portfolio_tree = ttk.Treeview(
            portfolio_table,
            columns=("id", "name", "count", "status"),
            show="headings",
            style="Portfolio.Treeview",
        )
        for column, heading in (
            ("id", "ID"),
            ("name", "NAME"),
            ("count", "PROPERTIES"),
            ("status", "STATUS"),
        ):
            self.portfolio_tree.heading(column, text=heading)
        self.portfolio_tree.column("id", width=0, stretch=tk.NO)
        self.portfolio_tree.column("name", width=155, anchor="w")
        self.portfolio_tree.column("count", width=76, anchor="center")
        self.portfolio_tree.column("status", width=70, anchor="center")
        portfolio_scroll = ttk.Scrollbar(
            portfolio_table, orient="vertical", command=self.portfolio_tree.yview
        )
        self.portfolio_tree.configure(yscrollcommand=portfolio_scroll.set)
        portfolio_scroll.pack(side="right", fill="y")
        self.portfolio_tree.pack(side="left", fill="both", expand=True)
        self.portfolio_tree.bind("<<TreeviewSelect>>", self._portfolio_selected)

        manage = ctk.CTkFrame(left, fg_color="transparent")
        manage.pack(fill="x", padx=14, pady=(0, 14))
        self.create_button = ctk.CTkButton(
            manage,
            text="CREATE",
            command=self.create_portfolio,
            width=92,
            height=32,
            fg_color=COLORS["green"],
            hover_color=COLORS["green_hover"],
            state="normal" if self.can_edit else "disabled",
        )
        self.create_button.pack(side="left")
        self.rename_button = ctk.CTkButton(
            manage,
            text="RENAME",
            command=self.rename_portfolio,
            width=92,
            height=32,
            fg_color=COLORS["slate"],
            hover_color=COLORS["slate_hover"],
            state="disabled",
        )
        self.rename_button.pack(side="left", padx=6)
        self.toggle_button = ctk.CTkButton(
            manage,
            text="DEACTIVATE",
            command=self.toggle_portfolio,
            width=105,
            height=32,
            fg_color=COLORS["amber"],
            hover_color=COLORS["amber_hover"],
            state="disabled",
        )
        self.toggle_button.pack(side="left")

        right = ctk.CTkFrame(
            body,
            fg_color=COLORS["panel"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
        )
        right.pack(side="left", fill="both", expand=True)

        detail_header = ctk.CTkFrame(right, fg_color="transparent")
        detail_header.pack(fill="x", padx=16, pady=(14, 10))
        detail_text = ctk.CTkFrame(detail_header, fg_color="transparent")
        detail_text.pack(side="left")
        self.portfolio_name_label = ctk.CTkLabel(
            detail_text,
            text="SELECT A PORTFOLIO",
            font=("Inter", 16, "bold"),
            text_color=COLORS["text"],
        )
        self.portfolio_name_label.pack(anchor="w")
        self.portfolio_status_label = ctk.CTkLabel(
            detail_text,
            text="Choose a folder to view its linked properties.",
            font=("Inter", 10),
            text_color=COLORS["muted"],
        )
        self.portfolio_status_label.pack(anchor="w", pady=(2, 0))
        self.link_button = ctk.CTkButton(
            detail_header,
            text="LINK PROPERTY",
            command=self.open_link_dialog,
            width=135,
            height=34,
            fg_color=COLORS["green"],
            hover_color=COLORS["green_hover"],
            state="disabled",
        )
        self.link_button.pack(side="right")

        property_table = ctk.CTkFrame(right, fg_color=COLORS["panel_alt"])
        property_table.pack(fill="both", expand=True, padx=16)
        self._configure_tree_style("PortfolioProperty.Treeview")
        columns = (
            "id",
            "td",
            "owner",
            "barangay",
            "kind",
            "lot_block",
            "assessed",
            "status",
        )
        self.property_tree = ttk.Treeview(
            property_table,
            columns=columns,
            show="headings",
            style="PortfolioProperty.Treeview",
        )
        headings = {
            "id": "ID",
            "td": "TD NUMBER",
            "owner": "OWNER NAME",
            "barangay": "BARANGAY",
            "kind": "PROPERTY TYPE",
            "lot_block": "LOT / BLOCK",
            "assessed": "ASSESSED VALUE",
            "status": "RECORD STATUS",
        }
        for column, heading in headings.items():
            self.property_tree.heading(column, text=heading)
            self.property_tree.column(column, anchor="w")
        self.property_tree.column("id", width=0, stretch=tk.NO)
        self.property_tree.column("td", width=135)
        self.property_tree.column("owner", width=250)
        self.property_tree.column("barangay", width=130)
        self.property_tree.column("kind", width=170)
        self.property_tree.column("lot_block", width=115)
        self.property_tree.column("assessed", width=125, anchor="e")
        self.property_tree.column("status", width=115, anchor="center")
        property_scroll = ttk.Scrollbar(
            property_table, orient="vertical", command=self.property_tree.yview
        )
        self.property_tree.configure(yscrollcommand=property_scroll.set)
        property_scroll.pack(side="right", fill="y")
        self.property_tree.pack(side="left", fill="both", expand=True)
        self.property_tree.bind("<<TreeviewSelect>>", self._property_selected)
        self.property_tree.bind("<Double-1>", lambda _event: self.open_property_record())

        organization_actions = ctk.CTkFrame(right, fg_color="transparent")
        organization_actions.pack(fill="x", padx=16, pady=(10, 6))
        self.unlink_button = self._action_button(
            organization_actions,
            "UNLINK",
            self.unlink_property,
            COLORS["red"],
            COLORS["red_hover"],
            side="left",
        )
        ctk.CTkLabel(
            organization_actions,
            text="Unlink removes only the folder association.",
            font=("Inter", 9),
            text_color=COLORS["muted"],
        ).pack(side="left", padx=10)

        workflow_actions = ctk.CTkFrame(right, fg_color="transparent")
        workflow_actions.pack(fill="x", padx=16, pady=(0, 14))
        self.property_button = self._action_button(
            workflow_actions, "PROPERTY RECORD", self.open_property_record,
            COLORS["blue"], COLORS["blue_hover"]
        )
        self.ledger_button = self._action_button(
            workflow_actions, "LEDGER", self.open_ledger,
            COLORS["blue"], COLORS["blue_hover"]
        )
        self.tax_bill_button = self._action_button(
            workflow_actions, "TAX BILL", self.download_tax_bill,
            COLORS["green"], COLORS["green_hover"]
        )
        self.soa_button = self._action_button(
            workflow_actions, "SOA", self.download_soa,
            COLORS["green"], COLORS["green_hover"]
        )
        self.delinquency_button = self._action_button(
            workflow_actions, "DELINQUENCY", self.open_delinquency,
            COLORS["amber"], COLORS["amber_hover"]
        )

    @staticmethod
    def _configure_tree_style(style_name):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            style_name,
            rowheight=34,
            font=("Inter", 10),
            background=COLORS["panel_alt"],
            fieldbackground=COLORS["panel_alt"],
            foreground="#e2e8f0",
            borderwidth=0,
        )
        style.configure(
            f"{style_name}.Heading",
            font=("Inter", 9, "bold"),
            background="#334155",
            foreground="#f8fafc",
            borderwidth=0,
        )
        style.map(
            style_name,
            background=[("selected", COLORS["blue"])],
            foreground=[("selected", "#ffffff")],
        )

    @staticmethod
    def _action_button(parent, text, command, color, hover, side="left"):
        button = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=120,
            height=32,
            fg_color=color,
            hover_color=hover,
            state="disabled",
            font=("Inter", 9, "bold"),
        )
        button.pack(side=side, padx=(0, 6))
        return button

    def _schedule(self, callback):
        try:
            if self.container.winfo_exists():
                self.container.after(0, callback)
        except (tk.TclError, RuntimeError):
            pass

    def _run_async(self, message, work, on_success, error_title="Property Portfolios"):
        overlay = LoadingOverlay(self.container, message)

        def worker():
            try:
                result = work()
                self._schedule(
                    lambda: self._finish_async(overlay, result, None, on_success, error_title)
                )
            except Exception as exc:
                self._schedule(
                    lambda error=exc: self._finish_async(
                        overlay, None, error, on_success, error_title
                    )
                )

        threading.Thread(target=worker, daemon=True).start()

    def _finish_async(self, overlay, result, error, on_success, error_title):
        try:
            overlay.hide()
        except (tk.TclError, RuntimeError):
            pass
        if error:
            ErrorDialog(self.parent.winfo_toplevel(), error_title, str(error))
            return
        on_success(result)

    def refresh_portfolios(self, select_id=None):
        if select_id is None and self.selected_portfolio:
            select_id = self.selected_portfolio.get("id")
        term = self.search_entry.get().strip()
        include_inactive = self.include_inactive.get()
        self._run_async(
            "Loading property portfolios...",
            lambda: portfolio_api.list_portfolios(term, include_inactive),
            lambda response: self._populate_portfolios(response, select_id),
        )

    def _populate_portfolios(self, response, select_id=None):
        items = response.get("items", []) if isinstance(response, dict) else response or []
        for item in self.portfolio_tree.get_children():
            self.portfolio_tree.delete(item)
        selected_iid = None
        for portfolio in items:
            iid = f"portfolio-{portfolio['id']}"
            self.portfolio_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    portfolio["id"],
                    portfolio.get("name") or "Unnamed",
                    portfolio.get("property_count", 0),
                    "ACTIVE" if portfolio.get("is_active") else "INACTIVE",
                ),
            )
            if select_id is not None and int(portfolio["id"]) == int(select_id):
                selected_iid = iid
        if selected_iid:
            self.portfolio_tree.selection_set(selected_iid)
            self.portfolio_tree.focus(selected_iid)
            self.portfolio_tree.see(selected_iid)
            self._portfolio_selected()
        elif not items:
            self._clear_detail()
        else:
            self._clear_detail()

    def _portfolio_selected(self, _event=None):
        selection = self.portfolio_tree.selection()
        if not selection:
            self._clear_detail()
            return
        portfolio_id = int(self.portfolio_tree.item(selection[0], "values")[0])
        self._run_async(
            "Loading linked properties...",
            lambda: portfolio_api.get_portfolio(portfolio_id),
            self._show_portfolio,
        )

    def _show_portfolio(self, portfolio):
        self.selected_portfolio = portfolio
        self.portfolio_name_label.configure(text=portfolio.get("name", "PORTFOLIO").upper())
        active = bool(portfolio.get("is_active"))
        count = int(portfolio.get("property_count", 0) or 0)
        self.portfolio_status_label.configure(
            text=f"{'Active' if active else 'Inactive'} folder - {count} linked propert{'y' if count == 1 else 'ies'}"
        )
        self.rename_button.configure(
            state="normal" if self.can_edit else "disabled"
        )
        self.toggle_button.configure(
            text="DEACTIVATE" if active else "REACTIVATE",
            state="normal" if self.can_edit else "disabled",
            fg_color=COLORS["amber"] if active else COLORS["green"],
            hover_color=COLORS["amber_hover"] if active else COLORS["green_hover"],
        )
        self.link_button.configure(
            state="normal" if self.can_edit and active else "disabled"
        )
        self.linked_properties = {}
        for item in self.property_tree.get_children():
            self.property_tree.delete(item)
        for index, prop in enumerate(portfolio.get("properties", [])):
            iid = f"linked-{prop['property_id']}-{index}"
            self.linked_properties[iid] = prop
            lot_block = " / ".join(
                value for value in (
                    str(prop.get("lot_number") or "").strip(),
                    str(prop.get("block_number") or "").strip(),
                )
                if value
            ) or "-"
            record_status = (
                "DELETED"
                if not prop.get("property_active", True)
                else "ARCHIVED"
                if prop.get("property_archived")
                else "ACTIVE"
            )
            self.property_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    prop.get("property_id"),
                    prop.get("td_number") or "-",
                    prop.get("owner_name") or "UNKNOWN",
                    prop.get("barangay") or "-",
                    prop.get("kind_of_property") or "-",
                    lot_block,
                    format_curr(prop.get("assessed_value", 0)),
                    record_status,
                ),
            )
        self._property_selected()

    def _clear_detail(self):
        self.selected_portfolio = None
        self.linked_properties = {}
        self.portfolio_name_label.configure(text="SELECT A PORTFOLIO")
        self.portfolio_status_label.configure(
            text="Choose a folder to view its linked properties."
        )
        for item in self.property_tree.get_children():
            self.property_tree.delete(item)
        for button in (
            self.rename_button,
            self.toggle_button,
            self.link_button,
            self.unlink_button,
            self.property_button,
            self.ledger_button,
            self.tax_bill_button,
            self.soa_button,
            self.delinquency_button,
        ):
            button.configure(state="disabled")

    def _selected_property(self):
        selection = self.property_tree.selection()
        return self.linked_properties.get(selection[0]) if selection else None

    def _property_selected(self, _event=None):
        prop = self._selected_property()
        usable = bool(
            prop
            and prop.get("property_active", True)
            and not prop.get("property_archived", False)
        )
        workflow_state = "normal" if usable else "disabled"
        for button in (
            self.property_button,
            self.ledger_button,
            self.tax_bill_button,
            self.soa_button,
            self.delinquency_button,
        ):
            button.configure(state=workflow_state)
        self.unlink_button.configure(
            state="normal" if prop and self.can_edit else "disabled"
        )

    def create_portfolio(self):
        name = simpledialog.askstring(
            "Create Portfolio",
            "Portfolio name:",
            parent=self.parent.winfo_toplevel(),
        )
        if not name or not name.strip():
            return
        self._run_async(
            "Creating portfolio...",
            lambda: portfolio_api.create_portfolio(name),
            lambda created: self._mutation_complete(
                created, "Portfolio created successfully."
            ),
        )

    def rename_portfolio(self):
        if not self.selected_portfolio:
            return
        current_name = self.selected_portfolio.get("name", "")
        name = simpledialog.askstring(
            "Rename Portfolio",
            "New portfolio name:",
            initialvalue=current_name,
            parent=self.parent.winfo_toplevel(),
        )
        if not name or not name.strip() or name.strip() == current_name:
            return
        portfolio_id = self.selected_portfolio["id"]
        self._run_async(
            "Renaming portfolio...",
            lambda: portfolio_api.update_portfolio(portfolio_id, name=name),
            lambda updated: self._mutation_complete(
                updated, "Portfolio renamed successfully."
            ),
        )

    def toggle_portfolio(self):
        if not self.selected_portfolio:
            return
        portfolio_id = self.selected_portfolio["id"]
        active = bool(self.selected_portfolio.get("is_active"))
        action = "deactivate" if active else "reactivate"
        explanation = (
            "Linked properties will remain in the folder and no property records "
            "will be changed."
            if active
            else "The folder will be available for linking properties again."
        )
        if not messagebox.askyesno(
            f"{action.title()} Portfolio",
            f"Do you want to {action} '{self.selected_portfolio.get('name')}'?\n\n{explanation}",
            parent=self.parent.winfo_toplevel(),
        ):
            return
        self._run_async(
            f"{action.title()} portfolio...",
            lambda: portfolio_api.update_portfolio(
                portfolio_id, is_active=not active
            ),
            lambda updated: self._mutation_complete(
                updated, f"Portfolio {action}d successfully."
            ),
        )

    def open_link_dialog(self):
        if not self.selected_portfolio or not self.selected_portfolio.get("is_active"):
            return
        PropertyLinkDialog(
            self.parent.winfo_toplevel(),
            self._link_property,
        )

    def _link_property(self, property_id, dialog):
        portfolio_id = self.selected_portfolio["id"]
        self._run_async(
            "Linking property...",
            lambda: portfolio_api.link_property(portfolio_id, property_id),
            lambda updated: self._link_complete(updated, dialog),
        )

    def _link_complete(self, updated, dialog):
        try:
            dialog.destroy()
        except (tk.TclError, RuntimeError):
            pass
        self._mutation_complete(updated, "Property linked to the portfolio.")

    def unlink_property(self):
        portfolio = self.selected_portfolio
        prop = self._selected_property()
        if not portfolio or not prop:
            return
        if not messagebox.askyesno(
            "Unlink Property",
            (
                f"Unlink TD {prop.get('td_number')} from '{portfolio.get('name')}'?\n\n"
                "The official property record, billing, and payments will not be changed."
            ),
            parent=self.parent.winfo_toplevel(),
        ):
            return
        self._run_async(
            "Unlinking property...",
            lambda: portfolio_api.unlink_property(
                portfolio["id"], prop["property_id"]
            ),
            lambda updated: self._mutation_complete(
                updated, "Property unlinked. Its official record was not changed."
            ),
        )

    def _mutation_complete(self, portfolio, message):
        self._show_portfolio(portfolio)
        show_toast(self.parent.winfo_toplevel(), message, type="success")
        self.refresh_portfolios(select_id=portfolio.get("id"))

    def _open_workflow(self, callback_name):
        prop = self._selected_property()
        callback = self.callbacks.get(callback_name)
        if not prop or not callback:
            return
        callback(prop.get("td_number"))

    def open_property_record(self):
        self._open_workflow("open_property")

    def open_ledger(self):
        self._open_workflow("open_ledger")

    def open_delinquency(self):
        self._open_workflow("open_delinquency")

    def download_tax_bill(self):
        prop = self._selected_property()
        if not prop:
            return
        default_year = datetime.now().year + 1
        tax_year = simpledialog.askinteger(
            "Tax Bill Year",
            "Tax year for this property:",
            initialvalue=default_year,
            minvalue=1900,
            maxvalue=2500,
            parent=self.parent.winfo_toplevel(),
        )
        if tax_year is None:
            return
        self._run_async(
            "Generating Tax Bill...",
            lambda: billing.download_tax_bill_pdf(prop["property_id"], tax_year),
            lambda path: self._open_document(path, "Tax Bill"),
            error_title="Tax Bill",
        )

    def download_soa(self):
        prop = self._selected_property()
        if not prop:
            return
        self._run_async(
            "Generating Statement of Account...",
            lambda: billing.download_statement_pdf(prop["property_id"]),
            lambda path: self._open_document(path, "Statement of Account"),
            error_title="Statement of Account",
        )

    def _open_document(self, path, document_name):
        try:
            if not path or not os.path.exists(path):
                raise FileNotFoundError("The downloaded file could not be found.")
            os.startfile(path)
            show_toast(
                self.parent.winfo_toplevel(),
                f"{document_name} opened for the selected property.",
                type="success",
            )
        except Exception as exc:
            ErrorDialog(
                self.parent.winfo_toplevel(),
                document_name,
                f"The document was downloaded but could not be opened: {exc}",
            )
