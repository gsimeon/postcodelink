"""Official NIPOST (Nigerian Postal Service) API Client Adapter.

Provides resilient integration with official NIPOST national postcode endpoints:
- Code lookup (6-digit legacy and 11-character digital postcodes)
- Address verification and digital building geocoding
- Resilient fallback to local reference dataset on API outage or timeout
"""
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import httpx
from backend.app.config import settings

logger = logging.getLogger("nipost_client")


class NIPOSTLookupStatus(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
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
    ):
        raw_url = base_url if base_url is not None else (settings.NIPOST_API_BASE_URL or settings.NIPOST_API_URL or "")
        self.base_url = raw_url.strip().rstrip("/")
        self.api_key = (api_key if api_key is not None else settings.NIPOST_API_KEY).strip()
        self.timeout = timeout or getattr(settings, "NIPOST_TIMEOUT_SECONDS", 5.0)
        self.transport = transport

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
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["x-api-key"] = self.api_key
        return headers

    def lookup_postcode(self, code: str) -> NIPOSTLookupResult:
        """Query official NIPOST API for a 6-digit or 11-character digital postcode with status discrimination."""
        if not self.is_configured or not code:
            return NIPOSTLookupResult(
                status=NIPOSTLookupStatus.UNAVAILABLE,
                error_message="NIPOST API base URL is not configured.",
            )

        clean_code = code.strip().upper()
        url = f"{self.base_url}/api/v1/postcodes/lookup"
        params = {"code": clean_code}

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
                    match_record = None
                    if isinstance(data, dict):
                        matches = data.get("matches")
                        if isinstance(matches, list) and len(matches) > 0:
                            match_record = matches[0]
                        elif "code" in data:
                            match_record = data

                    if not match_record or not isinstance(match_record, dict):
                        return NIPOSTLookupResult(
                            status=NIPOSTLookupStatus.INVALID_RESPONSE,
                            http_status=200,
                            data=data if isinstance(data, dict) else None,
                            error_message="Response payload missing postcode record.",
                        )

                    # Strict Schema Validation: must include code, area, and state
                    ret_code = str(match_record.get("code", "")).strip().upper()
                    ret_area = str(match_record.get("area", "")).strip()
                    ret_state = str(match_record.get("state", "")).strip()

                    if not ret_code or not ret_area or not ret_state:
                        return NIPOSTLookupResult(
                            status=NIPOSTLookupStatus.INVALID_RESPONSE,
                            http_status=200,
                            data=match_record,
                            error_message="Response record missing mandatory fields (code, area, state).",
                        )

                    # Verify returned code matches requested code (normalized comparison)
                    norm_req = clean_code.replace("-", "").replace(" ", "")
                    norm_ret = ret_code.replace("-", "").replace(" ", "")
                    if norm_req != norm_ret:
                        return NIPOSTLookupResult(
                            status=NIPOSTLookupStatus.INVALID_RESPONSE,
                            http_status=200,
                            data=match_record,
                            error_message=f"Returned postcode '{ret_code}' does not match requested code '{clean_code}'.",
                        )

                    return NIPOSTLookupResult(
                        status=NIPOSTLookupStatus.FOUND,
                        data=match_record,
                        http_status=200,
                    )

                elif resp.status_code == 404:
                    logger.info(f"NIPOST API: Postcode '{clean_code}' not found (404).")
                    return NIPOSTLookupResult(
                        status=NIPOSTLookupStatus.NOT_FOUND,
                        http_status=404,
                        error_message=f"Postcode '{clean_code}' does not exist in official NIPOST directory.",
                    )
                elif resp.status_code in (401, 403):
                    logger.error(f"NIPOST API authorization error ({resp.status_code}) querying '{clean_code}'.")
                    return NIPOSTLookupResult(
                        status=NIPOSTLookupStatus.UNAUTHORIZED,
                        http_status=resp.status_code,
                        error_message="Official NIPOST API authorization failed: verify license credentials.",
                    )
                else:
                    logger.warning(f"NIPOST API non-200 response ({resp.status_code}) for '{clean_code}': {resp.text}")
                    return NIPOSTLookupResult(
                        status=NIPOSTLookupStatus.UNAVAILABLE,
                        http_status=resp.status_code,
                        error_message="The official NIPOST verification gateway returned an unexpected response.",
                    )
        except httpx.TimeoutException:
            logger.warning(f"NIPOST API timeout after {self.timeout}s looking up '{clean_code}'.")
            return NIPOSTLookupResult(
                status=NIPOSTLookupStatus.UNAVAILABLE,
                http_status=504,
                error_message="The official NIPOST verification gateway timed out.",
            )
        except Exception as exc:
            logger.warning(f"NIPOST API connection error looking up '{clean_code}': {exc}.")
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
