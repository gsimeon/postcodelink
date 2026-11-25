"""Postcode directory service and Nigerian address cleanser.

PostcodeLink Local Reference Provenance:
- Source: PostcodeLink Demonstration Reference Dataset (independent local reference)
- Edition: Demonstration & Reference Edition
- Version: 2024.2
- States Covered (11): Lagos, Abuja FCT, Rivers, Oyo, Ogun, Kano, Kaduna, Enugu, Delta, Edo, Anambra
- Note: Live official national postcode validation and autofill are provided via the NIPOST API client.
  Local records are strictly categorized as local_reference and never represented as official government verification.
"""
import re
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

logger = logging.getLogger("postcode_service")
from backend.app.models.postcode import PostcodeDirectory
from backend.app.schemas.postcode import (
    CleanseAddressResponse,
    PostcodeRecordSchema,
    VerificationMode,
    CoverageReportResponse,
)
from backend.app.services.nipost_client import NIPOSTLookupStatus
from backend.app.core.postcode_utils import (
    parse_digital_postcode_components,
    parse_legacy_postcode,
    parse_legacy_3part_code,
    is_well_formed_postcode,
    normalize_postcode,
    extract_postcode_from_text,
)

DATASET_METADATA = {
    "version": "2024.2",
    "edition": "Local Demonstration & Reference Edition",
    "source": "PostcodeLink Local Reference & Demonstration Dataset",
    "publication_date": "2024-06-01",
    "states_covered": [
        "Lagos", "Abuja FCT", "Rivers", "Oyo", "Ogun",
        "Kano", "Kaduna", "Enugu", "Delta", "Edo", "Anambra"
    ],
    "status": "local_reference",
}

