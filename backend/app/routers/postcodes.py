"""Postcode lookup and address cleansing router."""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.schemas.postcode import (
    PostcodeLookupResponse,
    CleanseAddressRequest,
    CleanseAddressResponse,
    PostcodeRecordSchema,
)
from backend.app.services.postcode_service import find_postcodes, cleanse_address
from backend.app.services.nipost_client import get_nipost_client, NIPOSTClient, NIPOSTLookupStatus

router = APIRouter(prefix="/postcodes", tags=["postcodes"])


@router.get("/lookup", response_model=PostcodeLookupResponse)
def api_lookup_postcodes(
    state: Optional[str] = Query(None),
    area: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    client: NIPOSTClient = Depends(get_nipost_client),
    db: Session = Depends(get_db),
):
    """Search official Nigerian postal codes from live NIPOST API or local reference dataset."""
    if client.is_configured and code:
        res = client.lookup_postcode(code)
        if res.status == NIPOSTLookupStatus.FOUND and res.data:
            live_res = res.data
            schema_rec = PostcodeRecordSchema(
                code=live_res["code"],
                area=live_res["area"],
                state=live_res["state"],
                lga=live_res.get("lga"),
                lat=live_res.get("lat"),
                lng=live_res.get("lng"),
                postcode_type=live_res.get("postcode_type", "digital_location" if len(code.replace("-", "")) > 6 else "conventional_area"),
                postcode_category="official_digital_postcode" if len(code.replace("-", "")) > 6 else "legacy_postal_code",
                building_reference=live_res.get("building_reference"),
                verification_status="official_verified",
                provenance="NIPOST Official National Directory (Live API)",
                dataset_version=live_res.get("dataset_version", "2026.1"),
                source_owner="NIPOST",
                source_type="official_national_directory",
            )
            return PostcodeLookupResponse(
                source="live_nipost_api",
                count=1,
                matches=[schema_rec],
                is_live_nipost=True,
                dataset_version=live_res.get("dataset_version", "2026.1"),
                provenance="NIPOST Official National Directory (Live API)",
            )
        elif res.status == NIPOSTLookupStatus.NOT_FOUND:
            # Authoritative response: code does not exist in NIPOST directory. Do NOT fall back to local data.
            return PostcodeLookupResponse(
                source="live_nipost_api",
                count=0,
                matches=[],
                is_live_nipost=True,
                dataset_version="2026.1",
                provenance="NIPOST Official National Directory (Live API: Postcode Not Found)",
            )
        # If UNAVAILABLE, UNAUTHORIZED, or INVALID_RESPONSE: fall through to local reference dataset with fallback notice

    matches = find_postcodes(db=db, state=state, area=area, code=code)
    return PostcodeLookupResponse(
        source="local_nipost_reference_dataset",
        count=len(matches),
        matches=matches,
        is_live_nipost=False,
    )


@router.post("/cleanse", response_model=CleanseAddressResponse)
def api_cleanse_address(request: CleanseAddressRequest, db: Session = Depends(get_db)):
    """Normalize and cleanse a messy Nigerian street address against verified reference postcodes."""
    return cleanse_address(
        address=request.address,
        state_hint=request.state,
        area_hint=request.area,
        postcode_hint=request.postcode,
        db=db,
    )
