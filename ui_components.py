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
            bg_color = "#2b2b2b"  # Default CTK dark frame color
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

            self.ax.tick_params(colors="white", labelsize=8)
            for spine in self.ax.spines.values():
                spine.set_color("#444444")
            self.ax.grid(True, axis="y", alpha=0.1)

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

        # Position at bottom right
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = screen_width - 320
        y = screen_height - 100
        self.geometry(f"300x60+{x}+{y}")

        self.label = ctk.CTkLabel(
            self,
            text=message,
            font=ModernTheme.BODY,
            text_color="white",
            wraplength=280,
        )
        self.label.pack(expand=True, padx=10, pady=10)

        # Fade out and destroy
        self.after(duration, self.fade_out)

    def fade_out(self):
        alpha = self.attributes("-alpha")
        if alpha > 0:
            alpha -= 0.1
            self.attributes("-alpha", alpha)
            self.after(50, self.fade_out)
        else:
            self.destroy()


def show_toast(master, message, type="info"):
    colors = {
        "info": "#3498db",
        "success": "#2ecc71",
        "error": "#e74c3c",
        "warning": "#f39c12",
    }
    # Centralized UI thread safety: ensure windows are only created in the main thread
    master.after(
        0, lambda: ToastNotification(master, message, colors.get(type, "#3498db"))
    )
