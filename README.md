# PostcodeLink — Nigeria's Postcode Intelligence and Address Verification Platform

A modern address intelligence, national digital postcode verification, and address standardization platform tailored for Nigerian e-commerce merchants, financial institutions, logistics fleets, and enterprise developer integrations.

PostcodeLink bridges the gap between unstructured customer addresses (often described using informal landmarks) and official **NIPOST (Nigerian Postal Service)** digital postal codes (both the October 2026 11-character 5-component national digital postcode standard `SS-LL-DDD-AA-BB` and legacy 6-digit postal codes) to eliminate driver disambiguation delays, prevent failed deliveries, improve address hygiene, and power building-level geolocation.

### Core Product Capabilities
1. **Nigerian Postcode Intelligence & Directory Lookup**: High-performance querying of legacy 6-digit postal codes and 11-character national digital postcodes with decoupled existence validation (`Validator`) and address retrieval (`Autofill`) service contracts.
2. **Address Verification & Cleansing**: Algorithmic landmark extraction, administrative entity normalization (State, LGA, District, Ward), and structured address standardisation.
3. **Building-Level Digital Postcode Disambiguation**: Strict structural validation and component decomposition of the 5-component national standard (`SS-LL-DDD-AA-BB`: State, LGA, District, Area, Building Unit).
4. **Developer API & Enterprise Platform**: REST API with API-key authentication, monthly tiered quota metering, anti-spoofing sliding-window rate limiting (webhook integration is **Planned**).
5. **Last-Mile Logistics & Dispatch Module**: Integrated downstream operational module providing merchant dispatch queues, courier fleet assignment, rider manifests, live radar dispatch tracking, and tamper-evident 6-digit PIN Proof-of-Delivery (POD).

---

## Strategic Product Architecture & Modularity

PostcodeLink is architected as two decoupled, enterprise-ready product modules sharing a unified digital address intelligence foundation:

```mermaid
graph TD
    subgraph Foundation [Shared Postcode Intelligence Foundation]
        NIPOST[Official NIPOST Verification Gateway]
        TAX[National Taxonomy & Address Standardisation]
        SEC[Cryptographic Evidence Engine & Distributed Redis Cluster]
    end

    subgraph Domain1 [Domain 1: Postcode Intelligence Platform]
        POSTCODE_SEARCH[Postcode Explorer & Address Cleanser]
        BULK_VALIDATE[Bulk CSV Address Validation & Geo-Enrichment]
        CHECKOUT_SDK[E-Commerce Checkout & Autocomplete Plugins]
    end

    subgraph Domain2 [Domain 2: Developer Platform]
        API_KEYS[Self-Service API Key Management]
        QUOTAS[Tiered Monthly Quotas & Usage Telemetry]
        DOCS[Developer Documentation & Integration Guides]
    end

    subgraph Domain3 [Domain 3: Last-Mile Logistics Operations]
        ORDER_DISP[Durable Outbox Dispatch & Fleet Assignment]
        COURIER_APP[Rider Manifest, Waybills & Live Dispatch Radar]
        POD[6-Digit OTP Proof-of-Delivery Verification]
    end

    Foundation --> Domain1
    Foundation --> Domain2
    Foundation --> Domain3
```

1. **Shared Postcode Intelligence Foundation**: Core national address register, two-stage NIPOST gateway integration, spatial classification, cryptographic evidence generation, and distributed caching/rate-limiting infrastructure.
2. **Developer Platform**: Independent commercial API product offering self-service registration, API key provisioning, versioned key rotation, monthly quota management, usage analytics, and interactive integration guides for enterprise software, fintech, and banking systems.
3. **Postcode Intelligence & Address Validation**: Standalone web explorer and address standardisation today (CSV bulk postcode validation and e-commerce checkout widgets are **Planned**).
4. **Last-Mile Logistics Operations**: Specialized delivery dispatch, courier fleet workload management, real-time customer tracking portal, and fraud-proof recipient PIN verification.

---

## Data Sources, System Taxonomy & Regulatory Governance (Release Gate v6.1.4 Standard)