# Legacy postal references and demonstration fixtures (multi-state pilot & format demonstration)
LEGACY_POSTAL_REFERENCES: List[Dict[str, Any]] = [
    # 1. Lagos State (Zone 1)
    {"code": "100001", "area": "Ikeja Central / Alausa", "state": "Lagos", "lga": "Ikeja", "lat": 6.6186, "lng": 3.3570},
    {"code": "100271", "area": "Ikeja GRA", "state": "Lagos", "lga": "Ikeja", "lat": 6.5885, "lng": 3.3556},
    {"code": "100281", "area": "Opebi / Allen Avenue", "state": "Lagos", "lga": "Ikeja", "lat": 6.5982, "lng": 3.3538},
    {"code": "100276", "area": "Ogba", "state": "Lagos", "lga": "Ikeja", "lat": 6.6342, "lng": 3.3421},
    {"code": "101241", "area": "Lekki Phase 1", "state": "Lagos", "lga": "Eti-Osa", "lat": 6.4474, "lng": 3.4723},
    {"code": "101233", "area": "Victoria Island (VI)", "state": "Lagos", "lga": "Eti-Osa", "lat": 6.4281, "lng": 3.4219},
    {"code": "101245", "area": "Ikoyi / Banana Island", "state": "Lagos", "lga": "Eti-Osa", "lat": 6.4549, "lng": 3.4357},
    {"code": "105102", "area": "Lekki Phase 1", "state": "Lagos", "lga": "Eti-Osa", "lat": 6.4474, "lng": 3.4723},
    {"code": "105101", "area": "Chevron / Lekki Phase 2 / Ajah", "state": "Lagos", "lga": "Eti-Osa", "lat": 6.4382, "lng": 3.5321},
    {"code": "101212", "area": "Yaba / Sabo Tech Hub", "state": "Lagos", "lga": "Lagos Mainland", "lat": 6.5095, "lng": 3.3711},
    {"code": "101283", "area": "Surulere / Bode Thomas", "state": "Lagos", "lga": "Surulere", "lat": 6.4969, "lng": 3.3533},
    {"code": "100248", "area": "Magodo Phase 1 & 2 / Shangisha", "state": "Lagos", "lga": "Kosofe", "lat": 6.6212, "lng": 3.3854},
    {"code": "100242", "area": "Gbagada / Ifako", "state": "Lagos", "lga": "Kosofe", "lat": 6.5562, "lng": 3.3881},
    {"code": "100216", "area": "Anthony Village / Maryland", "state": "Lagos", "lga": "Kosofe", "lat": 6.5688, "lng": 3.3712},
    {"code": "102213", "area": "Festac Town / Mile 2", "state": "Lagos", "lga": "Amuwo-Odofin", "lat": 6.4674, "lng": 3.2829},
    {"code": "100265", "area": "Oshodi / Airport Road", "state": "Lagos", "lga": "Oshodi-Isolo", "lat": 6.5540, "lng": 3.3486},
    {"code": "100218", "area": "Agege / Pen Cinema", "state": "Lagos", "lga": "Agege", "lat": 6.6180, "lng": 3.3209},
    {"code": "101251", "area": "Apapa Port / Wharf", "state": "Lagos", "lga": "Apapa", "lat": 6.4442, "lng": 3.3642},
    {"code": "104101", "area": "Ikorodu Central", "state": "Lagos", "lga": "Ikorodu", "lat": 6.6194, "lng": 3.5105},
    {"code": "102102", "area": "Badagry Central", "state": "Lagos", "lga": "Badagry", "lat": 6.4150, "lng": 2.8813},
    {"code": "103241", "area": "Epe Central", "state": "Lagos", "lga": "Epe", "lat": 6.5841, "lng": 3.9834},

    # 2. Abuja FCT (Zone 9)
    {"code": "900001", "area": "Garki Area 1 - 11", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.0345, "lng": 7.4891},
    {"code": "900211", "area": "Central Business District (CBD)", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.0579, "lng": 7.4951},
    {"code": "900241", "area": "Wuse Zone 1 - 7", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.0621, "lng": 7.4612},
    {"code": "900288", "area": "Wuse 2 (Aminu Kano Crescent)", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.0765, "lng": 7.4722},
    {"code": "900271", "area": "Maitama District", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.0882, "lng": 7.4934},
    {"code": "900281", "area": "Asokoro District", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.0512, "lng": 7.5255},
    {"code": "900108", "area": "Gwarinpa Estate", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.1088, "lng": 7.3982},
    {"code": "900104", "area": "Utako / Jabi", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.0673, "lng": 7.4328},
    {"code": "901101", "area": "Kubwa / Dutse", "state": "Abuja FCT", "lga": "Bwari", "lat": 9.1550, "lng": 7.3360},
    {"code": "900107", "area": "Lugbe / Airport Express Corridor", "state": "Abuja FCT", "lga": "Municipal", "lat": 8.9741, "lng": 7.3719},
    {"code": "900103", "area": "Nyanya / Karu Corridor", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.0312, "lng": 7.5794},

    # 3. Rivers State (Zone 5)
    {"code": "500001", "area": "Old GRA / Forces Avenue", "state": "Rivers", "lga": "Port Harcourt", "lat": 4.8156, "lng": 7.0498},
    {"code": "500261", "area": "D-Line / Aba Road / Diobu", "state": "Rivers", "lga": "Port Harcourt", "lat": 4.8089, "lng": 7.0092},
    {"code": "500211", "area": "Trans-Amadi Industrial Layout", "state": "Rivers", "lga": "Port Harcourt", "lat": 4.8234, "lng": 7.0392},
    {"code": "500272", "area": "Rumuola / Rumuokwuta", "state": "Rivers", "lga": "Obio-Akpor", "lat": 4.8389, "lng": 6.9972},
    {"code": "500102", "area": "Choba (Uniport Corridor)", "state": "Rivers", "lga": "Obio-Akpor", "lat": 4.9012, "lng": 6.9123},
    {"code": "501101", "area": "Eleme / Petrochemical Zone", "state": "Rivers", "lga": "Eleme", "lat": 4.7891, "lng": 7.1234},

    # 4. Oyo State (Zone 2)
    {"code": "200213", "area": "Bodija / Old Bodija", "state": "Oyo", "lga": "Ibadan North", "lat": 7.4325, "lng": 3.9056},
    {"code": "200281", "area": "University of Ibadan / Samonda", "state": "Oyo", "lga": "Ibadan North", "lat": 7.4452, "lng": 3.9011},
    {"code": "200263", "area": "Dugbe Commercial District", "state": "Oyo", "lga": "Ibadan North-West", "lat": 7.3889, "lng": 3.8791},
    {"code": "200255", "area": "Ring Road / Challenge", "state": "Oyo", "lga": "Ibadan South-West", "lat": 7.3621, "lng": 3.8642},
    {"code": "200273", "area": "Oluyole Estate", "state": "Oyo", "lga": "Ibadan South-West", "lat": 7.3510, "lng": 3.8710},

    # 5. Ogun State (Zone 1)
    {"code": "110001", "area": "Abeokuta Central / Ake", "state": "Ogun", "lga": "Abeokuta South", "lat": 7.1557, "lng": 3.3486},
    {"code": "110252", "area": "Ibara GRA / Oke-Mosan", "state": "Ogun", "lga": "Abeokuta South", "lat": 7.1421, "lng": 3.3245},
    {"code": "112212", "area": "Ota Industrial Zone / Sango", "state": "Ogun", "lga": "Ado-Odo/Ota", "lat": 6.6912, "lng": 3.2341},
    {"code": "110115", "area": "Mowe / Ibafo Corridor", "state": "Ogun", "lga": "Obafemi Owode", "lat": 6.8123, "lng": 3.4412},

    # 6. Kano State (Zone 7)
    {"code": "700001", "area": "Kano Central / Post Office Rd", "state": "Kano", "lga": "Kano Municipal", "lat": 12.0022, "lng": 8.5920},
    {"code": "700211", "area": "Fagge / Cantonment", "state": "Kano", "lga": "Fagge", "lat": 12.0145, "lng": 8.5321},
    {"code": "700282", "area": "Bompai Industrial Area / GRA", "state": "Kano", "lga": "Nassarawa", "lat": 12.0234, "lng": 8.5671},
    {"code": "700221", "area": "Sabon Gari Market", "state": "Kano", "lga": "Fagge", "lat": 12.0089, "lng": 8.5412},

    # 7. Kaduna State (Zone 8)
    {"code": "800001", "area": "Kaduna Central / Ahmadu Bello Way", "state": "Kaduna", "lga": "Kaduna North", "lat": 10.5105, "lng": 7.4165},
    {"code": "800271", "area": "Malali GRA", "state": "Kaduna", "lga": "Kaduna North", "lat": 10.5512, "lng": 7.4521},
    {"code": "800242", "area": "Barnawa / Narayi", "state": "Kaduna", "lga": "Kaduna South", "lat": 10.4821, "lng": 7.4312},

    # 8. Enugu State (Zone 4)
    {"code": "400001", "area": "Independence Layout / Government House", "state": "Enugu", "lga": "Enugu North", "lat": 6.4413, "lng": 7.5190},
    {"code": "400102", "area": "New Haven / Ogui", "state": "Enugu", "lga": "Enugu North", "lat": 6.4491, "lng": 7.5021},
    {"code": "400271", "area": "GRA Enugu", "state": "Enugu", "lga": "Enugu North", "lat": 6.4589, "lng": 7.4912},

    # 9. Delta State (Zone 3)
    {"code": "320001", "area": "Asaba Central / Nnebisi Rd", "state": "Delta", "lga": "Oshimili South", "lat": 6.1984, "lng": 6.7321},
    {"code": "332001", "area": "Warri Central / Airport Rd", "state": "Delta", "lga": "Warri South", "lat": 5.5174, "lng": 5.7501},
    {"code": "330102", "area": "Effurun / PTI Road", "state": "Delta", "lga": "Uvwie", "lat": 5.5612, "lng": 5.7891},

    # 10. Edo State (Zone 3)
    {"code": "300001", "area": "Benin City Central / Ring Road", "state": "Edo", "lga": "Oredo", "lat": 6.3350, "lng": 5.6037},
    {"code": "300251", "area": "GRA Benin City", "state": "Edo", "lga": "Oredo", "lat": 6.3121, "lng": 5.6212},

    # 11. Anambra State (Zone 4)
    {"code": "420001", "area": "Awka Central / Zik Avenue", "state": "Anambra", "lga": "Awka South", "lat": 6.2209, "lng": 7.0718},
    {"code": "430001", "area": "Onitsha Main Market / Old Market Rd", "state": "Anambra", "lga": "Onitsha North", "lat": 6.1512, "lng": 6.7821},

    # 12. Verified Digital Building-Level Postcodes (Pilot Phase Registry)
    {
        "code": "LAG-IKJ-0012",
        "area": "Ikeja Central Business District",
        "state": "Lagos",
        "lga": "Ikeja",
        "lat": 6.5921,
        "lng": 3.3541,
        "postcode_type": "digital_location",
        "postcode_category": "local_address_reference",
        "verification_status": "local_reference",
        "building_reference": "Plot 4 Ikeja Commercial Plaza",
        "provenance": "NIPOST Digital Address Register 2024",
        "dataset_version": "2024.1",
        "source_owner": "PostcodeLink",
        "source_type": "locally_collected_reference",
    },
    {
        "code": "LAG-LEK-0045",
        "area": "Lekki Phase 1 / Admiralty",
        "state": "Lagos",
        "lga": "Eti-Osa",
        "lat": 6.4421,
        "lng": 3.4751,
        "postcode_type": "digital_location",
        "postcode_category": "local_address_reference",
        "verification_status": "local_reference",
        "building_reference": "Admiralty Mall & Tower",
        "provenance": "NIPOST Digital Address Register 2024",
        "dataset_version": "2024.1",
        "source_owner": "PostcodeLink",
        "source_type": "locally_collected_reference",
    },
    {
        "code": "ABJ-GAR-0101",
        "area": "Garki District Area 2",
        "state": "Abuja (FCT)",
        "lga": "Municipal Area Council",
        "lat": 9.0321,
        "lng": 7.4891,
        "postcode_type": "digital_location",
        "postcode_category": "local_address_reference",
        "verification_status": "local_reference",
        "building_reference": "Federal Commerce House",
        "provenance": "NIPOST Digital Address Register 2024",
        "dataset_version": "2024.1",
        "source_owner": "PostcodeLink",
        "source_type": "locally_collected_reference",
    },
    # National 11-Character 5-Component Digital Postcode Fixtures (Format Demonstration Reference)
    {
        "code": "FC-02-A09-DB-09",
        "area": "Garki District Area 2",
        "state": "Abuja (FCT)",
        "lga": "Municipal Area Council",
        "lat": 9.0321,
        "lng": 7.4891,
        "postcode_type": "digital_location",
        "postcode_category": "local_address_reference",
        "verification_status": "local_reference",
        "building_reference": "Federal Commerce House",
        "provenance": "PostcodeLink National Postcode Format Demonstration Reference",
        "dataset_version": "2026.1",
        "source_owner": "PostcodeLink",
        "source_type": "demonstration_fixture",
        "national_components": {
            "state": "FC",
            "lga": "02",
            "district": "A09",
            "area": "DB",
            "building": "09",
        },
    },
    {
        "code": "LA-01-A04-IK-02",
        "area": "Ikeja Central Business District",
        "state": "Lagos",
        "lga": "Ikeja",
        "lat": 6.5921,
        "lng": 3.3541,
        "postcode_type": "digital_location",
        "postcode_category": "local_address_reference",
        "verification_status": "local_reference",
        "building_reference": "Plot 4 Ikeja Commercial Plaza",
        "provenance": "PostcodeLink National Postcode Format Demonstration Reference",
        "dataset_version": "2026.1",
        "source_owner": "PostcodeLink",
        "source_type": "demonstration_fixture",
        "national_components": {
            "state": "LA",
            "lga": "01",
            "district": "A04",
            "area": "IK",
            "building": "02",
        },
    },
]

