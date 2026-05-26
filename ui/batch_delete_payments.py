"""
Batch Payment Delete Tool
Allows admin to delete a batch of wrong payments by uploading a CSV/Excel
of OR numbers, previewing what will be deleted, then confirming.
"""
import csv
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import customtkinter as ctk

import api_clients.payment_service as pay_svc
from theme_manager import ModernTheme
from utils import format_curr

# ── Row colours ───────────────────────────────────────────────────────────────
_ROW_ODD   = "#1e293b"
_ROW_EVEN  = "#162032"
_ROW_FG    = "#cbd5e1"
_ROW_SEL   = "#1d4ed8"
_HDR_BG    = "#0f172a"
_HDR_FG    = "#64748b"


class BatchDeletePaymentsModal(ctk.CTkToplevel):
    def __init__(self, parent, user=None):
        super().__init__(parent)
        self.title("Batch Payment Delete")
        self.geometry("1000x680")
        self.resizable(True, True)
        self.user = user
        self._preview_data = []   # list of payment dicts from preview
        self._or_numbers   = []   # OR numbers loaded from file

        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-1000)//2}+{(sh-680)//2}")

        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.configure(fg_color=(ModernTheme.BG_LIGHT, ModernTheme.BG_DARK))

        # ── Header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(16, 0))

        ctk.CTkLabel(
            hdr, text="🗑️  BATCH PAYMENT DELETE",
            font=ModernTheme.H3, text_color="#ef4444", anchor="w",
        ).pack(side="left")

        ctk.CTkButton(
            hdr, text="✕  CLOSE", command=self.destroy,
            width=90, height=32,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SECONDARY,
            hover_color=ModernTheme.SECONDARY_HOVER,
        ).pack(side="right")

        # ── Warning banner ────────────────────────────────────────────────────
        warn = ctk.CTkFrame(
            self, fg_color=("#fff3e0", "#1e293b"),
            corner_radius=8, border_width=1, border_color=("#ffcc80", "#92400e"),
        )
        warn.pack(fill="x", padx=20, pady=(10, 0))
        ctk.CTkLabel(
            warn,
            text=(
                "⚠️  This tool permanently deletes payment records and reverses their billing balances. "
                "Always preview before confirming. This action is logged in the Audit Trail."
            ),
            font=ModernTheme.BODY, text_color=("#92400e", "#fbbf24"),
            wraplength=900, justify="left",
        ).pack(padx=14, pady=8, anchor="w")

        # ── Step 1: Load OR numbers ───────────────────────────────────────────
        step1 = ctk.CTkFrame(self, fg_color=(ModernTheme.CARD_LIGHT, ModernTheme.CARD_DARK), corner_radius=10)
        step1.pack(fill="x", padx=20, pady=(12, 0))

        ctk.CTkLabel(
            step1, text="STEP 1 — Load OR Numbers",
            font=("Inter", 11, "bold"), text_color=ModernTheme.PRIMARY, anchor="w",
        ).pack(anchor="w", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            step1,
            text="Upload a CSV or Excel file with a column named 'OR NUMBER' (or 'OR NO', 'OR_NO').\n"
                 "You can also paste OR numbers directly — one per line.",
            font=ModernTheme.BODY, text_color=ModernTheme.TEXT_GRAY, anchor="w",
        ).pack(anchor="w", padx=14)

        btn_row = ctk.CTkFrame(step1, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(8, 10))

        ctk.CTkButton(
            btn_row, text="📁  UPLOAD CSV / EXCEL",
            command=self._load_file,
            width=180, height=36,
            font=ModernTheme.BUTTON_SMALL,
            fg_color="#1d4ed8", hover_color="#1e40af",
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_row, text="✏️  PASTE OR NUMBERS",
            command=self._paste_dialog,
            width=180, height=36,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SECONDARY,
            hover_color=ModernTheme.SECONDARY_HOVER,
        ).pack(side="left")

        self._loaded_lbl = ctk.CTkLabel(
            btn_row, text="No file loaded",
            font=ModernTheme.BODY, text_color=ModernTheme.TEXT_GRAY,
        )
        self._loaded_lbl.pack(side="left", padx=14)

        # ── Step 2: Preview ───────────────────────────────────────────────────
        step2_hdr = ctk.CTkFrame(self, fg_color="transparent")
        step2_hdr.pack(fill="x", padx=20, pady=(12, 4))

        ctk.CTkLabel(
            step2_hdr, text="STEP 2 — Preview & Confirm",
            font=("Inter", 11, "bold"), text_color=ModernTheme.PRIMARY, anchor="w",
        ).pack(side="left")

        self._preview_btn = ctk.CTkButton(
            step2_hdr, text="🔍  LOAD PREVIEW",
            command=self._load_preview,
            width=150, height=34,
            font=ModernTheme.BUTTON_SMALL,
            fg_color="#059669", hover_color="#047857",
            state="disabled",
        )
        self._preview_btn.pack(side="right")

        self._summary_lbl = ctk.CTkLabel(
            step2_hdr, text="",
            font=ModernTheme.BODY, text_color=ModernTheme.TEXT_GRAY,
        )
        self._summary_lbl.pack(side="right", padx=12)

        # Preview treeview
        tree_fr = tk.Frame(self, bg=_ROW_ODD)
        tree_fr.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        style = ttk.Style()
        style.configure(
            "BatchDel.Treeview",
            rowheight=30, font=("Inter", 11),
            background=_ROW_ODD, fieldbackground=_ROW_ODD, foreground=_ROW_FG,
        )
        style.configure(
            "BatchDel.Treeview.Heading",
            font=("Inter", 11, "bold"), background=_HDR_BG, foreground=_HDR_FG,
        )
        style.map("BatchDel.Treeview", background=[("selected", _ROW_SEL)])

        cols = ("PAY ID", "OR NUMBER", "TD NUMBER", "OWNER", "YEAR", "AMOUNT", "DISCOUNT", "DATE PAID")
        self._tree = ttk.Treeview(tree_fr, columns=cols, show="headings", style="BatchDel.Treeview")
        self._tree.column("PAY ID",    width=70,  anchor="center")
        self._tree.column("OR NUMBER", width=110, anchor="w")
        self._tree.column("TD NUMBER", width=130, anchor="w")
        self._tree.column("OWNER",     width=200, anchor="w")
        self._tree.column("YEAR",      width=60,  anchor="center")
        self._tree.column("AMOUNT",    width=110, anchor="e")
        self._tree.column("DISCOUNT",  width=100, anchor="e")
        self._tree.column("DATE PAID", width=100, anchor="center")
        for col in cols:
            self._tree.heading(col, text=col)

        scrolly = ttk.Scrollbar(tree_fr, orient="vertical", command=self._tree.yview)
        scrollx = ttk.Scrollbar(tree_fr, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=scrolly.set, xscrollcommand=scrollx.set)
        scrolly.pack(side="right", fill="y")
        scrollx.pack(side="bottom", fill="x")
        self._tree.pack(side="left", fill="both", expand=True)

        self._tree.tag_configure("oddrow",  background=_ROW_ODD,  foreground=_ROW_FG)
        self._tree.tag_configure("evenrow", background=_ROW_EVEN, foreground=_ROW_FG)
        self._tree.tag_configure("notfound", background="#450a0a", foreground="#fca5a5")

        # ── Footer ────────────────────────────────────────────────────────────
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=20, pady=(0, 16))

        ctk.CTkButton(
            foot, text="CANCEL", command=self.destroy,
            fg_color=ModernTheme.SECONDARY, hover_color=ModernTheme.SECONDARY_HOVER,
            width=120, height=40, font=ModernTheme.BUTTON_SMALL,
        ).pack(side="left")

        self._delete_btn = ctk.CTkButton(
            foot,
            text="🗑️  DELETE ALL PREVIEWED PAYMENTS",
            command=self._confirm_and_delete,
            fg_color="#dc2626", hover_color="#b91c1c",
            text_color="white",
            width=280, height=40, font=("Inter", 13, "bold"),
            state="disabled",
        )
        self._delete_btn.pack(side="right")

    # ── File loading ──────────────────────────────────────────────────────────

    def _load_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("Data files", "*.csv *.xlsx *.xls")],
            title="Select file with OR numbers",
        )
        if not path:
            return
        try:
            or_numbers = self._parse_file(path)
            self._set_or_numbers(or_numbers, label=f"{os.path.basename(path)} ({len(or_numbers)} OR numbers)")
        except Exception as e:
            messagebox.showerror("File Error", str(e))

    def _parse_file(self, path: str) -> list:
        ext = os.path.splitext(path)[1].lower()
        or_col_aliases = {"or number", "or no", "or_no", "ornumber", "or no.", "receipt no"}

        if ext == ".csv":
            with open(path, encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                headers = {h.strip().lower(): h for h in (reader.fieldnames or [])}
                col = next((headers[a] for a in or_col_aliases if a in headers), None)
                if not col:
                    raise ValueError(f"No OR number column found. Headers: {list(headers.keys())}")
                return [str(row[col]).strip() for row in reader if str(row[col]).strip()]
        else:
            import pandas as pd
            df = pd.read_excel(path)
            df.columns = [str(c).strip().upper() for c in df.columns]
            aliases_upper = {a.upper() for a in or_col_aliases}
            col = next((c for c in df.columns if c in aliases_upper), None)
            if not col:
                raise ValueError(f"No OR number column found. Headers: {list(df.columns)}")
            return [str(v).strip() for v in df[col].dropna() if str(v).strip()]

    def _paste_dialog(self):
        """Open a simple text dialog for pasting OR numbers."""
        dlg = ctk.CTkToplevel(self)
        dlg.title("Paste OR Numbers")
        dlg.geometry("420x380")
        dlg.grab_set()
        dlg.attributes("-topmost", True)

        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"+{(sw-420)//2}+{(sh-380)//2}")

        ctk.CTkLabel(
            dlg, text="Paste OR numbers — one per line:",
            font=ModernTheme.BODY_BOLD,
        ).pack(padx=16, pady=(14, 4), anchor="w")

        txt = ctk.CTkTextbox(dlg, height=260, font=("Courier New", 12))
        txt.pack(fill="both", expand=True, padx=16)

        def apply():
            raw = txt.get("1.0", "end").strip()
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            if not lines:
                messagebox.showwarning("Empty", "No OR numbers entered.", parent=dlg)
                return
            dlg.destroy()
            self._set_or_numbers(lines, label=f"Pasted ({len(lines)} OR numbers)")

        ctk.CTkButton(
            dlg, text="USE THESE OR NUMBERS", command=apply,
            fg_color="#1d4ed8", hover_color="#1e40af",
            height=36, font=ModernTheme.BUTTON_SMALL,
        ).pack(padx=16, pady=10, fill="x")

    def _set_or_numbers(self, or_numbers: list, label: str):
        self._or_numbers = or_numbers
        self._loaded_lbl.configure(text=f"✅  {label}", text_color="#10b981")
        self._preview_btn.configure(state="normal")
        self._delete_btn.configure(state="disabled")
        self._summary_lbl.configure(text="")
        for item in self._tree.get_children():
            self._tree.delete(item)

    # ── Preview ───────────────────────────────────────────────────────────────

    def _load_preview(self):
        if not self._or_numbers:
            return
        self._preview_btn.configure(state="disabled", text="⏳ LOADING...")

        def worker():
            try:
                result = pay_svc.batch_delete_preview(self._or_numbers)
                self.after(0, lambda r=result: self._render_preview(r))
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror("Preview Error", str(err)))
            finally:
                if self.winfo_exists():
                    self.after(0, lambda: self._preview_btn.configure(
                        state="normal", text="🔍  LOAD PREVIEW"
                    ))

        threading.Thread(target=worker, daemon=True).start()

    def _render_preview(self, result: dict):
        for item in self._tree.get_children():
            self._tree.delete(item)

        self._preview_data = result.get("preview", [])
        found       = result.get("found", 0)
        not_found   = result.get("not_found_count", 0)
        not_found_list = result.get("not_found", [])

        for i, p in enumerate(self._preview_data):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self._tree.insert("", "end", tags=(tag,), values=(
                p["payment_id"],
                p["or_number"],
                p["td_number"],
                p["owner_name"],
                p["tax_year"],
                format_curr(p["amount"]),
                format_curr(p["discount"]),
                p["date_paid"] or "—",
            ))

        summary = f"Found: {found}  |  Not found: {not_found}"
        self._summary_lbl.configure(
            text=summary,
            text_color="#10b981" if not_found == 0 else "#f59e0b",
        )

        if not_found_list:
            msg = f"{not_found} OR number(s) not found in the system:\n\n" + "\n".join(not_found_list[:20])
            if not_found > 20:
                msg += f"\n... and {not_found - 20} more"
            messagebox.showwarning("Some OR Numbers Not Found", msg, parent=self)

        if found > 0:
            self._delete_btn.configure(
                state="normal",
                text=f"🗑️  DELETE {found} PAYMENTS",
            )
        else:
            self._delete_btn.configure(state="disabled")

    # ── Delete ────────────────────────────────────────────────────────────────

    def _confirm_and_delete(self):
        if not self._preview_data:
            return

        count = len(self._preview_data)
        payment_ids = [p["payment_id"] for p in self._preview_data]

        # Premium confirmation dialog
        result = tk.BooleanVar(value=False)
        dlg = ctk.CTkToplevel(self)
        dlg.title("")
        dlg.resizable(False, False)
        dlg.overrideredirect(True)
        dlg.attributes("-topmost", True)
        dlg.grab_set()

        dw, dh = 440, 270
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        dlg.geometry(f"{dw}x{dh}+{(sw-dw)//2}+{(sh-dh)//2}")

        outer = ctk.CTkFrame(dlg, fg_color="#0f172a", corner_radius=16,
                             border_width=1, border_color="#1e293b")
        outer.pack(fill="both", expand=True, padx=2, pady=2)
        ctk.CTkFrame(outer, height=5, fg_color="#dc2626", corner_radius=0).pack(fill="x")

        icon_fr = ctk.CTkFrame(outer, width=56, height=56, corner_radius=28,
                               fg_color="#1e293b", border_width=2, border_color="#ef4444")
        icon_fr.pack(pady=(18, 0))
        icon_fr.pack_propagate(False)
        ctk.CTkLabel(icon_fr, text="🗑️", font=("Segoe UI Emoji", 22),
                     text_color="#ef4444").place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(outer, text="Confirm Batch Delete",
                     font=("Inter", 15, "bold"), text_color="#f1f5f9").pack(pady=(10, 2))
        ctk.CTkLabel(outer,
                     text=f"This will permanently delete {count:,} payment records\n"
                          f"and reverse all their billing balances.\nThis cannot be undone.",
                     font=("Inter", 11), text_color="#94a3b8", justify="center").pack()
        ctk.CTkFrame(outer, height=1, fg_color="#1e293b").pack(fill="x", padx=20, pady=(12, 0))

        btn_fr = ctk.CTkFrame(outer, fg_color="transparent")
        btn_fr.pack(pady=12)

        def on_cancel():
            result.set(False)
            dlg.grab_release()
            dlg.destroy()

        def on_confirm():
            result.set(True)
            dlg.grab_release()
            dlg.destroy()

        ctk.CTkButton(btn_fr, text="CANCEL", command=on_cancel,
                      fg_color="#1e293b", hover_color="#334155", text_color="#94a3b8",
                      border_width=1, border_color="#334155",
                      font=("Inter", 12, "bold"), width=130, height=36, corner_radius=8,
                      ).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_fr, text=f"DELETE {count:,} PAYMENTS", command=on_confirm,
                      fg_color="#dc2626", hover_color="#b91c1c", text_color="white",
                      font=("Inter", 12, "bold"), width=180, height=36, corner_radius=8,
                      ).pack(side="left")

        dlg.bind("<Return>", lambda e: on_confirm())
        dlg.bind("<Escape>", lambda e: on_cancel())
        dlg.focus_set()
        dlg.wait_window()

        if not result.get():
            return

        self._delete_btn.configure(state="disabled", text="⏳ DELETING...")

        def do_delete():
            try:
                res = pay_svc.batch_delete_commit(payment_ids)
                self.after(0, lambda r=res: self._show_result(r))
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror("Delete Error", str(err)))
            finally:
                if self.winfo_exists():
                    self.after(0, lambda: self._delete_btn.configure(
                        state="disabled", text="🗑️  DELETE ALL PREVIEWED PAYMENTS"
                    ))

        threading.Thread(target=do_delete, daemon=True).start()

    def _show_result(self, res: dict):
        deleted = res.get("deleted", 0)
        failed  = res.get("failed_count", 0)

        dlg = ctk.CTkToplevel(self)
        dlg.title("")
        dlg.resizable(False, False)
        dlg.overrideredirect(True)
        dlg.attributes("-topmost", True)
        dlg.grab_set()

        dw, dh = 380, 230
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        dlg.geometry(f"{dw}x{dh}+{(sw-dw)//2}+{(sh-dh)//2}")

        color = "#10b981" if failed == 0 else "#f59e0b"
        outer = ctk.CTkFrame(dlg, fg_color="#0f172a", corner_radius=16,
                             border_width=1, border_color="#1e293b")
        outer.pack(fill="both", expand=True, padx=2, pady=2)
        ctk.CTkFrame(outer, height=5, fg_color=color, corner_radius=0).pack(fill="x")

        icon_fr = ctk.CTkFrame(outer, width=52, height=52, corner_radius=26,
                               fg_color="#1e293b", border_width=2, border_color=color)
        icon_fr.pack(pady=(16, 0))
        icon_fr.pack_propagate(False)
        ctk.CTkLabel(icon_fr, text="✓", font=("Inter", 22, "bold"),
                     text_color=color).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(outer, text="Batch Delete Complete",
                     font=("Inter", 14, "bold"), text_color="#f1f5f9").pack(pady=(10, 2))
        ctk.CTkLabel(outer,
                     text=f"Deleted: {deleted:,} payments\nFailed:  {failed:,}",
                     font=("Inter", 11), text_color="#94a3b8", justify="center").pack()
        ctk.CTkFrame(outer, height=1, fg_color="#1e293b").pack(fill="x", padx=20, pady=(10, 0))

        def close():
            dlg.grab_release()
            dlg.destroy()
            self.destroy()

        ctk.CTkButton(outer, text="DONE", command=close,
                      fg_color=color, hover_color="#047857" if failed == 0 else "#d97706",
                      text_color="white", font=("Inter", 12, "bold"),
                      width=120, height=34, corner_radius=8).pack(pady=10)

        dlg.bind("<Return>", lambda e: close())
        dlg.bind("<Escape>", lambda e: close())
        dlg.focus_set()
        dlg.wait_window()
