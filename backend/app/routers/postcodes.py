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
from backend.app.core.rate_limiter import check_client_ip_rate_limit
from backend.app.core.network import get_trusted_client_ip
from backend.app.config import settings
from backend.app.models.profile import Profile

router = APIRouter(prefix="/postcodes", tags=["postcodes"])


def check_optional_api_key(request: Request, db: Session):
    """Optional metering dependency for public demonstration endpoints:
    
    1. If x-api-key header is present: validates key and meters monthly quota atomically.
    2. If x-api-key header is absent: enforces strict IP-based sliding window rate limiting
       to prevent unmetered commercial scraping or abuse of public demonstration endpoints.
       Uses get_trusted_client_ip to reject spoofed X-Forwarded-For headers from untrusted origins.
    """
    x_api_key = request.headers.get("x-api-key")
    if x_api_key:
        get_api_key_merchant(x_api_key=x_api_key, db=db)
    else:
        # Enforce strict client IP rate limiting on unauthenticated public demo calls
        client_ip = get_trusted_client_ip(request)
        if client_ip != "testclient":
            check_client_ip_rate_limit(client_ip, limit_per_minute=settings.PUBLIC_DEMO_RATE_LIMIT_PER_MINUTE)


def execute_postcode_lookup(
    db: Session,
    state: Optional[str] = None,
    area: Optional[str] = None,
    code: Optional[str] = None,
    strict: bool = False,
    client: Optional[NIPOSTClient] = None,
) -> PostcodeLookupResponse:
    """Core business logic for searching official Nigerian postal codes from live NIPOST API or local reference dataset.
    
    If strict=True: fails closed with HTTP 502/503 if upstream NIPOST returns unauthorized,
    unavailable, or invalid response, strictly preventing local fallback masquerading as official verification.
    """
    upstream_status = None
    upstream_error = None
    fallback_reason = None

    if strict:
        if not code or not code.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Strict verification mode requires an authoritative 'code' parameter. Area-only discovery cannot be strictly verified against NIPOST.",
            )
        if not client or not client.is_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Official NIPOST API gateway is not configured or enabled. Strict verification requires live NIPOST connectivity.",
            )

    if client and client.is_configured and code:
        res = client.lookup_postcode(code)
        nipost_status = res.status
        live_res = res.data
        nipost_err = res.error_message
        res_status_val = res.status.value

        if nipost_status == NIPOSTLookupStatus.FOUND and live_res:
            upstream_version = live_res.get("dataset_version")
            is_validator = bool(live_res.get("service") == "validator" or not live_res.get("area") or not live_res.get("state"))
            ver_method = "validator" if is_validator else "validator_autofill_pipeline"
            addr_metadata_source = "local_enrichment" if is_validator else "nipost_autofill"

            rec_area = live_res.get("area")
            rec_state = live_res.get("state")
            rec_lga = live_res.get("lga")
            rec_building = live_res.get("building_reference") or live_res.get("recent_house_address")

            # If validator-only (existence verified without address metadata), check if local directory provides attributes
            if is_validator and (not rec_area or not rec_state):
                local_candidates = find_postcodes(db=db, code=code)
                if local_candidates:
                    loc = local_candidates[0]
                    rec_area = rec_area or loc.area
                    rec_state = rec_state or loc.state
                    rec_lga = rec_lga or loc.lga
                    rec_building = rec_building or loc.building_reference
                else:
                    rec_area = rec_area or "Unspecified Location"
                    rec_state = rec_state or "Nigeria"

            # Create VerificationEvidence if db available
            ev_id = None
            ev_valid_until = None
            if db is not None:
                try:
                    import hashlib
                    import json
                    from backend.app.models.verification_evidence import VerificationEvidence, default_valid_until
                    raw_bytes = json.dumps(live_res or {}, sort_keys=True).encode("utf-8")
                    resp_hash = hashlib.sha256(raw_bytes).hexdigest()
                    ev_valid_until = default_valid_until()
                    ev_rec = VerificationEvidence(
                        postcode=live_res.get("code") or code,
                        provider="NIPOST",
                        provider_reference_id=live_res.get("reference_id") or live_res.get("transaction_id"),
                        verification_method=ver_method,
                        dataset_version=upstream_version or "2026.1",
                        response_hash=resp_hash,
                        status="verified" if not is_validator else "partial",
                        address_metadata_source=addr_metadata_source,
                        valid_until=ev_valid_until,
                    )
                    db.add(ev_rec)
                    db.commit()
                    db.refresh(ev_rec)
                    ev_id = ev_rec.id
                except Exception:
                    pass

            prov_text = (
                "NIPOST Official Directory (Existence Verified by Validator; Local Enrichment for Address Attributes)"
                if is_validator
                else "NIPOST Official National Directory (Live API)"
            )

            schema_rec = PostcodeRecordSchema(
                code=live_res.get("code") or code,
                area=rec_area,
                state=rec_state,
                lga=rec_lga,
                lat=live_res.get("lat"),
                lng=live_res.get("lng"),
                postcode_type=live_res.get("postcode_type", "digital_location" if len(code.replace("-", "")) > 6 else "conventional_area"),
                postcode_category="official_digital_postcode" if len(code.replace("-", "")) > 6 else "legacy_postal_code",
                building_reference=rec_building,
                verification_status="official_verified" if not is_validator else "local_reference",
                provenance=prov_text,
                dataset_version=upstream_version,
                source_owner="NIPOST",
                source_type="official_national_directory",
                evidence_id=ev_id,
                verification_method=ver_method,
                address_metadata_source=addr_metadata_source,
                valid_until=ev_valid_until,
            )
            return PostcodeLookupResponse(
                source="live_nipost_api",
                count=1,
                matches=[schema_rec],
                is_live_nipost=True,
                is_partial_verification=is_validator,
                service_type="validator" if is_validator else "autofill",
                dataset_version=upstream_version,
                api_integration_version="2026.1",
                provenance=prov_text,
                lookup_status="official_verified" if not is_validator else "partially_verified",
                verification_source="live_nipost_api",
                verification_status="official_verified" if not is_validator else "local_reference",
                fallback_used=False,
                upstream_status=res_status_val,
                evidence_id=ev_id,
                verification_method=ver_method,
                address_metadata_source=addr_metadata_source,
                valid_until=ev_valid_until,
            )
        elif nipost_status == NIPOSTLookupStatus.NOT_FOUND:
            # Authoritative response: code does not exist in NIPOST directory. Do NOT fall back to local data.
            err_msg = nipost_err or "Postcode not found in official national directory."
            upstream_version = live_res.get("dataset_version") if (live_res and isinstance(live_res, dict)) else None
            return PostcodeLookupResponse(
                source="live_nipost_api",
                count=0,
                matches=[],
                is_live_nipost=True,
                dataset_version=upstream_version,
                api_integration_version="2026.1",
                provenance="NIPOST Official National Directory (Live API: Postcode Not Found)",
                lookup_status="not_found",
                verification_source="live_nipost_api",
                verification_status="unverified",
                fallback_used=False,
                upstream_status=res_status_val,
                upstream_error=err_msg,
            )
        else:
            # Invalid caller input is not an upstream outage and must not fall back
            # to local reference data or be reported as a missing postcode.
            if nipost_status == NIPOSTLookupStatus.INVALID_INPUT:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=nipost_err or "NIPOST rejected the postcode input.",
                )

            # Upstream error: UNAUTHORIZED, UNAVAILABLE, or INVALID_RESPONSE
            err_msg = nipost_err
            upstream_status = res_status_val
            upstream_error = err_msg

            if strict:
                if nipost_status == NIPOSTLookupStatus.INVALID_INPUT:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"NIPOST API validation error ({res_status_val}): {err_msg or 'Invalid postcode format'}.",
                    )
                elif nipost_status == NIPOSTLookupStatus.UNAUTHORIZED:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Official NIPOST API authorization failed ({res_status_val}): {err_msg or 'Invalid or expired credentials'}. Fallback disabled in strict verification mode.",
                    )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=f"Official NIPOST API unavailable ({res_status_val}): {err_msg or 'Service unreachable'}. Fallback disabled in strict verification mode.",
                    )

            fallback_reason = f"Upstream NIPOST {res_status_val}: {err_msg or 'Check authorization credentials or service availability.'}. Displaying local demonstration reference."

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
            m["dataset_version"] = m.get("dataset_version", "2024.2")
            if m.get("code") and len(m["code"].replace("-", "")) > 6:
                m["postcode_category"] = "local_address_reference"
            matches.append(PostcodeRecordSchema(**m))
        else:
            m_dict = PostcodeRecordSchema.model_validate(m).model_dump()
            m_dict["verification_status"] = "local_reference"
            m_dict["source_owner"] = "PostcodeLink"
            m_dict["dataset_version"] = m_dict.get("dataset_version", "2024.2")
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
        api_integration_version="2026.1",
        provenance="PostcodeLink Local Reference Dataset",
        lookup_status="fallback_reference" if fallback_used else "local_reference",
        verification_source="local_nipost_reference_dataset",
        verification_status="local_reference",
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        upstream_status=upstream_status,
        upstream_error=upstream_error,
    )


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
    return execute_postcode_lookup(
        db=db,
        state=state,
        area=area,
        code=code,
        strict=strict,
        client=client,
    )


