import os
import threading
import customtkinter as ctk
from tkinter import messagebox, ttk
import tkinter as tk
from theme_manager import ModernTheme
import api_clients.payment_service as payment
import api_clients.property_service as prop_svc
import api_clients.auth_service as auth
import api_clients.system_service as system
from utils import format_curr, export_data_to_excel, tr
from ui_components import LoadingOverlay, ErrorDialog


class PropertyAccountSelectionDialog(ctk.CTkToplevel):
    """Require an explicit property choice when an exact TD is duplicated."""

    def __init__(self, parent, td_number, matches, on_select):
        super().__init__(parent)
        self.matches = {int(item["id"]): item for item in matches}
        self.on_select = on_select
        self.title("Select Property Account")
        self.geometry("1040x470")
        self.minsize(900, 420)
        self.transient(parent)
        self.grab_set()
        self.configure(fg_color="#0f172a")

        header = ctk.CTkFrame(self, fg_color="#1e293b", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(
            header,
            text="⚠ MULTIPLE PROPERTY ACCOUNTS FOUND",
            font=("Inter", 18, "bold"),
            text_color="#fbbf24",
        ).pack(anchor="w", padx=22, pady=(18, 4))
        ctk.CTkLabel(
            header,
            text=(
                f"{len(matches)} properties use TD {td_number}. "
                "Select the correct owner/property before viewing or posting payments."
            ),
            font=("Inter", 11),
            text_color="#cbd5e1",
        ).pack(anchor="w", padx=22, pady=(0, 18))

        table_frame = ctk.CTkFrame(
            self,
            fg_color="#111827",
            border_width=1,
            border_color="#d97706",
            corner_radius=8,
        )
        table_frame.pack(fill="both", expand=True, padx=20, pady=18)

        style = ttk.Style()
        style.configure(
            "PropertyChoice.Treeview",
            rowheight=38,
            font=("Inter", 10),
            background="#172033",
            fieldbackground="#172033",
            foreground="#f8fafc",
            borderwidth=0,
        )
        style.configure(
            "PropertyChoice.Treeview.Heading",
            font=("Inter", 9, "bold"),
            background="#92400e",
            foreground="#ffffff",
            borderwidth=0,
        )
        style.map(
            "PropertyChoice.Treeview",
            background=[("selected", "#d97706")],
            foreground=[("selected", "#ffffff")],
        )

        columns = (
            "Record",
            "Owner",
            "PIN",
            "Lot / Block",
            "Barangay",
            "Classification",
            "Assessed Value",
        )
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            style="PropertyChoice.Treeview",
        )
        widths = {
            "Record": 80,
            "Owner": 240,
            "PIN": 145,
            "Lot / Block": 125,
            "Barangay": 130,
            "Classification": 155,
            "Assessed Value": 125,
        }
        for column in columns:
            self.tree.heading(column, text=column.upper())
            self.tree.column(
                column,
                width=widths[column],
                anchor="w" if column in ("Owner", "Classification") else "center",
            )
        for match in matches:
            lot_block = " / ".join(
                value
                for value in (
                    str(match.get("lot_number") or "").strip(),
                    str(match.get("block_number") or "").strip(),
                )
                if value
            ) or "—"
            self.tree.insert(
                "",
                "end",
                iid=str(match["id"]),
                values=(
                    f"#{match['id']}",
                    match.get("owner_name") or "UNKNOWN OWNER",
                    match.get("pin") or "—",
                    lot_block,
                    match.get("barangay") or match.get("location") or "—",
                    match.get("kind_of_property") or "—",
                    format_curr(match.get("assessed_value") or 0),
                ),
                tags=("duplicate_td",),
            )
        self.tree.tag_configure(
            "duplicate_td", background="#3b2a16", foreground="#fef3c7"
        )
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", pady=1, padx=(0, 1))
        self.tree.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_selection)
        self.tree.bind("<Double-1>", lambda _event: self._confirm())

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=(0, 18))
        ctk.CTkButton(
            actions,
            text="CANCEL",
            command=self.destroy,
            width=120,
            fg_color="#475569",
            hover_color="#64748b",
        ).pack(side="right")
        self.open_btn = ctk.CTkButton(
            actions,
            text="OPEN SELECTED LEDGER",
            command=self._confirm,
            width=210,
            state="disabled",
            fg_color="#d97706",
            hover_color="#b45309",
        )
        self.open_btn.pack(side="right", padx=(0, 10))
        self.after(50, self._center)

    def _center(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _on_selection(self, _event=None):
        self.open_btn.configure(
            state="normal" if self.tree.selection() else "disabled"
        )

    def _confirm(self):
        selection = self.tree.selection()
        if not selection:
            return
        match = self.matches.get(int(selection[0]))
        if not match:
            return
        self.grab_release()
        self.destroy()
        self.on_select(match)


class LedgerPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.is_loading = False
        self.search_timer = None
        self._ledger_property_ids = {}
        self._ledger_property_contexts = {}
        self._ledger_receipt_statuses = {}
        self._active_property_context = None
        self.setup_ui()

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)
        colors = {
            "panel": "#111827", "panel_alt": "#0f172a", "border": "#334155",
            "muted": "#94a3b8", "text": "#f8fafc", "blue": "#0284c7",
            "blue_hover": "#0369a1", "green": "#059669", "green_hover": "#047857",
            "amber": "#d97706", "amber_hover": "#b45309", "red": "#dc2626",
        }

        header = ctk.CTkFrame(self.container, fg_color="transparent")
        header.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(header, text=tr("ledger.title"), font=("Inter", 25, "bold"), text_color=colors["text"]).pack(anchor="w")
        ctk.CTkLabel(header, text=tr("ledger.subtitle"), font=("Inter", 11), text_color=colors["muted"]).pack(anchor="w", pady=(2, 0))

        toolbar = ctk.CTkFrame(self.container, fg_color=colors["panel"], corner_radius=8, border_width=1, border_color=colors["border"])
        toolbar.pack(fill="x", pady=(0, 12))
        lookup = ctk.CTkFrame(toolbar, fg_color="transparent")
        lookup.pack(side="left", padx=12, pady=11)
        ctk.CTkLabel(lookup, text="FIND LEDGER", font=("Inter", 10, "bold"), text_color=colors["muted"]).pack(side="left", padx=(0, 8))
        self.search_ent = ctk.CTkEntry(lookup, placeholder_text=tr("ledger.search_placeholder"), width=400, height=36, font=("Inter", 11), fg_color=colors["panel_alt"], border_color=colors["border"])
        self.search_ent.pack(side="left")
        self.search_ent.bind("<Return>", lambda e: self.load_ledger())
        self.search_ent.bind("<KP_Enter>", lambda e: self.load_ledger())
        self.search_btn = ctk.CTkButton(lookup, text=tr("ledger.btn_fetch").upper(), command=self.load_ledger, width=125, height=36, font=("Inter", 10, "bold"), fg_color=colors["blue"], hover_color=colors["blue_hover"], corner_radius=6)
        self.search_btn.pack(side="left", padx=(7, 0))
        if auth.has_permission(self.user, "payment_post"):
            self.add_payment_btn = ctk.CTkButton(lookup, text="ADD PAYMENT", command=self.add_payment, width=125, height=36, font=("Inter", 10, "bold"), fg_color=colors["green"], hover_color=colors["green_hover"], corner_radius=6)
            self.add_payment_btn.pack(side="left", padx=(8, 0))

        tools = ctk.CTkFrame(toolbar, fg_color="transparent")
        tools.pack(side="right", padx=12, pady=11)
        self.import_btn = ctk.CTkButton(tools, text=tr("property.btn_import").upper(), command=self.open_import_wizard, font=("Inter", 10, "bold"), fg_color="#334155", hover_color="#475569", width=112, height=36, corner_radius=6)
        self.import_btn.pack(side="left", padx=(0, 7))
        self.export_btn = ctk.CTkButton(tools, text=tr("ledger.btn_export").upper(), command=self.do_export, font=("Inter", 10, "bold"), fg_color=colors["amber"], hover_color=colors["amber_hover"], width=112, height=36, corner_radius=6)
        self.export_btn.pack(side="left")

        selected_bar = ctk.CTkFrame(
            self.container,
            fg_color=colors["panel"],
            corner_radius=8,
            border_width=1,
            border_color=colors["border"],
        )
        selected_bar.pack(fill="x", pady=(0, 9))
        context = ctk.CTkFrame(selected_bar, fg_color="transparent")
        context.pack(side="left", fill="x", expand=True, padx=(14, 10), pady=8)
        self.property_owner_lbl = ctk.CTkLabel(
            context,
            text="PROPERTY ACCOUNT  |  No property loaded",
            font=("Inter", 12, "bold"),
            text_color=colors["text"],
            anchor="w",
        )
        self.property_owner_lbl.pack(fill="x", anchor="w")
        self.property_context_lbl = ctk.CTkLabel(
            context,
            text="Search a TD number, owner, or OR number to view its payment history.",
            font=("Inter", 9),
            text_color=colors["muted"],
            anchor="w",
        )
        self.property_context_lbl.pack(fill="x", anchor="w", pady=(2, 0))
        self.view_btn = ctk.CTkButton(selected_bar, text=tr("ledger.btn_view").upper(), command=self.open_receipt, font=("Inter", 10, "bold"), fg_color=colors["blue"], hover_color=colors["blue_hover"], width=118, height=32, corner_radius=6, state="disabled")
        self.view_btn.pack(side="right", padx=(0, 12), pady=10)
        if auth.has_permission(self.user, "receipt_generate"):
            self.regen_btn = ctk.CTkButton(selected_bar, text=tr("ledger.btn_regen").upper(), command=self.regenerate_receipt, font=("Inter", 10, "bold"), fg_color=colors["green"], hover_color=colors["green_hover"], width=118, height=32, corner_radius=6, state="disabled")
            self.regen_btn.pack(side="right", padx=(0, 7))
        if auth.has_permission(self.user, "payment_post"):
            self.edit_btn = ctk.CTkButton(selected_bar, text="EDIT", command=self.edit_payment, font=("Inter", 10, "bold"), fg_color="#475569", hover_color="#64748b", width=92, height=32, corner_radius=6, state="disabled")
            self.edit_btn.pack(side="right", padx=(0, 7))
        if auth.has_permission(self.user, "payment_delete"):
            self.del_btn = ctk.CTkButton(selected_bar, text="DELETE", command=self.delete_payment, font=("Inter", 10, "bold"), fg_color=colors["red"], hover_color="#b91c1c", width=92, height=32, corner_radius=6, state="disabled")
            self.del_btn.pack(side="right", padx=(0, 7))

        t_frame = ctk.CTkFrame(self.container, fg_color=colors["panel_alt"], corner_radius=8, border_width=1, border_color=colors["border"])
        t_frame.pack(fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Ledger.Treeview", rowheight=34, font=("Inter", 11), background="#0f172a", fieldbackground="#0f172a", foreground="#e2e8f0", borderwidth=0)
        style.configure("Ledger.Treeview.Heading", font=("Inter", 10, "bold"), background="#334155", foreground="#f8fafc", borderwidth=0, relief="flat", padding=(8, 8))
        style.map("Ledger.Treeview", background=[("selected", colors["blue"])], foreground=[("selected", "#ffffff")])
        style.configure("Ledger.Vertical.TScrollbar", background="#475569", troughcolor="#0f172a", bordercolor="#0f172a", arrowcolor="#cbd5e1")

        # Internal ID, Date, OR, Year, Basic, SEF, Penalty, Discount, Total, PostedBy, FilePath
        self.cols = (
            tr("property.table.id"),
            tr("ledger.table.date"),
            tr("ledger.table.or"),
            tr("ledger.table.year"),
            tr("ledger.table.basic"),
            tr("ledger.table.sef"),
            tr("ledger.table.penalty"),
            tr("ledger.table.discount"),
            tr("ledger.table.total"),
            tr("ledger.table.posted"),
            "Remarks",
            tr("ledger.table.status")
        )
        self.tree = ttk.Treeview(t_frame, columns=self.cols, show="headings", style="Ledger.Treeview")
        
        for col in self.cols:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=100, anchor="center")

        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.column("OR Number", width=120)
        self.tree.column("Total Paid", width=130)
        self.tree.column("Posted By", width=150)
        self.tree.column("Remarks", width=220, anchor="w")
        self.tree.column("File Status", width=120)

        scrolly = ttk.Scrollbar(t_frame, orient="vertical", command=self.tree.yview, style="Ledger.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrolly.set)
        self.tree.tag_configure('oddrow', background="#162032", foreground="#e2e8f0")
        self.tree.tag_configure('evenrow', background="#1e293b", foreground="#e2e8f0")
        scrolly.pack(side="right", fill="y", pady=1, padx=(0, 1))
        self.tree.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        
        self.tree.bind("<<TreeviewSelect>>", self.on_selection_change)
        self.tree.bind("<Double-1>", lambda e: self.open_receipt())

        self.footer = ctk.CTkFrame(self.container, height=58, fg_color=colors["panel"], corner_radius=8, border_width=1, border_color=colors["border"])
        self.footer.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(self.footer, text="PAYMENT HISTORY TOTAL", font=("Inter", 9, "bold"), text_color=colors["muted"]).pack(side="left", padx=18, pady=14)
        self.total_lbl = ctk.CTkLabel(self.footer, text=tr("ledger.footer.total").replace("{value}", "₱ 0.00"), 
                                      font=("Inter", 17, "bold"), text_color="#34d399")
        self.total_lbl.pack(side="right", padx=18, pady=14)

    def on_selection_change(self, event=None):
        sel = self.tree.selection()
        state = "normal" if sel else "disabled"
        self.view_btn.configure(state=state)
        if hasattr(self, "regen_btn"):
            regen_state = (
                state if auth.has_permission(self.user, "receipt_generate") else "disabled"
            )
            self.regen_btn.configure(state=regen_state)
        if hasattr(self, "edit_btn"):
            self.edit_btn.configure(state=state)
        if hasattr(self, "del_btn"):
            self.del_btn.configure(state=state)
        if sel:
            self._show_property_context(
                self._ledger_property_contexts.get(sel[0]),
                self.tree.item(sel[0]).get("values", []),
            )
        elif self._active_property_context:
            self._show_property_context(self._active_property_context)

    def _show_property_context(self, context, payment_values=None):
        if not context:
            self.property_owner_lbl.configure(
                text="PROPERTY ACCOUNT  |  No property loaded",
                text_color="#f8fafc",
            )
            self.property_context_lbl.configure(
                text="Search a TD number, owner, or OR number to view its payment history."
            )
            return

        if context.get("multiple"):
            count = context.get("count", 0)
            self.property_owner_lbl.configure(text="PROPERTY ACCOUNT  |  Multiple properties found")
            self.property_context_lbl.configure(
                text=f"{count} property accounts match this search. Select a payment row to confirm its owner."
            )
            return

        owner = str(context.get("owner_name") or "UNKNOWN OWNER").strip()
        td_number = str(context.get("td_number") or "No TD").strip()
        barangay = str(context.get("barangay") or "Unspecified barangay").strip()
        classification = str(
            context.get("kind_of_property") or "Unspecified classification"
        ).strip()
        record_id = context.get("property_id")
        pin = str(context.get("pin") or "").strip()
        lot = str(context.get("lot_number") or "").strip()
        block = str(context.get("block_number") or "").strip()
        details = f"TD {td_number}"
        if record_id:
            details += f"  |  Record #{record_id}"
        if pin:
            details += f"  |  PIN {pin}"
        if lot or block:
            details += f"  |  Lot/Block {lot or '—'} / {block or '—'}"
        details += f"  |  {barangay}  |  {classification}"
        if payment_values and len(payment_values) > 3:
            or_number = str(payment_values[2] or "No OR")
            tax_year = str(payment_values[3] or "No tax year")
            details += f"  |  Selected: OR {or_number} - Tax Year {tax_year}"
        prefix = (
            "⚠ DUPLICATE TD ACCOUNT"
            if context.get("duplicate_td")
            else "PROPERTY OWNER"
        )
        self.property_owner_lbl.configure(text=f"{prefix}  |  {owner}")
        self.property_owner_lbl.configure(
            text_color="#fbbf24" if context.get("duplicate_td") else "#f8fafc"
        )
        self.property_context_lbl.configure(text=details)

    def load_ledger(self):
        term = self.search_ent.get().strip()
        if not term:
            ErrorDialog(self.parent.winfo_toplevel(), tr("ledger.errors.input_req"), tr("ledger.errors.input_req_msg"))
            return

        if self.is_loading: return
        self.is_loading = True
        self.search_btn.configure(state="disabled")
        
        self.overlay = LoadingOverlay(self.container, tr("ledger.loading_msg") if "ledger.loading_msg" in tr("ledger") else "Fetching Records...")

        for r in self.tree.get_children(): self.tree.delete(r)

        def worker():
            try:
                exact_matches = prop_svc.find_properties_by_td_number(term)
                if len(exact_matches) > 1:
                    self.container.after(
                        0,
                        lambda matches=exact_matches: self._show_property_selector(
                            term, matches
                        ),
                    )
                    return

                # Unified query returns:
                # 0 payment_id, 1 date_paid, 2 OR, 3 tax_year, 4 basic, 5 SEF,
                # 6 penalty, 7 discount, 8 amount, 9 posted_by, 10 remarks,
                # 11 file_path, 12 receipt_id, 13 TD, 14 owner, 15 property_id,
                # 16 barangay, 17 classification, 18 retained PDF status.
                if len(exact_matches) == 1:
                    selected = exact_matches[0]
                    rows = payment.get_unified_payment_history(
                        property_id=selected["id"]
                    )
                    fallback_context = self._property_context_from_detail(selected)
                else:
                    rows = payment.get_unified_payment_history(term=term)
                    fallback_context = None
                if not rows and fallback_context is None:
                    fallback_context = self._resolve_property_context(term)
                self.container.after(
                    0,
                    lambda: self._update_ui(rows, term, fallback_context),
                )
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Error", str(err)))
            finally:
                self.is_loading = False
                self.container.after(0, lambda: self.overlay.hide())
                self.container.after(0, lambda: self.search_btn.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _show_property_selector(self, td_number, matches):
        for match in matches:
            match["duplicate_count"] = len(matches)
        PropertyAccountSelectionDialog(
            self.container.winfo_toplevel(),
            td_number,
            matches,
            self._load_selected_property,
        )
        self._active_property_context = {
            "multiple": True,
            "count": len(matches),
        }
        self._show_property_context(self._active_property_context)

    def _load_selected_property(self, match):
        if self.is_loading:
            return
        self.is_loading = True
        self.search_btn.configure(state="disabled")
        overlay = LoadingOverlay(self.container, "Loading selected property ledger...")
        context = self._property_context_from_detail(match)
        context["duplicate_td"] = True
        context["duplicate_count"] = int(match.get("duplicate_count") or 2)

        for row_id in self.tree.get_children():
            self.tree.delete(row_id)

        def worker():
            try:
                rows = payment.get_unified_payment_history(
                    property_id=match["id"]
                )
                self.container.after(
                    0,
                    lambda: self._update_ui(
                        rows,
                        str(match.get("td_number") or ""),
                        context,
                    ),
                )
            except Exception as exc:
                self.container.after(
                    0, lambda err=exc: messagebox.showerror("Ledger", str(err))
                )
            finally:
                self.is_loading = False
                self.container.after(0, overlay.hide)
                self.container.after(
                    0, lambda: self.search_btn.configure(state="normal")
                )

        threading.Thread(target=worker, daemon=True).start()

    def _update_ui(self, rows, term, fallback_context=None):
        grand_total = 0.0
        self._ledger_property_ids = {}
        self._ledger_property_contexts = {}
        self._ledger_receipt_statuses = {}
        self._active_property_context = None
        if rows:
            for i, r in enumerate(rows):
                # r: 0:pay_id, 1:date, 2:or, 3:year, 4:basic, 5:sef, 6:pen,
                # 7:disc, 8:amt, 9:user, 10:remarks, 11:path, 12:rid
                f_r = list(r[:11])
                file_path = r[11] if len(r) > 11 else None
                status_code = (
                    str(r[18] or "").upper()
                    if len(r) > 18
                    else ("READY" if file_path else "NOT_GENERATED")
                )
                status_key = {
                    "READY": "ledger.table.status_ready",
                    "NOT_GENERATED": "ledger.table.status_not_generated",
                }.get(status_code, "ledger.table.status_missing")
                status = tr(status_key)
                f_r.append(status)
                
                # Format Currencies
                f_r[4] = format_curr(f_r[4]) # Basic
                f_r[5] = format_curr(f_r[5]) # SEF
                f_r[6] = format_curr(f_r[6]) # Penalty
                f_r[7] = format_curr(f_r[7]) # Discount
                f_r[8] = format_curr(f_r[8]) # Total
                f_r[10] = str(f_r[10] or "")
                
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                item_id = self.tree.insert("", "end", values=f_r, tags=(tag,))
                self._ledger_receipt_statuses[item_id] = status_code
                if len(r) > 15:
                    self._ledger_property_ids[item_id] = r[15]
                    self._ledger_property_contexts[item_id] = {
                        "property_id": r[15],
                        "td_number": r[13] if len(r) > 13 else "",
                        "owner_name": r[14] if len(r) > 14 else "",
                        "barangay": r[16] if len(r) > 16 else "",
                        "kind_of_property": r[17] if len(r) > 17 else "",
                    }
                try: grand_total += float(r[8])
                except: pass
            self.total_lbl.configure(text=tr("ledger.footer.total").replace("{value}", f"₱ {grand_total:,.2f}"))
            contexts_by_property = {
                context["property_id"]: context
                for context in self._ledger_property_contexts.values()
            }
            if len(contexts_by_property) == 1:
                only_context = next(iter(contexts_by_property.values()))
                if (
                    fallback_context
                    and fallback_context.get("property_id")
                    == only_context.get("property_id")
                ):
                    self._active_property_context = fallback_context
                else:
                    self._active_property_context = only_context
            elif contexts_by_property:
                self._active_property_context = {
                    "multiple": True,
                    "count": len(contexts_by_property),
                }
        else:
            # A valid property can have no payment history yet. Preserve its
            # identity so the ledger and Add Payment modal stay connected.
            self._active_property_context = fallback_context
            self.total_lbl.configure(text=tr("ledger.footer.total").replace("{value}", "₱ 0.00"))
        self._show_property_context(self._active_property_context)
        self.on_selection_change()

    def open_receipt(self):
        sel = self.tree.selection()
        if not sel: return

        item_id = sel[0]
        pay_id = self.tree.item(item_id)["values"][0]
        status = self._ledger_receipt_statuses.get(item_id, "NOT_GENERATED")
        if status != "READY":
            if messagebox.askyesno(
                tr("ledger.errors.receipt_missing"),
                tr("ledger.errors.receipt_missing_msg"),
            ):
                self.regenerate_receipt()
            return

        overlay = LoadingOverlay(self.container, "Opening retained PDF copy...")

        def worker():
            try:
                local_path = payment.get_receipt_pdf(pay_id)
                self.container.after(0, lambda: os.startfile(local_path))
            except Exception as exc:
                error_message = str(exc)
                self.container.after(
                    0,
                    lambda: self._handle_receipt_open_error(error_message),
                )
            finally:
                self.container.after(0, overlay.hide)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_receipt_open_error(self, error_message):
        if "Status 404" in error_message and messagebox.askyesno(
            tr("ledger.errors.receipt_missing"),
            tr("ledger.errors.receipt_missing_msg"),
        ):
            self.regenerate_receipt()
            return
        messagebox.showerror("PDF Copy Error", error_message)

    def regenerate_receipt(self):
        sel = self.tree.selection()
        if not sel: return
        
        pay_id = self.tree.item(sel[0])["values"][0]
        overlay = LoadingOverlay(self.container, "Generating current PDF copy...")
        
        def worker():
            try:
                # Ask the backend to generate the PDF and download it locally
                new_path = payment.generate_receipt_pdf(pay_id)
                if not new_path:
                    raise Exception("Backend did not return a PDF path.")

                system.log_action(
                    self.user,
                    f"Regenerated payment-record PDF for payment ID {pay_id}",
                )
                self.container.after(0, lambda: [self.load_ledger(), os.startfile(new_path)])
            except Exception as e:
                err_msg = str(e)
                self.container.after(0, lambda: messagebox.showerror("Generation Error", err_msg))
            finally:
                self.container.after(0, lambda: overlay.hide())

        threading.Thread(target=worker, daemon=True).start()

    def open_import_wizard(self):
        from ui.import_wizard import ImportWizardModal
        ImportWizardModal(self.container.winfo_toplevel(), mode="payments")

    def add_payment(self):
        selected_property_id = self._selected_property_id()
        if selected_property_id:
            self._open_payment_modal(selected_property_id)
            return

        if (
            self._active_property_context
            and not self._active_property_context.get("multiple")
            and self._active_property_context.get("property_id")
        ):
            self._open_payment_modal(
                self._active_property_context["property_id"],
                self._active_property_context,
            )
            return

        term = self.search_ent.get().strip()
        if not term:
            ErrorDialog(
                self.parent.winfo_toplevel(),
                "Search Required",
                "Search a TD number, former TD number, PIN, or owner name first.",
            )
            return

        overlay = LoadingOverlay(self.container, "Finding Property...")

        def worker():
            try:
                # Resolve an exact current TD through a fresh, non-cached
                # request before using the broader property search. A former
                # TD on a replacement record may equal another property's
                # current TD, so the general result set can be ambiguous.
                property_id = self._find_exact_current_property_id(term)
                if property_id is not None:
                    context = self._property_context_for_id(property_id)
                    self.container.after(
                        0,
                        lambda pid=property_id, ctx=context: self._open_payment_modal(
                            pid, ctx
                        ),
                    )
                    return

                res = prop_svc.search_properties(term, limit=20)
                items = res.get("items", []) if isinstance(res, dict) else []
                match, message = self._resolve_property_match(term, items)
                if match:
                    context = self._property_context_from_search_row(match)
                    self.container.after(
                        0,
                        lambda pid=match[0], ctx=context: self._open_payment_modal(
                            pid, ctx
                        ),
                    )
                else:
                    self.container.after(0, lambda msg=message: messagebox.showwarning("Add Payment", msg))
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Add Payment", str(err)))
            finally:
                self.container.after(0, lambda: overlay.hide())

        threading.Thread(target=worker, daemon=True).start()

    def _find_exact_current_property_id(self, term):
        exact_current = prop_svc.find_property_by_td_number(term)
        if not isinstance(exact_current, dict):
            return None
        return exact_current.get("id")

    def _resolve_property_context(self, term):
        exact_current = prop_svc.find_property_by_td_number(term)
        if isinstance(exact_current, dict) and exact_current.get("id") is not None:
            return self._property_context_for_id(
                exact_current["id"], fallback=exact_current
            )

        response = prop_svc.search_properties(term, limit=20)
        items = response.get("items", []) if isinstance(response, dict) else []
        match, _message = self._resolve_property_match(term, items)
        if match:
            return self._property_context_from_search_row(match)
        if len(items) > 1:
            return {"multiple": True, "count": len(items)}
        return None

    def _property_context_for_id(self, property_id, fallback=None):
        try:
            detail = prop_svc.get_property_by_id(property_id)
        except Exception:
            detail = fallback
        return self._property_context_from_detail(detail)

    def _property_context_from_detail(self, detail):
        if not isinstance(detail, dict):
            return None
        return {
            "property_id": detail.get("id"),
            "td_number": detail.get("td_number"),
            "owner_name": detail.get("owner_name"),
            "barangay": detail.get("barangay") or detail.get("location"),
            "kind_of_property": detail.get("kind_of_property"),
            "pin": detail.get("pin"),
            "lot_number": detail.get("lot_number"),
            "block_number": detail.get("block_number"),
        }

    def _property_context_from_search_row(self, row):
        if not row:
            return None
        return {
            "property_id": row[0] if len(row) > 0 else None,
            "td_number": row[1] if len(row) > 1 else None,
            "owner_name": row[2] if len(row) > 2 else None,
            "kind_of_property": row[7] if len(row) > 7 else None,
            "barangay": row[22] if len(row) > 22 else (
                row[6] if len(row) > 6 else None
            ),
        }

    def _selected_property_id(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self._ledger_property_ids.get(sel[0])

    def _resolve_property_match(self, term, items):
        if not items:
            return None, "No property matched your search."

        clean_term = self._normalize_identifier(term)
        # A current TD is the strongest identifier. A transferred property's
        # former TD may legitimately equal another record's current TD, so the
        # two fields must never compete at the same priority.
        for field_index, field_name in (
            (1, "current TD number"),
            (18, "PIN"),
            (20, "former TD number"),
        ):
            matches = [
                row for row in items
                if len(row) > field_index
                and self._normalize_identifier(row[field_index]) == clean_term
            ]
            if len(matches) == 1:
                return matches[0], None
            if len(matches) > 1:
                return None, f"Multiple properties share this {field_name}. Please verify the property record first."

        if len(items) == 1:
            return items[0], None

        return None, "Multiple properties matched. Please search the exact TD number or former TD number, then try Add Payment again."

    def _normalize_identifier(self, value):
        return str(value or "").strip().replace(" ", "-").upper()

    def _open_payment_modal(self, property_id, context=None):
        if context:
            self._active_property_context = context
            self._show_property_context(context)
        from ui.property import PropertyEditModal
        PropertyEditModal(
            self.container.winfo_toplevel(),
            "Add Payment",
            property_id,
            self.load_ledger,
            user=self.user,
            payment_mode=True,
        )

    def do_export(self):
        data = []
        for child in self.tree.get_children():
            data.append(self.tree.item(child)["values"])
            
        if not data:
            messagebox.showwarning("Export", "No data to export. Please search for a record first.")
            return
            
        export_data_to_excel(data, self.cols, filename_prefix="LedgerExport")

    def edit_payment(self):
        sel = self.tree.selection()
        if not sel:
            return
        pay_id = self.tree.item(sel[0])["values"][0]
        overlay = LoadingOverlay(self.container, "Loading Payment...")

        def worker():
            try:
                details = payment.get_payment_receipt_details(pay_id)
                self.container.after(0, lambda: PaymentEditModal(
                    self.container.winfo_toplevel(),
                    pay_id,
                    details,
                    self.load_ledger,
                ))
            except Exception as e:
                self.container.after(0, lambda err=e: messagebox.showerror("Edit Payment", str(err)))
            finally:
                self.container.after(0, lambda: overlay.hide())

        threading.Thread(target=worker, daemon=True).start()
    def delete_payment(self):
        sel = self.tree.selection()
        if not sel: return
        
        item = self.tree.item(sel[0])
        pay_id = item["values"][0]
        or_no = item["values"][2]
        
        if not messagebox.askyesno("Delete Payment", f"Are you sure you want to permanently delete payment OR {or_no}?\n\nThis will reverse its impact on the corresponding billing balances.", icon="warning"):
            return
            
        overlay = LoadingOverlay(self.container, "Deleting Payment...")
        
        def worker():
            try:
                res = payment.delete_payment(pay_id)
                self.container.after(0, lambda: messagebox.showinfo("Success", res.get("message", "Payment deleted.")))
                self.container.after(0, self.load_ledger)
            except Exception as e:
                err_msg = str(e)
                self.container.after(0, lambda: messagebox.showerror("Error", err_msg))
            finally:
                self.container.after(0, lambda: overlay.hide())

        threading.Thread(target=worker, daemon=True).start()

class PaymentEditModal(ctk.CTkToplevel):
    def __init__(self, parent, payment_id, details, callback):
        super().__init__(parent)
        self.payment_id = payment_id
        self.details = details or {}
        self.callback = callback
        self.title("Edit Payment")
        self._modal_width = 500
        self._modal_height = 640
        self.geometry(f"{self._modal_width}x{self._modal_height}")
        self.minsize(480, 560)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()
        self.configure(fg_color="#0f172a")
        self._build_ui()
        self.update_idletasks()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - self._modal_width) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self._modal_height) // 2)
        self.geometry(f"+{x}+{y}")

    def _date_text(self, value):
        text = str(value or "").strip()
        if "T" in text:
            return text.split("T", 1)[0]
        if " " in text:
            return text.split(" ", 1)[0]
        return text

    def _money_text(self, key):
        try:
            return f"{float(self.details.get(key, 0) or 0):.2f}"
        except Exception:
            return "0.00"

    def _build_ui(self):
        body = ctk.CTkFrame(self, fg_color="#111827", corner_radius=8)
        body.pack(fill="both", expand=True, padx=20, pady=20)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(body, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 8))
        ctk.CTkLabel(header, text="Edit Payment", font=("Segoe UI", 20, "bold"), text_color="white").pack(anchor="w")
        title = f"{self.details.get('td_number', '')}  |  {self.details.get('owner_name', '')}"
        ctk.CTkLabel(header, text=title, font=("Segoe UI", 11), text_color="#94a3b8", wraplength=430, justify="left").pack(anchor="w", pady=(4, 0))

        content = ctk.CTkScrollableFrame(
            body,
            fg_color="transparent",
            scrollbar_button_color="#334155",
            scrollbar_button_hover_color="#475569",
        )
        content.grid(row=1, column=0, sticky="nsew", padx=(18, 10), pady=(0, 12))
        content.grid_columnconfigure(0, weight=1)

        self.vars = {
            "date_paid": tk.StringVar(value=self._date_text(self.details.get("date_paid"))),
            "or_number": tk.StringVar(value=str(self.details.get("or_number") or "")),
            "tax_year": tk.StringVar(value=str(self.details.get("tax_year") or "")),
            "penalty": tk.StringVar(value=self._money_text("penalty")),
            "discount": tk.StringVar(value=self._money_text("discount")),
            "amount": tk.StringVar(value=self._money_text("amount")),
            "remarks": tk.StringVar(value=str(self.details.get("remarks") or "")),
        }

        fields = (
            ("OR Date", "date_paid", "YYYY-MM-DD"),
            ("OR Number", "or_number", ""),
            ("Tax Year", "tax_year", "e.g. 2026"),
            ("Penalty", "penalty", "0.00"),
            ("Discount", "discount", "0.00"),
            ("Total Paid", "amount", "0.00"),
            ("Remarks", "remarks", "Optional note only"),
        )
        self._field_entries = []
        for label, key, placeholder in fields:
            ctk.CTkLabel(content, text=label.upper(), font=("Segoe UI", 10, "bold"), text_color="#94a3b8").pack(anchor="w", fill="x")
            ent = ctk.CTkEntry(content, textvariable=self.vars[key], placeholder_text=placeholder, height=36, fg_color="#1f2937", border_color="#475569", text_color="white")
            ent.pack(fill="x", pady=(4, 12))
            self._field_entries.append(ent)

        hint = "Changing this record recalculates the linked billing balance. Regenerate the receipt after saving if the PDF should reflect the correction."
        ctk.CTkLabel(content, text=hint, font=("Segoe UI", 10), text_color="#fbbf24", wraplength=430, justify="left").pack(anchor="w", fill="x", pady=(0, 8))

        footer = ctk.CTkFrame(body, fg_color="#111827")
        footer.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 18))
        footer.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(footer, text="CANCEL", command=self.destroy, fg_color="#64748b", width=120, height=36).grid(row=0, column=0, sticky="w")
        self.save_btn = ctk.CTkButton(footer, text="SAVE CHANGES", command=self.save, fg_color=ModernTheme.SUCCESS, width=160, height=36)
        self.save_btn.grid(row=0, column=2, sticky="e")
        self.save_btn.bind("<Return>", lambda _e: self.save())
        self.save_btn.bind("<KP_Enter>", lambda _e: self.save())
        self._bind_enter_navigation()

        if self._field_entries:
            self._field_entries[0].focus_set()

    def _bind_enter_navigation(self):
        for entry in self._field_entries:
            for widget in (entry, getattr(entry, "_entry", None)):
                if widget:
                    widget.bind("<Return>", lambda _e, w=entry: self._focus_next_entry(w))
                    widget.bind("<KP_Enter>", lambda _e, w=entry: self._focus_next_entry(w))

    def _focus_next_entry(self, current):
        try:
            index = self._field_entries.index(current)
        except ValueError:
            return "break"

        if index + 1 < len(self._field_entries):
            next_widget = self._field_entries[index + 1]
        else:
            next_widget = self.save_btn
        self.after_idle(next_widget.focus_set)
        return "break"

    def _amount(self, key):
        text = self.vars[key].get().replace(",", "").strip()
        return float(text or 0)

    def save(self):
        try:
            data = {
                "date_paid": self.vars["date_paid"].get().strip(),
                "or_number": self.vars["or_number"].get().strip(),
                "tax_year": self.vars["tax_year"].get().strip(),
                "penalty": self._amount("penalty"),
                "discount": self._amount("discount"),
                "amount": self._amount("amount"),
                "remarks": self.vars["remarks"].get().strip(),
            }
        except ValueError:
            messagebox.showerror("Invalid Amount", "Penalty, discount, and total paid must be valid numbers.", parent=self)
            return

        missing = [label for label, key in (("OR Date", "date_paid"), ("OR Number", "or_number"), ("Tax Year", "tax_year")) if not data[key]]
        if missing:
            messagebox.showerror("Missing Details", f"Please fill in: {', '.join(missing)}.", parent=self)
            return

        self.save_btn.configure(state="disabled", text="SAVING...")

        def worker():
            try:
                res = payment.update_payment(self.payment_id, data)
                self.after(0, lambda: messagebox.showinfo("Payment Updated", res.get("message", "Payment updated successfully."), parent=self))
                if self.callback:
                    self.after(0, self.callback)
                self.after(0, self.destroy)
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror("Edit Payment", str(err), parent=self))
                self.after(0, lambda: self.save_btn.configure(state="normal", text="SAVE CHANGES"))

        threading.Thread(target=worker, daemon=True).start()
