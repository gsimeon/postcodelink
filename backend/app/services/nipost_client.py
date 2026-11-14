"""Official NIPOST (Nigerian Postal Service) API Client Adapter.

Provides resilient integration with official NIPOST national postcode endpoints:
- Code lookup (6-digit legacy and 11-character digital postcodes)
- Address verification and digital building geocoding
- Resilient fallback to local reference dataset on API outage or timeout
"""
import logging
from typing import Optional, Dict, Any, List
import httpx
from backend.app.config import settings

logger = logging.getLogger("nipost_client")


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

    def lookup_postcode(self, code: str) -> Optional[Dict[str, Any]]:
        """Query official NIPOST API for a 6-digit or 11-character digital postcode."""
        if not self.is_configured or not code:
            return None

        clean_code = code.strip().upper()
        url = f"{self.base_url}/api/v1/postcodes/lookup"
        params = {"code": clean_code}

        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                resp = client.get(url, params=params, headers=self._get_headers())
                if resp.status_code == 200:
                    data = resp.json()
                    # Return first match or parsed record
                    matches = data.get("matches") if isinstance(data, dict) else None
                    if matches and isinstance(matches, list) and len(matches) > 0:
                        return matches[0]
                    if isinstance(data, dict) and "code" in data:
                        return data
                    return None
                elif resp.status_code == 404:
                    logger.info(f"NIPOST API: Postcode '{clean_code}' not found (404).")
                    return None
                else:
                    logger.warning(f"NIPOST API returned non-200 status {resp.status_code} for code '{clean_code}': {resp.text}")
                    return None
        except httpx.TimeoutException:
            logger.warning(f"NIPOST API timeout after {self.timeout}s looking up '{clean_code}'. Falling back to local reference.")
            return None
        except Exception as exc:
            logger.warning(f"NIPOST API connection error looking up '{clean_code}': {exc}. Falling back to local reference.")
            return None

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
                    logger.warning(f"NIPOST API address validation returned status {resp.status_code}: {resp.text}")
                    return None
        except httpx.TimeoutException:
            logger.warning(f"NIPOST API timeout during address validation for '{address[:30]}...'. Falling back to local cleanser.")
            return None
        except Exception as exc:
            logger.warning(f"NIPOST API error during address validation: {exc}.")
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
        except Exception as exc:
            logger.warning(f"NIPOST API autofill error for '{area}, {state}': {exc}")
            return None


# Module-level default client
nipost_client = NIPOSTClient()


def get_nipost_client() -> NIPOSTClient:
    """Dependency injector / factory for NIPOSTClient."""
    return nipost_client
