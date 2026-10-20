"""Exact receipt-series parsing; never strip arbitrary characters or round ranges."""

import re


def receipt_serial(value):
    value = str(value or "").strip()
    match = re.fullmatch(r"([A-Za-z0-9 /-]*[A-Za-z /-])?([0-9]{1,15})", value)
    if not match or len(value) > 80 or len(match[1] or "") > 64:
        raise ValueError(
            "Use the exact OR prefix followed by its numeric serial (at most 15 digits)."
        )
    return (match[1] or "").upper(), int(match[2]), len(match[2])


def booklet_range(first_or, last_or):
    prefix, start, width = receipt_serial(first_or)
    last_prefix, end, last_width = receipt_serial(last_or)
    if prefix != last_prefix or width != last_width or end - start != 49:
        raise ValueError(
            "A booklet must contain exactly 50 consecutive ORs with the same prefix and serial width."
        )
    return prefix, start, end, width
