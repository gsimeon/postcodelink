# PostcodeLink Nigeria — Delivery Operations & Digital Postcode Platform

A modern Next.js 15 delivery operations and address disambiguation platform tailored for Nigerian e-commerce merchants, last-mile logistics riders, and courier operators.

PostcodeLink bridges the gap between customer addresses (often described with informal landmarks) and official **NIPOST (Nigerian Postal Service)** 6-digit digital postal codes to eliminate driver calls ("where you dey?"), avoid missed parcels, and optimize dispatch routes.

---

## Architecture & Security Hardening (v1.4.0 Release Gate Production Standard)

Following an in-depth security and architectural audit of the FastAPI backend and Next.js frontend, the platform has completed enterprise-grade hardening covering all Release Gate requirements:

### 1. P0 — Authentication & Privilege Escalation Immunity
- **Public Registration Role Lockdown**: Public registration (`POST /api/v1/auth/register`) strictly sets account role to `merchant`. Client-supplied role attributes are discarded.
- **Login Rate Limiting & Brute-Force Guard**: Implemented in-memory sliding window rate limiting on `POST /api/v1/auth/login`. After 5 consecutive failed attempts, the account is locked for 15 minutes (HTTP 429).
- **Interactive Auth Flow**: Interactive `AuthModal` supporting credentials login and registration with JWT token persistence.
- **Controlled Account Provisioning**: Operator couriers and additional platform administrators can only be provisioned by authenticated Platform Admins via `POST /api/v1/auth/admin/create-user`.
- **Production Secret & Migration Guard**: In `production` environments, the API refuses startup if `SECRET_KEY` is missing, default, or shorter than 32 characters. `Base.metadata.create_all` is disabled in production to guarantee Alembic migration integrity.

### 2. P0 — Genuine Out-of-Band SMS Dispatches & Persistent Notification Outbox
- **Real HTTP Provider Adapters**: Implemented genuine HTTP dispatches in `notification_service.py`:
  - `TermiiNotificationProvider`: Dispatches real SMS over Nigerian mobile networks (`api.ng.termii.com/api/sms/send`) with HTTP status validation, phone sanitization (`234...`), and 10s request timeouts.
  - `TwilioNotificationProvider`: Dispatches international SMS and WhatsApp messages (`api.twilio.com`) with HTTP 201 Created validation.
  - `SimulatedNotificationProvider`: Sandbox mock for zero-cost local development returning `SIMULATED`.
- **Accurate Outbox Reporting**: Never falsely claims `SENT` without verified provider API acknowledgment. Returns `FAILED` with provider error details on API rejections or network timeouts.
- **Database-Backed Persistent Outbox**: Every delivery creation transaction atomically inserts a `notification_outbox` record (`d8b2ddd3352d` migration) tracking channel, recipient phone, provider, status (`QUEUED`, `SENT`, `SIMULATED`, `FAILED`), retry count, and error details.
- **Asynchronous Outbox Processor**: Includes `process_notification_outbox()` for background queue processing and retries with backoff.
- **Zero-Knowledge PIN Privacy**: Plaintext PINs are **never** logged or stored in application memory or ordinary outbox records. Phone numbers are strictly masked (`080****7890`) in all server log outputs.

### 3. P0 — Strict Delivery Lifecycle Stage Enforcement for Proof-of-Delivery PINs
- **Out for Delivery Gate**: `POST /api/v1/deliveries/{id}/verify-otp` strictly enforces that an order must be in `OUT_FOR_DELIVERY` status before accepting PIN confirmation. Verification requests on `PENDING`, `ASSIGNED`, `PICKED_UP`, or `IN_TRANSIT` orders are rejected with HTTP 400.
- **Single-Use Revocation**: Upon successful verification, `otp_hash` is immediately overwritten with `REVOKED_AND_VERIFIED`, preventing replay attacks.
- **Brute-Force Lockout**: 3 failed verification attempts lock PIN verification for 15 minutes (HTTP 429).

