# PostcodeLink Nigeria — Delivery Operations & National Digital Postcode Platform

A modern Next.js 15 delivery operations, out-of-band notification, and national address disambiguation platform tailored for Nigerian e-commerce merchants, last-mile logistics riders, and courier operators.

PostcodeLink bridges the gap between customer addresses (often described with informal landmarks) and official **NIPOST (Nigerian Postal Service)** digital postal codes (both the October 2026 11-character 5-component national digital postcode standard and legacy 6-digit postal codes) to eliminate driver calls ("where you dey?"), avoid missed parcels, and optimize dispatch routes.

---

## Architecture & Security Hardening (Release Gate v5.7 Production Standard)

Following an in-depth security, operational, and distributed systems audit of the FastAPI backend and Next.js frontend, the platform has completed enterprise-grade hardening covering all Release Gate v5.7 requirements:

### 1. P1 — Targeted Postcode Migration (Exact Demonstration Fixture Isolation)
- **Narrow Migration Matching**: Alembic migration `e5f6a7b8c9d0` strictly targets known demonstration fixtures by exact code (`WHERE code IN ('FC-02-A09-DB-09', 'LA-01-A04-IK-02')`). All broad text-based heuristics (`LIKE '%Demonstration%'`, `LIKE '%Pilot%'`, `LIKE '%Local Reference%'`) have been eliminated.
- **Strict Verification Preservation**: Legitimate government-verified records with NIPOST provenance are preserved without exception as `verification_status="official_verified"`.
- **Reversibility**: Downgrade routines are documented and tested, restoring demonstration fixtures cleanly. Real Alembic migration execution tests run on every CI build.

### 2. P1 — Resilient SMS Crash Recovery & Outbound Status Reconciliation
- **Crash Recovery Without Saved Message ID**: When a background worker crashes between provider HTTP acceptance and database commit, `provider_message_id` is lost. Upon recovery, the worker queries the provider by `recipient_phone` and `idempotency_key`. If the provider cannot conclusively confirm delivery, the item transitions to `RECONCILIATION_REQUIRED` and is **never blindly re-dispatched**, eliminating duplicate customer SMS risks.
- **Provider Gateway Status Inquiries**: `check_message_status` implemented across `SimulatedNotificationProvider`, `TwilioNotificationProvider` (querying recent outbound messages to recipient by E.164), and `TermiiNotificationProvider`.

### 3. P1 — Privacy-Hardened, Admin-Only Manual Reconciliation Workflows
- **Strict RBAC Enforcement**: `GET /api/v1/deliveries/outbox/reconciliation` and `POST /api/v1/deliveries/outbox/{id}/reconcile` are restricted exclusively to `AppRole.ADMIN`. Courier operators receive HTTP 403 Forbidden.
- **Customer Privacy Protection**: Full recipient phone numbers are masked in reconciliation listings (`recipient_phone_masked: "+234803***789"`), preventing unauthorized inspection of merchant customer records.
- **Mandatory Audit Reason & Evidence**: Manual resolutions (`mark_sent`, `requeue`, `mark_failed`) require an explicit reason (`reason` >= 10 characters). Marking an item as sent strictly requires carrier evidence (`provider_message_id` or `evidence_reference`). Every resolution appends an immutable `DeliveryEvent` audit entry recording actor email, role, action, and rationale.

### 4. P1 — Strict NIPOST Verification with Input Validation
- **Mandatory Postcode Parameter**: In strict verification mode (`GET /api/v1/postcodes/lookup?strict=true`), omitting the `code` parameter raises HTTP 422 Unprocessable Content. Area-only discovery is barred from strict verification.
- **Zero Local Fallback in Strict Mode**: If upstream NIPOST is unavailable or returns an error, the API fails closed (HTTP 502/503) and never silently falls back to local reference fixtures.

### 5. P2 — Distributed Redis-Backed Rate Limiting
- **Pluggable Sliding-Window Store**: Per-minute API key rate limits use an atomic Redis sorted-set sliding window (`ZREMRANGEBYSCORE` / `ZCARD` / `ZADD` / `EXPIRE`) when `REDIS_URL` is configured, guaranteeing shared enforcement across distributed API instances and process restarts.
- **Memory-Safe In-Memory Fallback**: When Redis is unconfigured, falls back to an in-memory thread-safe sliding window with periodic TTL eviction of stale keys (every 120s) to prevent memory leaks.
- **Invalid Configuration Rejection**: Non-positive rate limits (`<= 0`) are rejected immediately with HTTP 400 Bad Request rather than treated as unlimited.

### 6. P2 — Persistent Cross-Process Worker Heartbeat
- **Database Heartbeat Persistence**: Worker instances record heartbeats in the `worker_heartbeats` table (migration `f6a7b8c9d0e1`), storing `worker_id`, `process_id`, `hostname`, `status`, `processed_count`, and `last_heartbeat_at`.
- **Standalone Process Monitoring**: `/health/worker` queries persistent database heartbeats, reliably monitoring standalone worker daemon processes (`python -m backend.app.workers.outbox_worker`) across isolated OS processes and containers. Reports `status="operational"` or `status="degraded"` if heartbeats exceed the configurable threshold (`OUTBOX_WORKER_HEARTBEAT_THRESHOLD_SECONDS = 120`).

### 7. P2 — Sanitized, Real Integration Health Probes
- **Live Reachability & Authentication Probes**: `/health/integrations` tests external provider status using bounded network probes (1.5s timeout), separating `configured`, `reachable`, `authenticated`, `last_successful_check`, and `last_error_category`.
- **Zero Information Leakage**: Internal infrastructure URLs (`base_url`, `url`), API keys, and credentials are completely omitted from the public health response.

### 8. P2 — Concurrent API-Key Rotation Protection
- **Atomic Conditional Updates**: `POST /api/v1/api-keys/{id}/rotate` executes an atomic conditional update (`is_active = False, is_revoked = True WHERE is_active = True AND is_revoked = False`). Simultaneous rotation requests race safely: exactly one generates a replacement credential, while competing requests receive HTTP 409 Conflict.
- **Quota Inheritance**: Replacement credentials inherit billing period usage (`period_usage_count`) and lifetime usage from the rotated key, preventing quota reset bypasses.

### 9. P0 — Dual PostgreSQL 16 & Redis 7 CI/CD Pipeline
- **GitHub Actions Workflow (`.github/workflows/ci.yml`)**:
  - Spin up `postgres:16` and `redis:7` service containers with health checks.
  - Run Alembic migrations and database seeding against PostgreSQL 16.
  - Run 95/95 Pytest security, cryptography, and API integration tests against PostgreSQL and Redis.
  - Verify SQLite migration and local fallback test compatibility.
  - Run 7/7 Node.js state-machine and 6-digit OTP security tests.
  - Compile production Next.js 15 build with 0 errors.

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
- **Nigerian Address Cleanser & Standardizer**: Pasting unstructured customer notes with local landmarks (e.g. *"Beside Access Bank, Plot 412 Aminu Kano Crescent, Wuse 2, Abuja"* or *"Opposite Yellow Gate after transformer"*) automatically extracts the area, LGA, State, and attaches the matching official NIPOST 6-digit code.
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
   npm install
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
   
   # Seed official Nigerian postcodes and initial profiles
   npm run backend:seed
   # Or: backend/venv/Scripts/python -m backend.app.seed
   ```

3. Run FastAPI automated security & API test suite (68/68 tests passing):
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
