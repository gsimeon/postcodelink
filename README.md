# PostcodeLink Nigeria — Delivery Operations & Digital Postcode Platform

A modern Next.js 15 delivery operations and address disambiguation platform tailored for Nigerian e-commerce merchants, last-mile logistics riders, and courier operators.

PostcodeLink bridges the gap between customer addresses (often described with informal landmarks) and official **NIPOST (Nigerian Postal Service)** 6-digit digital postal codes to eliminate driver calls ("where you dey?"), avoid missed parcels, and optimize dispatch routes.

---

## Complete Features

### 1. Operations Overview Dashboard
- **Real-Time KPIs**: Total deliveries, in-transit parcels, deliveries awaiting dispatch, and verified postcode adoption percentage.
- **Recent Deliveries Feed**: Interactive table with status badges, verified NIPOST tags, and quick-view action drawers.
- **Service Status Card**: Real-time indicator for the NIPOST digital postcode service (Local 6-digit registry vs Live FMCIDE Cloud API).

### 2. Deliveries Management Hub
- **Lifecycle Pipeline**: Filter across `Awaiting Dispatch`, `Assigned`, `In Transit`, and `Delivered`.
- **Search & Multi-Filters**: Search by reference ID (`PL-2048`), recipient name, phone, address, landmark, state, or assigned courier.
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
- **4-Digit Delivery PIN (OTP)**: Fraud-prevention security code for delivery confirmation.
- **Direct Courier Communication**: Direct one-click links to Call Courier or Chat via WhatsApp.
- **Simulated Route Visualizer**: Vector route connecting merchant origin hub (Sabo-Yaba) to destination.

### 5. Bulk CSV & Batch Order Dispatch
- **Multi-Line Order Importer**: Paste order data from Shopify, Instagram DMs, or WhatsApp.
- **Parallel NIPOST Auto-Resolver**: Batch-cleanses and validates addresses across all lines in parallel.
- **One-Click Dispatch All**: Create dozens of verified orders with tracking IDs in one action.
- **Sample Batch Pre-Loader**: Test immediate batch dispatch with authentic Nigerian merchant sample records.

### 6. WhatsApp Dispatch & Tracking Notifications
- **Customer Updates**: One-click WhatsApp link generator sending formatted tracking links and 4-digit OTPs directly to recipients.
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

## Tech Stack
- **Framework**: Next.js 15 (App Router, Turbopack, React 19)
- **Language**: TypeScript 5.8
- **Icons**: Lucide React
- **Styling**: Responsive CSS with clean light palette (DM Sans, Manrope, JetBrains Mono)
- **Database Schema**: Supabase PostgreSQL migration ready in `supabase/migrations/0001_initial_schema.sql`

---

## Running Locally

1. Install dependencies:
   ```bash
   npm install
   ```

2. Setup environment variables:
   ```bash
   cp .env.example .env.local
   ```

3. Run development server:
   ```bash
   npm run dev
   ```

4. Open [http://localhost:3000](http://localhost:3000) in your browser.

5. Test production build:
   ```bash
   npm run build
   ```
