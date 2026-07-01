import customtkinter as ctk
import tkinter as tk
from typing import Any, Optional
from theme_manager import ModernTheme

# Backward compatibility for legacy pages
HoverButton = ctk.CTkButton


class ModernChartWidget:
    def __init__(self, parent, title):
        try:
            import matplotlib

            matplotlib.use("TkAgg")
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

            self.matplotlib = matplotlib
            self.Figure = Figure
            self.FigureCanvasTkAgg = FigureCanvasTkAgg
        except ImportError:
            self.matplotlib = None

        self.card = ctk.CTkFrame(parent, corner_radius=10)

        self.title_label = ctk.CTkLabel(self.card, text=title, font=ModernTheme.H2)
        self.title_label.pack(anchor="w", padx=20, pady=(15, 5))

        self.figure = None
        self.ax = None
        self.canvas = None

        if self.matplotlib:
            # Match the dark theme of CustomTkinter
            bg_color = ModernTheme.CARD_DARK if ctk.get_appearance_mode().lower() == "dark" else ModernTheme.CARD_LIGHT
            self.figure = self.Figure(figsize=(5, 3), dpi=100, facecolor=bg_color)
            self.ax = self.figure.add_subplot(111)
            self.ax.set_facecolor(bg_color)

            self.canvas = self.FigureCanvasTkAgg(self.figure, master=self.card)
            canvas_widget = self.canvas.get_tk_widget()
            canvas_widget.configure(bg=bg_color, highlightthickness=0)
            canvas_widget.pack(fill="both", expand=True, padx=10, pady=(0, 10))

            # Enable hover interaction
            self.canvas.mpl_connect("motion_notify_event", self._on_hover)
            self.annot = self.ax.annotate(
                "",
                xy=(0, 0),
                xytext=(20, 20),
                textcoords="offset points",
                bbox=dict(boxstyle="round", fc="black", ec="white", alpha=0.8),
                arrowprops=dict(arrowstyle="->", color="white"),
                color="white",
                fontweight="bold",
            )
            self.annot.set_visible(False)
        else:
            ctk.CTkLabel(
                self.card, text="Charts unavailable (matplotlib missing)"
            ).pack(expand=True)

    def pack(self, **kwargs):
        self.card.grid(**kwargs) if "row" in kwargs else self.card.pack(**kwargs)

    def draw(
        self,
        x_data,
        y_data,
        chart_type="bar",
        color="#1f538d",
        no_data_msg="No data available",
    ):
        if not self.ax or not self.matplotlib:
            return

        self.ax.clear()
        if not x_data or not y_data:
            self.ax.text(0.5, 0.5, no_data_msg, ha="center", va="center", color="gray")
            self.ax.axis("off")
        else:
            if chart_type == "bar":
                self.ax.bar(x_data, y_data, color=color, width=0.6, edgecolor="white")
            else:
                self.ax.plot(x_data, y_data, color=color, marker="o", linewidth=2)

            self.ax.tick_params(colors="gray", labelsize=8)
            for spine in self.ax.spines.values():
                spine.set_color(ModernTheme.BORDER_DARK if ctk.get_appearance_mode().lower() == "dark" else ModernTheme.BORDER_LIGHT)
            self.ax.grid(True, axis="y", alpha=0.05)

            # ── Format Y-axis as peso values — no scientific notation ─────────
            import matplotlib.ticker as mticker

            max_val = max(y_data) if y_data else 0
            if max_val >= 1_000_000:
                # Show as "₱1.2M"
                self.ax.yaxis.set_major_formatter(
                    mticker.FuncFormatter(lambda x, _: f"₱{x/1_000_000:.1f}M")
                )
            elif max_val >= 1_000:
                # Show as "₱12,500"
                self.ax.yaxis.set_major_formatter(
                    mticker.FuncFormatter(lambda x, _: f"₱{x:,.0f}")
                )
            else:
                self.ax.yaxis.set_major_formatter(
                    mticker.FuncFormatter(lambda x, _: f"₱{x:.0f}")
                )
            # Prevent matplotlib from using offset/scientific notation
            self.ax.ticklabel_format(style="plain", axis="y")

        self.figure.tight_layout()
        self.canvas.draw()

    def _on_hover(self, event):
        vis = self.annot.get_visible()
        if event.inaxes == self.ax:
            for container in self.ax.containers:  # For bar charts
                for bar in container:
                    cont, ind = bar.contains(event)
                    if cont:
                        self._update_annot(bar, bar.get_height())
                        self.annot.set_visible(True)
                        self.canvas.draw_idle()
                        return

            # For line charts (check lines)
            for line in self.ax.get_lines():
                cont, ind = line.contains(event)
                if cont:
                    x, y = line.get_data()
                    idx = ind["ind"][0]
                    self._update_annot_point(x[idx], y[idx])
                    self.annot.set_visible(True)
                    self.canvas.draw_idle()
                    return

        if vis:
            self.annot.set_visible(False)
            self.canvas.draw_idle()

    def _update_annot(self, bar, val):
        x = bar.get_x() + bar.get_width() / 2
        y = bar.get_height()
        self.annot.xy = (x, y)
        self.annot.set_text(f"P {val:,.2f}")

    def _update_annot_point(self, x, y):
        self.annot.xy = (x, y)
        self.annot.set_text(f"P {y:,.2f}")


