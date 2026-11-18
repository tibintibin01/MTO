"""In-app status, field feedback, and confirmations for the record workflows."""

import re
from dataclasses import dataclass

import customtkinter as ctk

from api_clients.api_helper import ApiResponseError
from theme_manager import ModernTheme
from ui.accessibility import bind_keyboard_activation

# Background and accent pairs in CustomTkinter's light/dark order.
PALETTES = {
    "success": (("#ecfdf5", "#102c25"), ("#166534", "#86efac"), "✓"),
    "warning": (("#fffbeb", "#342817"), ("#854d0e", "#fde68a"), "!"),
    "error": (("#fef2f2", "#381d25"), ("#991b1b", "#fecaca"), "!"),
}


@dataclass(frozen=True)
class SaveFeedback:
    level: str
    title: str
    detail: str
    field: str = ""
    duplicate_id: int | None = None
    uncertain: bool = False


@dataclass(frozen=True)
class SavedRecord:
    title: str
    detail: str
    property_id: int | None
    td_number: str


_VALIDATION_FIELDS = {
    "td_number",
    "owner_name",
    "pin",
    "lot_number",
    "area",
    "location",
    "kind_of_property",
    "prev_td_number",
    "effectivity_date",
    "assessed_value",
    "prior_assessed_value",
    "prior_effectivity_year",
    "or_number",
    "or_date",
    "tax_year",
    "amount_paid",
    "penalty",
    "discount",
    "remarks",
}
_FIELD_ALIASES = {
    "previous_td_number": "prev_td_number",
    "barangay": "location",
}


def save_failure_feedback(error, *, payment):
    """Do not infer that a write failed from a missing or ambiguous response."""
    title = "Payment not saved" if payment else "Property not updated"
    if str(error) == "Your session has expired. Please log in again.":
        return SaveFeedback(
            "error", title, "Your session expired. Sign in again before submitting."
        )
    if isinstance(error, ApiResponseError):
        status = error.status_code
        detail = error.detail.strip() if isinstance(error.detail, str) else ""
        lower = detail.lower()
        if status == 409:
            if payment and lower.startswith(
                (
                    "payment already exists for or ",
                    "this official receipt is already recorded for ",
                )
            ):
                match = re.search(r"\(payment ID ([1-9][0-9]{0,18})\)", detail)
                return SaveFeedback(
                    "warning",
                    "Payment already recorded",
                    "This official receipt is already on file for this account and tax year. "
                    "No new payment was saved. Review the existing entry before making changes.",
                    duplicate_id=int(match.group(1)) if match else None,
                )
            if not payment and lower.startswith("this property was changed after"):
                return SaveFeedback(
                    "warning",
                    "Property changed since you opened it",
                    "Your edits are still here. Review the current property before re-entering your changes.",
                )
            # An idempotency conflict can refer to a prior in-flight or completed write.
            if "idempotency" not in lower and "financial operation" not in lower:
                field = (
                    "td_number"
                    if not payment
                    and (
                        lower.startswith("td number is already used")
                        or "active property account(s) already use td" in lower
                    )
                    else ""
                )
                return SaveFeedback(
                    "warning",
                    title,
                    detail[:700] or "Review the record before saving again.",
                    field,
                )
        elif status in (400, 422):
            field = ""
            for item in error.errors if isinstance(error.errors, list) else ():
                loc = item.get("loc") if isinstance(item, dict) else None
                if isinstance(loc, (tuple, list)) and len(loc) > 1 and loc[0] == "body":
                    key = str(loc[1]).lower().replace(" ", "_")
                    key = _FIELD_ALIASES.get(key, key)
                    if key in _VALIDATION_FIELDS:
                        return SaveFeedback(
                            "error",
                            title,
                            "Check the value and format for this field.",
                            key,
                        )
            for prefix, key in (
                ("effectivity must", "effectivity_date"),
                ("a valid official receipt date", "or_date"),
                ("enter a valid official receipt number", "or_number"),
                ("a posted payment must", "amount_paid"),
            ):
                if lower.startswith(prefix):
                    field = key
                    break
            return SaveFeedback(
                "error",
                title,
                detail[:700] or "Check the highlighted or required details.",
                field,
            )
        elif status in (401, 403, 404, 429):
            return SaveFeedback(
                "error",
                title,
                {
                    401: "Your session was not accepted. Sign in again before submitting.",
                    403: "Your account does not have permission to save this change.",
                    404: "This record could not be found. Review the current records before continuing.",
                    429: "The server received too many requests. Wait before trying again.",
                }[status],
            )

    where = "the ledger for this receipt" if payment else "the current property record"
    return SaveFeedback(
        "warning",
        "Save not confirmed",
        f"Your entries are still here. Check {where} before trying again. Do not submit a second entry to check.",
        uncertain=True,
    )


