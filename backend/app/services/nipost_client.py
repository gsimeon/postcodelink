"""Official NIPOST (Nigerian Postal Service) API Client Adapter.

Provides resilient integration with official NIPOST national postcode endpoints:
- Code lookup (6-digit legacy and 11-character digital postcodes)
- Address verification and digital building geocoding
- Resilient fallback to local reference dataset on API outage or timeout
"""
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple
import httpx
from backend.app.config import settings

logger = logging.getLogger("nipost_client")


class NIPOSTLookupStatus(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    INVALID_INPUT = "INVALID_INPUT"
    UNAVAILABLE = "UNAVAILABLE"
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_RESPONSE = "INVALID_RESPONSE"


@dataclass
class NIPOSTLookupResult:
    status: NIPOSTLookupStatus
    data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    http_status: Optional[int] = None

    @property
    def is_found(self) -> bool:
        return self.status == NIPOSTLookupStatus.FOUND

    def __bool__(self) -> bool:
        return self.is_found

    def __getitem__(self, key: str) -> Any:
        if self.data and isinstance(self.data, dict) and key in self.data:
            return self.data[key]
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return bool(self.data and isinstance(self.data, dict) and key in self.data)


class NIPOSTClient:
    """Client for querying official NIPOST National Digital Postcode Directory APIs."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
        transport: Optional[httpx.BaseTransport] = None,
        lookup_path: Optional[str] = None,
        auth_scheme: Optional[str] = None,
        query_param: Optional[str] = None,
    ):
        raw_url = base_url if base_url is not None else (settings.NIPOST_API_BASE_URL or settings.NIPOST_API_URL or "")
        self.base_url = raw_url.strip().rstrip("/")
        self.api_key = (api_key if api_key is not None else settings.NIPOST_API_KEY).strip()
        self.timeout = timeout or getattr(settings, "NIPOST_TIMEOUT_SECONDS", 5.0)
        self.transport = transport
        self.lookup_path = lookup_path or getattr(settings, "NIPOST_LOOKUP_PATH", "/v1/lookup")
        self.auth_scheme = (auth_scheme or getattr(settings, "NIPOST_AUTH_SCHEME", "bearer")).lower()
        self.query_param = query_param or getattr(settings, "NIPOST_QUERY_PARAM", "code")

    @property
    def is_configured(self) -> bool:
        """Returns True if live NIPOST API base URL is configured."""
        return bool(self.base_url)

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"PostcodeLink-Nigeria/{settings.VERSION}",
        }
        if self.api_key:
            if self.auth_scheme in ("api_key", "api_key_header", "x-api-key"):
                headers["x-api-key"] = self.api_key
            elif self.auth_scheme == "both":
                headers["Authorization"] = f"Bearer {self.api_key}"
                headers["x-api-key"] = self.api_key
            else:
                headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _adapt_nipost_payload(data: Any, clean_code: str) -> Tuple[NIPOSTLookupStatus, Optional[Dict[str, Any]], Optional[str]]:
        """Adapt diverse official NIPOST response schemas into standardized PostcodeLink dictionary.
        
        Supports:
        1. Official NIPOST developer lookup schema (/v1/lookup):
           {"postcode": "...", "valid": true, "administrative_address": {"state": "...", "lga": "...", "district": "..."}, "recent_house_address": "..."}
        2. PostcodeLink direct gateway schema:
           {"code": "...", "area": "...", "state": "...", "lga": "...", "lat": ..., "lng": ...}
        3. Match array schema:
           {"matches": [{"code": "...", "area": "...", "state": "..."}]}
        4. Official invalid/not found response schema:
           {"valid": false, "postcode": "...", "message": "..."} or {"status": "NOT_FOUND"} or {"matches": []}
        """
        if not isinstance(data, dict):
            return NIPOSTLookupStatus.INVALID_RESPONSE, None, "NIPOST API returned non-dict JSON response."

        # Check explicit negative validity
        status_str = str(data.get("status", "")).strip().upper()
        error_code = str(data.get("error_code") or data.get("code") or "").strip().upper()
        detail_str = str(data.get("detail") or data.get("message") or data.get("error") or "").lower()

        # 1. Explicit invalid input / format classification
        if (
            status_str in ("INVALID_INPUT", "INVALID_FORMAT", "BAD_REQUEST", "MALFORMED_CODE")
            or error_code in ("INVALID_INPUT", "INVALID_FORMAT", "INVALID_CODE", "VALIDATION_ERROR")
            or "invalid postcode format" in detail_str
            or "code must be" in detail_str
            or "invalid input" in detail_str
        ):
            return NIPOSTLookupStatus.INVALID_INPUT, data, f"Postcode '{clean_code}' has invalid format or rejected syntax: {detail_str or 'invalid input'}."

        # 2. Explicit authoritative non-existence check
        if (
            data.get("valid") is False
            or status_str in ("NOT_FOUND", "POSTCODE_NOT_FOUND")
            or error_code in ("NOT_FOUND", "POSTCODE_NOT_FOUND", "ERR_POSTCODE_NOT_FOUND")
            or data.get("found") is False
        ):
            return NIPOSTLookupStatus.NOT_FOUND, data, f"Postcode '{clean_code}' is confirmed not found in official NIPOST directory."

        # Extract record container
        matches = data.get("matches")
        if isinstance(matches, list):
            if len(matches) == 0:
                return NIPOSTLookupStatus.NOT_FOUND, data, f"Postcode '{clean_code}' does not exist in official directory."
            match_record = matches[0]
        else:
            match_record = data

        if not isinstance(match_record, dict):
            return NIPOSTLookupStatus.INVALID_RESPONSE, None, "Response payload missing postcode record."

        # Extract code (official: postcode, gateway: code)
        ret_code = str(match_record.get("code") or match_record.get("postcode") or "").strip().upper()

        # Extract state, area, lga
        ret_state = str(match_record.get("state") or "").strip()
        ret_area = str(match_record.get("area") or match_record.get("district") or "").strip()
        ret_lga = str(match_record.get("lga") or "").strip()
        building_ref = match_record.get("building_reference") or match_record.get("recent_house_address") or match_record.get("street")

        # Parse nested administrative_address if state or area missing
        admin_addr = match_record.get("administrative_address")
        if isinstance(admin_addr, dict):
            ret_state = ret_state or str(admin_addr.get("state") or "").strip()
            ret_area = ret_area or str(admin_addr.get("district") or admin_addr.get("area") or "").strip()
            ret_lga = ret_lga or str(admin_addr.get("lga") or "").strip()
        elif isinstance(admin_addr, str) and (not ret_state or not ret_area):
            parts = [p.strip() for p in admin_addr.split(",") if p.strip()]
            if len(parts) >= 2:
                ret_area = ret_area or parts[0]
                ret_state = ret_state or parts[-1]
                if len(parts) >= 3:
                    ret_lga = ret_lga or parts[1]

        # Mandatory fields check
        if not ret_code or not ret_area or not ret_state:
            return NIPOSTLookupStatus.INVALID_RESPONSE, match_record, "Response record missing mandatory fields (code/postcode, area/district, state)."

        # Code match verification (normalized comparison)
        norm_req = clean_code.replace("-", "").replace(" ", "")
        norm_ret = ret_code.replace("-", "").replace(" ", "")
        if norm_req != norm_ret:
            return NIPOSTLookupStatus.INVALID_RESPONSE, match_record, f"Returned postcode '{ret_code}' does not match requested code '{clean_code}'."

        dataset_ver = match_record.get("dataset_version") or data.get("dataset_version")
        postcode_type = match_record.get("postcode_type") or ("digital_location" if len(clean_code.replace("-", "")) > 6 else "conventional_area")

        adapted_record = {
            "code": ret_code,
            "area": ret_area,
            "state": ret_state,
            "lga": ret_lga or None,
            "lat": match_record.get("lat") or match_record.get("latitude"),
            "lng": match_record.get("lng") or match_record.get("longitude"),
            "building_reference": str(building_ref).strip() if building_ref else None,
            "recent_house_address": str(building_ref).strip() if building_ref else None,
            "administrative_address": admin_addr if isinstance(admin_addr, dict) else None,
            "dataset_version": dataset_ver,
            "postcode_type": postcode_type,
            "valid": True,
        }
        return NIPOSTLookupStatus.FOUND, adapted_record, None

    def lookup_postcode(self, code: str) -> NIPOSTLookupResult:
        """Query official NIPOST API for a 6-digit or 11-character digital postcode with status discrimination."""
        if not self.is_configured or not code:
            return NIPOSTLookupResult(
                status=NIPOSTLookupStatus.UNAVAILABLE,
                error_message="NIPOST API base URL is not configured.",
            )

        clean_code = code.strip().upper()
        path = self.lookup_path.strip().lstrip("/")
        url = f"{self.base_url}/{path}"
        # Provide verified query parameters (configurable via NIPOST_QUERY_PARAM, default 'code')
        if self.query_param == "both":
            params = {"code": clean_code, "postcode": clean_code}
        else:
            params = {self.query_param: clean_code}

        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                resp = client.get(url, params=params, headers=self._get_headers())
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception:
                        return NIPOSTLookupResult(
                            status=NIPOSTLookupStatus.INVALID_RESPONSE,
                            http_status=200,
                            error_message="NIPOST API returned non-JSON response.",
                        )

                    status_res, adapted_rec, err_msg = self._adapt_nipost_payload(data, clean_code)
                    if status_res == NIPOSTLookupStatus.FOUND:
                        return NIPOSTLookupResult(
                            status=NIPOSTLookupStatus.FOUND,
                            data=adapted_rec,
                            http_status=200,
                        )
                    elif status_res == NIPOSTLookupStatus.INVALID_INPUT:
                        logger.warning(f"NIPOST API: Postcode prefix '{clean_code[:3]}***' rejected as invalid format.")
                        return NIPOSTLookupResult(
                            status=NIPOSTLookupStatus.INVALID_INPUT,
                            http_status=200,
                            data=data if isinstance(data, dict) else None,
                            error_message=err_msg or f"Postcode '{clean_code}' has invalid format.",
                        )
                    elif status_res == NIPOSTLookupStatus.NOT_FOUND:
                        logger.info(f"NIPOST API: Postcode prefix '{clean_code[:3]}***' verified as not found in directory.")
                        return NIPOSTLookupResult(
                            status=NIPOSTLookupStatus.NOT_FOUND,
                            http_status=200,
                            data=data if isinstance(data, dict) else None,
                            error_message=err_msg or f"Postcode '{clean_code}' does not exist in official NIPOST directory.",
                        )
                    else:
                        return NIPOSTLookupResult(
                            status=status_res,
                            http_status=200,
                            data=adapted_rec or (data if isinstance(data, dict) else None),
                            error_message=err_msg,
                        )

                elif resp.status_code == 404:
                    # Critical security & routing check:
                    # Differentiate authoritative postcode non-existence from route / endpoint 404.
                    # Generic {"detail": "Not Found"}, {"message": "Not Found"}, or HTML proxy 404
                    # are NOT authoritative and must be classified as UNAVAILABLE (route error).
                    is_authoritative_not_found = False
                    content_type = resp.headers.get("content-type", "").lower()

                    if "application/json" in content_type or (resp.text and resp.text.strip().startswith("{")):
                        try:
                            data = resp.json()
                            if isinstance(data, dict):
                                err_code = str(data.get("error_code") or data.get("code") or "").upper()
                                status_val = str(data.get("status", "")).upper()
                                detail = str(data.get("detail", "")).strip()
                                message = str(data.get("message", "")).strip()
                                detail_lower = detail.lower()
                                message_lower = message.lower()

                                # Reject generic 404 messages from routers or reverse proxies
                                is_generic_404 = (
                                    detail_lower in ("not found", "resource not found", "route not found", "")
                                    and message_lower in ("not found", "resource not found", "route not found", "")
                                    and not err_code
                                    and not status_val
                                    and data.get("valid") is None
                                )

                                if not is_generic_404:
                                    # Must contain documented NIPOST error code or explicit postcode-level search result
                                    if (
                                        err_code in ("POSTCODE_NOT_FOUND", "NOT_FOUND", "ERR_POSTCODE_NOT_FOUND")
                                        or status_val in ("NOT_FOUND", "POSTCODE_NOT_FOUND")
                                        or (data.get("valid") is False and (data.get("postcode") or data.get("code")))
                                        or ("postcode" in detail_lower and "not found" in detail_lower)
                                        or ("postcode" in message_lower and "not found" in message_lower)
                                        or "does not exist in official" in detail_lower
                                        or "does not exist in official" in message_lower
                                    ):
                                        is_authoritative_not_found = True
                        except Exception:
                            is_authoritative_not_found = False

                    if is_authoritative_not_found:
                        logger.info(f"NIPOST API: Postcode prefix '{clean_code[:3]}***' confirmed not found in national directory (404).")
                        return NIPOSTLookupResult(
                            status=NIPOSTLookupStatus.NOT_FOUND,
                            http_status=404,
                            error_message=f"Postcode '{clean_code}' does not exist in official NIPOST directory.",
                        )
                    else:
                        logger.warning(
                            f"NIPOST API endpoint routing error (HTTP 404) for prefix '{clean_code[:3]}***'. "
                            "Upstream endpoint path may be invalid or reverse proxy returned route 404."
                        )
                        return NIPOSTLookupResult(
                            status=NIPOSTLookupStatus.UNAVAILABLE,
                            http_status=404,
                            error_message="The official NIPOST verification gateway returned an endpoint routing error (HTTP 404).",
                        )

                elif resp.status_code in (400, 422):
                    logger.warning(f"NIPOST API validation error ({resp.status_code}) during verification request.")
                    return NIPOSTLookupResult(
                        status=NIPOSTLookupStatus.INVALID_INPUT,
                        http_status=resp.status_code,
                        error_message=f"The official NIPOST verification gateway rejected postcode format '{clean_code}'.",
                    )

                elif resp.status_code in (401, 403):
                    logger.error(f"NIPOST API authorization error ({resp.status_code}) during verification request.")
                    return NIPOSTLookupResult(
                        status=NIPOSTLookupStatus.UNAUTHORIZED,
                        http_status=resp.status_code,
                        error_message="Official NIPOST API authorization failed: verify license credentials.",
                    )
                else:
                    logger.warning(f"NIPOST API non-200 response ({resp.status_code}) during verification request.")
                    return NIPOSTLookupResult(
                        status=NIPOSTLookupStatus.UNAVAILABLE,
                        http_status=resp.status_code,
                        error_message="The official NIPOST verification gateway returned an unexpected response.",
                    )
        except httpx.TimeoutException:
            logger.warning(f"NIPOST API timeout after {self.timeout}s during verification request.")
            return NIPOSTLookupResult(
                status=NIPOSTLookupStatus.UNAVAILABLE,
                http_status=504,
                error_message="The official NIPOST verification gateway timed out.",
            )
        except Exception as exc:
            logger.warning(f"NIPOST API connection error during verification request ({type(exc).__name__}).")
            return NIPOSTLookupResult(
                status=NIPOSTLookupStatus.UNAVAILABLE,
                http_status=503,
                error_message="The official NIPOST verification gateway is temporarily unavailable.",
            )

    def validate_address(
        self,
        address: str,
        state: Optional[str] = None,
        area: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Validate a Nigerian delivery address against the live NIPOST validation endpoint."""
        if not self.is_configured or not address:
            return None

        url = f"{self.base_url}/api/v1/address/validate"
        payload = {
            "address": address.strip(),
            "state": state.strip() if state else None,
            "area": area.strip() if area else None,
        }

        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                resp = client.post(url, json=payload, headers=self._get_headers())
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 404:
                    return None
                else:
                    logger.warning(f"NIPOST API address validation returned status {resp.status_code}.")
                    return None
        except httpx.TimeoutException:
            logger.warning(f"NIPOST API timeout during address validation (timeout={self.timeout}s). Falling back to local cleanser.")
            return None
        except Exception:
            logger.warning("NIPOST API connection error during address validation. Falling back to local cleanser.")
            return None

    def autofill_postcode(self, area: str, state: str) -> Optional[str]:
        """Query NIPOST for the primary postcode assigned to a specific area and state."""
        if not self.is_configured or not area or not state:
            return None

        url = f"{self.base_url}/api/v1/postcodes/autofill"
        params = {"area": area.strip(), "state": state.strip()}

        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                resp = client.get(url, params=params, headers=self._get_headers())
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("postcode") or data.get("code")
                return None
        except Exception:
            logger.warning("NIPOST API connection error during postcode autofill query.")
            return None


# Module-level default client
nipost_client = NIPOSTClient()


def get_nipost_client() -> NIPOSTClient:
    """Dependency injector / factory for NIPOSTClient."""
    return nipost_client
