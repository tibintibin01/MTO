"""Read-only, account-specific Tax Bill discovery, independent of compliance."""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models import Property


def search_tax_bill_properties(
    search: str, limit=50, cursor=None, db_session: Session = None
):
    """Include unbilled/future declarations; never infer a target from a TD alone.

    Stable ID order is deliberate: the general property's fuzzy relevance order
    is not compatible with ID-cursor paging. No payment or billing join belongs
    here, and this result is not a statement of tax-year eligibility/compliance.
    """
    term = str(search or "").strip()
    if not term or len(term) > 100:
        raise ValueError("Enter 1 to 100 characters of a TD, PIN, owner or location.")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Search page size must be between 1 and 100.")
    if cursor is not None and (type(cursor) is not int or cursor <= 0):
        raise ValueError("Invalid search cursor.")

    query = db_session.query(
        Property.id,
        Property.td_number,
        Property.owner_name,
        Property.pin,
        Property.lot_number,
        Property.block_number,
        Property.location,
        Property.barangay,
        Property.effectivity_date,
        Property.tax_year,
    ).filter(
        Property.deleted_at == None,
        or_(
            *(
                column.icontains(term, autoescape=True)
                for column in (
                    Property.td_number,
                    Property.pin,
                    Property.owner_name,
                    Property.location,
                    Property.barangay,
                    Property.lot_number,
                )
            )
        ),
    )
    if cursor is not None:
        query = query.filter(Property.id < cursor)
    rows = query.order_by(Property.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            {
                "id": row.id,
                "td_number": row.td_number,
                "owner_name": row.owner_name,
                "pin": row.pin or "",
                "lot_number": row.lot_number or "",
                "block_number": row.block_number or "",
                "location": row.location or "",
                "barangay": row.barangay or "",
                "effectivity": str(row.effectivity_date or row.tax_year or ""),
            }
            for row in rows
        ],
        "has_more": has_more,
        "next_cursor": rows[-1].id if has_more else None,
    }
