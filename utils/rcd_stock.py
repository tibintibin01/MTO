"""Report-only physical OR stock, explicitly reviewed against the office log.

Cancelled/spoiled forms consume an unused serial, but never create collection
cash, a cancelled Payment, destruction evidence or relief of accountability.
"""

from datetime import date

from utils.rcd_booklets import booklet_range, receipt_serial
from utils.rcd_metadata import _report_text

CAPACITY = 6


def _identifier(value):
    if type(value) is not int or value <= 0:
        raise ValueError("Select a registered booklet, not a typed or inferred ID.")
    return value


def _text(value, label, limit):
    result = _report_text(value, label, limit)
    if not result:
        raise ValueError(f"Enter the actual {label.lower()}.")
    return result


def _segments(numbers, book):
    """Never bridge a missing serial or a booklet boundary."""
    result = []
    for serial in sorted(numbers):
        printed = f"{book['prefix']}{serial:0{book['width']}d}"
        if result and result[-1]["end"] + 1 == serial:
            result[-1].update(to_or=printed, end=serial)
            result[-1]["count"] += 1
        else:
            result.append(
                {"from_or": printed, "to_or": printed, "end": serial, "count": 1}
            )
    return result


def build_stock_review(payload, details):
    """Compute opening + received - paid - recorded cancelled = unused ending.

    The official-log opening list is a human declaration, not reconstructed
    from payment history. The server separately checks it against known usage.
    """
    if not isinstance(details, dict) or set(details) != {
        "confirmed",
        "register_reference",
        "opening_ranges",
        "received_booklet_ids",
        "cancelled",
    }:
        raise ValueError("Complete the receipt-stock review fields.")
    if details["confirmed"] is not True:
        raise ValueError(
            "Confirm all unused stock and cancelled ORs against the office log."
        )
    if payload.get("issues"):
        raise ValueError(
            "Resolve daily receipt findings before reviewing physical stock."
        )
    reference = _text(details["register_reference"], "Stock register reference", 160)
    day = date.fromisoformat(payload["report_date"])
    books = {}
    for item in payload.get("stock_booklets", []):
        prefix, first, last, width = booklet_range(item["first_or"], item["last_or"])
        identity = _identifier(item["id"])
        if identity in books or item["collector_id"] != payload["collector"]["id"]:
            raise ValueError("Reload the officer's registered booklet list.")
        books[identity] = {
            **item,
            "prefix": prefix,
            "first": first,
            "last": last,
            "width": width,
            "issued": date.fromisoformat(item["issued_on"]),
        }
    opening = details["opening_ranges"]
    received = details["received_booklet_ids"]
    cancelled = details["cancelled"]
    if (
        not isinstance(opening, list)
        or not isinstance(received, list)
        or not isinstance(cancelled, list)
        or len(opening) > CAPACITY
        or len(received) > CAPACITY
        or len(cancelled) > 50 * CAPACITY
    ):
        raise ValueError(
            "Stock exceeds the exact six-row form; review continuation needs."
        )
    states = {}

    def state(identity):
        identity = _identifier(identity)
        if identity not in books or books[identity]["issued"] > day:
            raise ValueError(
                "Stock must belong to this officer and be issued by the OR date."
            )
        if identity not in states:
            states[identity] = {key: set() for key in ("opening", "received", "issued")}
        return states[identity]

    normalized_opening = []
    for entry in opening:
        if not isinstance(entry, dict) or set(entry) != {
            "booklet_id",
            "from_or",
            "to_or",
        }:
            raise ValueError(
                "Each opening range needs a booklet and its actual unused bounds."
            )
        identity = _identifier(entry["booklet_id"])
        stock = state(identity)
        book = books[identity]
        a, b = receipt_serial(entry["from_or"]), receipt_serial(entry["to_or"])
        if (
            book["issued"] >= day
            or a[0] != book["prefix"]
            or b[0] != book["prefix"]
            or not book["first"] <= a[1] <= b[1] <= book["last"]
        ):
            raise ValueError(
                "Opening stock must be unused forms received before this OR date, within the actual booklet."
            )
        serials = set(range(a[1], b[1] + 1))
        if serials & stock["opening"]:
            raise ValueError(
                "Opening stock ranges overlap; no serial can be counted twice."
            )
        stock["opening"].update(serials)
        normalized_opening.append(
            {
                "booklet_id": identity,
                "from_or": f"{book['prefix']}{a[1]:0{book['width']}d}",
                "to_or": f"{book['prefix']}{b[1]:0{book['width']}d}",
            }
        )
    normalized_received = []
    for identity in received:
        stock = state(identity)
        book = books[identity]
        if book["issued"] != day or stock["received"] or stock["opening"]:
            raise ValueError(
                "Received stock must be one newly issued, full 50-OR booklet on this OR date, listed once."
            )
        stock["received"].update(range(book["first"], book["last"] + 1))
        normalized_received.append(identity)
    if len(states) > CAPACITY:
        raise ValueError("The exact office form fits at most six stock booklets.")
    available, paid = {}, set()
    for identity, stock in states.items():
        for serial in stock["opening"] | stock["received"]:
            key = (books[identity]["prefix"], serial)
            if key in available:
                raise ValueError(
                    "Registered stock overlaps; reload the booklet register."
                )
            available[key] = identity
    for receipt in payload["receipts"]:
        key = receipt_serial(receipt["or_number"])[:2]
        if key in paid or key not in available:
            raise ValueError(
                "Every recorded OR must appear once in the reviewed opening/received stock."
            )
        identity = available[key]
        if receipt.get("booklet_id") != identity:
            raise ValueError(
                "A recorded OR and its stock booklet do not match; reload the preview."
            )
        paid.add(key)
        states[identity]["issued"].add(key[1])
    normalized_cancelled, cancelled_keys = [], set()
    for entry in cancelled:
        if not isinstance(entry, dict) or set(entry) != {
            "or_number",
            "status",
            "reason",
            "reference",
            "copies_retained",
        }:
            raise ValueError(
                "Cancelled/spoiled ORs need their identity, reason, log reference and retained-copy confirmation."
            )
        key = receipt_serial(entry["or_number"])[:2]
        if key in paid:
            raise ValueError(
                "A collected OR cannot also be cancelled/spoiled. No payment was changed."
            )
        if key in cancelled_keys or key not in available:
            raise ValueError(
                "Cancelled/spoiled ORs must be unused available serials, listed only once."
            )
        if (
            entry["status"] not in ("CANCELLED", "SPOILED")
            or entry["copies_retained"] is not True
        ):
            raise ValueError(
                "Confirm the actual cancelled/spoiled status and retained original/duplicate copies."
            )
        identity = available[key]
        book = books[identity]
        normalized_cancelled.append(
            {
                "or_number": f"{key[0]}{key[1]:0{book['width']}d}",
                "status": entry["status"],
                "reason": _text(entry["reason"], "Cancellation/spoilage reason", 240),
                "reference": _text(
                    entry["reference"], "Cancellation register reference", 160
                ),
                "copies_retained": True,
            }
        )
        cancelled_keys.add(key)
        states[identity]["issued"].add(key[1])
    rows, totals = [], {key: 0 for key in ("opening", "received", "issued", "ending")}
    for identity, stock in sorted(states.items()):
        stock["ending"] = (stock["opening"] | stock["received"]) - stock["issued"]
        for key, numbers in stock.items():
            totals[key] += len(numbers)
        # Pair at most one issued run and one ending run per contiguous opening
        # subrange. Independently lining up the nth run in each column can make
        # the overall total correct while individual printed rows do not balance.
        buckets, seen_phases, previous, last_phase = [], set(), None, None
        for serial in sorted(stock["opening"] | stock["received"]):
            phase = "issued" if serial in stock["issued"] else "ending"
            if (
                previous is None
                or previous + 1 != serial
                or (phase != last_phase and phase in seen_phases)
            ):
                buckets.append(set())
                seen_phases = set()
            buckets[-1].add(serial)
            seen_phases.add(phase)
            previous, last_phase = serial, phase
        for bucket in buckets:
            sections = {
                key: _segments(numbers & bucket, books[identity])
                for key, numbers in stock.items()
            }
            rows.append(
                {
                    "booklet_id": identity,
                    "form_type": books[identity]["form_type"],
                    **{
                        key: items[0] if items else None
                        for key, items in sections.items()
                    },
                }
            )
    if len(rows) > CAPACITY:
        raise ValueError(
            "Stock gaps need more than six rows. No range was stretched or omitted; review continuation needs."
        )
    return {
        "details": {
            "confirmed": True,
            "register_reference": reference,
            "opening_ranges": sorted(
                normalized_opening,
                key=lambda r: (r["booklet_id"], receipt_serial(r["from_or"])[1]),
            ),
            "received_booklet_ids": sorted(normalized_received),
            "cancelled": sorted(
                normalized_cancelled, key=lambda r: receipt_serial(r["or_number"])[:2]
            ),
        },
        "rows": rows,
        "totals": {**totals, "paid": len(paid), "cancelled": len(cancelled_keys)},
        "available_identities": sorted(available),
        "cancelled_identities": sorted(cancelled_keys),
    }
