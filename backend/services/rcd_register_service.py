"""Server-only, append-only RPT booklet assignments; no payment mutations."""

from sqlalchemy import inspect
from backend.database import Base
from backend.models import RcdCollectingOfficer, RcdReceiptBooklet, RcdRegisterControl
from utils.rcd_booklets import booklet_range
from utils.rcd_metadata import resolve_rcd_metadata


class RcdRegisterUnavailable(RuntimeError):
    pass


MODELS = (RcdCollectingOfficer, RcdReceiptBooklet, RcdRegisterControl)


def ensure_rcd_register_schema(db):
    """Called only by the approved server migration command, never an API request."""
    connection = db.connection()
    Base.metadata.create_all(
        connection, tables=[model.__table__ for model in MODELS], checkfirst=True
    )
    inspector = inspect(connection)
    for model in MODELS:
        existing = {item["name"] for item in inspector.get_columns(model.__tablename__)}
        if not set(model.__table__.columns.keys()) <= existing:
            raise RcdRegisterUnavailable(
                "RCD register schema needs review; no automatic ALTER or financial repair was attempted."
            )
    if db.get(RcdRegisterControl, 1) is None:
        db.add(RcdRegisterControl(id=1, revision=0))
        db.flush()


def require_rcd_register(db):
    inspector = inspect(db.connection())
    if any(not inspector.has_table(model.__tablename__) for model in MODELS):
        raise RcdRegisterUnavailable(
            "The RCD register is not installed. Use the approved server release/migration workflow; do not create it from the desktop."
        )
    control = (
        db.query(RcdRegisterControl).filter_by(id=1).populate_existing().one_or_none()
    )
    if control is None:
        raise RcdRegisterUnavailable(
            "RCD register initialization is incomplete; preserve evidence and review the server migration."
        )
    return control


def _lock_register(db):
    require_rcd_register(db)
    # MySQL row lock prevents concurrent range registrations. Validation queries
    # also use locking/current reads: an earlier REPEATABLE READ schema check
    # must not hide a range committed by the previous lock holder.
    control = (
        db.query(RcdRegisterControl)
        .filter_by(id=1)
        .populate_existing()
        .with_for_update()
        .one()
    )
    return control


def register_officer(db, name, actor):
    name = resolve_rcd_metadata(accountable_officer=name).accountable_officer
    if not name:
        raise ValueError(
            "Enter the collecting officer's name from the issuance record."
        )
    control = _lock_register(db)
    key = name.casefold()
    if db.query(RcdCollectingOfficer).filter_by(name_key=key).with_for_update().first():
        raise ValueError(
            "This collecting officer is already registered; select the existing entry."
        )
    officer = RcdCollectingOfficer(name=name, name_key=key, created_by=actor)
    db.add(officer)
    control.revision += 1
    db.flush()
    return officer


def register_booklet(db, collector_id, first_or, last_or, issued_on, actor):
    prefix, start, end, width = booklet_range(first_or, last_or)
    issued = resolve_rcd_metadata(report_date=issued_on).report_date
    control = _lock_register(db)
    if (
        not db.query(RcdCollectingOfficer)
        .filter_by(id=collector_id)
        .with_for_update()
        .first()
    ):
        raise ValueError("Select a registered collecting officer.")
    overlap = (
        db.query(RcdReceiptBooklet)
        .filter(
            RcdReceiptBooklet.serial_prefix == prefix,
            RcdReceiptBooklet.start_serial <= end,
            RcdReceiptBooklet.end_serial >= start,
        )
        .with_for_update()
        .first()
    )
    if overlap:
        raise ValueError(
            "This OR range overlaps a registered booklet. Review the issuance record; existing assignments were not changed."
        )
    booklet = RcdReceiptBooklet(
        collector_id=collector_id,
        first_or=str(first_or).strip(),
        last_or=str(last_or).strip(),
        serial_prefix=prefix,
        start_serial=start,
        end_serial=end,
        serial_width=width,
        issued_on=issued,
        created_by=actor,
    )
    db.add(booklet)
    control.revision += 1
    db.flush()
    return booklet


def officer_dict(officer):
    return {"id": officer.id, "name": officer.name}


def booklet_dict(booklet):
    return {
        "id": booklet.id,
        "collector_id": booklet.collector_id,
        "form_type": booklet.form_type,
        "first_or": booklet.first_or,
        "last_or": booklet.last_or,
        "quantity": 50,
        "issued_on": booklet.issued_on.isoformat(),
    }


def read_register(db):
    control = require_rcd_register(db)
    return {
        "revision": control.revision,
        "officers": [
            officer_dict(item)
            for item in db.query(RcdCollectingOfficer)
            .order_by(RcdCollectingOfficer.name, RcdCollectingOfficer.id)
            .all()
        ],
        "booklets": [
            booklet_dict(item)
            for item in db.query(RcdReceiptBooklet).order_by(RcdReceiptBooklet.id).all()
        ],
    }
