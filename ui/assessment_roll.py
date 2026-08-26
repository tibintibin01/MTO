import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from theme_manager import ModernTheme
from utils import tr
from ui_components import LoadingOverlay
import api_clients.property_service as prop_svc
import api_clients.api_helper as api
import api_clients.billing_service as billing
import shutil
import os
from ui.dossier import PropertyDossierModal
from ui.import_wizard import ImportWizardModal
import threading


def parse_assessment_roll_as_of_year(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    if not raw.isdigit() or len(raw) != 4:
        raise ValueError("As of Year must be a four-digit year, such as 2026.")
    year = int(raw)
    if year < 1900 or year > 2200:
        raise ValueError("As of Year must be between 1900 and 2200.")
    return year


def assessment_roll_export_dialog_options(path, export_format):
    """Build a save dialog that matches the export button the user selected."""
    formats = {
        "pdf": (".pdf", "PDF document (*.pdf)", "*.pdf"),
        "excel": (".xlsx", "Excel workbook (*.xlsx)", "*.xlsx"),
    }
    try:
        extension, label, pattern = formats[str(export_format).strip().lower()]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported Assessment Roll export: {export_format}"
        ) from exc

    source_name = os.path.basename(path)
    stem = os.path.splitext(source_name)[0] or "Assessment_Roll"
    return {
        "title": f"Save Assessment Roll as {label.split(' (', 1)[0]}",
        "initialfile": f"{stem}{extension}",
        "defaultextension": extension,
        "filetypes": [(label, pattern)],
    }


class AssessmentRollPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.page_cursors = [None]
        self.current_page = 0
        self.page_size = 50
        self.is_loading = False
        self.all_loaded = False
        self._refresh_generation = 0
        self.barangays = [
            "NORTH POBLACION",
            "SOUTH POBLACION",
            "BAYABAS",
            "BORLONGAN",
            "BUENAVISTA",
            "CALAOCAN",
            "DIAMANEN",
            "DIANED",
            "DIARABASIN",
            "DIBUTUNAN",
            "DIMABUNO",
            "DINADIAWAN",
            "DITALE",
            "GUPA",
            "IPIL",
            "LABOY",
            "LIPIT",
            "LOBBOT",
            "MALIGAYA",
            "MIJARES",
            "MUCDOL",
            "PUANGI",
            "SALAY",
            "SAPANGKAWAYAN",
            "TOYTOYAN",
        ]
        self.search_timer = None
        self.setup_ui()
        # Keep table clear initially for performance (Search-First logic)

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        header = ctk.CTkFrame(self.container, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))

        title_fr = ctk.CTkFrame(header, fg_color="transparent")
        title_fr.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            title_fr,
            text="ASSESSMENT ROLL",
            font=ModernTheme.H2,
            text_color=(ModernTheme.TEXT_MAIN_LIGHT, ModernTheme.TEXT_MAIN_DARK),
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_fr,
            text="Active property assessments and valuation history",
            font=ModernTheme.BODY_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(anchor="w", pady=(2, 0))

        filters_fr = ctk.CTkFrame(
            self.container,
            fg_color=(ModernTheme.CARD_LIGHT, ModernTheme.CARD_DARK),
            corner_radius=8,
            border_width=1,
            border_color=(ModernTheme.BORDER_LIGHT, ModernTheme.BORDER_DARK),
        )
        filters_fr.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            filters_fr,
            text="FIND PROPERTY",
            font=ModernTheme.BUTTON_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(side="left", padx=(14, 7), pady=10)
        self.search_ent = ctk.CTkEntry(
            filters_fr,
            placeholder_text="Search PIN, TD, Former TD, or Owner...",
            width=330,
            height=34,
            font=ModernTheme.BODY_SMALL,
        )
        self.search_ent.pack(side="left", pady=10)
        self.search_ent.bind("<Return>", lambda e: self.refresh_table())
        self.search_ent.bind("<KP_Enter>", lambda e: self.refresh_table())

        ctk.CTkLabel(
            filters_fr,
            text="BARANGAY",
            font=ModernTheme.BUTTON_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(side="left", padx=(16, 7), pady=10)
        self.brgy_var = tk.StringVar(value="ALL")
        self.brgy_cb = ctk.CTkComboBox(
            filters_fr,
            values=["ALL"] + sorted(self.barangays),
            variable=self.brgy_var,
            width=190,
            height=34,
            font=ModernTheme.BODY_SMALL,
        )
        self.brgy_cb.pack(side="left", pady=10)
        self.brgy_cb.configure(command=lambda e: self.refresh_table())
        self.brgy_cb.bind("<Return>", lambda e: self.refresh_table())
        self.brgy_cb.bind("<KP_Enter>", lambda e: self.refresh_table())

        ctk.CTkLabel(
            filters_fr,
            text="AS OF YEAR",
            font=ModernTheme.BUTTON_SMALL,
            text_color=ModernTheme.TEXT_GRAY,
        ).pack(side="left", padx=(16, 7), pady=10)
        self.as_of_year_ent = ctk.CTkEntry(
            filters_fr,
            width=90,
            height=34,
            placeholder_text="YYYY",
            font=ModernTheme.BODY_SMALL,
        )
        self.as_of_year_ent.pack(side="left", pady=10)
        self.as_of_year_ent.bind("<Return>", lambda e: self.refresh_table())
        self.as_of_year_ent.bind("<KP_Enter>", lambda e: self.refresh_table())

        ctk.CTkButton(
            filters_fr,
            text="REFRESH",
            command=self.refresh_table,
            width=105,
            height=34,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.PRIMARY,
            hover_color=ModernTheme.PRIMARY_HOVER,
        ).pack(side="left", padx=(12, 8), pady=10)

        ctk.CTkButton(
            filters_fr,
            text="BULK IMPORT",
            command=self.open_import_wizard,
            fg_color=ModernTheme.SECONDARY,
            hover_color=ModernTheme.SECONDARY_HOVER,
            width=125,
            height=34,
            font=ModernTheme.BUTTON_SMALL,
        ).pack(side="right", padx=12, pady=10)

        self._pdf_btn = ctk.CTkButton(
            header,
            text="EXPORT PDF",
            command=self._export_roll_pdf,
            fg_color=ModernTheme.DANGER,
            width=125,
            height=34,
            font=ModernTheme.BUTTON_SMALL,
        )
        self._pdf_btn.pack(side="right", padx=(8, 0))

        self._excel_btn = ctk.CTkButton(
            header,
            text="EXPORT EXCEL",
            command=self._export_roll_excel,
            fg_color=ModernTheme.SUCCESS,
            width=135,
            height=34,
            font=ModernTheme.BUTTON_SMALL,
        )
        self._excel_btn.pack(side="right")

        table_fr = ctk.CTkFrame(
            self.container,
            fg_color="#0f172a",
            corner_radius=8,
            border_width=1,
            border_color=ModernTheme.BORDER_DARK,
        )
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Roll.Treeview",
            rowheight=34,
            font=("Inter", 11),
            background="#0f172a",
            fieldbackground="#0f172a",
            foreground="#e2e8f0",
            borderwidth=0,
            bordercolor="#334155",
            lightcolor="#334155",
            darkcolor="#334155",
            relief="flat",
        )
        style.configure(
            "Roll.Treeview.Heading",
            font=("Inter", 10, "bold"),
            background="#334155",
            foreground="#f8fafc",
            borderwidth=0,
            bordercolor="#475569",
            lightcolor="#475569",
            darkcolor="#475569",
            relief="flat",
            padding=(8, 8),
        )
        style.map(
            "Roll.Treeview",
            background=[("selected", "#0284c7")],
            foreground=[("selected", "#ffffff")],
        )
        style.map("Roll.Treeview.Heading", background=[("active", "#475569")])
        for scrollbar_style in (
            "Roll.Vertical.TScrollbar",
            "Roll.Horizontal.TScrollbar",
        ):
            style.configure(
                scrollbar_style,
                gripcount=0,
                background="#475569",
                darkcolor="#475569",
                lightcolor="#475569",
                troughcolor="#0f172a",
                bordercolor="#0f172a",
                arrowcolor="#cbd5e1",
                relief="flat",
            )

        self.cols = (
            "ID",
            "TD NO.",
            "PIN",
            "LOT & BLK",
            "PROPERTY OWNER",
            "LOCATION",
            "CLASSIFICATION",
            "ASSESSED VALUE",
            "PREVIOUS TD",
            "EFFECTIVITY",
        )
        tree_host = tk.Frame(table_fr, bg="#0f172a", bd=0, highlightthickness=0)
        tree_host.pack(fill="both", expand=True, padx=1, pady=1)
        self.tree = ttk.Treeview(
            tree_host, columns=self.cols, show="headings", style="Roll.Treeview"
        )

        # Column Config
        col_widths = {
            "ID": 0,
            "TD NO.": 110,
            "PIN": 130,
            "LOT & BLK": 100,
            "PROPERTY OWNER": 200,
            "LOCATION": 130,
            "CLASSIFICATION": 120,
            "ASSESSED VALUE": 120,
            "PREVIOUS TD": 110,
            "EFFECTIVITY": 100,
        }

        for col in self.cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center", width=col_widths.get(col, 100))

        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.column("PROPERTY OWNER", anchor="w")
        self.tree.column("LOCATION", anchor="center")

        scrolly = ttk.Scrollbar(
            tree_host,
            orient="vertical",
            command=self.tree.yview,
            style="Roll.Vertical.TScrollbar",
        )
        scrollx = ttk.Scrollbar(
            tree_host,
            orient="horizontal",
            command=self.tree.xview,
            style="Roll.Horizontal.TScrollbar",
        )
        self.tree.configure(yscrollcommand=scrolly.set, xscrollcommand=scrollx.set)

        # Zebra Tags
        self.tree.tag_configure("oddrow", background="#162032", foreground="#e2e8f0")
        self.tree.tag_configure("evenrow", background="#1e293b", foreground="#f8fafc")

        scrolly.pack(side="right", fill="y")
        scrollx.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)

        # --- PAGINATION BAR ---
        self.pag_fr = ctk.CTkFrame(
            self.container,
            fg_color=(ModernTheme.CARD_LIGHT, ModernTheme.CARD_DARK),
            corner_radius=8,
            border_width=1,
            border_color=(ModernTheme.BORDER_LIGHT, ModernTheme.BORDER_DARK),
        )
        self.pag_fr.pack(side="bottom", fill="x", pady=(8, 0))

        self.prev_btn = ctk.CTkButton(
            self.pag_fr,
            text="PREVIOUS",
            command=self.prev_page,
            width=110,
            height=32,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SECONDARY,
            hover_color=ModernTheme.SECONDARY_HOVER,
        )
        self.prev_btn.pack(side="left", padx=10, pady=8)

        self.page_lbl = ctk.CTkLabel(
            self.pag_fr,
            text="Page 1",
            font=("Inter", 11, "bold"),
            text_color=ModernTheme.TEXT_GRAY,
        )
        self.page_lbl.pack(side="left", expand=True)

        self.next_btn = ctk.CTkButton(
            self.pag_fr,
            text="NEXT",
            command=self.next_page,
            width=110,
            height=32,
            font=ModernTheme.BUTTON_SMALL,
            fg_color=ModernTheme.SECONDARY,
            hover_color=ModernTheme.SECONDARY_HOVER,
        )
        self.next_btn.pack(side="right", padx=10, pady=8)

        table_fr.pack(fill="both", expand=True)  # Pack expanding table LAST

        self.tree.bind("<Double-1>", lambda e: self.open_dossier())

    def _is_current_refresh(self, generation):
        return generation == self._refresh_generation

    def refresh_table(self, reset_page=True):
        try:
            as_of_year = parse_assessment_roll_as_of_year(self.as_of_year_ent.get())
        except ValueError as exc:
            messagebox.showerror("Invalid As of Year", str(exc))
            return

        term = self.search_ent.get().strip()
        brgy = self.brgy_var.get()

        if reset_page:
            self.page_cursors = [None]
            self.current_page = 0
            self.all_loaded = False

        page_index = self.current_page
        cursor_to_use = self.page_cursors[page_index]
        self._refresh_generation += 1
        request_generation = self._refresh_generation
        self.is_loading = True
        overlay = LoadingOverlay(self.container, "Loading Assessment Roll...")

        def apply_response(response):
            if not self._is_current_refresh(request_generation):
                return

            results = response.get("items", [])
            next_cursor = response.get("next_cursor")
            has_more = bool(response.get("has_more"))

            if len(self.page_cursors) <= page_index + 1:
                self.page_cursors.append(next_cursor)
            else:
                self.page_cursors[page_index + 1] = next_cursor

            self.all_loaded = not has_more
            self._update_table(results, has_more=has_more)

        def show_error(error):
            if self._is_current_refresh(request_generation):
                messagebox.showerror("Error", str(error))

        def finish_request():
            overlay.hide()
            if self._is_current_refresh(request_generation):
                self.is_loading = False

        def worker():
            try:
                response = prop_svc.search_properties(
                    term,
                    limit=self.page_size,
                    cursor=cursor_to_use,
                    barangay=brgy if brgy != "ALL" else None,
                    as_of_year=as_of_year,
                )
                self.container.after(
                    0, lambda response=response: apply_response(response)
                )
            except Exception as exc:
                self.container.after(0, lambda error=exc: show_error(error))
            finally:
                self.container.after(0, finish_request)

        threading.Thread(target=worker, daemon=True).start()

    def next_page(self):
        if not self.all_loaded:
            self.current_page += 1
            self.refresh_table(reset_page=False)

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.all_loaded = False
            self.refresh_table(reset_page=False)

    def _update_table(self, results, has_more=None):
        self.page_lbl.configure(text=f"PAGE {self.current_page + 1}")
        self.prev_btn.configure(state="normal" if self.current_page > 0 else "disabled")

        if has_more is None:
            has_more = len(results) >= self.page_size
        self.all_loaded = not has_more
        self.next_btn.configure(state="normal" if has_more else "disabled")

        if not results and self.current_page == 0:
            for item in self.tree.get_children():
                self.tree.delete(item)
            return

        # Always clear table for true page-by-page pagination
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Get current row count for zebra tagging
        current_count = len(self.tree.get_children())

        for i, r in enumerate(results):
            # Indices from backend search_properties:
            # 0:id, 1:td, 2:owner, 4:lot, 6:loc, 7:kind, 9:av, 18:pin, 19:blk, 20:prev, 21:eff, 22:brgy
            td = r[1]
            pin = r[18] if len(r) > 18 else ""
            lot_blk = f"{r[4]} / {r[19]}" if len(r) > 19 and r[19] else str(r[4])
            owner = r[2]
            loc = r[22] if len(r) > 22 and r[22] else r[6]  # Barangay or Location
            kind = r[7]
            av = f"{r[9]:,.2f}"
            prev = r[20] if len(r) > 20 else ""
            eff = r[21] if len(r) > 21 else ""

            # If it's a full date string like 2023-01-01, just show the year
            if eff and len(str(eff)) >= 4:
                eff = str(eff)[:4]

            tag = "evenrow" if (current_count + i) % 2 == 0 else "oddrow"
            self.tree.insert(
                "",
                "end",
                values=(r[0], td, pin, lot_blk, owner, loc, kind, av, prev, eff),
                tags=(tag,),
            )

    def open_import_wizard(self):
        ImportWizardModal(self.container.winfo_toplevel(), mode="assessment")

    def _show_import_summary(self, res):
        if "error" in res:
            messagebox.showerror("Import Failed", res["error"])
            return

        msg = f"✅ Import Complete!\n\nInserted: {res['inserted']}\nUpdated: {res['updated']}\nFailed: {res['failed']}"
        if res["errors"]:
            msg += f"\n\nFirst 5 Errors:\n" + "\n".join(res["errors"][:5])

        messagebox.showinfo("Import Summary", msg)
        self.refresh_table()

    def open_dossier(self):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0])["values"]
        property_id = int(vals[0]) if vals else None
        td_number = str(vals[1]).strip() if len(vals) > 1 else ""

        if not td_number:
            messagebox.showwarning(
                "Dossier Error", "This property record is missing a TD Number."
            )
            return

        # 1. Create a subtle loading overlay
        loading = ctk.CTkToplevel(self.parent)
        loading.overrideredirect(True)
        loading.geometry("300x100")
        loading.attributes("-topmost", True)

        # Center
        sw, sh = loading.winfo_screenwidth(), loading.winfo_screenheight()
        loading.geometry(f"+{(sw-300)//2}+{(sh-100)//2}")

        ctk.CTkLabel(
            loading,
            text="📂 FETCHING PROPERTY DOSSIER...",
            font=("Segoe UI", 12, "bold"),
            text_color="#1f538d",
        ).pack(expand=True)
        loading.update()

        def worker():
            try:
                # Use centralized API helper
                data = prop_svc.get_property_dossier(property_id)
                self.container.after(
                    0,
                    lambda: [
                        loading.destroy(),
                        PropertyDossierModal(self.parent, data),
                    ],
                )
            except Exception as e:
                self.container.after(
                    0,
                    lambda e=e: [
                        loading.destroy(),
                        messagebox.showerror("Dossier Error", str(e)),
                    ],
                )

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _open_file(path):
        """Open a file with the default OS application after saving."""
        try:
            import subprocess, sys

            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.call(["open", path])
            else:
                subprocess.call(["xdg-open", path])
        except Exception:
            pass

    def _export_with_feedback(self, btn, worker_fn, export_format):
        """Run worker_fn in a thread; show progress on btn, then open the result."""
        original_text = btn.cget("text")
        btn.configure(text="⏳ Generating...", state="disabled")

        def _run():
            try:
                path = worker_fn()

                # Ask where to save
                def _save():
                    dialog_options = assessment_roll_export_dialog_options(
                        path, export_format
                    )
                    dest = filedialog.asksaveasfilename(**dialog_options)
                    if dest:
                        shutil.copy2(path, dest)
                        if messagebox.askyesno(
                            "Export Successful",
                            f"Assessment roll saved to:\n{dest}\n\nOpen it now?",
                        ):
                            self._open_file(dest)
                    btn.configure(text=original_text, state="normal")

                self.container.after(0, _save)
            except Exception as exc:
                self.container.after(
                    0,
                    lambda e=exc: (
                        messagebox.showerror("Export Failed", str(e)),
                        btn.configure(text=original_text, state="normal"),
                    ),
                )

        threading.Thread(target=_run, daemon=True).start()

    def _export_roll_pdf(self):
        brgy = self.brgy_var.get()
        try:
            as_of_year = parse_assessment_roll_as_of_year(self.as_of_year_ent.get())
        except ValueError as exc:
            messagebox.showerror("Invalid As of Year", str(exc))
            return

        self._export_with_feedback(
            self._pdf_btn,
            lambda: billing.download_assessment_roll_pdf(
                barangay=brgy if brgy != "ALL" else None,
                as_of_year=as_of_year,
            ),
            "pdf",
        )

    def _export_roll_excel(self):
        brgy = self.brgy_var.get()
        try:
            as_of_year = parse_assessment_roll_as_of_year(self.as_of_year_ent.get())
        except ValueError as exc:
            messagebox.showerror("Invalid As of Year", str(exc))
            return

        self._export_with_feedback(
            self._excel_btn,
            lambda: billing.export_report_excel(
                "assessment_roll",
                barangay=brgy if brgy != "ALL" else None,
                as_of_year=as_of_year,
            ),
            "excel",
        )
