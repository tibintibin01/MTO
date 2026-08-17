# -*- coding: utf-8 -*-
"""Organizational portfolio operations.

This service never changes Property, PropertyBilling, Payment, or generated
document data. Linking and unlinking only insert/delete association rows.
"""

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import Property
from backend.models_portfolio import PropertyPortfolio, PropertyPortfolioLink
from backend.services.history_service import log_data_change
from utils.sanitizer import sanitize_string


class PortfolioNotFoundError(LookupError):
    pass


class PortfolioConflictError(ValueError):
    pass


class PortfolioValidationError(ValueError):
    pass


def ensure_portfolio_schema(db_session: Session) -> None:
    """Idempotently create portfolio tables for deployments not running Alembic."""
    bind = db_session.get_bind()
    PropertyPortfolio.__table__.create(bind=bind, checkfirst=True)
    PropertyPortfolioLink.__table__.create(bind=bind, checkfirst=True)


def _actor(user: dict) -> tuple[int, str]:
    user = user or {}
    try:
        user_id = int(user.get("id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    return user_id, str(user.get("username") or "system")


def _clean_name(name: str) -> str:
    cleaned = str(sanitize_string(name or "") or "").strip()
    if len(cleaned) < 2:
        raise PortfolioValidationError(
            "Portfolio name must contain at least two characters."
        )
    if len(cleaned) > 255:
        raise PortfolioValidationError(
            "Portfolio name cannot exceed 255 characters."
        )
    return cleaned


def _iso(value):
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def _summary(portfolio: PropertyPortfolio, property_count: int = 0) -> dict:
    return {
        "id": portfolio.id,
        "name": portfolio.name,
        "is_active": bool(portfolio.is_active),
        "property_count": int(property_count or 0),
        "created_by": portfolio.created_by,
        "created_at": _iso(portfolio.created_at),
        "updated_at": _iso(portfolio.updated_at),
    }


def _get_portfolio(portfolio_id: int, db_session: Session) -> PropertyPortfolio:
    portfolio = (
        db_session.query(PropertyPortfolio)
        .filter(PropertyPortfolio.id == int(portfolio_id))
        .first()
    )
    if not portfolio:
        raise PortfolioNotFoundError("Portfolio not found.")
    return portfolio


def _find_by_name(name: str, db_session: Session, exclude_id: int = None):
    query = db_session.query(PropertyPortfolio).filter(
        func.lower(PropertyPortfolio.name) == name.lower()
    )
    if exclude_id is not None:
        query = query.filter(PropertyPortfolio.id != int(exclude_id))
    return query.first()


def list_portfolios(
    search: str = "",
    include_inactive: bool = False,
    db_session: Session = None,
) -> list[dict]:
    counts = (
        db_session.query(
            PropertyPortfolioLink.portfolio_id.label("portfolio_id"),
            func.count(PropertyPortfolioLink.id).label("property_count"),
        )
        .group_by(PropertyPortfolioLink.portfolio_id)
        .subquery()
    )
    query = (
        db_session.query(
            PropertyPortfolio,
            func.coalesce(counts.c.property_count, 0),
        )
        .outerjoin(counts, counts.c.portfolio_id == PropertyPortfolio.id)
    )
    if not include_inactive:
        query = query.filter(PropertyPortfolio.is_active.is_(True))
    cleaned_search = str(search or "").strip()
    if cleaned_search:
        query = query.filter(
            func.lower(PropertyPortfolio.name).like(
                f"%{cleaned_search.lower()}%"
            )
        )
    rows = query.order_by(
        PropertyPortfolio.is_active.desc(),
        PropertyPortfolio.name.asc(),
        PropertyPortfolio.id.asc(),
    ).all()
    return [_summary(portfolio, count) for portfolio, count in rows]


def get_portfolio_detail(
    portfolio_id: int,
    db_session: Session = None,
) -> dict:
    portfolio = _get_portfolio(portfolio_id, db_session)
    rows = (
        db_session.query(PropertyPortfolioLink, Property)
        .join(Property, Property.id == PropertyPortfolioLink.property_id)
        .filter(PropertyPortfolioLink.portfolio_id == portfolio.id)
        .order_by(
            Property.owner_name.asc(),
            Property.td_number.asc(),
            Property.id.asc(),
        )
        .all()
    )
    properties = []
    for link, prop in rows:
        properties.append(
            {
                "link_id": link.id,
                "property_id": prop.id,
                "td_number": prop.td_number,
                "owner_name": prop.owner_name,
                "payor_name": prop.payor_name,
                "barangay": prop.barangay or prop.location,
                "kind_of_property": prop.kind_of_property,
                "lot_number": prop.lot_number,
                "block_number": prop.block_number,
                "pin": prop.pin,
                "effectivity_date": prop.effectivity_date,
                "assessed_value": float(prop.assessed_value or 0),
                "property_active": prop.deleted_at is None,
                "property_archived": bool(prop.archived),
                "linked_by": link.linked_by,
                "linked_at": _iso(link.linked_at),
            }
        )
    result = _summary(portfolio, len(properties))
    result["properties"] = properties
    return result


def create_portfolio(
    name: str,
    user: dict,
    db_session: Session = None,
) -> dict:
    cleaned_name = _clean_name(name)
    existing = _find_by_name(cleaned_name, db_session)
    if existing:
        state = "active" if existing.is_active else "inactive"
        raise PortfolioConflictError(
            f"A {state} portfolio named '{existing.name}' already exists."
        )

    user_id, username = _actor(user)
    portfolio = PropertyPortfolio(
        name=cleaned_name,
        is_active=True,
        created_by=username,
    )
    try:
        db_session.add(portfolio)
        db_session.flush()
        log_data_change(
            user_id=user_id,
            username=username,
            table_name="property_portfolios",
            record_id=portfolio.id,
            action="CREATE",
            after={"name": portfolio.name, "is_active": True},
            db_session=db_session,
        )
        db_session.commit()
        db_session.refresh(portfolio)
    except IntegrityError as exc:
        db_session.rollback()
        raise PortfolioConflictError(
            f"A portfolio named '{cleaned_name}' already exists."
        ) from exc
    except Exception:
        db_session.rollback()
        raise
    return _summary(portfolio, 0)


def update_portfolio(
    portfolio_id: int,
    name: str = None,
    is_active: bool = None,
    user: dict = None,
    db_session: Session = None,
) -> dict:
    portfolio = _get_portfolio(portfolio_id, db_session)
    before = {"name": portfolio.name, "is_active": bool(portfolio.is_active)}

    if name is not None:
        cleaned_name = _clean_name(name)
        duplicate = _find_by_name(
            cleaned_name,
            db_session,
            exclude_id=portfolio.id,
        )
        if duplicate:
            raise PortfolioConflictError(
                f"A portfolio named '{duplicate.name}' already exists."
            )
        portfolio.name = cleaned_name
    if is_active is not None:
        portfolio.is_active = bool(is_active)

    after = {"name": portfolio.name, "is_active": bool(portfolio.is_active)}
    if before == after:
        return get_portfolio_detail(portfolio.id, db_session)

    user_id, username = _actor(user)
    try:
        log_data_change(
            user_id=user_id,
            username=username,
            table_name="property_portfolios",
            record_id=portfolio.id,
            action="UPDATE",
            before=before,
            after=after,
            db_session=db_session,
        )
        db_session.commit()
        db_session.refresh(portfolio)
    except IntegrityError as exc:
        db_session.rollback()
        raise PortfolioConflictError(
            f"A portfolio named '{portfolio.name}' already exists."
        ) from exc
    except Exception:
        db_session.rollback()
        raise
    return get_portfolio_detail(portfolio.id, db_session)


def link_property(
    portfolio_id: int,
    property_id: int,
    user: dict,
    db_session: Session = None,
) -> dict:
    portfolio = _get_portfolio(portfolio_id, db_session)
    if not portfolio.is_active:
        raise PortfolioValidationError(
            "Reactivate this portfolio before linking properties."
        )

    prop = (
        db_session.query(Property)
        .filter(
            Property.id == int(property_id),
            Property.deleted_at.is_(None),
            Property.archived.is_(False),
        )
        .first()
    )
    if not prop:
        raise PortfolioNotFoundError("Active property not found.")

    existing = (
        db_session.query(PropertyPortfolioLink)
        .filter(PropertyPortfolioLink.property_id == prop.id)
        .first()
    )
    if existing:
        existing_portfolio = _get_portfolio(existing.portfolio_id, db_session)
        if existing.portfolio_id == portfolio.id:
            result = get_portfolio_detail(portfolio.id, db_session)
            result["already_linked"] = True
            return result
        raise PortfolioConflictError(
            f"TD {prop.td_number} is already linked to portfolio "
            f"'{existing_portfolio.name}'. Unlink it there first."
        )

    user_id, username = _actor(user)
    link = PropertyPortfolioLink(
        portfolio_id=portfolio.id,
        property_id=prop.id,
        linked_by=username,
    )
    try:
        db_session.add(link)
        db_session.flush()
        log_data_change(
            user_id=user_id,
            username=username,
            table_name="property_portfolio_links",
            record_id=link.id,
            action="LINK_PROPERTY",
            after={
                "portfolio_id": portfolio.id,
                "portfolio_name": portfolio.name,
                "property_id": prop.id,
                "td_number": prop.td_number,
            },
            db_session=db_session,
        )
        db_session.commit()
    except IntegrityError as exc:
        db_session.rollback()
        raise PortfolioConflictError(
            f"TD {prop.td_number} is already linked to a portfolio."
        ) from exc
    except Exception:
        db_session.rollback()
        raise
    return get_portfolio_detail(portfolio.id, db_session)


def unlink_property(
    portfolio_id: int,
    property_id: int,
    user: dict,
    db_session: Session = None,
) -> dict:
    portfolio = _get_portfolio(portfolio_id, db_session)
    link = (
        db_session.query(PropertyPortfolioLink)
        .filter(
            PropertyPortfolioLink.portfolio_id == portfolio.id,
            PropertyPortfolioLink.property_id == int(property_id),
        )
        .first()
    )
    if not link:
        raise PortfolioNotFoundError(
            "This property is not linked to the selected portfolio."
        )

    prop = db_session.query(Property).filter(Property.id == link.property_id).first()
    user_id, username = _actor(user)
    before = {
        "portfolio_id": portfolio.id,
        "portfolio_name": portfolio.name,
        "property_id": link.property_id,
        "td_number": prop.td_number if prop else None,
    }
    link_id = link.id
    try:
        db_session.delete(link)
        log_data_change(
            user_id=user_id,
            username=username,
            table_name="property_portfolio_links",
            record_id=link_id,
            action="UNLINK_PROPERTY",
            before=before,
            db_session=db_session,
        )
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise
    return get_portfolio_detail(portfolio.id, db_session)
