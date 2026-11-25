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

    lookup_entitlement_verified = False
    for code in ("EK-01-A03-FK-01", "100001"):
        res = client.lookup_postcode(code)
        print(f"2. Lookup ({code}): status={res.status.value} http={res.http_status} msg={res.error_message}")
        if res.status.value in ("FOUND", "NOT_FOUND", "INVALID_INPUT") and res.http_status == 200:
            lookup_entitlement_verified = True

    orch_status, _, orch_err, orch_method = client.orchestrated_verify("EK-01-A03-FK-01")
    print(f"3. Orchestrated Verify (EK-01-A03-FK-01): status={orch_status.value} method={orch_method} err={orch_err}")
    print(f"   Summary: assembly_contract_verified={bool(status['contract_verified'])} lookup_entitlement_verified={lookup_entitlement_verified}")

    return 0 if (health.get("healthy") and lookup_entitlement_verified) else 1


if __name__ == "__main__":
    sys.exit(main())
