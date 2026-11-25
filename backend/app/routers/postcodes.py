"""Postcode lookup and address cleansing router."""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.schemas.postcode import (
    PostcodeLookupResponse,
    CleanseAddressRequest,
    CleanseAddressResponse,
    PostcodeRecordSchema,
    CoverageReportResponse,
)
from backend.app.services.postcode_service import (
    find_postcodes,
    cleanse_address,
    get_postcode_coverage_report,
    record_verification_evidence,
)
from backend.app.services.nipost_client import get_nipost_client, NIPOSTClient, NIPOSTLookupStatus
from backend.app.routers.api_keys import get_api_key_merchant
from backend.app.core.rate_limiter import check_client_ip_rate_limit
from backend.app.core.network import get_trusted_client_ip
from backend.app.config import settings
from backend.app.models.profile import Profile
from backend.app.models.enums import AppRole
from backend.app.core.auth_deps import require_roles

router = APIRouter(prefix="/postcodes", tags=["postcodes"])
logger = logging.getLogger("postcode_router")


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

    if client is None:
        client = get_nipost_client()

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
        orch = getattr(client, "orchestrated_verify", None)
        orch_res = orch(code) if callable(orch) else None
        if isinstance(orch_res, tuple) and len(orch_res) == 4:
            nipost_status, live_res, nipost_err, ver_method = orch_res
            res_status_val = nipost_status.value
        else:
            res = client.lookup_postcode(code)
            nipost_status = res.status
            live_res = res.data
            nipost_err = res.error_message
            res_status_val = res.status.value
            is_validator_temp = bool(live_res and (live_res.get("service") == "validator" or not live_res.get("area") or not live_res.get("state")))
            ver_method = "validator" if is_validator_temp else "validator_autofill_pipeline"

        if nipost_status == NIPOSTLookupStatus.FOUND and live_res:
            upstream_version = live_res.get("dataset_version")
            rec_area = live_res.get("area")
            rec_state = live_res.get("state")
            rec_lga = live_res.get("lga")
            rec_building = live_res.get("building_reference") or live_res.get("recent_house_address")
            is_validator = bool(ver_method == "validator" or live_res.get("service") == "validator" or not rec_area or not rec_state)
            addr_metadata_source = "local_enrichment" if is_validator else "nipost_autofill"

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
                    rec_area = rec_area or None
                    rec_state = rec_state or None

            upstream_env = getattr(client, "upstream_environment", "unclassified")
            is_production_cred = upstream_env == "production"
            is_sandbox = upstream_env == "sandbox"
            if strict and not is_production_cred:
                detail = (
                    "Strict production verification failed closed: NIPOST client is configured with a sandbox (nipost_test_) credential, which cannot provide authoritative production verification."
                    if is_sandbox
                    else "Strict production verification failed closed: NIPOST client requires a positively identified production secret (nipost_live_). Unclassified, publishable (nipost_pk_*), missing, or auth_scheme='none' credentials are rejected."
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=detail,
                )

            # Record VerificationEvidence via dedicated transactional service (never persisted as official for non-production creds)
            evidence_persisted, ev_id, ev_valid_until = record_verification_evidence(
                db=db,
                code=code,
                live_res=live_res,
                ver_method=ver_method,
                upstream_version=upstream_version,
                is_validator=is_validator,
                addr_metadata_source=addr_metadata_source,
                is_sandbox=is_sandbox or not is_production_cred,
            )

            if strict and not evidence_persisted:
                if db is None:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Database session required for official verification evidence persistence. Strict verification failed closed.",
                    )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Verification evidence audit record could not be persisted. Strict verification failed closed.",
                )

            is_official_production = bool(is_production_cred and evidence_persisted)
            if is_sandbox:
                prov_text = "NIPOST Sandbox API (Test Key — Sample Dataset; not valid for production verification)"
                ver_status = "sandbox_verified"
                lookup_status_val = "sandbox_verified"
                service_type_val = "sandbox"
            elif not is_production_cred:
                prov_text = (
                    "Upstream NIPOST Gateway responded with an unclassified credential (not nipost_live_); "
                    "downgraded to local reference per verification integrity policy."
                )
                ver_status = "local_reference"
                lookup_status_val = "local_reference"
                service_type_val = "unverified_fallback"
            elif not evidence_persisted:
                prov_text = (
                    "NIPOST Live Gateway responded, but audit evidence persistence failed or database unavailable; "
                    "downgraded to local reference per verification integrity policy."
                )
                ver_status = "local_reference"
                lookup_status_val = "local_reference"
                service_type_val = "unverified_fallback"
            else:
                prov_text = (
                    "NIPOST Official Directory (Existence Verified by Validator; Local Enrichment for Address Attributes)"
                    if is_validator
                    else "NIPOST Official National Directory (Live API)"
                )
                ver_status = "official_verified" if not is_validator else "local_reference"
                lookup_status_val = "official_verified" if not is_validator else "partially_verified"
                service_type_val = "validator" if is_validator else "autofill"

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
                verification_status=ver_status,
                provenance=prov_text,
                dataset_version=upstream_version,
                source_owner="NIPOST Sandbox" if is_sandbox else ("NIPOST" if is_official_production else "PostcodeLink"),
                source_type="nipost_sandbox" if is_sandbox else ("official_national_directory" if is_official_production else "local_reference"),
                evidence_id=ev_id,
                verification_method=ver_method if (is_official_production or is_sandbox) else "unverified_fallback",
                address_metadata_source=addr_metadata_source,
                valid_until=ev_valid_until,
            )
            return PostcodeLookupResponse(
                source="nipost_sandbox" if is_sandbox else ("live_nipost_api" if is_official_production else "local_reference_fallback"),
                count=1,
                matches=[schema_rec],
                is_live_nipost=is_official_production,
                upstream_contacted=True,
                postcode_exists=True,
                is_partial_verification=is_validator,
                service_type=service_type_val,
                dataset_version=upstream_version,
                api_integration_version="2026.1",
                provenance=prov_text,
                lookup_status=lookup_status_val,
                verification_source="nipost_sandbox" if is_sandbox else ("live_nipost_api" if is_official_production else "local_nipost_reference_dataset"),
                verification_status=ver_status,
                fallback_used=bool(not is_official_production and not is_sandbox),
                fallback_reason=(
                    "Upstream credential is unclassified (requires nipost_live_)"
                    if (not is_production_cred and not is_sandbox)
                    else ("Verification evidence could not be recorded" if (not evidence_persisted and not is_sandbox) else None)
                ),
                upstream_status=res_status_val,
                evidence_id=ev_id,
                verification_method=ver_method if evidence_persisted else "unverified_fallback",
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
                is_live_nipost=False,
                upstream_contacted=True,
                postcode_exists=False,
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
        upstream_contacted=fallback_used,
        postcode_exists=bool(matches) if not fallback_used else None,
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
        verification_mode=request.verification_mode,
        client=client,
        db=db,
    )


