import customtkinter as ctk

class ModernTheme:
    """
    Premium Design System for MTO Treasury.
    Uses 'Midnight Slate' palette for professional, low-strain interfaces.
    """
    # --- CORE BRANDING ---
    PRIMARY = "#38bdf8"        # Sky Blue
    PRIMARY_HOVER = "#0ea5e9"
    ACCENT = "#8b5cf6"         # Violet
    
    # --- SEMANTIC STATES ---
    SUCCESS = "#10b981"        # Emerald
    DANGER = "#ef4444"         # Rose
    WARNING = "#f59e0b"        # Amber
    INFO = "#3b82f6"           # Blue
    
    # --- NEUTRAL PALETTE (Light) ---
    BG_LIGHT = "#f8fafc"
    CARD_LIGHT = "#ffffff"
    TEXT_MAIN_LIGHT = "#1e293b"
    TEXT_SUB_LIGHT = "#64748b"
    BORDER_LIGHT = "#e2e8f0"
    
    # --- NEUTRAL PALETTE (Dark / Midnight Slate) ---
    BG_DARK = "#0f172a"
    CARD_DARK = "#1e293b"
    TEXT_MAIN_DARK = "#f1f5f9"
    TEXT_SUB_DARK = "#94a3b8"
    BORDER_DARK = "#334155"

    # --- TYPOGRAPHY ---
    FONT_FAMILY = "Inter" # Fallback to Segoe UI if Inter is missing
    H1 = ("Inter", 32, "bold")
    H2 = ("Inter", 24, "bold")
    H3 = ("Inter", 18, "bold")
    BODY = ("Inter", 13)
    BODY_BOLD = ("Inter", 13, "bold")
    BODY_SMALL = ("Inter", 11)

def setup_theme(mode=None):
    """
    Initializes the application visual environment.
    If mode is None, it defaults to the system setting.
    """
    if mode:
        ctk.set_appearance_mode(mode)
    else:
        ctk.set_appearance_mode("system")
        
    ctk.set_default_color_theme("blue") # We use our own variables, but blue is a safe base

def get_colors(mode=None):
    """Returns a dictionary of current theme colors."""
    current_mode = mode or ctk.get_appearance_mode().lower()
    if current_mode == "dark":
        return {
            "bg": ModernTheme.BG_DARK,
            "card": ModernTheme.CARD_DARK,
            "text": ModernTheme.TEXT_MAIN_DARK,
            "subtext": ModernTheme.TEXT_SUB_DARK,
            "border": ModernTheme.BORDER_DARK,
            "accent": ModernTheme.PRIMARY
        }
    else:
        return {
            "bg": ModernTheme.BG_LIGHT,
            "card": ModernTheme.CARD_LIGHT,
            "text": ModernTheme.TEXT_MAIN_LIGHT,
            "subtext": ModernTheme.TEXT_SUB_LIGHT,
            "border": ModernTheme.BORDER_LIGHT,
            "accent": ModernTheme.PRIMARY
        }