# Backward-compatible alias for existing imports
OFFICIAL_POSTCODES = LEGACY_POSTAL_REFERENCES


from backend.app.services.postcodes.normalization import (
    normalize_digital_postcode,
    normalize_string,
    parse_national_digital_postcode,
)


from backend.app.services.postcodes.evidence import (
    classify_verification_evidence,
    record_verification_evidence,
    validate_verification_evidence,
)


def find_postcodes(
    db: Optional[Session],
    state: Optional[str] = None,
    area: Optional[str] = None,
    code: Optional[str] = None,
) -> List[PostcodeRecordSchema]:
    """Search postcodes by state, area, or 6-digit postal code / digital postcode."""
    clean_code = code.strip().upper() if code else ""
    compact_code = clean_code.replace("-", "") if clean_code else ""

    if db:
        from sqlalchemy import func, or_
        query = db.query(PostcodeDirectory).filter(PostcodeDirectory.is_active == True)
        if clean_code:
            query = query.filter(
                or_(
                    PostcodeDirectory.code == clean_code,
                    PostcodeDirectory.code == compact_code,
                    PostcodeDirectory.code.ilike(clean_code),
                    PostcodeDirectory.code.ilike(compact_code),
                    func.replace(PostcodeDirectory.code, "-", "").ilike(compact_code),
                )
            )
        if state:
            query = query.filter(PostcodeDirectory.state.ilike(f"%{state.strip()}%"))
        if area:
            query = query.filter(PostcodeDirectory.area.ilike(f"%{area.strip()}%"))

        db_records = query.limit(50).all()
        if db_records:
            return [PostcodeRecordSchema.model_validate(r) for r in db_records]

    # Reference dataset search
    results: List[PostcodeRecordSchema] = []
    norm_state = normalize_string(state)
    norm_area = normalize_string(area)

    for rec in OFFICIAL_POSTCODES:
        if clean_code:
            rec_c = rec["code"].strip().upper()
            rec_comp = rec_c.replace("-", "")
            if rec_c != clean_code and rec_comp != compact_code:
                continue
        if norm_state and norm_state not in normalize_string(rec["state"]):
            continue
        if norm_area and norm_area not in normalize_string(rec["area"]):
            continue

        results.append(PostcodeRecordSchema(**rec))

    return results


