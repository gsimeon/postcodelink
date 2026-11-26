"use client";

import React, { useState } from "react";
import { AppSettings } from "@/lib/types";
import {
  Settings2,
  Save,
  RotateCcw,
  Download,
  ShieldCheck,
  Database,
  Cloud,
  CheckCircle2,
  AlertTriangle,
  Key,
  Lock
} from "lucide-react";
import { STATES_LIST, getLgasForState } from "@/lib/nigeria-postcodes";

interface SettingsTabProps {
  settings: AppSettings;
  onSaveSettings: (settings: AppSettings) => void;
  onResetData: () => void;
  onExportAllData: () => void;
}

export function SettingsTab({
  settings,
  onSaveSettings,
  onResetData,
  onExportAllData,
}: SettingsTabProps) {
  const [form, setForm] = useState<AppSettings>(settings);
  const [savedNotice, setSavedNotice] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSaveSettings(form);
    setSavedNotice(true);
    setTimeout(() => setSavedNotice(false), 3000);
  };

  return (
    <div>
      {savedNotice && (
        <div
          style={{
            background: "#dcfce7",
            border: "1px solid #bbf7d0",
            color: "#15803d",
            padding: "12px 16px",
            borderRadius: "8px",
            marginBottom: "20px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
            fontWeight: 600,
          }}
        >
          <CheckCircle2 size={16} /> Workspace settings saved successfully.
        </div>
      )}

      <form onSubmit={handleSubmit}>
        {/* Merchant Store Profile */}
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Merchant Profile & Dispatch Hub</h2>
              <p>Your primary origin address printed on delivery notes and consignment slips.</p>
            </div>
            <button type="submit" className="primary">
              <Save size={15} /> Save Changes
            </button>
          </div>

          <div className="form-grid">
            <div className="form-group">
              <label>Merchant / Business Name *</label>
              <input
                type="text"
                required
                value={form.merchantName}
                onChange={(e) => setForm({ ...form, merchantName: e.target.value })}
              />
            </div>

            <div className="form-group">
              <label>Operations Phone Number *</label>
              <input
                type="text"
                required
                value={form.merchantPhone}
                onChange={(e) => setForm({ ...form, merchantPhone: e.target.value })}
              />
            </div>

            <div className="form-group full">
              <label>Warehouse / Dispatch Hub Street Address *</label>
              <input
                type="text"
                required
                value={form.merchantAddress}
                onChange={(e) => setForm({ ...form, merchantAddress: e.target.value })}
              />
            </div>

            <div className="form-group">
              <label>State *</label>
              <select
                value={form.merchantState}
                onChange={(e) => setForm({ ...form, merchantState: e.target.value })}
              >
                {STATES_LIST.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>LGA</label>
              <input
                type="text"
                value={form.merchantLga}
                onChange={(e) => setForm({ ...form, merchantLga: e.target.value })}
              />
            </div>
          </div>
        </section>

        {/* NIPOST Integration & Security Architecture */}
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>National Digital Postcode Gateway Architecture</h2>
              <p>Server-side integration architecture and secret isolation (verification mode is selected directly in the Postcode Intelligence workspace).</p>
            </div>
          </div>

          <div className="form-grid">
            {/* P1 Security Fix: Server-side environment credential boundary */}
            <div
              className="form-group full"
              style={{
                background: "#f0fdf4",
                border: "1px solid #bbf7d0",
                borderRadius: "8px",
                padding: "16px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#166534", fontWeight: 700, fontSize: "13px", marginBottom: "6px" }}>
                <Lock size={16} /> Server-Side Secret Isolation (Production Standard)
              </div>
              <p style={{ fontSize: "12px", color: "#14532d", margin: "0 0 10px", lineHeight: 1.5 }}>
                In compliance with the PostcodeLink Reliability Gate, upstream API secrets (<code>NIPOST_API_KEY</code>) are never stored in browser storage or managed from client settings. Requests route through FastAPI using the server-configured gateway and local pilot reference dataset (11-state pilot coverage; not independently NIPOST-verified):
              </p>
              <div style={{ fontFamily: "monospace", fontSize: "11px", background: "#ffffff", padding: "10px", borderRadius: "6px", border: "1px solid #86efac", color: "#0f172a" }}>
                <div>GET  /api/v1/postcodes/lookup?code=105102  → Server-authenticated lookup</div>
                <div style={{ marginTop: "4px" }}>POST /api/v1/postcodes/cleanse             → Server-side address resolution</div>
              </div>
            </div>
          </div>
        </section>

        {/* Database Authority & Tenant Security Architecture */}
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Database Authority & Tenant Security Architecture</h2>
              <p>Authoritative schema migrations (Alembic / SQLAlchemy) and FastAPI RBAC boundaries.</p>
            </div>
          </div>

          <div
            style={{
              background: "#f8fafc",
              border: "1px solid var(--line)",
              borderRadius: "8px",
              padding: "16px",
              fontSize: "12px",
              color: "#475569",
              lineHeight: 1.6,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 700, color: "var(--ink)", marginBottom: "8px" }}>
              <Database size={16} color="#2563eb" /> Single Schema Authority & Application-Enforced Tenant Isolation
            </div>
            <div>
              • <b>Alembic & SQLAlchemy (Single Schema Authority):</b> All production PostgreSQL and local SQLite schema migrations are managed exclusively via Alembic (<code>backend/alembic/versions/</code>). Legacy Supabase SQL files (<code>supabase/migrations/</code>) are retained solely as reference DDL and are not applied independently.
            </div>
            <div style={{ marginTop: "4px" }}>
              • <b>FastAPI Authentication & RBAC Boundaries:</b> Application-layer JWT / API-key guards enforce strict tenant isolation:
              <ul style={{ margin: "6px 0 0 20px", padding: 0, fontSize: "11px", color: "#64748b" }}>
                <li><b>Merchants:</b> Scoped strictly to their own deliveries, API keys, and audit events.</li>
                <li><b>Operators:</b> Scoped strictly to deliveries assigned to their operator profile.</li>
                <li><b>Immutable Audit Ledgers:</b> Both <code>delivery_events</code> and <code>verification_evidence</code> enforce database-level triggers blocking <code>UPDATE</code> and <code>DELETE</code> operations.</li>
              </ul>
            </div>
          </div>
        </section>

        {/* Data & Backup Tools */}
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Data Management & Backup</h2>
              <p>Export database backups or reset to factory demo state.</p>
            </div>
          </div>

          <div style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>
            <button type="button" className="outline" onClick={onExportAllData}>
              <Download size={15} /> Export Complete JSON Backup
            </button>
            <button
              type="button"
              className="danger-btn"
              onClick={() => {
                if (
                  confirm(
                    "Are you sure you want to reset all data back to the default demo records? This will clear custom deliveries."
                  )
                ) {
                  onResetData();
                }
              }}
            >
              <RotateCcw size={15} /> Reset Demo Workspace
            </button>
          </div>
        </section>
      </form>
    </div>
  );
}
