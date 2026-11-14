"""Service for Nigerian postal code verification and address cleansing."""
import re
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session
from backend.app.config import settings
from backend.app.models.postcode import PostcodeDirectory
from backend.app.schemas.postcode import PostcodeRecordSchema, CleanseAddressResponse

# Canonical seed data for Nigerian Postcodes (NIPOST standard)
OFFICIAL_POSTCODES: List[Dict[str, Any]] = [
    # Lagos State
    {"code": "100001", "area": "Marina", "state": "Lagos", "lga": "Lagos Island", "lat": 6.4531, "lng": 3.3958},
    {"code": "100211", "area": "Ikeja", "state": "Lagos", "lga": "Ikeja", "lat": 6.5960, "lng": 3.3444},
    {"code": "100271", "area": "Alausa", "state": "Lagos", "lga": "Ikeja", "lat": 6.6190, "lng": 3.3580},
    {"code": "101233", "area": "Victoria Island", "state": "Lagos", "lga": "Iru-Victoria Island", "lat": 6.4281, "lng": 3.4219},
    {"code": "101241", "area": "Lekki Phase 1", "state": "Lagos", "lga": "Eti-Osa", "lat": 6.4474, "lng": 3.4723},
    {"code": "101245", "area": "Ikoyi", "state": "Lagos", "lga": "Eti-Osa", "lat": 6.4500, "lng": 3.4333},
    {"code": "100253", "area": "Yaba", "state": "Lagos", "lga": "Lagos Mainland", "lat": 6.5095, "lng": 3.3711},
    {"code": "100261", "area": "Surulere", "state": "Lagos", "lga": "Surulere", "lat": 6.4975, "lng": 3.3553},
    {"code": "102213", "area": "Festac Town", "state": "Lagos", "lga": "Amuwo-Odofin", "lat": 6.4674, "lng": 3.2829},
    {"code": "100276", "area": "Ogba", "state": "Lagos", "lga": "Ikeja", "lat": 6.6342, "lng": 3.3421},
    {"code": "100265", "area": "Oshodi", "state": "Lagos", "lga": "Oshodi-Isolo", "lat": 6.5540, "lng": 3.3486},
    {"code": "101283", "area": "Ajah", "state": "Lagos", "lga": "Eti-Osa", "lat": 6.4698, "lng": 3.5684},
    {"code": "100218", "area": "Agege", "state": "Lagos", "lga": "Agege", "lat": 6.6180, "lng": 3.3209},
    {"code": "100281", "area": "Maryland", "state": "Lagos", "lga": "Kosofe", "lat": 6.5724, "lng": 3.3670},
    {"code": "100242", "area": "Gbagada", "state": "Lagos", "lga": "Kosofe", "lat": 6.5562, "lng": 3.3881},
    {"code": "100216", "area": "Anthony Village", "state": "Lagos", "lga": "Kosofe", "lat": 6.5688, "lng": 3.3712},
    {"code": "102215", "area": "Satellite Town", "state": "Lagos", "lga": "Amuwo-Odofin", "lat": 6.4428, "lng": 3.2647},
    {"code": "103241", "area": "Epe", "state": "Lagos", "lga": "Epe", "lat": 6.5841, "lng": 3.9834},
    {"code": "104101", "area": "Ikorodu", "state": "Lagos", "lga": "Ikorodu", "lat": 6.6194, "lng": 3.5105},
    {"code": "102102", "area": "Badagry", "state": "Lagos", "lga": "Badagry", "lat": 6.4150, "lng": 2.8813},
    
    # Abuja FCT
    {"code": "900211", "area": "Garki", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.0300, "lng": 7.4900},
    {"code": "900241", "area": "Wuse", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.0700, "lng": 7.4700},
    {"code": "900271", "area": "Maitama", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.0882, "lng": 7.4934},
    {"code": "900281", "area": "Asokoro", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.0436, "lng": 7.5255},
    {"code": "900108", "area": "Jabi", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.0722, "lng": 7.4258},
    {"code": "900104", "area": "Gwarinpa", "state": "Abuja FCT", "lga": "Municipal", "lat": 9.1124, "lng": 7.3980},
    {"code": "900102", "area": "Kubwa", "state": "Abuja FCT", "lga": "Bwari", "lat": 9.1550, "lng": 7.3360},
    
    # Rivers State
    {"code": "500272", "area": "Old GRA", "state": "Rivers", "lga": "Port Harcourt", "lat": 4.8156, "lng": 7.0498},
    {"code": "500261", "area": "Diobu", "state": "Rivers", "lga": "Port Harcourt", "lat": 4.7925, "lng": 6.9980},
    {"code": "500211", "area": "Trans-Amadi", "state": "Rivers", "lga": "Port Harcourt", "lat": 4.8236, "lng": 7.0345},
    
    # Oyo State
    {"code": "200221", "area": "Bodija", "state": "Oyo", "lga": "Ibadan North", "lat": 7.4325, "lng": 3.9056},
    {"code": "200252", "area": "Dugbe", "state": "Oyo", "lga": "Ibadan North-West", "lat": 7.3889, "lng": 3.8767},
    {"code": "200284", "area": "Ring Road", "state": "Oyo", "lga": "Ibadan South-West", "lat": 7.3554, "lng": 3.8642},
    
    # Kano State
    {"code": "700211", "area": "Nassarawa", "state": "Kano", "lga": "Nassarawa", "lat": 11.9964, "lng": 8.5422},
    {"code": "700221", "area": "Fagge", "state": "Kano", "lga": "Fagge", "lat": 12.0125, "lng": 8.5284},
]


