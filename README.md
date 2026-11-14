# PostcodeLink Nigeria — Delivery Operations & Digital Postcode Platform

A modern Next.js 15 delivery operations and address disambiguation platform tailored for Nigerian e-commerce merchants, last-mile logistics riders, and courier operators.

PostcodeLink bridges the gap between customer addresses (often described with informal landmarks) and official **NIPOST (Nigerian Postal Service)** 6-digit digital postal codes to eliminate driver calls ("where you dey?"), avoid missed parcels, and optimize dispatch routes.

---

## Architecture & Security Hardening (v1.3.0 Release Gate Standard)

Following an in-depth security and architectural audit of the FastAPI backend and Next.js frontend, the platform has completed enterprise-grade hardening covering all Release Gate requirements:

### 1. P0 — Authentication & Privilege Escalation Immunity
- **Public Registration Role Lockdown**: Public registration (`POST /api/v1/auth/register`) strictly sets account role to `merchant`. Client-supplied role attributes are discarded.
- **Interactive Auth Flow**: Replaced demo one-click credentials with an interactive `AuthModal` supporting both registration and credential login with JWT storage.
- **Controlled Account Provisioning**: Operator couriers and additional platform administrators can only be provisioned by authenticated Platform Admins via `POST /api/v1/auth/admin/create-user`.
- **Production Secret & Migration Guard**: In `production` environments, the API refuses startup if `SECRET_KEY` is missing, default, or shorter than 32 characters. `Base.metadata.create_all` is disabled in production to guarantee Alembic migration integrity.

### 2. P0 — Complete Multi-Tenant Isolation & Analytics Scoping
- **Customer Directory Isolation**: Customer records are strictly scoped by `merchant_id` with a database-level composite unique constraint `(merchant_id, phone)`. Merchants can only list, read, or delete recipient entries belonging to their account.
- **Delivery Order Isolation**: Merchants are prevented from viewing or modifying orders belonging to other merchants. Courier operators only access deliveries dispatched to their specific fleet.
- **Tenant-Scoped Analytics**: Merchant analytics only aggregate deliveries and unique customer records owned by the authenticated merchant. Operator analytics are strictly filtered to assigned orders and completely withhold merchant commercial revenue figures.

### 3. P0 — Zero-Knowledge Delivery PIN Privacy & Pluggable Notification Outbox
- **Zero-Knowledge API Boundary**: The plaintext confirmation PIN is **never** returned in any API response payload—not in delivery creation, order detail, status logs, or notification preview payloads.
- **No In-Memory or Log Retention**: Removed in-memory notification lists and eliminated PIN logging in application logs. Phone numbers are strictly masked (`080****7890`) in all server log outputs.
- **Pluggable Notification Adapter**: Implemented `notification_service.py` with provider abstraction supporting:
  - `TermiiNotificationProvider` (Nigerian SMS/WhatsApp routes)
  - `TwilioNotificationProvider` (Global SMS)
  - `SimulatedNotificationProvider` (Local development mock)
- **Accurate Outbox Status Reporting**: Dispatches report accurate states (`SIMULATED`, `SENT`, `QUEUED`, `FAILED`) rather than claiming artificial delivery.
- **Cryptographic Storage & Single-Use Revocation**: Stored using SHA-256 with order-specific salt. Upon successful delivery confirmation, the hash is immediately overwritten with `REVOKED_AND_VERIFIED`, preventing replay attacks.
- **Concurrency-Safe Lockout**: Verifications acquire row-level locks (`with_for_update()`). Brute-force protection limits failed attempts to 3, after which a 15-minute lockout is enforced.

### 4. P0 — Privacy-Preserving Token-Only Public Tracking Portal
- **Strict Cryptographic Token Enforceability**: The public tracking endpoint (`GET /api/v1/deliveries/track/{tracking_token}`) strictly enforces 32-byte cryptographic hex tokens. Attempting to query with human-readable delivery IDs (`PL-...`) returns HTTP 404 to block sequential enumeration and scraping.
- **Token Revocation & Regeneration**: Merchants and administrators can revoke leaked tracking links and generate fresh tokens via `POST /api/v1/deliveries/{id}/regenerate-token`.
- **PII Masking**: Recipient names (`C******* N*****`) and phone numbers (`080****7890`) are masked on public views.
- **Internal Data Shielding**: Exact street addresses, landmarks, GPS coordinates, fulfillment fees, package descriptions, and internal rider/admin audit notes are withheld from unauthenticated tracking responses.

### 5. P0 — Operator Fleet Privacy & Telemetry Masking
- **Restricted Merchant Directory View**: When merchants list or inspect fleet couriers, sensitive driver contact details (phone numbers, full names), exact real-time GPS coordinates, and internal active delivery counts are redacted via `OperatorDirectoryResponse`. Merchants only receive `has_capacity: bool` and public vehicle metadata.
- **Full Telemetry for Admins Only**: Unrestricted fleet contact details, GPS tracking coordinates, and active workload counts are strictly reserved for Platform Administrators (`OperatorResponse`).
- **Contextual Courier Contact on Assigned Orders**: Once an order is assigned, only the assigned operator's contact is exposed to the merchant strictly on that specific delivery record (`OperatorAssignedResponse`).

### 6. P0 — Centralized Postcode Verification, Area Consistency & Provenance
- **NIPOST Reference Provenance**: Documented and verified against the official Nigerian Postal Service standard (NIPOST National Postcode Directory Edition v2024.1).
- **Multi-Factor Consistency Checks**: Address cleansing (`cleanse_address`) accepts `area_hint` and returns `postcode_valid`, `address_consistent`, and `dispatch_confidence`.
- **Conflict Detection**: If a valid postcode is paired with a conflicting administrative zone (e.g., Lekki postcode with an Ikeja area), the engine flags it as `conflict` and lowers confidence below 0.60, preventing false `verified` status badges.
- **No False Positives or Fallbacks**: Area-only matches receive `estimated` status (never `verified`). Unknown addresses receive `unverified` and empty postcodes with **zero fallback to 100001**.

### 7. P0 — Complete Role-Transition Matrix & Operator Workload Accounting
- **Role Permission Enforcement**:
  - `PENDING` (Unassignment): Only merchant owner or admin can unassign a courier back to pending.
  - `PICKED_UP`, `IN_TRANSIT`, `OUT_FOR_DELIVERY`: Strictly assigned courier or platform admin.
  - `FAILED`: Strictly assigned courier or platform admin.
  - `CANCELLED`: Deliveries in transit can only be cancelled by platform administrators; pending/assigned deliveries can be cancelled by merchant owner or admin.
  - `DELIVERED`: Terminal status achievable strictly through the recipient PIN verification endpoint.
- **Atomic Counter Accounting**: Operator `active_deliveries_count` is decremented atomically with row-level locks whenever an order is unassigned back to `PENDING`, marked `FAILED`, `CANCELLED`, or successfully `DELIVERED`.

### 8. Continuous Integration & Automated Testing Pipeline
- **GitHub Actions Workflow**: Added `.github/workflows/ci.yml` running automated tests on every push and pull request to `main`:
  - Python 3.12 environment with Alembic migrations, PostgreSQL readiness check, and 14/14 passing Pytest integration/security tests.
  - Node.js 22 environment with 6/6 passing unit tests and a verified Next.js 15 production build (`next build`).

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

3. Run FastAPI automated security & API test suite (14/14 tests passing):
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
