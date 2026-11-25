"""Live NIPOST Sandbox Contract Verification Script.

Verifies the configured NIPOST_API_BASE_URL and NIPOST_API_KEY in .env against:
1. POST /v1/assembly/assemble (zero-credit authenticated health & schema probe)
2. GET /v1/lookup?code=EK-01-A03-FK-01 (unified digital postcode validation & lookup)
3. GET /v1/lookup?code=100001 (legacy code classification)

Never prints secret credentials.
"""
import sys
from dotenv import dotenv_values
from backend.app.services.nipost_client import NIPOSTClient


def main() -> int:
    env_vals = dotenv_values(".env")
    base_url = env_vals.get("NIPOST_API_BASE_URL", "").strip()
    api_key = env_vals.get("NIPOST_API_KEY", "").strip()
    auth_scheme = env_vals.get("NIPOST_AUTH_SCHEME", "x-api-key").strip()
    lookup_path = env_vals.get("NIPOST_LOOKUP_PATH", "/v1/lookup").strip()

    if not base_url or not api_key:
        print("ERROR: NIPOST_API_BASE_URL and NIPOST_API_KEY must be set in .env.")
        return 1

    client = NIPOSTClient(
        base_url=base_url,
        api_key=api_key,
        auth_scheme=auth_scheme,
        lookup_path=lookup_path,
    )
    print(f"Target: {client.base_url} | Auth: {client.auth_scheme} | Env: {client.upstream_environment}")

    health = client.check_health()
    print("1. Assembly Health Probe:", health)
    status = client.get_integration_status()
    print("   Status Snapshot:", {
        "connectivity_healthy": status["connectivity_healthy"],
        "authentication_verified": status["authentication_verified"],
        "contract_verified": status["contract_verified"],
        "upstream_environment": status["upstream_environment"],
    })

    # 2. Valid 11-char digital postcode lookup: require FOUND or NOT_FOUND (never INVALID_INPUT)
    res_digital = client.lookup_postcode("EK-01-A03-FK-01")
    print(f"2a. Lookup (EK-01-A03-FK-01): status={res_digital.status.value} http={res_digital.http_status} msg={res_digital.error_message}")
    lookup_entitlement_verified = res_digital.status.value in ("FOUND", "NOT_FOUND") and res_digital.http_status == 200

    # 2b. Invalid legacy/malformed format check
    res_invalid = client.lookup_postcode("100001")
    print(f"2b. Lookup (100001): status={res_invalid.status.value} http={res_invalid.http_status} msg={res_invalid.error_message}")
    invalid_format_handled = res_invalid.status.value in ("INVALID_INPUT", "NOT_FOUND") and res_invalid.http_status == 200

    # 2c. Negative auth check (invalid key must fail closed as UNAUTHORIZED)
    bad_client = NIPOSTClient(base_url=base_url, api_key="nipost_test_invalid_probe_key", auth_scheme=auth_scheme, lookup_path=lookup_path)
    bad_health = bad_client.check_health()
    unauthorized_handled = not bad_health.get("healthy") and bad_health.get("status_code") in (401, 403)
    print(f"2c. Negative Auth Probe: healthy={bad_health.get('healthy')} status={bad_health.get('status_code')} rejected={unauthorized_handled}")

    orch_status, _, orch_err, orch_method = client.orchestrated_verify("EK-01-A03-FK-01")
    print(f"3. Orchestrated Verify (EK-01-A03-FK-01): status={orch_status.value} method={orch_method} err={orch_err}")
    print(
        f"   Summary: assembly_contract_verified={bool(status['contract_verified'])} "
        f"lookup_entitlement_verified={lookup_entitlement_verified} "
        f"invalid_format_handled={invalid_format_handled} "
        f"unauthorized_handled={unauthorized_handled}"
    )

    return 0 if (health.get("healthy") and lookup_entitlement_verified and invalid_format_handled and unauthorized_handled) else 1


if __name__ == "__main__":
    sys.exit(main())
