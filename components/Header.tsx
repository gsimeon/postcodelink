"use client";

import React, { useState } from "react";
import { Bell, Sparkles, CheckCircle2 } from "lucide-react";
import { TabKey } from "./Sidebar";
import { AppSettings } from "@/lib/types";

interface HeaderProps {
  activeTab: TabKey;
  settings: AppSettings;
  unassignedCount: number;
}

export function Header({ activeTab, settings, unassignedCount }: HeaderProps) {
  const [showNotifications, setShowNotifications] = useState(false);

  const tabTitles: Record<TabKey, string> = {
    overview: "Overview",
    deliveries: "Deliveries Hub",
    map: "Interactive Dispatch Radar & Fleet Map",
    tracking: "Public Customer Tracking Portal",
    postcodes: "Nigerian Postcode Directory & Cleanser",
    operators: "Logistics Dispatch Operators",
    customers: "Customer Directory",
    analytics: "Zone Performance & Courier SLAs",
    settings: "Workspace Settings & API",
  };

  return (
    <header className="topbar">
      <div className="crumb">
        Workspace <span>/</span> <strong>{tabTitles[activeTab]}</strong>
      </div>

      <div className="top-actions">
        {/* Environment Tag */}
        <div className="env-tag">
          <span className={`status-dot ${settings.nipostMode === "mock" ? "amber" : ""}`} />
          <span>
            {settings.nipostMode === "mock"
              ? "NIPOST Local Registry (Active)"
              : "NIPOST Live Production API"}
          </span>
        </div>

        {/* Notifications Icon with Popup */}
        <div style={{ position: "relative" }}>
          <button
            type="button"
            className="icon-btn"
            aria-label="Notifications"
            onClick={() => setShowNotifications(!showNotifications)}
          >
            <Bell size={17} />
            {unassignedCount > 0 && (
              <span
                style={{
                  position: "absolute",
                  top: "2px",
                  right: "2px",
                  width: "8px",
                  height: "8px",
                  borderRadius: "50%",
                  background: "#dc2626",
                }}
              />
            )}
          </button>

          {showNotifications && (
            <div
              style={{
                position: "absolute",
                right: 0,
                top: "44px",
                width: "280px",
                background: "#ffffff",
                border: "1px solid var(--line)",
                borderRadius: "10px",
                boxShadow: "var(--shadow-md)",
                padding: "14px",
                zIndex: 50,
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: "10px",
                  fontWeight: 700,
                  fontSize: "12px",
                }}
              >
                <span>Activity & Alerts</span>
                <span style={{ fontSize: "10px", color: "var(--blue)" }}>Mark all read</span>
              </div>
              {unassignedCount > 0 ? (
                <div
                  style={{
                    background: "#fffbeb",
                    border: "1px solid #fef3c7",
                    borderRadius: "6px",
                    padding: "8px 10px",
                    fontSize: "11px",
                    color: "#b45309",
                    marginBottom: "8px",
                  }}
                >
                  <b>{unassignedCount} delivery awaiting dispatch</b>
                  <div style={{ marginTop: "2px", fontSize: "10px" }}>
                    Assign available courier operators for fastest SLA.
                  </div>
                </div>
              ) : (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    color: "#16a34a",
                    fontSize: "11px",
                    marginBottom: "8px",
                  }}
                >
                  <CheckCircle2 size={14} /> All deliveries currently assigned
                </div>
              )}
              <div
                style={{
                  fontSize: "11px",
                  color: "#64748b",
                  borderTop: "1px solid var(--line)",
                  paddingTop: "8px",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                <Sparkles size={13} color="#2563eb" /> PostcodeLink routing engine ready
              </div>
            </div>
          )}
        </div>

        {/* User Badge */}
        <div className="avatar small">GS</div>
      </div>
    </header>
  );
}
