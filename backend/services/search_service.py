# -*- coding: utf-8 -*-
import db_manager as db


def global_search(query, limit=10):
    """
    Performs a unified search across Properties and Payments.
    Returns a list of results categorized by type.
    """
    if not query or len(str(query).strip()) < 2:
        return []

    search_term = f"%{query}%"
    results = []

    # 1. Search Properties
    prop_query = """
        SELECT id, td_number, owner_name, 'property' as type
        FROM properties
        WHERE is_deleted = 0 
          AND (td_number LIKE %s OR owner_name LIKE %s OR pin LIKE %s)
        LIMIT %s
    """
    props = db.db_query(
        prop_query,
        (search_term, search_term, search_term, limit),
        fetch=True,
        commit=False,
    )
    for p in props or []:
        results.append(
            {
                "id": p[0],
                "title": f"🏠 {p[1]}",
                "subtitle": p[2],
                "type": "property",
                "identifier": p[1],  # TD Number for navigation
            }
        )

    # 2. Search Payments/Receipts
    pay_query = """
        SELECT pay.id, pay.or_number, prop.owner_name, 'receipt' as type
        FROM payments pay
        JOIN properties prop ON prop.id = pay.property_id
        WHERE prop.is_deleted = 0
          AND (pay.or_number LIKE %s OR prop.owner_name LIKE %s)
        LIMIT %s
    """
    pays = db.db_query(
        pay_query, (search_term, search_term, limit), fetch=True, commit=False
    )
    for pay in pays or []:
        results.append(
            {
                "id": pay[0],
                "title": f"📄 OR: {pay[1]}",
                "subtitle": f"Payor: {pay[2]}",
                "type": "receipt",
                "identifier": pay[0],  # Payment ID for navigation
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
