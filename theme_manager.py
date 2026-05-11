import customtkinter as ctk

class ModernTheme:
    # --- Color Palette ---
    PRIMARY = "#1f538d"
    PRIMARY_HOVER = "#1a4575"
    SECONDARY = "#2c3e50"
    SUCCESS = "#27ae60"
    DANGER = "#e74c3c"
    WARNING = "#f39c12"
    TEXT_LIGHT = "#ecf0f1"
    TEXT_DARK = "#2c3e50"
    TEXT_GRAY = "#7f8c8d"
    
    BG_CARD_LIGHT = "#ffffff"
    BG_CARD_DARK = "#2b2b2b"
    BORDER_LIGHT = "#e0e0e0"
    BORDER_DARK = "#333333"

    # --- Typography ---
    FONT_FAMILY = "Segoe UI"
    H1 = (FONT_FAMILY, 28, "bold")
    H2 = (FONT_FAMILY, 20, "bold")
    H3 = (FONT_FAMILY, 16, "bold")
    BODY = (FONT_FAMILY, 13)
    BODY_SMALL = (FONT_FAMILY, 11)
    BUTTON = (FONT_FAMILY, 13, "bold")

def setup_theme(mode="dark"):
    """
    Standardizes the application theme. 
    mode: "dark", "light", or "system"
    """
    ctk.set_appearance_mode(mode)
    ctk.set_default_color_theme("blue")