PostcodeLink strictly differentiates between tiers of postcode data and enforces clear data governance in compliance with the [NIPOST Terms of Service](https://www.postcode.gov.ng/terms):

### 1. Six-Tier Verification Taxonomy & Provenance Enforcement
To prevent fabricated test fixtures or local reference data from being misrepresented as official government verifications, PostcodeLink enforces strict six-tier categorization across API contracts, database persistence, and UI indicators:
1. **Format Valid (`format_valid`)**: The postcode adheres to official syntax specifications (either the 11-character 5-component `SS-LL-DDD-AA-BB` national digital standard or the 6-digit legacy format). Validated by `is_well_formed_postcode()`.
2. **Local Reference Match (`local_match`)**: Matched against PostcodeLink's local demonstration registry or database directory (`PostcodeDirectory`). Returns `postcode_status: "local_match"` (internal algorithmic heuristic score `match_quality_score: 0.75`). Demonstration fixtures (e.g. `FC-02-A09-DB-09` and `LA-01-A04-IK-02`) carry `source_type: "demonstration_fixture"` and explicitly disclose `(unverified with official NIPOST)`. Even database-backed reference entries remain `local_reference` unless authoritatively verified.
3. **Partially Verified (`partially_verified`)**: Postcode existence confirmed by official NIPOST Validator (`/v1/validate`), but address metadata is absent from NIPOST and enriched from local reference datasets. Tagged with `address_metadata_source = "local_enrichment"` (internal heuristic score `0.80`). Enriched addresses are never falsely described as officially verified.
4. **Officially Verified (`nipost_verified`)**: Both postcode existence and address administrative metadata are verified in real time against the live official NIPOST national digital directory (`/v1/lookup`). Returns `postcode_status: "verified"` (internal heuristic score `0.95`).
5. **Address Conflict (`address_conflict`)**: Postcode exists in the directory, but the caller-supplied area or state contradicts the official geographic zone assignment (internal heuristic score `0.40`).
6. **Verification Unavailable (`unavailable`)**: Upstream official NIPOST gateway is unreachable or timed out; non-strict local fallback applied with full transparent disclosure (`fallback_used: true`, `upstream_status: "UNAVAILABLE"`).

> [!NOTE]
> **Heuristic Scoring vs Factual Trust Indicators**:
> Scores returned in `confidence` and `match_quality_score` are strictly internal algorithmic match heuristics and MUST NOT be construed as empirical delivery success probabilities. Production applications should evaluate PostcodeLink's 5 factual trust indicators:
> 1. **Format Syntax (`postcode_valid`)**: Conformance to canonical Nigerian postal or digital location standard.
> 2. **Registry Existence (`postcode_exists`)**: Authoritative upstream confirmation of registry existence (`True`, `False`, or `None` if unverified).
> 3. **Upstream Gateway (`upstream_contacted`, `is_live_nipost`)**: Confirmation that live NIPOST APIs were queried and authoritative evidence logged.
> 4. **Boundary Consistency (`address_consistent`)**: Geographic alignment between supplied address text and administrative district boundaries.
> 5. **Location Precision (`resolution_level`)**: Granularity indicator (`building_location` for 11-char digital codes vs `area_district` for 6-digit codes).

| Data Source Tier | Scope & Format | Verification Status | Provenance Attributes |
| :--- | :--- | :--- | :--- |
| **Authoritative Live NIPOST Cloud Gateway** | Live FMCIDE/NIPOST national digital postcode registry. | `official_verified` (`postcode_status: "verified"`) | `dataset_version: null` (or provider-supplied), `fallback_used: false` |
| **Database Directory Records** | Seeded reference data in local SQLite/PostgreSQL (`PostcodeDirectory`). | `local_reference` (`postcode_status: "local_match"`) | `source_type: "database_directory"`, `source_owner: "NIPOST / PostcodeLink"` |
| **NIPOST National Digital Postcode** | 5-component building-level standard (`SS-LL-DDD-AA-BB`: State, LGA, District, Area, Building Unit). | Standard NIPOST format | Strict 2-2-3-2-2 width validation (11 alphanumeric chars compact, 15 chars display), canonical & compact parsing |

> **NIPOST Terms & Scope Disclosure**: A syntactically valid or recognized postcode confirms a location reference only; it does not independently establish personal identity, residence, property ownership, or business occupancy.

### Feature Maturity & Release Scope (v6.1.8)
| Capability | Status | Notes |
| :--- | :--- | :--- |
| **Postcode Lookup, Cleansing & Provenance** | **Shipped** | 11-state local pilot reference + NIPOST adapter (`nipost_test_` / `nipost_live_` separation). |
| **Commercial API & API Key Lifecycle (Backend)** | **Shipped** | `/api/v1/api-keys` & `/api/v1/postcodes/commercial/*` with quota metering. |
| **Logistics Dispatch, Outbox & Public Tracking** | **Shipped** | Cryptographic 32-char tokens, HMAC challenge proof, distributed Redis/DB nonce replay protection. |
| **Dispatch Topology Map** | **Experimental / Simulated** | Simulated hub topology; hardware GPS telemetry is not connected. |
| **Developer Console UI** | **Shipped (Preview)** | Self-service `pl_test_` / `pl_live_` key creation, rotation, revocation & quota progress (`pl_live_` gated on commercial authorization). |
| **Webhooks, Usage History & Bulk CSV Postcode Validation** | **Planned** | Deferred pending NIPOST commercial authorization and customer demand. |
| **Legacy 6-Digit Postal Codes** | Traditional regional sorting codes (e.g. `100001` Lagos Island, `900001` Garki Abuja). | `local_match` (or `verified` when verified upstream) | Regional routing (`[1-9]\d{5}`) |
| **Demonstration Reference Fixtures** | Sample 11-character format demonstration codes (e.g. `FC-02-A09-DB-09`, `LA-01-A04-IK-02`). | `local_reference` (`postcode_status: "local_match"`) | `source_type: "demonstration_fixture"`, `source_owner: "PostcodeLink"` |

### 2. Verification Mode Precedence & Validation Matrix
PostcodeLink supports explicit verification mode control via `verification_mode` alongside backwards-compatible boolean flags (`strict`, `live_verify`). Contradictory flag combinations are rejected with HTTP 422:

| `verification_mode` | `strict` Flag | `live_verify` Flag | Effective Behavior | Resolution / Validation |
| :--- | :--- | :--- | :--- | :--- |
| `local_standardization` | `False` (default) | `False` (default) | Local standardization only | **Allowed** (Offline standardisation; zero upstream queries) |
| `local_standardization` | `True` | Any | Contradictory | **Rejected with HTTP 422** |
| `local_standardization` | Any | `True` | Contradictory | **Rejected with HTTP 422** |
| `nipost_validate` | `False` (default) | Any | Upstream verification with local fallback | **Allowed** (Fallback enabled if NIPOST unavailable) |
| `nipost_validate` | `True` | Any | Contradictory | **Rejected with HTTP 422** (Use `nipost_strict` for fail-closed) |
| `nipost_strict` | `True` (or omitted) | Any | Upstream verification fail-closed | **Allowed** (Fails closed with HTTP 503/404/502) |
| `nipost_strict` | `False` (explicit) | Any | Contradictory | **Rejected with HTTP 422** (`nipost_strict` cannot be non-strict) |
| `None` (omitted) | `True` | Any | Resolves to `nipost_strict` | **Allowed** (Legacy strict flag resolution) |
| `None` (omitted) | `False` | `True` | Resolves to `nipost_validate` | **Allowed** (Legacy live_verify flag resolution) |
| `None` (omitted) | `False` | `False` | Resolves to `local_standardization` | **Allowed** (Default offline resolution) |

> [!IMPORTANT]
> **No Conflation of Local Data with Official Verification**: Local reference data and demonstration fixtures are strictly tagged as demonstration and fallback data. In strict verification mode (`strict=true`), local fallback is disabled; unverified postcodes return HTTP 503 rather than asserting local demonstration data as government truth.

### 2. Verification Evidence Model & Database Provenance Gate
A database record in `PostcodeDirectory` claiming `verification_status = "official_verified"` is **never** accepted as official truth on face value. To qualify as `verified`, it must be backed by an active, unexpired record in `VerificationEvidence`:
- **Evidence Fields**: `postcode`, `provider = "NIPOST"`, `provider_reference_id` (upstream transaction receipt or request timestamp), `verification_method` (`validator_autofill_pipeline` | `validator`), `dataset_version`, `verified_at`, `valid_until` (default 30-day expiration window), `response_hash` (SHA-256 integrity digest of raw response payload), and `address_metadata_source`.
- **Integrity Notice (Hashed Response Evidence)**: The SHA-256 `response_hash` serves as an immutable, tamper-evident cryptographic digest of the upstream response payload for auditable tracking. It is a cryptographic integrity hash of response data, not an asymmetric government digital signature.
- **Automatic Demotion**: If verification evidence is missing, expired, or deactivated, database candidates are automatically demoted to `postcode_status = "local_match"` (internal heuristic score `0.75`), preventing stale or artificially flagged entries from posing as government-verified truth.

### 3. Explicit Two-Stage Validator $\to$ Autofill Orchestration
1. **Stage 1 (Validator)**: Queries `/v1/validate` to verify existence. If rejected or not found, halts immediately (failing closed with HTTP 404/422 in strict mode).
2. **Stage 2 (Autofill)**: Queries `/v1/lookup` to retrieve authoritative administrative address metadata (area, state, LGA, building unit).
3. **Stage 3 (Local Enrichment Boundary)**: If Autofill is absent but Validator confirms existence, the platform enriches missing address attributes from local reference datasets, explicitly returning `is_partial_verification: true`, `postcode_status: "partially_verified"`, `address_metadata_source: "local_enrichment"`, and notes the local enrichment in `changes_made`.

### 4. NIPOST Terms of Service, Commercial Usage & Official Integration Status
- **Adapter Verification Status**: The NIPOST integration client in PostcodeLink is structured as an integration adapter pending authorized external contract verification against official National Digital Postcode API references and sandbox credentials. (Note: NIPOST's public e-commerce shipping API documentation describes merchant logistics, not the National Digital Postcode directory service).
- **Software Service Model**: PostcodeLink provides address disambiguation, algorithmic landmark cleansing, and last-mile delivery tracking software. It does not claim ownership of the national postal directory, nor does it engage in unauthorized wholesale resale or bulk redistribution of raw government databases.
- **Operational Caching Limits**: Stored lookup metadata is restricted to operational verification audit logs and merchant delivery records. Commercial API consumers are prohibited from building independent derivative national postal databases without a direct commercial agreement with NIPOST.
- **Enterprise Licensing Notice**: Production deployments requiring high-volume directory synchronization or deep government registry integrations must obtain written authorization and an applicable commercial API data-use agreement directly from NIPOST ([https://www.postcode.gov.ng](https://www.postcode.gov.ng)).

---

## Production Cryptographic Key Management & Zero-Downtime Rotation Policy

1. **Cryptographic Key Strength & Entropy Guardrails**:
   - Production startup strictly enforces Shannon entropy ($\ge 3.0$ bits/character), character variety (maximum character concentration $\le 25\%$, minimum 10 distinct characters), and rejects repetitive padding (`'a'*32`), predictable sequences (`123456`, `abcdef`), and example templates.
   - Production keys MUST be generated using cryptographically authentic random generators:
     ```bash
     python -c "import secrets; print(secrets.token_urlsafe(32))"
     # or: openssl rand -hex 32
     ```
   - In production environments, credentials should be injected from a managed secret provider (e.g. AWS Secrets Manager, HashiCorp Vault, or GCP Secret Manager).

2. **Strict Domain Separation & Key Identifier (`kid`) Enforcement**:
   - `SECRET_KEY`: Dedicated to JWT session token creation and verification. Tokens embed a versioned `kid` header (`v1`, `v2`, etc.). During verification, `decode_access_token()` extracts `kid`, matches it against active or rotated keys (`get_jwt_verification_keys()`), and strictly rejects tokens with unknown or retired key IDs.
   - `OUTBOX_ENCRYPTION_KEY`: Dedicated to in-transit message payload encryption (AES-256-GCM). Must be distinct from `SECRET_KEY`.
   - `OTP_SECRET_KEY`: Dedicated to delivery verification PIN hashing (HMAC-SHA256). Strictly **mandatory** in production environments and must be distinct from both `SECRET_KEY` and `OUTBOX_ENCRYPTION_KEY`. In production, falling back to `SECRET_KEY` is completely disabled and triggers a runtime exception.

3. **Zero-Downtime Key Rotation Procedures**:
   - **JWT Secret Rotation**:
     1. Add previous key mapping using either:
        - `JWT_PREVIOUS_SECRETS=v1:<old_v1_secret>`
        - `JWT_PREVIOUS_KEYS_MAP='{"v1": "<old_v1_secret>"}'`
     2. Generate a new authentic secret and assign to `SECRET_KEY`, incrementing `JWT_KEY_ID` (e.g. `v1` $\to$ `v2`).
     3. Deploy API services. New tokens are signed with `kid: v2`; existing in-flight tokens signed with `kid: v1` decode cleanly via `get_jwt_verification_keys()` until expiration.
     4. After the token validity window (`ACCESS_TOKEN_EXPIRE_MINUTES`) has elapsed, remove the retired secret from `JWT_PREVIOUS_SECRETS` or `JWT_PREVIOUS_KEYS_MAP`.
   - **Delivery PIN / OTP Key Rotation**:
     1. Add current active `OTP_SECRET_KEY` to `OTP_PREVIOUS_SECRETS`.
     2. Set `OTP_SECRET_KEY` to the new secret and deploy.
     3. New deliveries are hashed with the new key; in-flight pending deliveries created under the previous key continue to verify successfully via `OTP_PREVIOUS_SECRETS`.
     4. Once all in-flight deliveries with previous OTP hashes are finalized, remove the old key from `OTP_PREVIOUS_SECRETS`.
   - **Outbox Key Rotation**: Before rotating `OUTBOX_ENCRYPTION_KEY`, allow pending messages in the transactional outbox to dispatch (`retry_count` settled), or execute the outbox re-encryption script to migrate un-dispatched encrypted payloads to the new key before deleting the old key.

---

## Architecture & Security Hardening (Release Gate v6.0 Production Standard)

Following the production-readiness review of Release Gate v5.9, Release Gate v6.0 introduces permanent audit retention, fail-closed live carrier verification, commercial API quota metering, and requeue lifecycle integrity:

### 1. P1 — Live Carrier Telemetry Verification Only (Simulated Provider Rejection)
- **Rejection of Simulated Evidence**: `provider_telemetry_verified` resolution strictly requires authoritative upstream carrier telemetry (`termii` or `twilio`) and status `SENT`. Simulated sandbox evidence is rejected with HTTP 422 Unprocessable Content.
- **Fail-Closed Carrier Association & Delivery Identifier Correlation**: `TwilioNotificationProvider` and `TermiiNotificationProvider` enforce complete, non-empty presence of `from`, `to`, `body`/`text`, and `message_id`. They perform delivery identifier correlation (`order {delivery_id}` in message text) and carrier association checks (exact match on recipient, sender, and message ID). Note that while PIN proof-of-delivery uses SHA-256 and stored payloads use AES-256-GCM, SMS verification is carrier identifier association rather than cryptographic message signing.
- **No Fallback to Inbound Inbox & Configurable Account Base URL**: Termii status inquiry strictly queries `{TERMII_BASE_URL}/api/sms/status` (defaulting to `https://api.ng.termii.com`) and never queries `/api/sms/inbox` (which is exclusively for customer inbound messages). Custom enterprise account base URLs are fully supported.

### 2. P1 — Manual Requeue Stale ID Resolution & Dispatch Guarantees
- **Stale Provider ID Resolution**: On manual requeue (`resolution="requeue"`), the active `provider_message_id` is cleared (`None`), preserved in `last_failed_provider_message_id`, `dispatch_attempt` is incremented, and `retry_count` is reset to 0.
- **Worker Re-dispatch Guarantee**: The background outbox worker only bypasses dispatch for crashed items with active provider acceptance, ensuring newly requeued items with cleared IDs are always dispatched anew.

### 3. P1 — Commercial API Quota Metering & Anti-Spoofing IP Rate Limiting
- **Dedicated Commercial Endpoints & Single Quota Metering**: `GET /api/v1/postcodes/commercial/lookup` and `POST /api/v1/postcodes/commercial/cleanse` strictly require active `x-api-key` validation with atomic monthly quota metering (401 on missing/invalid, 429 on quota exhaustion). Route handlers invoke core business logic directly without re-triggering dependency checks, guaranteeing exactly one quota debit per request.
- **Anti-Spoofing Reverse Proxy IP Extraction**: Unauthenticated public demo callers on `/lookup` and `/cleanse` are metered by client IP with a sliding-window rate limit (15 requests/minute). The real client IP is extracted via `get_trusted_client_ip()`, which only respects `X-Forwarded-For` when the direct peer connection originates from a configured `TRUSTED_PROXIES` entry. Untrusted direct callers attempting to rotate spoofed headers are restricted by their physical connection IP.
- **Accurate NIPOST Provenance**: Live NIPOST responses maintain accurate provenance, returning `dataset_version: null` when omitted or not found in upstream directory results, while exposing `api_integration_version: "2026.1"`. Local fallback reference responses clearly declare `dataset_version: "2024.2"`.

### 4. P1 & P2 — Permanent Audit Retention & Soft Deletion Architecture
- **Elimination of Audit Cascades**: Removed `cascade="all, delete-orphan"` from `Delivery.events`. Direct hard deletions of `delivery_events` are permanently blocked by `ON DELETE RESTRICT` foreign key constraints and engine-level triggers.
- **Soft Deletion & Tracking Revocation**: Deleting a delivery sets `is_deleted = True`, records `deleted_at = now`, transitions status to `CANCELLED`, and appends an immutable `DeliveryEvent` audit entry. In addition, the public `tracking_token` is revoked (`revoked_{id}_{hash}`), and `GET /api/v1/deliveries/track/{token}` returns HTTP 404 for soft-deleted orders.
- **Migration Downgrade & Upgrade Lifecycle**: Migration `c3d4e5f6a7b8` downgrade drops triggers cleanly before batch schema alter operations, restores exact v5.9 triggers and functions with `WHEN EXISTS` checks, and safely restores `ON DELETE CASCADE` foreign keys.

### 5. P2 — Worker Subprocess OS Signal Handling & Crash Recovery
- **Real OS Subprocess Verification**: Integration tests spawn `backend.app.workers.outbox_worker` as a real OS subprocess, verify heartbeat creation, send termination signals (`SIGTERM`, `SIGINT`, `SIGBREAK`), and confirm graceful exit code 0 with persistent `status="stopped"` and `stop_reason="graceful_shutdown"`.

### 6. P2 — API Key Lifecycle Validation & Expiration Control (v6.0.1 Hardening)
- **Resolved Missing Expiry Import**: Fixed `timedelta` import in `api_keys.py`, enabling reliable creation of expiring keys (`expires_in_days`). Verified that expired keys reject requests with HTTP 401.
- **Strict Pydantic Input Validation**: Enforced non-blank names (`min_length=1, max_length=100`), bounded quotas (`ge=1, le=10_000_000`), and bounded expiry (`ge=1, le=365`), rejecting malformed requests with HTTP 422 rather than silently altering inputs.

### 7. P2 — Trusted Proxy Topology Narrowing & Defense in Depth
- **Zero-Trust Default Proxy List**: Removed broad private network ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) from default `TRUSTED_PROXIES`. In production, default is empty (`[]`), requiring explicit configuration of reverse proxy IPs or CIDRs via environment variables. Untrusted internal containers or shared infrastructure cannot forge client IPs.
- **All-Trusted Proxy Chain Fallback**: When all parsed hops in `X-Forwarded-For` match configured trusted proxies, `get_trusted_client_ip()` safely falls back to the immediate peer connection IP (`direct_ip`) rather than returning an internal proxy IP.

### 8. P2 — Upstream NIPOST Error Sanitization & Diagnostic Log Protection
- **Information Leakage Prevention**: Connection timeouts, DNS failures, and socket errors caught in `NIPOSTClient` return safe public categories (`UNAVAILABLE`, `UNAUTHORIZED`, `TIMEOUT`) without leaking internal hostnames, ports, or raw exception strings into API responses.
- **Log Masking**: Address validation and autofill queries omit sensitive customer address text, response bodies, and raw exceptions from server logs, logging only status codes and operational diagnostics.

### 9. P2 — Public IP Distributed Rate Limiting Production Fail-Closed Policy (v6.0.2)
- **Production Consistency**: `check_client_ip_rate_limit()` now enforces the exact same distributed fail-closed policy as `check_api_key_rate_limit()`. If Redis is unavailable in production, public demo requests fail closed with HTTP 503, eliminating multi-instance memory fallback bypasses. Process-local in-memory fallback is permitted strictly in development or when `ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION=true` is explicitly configured.

### 10. P2 — Least-Privilege CI Security Permissions & Test Coverage
- **GitHub Actions Hardening (`.github/workflows/ci.yml`)**: Explicitly configured top-level `permissions: contents: read` adhering to the principle of least privilege.
- **Comprehensive Dual-DB Test Suite**: 144/144 Pytest security, cryptography, and API integration tests passing (143 passed, 1 skipped) across PostgreSQL 16 and SQLite 3, plus 7/7 Node.js state-machine and OTP verification tests.

---

## Architecture & Security Hardening (Release Gate v5.9 Production Standard)

Following the production-readiness review of Release Gate v5.8, Release Gate v5.9 introduces engine-level database audit guarantees, live upstream provider verification, and distributed fail-closed reliability:

### 1. P1 — Live Provider Telemetry Verification for Manual Outbox Reconciliation
- **Authoritative Gateway Verification**: When administrators resolve stuck outbox records with `evidence_type = "provider_telemetry_verified"`, the API actively calls the configured notification provider's upstream gateway (`check_message_status`) with the operator-provided `provider_message_id`.
- **Rejection of Fabricated References**: If the carrier gateway cannot authenticate the dispatch status or if the returned status is not confirmed delivered/sent, the reconciliation request is rejected with HTTP 422 Unprocessable Content, preventing operators from asserting unverified message IDs.

### 2. P1 — PostgreSQL & SQLite Database-Level Audit Trail Immutability
- **Engine-Level Trigger Enforcement**: Implemented database migration `b2c3d4e5f6a7` adding native triggers:
  - **PostgreSQL**: `prevent_delivery_events_tampering()` row-level trigger preventing direct SQL `UPDATE` and `DELETE` on `delivery_events`.
  - **SQLite**: `trg_delivery_events_no_update` and `trg_delivery_events_no_delete` triggers aborting modifications at the database layer.
- **Relational Integrity**: Prohibits direct manipulation of compliance and transition audit logs while respecting parent delivery cascading lifecycle operations.

### 3. P1 — Mandatory Production Redis Policy & Default Fail-Closed Throttling
- **Mandatory Redis in Production**: `REDIS_REQUIRED_IN_PRODUCTION=true` is enforced by default. In `ENVIRONMENT=production`, the application refuses to start if `REDIS_URL` is omitted, eliminating unintentional single-node in-memory rate-limiting in multi-instance deployments.
- **Fail-Closed Protection**: In `production` with `RATE_LIMIT_REDIS_FAIL_CLOSED=true` (default), API key requests that cannot connect to Redis are rejected with HTTP 503 Service Unavailable, preventing quota exhaustion and denial-of-service bypasses. Single-instance testing environments can explicitly opt out via `ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION=true`.

### 4. P2 — Redis Lua Script Sliding-Window Integration Verification
- **Cardinality Verification**: Verified that requests exceeding the sliding-window threshold are never added to the Redis sorted set (`ZCARD` remains strictly at `limit`), preventing memory growth and unbounded throttling cascades.

### 5. P2 — Real Worker Loop Signal Handling & Stale Worker Telemetry
- **Graceful Signal Handling**: Integration tested that `run_outbox_worker_loop` listening to `stop_event` cleanly records `status="stopped"` and `stop_reason="graceful_shutdown"` in `worker_heartbeats`.
- **Abrupt Termination Telemetry**: Verified `/health/worker` marks workers whose heartbeat exceeds the timeout as `stale_workers` and returns `status="degraded"`.

### 6. P2 — Automatic Retry Reset on Manual Requeue
- **Worker Re-eligibility**: When an administrator requeues an exhausted outbox notification (`retry_count == max_retries`), the API automatically resets `retry_count = 0`, immediately making the record eligible for outbox worker processing.

### 7. P2 — Verified Current Capabilities vs Planned Roadmap
- **Verified Current Production Implementation**:
  - Authenticated payload encryption in transit via **AES-256-GCM** bound to delivery context AAD (`delivery_id`).
  - Cryptographic one-way **SHA-256** hash verification for 6-digit proof-of-delivery PINs.
  - Multi-factor phone verification challenge to unmask tracking PINs.
  - Dual PostgreSQL 16 and SQLite 3 migration, trigger, and regression test suites.
- **Planned Post-v5.9 Capabilities**:
  - Asymmetric client-side public-key encryption for end-to-end zero-knowledge recipient secrets.
  - Native telecommunication SMPP bindings for direct telco SMSC integration.
  - Live GPS rider telemetry stream ingestion.

---

## Architecture & Security Hardening (Release Gate v5.8 Production Standard)

Following the comprehensive production-readiness review of Release Gate v5.7, the platform has completed enterprise-grade hardening across distributed coordination, provider reconciliation, and lifecycle reliability:

### 1. P1 — Termii Crash Recovery Without Saved Message ID (Zero Duplicate Dispatches)
- **Documented API Boundary**: Verified that Termii's public REST gateway does not provide an outbound query endpoint by recipient phone or client_reference without an authoritative `provider_message_id`.
- **Zero-Duplicate Invariant**: When a worker crashes after provider HTTP acceptance but before `provider_message_id` is committed to PostgreSQL, `check_message_status` safely returns `None`. The outbox worker immediately routes the item to `RECONCILIATION_REQUIRED` and **never automatically re-dispatches**, completely eliminating duplicate customer SMS risks.

### 2. P1 — Twilio Outbound Verification with Delivery Fingerprint Matching
- **Delivery Fingerprint Binding**: Outbound PIN SMS messages embed an explicit order fingerprint (`Your PostcodeLink delivery confirmation PIN for order {delivery_id} is {pin}.`).
- **Ambiguity Rejection**: Outbound status inquiries by recipient phone verify that returned messages contain the specific delivery fingerprint. Unrelated messages or multiple ambiguous results are rejected (`return None`), routing to administrator reconciliation rather than misassociating an unrelated delivery's SMS.

### 3. P1 & P2 — Distributed Sliding-Window Rate Limiting with Atomic Lua Script
- **Atomic Lua Sliding Window**: Rate limits are evaluated in Redis via a single atomic Lua script executing `ZREMRANGEBYSCORE`, `ZCARD`, conditional `ZADD`, and `EXPIRE`.
- **No Accumulation of Rejected Requests**: Requests that exceed limits are strictly **not** added to the sorted set, preventing throttling cascades and ensuring accurate `Retry-After` calculation.
- **Connection Retry with Bounded Backoff**: Replaced one-shot connection caching with a resilient retry loop (15s backoff). If Redis temporarily fails and recovers, the client reconnects automatically.
- **Configurable Production Fail-Closed Policy**: Supports `RATE_LIMIT_REDIS_FAIL_CLOSED=true` to reject requests with HTTP 503 rather than silently partitioning distributed allowances across multi-instance nodes.
- **Operational Monitoring**: Exposes rate-limiter backend health (`redis` vs `in_memory_fallback`) in `/health/rate-limiter` and `/health/integrations`.

### 4. P1 — Transaction-Level Concurrent API Key Rotation Race Tests
- **Multi-Thread Concurrency Proof**: Verified simultaneous rotation requests via `ThreadPoolExecutor` against PostgreSQL and SQLite. Exactly one request succeeds (HTTP 201) while competing requests receive HTTP 409 Conflict.
- **Quota Inheritance**: New credentials inherit exact billing period usage without reset bypasses.

### 5. P2 — Persistent Worker Heartbeat Lifecycle & Graceful Shutdown
- **Worker Lifecycle Tracking**: Added `last_successful_process_at` and `stop_reason` to the `worker_heartbeats` table (migration `a1b2c3d4e5f6`).
- **Clean Signal Handling**: Outbox worker daemon intercepts `SIGINT` and `SIGTERM`, recording `status="stopped"` and reason in the database before process termination.
- **Observability Telemetry**: `/health/worker` surfaces `active_workers`, `stale_workers` (heartbeat age > threshold), `stopped_workers`, `outbox_backlog`, and `last_successful_process_at`.

### 6. P2 — Stronger Reconciliation Evidence Handling & Immutable Audit Trail
- **Evidence Classification**: Reconciliation requests explicitly distinguish `manual_operator_asserted` from `provider_telemetry_verified`. Provider-verified resolutions strictly require `provider_message_id` (HTTP 422 if omitted).
- **Client Tracking Reference**: Tracks `reconciliation_request_id` across outbox items and audit logs.
- **Database-Level Immutability**: `DeliveryEvent` records are enforced append-only via SQLAlchemy event hooks that reject modifications with `ValueError`.

### 7. P2 — Production Policy for Multi-Instance Redis
- **Mandatory Production Redis**: When `REDIS_REQUIRED_IN_PRODUCTION=true` is set, the application strictly refuses to start in `ENVIRONMENT=production` if `REDIS_URL` is omitted.

### 8. P0 — Dual PostgreSQL 16 & Redis 7 CI/CD Pipeline
- **Continuous Integration (`.github/workflows/ci.yml`)**:
  - Spin up `postgres:16` and `redis:7` service containers with health checks.
  - Run Alembic migrations and database seeding against PostgreSQL 16.
  - Run 150/150 Pytest security, cryptography, and API integration tests against PostgreSQL and Redis.
  - Run 7/7 Node.js state-machine and 6-digit OTP security tests.
  - Compile production Next.js 15 build with 0 errors.

### 9. P1 & P2 — Release Gate v6.0.3 Operational Security & NIPOST Contract Integrity
- **Redis Credential Masking in Logs**: Connection URLs are strictly sanitized using `_sanitize_redis_url()` across startup, connection success, runtime failovers, and `/health/rate-limiter` telemetry (`redis://user:***@host:port/db`). Plaintext passwords and user credentials can never appear in application logs or monitoring dashboards.
- **NIPOST Official Contract Adapter**: Supports official NIPOST developer lookup schema (`/v1/lookup`) with graded fields (`postcode`, `valid`, `administrative_address` object, `recent_house_address`) alongside PostcodeLink gateway schema.
- **Endpoint Route 404 vs Postcode Non-existence Discrimination**: Prevents misconfigured reverse proxies or bad gateway paths returning HTML 404 from falsely reporting that a valid Nigerian postcode does not exist. Only authoritative JSON responses with explicit validity failure are classified as `NOT_FOUND`.
- **NIPOST Diagnostic Log Sanitization**: Response bodies (`resp.text`), raw exception strings (`exc`), and sensitive query parameters are completely omitted from logs in `lookup_postcode()`, `validate_address()`, and `autofill_postcode()`.
- **Bounded In-Memory Public IP Rate Limiting**: Periodic cleanup (`_cleanup_expired_in_memory_windows`) purges expired IP buckets every 60s and enforces a hard bound (`MAX_IN_MEMORY_KEYS = 10,000`), preventing memory exhaustion under sustained traffic.
- **Tri-State Rate Limiter Health Telemetry**: `/health/rate-limiter` reports three distinct states: `"redis"` (connected cluster), `"unavailable_fail_closed"` (production Redis down with fail-closed HTTP 503), and `"in_memory_fallback"` (local fallback active).

### 5. P2 — Configurable Operator Capacity & Service Area Routing
- **Configurable Fleet Limits**: Respects each logistics operator's configured `max_active_deliveries` limit across operator directories, dispatch assignments, and capacity indicators (`has_capacity = active_deliveries_count < max_active_deliveries`).
- **Service Area Filtering**: Merchants can filter available couriers by coverage zones (`GET /api/v1/operators/?service_area=Ikeja`).

### 6. P2 — Production Health & Observability Probes
- `/health/live`: Application process liveness probe (HTTP 200).
- `/health/ready`: Database connectivity readiness check; returns HTTP 503 Service Unavailable without leaking internal exception traces if disconnected.
- `/health/worker`: Outbox queue depth, lease timing, worker heartbeat, and reconciliation alert telemetry.
- `/health/integrations`: SMS gateway and NIPOST upstream configuration and production readiness checks.

### 7. P2 — Anti-DoS Scoped Login Rate Limiting
- **Composite Brute-Force Bucket**: Scoped failed attempt counters by `(client_ip, email)`.
- **Targeted Lockout**: An adversary attempting 5 failed passwords from an attacker IP is locked out from that origin, while legitimate users on distinct IPs can continue to authenticate with valid credentials.

### 8. P0 — Authentication & Privilege Escalation Immunity
- **Public Registration Role Lockdown**: Public registration (`POST /api/v1/auth/register`) strictly sets account role to `merchant`. Client-supplied role attributes are discarded.
- **Interactive Auth Flow**: Interactive `AuthModal` supporting credentials login and registration with JWT token persistence.
- **Controlled Account Provisioning**: Operator couriers and additional platform administrators can only be provisioned by authenticated Platform Admins via `POST /api/v1/auth/admin/create-user`.
- **Production Secret & Migration Guard**: In `production` environments, the API refuses startup if `SECRET_KEY` is missing, default, or shorter than 32 characters. `Base.metadata.create_all` is disabled in production to guarantee Alembic migration integrity.

### 9. P0 — Dual PostgreSQL & SQLite CI/CD Pipeline
- **GitHub Actions Workflow (`.github/workflows/ci.yml`)**:
  - Spin up `postgres:16` service container with health checks.
  - Run Alembic migrations and database seeding against PostgreSQL.
  - Run 68/68 Pytest security, cryptography, and API integration tests against PostgreSQL.
  - Verify SQLite migration and local fallback test compatibility.
  - Run 7/7 Node.js state-machine and 6-digit OTP security tests.
  - Compile production Next.js 15 build with 0 errors.

---

## Complete Features

### 1. Operations Overview Dashboard
- **Real-Time KPIs**: Total deliveries, in-transit parcels, deliveries awaiting dispatch, and verified postcode adoption percentage.
- **Recent Deliveries Feed**: Interactive table with status badges, verified NIPOST tags, and quick-view action drawers.
- **Service Status Card**: Real-time indicator for the NIPOST digital postcode service (Local 6-digit registry vs Live FMCIDE Cloud API).

### 2. Deliveries Management Hub
- **Lifecycle Pipeline**: Filter across `Awaiting Dispatch`, `Assigned`, `In Transit`, and `Delivered`.
- **Search & Multi-Filters**: Search by reference ID (`PL-2026-...`), recipient name, phone, address, landmark, state, or assigned courier.
- **Delivery Audit Trail & Event Timeline**: Timestamped history for every transition (actor role, notes, and rider updates).
- **Logistics Operator Assignment**: Dynamic courier selector for dispatch routing.
- **Official Printable Waybills**: Generates printable consignment slips with barcodes, QR code layouts, merchant origin, recipient destination, verified postcode badges, and rider signature strips.
- **CSV Data Export**: One-click export of filtered delivery records.

### 3. Interactive Dispatch Radar & Fleet Map
- **Multi-Region Projections**: Switch between **Lagos Metropolitan Zone (01)**, **Abuja FCT (09)**, and **National Nigeria**.
- **Geographic SVG Radar Canvas**: Dynamic pins plotted using real geographic coordinates, color-coded by delivery status (Blue = In Transit, Amber = Awaiting Rider, Green = Delivered).
- **Interactive Marker Inspection**: Click any radar marker to inspect parcel details, verified NIPOST codes, and rider locations.
- **Active Courier Fleet Tracking**: Real-time status cards for on-duty couriers across major sectors.

### 4. Public Customer Tracking Portal
- **Reference Lookup**: Recipients and merchants can track any delivery reference (e.g. `PL-2048`).
- **Interactive Progress Stepper**: Order Placed → Postcode Verified → Out for Delivery → Delivered.
- **Protected 6-Digit Delivery PIN (OTP)**: Fraud-prevention security code with phone verification challenge.
- **Direct Courier Communication**: Direct one-click links to Call Courier or Chat via WhatsApp.
- **Simulated Route Visualizer**: Vector route connecting merchant origin hub (Sabo-Yaba) to destination.

### 5. Bulk CSV & Batch Order Dispatch
- **Multi-Line Order Importer**: Paste order data from Shopify, Instagram DMs, or WhatsApp.
- **Parallel NIPOST Auto-Resolver**: Batch-cleanses and validates addresses across all lines in parallel.
- **One-Click Dispatch All**: Create verified orders with unique tracking IDs in one action.
- **Sample Batch Pre-Loader**: Test immediate batch dispatch with authentic Nigerian merchant sample records.

### 6. WhatsApp Dispatch & Tracking Notifications
- **Customer Updates**: One-click WhatsApp link generator sending formatted tracking links and masked OTP instructions directly to recipients.
- **Rider Waybills**: Pre-formatted WhatsApp dispatch notes containing destination addresses, landmarks, and recipient contacts.

### 7. Zone Intelligence & Courier SLA Analytics
- **Verification KPIs**: Postcode standardization rate (%), average delivery SLA (hrs), and total fulfillment spend.
- **Regional Distribution**: Order volume breakdowns across Lagos, Abuja, Rivers, Oyo, and Kano.
- **Top NIPOST Postal Delivery Clusters**: High-density zones (e.g. `105102 Lekki Phase 1`, `900288 Wuse 2`, `100271 Ikeja GRA`, `500001 Old GRA PH`).
- **Courier SLA Scorecard**: Rankings of logistics partners based on on-time fulfillment, average speed, and customer ratings.

### 8. NIPOST Digital Postcode Registry & Address Cleanser
- **National Postcode Directory**: Searchable registry of official 6-digit NIPOST codes across Lagos, Abuja (FCT), Rivers, Oyo, Kano, Kaduna, Enugu, Ogun, Delta, Edo, and Anambra.
- **Nigerian Address Cleanser & Standardizer**: Pasting unstructured customer notes with local landmarks (e.g. *"Beside Access Bank, Plot 412 Aminu Kano Crescent, Wuse 2, Abuja"* or *"Opposite Yellow Gate after transformer"*) automatically extracts the area, LGA, State, and attaches a matching local reference postcode (or an official NIPOST-verified code when live upstream verification is enabled and authorized).
- **One-Click Dispatch**: Create a delivery order directly from any resolved postcode entry or cleansed address.

### 9. Courier Fleet & Dispatch Operators
- **Courier Directory**: Pre-seeded with logistics partners (*SwiftMove Logistics*, *CityRoute NG*, *Apex Capital Express*, *Kwik Express*, *Delta-Rivers FastCargo*).
- **Fleet Attributes**: Motorcycle, Delivery Van, Tricycle (Keke), and Truck vehicle types, service areas, ratings, and completed trips.
- **Real-Time Availability**: Toggle operators between *Available* and *Busy*.

### 10. Customer Directory & Address Book
- Saved recipient profiles with pre-verified digital postcodes for one-click repeat order dispatch.

### 11. Workspace Settings & Data Portability
- **Merchant Origin Profile**: Configures warehouse address, state, and phone printed on consignment notes.
- **Integration Controls**: Switch between local NIPOST registry and live API endpoints.
- **Database & Backup**: Export full JSON database backups or reset the workspace to initial demo data.
- **Client-Side Persistence**: Deliveries, status events, and settings automatically persist in `localStorage`.

---

## FastAPI Backend Architecture & Database Structure

PostcodeLink Nigeria provides a dedicated Python/FastAPI backend powered by **SQLAlchemy 2.0 ORM** and **Pydantic v2**, supporting zero-config local development with SQLite (`postcodelink.db`) and instant production deployment on PostgreSQL via the `DATABASE_URL` environment setting.

### 1. Database Schema & Relational Design

The backend implements a normalized, relational schema:

| Table | Primary Key | Description & Relationships |
|---|---|---|
| `profiles` | `UUID` | Merchant accounts, dispatch managers, and courier users (`merchant`, `operator`, `admin`). |
| `operators` | `UUID` | Logistics fleets and couriers (vehicle type, service areas JSON, rating, active delivery counters). FK to `profiles.id`. |
| `customers` | `UUID` | Recipient address directory (phone index, default address, state, verified postcode, total order counter). |
| `deliveries` | `VARCHAR(32)` | Complete delivery orders with human-readable tracking references (`PL-2026-XXXXXX`), destination coordinates, fees, and state-machine statuses. |
| `delivery_events` | `UUID` | **Immutable append-only audit trail** recording actor, role, status transition, timestamp, and notes. FK to `deliveries.id`. |
| `postcodes` | `UUID` | Authoritative Nigerian 6-digit postal code directory (NIPOST standard) across Lagos, Abuja FCT, Rivers, Oyo, Kano, etc. |

### 2. State Machine & Lifecycle Transitions

All state modifications are enforced server-side by the lifecycle state machine:
```
           ┌──────────┐
           │ PENDING  │
           └────┬─────┘
                │
                ▼
          ┌───────────┐
          │ ASSIGNED  │
          └─────┬─────┘
                │
                ▼
         ┌────────────┐
         │ PICKED_UP  │
         └──────┬─────┘
                │
                ▼
        ┌─────────────┐
        │ IN_TRANSIT  │
        └───────┬─────┘
                │
                ▼
     ┌──────────────────┐
     │ OUT_FOR_DELIVERY │
     └──────────┬───────┘
                │
         (OTP Confirmed)
                ▼
         ┌───────────┐
         │ DELIVERED │  (Terminal)
         └───────────┘
```
*Note: Any order can move to `FAILED` or `CANCELLED` according to strict guard rules. Terminal states (`DELIVERED`, `CANCELLED`) reject all subsequent modifications.*

### 3. Proof of Delivery PIN (OTP) & Brute-Force Lockout
- **Generation**: Cryptographically secure 6-digit PIN generated server-side on order placement.
- **Privacy Masking**: Public tracking portal only returns a masked representation (`***924`), requiring the recipient's phone number verification challenge.
- **Brute-Force Guard**: Maximum of **3 failed attempts**. The 3rd failed attempt automatically locks PIN verification for **15 minutes** (HTTP 429).

### 4. RESTful API Endpoints (`/api/v1`)

- **System & Health**:
  - `GET /` — API root, service status, version info.
  - `GET /health` — Verifies database engine and connection health.
  - `GET /health/live` — Liveness probe (process up).
  - `GET /health/ready` — Readiness probe (database and engine connectivity).
  - `GET /health/worker` — Background outbox worker queue depth and heartbeat telemetry.
  - `GET /health/integrations` — Upstream NIPOST and SMS gateway connectivity status (credentials omitted).
- **Deliveries** (Supports Bearer JWT and `x-api-key` header):
  - `POST /api/v1/deliveries/` — Create new delivery with automated NIPOST verification and outbox PIN dispatch.
  - `GET /api/v1/deliveries/` — List deliveries (scoped to authenticated merchant/courier).
  - `GET /api/v1/deliveries/{id}` — Full merchant/operator delivery details.
  - `POST /api/v1/deliveries/bulk` — Batch import and cleanse multi-order dispatch.
  - `GET /api/v1/deliveries/track/{tracking_token}` — Strict token-only public recipient tracking portal.
  - `POST /api/v1/deliveries/{id}/regenerate-token` — Regenerate and revoke public tracking URL token.
  - `POST /api/v1/deliveries/{id}/assign` — Assign courier fleet operator with capacity check.
  - `POST /api/v1/deliveries/{id}/status` — Advance lifecycle status with complete role permission matrix.
  - `POST /api/v1/deliveries/{id}/verify-otp` — Verify recipient PIN and confirm delivery (single-use revocation).
- **Postcodes & Address Cleanser** (Supports `x-api-key` metering):
  - `GET /api/v1/postcodes/lookup` — Search official postcodes by area, state, or 6-digit/11-character code.
  - `POST /api/v1/postcodes/cleanse` — Normalize and standardize messy addresses against postal records.
- **Fleet Operators & Customers** (Supports `x-api-key`):
  - `GET /api/v1/operators/` & `POST /api/v1/operators/` — Manage courier fleet and capacity. Filter by `?service_area=...`.
  - `GET /api/v1/customers/` & `POST /api/v1/customers/` — Recipient directory with merchant tenant isolation.
- **API Keys & Integrations**:
  - `POST /api/v1/api-keys/` — Issue new merchant API keys with custom monthly quotas.
  - `GET /api/v1/api-keys/` — List active API keys and inspect call usage metrics.
  - `POST /api/v1/api-keys/{id}/rotate` — Atomically rotate an API key, issuing a new key and revoking the old one.
  - `DELETE /api/v1/api-keys/{id}` — Revoke an API key immediately.
- **Analytics** (Supports `x-api-key`):
  - `GET /api/v1/analytics/overview` — Operations KPIs, verification accuracy, and fulfillment revenues.

Interactive OpenAPI documentation is live at **`http://127.0.0.1:8000/docs`** and ReDoc at **`http://127.0.0.1:8000/redoc`**.

---

## Tech Stack
- **Frontend Framework**: Next.js 15 (App Router, Turbopack, React 19)
- **Frontend Language**: TypeScript 5.8
- **Backend Framework**: Python 3.12, FastAPI, Uvicorn, Starlette
- **ORM & Data Layer**: SQLAlchemy 2.0 (SQLite / PostgreSQL compatible)
- **Data Validation**: Pydantic v2, Pydantic-Settings
- **Testing**: Node Test Runner (Frontend/Lib) & Pytest (FastAPI endpoints)
- **Database Schema**: Supabase PostgreSQL migration ready in `supabase/migrations/`
  - `0001_initial_schema.sql` (Tables & Types)
  - `0002_role_based_rls_policies.sql` (Role-based RLS Policies)

---

## Running Locally

### 1. Frontend (Next.js)

1. Install dependencies:
   ```bash
   npm ci
   # Or: npm install
   ```

2. Setup environment variables:
   ```bash
   cp .env.example .env.local
   ```

3. Run automated frontend tests:
   ```bash
   npm test
   ```

4. Run frontend development server:
   ```bash
   npm run dev
   ```

### 2. Backend (FastAPI)

1. Setup virtual environment and install requirements:
   ```bash
   python -m venv backend/venv
   backend/venv/Scripts/pip install -r backend/requirements.txt
   ```

2. Apply database migrations & seed reference data:
   ```bash
   # Run Alembic migrations
   python -m alembic upgrade head
   
   # Seed local reference demonstration postcodes and initial operational profiles
   npm run backend:seed
   # Or: backend/venv/Scripts/python -m backend.app.seed
   ```

3. Run FastAPI automated security & API test suite (188/188 tests passing across PostgreSQL & SQLite):
   ```bash
   npm run backend:test
   # Or: backend/venv/Scripts/python -m pytest backend/tests -v
   ```

4. Start FastAPI server:
   ```bash
   # API role (HTTP API server)
   PROCESS_ROLE=api uvicorn backend.app.main:app --reload --port 8000
   
   # Background Outbox Worker (independent process)
   PROCESS_ROLE=worker python -m backend.app.workers.outbox_worker
   ```

5. Access interactive Swagger API documentation:
   Open [http://localhost:8000/docs](http://localhost:8000/docs).