def cleanse_address(
    address: str = "",
    raw_address: Optional[str] = None,
    state_hint: Optional[str] = None,
    postcode_hint: Optional[str] = None,
    area_hint: Optional[str] = None,
    db: Optional[Session] = None,
    client: Optional[Any] = None,
    strict: bool = False,
    live_verify: bool = False,
    verification_mode: Optional[VerificationMode] = None,
) -> CleanseAddressResponse:
    """Cleanse, disambiguate, and validate a Nigerian delivery address against official NIPOST records (Database-first)."""
    target_addr = address or raw_address or ""
    clean_addr = target_addr.strip()
    norm_addr = normalize_string(clean_addr)
    norm_area_hint = normalize_string(area_hint)
    norm_state_hint = normalize_string(state_hint)

    # Validate verification mode if supplied as string directly
    if verification_mode is not None and verification_mode not in ("local_standardization", "nipost_validate", "nipost_strict"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid verification_mode '{verification_mode}'. Supported modes: 'local_standardization', 'nipost_validate', 'nipost_strict'."
        )

    # Validate contradictory flags
    if verification_mode == "local_standardization":
        if strict or live_verify:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Contradictory parameters: verification_mode='local_standardization' cannot be combined with strict or live_verify flags."
            )
        effective_mode: VerificationMode = "local_standardization"
        effective_strict = False
        effective_live_verify = False
    elif verification_mode == "nipost_validate":
        if strict:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Contradictory parameters: verification_mode='nipost_validate' allows fallback and cannot be combined with strict=True. Use 'nipost_strict' for fail-closed verification."
            )
        effective_mode: VerificationMode = "nipost_validate"
        effective_strict = False
        effective_live_verify = True
    elif verification_mode == "nipost_strict":
        effective_mode: VerificationMode = "nipost_strict"
        effective_strict = True
        effective_live_verify = True
    elif strict:
        effective_mode: VerificationMode = "nipost_strict"
        effective_strict = True
        effective_live_verify = True
    elif live_verify:
        effective_mode: VerificationMode = "nipost_validate"
        effective_strict = False
        effective_live_verify = True
    else:
        effective_mode: VerificationMode = "local_standardization"
        effective_strict = False
        effective_live_verify = False

    if client is None:
        from backend.app.services.nipost_client import get_nipost_client
        client = get_nipost_client()

    # 1. Digital Postcode (10-11 character building location) vs Conventional (6-digit area) detection
    extracted_code: Optional[str] = None
    is_digital_location: bool = False
    is_digital_syntax: bool = False

    cleaned_hint = (postcode_hint or "").strip()
    norm_digital = normalize_digital_postcode(cleaned_hint)
    if norm_digital:
        extracted_code = norm_digital
        is_digital_location = True
        is_digital_syntax = True
    elif cleaned_hint:
        extracted_code = cleaned_hint
        is_digital_location = False
    else:
        # Search address string for digital pattern or 6-digit conventional using unified extractor
        found_code, found_type, _ = extract_postcode_from_text(clean_addr)
        if found_code:
            extracted_code = found_code
            is_digital_location = (found_type == "digital_location")
            is_digital_syntax = (found_type == "digital_location")

    postcode_type = "digital_location" if is_digital_location else "conventional_area"
    postcode_category = "official_digital_postcode" if is_digital_location else "legacy_postal_code"
    resolution_level = "building_location" if is_digital_location else "area_district"

    # 2. Live Official NIPOST Verification Workflow
    checked_against_nipost = False
    is_live_nipost = False
    verification_source = "local_nipost_reference_dataset"
    fallback_used = False
    upstream_status: Optional[str] = None
    upstream_error: Optional[str] = None

    client_ready = bool(
        client and (
            getattr(client, "configuration_complete", False)
            or getattr(client, "transport", None) is not None
            or (not hasattr(client, "configuration_complete") and getattr(client, "is_configured", False))
        )
    )

    should_live_verify = bool(effective_live_verify or effective_strict)

    if effective_strict:
        if not extracted_code:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Strict verification mode requires an identifiable postcode in input or address text. Area-only discovery cannot be strictly verified against NIPOST.",
            )
        if not client_ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Official NIPOST API gateway configuration is incomplete (base URL and API credentials required). Strict verification requires live NIPOST connectivity.",
            )

    if should_live_verify and extracted_code and client and getattr(client, "is_configured", False):
        orch = getattr(client, "orchestrated_verify", None)
        orch_res = orch(extracted_code) if callable(orch) else None
        if isinstance(orch_res, tuple) and len(orch_res) == 4:
            nipost_status, live_data, nipost_err, ver_method = orch_res
        else:
            nipost_res = client.lookup_postcode(extracted_code)
            nipost_status = nipost_res.status
            live_data = nipost_res.data
            nipost_err = nipost_res.error_message
            is_val = bool(live_data and (live_data.get("service") == "validator" or not live_data.get("area") or not live_data.get("state")))
            ver_method = "validator" if is_val else "validator_autofill_pipeline"

        if nipost_status == NIPOSTLookupStatus.INVALID_INPUT:
            if effective_strict:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=nipost_err or f"NIPOST rejected postcode '{extracted_code}' as invalid input.",
                )
            return CleanseAddressResponse(
                original_address=clean_addr,
                formatted_address=clean_addr,
                area=area_hint or None,
                state=state_hint or None,
                lga=None,
                postcode=extracted_code,
                postcode_type=postcode_type,
                postcode_category=postcode_category,
                resolution_level=resolution_level,
                postcode_status="invalid",
                verification_status="unverified",
                verification_mode=effective_mode,
                confidence=0.0,
                match_quality_score=0.0,
                postcode_valid=False,
                postcode_exists=False,
                address_consistent=False,
                upstream_contacted=True,
                dispatch_confidence=0.0,
                source="live_nipost_api",
                matched_record=None,
                changes_made=[f"NIPOST API rejected postcode '{extracted_code}' as invalid input."],
                provenance="NIPOST Official National Directory (Rejected Input)",
                checked_against_nipost=True,
                is_live_nipost=False,
                verification_source="live_nipost_api",
                upstream_status=nipost_status.value,
                upstream_error=nipost_err,
                verification_method=ver_method,
            )
        elif nipost_status == NIPOSTLookupStatus.NOT_FOUND:
            if effective_strict:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=nipost_err or f"Postcode '{extracted_code}' not found in official national directory.",
                )
            return CleanseAddressResponse(
                original_address=clean_addr,
                formatted_address=clean_addr,
                area=area_hint or None,
                state=state_hint or None,
                lga=None,
                postcode=extracted_code,
                postcode_type=postcode_type,
                postcode_category=postcode_category,
                resolution_level=resolution_level,
                postcode_status="unverified",
                verification_status="unverified",
                verification_mode=effective_mode,
                confidence=0.0,
                match_quality_score=0.0,
                postcode_valid=False,
                postcode_exists=False,
                address_consistent=False,
                upstream_contacted=True,
                dispatch_confidence=0.0,
                source="live_nipost_api",
                matched_record=None,
                changes_made=[f"Postcode '{extracted_code}' verified as unassigned in official NIPOST directory."],
                provenance="NIPOST Official National Directory (Not Found)",
                checked_against_nipost=True,
                is_live_nipost=False,
                verification_source="live_nipost_api",
                upstream_status=nipost_status.value,
                upstream_error=nipost_err,
                verification_method=ver_method,
            )
        elif nipost_status in (NIPOSTLookupStatus.UNAUTHORIZED, NIPOSTLookupStatus.UNAVAILABLE, NIPOSTLookupStatus.INVALID_RESPONSE):
            if effective_strict:
                if nipost_status == NIPOSTLookupStatus.UNAUTHORIZED:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Official NIPOST API authorization failed: {nipost_err or 'Invalid or expired credentials'}. Fallback disabled in strict verification mode.",
                    )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=f"Official NIPOST API unavailable ({nipost_status.value}): {nipost_err or 'Service unreachable'}. Fallback disabled in strict verification mode.",
                    )
            fallback_used = True
            checked_against_nipost = True
            upstream_status = nipost_status.value
            upstream_error = nipost_err
        elif nipost_status == NIPOSTLookupStatus.FOUND and live_data:
            live_code = live_data.get("code") or extracted_code
            live_area = live_data.get("area")
            live_state = live_data.get("state")
            live_lga = live_data.get("lga")
            live_building = live_data.get("building_reference") or live_data.get("recent_house_address")

            is_validator = (ver_method == "validator" or live_data.get("service") == "validator" or not live_area or not live_state)
            addr_metadata_source = "local_enrichment" if is_validator else "nipost_autofill"

            if is_validator and (not live_area or not live_state):
                loc_cands = find_postcodes(db=db, code=live_code)
                if loc_cands:
                    live_area = live_area or loc_cands[0].area
                    live_state = live_state or loc_cands[0].state
                    live_lga = live_lga or loc_cands[0].lga
                    live_building = live_building or loc_cands[0].building_reference
                else:
                    live_area = live_area or area_hint or None
                    live_state = live_state or state_hint or None

            norm_live_area = normalize_string(live_area)
            norm_live_state = normalize_string(live_state)
            norm_live_lga = normalize_string(live_lga) if live_lga else ""

            area_consistent = True
            if norm_area_hint:
                if (
                    norm_area_hint not in norm_live_area
                    and norm_live_area not in norm_area_hint
                    and norm_area_hint not in norm_live_lga
                ):
                    area_consistent = False

            state_consistent = True
            if norm_state_hint and norm_state_hint != norm_live_state:
                state_consistent = False

            address_consistent = area_consistent and state_consistent
            rec_type = live_data.get("postcode_type", "digital_location" if len(live_code.replace("-", "")) > 6 else "conventional_area")
            rec_cat = "official_digital_postcode" if len(live_code.replace("-", "")) > 6 else "legacy_postal_code"
            rec_res = "building_location" if rec_type == "digital_location" else "area_district"

            upstream_ver = live_data.get("dataset_version") if live_data else None
            upstream_env = getattr(client, "upstream_environment", "unclassified")
            is_production_cred = upstream_env == "production"
            is_sandbox = upstream_env == "sandbox"
            if effective_strict and not is_production_cred:
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
                code=live_code,
                live_res=live_data or {},
                ver_method=ver_method,
                upstream_version=upstream_ver,
                is_validator=is_validator,
                addr_metadata_source=addr_metadata_source,
                is_sandbox=is_sandbox or not is_production_cred,
            )

            if effective_strict and not evidence_persisted:
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
                prov_text = (
                    "NIPOST Sandbox API (Test Key — Sample Dataset; not valid for production verification)"
                )
                ver_status = "sandbox_verified"
                is_official = False
            elif not is_production_cred:
                prov_text = (
                    "Upstream NIPOST Gateway responded with an unclassified credential (not nipost_live_); "
                    "downgraded to local reference per verification integrity policy."
                )
                ver_status = "local_reference"
                is_official = False
            elif not evidence_persisted:
                # Evidence could not be durably recorded: MUST NOT claim official verification
                prov_text = (
                    "NIPOST Live Gateway responded, but audit evidence persistence failed or database unavailable; "
                    "downgraded to local reference per verification integrity policy."
                )
                ver_status = "local_reference"
                is_official = False
            else:
                prov_text = (
                    "NIPOST Official Directory (Existence Verified by Validator; Local Enrichment for Address Attributes)"
                    if is_validator
                    else "NIPOST Official National Directory (Live API)"
                )
                ver_status = "official_verified" if not is_validator else "local_reference"
                is_official = not is_validator

            matched_schema = PostcodeRecordSchema(
                code=live_code,
                area=live_area,
                state=live_state,
                lga=live_lga,
                lat=live_data.get("lat"),
                lng=live_data.get("lng"),
                postcode_type=rec_type,
                postcode_category=rec_cat,
                building_reference=live_building,
                verification_status=ver_status,
                provenance=prov_text,
                dataset_version=upstream_ver,
                source_owner="NIPOST Sandbox" if is_sandbox else ("NIPOST" if is_official_production else "PostcodeLink"),
                source_type="nipost_sandbox" if is_sandbox else ("official_national_directory" if is_official_production else "local_reference"),
                evidence_id=ev_id,
                verification_method=ver_method if (is_official_production or is_sandbox) else "unverified_fallback",
                address_metadata_source=addr_metadata_source,
                valid_until=ev_valid_until,
            )

            if not address_consistent:
                p_status = "conflict"
                conf = 0.50
                disp_conf = 0.45
            elif is_sandbox or not is_official_production:
                p_status = "local_match"
                conf = 0.75
                disp_conf = 0.75
                disp_conf = 0.75
            elif is_official:
                p_status = "verified"
                conf = 0.95
                disp_conf = 0.95
            elif is_validator:
                p_status = "partially_verified"
                conf = 0.80
                disp_conf = 0.75
            else:
                p_status = "local_match"
                conf = 0.75
                disp_conf = 0.75

            if not address_consistent:
                changes_msg = [
                    f"Address Inconsistency: Supplied area '{area_hint or clean_addr}' does not match official postcode {live_code} area '{live_area}, {live_state}'."
                ]
            elif is_sandbox:
                changes_msg = [
                    f"Sandbox check: Postcode {live_code} recognized by NIPOST sandbox dataset ({live_area}, {live_state}); not valid for production verification."
                ]
            elif not is_production_cred:
                changes_msg = [
                    f"Warning: Upstream NIPOST credential is unclassified (requires nipost_live_). Downgraded code {live_code} to local reference."
                ]
            elif not evidence_persisted:
                changes_msg = [
                    f"Warning: Audit evidence persistence failed for code {live_code}. Downgraded from official verification to local reference."
                ]
            elif is_validator:
                changes_msg = [
                    f"Postcode existence verified by official NIPOST Validator for code {live_code}; address metadata enriched from local reference dataset ({live_area}, {live_state})."
                ]
            else:
                changes_msg = [
                    f"Verified against official live NIPOST API code {live_code} for {live_area}, {live_state}"
                ]

            formatted = f"{clean_addr.rstrip(',')}, {live_area}, {live_state} {live_code}" if address_consistent else f"{clean_addr.rstrip(',')}, {live_state}"

            return CleanseAddressResponse(
                original_address=clean_addr,
                formatted_address=formatted,
                area=live_area if address_consistent else (area_hint or live_area),
                state=live_state if address_consistent else (state_hint or live_state),
                lga=live_lga,
                postcode=live_code,
                postcode_type=rec_type,
                postcode_category=rec_cat,
                resolution_level=rec_res,
                postcode_status=p_status,
                verification_status=ver_status,
                verification_mode=effective_mode,
                confidence=conf,
                match_quality_score=disp_conf,
                postcode_valid=True,
                postcode_exists=True,
                address_consistent=address_consistent,
                upstream_contacted=True,
                dispatch_confidence=disp_conf,
                source="nipost_sandbox" if is_sandbox else ("live_nipost_api" if is_official_production else "local_reference_fallback"),
                matched_record=matched_schema,
                changes_made=changes_msg,
                provenance=prov_text,
                source_owner="NIPOST Sandbox" if is_sandbox else ("NIPOST" if is_official_production else "PostcodeLink"),
                source_type="nipost_sandbox" if is_sandbox else ("official_national_directory" if is_official_production else "local_reference"),
                checked_against_nipost=True,
                is_live_nipost=is_official_production,
                verification_source="nipost_sandbox" if is_sandbox else ("live_nipost_api" if is_official_production else "local_nipost_reference_dataset"),
                fallback_used=bool(not is_official_production and not is_sandbox),
                dataset_version=upstream_ver,
                api_integration_version="2026.1",
                evidence_id=ev_id,
                verification_method=ver_method if (is_official_production or is_sandbox) else "unverified_fallback",
                address_metadata_source=addr_metadata_source,
                valid_until=ev_valid_until,
                upstream_status=nipost_status.value,
                is_partial_verification=is_validator,
            )

    # 2. Database-First Candidates Selection
    candidates = []
    source_name = "local_nipost_reference_dataset"
    if db is not None:
        try:
            db_records = db.query(PostcodeDirectory).filter(PostcodeDirectory.is_active == True).all()
            if db_records:
                candidates = [
                    {
                        "code": r.code,
                        "area": r.area,
                        "state": r.state,
                        "lga": r.lga,
                        "lat": r.lat,
                        "lng": r.lng,
                        "postcode_type": getattr(r, "postcode_type", None) if getattr(r, "postcode_type", None) in ["conventional_area", "digital_location"] else ("digital_location" if len((r.code or "").replace("-", "")) > 6 else "conventional_area"),
                        "postcode_category": getattr(r, "postcode_category", "legacy_postal_code"),
                        "verification_status": getattr(r, "verification_status", "local_reference"),
                        "building_reference": getattr(r, "building_reference", None),
                        "provenance": getattr(r, "provenance", "NIPOST 6-Digit Postal Directory (Zone Reference)"),
                        "dataset_version": getattr(r, "dataset_version", "2024.2"),
                        "source_owner": getattr(r, "source_owner", "PostcodeLink"),
                        "source_type": getattr(r, "source_type", "local_reference" if getattr(r, "verification_status", "local_reference") != "official_verified" else "official_registry"),
                    }
                    for r in db_records
                ]
                source_name = "postgresql_postcode_directory"
        except Exception:
            candidates = []

    if not candidates:
        candidates = OFFICIAL_POSTCODES
        source_name = "local_nipost_reference_dataset"

    # 3. Score candidate reference postcodes
    best_match: Optional[Dict[str, Any]] = None
    highest_score = 0
    matched_area = ""

    for rec in candidates:
        score = 0
        norm_rec_area = normalize_string(rec["area"])
        rec_code_norm = rec["code"].strip().upper()

        # Prioritize matching exact code or compact variant
        if extracted_code:
            rec_c = rec["code"].strip().upper()
            ext_c = extracted_code.strip().upper()
            if rec_c == ext_c or rec_c.replace("-", "") == ext_c.replace("-", ""):
                score += 100

        # Substring area matching
        for part in norm_rec_area.split():
            if len(part) >= 4 and part in norm_addr:
                score += 10

        if norm_rec_area in norm_addr:
            score += 25

        if norm_area_hint and (norm_area_hint in norm_rec_area or norm_rec_area in norm_area_hint):
            score += 20

        # State matching
        if norm_state_hint and norm_state_hint in normalize_string(rec["state"]):
            score += 5
        elif normalize_string(rec["state"]) in norm_addr:
            score += 2

        if score > highest_score:
            highest_score = score
            best_match = rec
            matched_area = rec["area"]

    changes: List[str] = []
    postcode_valid = False

    # Check postcode validity against reference registry
    if extracted_code:
        ext_clean = extracted_code.strip().upper()
        ext_compact = ext_clean.replace("-", "")
        matching_code_rec = next(
            (
                r for r in candidates
                if r["code"].strip().upper() == ext_clean
                or r["code"].strip().upper().replace("-", "") == ext_compact
            ),
            None,
        )
        if matching_code_rec:
            postcode_valid = True
            if not best_match or best_match["code"].strip().upper() != matching_code_rec["code"].strip().upper():
                best_match = matching_code_rec
                matched_area = matching_code_rec["area"]

    # CRITICAL: Separate format recognition from directory verification
    # If a digital postcode matches syntax but is not in the directory, it cannot be verified!
    if is_digital_syntax and not postcode_valid:
        changes.append(
            f"Digital building code '{extracted_code}' matches canonical digital format, but was not found in the verified building directory."
        )
        return CleanseAddressResponse(
            original_address=clean_addr,
            formatted_address=clean_addr,
            area=area_hint or "Unverified Location",
            state=state_hint or "Lagos",
            lga=None,
            postcode=extracted_code,
            postcode_type="digital_location",
            postcode_category="local_address_reference",
            resolution_level="building_location",
            postcode_status="unverified",
            verification_status="unverified",
            verification_mode=effective_mode,
            confidence=0.0,
            match_quality_score=0.0,
            postcode_valid=False,
            postcode_exists=False if checked_against_nipost else None,
            address_consistent=False,
            upstream_contacted=checked_against_nipost,
            dispatch_confidence=0.0,
            source=source_name,
            matched_record=None,
            changes_made=changes,
            provenance="Unverified Address Input",
            source_owner="PostcodeLink",
            source_type="unverified_input",
            checked_against_nipost=checked_against_nipost,
            is_live_nipost=False,
            verification_source="local_nipost_reference_dataset",
            fallback_used=fallback_used,
            upstream_status=upstream_status,
            upstream_error=upstream_error,
        )

    # CASE 1: Exact postcode provided and matches reference record
    if (
        best_match
        and extracted_code
        and (
            best_match["code"].strip().upper() == extracted_code.strip().upper()
            or best_match["code"].strip().upper().replace("-", "") == extracted_code.strip().upper().replace("-", "")
        )
    ):
        verified_code = best_match["code"]
        detected_state = best_match["state"]
        detected_lga = best_match.get("lga")
        matched_area_norm = normalize_string(best_match["area"])
        matched_lga_norm = normalize_string(detected_lga) if detected_lga else ""
        rec_type = best_match.get("postcode_type", postcode_type)
        rec_category = best_match.get("postcode_category", postcode_category)
        rec_resolution = "building_location" if (rec_type == "digital_location" or rec_category == "official_digital_postcode") else "area_district"

        # Strict Area Consistency Verification:
        # 1. Compare supplied area hint strictly against the matched postcode record
        area_consistent = True
        if norm_area_hint:
            if (
                norm_area_hint not in matched_area_norm
                and matched_area_norm not in norm_area_hint
                and norm_area_hint not in matched_lga_norm
            ):
                area_consistent = False

        # 2. Check if address text explicitly names an area belonging to a DIFFERENT known postal zone
        if area_consistent:
            for other_rec in candidates:
                other_area_norm = normalize_string(other_rec["area"])
                other_lga_norm = normalize_string(other_rec.get("lga") or "")
                # If another area is in the address text, but has a different code / different LGA
                if len(other_area_norm) >= 4 and other_area_norm in norm_addr:
                    if (
                        other_area_norm not in matched_area_norm
                        and matched_area_norm not in other_area_norm
                        and (not matched_lga_norm or other_lga_norm != matched_lga_norm)
                        and other_rec["code"] != verified_code
                    ):
                        # If other area only appears as part of a street name and the address explicitly contains matched area, allow
                        is_street_name = bool(
                            re.search(
                                rf"\b{re.escape(other_area_norm)}\s+(road|rd|street|st|close|cls|crescent|cres|avenue|ave|way|drive|dr|lane|ln|expressway|exp)\b",
                                norm_addr,
                            )
                        )
                        if is_street_name and (matched_area_norm in norm_addr or matched_lga_norm in norm_addr):
                            continue
                        area_consistent = False
                        break

        state_consistent = True
        if norm_state_hint and norm_state_hint != normalize_string(detected_state):
            state_consistent = False

        address_consistent = area_consistent and state_consistent

        if address_consistent:
            formatted = f"{clean_addr.rstrip(',')}, {matched_area}, {detected_state} {verified_code}"
            
            # Authoritative verification strictly requires:
            # 1. record_ver_status == "official_verified"
            # 2. Backed by active, unexpired VerificationEvidence in DB (provenance gate)
            record_ver_status = best_match.get("verification_status", "local_reference")
            has_valid_evidence = False
            ev_id = None
            ev_valid_until = None
            ev_method = None
            ev_meta_source = "local_enrichment"

            if record_ver_status == "official_verified" and db is not None:
                try:
                    from backend.app.models.verification_evidence import VerificationEvidence
                    ev = db.query(VerificationEvidence).filter(
                        VerificationEvidence.postcode == verified_code,
                        VerificationEvidence.is_active == True,
                    ).order_by(VerificationEvidence.verified_at.desc()).first()
                    if validate_verification_evidence(ev, expected_code=verified_code):
                        has_valid_evidence = True
                        ev_id = ev.id
                        ev_valid_until = ev.valid_until
                        ev_method = ev.verification_method
                        ev_meta_source = ev.address_metadata_source
                except Exception:
                    has_valid_evidence = False

            is_official = bool(record_ver_status == "official_verified" and has_valid_evidence)
            
            p_status = "verified" if is_official else "local_match"
            ver_status = "official_verified" if is_official else "local_reference"
            conf = 0.95 if is_official else 0.75
            disp_conf = 0.95 if is_official else 0.75

            if is_official:
                changes.append(
                    f"Verified against official NIPOST registry code {verified_code} supported by audit evidence {ev_id} for {matched_area}, {detected_state}"
                )
            else:
                changes.append(
                    f"Matched against PostcodeLink local reference registry code {verified_code} for {matched_area}, {detected_state} (unverified with official NIPOST; local reference)"
                )

            best_match_rec = dict(best_match)
            best_match_rec["verification_status"] = ver_status
            best_match_rec["evidence_id"] = ev_id
            best_match_rec["valid_until"] = ev_valid_until
            best_match_rec["verification_method"] = ev_method
            best_match_rec["address_metadata_source"] = ev_meta_source

            return CleanseAddressResponse(
                original_address=clean_addr,
                formatted_address=formatted,
                area=matched_area,
                state=detected_state,
                lga=detected_lga,
                postcode=verified_code,
                postcode_type=rec_type,
                postcode_category=rec_category,
                resolution_level=rec_resolution,
                postcode_status=p_status,
                verification_status=ver_status,
                verification_mode=effective_mode,
                confidence=conf,
                match_quality_score=disp_conf,
                postcode_valid=True,
                postcode_exists=True if is_official else None,
                address_consistent=True,
                upstream_contacted=checked_against_nipost,
                dispatch_confidence=disp_conf,
                source=source_name,
                matched_record=PostcodeRecordSchema(**best_match_rec),
                changes_made=changes,
                provenance=best_match.get("provenance", "NIPOST 6-Digit Postal Directory (Zone Reference)"),
                source_owner=best_match.get("source_owner", "PostcodeLink"),
                source_type=best_match.get("source_type", "local_reference"),
                national_components=best_match.get("national_components"),
                checked_against_nipost=checked_against_nipost,
                is_live_nipost=False,
                verification_source="local_nipost_reference_dataset",
                fallback_used=fallback_used,
                upstream_status=upstream_status,
                upstream_error=upstream_error,
                evidence_id=ev_id,
                verification_method=ev_method,
                address_metadata_source=ev_meta_source,
                valid_until=ev_valid_until,
            )
        else:
            # Conflict detected: Postcode is valid, but supplied area/state contradicts postcode directory!
            changes.append(
                f"Address Inconsistency: Supplied area '{area_hint or clean_addr}' does not match official postcode {verified_code} area '{matched_area}, {detected_state}'."
            )
            formatted = f"{clean_addr.rstrip(',')}, {detected_state}"
            return CleanseAddressResponse(
                original_address=clean_addr,
                formatted_address=formatted,
                area=area_hint or matched_area,
                state=state_hint or detected_state,
                lga=detected_lga,
                postcode=verified_code,
                postcode_type=postcode_type,
                postcode_category=postcode_category,
                resolution_level=resolution_level,
                postcode_status="conflict",
                verification_status="local_reference",
                verification_mode=effective_mode,
                confidence=0.50,
                match_quality_score=0.45,
                postcode_valid=True,
                postcode_exists=None,
                address_consistent=False,
                upstream_contacted=checked_against_nipost,
                dispatch_confidence=0.45,
                source=source_name,
                matched_record=PostcodeRecordSchema(**best_match),
                changes_made=changes,
                provenance=best_match.get("provenance", "NIPOST 6-Digit Postal Directory (Zone Reference)"),
                checked_against_nipost=checked_against_nipost,
                is_live_nipost=False,
                verification_source="local_nipost_reference_dataset",
                fallback_used=fallback_used,
                upstream_status=upstream_status,
                upstream_error=upstream_error,
            )

    # CASE 2: Area recognized in address without explicit matching code (estimated postcode)
    elif best_match and highest_score >= 10:
        suggested_code = best_match["code"]
        detected_state = best_match["state"]
        detected_lga = best_match.get("lga")
        formatted = f"{clean_addr.rstrip(',')}, {matched_area}, {detected_state}"
        changes.append(f"Identified area '{matched_area}' in {detected_state}. Suggested reference postcode is {suggested_code}.")

        return CleanseAddressResponse(
            original_address=clean_addr,
            formatted_address=formatted,
            area=matched_area,
            state=detected_state,
            lga=detected_lga,
            postcode=suggested_code,
            postcode_type=postcode_type,
            postcode_category=postcode_category,
            resolution_level=resolution_level,
            postcode_status="estimated",
            verification_status="estimated",
            verification_mode=effective_mode,
            confidence=0.70,
            match_quality_score=0.68,
            postcode_valid=postcode_valid,
            postcode_exists=None,
            address_consistent=True,
            upstream_contacted=checked_against_nipost,
            dispatch_confidence=0.68,
            source=source_name,
            matched_record=PostcodeRecordSchema(**best_match),
            changes_made=changes,
            provenance=best_match.get("provenance", "NIPOST 6-Digit Postal Directory (Zone Reference)"),
            checked_against_nipost=checked_against_nipost,
            is_live_nipost=False,
            verification_source="local_nipost_reference_dataset",
            fallback_used=fallback_used,
            upstream_status=upstream_status,
            upstream_error=upstream_error,
        )

    # CASE 3: Unrecognized address / No postcode match (UNVERIFIED)
    else:
        changes.append("No matching NIPOST postal record identified. Marked unverified with zero arbitrary fallback.")
        return CleanseAddressResponse(
            original_address=clean_addr,
            formatted_address=clean_addr,
            area=area_hint or None,
            state=state_hint or None,
            lga=None,
            postcode="",
            postcode_type=postcode_type,
            postcode_category=postcode_category,
            resolution_level=resolution_level,
            postcode_status="unverified",
            verification_status="unverified",
            verification_mode=effective_mode,
            confidence=0.20,
            match_quality_score=0.0,
            postcode_valid=False,
            postcode_exists=None,
            address_consistent=False,
            upstream_contacted=checked_against_nipost,
            dispatch_confidence=0.0,
            source=source_name,
            matched_record=None,
            changes_made=changes,
            provenance="Unverified Address Input",
            checked_against_nipost=checked_against_nipost,
            is_live_nipost=False,
            verification_source="local_nipost_reference_dataset",
            fallback_used=fallback_used,
            upstream_status=upstream_status,
            upstream_error=upstream_error,
        )


