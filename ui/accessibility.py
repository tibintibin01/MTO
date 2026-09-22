"""Shared desktop accessibility helpers.

CustomTkinter renders buttons through an internal canvas, so its controls do
not automatically participate in the Windows tab order.  This module provides
one tested adapter for keyboard activation and visible focus, plus small WCAG
contrast utilities used by the Phase 8 release gate.
"""

from __future__ import annotations

from typing import Any, Callable

MINIMUM_NORMAL_TEXT_CONTRAST = 4.5
MINIMUM_LARGE_TEXT_CONTRAST = 3.0


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = str(hex_color).strip().lstrip("#")
    if len(value) != 6:
        raise ValueError("color must use six-digit hexadecimal notation")
    try:
        return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError as exc:
        raise ValueError("color must use six-digit hexadecimal notation") from exc


def _linear_channel(channel: int) -> float:
    normalized = channel / 255.0
    if normalized <= 0.04045:
        return normalized / 12.92
    return ((normalized + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """Return WCAG relative luminance for a six-digit RGB color."""
    red, green, blue = (_linear_channel(value) for value in _rgb(hex_color))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    """Return the WCAG contrast ratio for two opaque RGB colors."""
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def bind_keyboard_activation(
    widget: Any,
    command: Callable[[], Any],
    *,
    focus_color: str = "#FDE047",
) -> Any:
    """Put a CustomTkinter button in tab order with Enter/Space activation."""
    focus_target = getattr(widget, "_canvas", widget)
    original_border_width = getattr(widget, "_border_width", 0)
    original_border_color = getattr(widget, "_border_color", focus_color)

    def invoke(_event=None):
        if str(getattr(widget, "_state", "normal")).lower() != "disabled":
            command()
        return "break"

    def show_focus(_event=None):
        widget.configure(border_width=2, border_color=focus_color)

    def hide_focus(_event=None):
        widget.configure(
            border_width=original_border_width,
            border_color=original_border_color,
        )

    focus_target.configure(takefocus=True)
    focus_target.bind("<Return>", invoke, add="+")
    focus_target.bind("<space>", invoke, add="+")
    focus_target.bind("<FocusIn>", show_focus, add="+")
    focus_target.bind("<FocusOut>", hide_focus, add="+")
    return focus_target
