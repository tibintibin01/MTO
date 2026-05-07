class Theme:
    # Palette
    COLORS = {
        "primary": "#34495e",      # Dark blue-gray
        "secondary": "#2c3e50",    # Deeper blue-gray
        "accent": "#f4d35e",      # Gold/Yellow
        "background": "#f4f1ea",  # Off-white/Cream
        "surface": "#ffffff",      # Pure white
        "surface_light": "#f5f6fa",# Very light gray
        "surface_dark": "#f1f2f6", # Light gray (readonly)
        "success": "#27ae60",      # Green
        "error": "#c0392b",        # Red
        "warning": "#e76f51",      # Orange
        "text_main": "#2c3e50",    # Dark text
        "text_muted": "#7f8c8d",   # Gray text
        "text_on_primary": "#ffffff",# White text on dark bg
        "border": "#d8d2c5",       # Muted border
    }

    # Typography
    FONTS = {
        "h1": ("Georgia", 22, "bold"),
        "h2": ("Segoe UI", 16, "bold"),
        "body": ("Segoe UI", 10, "normal"),
        "body_bold": ("Segoe UI", 10, "bold"),
        "small": ("Segoe UI", 8, "normal"),
    }

    # Spacing
    SPACING = {
        "s": 8,
        "m": 16,
        "l": 24,
        "xl": 32,
    }

    @classmethod
    def get_color(cls, key):
        return cls.COLORS.get(key, "#000000")

    @classmethod
    def get_font(cls, key):
        return cls.FONTS.get(key, cls.FONTS["body"])
