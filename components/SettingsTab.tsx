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
  Key
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

  const lgas = getLgasForState(form.merchantState);

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

        {/* NIPOST Integration Settings */}
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>National Digital Postcode Service Integration</h2>
              <p>Configure NIPOST API gateway credentials or use the offline simulation registry.</p>
            </div>
          </div>

          <div className="form-grid">
            <div className="form-group full">
              <label>Integration Mode</label>
              <div style={{ display: "flex", gap: "14px", marginTop: "6px" }}>
                <label
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    cursor: "pointer",
                    fontSize: "13px",
                    fontWeight: 500,
                  }}
                >
                  <input
                    type="radio"
                    name="nipostMode"
                    value="mock"
                    checked={form.nipostMode === "mock"}
                    onChange={() => setForm({ ...form, nipostMode: "mock" })}
                    style={{ width: "auto", height: "auto" }}
                  />
                  <b>Offline Local Registry (Standard NIPOST Codes)</b>
                </label>

                <label
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    cursor: "pointer",
                    fontSize: "13px",
                    fontWeight: 500,
                  }}
                >
                  <input
                    type="radio"
                    name="nipostMode"
                    value="live"
                    checked={form.nipostMode === "live"}
                    onChange={() => setForm({ ...form, nipostMode: "live" })}
                    style={{ width: "auto", height: "auto" }}
                  />
                  <b>Live NIPOST / FMCIDE Cloud API</b>
                </label>
              </div>
            </div>

            <div className="form-group full">
              <label>NIPOST API Base URL</label>
              <input
                type="url"
                value={form.nipostApiBaseUrl || ""}
                onChange={(e) => setForm({ ...form, nipostApiBaseUrl: e.target.value })}
                placeholder="https://api.nipost.gov.ng/v1"
              />
            </div>

            <div className="form-group full">
              <label>NIPOST API Secret Key</label>
              <input
                type="password"
                value={form.nipostApiKey || ""}
                onChange={(e) => setForm({ ...form, nipostApiKey: e.target.value })}
                placeholder="nipost_live_sec_************************"
              />
              <small style={{ color: "#64748b", marginTop: "4px", display: "block" }}>
                Keep your secret key confidential. In production, this connects via server-side Next.js route handlers.
              </small>
            </div>
          </div>
        </section>

        {/* Supabase Database Settings */}
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Supabase Database Sync (Optional)</h2>
              <p>Wire your remote PostgreSQL database with Row Level Security (RLS) policies.</p>
            </div>
          </div>

          <div className="form-grid">
            <div className="form-group">
              <label>NEXT_PUBLIC_SUPABASE_URL</label>
              <input
                type="url"
                placeholder="https://your-project.supabase.co"
                value={form.supabaseUrl || ""}
                onChange={(e) => setForm({ ...form, supabaseUrl: e.target.value })}
              />
            </div>

            <div className="form-group">
              <label>NEXT_PUBLIC_SUPABASE_ANON_KEY</label>
              <input
                type="password"
                placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
                value={form.supabaseAnonKey || ""}
                onChange={(e) => setForm({ ...form, supabaseAnonKey: e.target.value })}
              />
            </div>
          </div>

          <div
            style={{
              background: "#f8fafc",
              border: "1px solid var(--line)",
              borderRadius: "6px",
              padding: "12px",
              fontSize: "12px",
              color: "#475569",
              marginTop: "8px",
            }}
          >
            <b>Storage Status:</b> Currently using reactive client storage with instant local persistence. When Supabase keys are configured, data syncs automatically to your cloud database.
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