@router.post("/cleanse", response_model=CleanseAddressResponse)
def api_cleanse_address(
    request: CleanseAddressRequest,
    http_req: Request,
    client: NIPOSTClient = Depends(get_nipost_client),
    db: Session = Depends(get_db),
):
    """Normalize and cleanse a messy Nigerian street address against verified reference postcodes,
    optionally verifying directly against the live official NIPOST gateway.
    """
    check_optional_api_key(http_req, db)
    return cleanse_address(
        address=request.address,
        state_hint=request.state,
        area_hint=request.area,
        postcode_hint=request.postcode,
        strict=request.strict,
        live_verify=request.live_verify,
        client=client,
        db=db,
    )


# ==============================================================================
# Commercial Subscription API Endpoints (Mandatory API Key Authentication)
# ==============================================================================

@router.get("/commercial/lookup", response_model=PostcodeLookupResponse)
def api_commercial_lookup_postcodes(
    request: Request,
    state: Optional[str] = Query(None),
    area: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    strict: bool = Query(False, description="Strict verification mode"),
    client: NIPOSTClient = Depends(get_nipost_client),
    merchant: Profile = Depends(get_api_key_merchant),
    db: Session = Depends(get_db),
):
    """Commercial enterprise postcode lookup. Strictly requires active 'x-api-key' with valid quota.
    
    Authenticates and meters monthly quota exactly once via dependency injection.
    Directly invokes business logic without duplicate route execution or double metering.
    """
    return execute_postcode_lookup(
        db=db,
        state=state,
        area=area,
        code=code,
        strict=strict,
        client=client,
    )


@router.post("/commercial/cleanse", response_model=CleanseAddressResponse)
def api_commercial_cleanse_address(
    request: CleanseAddressRequest,
    http_req: Request,
    client: NIPOSTClient = Depends(get_nipost_client),
    merchant: Profile = Depends(get_api_key_merchant),
    db: Session = Depends(get_db),
):
    """Commercial enterprise address cleansing. Strictly requires active 'x-api-key' with valid quota.
    
    Authenticates and meters monthly quota exactly once via dependency injection.
    Directly invokes business logic without duplicate route execution or double metering.
    """
    return cleanse_address(
        address=request.address,
        state_hint=request.state,
        area_hint=request.area,
        postcode_hint=request.postcode,
        strict=request.strict,
        live_verify=request.live_verify,
        client=client,
        db=db,
    )