class ToastNotification(ctk.CTkToplevel):
    def __init__(self, master, message, color="#2ecc71", duration=3000):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=color)

        self.message = message
        self.duration = duration

        # Position at bottom right
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = screen_width - 320
        y = screen_height - 120
        self.geometry(f"300x70+{x}+{y}")
        self.attributes("-alpha", 0.0) # Start transparent for animation
        
        self.label = ctk.CTkLabel(
            self,
            text=self.message,
            font=ModernTheme.BODY,
            text_color="white",
            wraplength=280,
        )
        self.label.pack(expand=True, padx=10, pady=10)

        # Fade out and destroy (if not sticky)
        if self.duration > 0:
            self.after(self.duration, self.fade_out)
        else:
            # Sticky: destroy on click
            self.bind("<Button-1>", lambda e: self.destroy())
            self.label.bind("<Button-1>", lambda e: self.destroy())

        self.animate_in()

    def animate_in(self):
        alpha = self.attributes("-alpha")
        if alpha < 1.0:
            alpha += 0.2
            self.attributes("-alpha", alpha)
            self.after(20, self.animate_in)

    def fade_out(self):
        alpha = self.attributes("-alpha")
        if alpha > 0:
            alpha -= 0.1
            self.attributes("-alpha", alpha)
            self.after(50, self.fade_out)
        else:
            self.destroy()


def show_toast(master, message, type="info", duration=None, sticky=False):
    """
    Shows a premium toast notification.
    duration: ms to show (overrides default). If 0 or sticky=True, stays until clicked.
    """
    from utils import ConfigManager
    colors = {
        "info": "#3498db",
        "success": "#2ecc71",
        "error": "#e74c3c",
        "warning": "#f39c12",
    }
    
    if duration is None:
        duration = ConfigManager.get("toast_duration", 3000)
    
    if sticky or type == "error":
        duration = 0
        message = f"📌 {message}"

    # Centralized UI thread safety
    master.after(
        0, lambda: ToastNotification(master, message, colors.get(type, "#3498db"), duration=duration)
    )