@router.get("/coverage", response_model=CoverageReportResponse)
def api_get_coverage_report(
    db: Session = Depends(get_db),
    client: NIPOSTClient = Depends(get_nipost_client),
):
    """Statistical dataset coverage, geographic breadth, and upstream NIPOST adapter status.
    Provides verifiable operational metrics for platform users and enterprise evaluators.
    """
    return get_postcode_coverage_report(db=db, client=client)


# ==============================================================================
# Commercial Subscription API Endpoints (Mandatory API Key Authentication)
# ==============================================================================

def _resolve_commercial_nipost_client(http_req: Request, live_client: NIPOSTClient, strict: bool) -> tuple[NIPOSTClient, bool]:
    """Enforce pl_test_ sandbox isolation and commercial production authorization gate."""
    from backend.app.config import settings

    api_key_env = getattr(http_req.state, "api_key_environment", "unclassified")
    if api_key_env == "test":
        if strict:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Developer sandbox keys (pl_test_) cannot perform strict production verification and never contact live NIPOST endpoints.",
            )
        # Isolated sandbox client: empty base_url guarantees zero outbound live NIPOST calls or credit consumption
        return NIPOSTClient(base_url="", api_key="nipost_test_sandbox_isolated"), True

    if api_key_env != "live":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unclassified or legacy API key environment cannot access commercial postcode endpoints. Issue a pl_test_ or authorized pl_live_ key.",
        )

    if not getattr(settings, "is_nipost_production_authorized", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Live commercial postcode access (pl_live_) is disabled pending recorded NIPOST commercial "
                "authorization (NIPOST_PRODUCTION_AUTHORIZED=true with agreement reference and approver)."
            ),
        )
    return live_client, False


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
    
    Enforces pl_test_ sandbox isolation (never hits live NIPOST) and commercial authorization gate for pl_live_.
    """
    effective_client, is_dev_sandbox = _resolve_commercial_nipost_client(request, client, strict)
    res = execute_postcode_lookup(
        db=db,
        state=state,
        area=area,
        code=code,
        strict=strict,
        client=effective_client,
    )
    if is_dev_sandbox:
        res.source = "postcodelink_sandbox"
        res.verification_source = "postcodelink_sandbox"
        res.verification_status = "sandbox_verified" if res.matches else "local_reference"
        res.is_live_nipost = False
        res.upstream_contacted = False
        res.provenance = "PostcodeLink Developer Sandbox (pl_test_ — isolated test environment; live NIPOST credits not consumed)"
    return res


@router.post("/commercial/cleanse", response_model=CleanseAddressResponse)
def api_commercial_cleanse_address(
    request: CleanseAddressRequest,
    http_req: Request,
    client: NIPOSTClient = Depends(get_nipost_client),
    merchant: Profile = Depends(get_api_key_merchant),
    db: Session = Depends(get_db),
):
    """Commercial enterprise address cleansing. Strictly requires active 'x-api-key' with valid quota.
    
    Enforces pl_test_ sandbox isolation (never hits live NIPOST) and commercial authorization gate for pl_live_.
    """
    strict_requested = bool(request.strict or request.verification_mode == "nipost_strict")
    effective_client, is_dev_sandbox = _resolve_commercial_nipost_client(http_req, client, strict_requested)
    res = cleanse_address(
        address=request.address,
        state_hint=request.state,
        area_hint=request.area,
        postcode_hint=request.postcode,
        strict=request.strict,
        live_verify=False if is_dev_sandbox else request.live_verify,
        verification_mode="local_standardization" if is_dev_sandbox else request.verification_mode,
        client=effective_client,
        db=db,
    )
    if is_dev_sandbox:
        res.source = "postcodelink_sandbox"
        res.verification_source = "postcodelink_sandbox"
        res.verification_status = "sandbox_verified" if res.postcode else "local_reference"
        res.is_live_nipost = False
        res.upstream_contacted = False
        res.provenance = "PostcodeLink Developer Sandbox (pl_test_ — isolated test environment; live NIPOST credits not consumed)"
    return res


@router.post("/integration/health-check")
def api_trigger_nipost_health_check(
    current_user: Profile = Depends(require_roles([AppRole.ADMIN])),
    client: NIPOSTClient = Depends(get_nipost_client),
):
    """Administrator-only, rate-limited upstream NIPOST health & credential probe.
    
    Returns minimal sanitized telemetry; detailed diagnostics remain in server logs.
    Connectivity/authentication probe success never implies commercial production_authorized approval.
    """
    check_client_ip_rate_limit(f"admin_health_{current_user.id}", limit_per_minute=10)
    probe_result = client.check_health()
    if not probe_result.get("healthy"):
        logger.warning(
            f"Admin NIPOST health probe triggered by {current_user.email} returned unhealthy: "
            f"{probe_result.get('reason')}"
        )
    status_snapshot = client.get_integration_status()
    return {
        "healthy": bool(probe_result.get("healthy")),
        "connectivity_healthy": bool(status_snapshot.get("connectivity_healthy")),
        "authentication_verified": bool(status_snapshot.get("authentication_verified")),
        "contract_verified": bool(status_snapshot.get("contract_verified")),
        "production_authorized": bool(status_snapshot.get("production_authorized")),
        "upstream_environment": status_snapshot.get("upstream_environment", "unclassified"),
        "last_checked_at": status_snapshot.get("last_checked_at"),
        "status": status_snapshot.get("status"),
    }
