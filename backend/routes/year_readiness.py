"""Administrative read-only endpoint for annual tax-year readiness."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.deps import admin_only
from backend.services.tax_year_readiness_service import get_tax_year_readiness


router = APIRouter(tags=["Admin Tools"])


@router.get("/system/tax-year-readiness", dependencies=[Depends(admin_only)])
def tax_year_readiness(db_session: Session = Depends(get_db)):
    """Return the December/January rollover warning state without writing data."""
    return get_tax_year_readiness(db_session=db_session)