class ErrorDialog(ctk.CTkToplevel):
    def __init__(self, master, title, message, retry_callback=None):
        super().__init__(master)
        self.title(title)
        self.geometry("400x200")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.grab_set() # Modal behavior
        
        # Center in parent
        self.update_idletasks()
        pw = master.winfo_width()
        ph = master.winfo_height()
        px = master.winfo_rootx()
        py = master.winfo_rooty()
        x = px + (pw // 2) - 200
        y = py + (ph // 2) - 100
        self.geometry(f"+{x}+{y}")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header with icon-ish label
        header = ctk.CTkLabel(self, text="⚠️", font=("Segoe UI", 32))
        header.grid(row=0, column=0, pady=(20, 0))

        msg_label = ctk.CTkLabel(self, text=message, font=ModernTheme.BODY, wraplength=350)
        msg_label.grid(row=1, column=0, padx=20, pady=10)

        btn_fr = ctk.CTkFrame(self, fg_color="transparent")
        btn_fr.grid(row=2, column=0, pady=20)

        if retry_callback:
            from utils import tr
            self.retry_btn = ctk.CTkButton(btn_fr, text=tr("common.retry"), command=lambda: [self.destroy(), retry_callback()])
            self.retry_btn.pack(side="left", padx=10)
        
        from utils import tr
        self.ok_btn = ctk.CTkButton(btn_fr, text=tr("common.ok"), command=self.destroy, fg_color="transparent", border_width=1)
        self.ok_btn.pack(side="left", padx=10)

class ModernProgressBar(ctk.CTkFrame):
    def __init__(self, master, title="Operation in Progress...", **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        
        self.lbl = ctk.CTkLabel(self, text=title, font=ModernTheme.BODY_BOLD)
        self.lbl.grid(row=0, column=0, padx=20, pady=(15, 5), sticky="w")
        
        self.pbar = ctk.CTkProgressBar(self, height=12, corner_radius=6)
        self.pbar.grid(row=1, column=0, padx=20, pady=(0, 5), sticky="ew")
        self.pbar.set(0)
        
        self.status_lbl = ctk.CTkLabel(self, text="Preparing...", font=ModernTheme.BODY_SMALL, text_color="gray")
        self.status_lbl.grid(row=2, column=0, padx=20, pady=(0, 15), sticky="w")

    def update_progress(self, percentage, message):
        self.pbar.set(percentage / 100)
        self.status_lbl.configure(text=message)

class ProgressOverlay(ctk.CTkToplevel):
    def __init__(self, master, title="System Task"):
        super().__init__(master)
        self.title(title)
        self.geometry("450x180")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.overrideredirect(True) # Borderless premium feel
        
        # Center
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() // 2) - 225
        y = master.winfo_rooty() + (master.winfo_height() // 2) - 90
        self.geometry(f"+{x}+{y}")
        
        self.configure(fg_color=ModernTheme.SECONDARY)
        
        self.inner = ctk.CTkFrame(self, fg_color="transparent")
        self.inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        self.progress_widget = ModernProgressBar(self.inner, title=title, fg_color=ModernTheme.CARD_DARK)
        self.progress_widget.pack(fill="both", expand=True)
        
    def update(self, percentage, message):
        self.progress_widget.update_progress(percentage, message)
        if percentage >= 100:
            self.after(1500, self.destroy)

class LoadingOverlay(ctk.CTkToplevel):
    def __init__(self, master, message="Loading...", **kwargs):
        super().__init__(master)
        
        # Premium Floating Window
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        
        # Card Styling
        card_bg = "#1e1e1e" if ctk.get_appearance_mode().lower() == "dark" else "#f0f0f0"
        self.configure(fg_color=card_bg)
        
        # Center relative to master
        self.update_idletasks()
        width, height = 350, 120
        
        # Try to get master coordinates, fallback to screen center
        try:
            mx = master.winfo_rootx()
            my = master.winfo_rooty()
            mw = master.winfo_width()
            mh = master.winfo_height()
            x = mx + (mw // 2) - (width // 2)
            y = my + (mh // 2) - (height // 2)
        except:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = (sw // 2) - (width // 2)
            y = (sh // 2) - (height // 2)
            
        self.geometry(f"{width}x{height}+{x}+{y}")
        
        # Border Frame
        self.border_fr = ctk.CTkFrame(
            self, 
            fg_color="transparent", 
            corner_radius=12, 
            border_width=2, 
            border_color=ModernTheme.PRIMARY
        )
        self.border_fr.pack(fill="both", expand=True)
        
        self.inner = ctk.CTkFrame(self.border_fr, fg_color="transparent")
        self.inner.place(relx=0.5, rely=0.5, anchor="center")
        
        self.lbl = ctk.CTkLabel(self.inner, text=message, font=ModernTheme.BODY_BOLD)
        self.lbl.pack(pady=(0, 15))
        
        self.progress = ctk.CTkProgressBar(self.inner, mode="indeterminate", width=250, height=8)
        self.progress.pack()
        self.progress.start()
        
    def hide(self):
        self.destroy()

class SyncBadge(ctk.CTkFrame):
    """Real-time status indicator for the offline sync queue."""
    def __init__(self, master, command=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.command = command
        self.label = ctk.CTkLabel(
            self, 
            text="● Synced", 
            font=ModernTheme.BODY_SMALL,
            text_color="#2ecc71",
            cursor="hand2"
        )
        self.label.pack(side="left", padx=5)
        
        # Make the whole frame and label clickable
        self.bind("<Button-1>", lambda e: self._on_click())
        self.label.bind("<Button-1>", lambda e: self._on_click())
        
        # Internal state
        self.last_count = 0
        self.is_syncing = False

    def _on_click(self):
        if self.command:
            self.command()

    def update_status(self, count, is_syncing):
        self.last_count = count
        self.is_syncing = is_syncing
        
        # Thread-safe UI update
        self.after(0, self._perform_update)

    def _perform_update(self):
        if self.is_syncing:
            self.label.configure(text=f"🔄 Syncing...", text_color="#f39c12")
        elif self.last_count > 0:
            self.label.configure(text=f"● {self.last_count} Pending", text_color="#f39c12")
        else:
            self.label.configure(text="● Synced", text_color="#2ecc71")


def attach_autocomplete(entry: ctk.CTkEntry, values: list, variable: tk.StringVar):
    """
    Attaches autocomplete behaviour to an EXISTING CTkEntry.
    No wrapper frame — works safely inside CTkScrollableFrame.

    Usage:
        var = tk.StringVar()
        entry = ctk.CTkEntry(parent, textvariable=var, height=40)
        entry.pack(fill="x", padx=10)
        attach_autocomplete(entry, values=BARANGAY_LIST, variable=var)

    Behaviour:
        - Typing filters the list (prefix first, then contains, case-insensitive)
        - ↓ arrow moves focus into the dropdown
        - Enter / Tab selects the highlighted item
        - Escape closes without selecting
        - Click selects
        - On blur: auto-completes if only one match remains
    """
    _state = {"win": None, "lb": None}

    def _close():
        if _state["win"]:
            try:
                _state["win"].destroy()
            except Exception:
                pass
        _state["win"] = None
        _state["lb"] = None

    def _open(items):
        _close()
        entry.update_idletasks()
        x = entry.winfo_rootx()
        y = entry.winfo_rooty() + entry.winfo_height()
        w = entry.winfo_width()
        h = min(len(items), 8) * 28

        win = tk.Toplevel(entry)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.configure(bg="#1e293b")

        lb = tk.Listbox(
            win, font=("Inter", 11),
            bg="#1e293b", fg="#cbd5e1",
            selectbackground="#1d4ed8", selectforeground="#ffffff",
            activestyle="none", borderwidth=0,
            highlightthickness=1, highlightcolor="#334155", relief="flat",
        )
        lb.pack(fill="both", expand=True)
        for item in items:
            lb.insert(tk.END, item)

        def on_select(e=None):
            sel = lb.curselection()
            if sel:
                val = lb.get(sel[0])
                traces = variable.trace_info()
                if traces:
                    variable.trace_remove("write", traces[0][1])
                variable.set(val)
                variable.trace_add("write", on_type)
            _close()
            entry.focus_set()

        lb.bind("<ButtonRelease-1>", on_select)
        lb.bind("<Return>",          on_select)
        lb.bind("<Tab>",             on_select)
        lb.bind("<Escape>",          lambda e: _close())
        lb.bind("<FocusOut>",        lambda e: entry.after(150, _close))
        win.bind("<FocusOut>",       lambda e: entry.after(150, _close))

        _state["win"] = win
        _state["lb"] = lb

    def on_type(*_):
        term = variable.get().strip().upper()
        if not term:
            _close()
            return
        # A complete valid value needs no suggestion popup. Keeping the
        # duplicate dropdown open here covered the next field in edit forms.
        if any(v.strip().upper() == term for v in values):
            _close()
            return
        prefix   = [v for v in values if v.upper().startswith(term)]
        contains = [v for v in values if not v.upper().startswith(term) and term in v.upper()]
        matches = prefix + contains
        if matches:
            _open(matches)
        else:
            _close()

    def on_focus_out(e=None):
        entry.after(150, auto_complete_blur)

    def auto_complete_blur():
        term = variable.get().strip().upper()
        matches = [v for v in values if v.upper().startswith(term)]
        if len(matches) == 1:
            traces = variable.trace_info()
            if traces:
                variable.trace_remove("write", traces[0][1])
            variable.set(matches[0])
            variable.trace_add("write", on_type)
        _close()

    def on_down(e=None):
        lb = _state["lb"]
        if lb and lb.size() > 0:
            lb.focus_set()
            lb.selection_set(0)
            lb.activate(0)

    def on_tab(e=None):
        lb = _state["lb"]
        if lb and lb.size() > 0:
            lb.selection_set(0)
            sel = lb.curselection()
            if sel:
                val = lb.get(sel[0])
                traces = variable.trace_info()
                if traces:
                    variable.trace_remove("write", traces[0][1])
                variable.set(val)
                variable.trace_add("write", on_type)
            _close()
            entry.focus_set()

    variable.trace_add("write", on_type)
    entry.bind("<Down>",     on_down)
    entry.bind("<Escape>",   lambda e: _close())
    entry.bind("<FocusOut>", on_focus_out)
    entry.bind("<Tab>",      on_tab)


# Keep the class name as an alias so existing imports don't break,
# but it now just wraps a plain CTkEntry + attach_autocomplete.
class AutocompleteComboBox(ctk.CTkFrame):
    """Thin shim — use attach_autocomplete() directly for new code."""
    def __init__(self, parent, values, variable=None, height=40,
                 placeholder="Type to search...", **kwargs):
        super().__init__(parent, fg_color="transparent", height=height, **kwargs)
        self.pack_propagate(False)
        self._var = variable or tk.StringVar()
        self._entry = ctk.CTkEntry(self, textvariable=self._var,
                                   height=height, placeholder_text=placeholder)
        self._entry.place(relx=0, rely=0, relwidth=1, relheight=1)
        attach_autocomplete(self._entry, values, self._var)

    def get(self): return self._var.get()
    def set(self, v): self._var.set(v)
    def bind(self, seq, func, add=None): self._entry.bind(seq, func, add)
