# -*- coding: utf-8 -*-
from sqlalchemy import or_
from sqlalchemy.orm import Session
from backend.models import Property, Payment
from backend.database import SessionLocal


def global_search(query, limit=10, db_session: Session = None):
    """
    Performs a unified search across Properties and Payments.
    Returns a list of results categorized by type.
    """
    if not query or len(str(query).strip()) < 2:
        return []

    search_term = f"%{query}%"
    results = []

    # 1. Search Properties
    props = db_session.query(Property).filter(
        Property.deleted_at == None,
        or_(
            Property.td_number.like(search_term),
            Property.owner_name.like(search_term),
            Property.pin.like(search_term)
        )
    ).limit(limit).all()

    for p in props:
        results.append(
            {
                "id": p.id,
                "title": f"🏠 {p.td_number}",
                "subtitle": p.owner_name,
                "type": "property",
                "identifier": p.td_number,  # TD Number for navigation
            }
        )

    # 2. Search Payments/Receipts
    pays = db_session.query(Payment, Property.owner_name).join(
        Property, Property.id == Payment.property_id
    ).filter(
        Property.deleted_at == None,
        or_(
            Payment.or_number.like(search_term),
            Property.owner_name.like(search_term)
        )
    ).limit(limit).all()

    for pay, owner_name in pays:
        results.append(
            {
                "id": pay.id,
                "title": f"📄 OR: {pay.or_number}",
                "subtitle": f"Payor: {owner_name}",
                "type": "receipt",
                "identifier": pay.id,  # Payment ID for navigation
            }
        )

    return results[:limit]


def get_quick_actions():
    """Returns a list of available system commands."""
    return [
        {
            "title": "⚡ Create New Property",
            "command": "nav:new_property",
            "type": "action",
        },
        {"title": "⚡ Run System Backup", "command": "action:backup", "type": "action"},
        {
            "title": "⚡ View Delinquency Report",
            "command": "nav:reports",
            "type": "action",
        },
        {"title": "⚡ User Management", "command": "nav:users", "type": "action"},
        {"title": "⚡ Assessment Roll", "command": "nav:assessment", "type": "action"},
    ]