### 4. P0 — Operator Workload Accounting & Double-Decrement Elimination
- **State-Aware Active Slot Accounting**: Operator `active_deliveries_count` is decremented if and only if the order was occupying an active transit slot (`ASSIGNED`, `PICKED_UP`, `IN_TRANSIT`, `OUT_FOR_DELIVERY`).
- **Elimination of Double-Decrement on Failures**: Moving `FAILED -> CANCELLED` does not decrement the counter a second time because the slot was already released upon entering `FAILED`.
- **Re-attempt Support**: Re-attempting an order from `FAILED` back to `OUT_FOR_DELIVERY` correctly increments the active workload counter.

### 5. P0 — National Postcode Directory Expansion & Strict Area Consistency
- **National Coverage Across 11 States**: Official 6-digit postal codes covering:
  - **Lagos State** (Zone 1: Ikeja Central, Ikeja GRA, Lekki Phase 1, Victoria Island, Ikoyi, Yaba, Surulere, Festac, Oshodi, Maryland, Gbagada, Agege, Ikorodu, Badagry, Epe, Magodo, Apapa)
  - **Abuja FCT** (Zone 9: Garki Area 1-11, Wuse 2, Maitama, Asokoro, CBD, Gwarinpa, Utako/Jabi, Kubwa, Lugbe, Nyanya)
  - **Rivers State** (Zone 5: Old GRA, D-Line, Trans-Amadi, Rumuola, Choba, Eleme)
  - **Oyo State** (Zone 2: Bodija, Dugbe, Ring Road, UI, Oluyole)
  - **Ogun State** (Zone 1: Abeokuta Central, Ibara GRA, Ota Industrial Zone, Mowe/Ibafo)
  - **Kano State** (Zone 7: Kano Central, Fagge, Bompai / Nassarawa, Sabon Gari)
  - **Kaduna State** (Zone 8: Kaduna Central, Malali GRA, Barnawa)
  - **Enugu State** (Zone 4: Independence Layout, New Haven/Ogui, GRA Enugu)
  - **Delta State** (Zone 3: Asaba Central, Warri Central, Effurun)
  - **Edo State** (Zone 3: Benin City Central, GRA Benin City)
  - **Anambra State** (Zone 4: Awka Central, Onitsha Main Market)
- **Documented Provenance**: Standardized against NIPOST Official Digital Postcode Directory — National Pilot Edition v2024.2.
- **Independent Area Consistency Validation**: `cleanse_address` validates supplied `area_hint` independently against the reference record (`matched_area` / `matched_lga`). Conflicting areas appearing in address text are detected and flagged as `conflict` (< 0.60 confidence), preventing false `verified` badges on deliveries.
- **Zero Fallback**: Unrecognized locations are marked `unverified` with 0.0 confidence and **zero arbitrary fallback to 100001**.

### 6. P0 — Token-Only Public Tracking & Fleet Telemetry Privacy
- **Strict Cryptographic Hex Tokens**: `GET /api/v1/deliveries/track/{tracking_token}` strictly enforces 32-byte cryptographic tokens. Querying human-readable delivery IDs (`PL-...`) returns HTTP 404.
- **Token Revocation & Regeneration**: Instant revocation via `POST /api/v1/deliveries/{id}/regenerate-token`.
- **Fleet Privacy**: Merchant operator queries receive `OperatorDirectoryResponse` with redacted phone numbers, GPS coordinates, and workload counts. Full fleet telemetry is reserved for Platform Administrators.

### 7. Dual PostgreSQL & SQLite CI/CD Pipeline
- **GitHub Actions Workflow (`.github/workflows/ci.yml`)**:
  - Spin up `postgres:16` service container with health checks.
  - Run Alembic migrations and database seeding against PostgreSQL.
  - Run 21/21 Pytest security and API integration tests against PostgreSQL.
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

3. Run FastAPI automated security & API test suite (21/21 tests passing):
   ```bash
   npm run backend:test
   # Or: backend/venv/Scripts/python -m pytest backend/tests -v
   ```

4. Start FastAPI server:
   ```bash
   npm run backend:dev
   # Or: backend/venv/Scripts/uvicorn backend.app.main:app --reload --port 8000
   ```

5. Access interactive Swagger API documentation:
   Open [http://localhost:8000/docs](http://localhost:8000/docs).
