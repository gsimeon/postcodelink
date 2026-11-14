# PostcodeLink Nigeria — Delivery Operations & National Digital Postcode Platform

A modern Next.js 15 delivery operations, out-of-band notification, and national address disambiguation platform tailored for Nigerian e-commerce merchants, last-mile logistics riders, and courier operators.

PostcodeLink bridges the gap between customer addresses (often described with informal landmarks) and official **NIPOST (Nigerian Postal Service)** digital postal codes (both the October 2026 11-character 5-component national digital postcode standard and legacy 6-digit postal codes) to eliminate driver calls ("where you dey?"), avoid missed parcels, and optimize dispatch routes.

---

## Architecture & Security Hardening (Release Gate v5.4 Production Standard)

Following an in-depth security and architectural audit of the FastAPI backend and Next.js frontend, the platform has completed enterprise-grade hardening covering all Release Gate v5.4 requirements:

### 1. P1 — Standard Authenticated Cryptography (AES-256-GCM)
- **AEAD Encryption**: Replaced XOR stream cipher with industry-standard **AES-256-GCM** via Python's `cryptography` library (`AESGCM`).
- **Context-Bound Associated Data (AAD)**: Transit OTPs stored in `notification_outbox` use 96-bit cryptographically secure random nonces and are cryptographically bound to their delivery context via Authenticated Additional Data (`f"delivery:{delivery_id}".encode()`). Any tampering with the ciphertext, nonce, or delivery association immediately fails decryption and tag verification.
- **Key Rotation & Backward Compatibility**: Supports dedicated `OUTBOX_ENCRYPTION_KEY` and candidate fallback keys via `OUTBOX_PREVIOUS_ENCRYPTION_KEYS`. Gracefully migrates and verifies legacy `v1:` HMAC and unversioned hex stream payloads.
- **Envelope Standard**: Versioned ciphertext envelopes format: `v2:<nonce_hex>:<aad_hex>:<ciphertext_and_tag_hex>`.

### 2. P1 — Official National Digital Postcode Standard (11 Characters, 5 Components)
- **October 2026 National Standard**: Full support for Nigeria's 11-character 5-component digital address standard:
  - `State` (2 letters)
  - `LGA` (2 alphanumeric)
  - `District` (3 alphanumeric)
  - `Area` (2 alphanumeric)
  - `Building` (2 alphanumeric)
  - Canonical format: `SS-LL-DDD-AA-BB` (e.g. `FC-02-A09-DB-09`, `LA-01-A04-IK-02`).
- **Strict Taxonomy & Provenance**:
  - `official_digital_postcode`: Reserved **exclusively** for codes verified against an authoritative NIPOST directory/API with `verification_status="official_verified"`. (Length alone no longer grants official status).
  - `local_address_reference`: Assigned to pilot, internal, or mock codes (e.g. `LAG-IKJ-0012`).
  - `legacy_postal_code`: Traditional 6-digit postal codes.
  - Unverified input syntax is explicitly classified with provenance `"Unverified Address Input"` and `source_owner="PostcodeLink"`, eliminating misleading references to official directories.

### 3. P1 — Authoritative NIPOST Client Status Discrimination
- **Explicit Status Discrimination**:
  - `FOUND` (200 + valid schema match)
  - `NOT_FOUND` (404 authoritative non-existence: does **not** fall back to local data, preventing false validations of non-existent codes)
  - `UNAVAILABLE` (503 / network timeout: triggers graceful fallback to local cache/database)
  - `UNAUTHORIZED` (401 / 403 API key or permission failure)
  - `INVALID_RESPONSE` (malformed schema or mismatched code)
- **Zero Masking of Missing Records**: An authoritative 404 from NIPOST reports 0 matches and does not contaminate results with speculative local estimates.

### 4. P2 — Process Role Separation (`PROCESS_ROLE`)
- **Independent Execution Roles**:
  - `PROCESS_ROLE="api"`: Dedicated HTTP API server. Disables embedded outbox processing loops in production to ensure predictability and prevent background thread starvation.
  - `PROCESS_ROLE="worker"`: Dedicated background worker process running `backend/app/workers/outbox_worker.py`.
  - `PROCESS_ROLE="all_in_one"`: Permitted in development or single-container staging deployments.
- **Production Gate**: The system refuses startup in production if `PROCESS_ROLE` is unset or invalid.

### 5. P2 — Outbox Delivery Guarantees & Duplicate Prevention
- **Provider Message Tracking**: Added `provider_message_id` and `status_reconciled_at` to `notification_outbox`.
- **At-Most-Once Provider Dispatch**: If a worker process crashes after the SMS provider (Termii/Twilio) has accepted the message, subsequent retry loops inspect `provider_message_id` and reconcile directly to `SENT` without sending duplicate SMS messages to the customer.

### 6. P2 — Complete API Key Lifecycle Management
- **Key Issuance & Management**:
  - `POST /api/v1/api-keys/` — Issue new merchant API keys with custom monthly quotas and prefix `pkl_live_...`.
  - `GET /api/v1/api-keys/` — List active keys with usage telemetry (last used timestamp, total calls, remaining quota).
  - `DELETE /api/v1/api-keys/{id}` — Immediate key revocation.
- **Authentication Middleware**: Supports authentication via `x-api-key` header with atomic call increments and monthly quota enforcement (HTTP 429 when quota exceeded).

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
- **Protected 4-Digit Delivery PIN (OTP)**: Fraud-prevention security code with phone verification challenge.
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
- **Deliveries**:
  - `POST /api/v1/deliveries/` — Create new delivery with automated NIPOST verification and outbox PIN dispatch.
  - `GET /api/v1/deliveries/` — List deliveries (scoped to authenticated merchant/courier).
  - `GET /api/v1/deliveries/{id}` — Full merchant/operator delivery details.
  - `GET /api/v1/deliveries/track/{tracking_token}` — Strict token-only public recipient tracking portal.
  - `POST /api/v1/deliveries/{id}/regenerate-token` — Regenerate and revoke public tracking URL token.
  - `POST /api/v1/deliveries/{id}/assign` — Assign courier fleet operator with capacity check.
  - `POST /api/v1/deliveries/{id}/status` — Advance lifecycle status with complete role permission matrix.
  - `POST /api/v1/deliveries/{id}/verify-otp` — Verify recipient PIN and confirm delivery (single-use revocation).
- **Postcodes & Address Cleanser**:
  - `GET /api/v1/postcodes/lookup` — Search official postcodes by area, state, or 6-digit code.
  - `POST /api/v1/postcodes/cleanse` — Normalize and standardize messy addresses against postal records.
- **Fleet Operators & Customers**:
  - `GET /api/v1/operators/` & `POST /api/v1/operators/` — Manage courier fleet.
  - `GET /api/v1/customers/` & `POST /api/v1/customers/` — Recipient directory.
- **API Keys & Integrations**:
  - `POST /api/v1/api-keys/` — Issue new merchant API keys with custom monthly quotas.
  - `GET /api/v1/api-keys/` — List active API keys and inspect call usage metrics.
  - `DELETE /api/v1/api-keys/{id}` — Revoke an API key immediately.
- **Analytics**:
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
