import customtkinter as ctk
from theme_manager import ModernTheme

class SystemHelpPage:
    def __init__(self, parent, user):
        self.container = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header with bright color
        ctk.CTkLabel(
            self.container,
            text="Municipal Revenue System Help Guide",
            font=ModernTheme.H1,
            text_color="#3498db",
        ).pack(anchor="w", pady=(0, 20))

        help_text = [
            (
                "🏠 Dashboard",
                "View real-time revenue collection charts and protection status.",
            ),
            (
                "📋 Property Records",
                "Search, edit, or delete property assessments. Use the 'Export' button to save to Excel.",
            ),
            (
                "🏦 Unified Ledger",
                "View all payment history. Use 'View Receipt' to open a PDF copy.",
            ),
            (
                "⌨️ Keyboard Shortcuts",
                "Ctrl + F: Quick Search / Command Palette\nCtrl + P: Open Command Palette\nCtrl + E: Export visible table data to Excel/CSV",
            ),
            (
                "🛡️ Data Protection",
                "The 'Restore Test' on the dashboard verifies that your backups are 100% healthy and ready for disaster recovery.",
            ),
            (
                "💼 Audit Trail",
                "Administrators can view all changes made to any record in the System Settings > Audit Logs tab.",
            ),
        ]

        for title, desc in help_text:
            # Card-like frame for each help item
            f = ctk.CTkFrame(
                self.container, fg_color=("#ebebeb", "#262626"), corner_radius=10
            )
            f.pack(fill="x", pady=8, padx=5)

            ctk.CTkLabel(f, text=title, font=ModernTheme.H3, text_color="#3498db").pack(
                anchor="w", padx=15, pady=(10, 2)
            )
            ctk.CTkLabel(
                f,
                text=desc,
                font=ModernTheme.BODY,
                text_color=("#333333", "#cccccc"),
                wraplength=800,
                justify="left",
            ).pack(anchor="w", padx=20, pady=(0, 15))
