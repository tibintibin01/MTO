"""Reusable, non-modal guidance for report and registry views with no rows."""

import customtkinter as ctk


class EmptyTableState:
    """Center an empty-result message over a table without replacing its headers."""

    def __init__(self, parent, message, title="No records to display"):
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(
            self.frame, text="⌕", font=("Inter", 48), text_color="#64748b"
        ).pack(pady=(0, 5))
        self.title = ctk.CTkLabel(
            self.frame, text=title, font=("Inter", 14, "bold"), text_color="#f8fafc"
        )
        self.title.pack()
        self.message = ctk.CTkLabel(
            self.frame, text=message, font=("Inter", 11), text_color="#94a3b8",
            wraplength=520, justify="center",
        )
        self.message.pack(pady=(8, 0))
        self.show()

    def show(self, message=None, title="No records to display"):
        self.title.configure(text=title)
        if message is not None:
            self.message.configure(text=message)
        self.frame.place(relx=0.5, rely=0.54, anchor="center")
        self.frame.tkraise()

    def hide(self):
        self.frame.place_forget()


def show_empty_content(parent, message, title="No records to display"):
    """Show the same guidance in report panels that do not contain a table."""
    panel = ctk.CTkFrame(parent, fg_color="transparent")
    panel.pack(fill="both", expand=True)
    ctk.CTkLabel(
        panel, text="⌕", font=("Inter", 48), text_color="#64748b"
    ).pack(pady=(50, 5))
    ctk.CTkLabel(
        panel, text=title, font=("Inter", 14, "bold"), text_color="#f8fafc"
    ).pack()
    ctk.CTkLabel(
        panel, text=message, font=("Inter", 11), text_color="#94a3b8",
        wraplength=520, justify="center",
    ).pack(pady=(8, 0))
    return panel
