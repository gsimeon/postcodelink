"""Postcode lookup and address cleansing router."""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, HTTPException, status
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
from backend.app.routers.api_keys import get_api_key_merchant

router = APIRouter(prefix="/postcodes", tags=["postcodes"])


def check_optional_api_key(request: Request, db: Session):
    """Optional metering dependency: if x-api-key header is present, validate key and meter quota atomically."""
    x_api_key = request.headers.get("x-api-key")
    if x_api_key:
        get_api_key_merchant(x_api_key=x_api_key, db=db)


@router.get("/lookup", response_model=PostcodeLookupResponse)
def api_lookup_postcodes(
    request: Request,
    state: Optional[str] = Query(None),
    area: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    strict: bool = Query(False, description="Strict verification mode: fail closed if live NIPOST verification is unavailable or unauthorized"),
    client: NIPOSTClient = Depends(get_nipost_client),
    db: Session = Depends(get_db),
):
    """Search official Nigerian postal codes from live NIPOST API or local reference dataset.
    
    If strict=True: fails closed with HTTP 502/503 if upstream NIPOST returns unauthorized,
    unavailable, or invalid response, strictly preventing local fallback masquerading as official verification.
    """
    check_optional_api_key(request, db)

    upstream_status = None
    upstream_error = None
    fallback_reason = None

    if strict:
        if not code or not code.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Strict verification mode requires an authoritative 'code' parameter. Area-only discovery cannot be strictly verified against NIPOST.",
            )
        if not client.is_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Official NIPOST API gateway is not configured or enabled. Strict verification requires live NIPOST connectivity.",
            )

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
                lookup_status="official_verified",
                verification_source="live_nipost_api",
                verification_status="official_verified",
                fallback_used=False,
                upstream_status=res.status.value,
            )
        elif res.status == NIPOSTLookupStatus.NOT_FOUND:
            # Authoritative response: code does not exist in NIPOST directory. Do NOT fall back to local data.
            err_msg = res.error_message or getattr(res, "error", None) or "Postcode not found in official national directory."
            return PostcodeLookupResponse(
                source="live_nipost_api",
                count=0,
                matches=[],
                is_live_nipost=True,
                dataset_version="2026.1",
                provenance="NIPOST Official National Directory (Live API: Postcode Not Found)",
                lookup_status="not_found",
                verification_source="live_nipost_api",
                verification_status="unverified",
                fallback_used=False,
                upstream_status=res.status.value,
                upstream_error=err_msg,
            )
        else:
            # Upstream error: UNAUTHORIZED, UNAVAILABLE, or INVALID_RESPONSE
            err_msg = res.error_message or getattr(res, "error", None)
            upstream_status = res.status.value
            upstream_error = err_msg

            if strict:
                if res.status == NIPOSTLookupStatus.UNAUTHORIZED:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Official NIPOST API authorization failed ({res.status.value}): {err_msg or 'Invalid or expired credentials'}. Fallback disabled in strict verification mode.",
                    )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=f"Official NIPOST API unavailable ({res.status.value}): {err_msg or 'Service unreachable'}. Fallback disabled in strict verification mode.",
                    )

            fallback_reason = f"Upstream NIPOST {res.status.value}: {err_msg or 'Check authorization credentials or service availability.'}. Displaying local demonstration reference."

    if strict:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authoritative NIPOST verification could not be completed. Local reference fallback is disabled in strict mode.",
        )

    raw_matches = find_postcodes(db=db, state=state, area=area, code=code)
    # Ensure local matches NEVER return official_verified or official_digital_postcode
    matches = []
    for m in raw_matches:
        if isinstance(m, dict):
            m["verification_status"] = "local_reference"
            m["source_owner"] = "PostcodeLink"
            if m.get("code") and len(m["code"].replace("-", "")) > 6:
                m["postcode_category"] = "local_address_reference"
            matches.append(PostcodeRecordSchema(**m))
        else:
            m_dict = PostcodeRecordSchema.model_validate(m).model_dump()
            m_dict["verification_status"] = "local_reference"
            m_dict["source_owner"] = "PostcodeLink"
            if m_dict.get("code") and len(m_dict["code"].replace("-", "")) > 6:
                m_dict["postcode_category"] = "local_address_reference"
            matches.append(PostcodeRecordSchema(**m_dict))

    fallback_used = upstream_status is not None
    return PostcodeLookupResponse(
        source="local_nipost_reference_dataset",
        count=len(matches),
        matches=matches,
        is_live_nipost=False,
        dataset_version="2024.2",
        provenance="PostcodeLink Local Reference Dataset",
        lookup_status="fallback_reference" if fallback_used else "local_reference",
        verification_source="local_nipost_reference_dataset",
        verification_status="local_reference",
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        upstream_status=upstream_status,
        upstream_error=upstream_error,
    )


@router.post("/cleanse", response_model=CleanseAddressResponse)
def api_cleanse_address(request: CleanseAddressRequest, http_req: Request, db: Session = Depends(get_db)):
    """Normalize and cleanse a messy Nigerian street address against verified reference postcodes."""
    check_optional_api_key(http_req, db)
    return cleanse_address(
        address=request.address,
        state_hint=request.state,
        area_hint=request.area,
        postcode_hint=request.postcode,
        db=db,
    )