def get_postcode_coverage_report(
    db: Optional[Session] = None,
    client: Optional[Any] = None,
) -> CoverageReportResponse:
    """Calculate and return data coverage metrics, state distribution, and integration readiness."""
    # 1. Inspect upstream integration
    if client is None:
        try:
            from backend.app.services.nipost_client import get_nipost_client
            client = get_nipost_client()
        except Exception:
            client = None

    integration_status = (
        client.get_integration_status()
        if client and hasattr(client, "get_integration_status")
        else {
            "adapter_installed": True,
            "configuration_complete": False,
            "base_url_set": False,
            "credentials_set": False,
            "auth_scheme": "bearer",
            "connectivity_healthy": False,
            "authentication_verified": False,
            "contract_verified": False,
            "production_authorized": False,
            "status": "unconfigured",
            "display_status": "Adapter Installed (Unconfigured)",
        }
    )

    # 2. Gather dataset counts from DB or fallback dataset
    states_in_dataset_metadata = sorted(list(set(DATASET_METADATA.get("states_covered", []))))
    active_states_set = set()
    states_with_verified_records_set = set()
    demo_states_set = set()
    non_demo_states_set = set()
    records_per_state: Dict[str, int] = {}
    total_records = 0
    records_with_coords = 0
    records_with_valid_evidence = 0
    records_with_expired_evidence = 0
    records_with_rejected_evidence = 0
    records_with_incomplete_evidence = 0
    records_with_invalid_evidence = 0
    records_with_complete_metadata = 0
    legacy_six_digit_records = 0
    national_digital_postcode_records = 0
    digital_records_with_valid_evidence = 0
    local_demonstration_fixtures = 0
    db_records = []

    if db is not None:
        try:
            from backend.app.models.verification_evidence import VerificationEvidence
            q_ev = db.query(VerificationEvidence)
            all_evidence = []
            if hasattr(q_ev, "filter"):
                filtered = q_ev.filter(VerificationEvidence.is_active == True)
                if hasattr(filtered, "all"):
                    res = filtered.all()
                    if isinstance(res, list):
                        all_evidence = res
            if not all_evidence and hasattr(q_ev, "all"):
                res = q_ev.all()
                if isinstance(res, list):
                    all_evidence = res

            valid_evidence_codes = set()
            valid_autofill_evidence_codes = set()
            expired_evidence_codes = set()
            rejected_evidence_codes = set()
            incomplete_evidence_codes = set()
            invalid_evidence_codes = set()

            for ev in all_evidence:
                code_norm = str(getattr(ev, "postcode", None) or getattr(ev, "code", "") or "").strip().upper().replace("-", "").replace(" ", "")
                cls_result = classify_verification_evidence(ev)
                if cls_result == "valid":
                    valid_evidence_codes.add(code_norm)
                    if getattr(ev, "address_metadata_source", None) == "nipost_autofill":
                        valid_autofill_evidence_codes.add(code_norm)
                elif cls_result == "expired":
                    expired_evidence_codes.add(code_norm)
                elif cls_result == "rejected":
                    rejected_evidence_codes.add(code_norm)
                elif cls_result == "incomplete":
                    incomplete_evidence_codes.add(code_norm)
                else:
                    invalid_evidence_codes.add(code_norm)

            records_with_expired_evidence = len(expired_evidence_codes)
            records_with_rejected_evidence = len(rejected_evidence_codes)
            records_with_incomplete_evidence = len(incomplete_evidence_codes)
            records_with_invalid_evidence = len(invalid_evidence_codes)

            q_dir = db.query(PostcodeDirectory)
            db_records = []
            if hasattr(q_dir, "filter"):
                filtered = q_dir.filter(PostcodeDirectory.is_active == True)
                if hasattr(filtered, "all"):
                    res = filtered.all()
                    if isinstance(res, list) and res:
                        db_records = res
            if not db_records and hasattr(q_dir, "all"):
                res = q_dir.all()
                if isinstance(res, list) and res:
                    db_records = res
            if isinstance(db_records, list):
                db_records = [r for r in db_records if getattr(r, "is_active", True) is not False]
            if db_records:
                total_records = len(db_records)
                for r in db_records:
                    st = r.state or "Other"
                    active_states_set.add(st)
                    records_per_state[st] = records_per_state.get(st, 0) + 1

                    # Coordinates
                    if r.lat is not None and r.lng is not None:
                        records_with_coords += 1

                    # Complete metadata
                    if r.area and r.state and r.lga and r.lat is not None and r.lng is not None:
                        records_with_complete_metadata += 1

                    code = (r.code or "").strip()
                    code_norm = code.upper().replace("-", "").replace(" ", "")

                    # Strict digital vs legacy classification
                    if parse_digital_postcode_components(code) is not None:
                        national_digital_postcode_records += 1
                    elif code.isdigit() and len(code) == 6:
                        legacy_six_digit_records += 1

                    # Demonstration / local fixture
                    is_demo = (
                        getattr(r, "source_type", None) == "demonstration_fixture"
                        or r.verification_status in ("local_reference", "synthetic_demo", "demonstration_fixture")
                        or (r.provenance and "Demonstration" in r.provenance)
                    )
                    if is_demo:
                        local_demonstration_fixtures += 1
                        demo_states_set.add(st)
                    else:
                        non_demo_states_set.add(st)

                    # Valid evidence-backed provenance (tied to distinct qualifying directory records)
                    if code_norm in valid_evidence_codes:
                        records_with_valid_evidence += 1
                        states_with_verified_records_set.add(st)
                        if parse_digital_postcode_components(code) is not None:
                            digital_records_with_valid_evidence += 1

        except Exception as db_err:
            logger.warning(f"Error querying PostcodeDirectory or VerificationEvidence for coverage report: {db_err}")

    if total_records == 0:
        total_records = len(OFFICIAL_POSTCODES)
        for r in OFFICIAL_POSTCODES:
            st = r.get("state") or "Other"
            active_states_set.add(st)
            records_per_state[st] = records_per_state.get(st, 0) + 1

            if r.get("lat") is not None and r.get("lng") is not None:
                records_with_coords += 1

            if r.get("area") and r.get("state") and r.get("lga") and r.get("lat") is not None and r.get("lng") is not None:
                records_with_complete_metadata += 1

            code = (r.get("code") or "").strip()
            if parse_digital_postcode_components(code) is not None:
                national_digital_postcode_records += 1
            elif code.isdigit() and len(code) == 6:
                legacy_six_digit_records += 1

            if (
                r.get("source_type") == "demonstration_fixture"
                or r.get("verification_status") in ("local_reference", "synthetic_demo", "demonstration_fixture")
                or (r.get("provenance") and "Demonstration" in r.get("provenance"))
            ):
                local_demonstration_fixtures += 1
                demo_states_set.add(st)
            else:
                non_demo_states_set.add(st)

    states_covered = sorted(list(active_states_set))
    states_with_active_records = states_covered
    states_with_verified_records = sorted(list(states_with_verified_records_set))
    states_with_only_demo_records = sorted(list(demo_states_set - non_demo_states_set))
    dataset_source = "database_directory" if db_records else "demonstration_fallback"

    return CoverageReportResponse(
        edition=DATASET_METADATA.get("edition", "Local Demonstration & Reference Edition"),
        version=DATASET_METADATA.get("version", "2024.2"),
        scope_states_count=len(states_covered),
        states_covered=states_covered,
        states_in_dataset_metadata=states_in_dataset_metadata,
        states_with_active_records=states_with_active_records,
        states_with_verified_records=states_with_verified_records,
        states_with_only_demo_records=states_with_only_demo_records,
        total_reference_records=total_records,
        records_per_state=records_per_state,
        records_with_coordinates=records_with_coords,
        records_with_verified_provenance=records_with_valid_evidence,
        records_with_valid_evidence=records_with_valid_evidence,
        records_with_expired_evidence=records_with_expired_evidence,
        records_with_rejected_evidence=records_with_rejected_evidence,
        records_with_incomplete_evidence=records_with_incomplete_evidence,
        records_with_invalid_evidence=records_with_invalid_evidence,
        records_with_complete_metadata=records_with_complete_metadata,
        legacy_six_digit_records=legacy_six_digit_records,
        national_digital_postcode_records=national_digital_postcode_records,
        format_valid_digital_references=national_digital_postcode_records,
        nipost_confirmed_postcodes=records_with_valid_evidence,
        nipost_confirmed_address_metadata=len(valid_autofill_evidence_codes) if db is not None and "valid_autofill_evidence_codes" in locals() else 0,
        local_demonstration_fixtures=local_demonstration_fixtures,
        digital_building_level_records=digital_records_with_valid_evidence,
        dataset_source=dataset_source,
        source=dataset_source,
        upstream_integration=integration_status,
    )
