"""Operator-reviewed RCD instrument/remittance metadata, never payment edits."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json

from utils.rcd_booklets import receipt_serial
from utils.rcd_stock import build_stock_review
from utils.rcd_metadata import (
    _report_text,
    philippine_report_date,
    resolve_rcd_metadata,
)

CENT = Decimal("0.01")
MAX_MONEY = Decimal("999999999999.99")


def _amount(value, label, *, optional=False):
    if optional and (value is None or value == ""):
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > MAX_MONEY:
            raise ValueError()
        rounded = number.quantize(CENT)
        if rounded != number:
            raise ValueError()
        return rounded
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(
            f"{label} must be a nonnegative amount with at most two decimals."
        ) from None


def build_remittance_review(
    payload, details, *, today=None, allow_incomplete_checks=False
):
    """Reconcile entered checks to the current physical-OR snapshot.

    Unlisted receipt amounts become cash only after an explicit instrument
    confirmation. Full handover is a separate operator declaration, never a
    bank deposit or the receiving officer's acknowledgment.
    """
    allowed = {
        "cash_check_confirmed",
        "checks",
        "opening_100",
        "opening_200",
        "full_handover_confirmed",
        "receiving_officer",
        "handover_date",
        "planned_deposit_date",
        "stock",
    }
    if not isinstance(details, dict) or set(details) - allowed:
        raise ValueError("Unsupported RCD review fields.")
    if payload.get("issues"):
        raise ValueError(
            "Resolve the receipt/booklet findings before reviewing remittance."
        )
    if details.get("cash_check_confirmed") is not True:
        raise ValueError(
            "Confirm the cash/check breakdown against the actual receipts first."
        )
    handed = details.get("full_handover_confirmed", False)
    if not isinstance(handed, bool):
        raise ValueError("Full handover confirmation must be true or false.")
    day = resolve_rcd_metadata(report_date=payload["report_date"]).report_date
    planned = details.get("planned_deposit_date")
    planned = (
        resolve_rcd_metadata(report_date=planned).report_date
        if planned
        else day + timedelta(days=1)
    )
    if planned < day:
        raise ValueError("The planned deposit date cannot precede the OR date.")
    recipient = _report_text(
        details.get("receiving_officer", ""), "Receiving officer", 120
    )
    handover = details.get("handover_date")
    if handed:
        if not recipient or not handover:
            raise ValueError(
                "Enter the actual receiving officer and full-handover date."
            )
        handover = resolve_rcd_metadata(report_date=handover).report_date
        if not day <= handover <= (today or philippine_report_date()):
            raise ValueError(
                "The actual handover date must be between the OR date and today."
            )
    elif recipient or handover:
        raise ValueError(
            "Unconfirmed handover must not contain an actual receiving officer/date."
        )
    openings = {
        fund: _amount(
            details.get("opening_" + fund),
            f"Fund {fund} opening balance",
            optional=True,
        )
        for fund in ("100", "200")
    }
    receipts = {receipt_serial(r["or_number"])[:2]: r for r in payload["receipts"]}
    if len(receipts) != len(payload["receipts"]):
        raise ValueError("The preview has duplicate physical OR identities; reload it.")
    for receipt in receipts.values():
        if _amount(receipt["basic_cash"], "Recorded Basic portion") + _amount(
            receipt["sef_cash"], "Recorded SEF portion"
        ) != _amount(receipt["cash"], "Recorded receipt amount"):
            raise ValueError(
                "The receipt's fund portions do not reconcile; reload the preview."
            )
    for key in ("basic_cash", "sef_cash", "cash"):
        if sum(
            (_amount(r[key], "Recorded receipt amount") for r in receipts.values()),
            Decimal(0),
        ) != _amount(payload["totals"][key], "Recorded daily total"):
            raise ValueError("The daily preview totals do not reconcile; reload it.")
    legs = details.get("checks", [])
    if not isinstance(legs, list) or len(legs) > 200:
        raise ValueError("Enter at most 200 check-to-OR allocations.")
    groups, seen, used, cumulative_basic, normalized_legs = {}, set(), {}, {}, []
    for entry in legs:
        if not isinstance(entry, dict) or set(entry) != {
            "or_number",
            "bank",
            "check_number",
            "payee",
            "amount",
            "face_amount",
        }:
            raise ValueError(
                "Each check needs its OR, bank, check number, payee, whole amount and allocated amount."
            )
        key = receipt_serial(entry["or_number"])[:2]
        if key not in receipts:
            raise ValueError(
                "A listed check does not belong to an OR in this daily preview."
            )
        receipt = receipts[key]
        bank = _report_text(entry["bank"], "Check bank", 80)
        number = _report_text(entry["check_number"], "Check number", 40)
        payee = _report_text(entry["payee"], "Check payee", 120)
        if not bank or not number or not payee:
            raise ValueError("Enter the actual bank, check number and payee.")
        identity = (bank.casefold(), number.casefold())
        if (key, identity) in seen:
            raise ValueError("The same check-to-OR allocation was entered twice.")
        seen.add((key, identity))
        amount = _amount(entry["amount"], "Allocated check amount")
        face = _amount(entry["face_amount"], "Whole check amount")
        if amount == 0:
            raise ValueError("An allocated check amount must be positive.")
        cash = _amount(receipt["cash"], "Recorded receipt amount")
        basic = _amount(receipt["basic_cash"], "Recorded Basic portion")
        used[key] = used.get(key, Decimal(0)) + amount
        if used[key] > cash:
            raise ValueError(
                "Checks exceed the recorded amount of their OR. No payment was changed."
            )
        # Cumulative rounding keeps every cent assigned once, even for several
        # checks on one OR, mixed cash/check and unequal Basic/SEF portions.
        assigned_basic = (used[key] * basic / cash).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
        basic_part = assigned_basic - cumulative_basic.get(key, Decimal(0))
        cumulative_basic[key] = assigned_basic
        group = groups.setdefault(
            identity,
            {
                "bank": bank,
                "check_number": number,
                "payee": payee,
                "face_amount": face,
                "100": Decimal(0),
                "200": Decimal(0),
            },
        )
        if (
            group["payee"].casefold() != payee.casefold()
            or group["face_amount"] != face
        ):
            raise ValueError(
                "One check has inconsistent payee or whole-amount details."
            )
        group["100"] += basic_part
        group["200"] += amount - basic_part
        normalized_legs.append(
            {
                "or_number": receipt["or_number"],
                "bank": bank,
                "check_number": number,
                "payee": payee,
                "amount": str(amount),
                "face_amount": str(face),
            }
        )
    for group in groups.values():
        allocated = group["100"] + group["200"]
        if allocated > group["face_amount"] or (
            not allow_incomplete_checks and allocated != group["face_amount"]
        ):
            raise ValueError(
                "A check's OR allocations do not match its whole amount. Review cross-date/officer or non-RPT collections; no amount was guessed."
            )
    if len(groups) > 9:
        raise ValueError(
            "The exact office form fits nine checks. No check was omitted; review continuation needs."
        )
    funds = {}
    for fund, total_key in (("100", "basic_cash"), ("200", "sef_cash")):
        total = _amount(payload["totals"][total_key], "Recorded fund total")
        checks = sum((r[fund] for r in groups.values()), Decimal(0)).quantize(CENT)
        if checks > total:
            raise ValueError("The check/fund breakdown does not reconcile.")
        opening = openings[fund]
        funds[fund] = {
            "cash": str(total - checks),
            "checks": str(checks),
            "collections": str(total),
            "opening": str(opening) if opening is not None else None,
            "total_accountability": (
                str(opening + total) if opening is not None else None
            ),
            "remitted": str(total) if handed else None,
            "closing": str(opening) if handed and opening is not None else None,
        }
    normalized = {
        "cash_check_confirmed": True,
        "checks": normalized_legs,
        "opening_100": funds["100"]["opening"],
        "opening_200": funds["200"]["opening"],
        "full_handover_confirmed": handed,
        "receiving_officer": recipient,
        "handover_date": handover.isoformat() if handed else None,
        "planned_deposit_date": planned.isoformat(),
    }
    stock = None
    if "stock" in details:
        stock = build_stock_review(payload, details["stock"])
        normalized["stock"] = stock["details"]
    signature = hashlib.sha256(
        json.dumps(
            {"source": payload["source_signature"], "review": normalized},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "details": normalized,
        "funds": funds,
        "stock": stock,
        "checks": [
            {
                **g,
                "face_amount": str(g["face_amount"]),
                "100": str(g["100"].quantize(CENT)),
                "200": str(g["200"].quantize(CENT)),
            }
            for g in groups.values()
        ],
        "review_signature": signature,
    }
