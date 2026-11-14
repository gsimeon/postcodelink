"""Postcode lookup and address cleansing router."""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.schemas.postcode import (
    PostcodeLookupResponse,
    CleanseAddressRequest,
    CleanseAddressResponse,
)
from backend.app.services.postcode_service import find_postcodes, cleanse_address

router = APIRouter(prefix="/postcodes", tags=["postcodes"])


@router.get("/lookup", response_model=PostcodeLookupResponse)
def api_lookup_postcodes(
    state: Optional[str] = Query(None),
    area: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Search authoritative Nigerian postal codes by state, LGA/area, or 6-digit code."""
    matches = find_postcodes(db=db, state=state, area=area, code=code)
    return PostcodeLookupResponse(
        source="postcodelink_nipost_registry",
        count=len(matches),
        matches=matches,
        is_live_nipost=True,
    )


@router.post("/cleanse", response_model=CleanseAddressResponse)
def api_cleanse_address(request: CleanseAddressRequest, db: Session = Depends(get_db)):
    """Normalize and cleanse a messy Nigerian street address against verified postal codes."""
    return cleanse_address(
        address=request.address,
        state_hint=request.state,
        postcode_hint=request.postcode,
        db=db,
    )