class OperationBanner(ctk.CTkFrame):
    """An initially hidden status card that never grabs focus or auto-hides."""

    def __init__(self, parent, *, before, padx=0, wraplength=475):
        super().__init__(parent, corner_radius=8, border_width=1)
        self._pack_options = dict(before=before, fill="x", padx=padx, pady=(0, 8))
        self._action = None
        self.title = ctk.CTkLabel(self, font=("Segoe UI", 13, "bold"), anchor="w")
        self.title.pack(side="top", fill="x", padx=12, pady=(6, 0))
        self.detail = ctk.CTkLabel(
            self, wraplength=wraplength, justify="left", anchor="w"
        )
        self.detail.pack(side="top", fill="x", padx=12, pady=(0, 6))
        self._buttons = ctk.CTkFrame(self, fg_color="transparent")
        self._action_btn = ctk.CTkButton(
            self._buttons, height=28, command=self.invoke_action
        )
        self._action_btn.pack(side="left", padx=(0, 8))
        self.action_focus = bind_keyboard_activation(
            self._action_btn, self.invoke_action
        )
        self._dismiss_btn = ctk.CTkButton(
            self._buttons, text="Dismiss", height=28, width=70, command=self.clear
        )
        bind_keyboard_activation(self._dismiss_btn, self.clear)

    @property
    def has_action(self):
        return self._action is not None

    def invoke_action(self):
        if self._action is not None:
            self._action()

    def show(self, level, title, detail, *, action=None, dismissible=False):
        background, accent, icon = PALETTES[level]
        self.configure(fg_color=background, border_color=accent)
        self.title.configure(text=f"{icon}  {title}", text_color=accent)
        self.detail.configure(text=detail, text_color=accent)
        self._action = action[1] if action else None
        if action:
            self._action_btn.configure(text=action[0], state="normal")
            self._action_btn.pack(side="left", padx=(0, 8))
        else:
            self._action_btn.pack_forget()
        if dismissible:
            self._dismiss_btn.pack(side="left")
        else:
            self._dismiss_btn.pack_forget()
        if action or dismissible:
            self._buttons.pack(anchor="w", padx=12, pady=(0, 8))
        else:
            self._buttons.pack_forget()
        self.pack(**self._pack_options)

    def clear(self):
        self._action = None
        self.pack_forget()


def confirm_action(parent, title, detail, *, action, destructive=False):
    """The title bar, Escape, and initial Enter all take the safe Cancel path."""
    parent = parent.winfo_toplevel()
    previous_grab = parent.grab_current()
    previous_focus = parent.focus_get()
    dialog = ctk.CTkToplevel(parent)
    dialog.withdraw()
    dialog.title(title)
    dialog.transient(parent)
    dialog.attributes("-topmost", bool(parent.attributes("-topmost")))
    dialog.resizable(False, False)
    dialog.configure(fg_color=(ModernTheme.BG_LIGHT, ModernTheme.BG_DARK))
    accepted = False

    def close(choice=False):
        nonlocal accepted
        accepted = choice
        dialog.destroy()
        return "break"

    ctk.CTkLabel(
        dialog,
        text=title,
        font=("Segoe UI", 18, "bold"),
        wraplength=425,
        justify="left",
    ).pack(anchor="w", padx=20, pady=(16, 4))
    ctk.CTkLabel(dialog, text=detail, wraplength=425, justify="left").pack(
        anchor="w", padx=20, pady=(0, 12)
    )
    buttons = ctk.CTkFrame(dialog, fg_color="transparent")
    buttons.pack(anchor="e", padx=20, pady=(0, 16))
    cancel = ctk.CTkButton(buttons, text="Cancel", command=close, fg_color="#475569")
    cancel.pack(side="left", padx=(0, 8))
    colors = dict(fg_color="#b91c1c", hover_color="#991b1b") if destructive else {}
    proceed = ctk.CTkButton(buttons, text=action, command=lambda: close(True), **colors)
    proceed.pack(side="left")
    cancel_focus = bind_keyboard_activation(cancel, close)
    proceed_focus = bind_keyboard_activation(proceed, lambda: close(True))
    for current, other in (
        (cancel_focus, proceed_focus),
        (proceed_focus, cancel_focus),
    ):

        def move_focus(_event, target=other):
            target.focus_set()
            return "break"

        current.bind("<Tab>", move_focus)
        current.bind("<Shift-Tab>", move_focus)

    dialog.protocol("WM_DELETE_WINDOW", close)
    dialog.bind("<Escape>", lambda _event: close())
    dialog.bind("<Return>", lambda _event: close())
    dialog.update_idletasks()
    x = parent.winfo_rootx() + max(
        0, (parent.winfo_width() - dialog.winfo_reqwidth()) // 2
    )
    y = parent.winfo_rooty() + max(
        0, (parent.winfo_height() - dialog.winfo_reqheight()) // 2
    )
    dialog.geometry(f"+{x}+{y}")
    dialog.deiconify()
    try:
        dialog.wait_visibility()
        dialog.grab_set()
        cancel_focus.focus_set()
        parent.wait_window(dialog)
    finally:
        if previous_grab is not None and previous_grab.winfo_exists():
            previous_grab.grab_set()
        if previous_focus is not None and previous_focus.winfo_exists():
            previous_focus.focus_set()
    return accepted