def normalize_string(text: Optional[str]) -> str:
    if not text:
        return ""
    # lowercase, strip accents/special chars, normalize spaces
    s = text.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def find_postcodes(db: Optional[Session], state: Optional[str] = None, area: Optional[str] = None, code: Optional[str] = None) -> List[PostcodeRecordSchema]:
    """Search postcodes by state, area, or 6-digit postal code."""
    # First query database if available
    results: List[PostcodeRecordSchema] = []
    
    if db:
        query = db.query(PostcodeDirectory).filter(PostcodeDirectory.is_active == True)
        if code:
            query = query.filter(PostcodeDirectory.code == code.strip())
        if state:
            query = query.filter(PostcodeDirectory.state.ilike(f"%{state.strip()}%"))
        if area:
            query = query.filter(PostcodeDirectory.area.ilike(f"%{area.strip()}%"))
            
        db_records = query.limit(50).all()
        if db_records:
            return [PostcodeRecordSchema.model_validate(r) for r in db_records]

    # Fallback to in-memory official directory
    norm_state = normalize_string(state)
    norm_area = normalize_string(area)
    norm_code = code.strip() if code else ""

    for rec in OFFICIAL_POSTCODES:
        if norm_code and rec["code"] != norm_code:
            continue
        if norm_state and norm_state not in normalize_string(rec["state"]):
            continue
        if norm_area and norm_area not in normalize_string(rec["area"]):
            continue
            
        results.append(PostcodeRecordSchema(**rec))

    return results


def cleanse_address(address: str, state_hint: Optional[str] = None, postcode_hint: Optional[str] = None, db: Optional[Session] = None) -> CleanseAddressResponse:
    """Intelligently cleanses, normalizes, and verifies a Nigerian address against postal authority records."""
    norm_addr = normalize_string(address)
    tokens = set(norm_addr.split())
    
    best_match: Optional[Dict[str, Any]] = None
    highest_score = 0
    matched_area = ""

    # Check against known postcode areas
    for rec in OFFICIAL_POSTCODES:
        area_norm = normalize_string(rec["area"])
        area_tokens = area_norm.split()
        
        # Check if full area name in address or tokens match
        score = 0
        if area_norm in norm_addr:
            score += 10
        elif any(tok in tokens for tok in area_tokens if len(tok) > 2):
            score += 4

        # State bonus
        if state_hint and normalize_string(state_hint) == normalize_string(rec["state"]):
            score += 3
        elif normalize_string(rec["state"]) in norm_addr:
            score += 2
            
        # Postcode bonus
        if postcode_hint and rec["code"] == postcode_hint.strip():
            score += 5

        if score > highest_score:
            highest_score = score
            best_match = rec
            matched_area = rec["area"]

    changes: List[str] = []
    
    # Check for 6-digit postcode pattern in address
    found_postcode = re.findall(r"\b\d{6}\b", address)
    extracted_code = found_postcode[0] if found_postcode else None

    if best_match and highest_score >= 10:
        # High confidence match
        verified_code = best_match["code"]
        detected_state = best_match["state"]
        detected_lga = best_match.get("lga")
        postcode_status = "verified"
        confidence = 0.95
        
        formatted = f"{address.strip().rstrip(',')}, {matched_area}, {detected_state} {verified_code}"
        changes.append(f"Linked verified NIPOST code {verified_code} for {matched_area}, {detected_state}")
        
        return CleanseAddressResponse(
            original_address=address,
            formatted_address=formatted,
            area=matched_area,
            state=detected_state,
            lga=detected_lga,
            postcode=verified_code,
            postcode_status=postcode_status,
            confidence=confidence,
            source="postcodelink_nipost_registry",
            matched_record=PostcodeRecordSchema(**best_match),
            changes_made=changes
        )
    elif best_match and highest_score >= 4:
        # Estimated / partial match
        detected_code = best_match["code"]
        detected_state = best_match["state"]
        postcode_status = "estimated"
        confidence = 0.70
        changes.append(f"Estimated postcode {detected_code} based on area token match: {matched_area}")
        formatted = f"{address.strip().rstrip(',')}, {detected_state}"
        
        return CleanseAddressResponse(
            original_address=address,
            formatted_address=formatted,
            area=matched_area,
            state=detected_state,
            lga=best_match.get("lga"),
            postcode=detected_code,
            postcode_status=postcode_status,
            confidence=confidence,
            source="postcodelink_nipost_registry",
            matched_record=PostcodeRecordSchema(**best_match),
            changes_made=changes
        )
    else:
        # Unverified
        fallback_state = state_hint.strip() if state_hint else "Lagos"
        changes.append("No authoritative 6-digit postal code found for specified location; flagged unverified")
        return CleanseAddressResponse(
            original_address=address,
            formatted_address=address.strip(),
            area="Unknown Area",
            state=fallback_state,
            lga=None,
            postcode=extracted_code or "100001",
            postcode_status="unverified",
            confidence=0.30,
            source="unverified_raw",
            matched_record=None,
            changes_made=changes
        )
