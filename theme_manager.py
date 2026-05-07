import customtkinter as ctk

# --- Color Palette ---
PRIMARY = "#1f538d"
SECONDARY = "#2c3e50"
SUCCESS = "#27ae60"
DANGER = "#e74c3c"
BG_DARK = "#1a1a1a"
BG_LIGHT = "#f5f6fa"

def setup_theme():
    ctk.set_appearance_mode("dark")  # "System" (standard), "Dark", "Light"
    ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

class ModernTheme:
    FONT_FAMILY = "Segoe UI"
    H1 = ("Segoe UI", 24, "bold")
    H2 = ("Segoe UI", 18, "bold")
    BODY = ("Segoe UI", 13)
    BUTTON = ("Segoe UI", 13, "bold")
