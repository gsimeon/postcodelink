"use client";

import React from "react";
import {
  Activity,
  Package,
  MapPin,
  Truck,
  Users,
  Settings2,
  ChevronDown,
  CircleHelp,
  ArrowRight,
  Navigation,
  Compass,
  BarChart3,
  Upload
} from "lucide-react";

export type TabKey =
  | "overview"
  | "deliveries"
  | "map"
  | "tracking"
  | "postcodes"
  | "operators"
  | "customers"
  | "analytics"
  | "settings";

interface SidebarProps {
  activeTab: TabKey;
  setActiveTab: (tab: TabKey) => void;
  deliveriesCount: number;
  unassignedCount: number;
  availableOperatorsCount: number;
}

export function Sidebar({
  activeTab,
  setActiveTab,
  deliveriesCount,
  unassignedCount,
  availableOperatorsCount,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      {/* Brand */}
      <div className="brand">
        <div className="brand-mark">
          <MapPin size={22} />
        </div>
        <div>
          <strong>PostcodeLink</strong>
          <span>NIGERIA</span>
        </div>
      </div>

      {/* Workspace Switcher */}
      <div className="workspace">
        <div className="avatar">P</div>
        <div>
          <b>Peak Stores Lagos</b>
          <small>Merchant workspace</small>
        </div>
        <ChevronDown size={14} color="#94a3b8" />
      </div>

      {/* Main Operations Navigation */}
      <p className="nav-label">DISPATCH OPERATIONS</p>
      <button
        type="button"
        className={`nav ${activeTab === "overview" ? "active" : ""}`}
        onClick={() => setActiveTab("overview")}
      >
        <Activity size={17} /> Overview
      </button>

      <button
        type="button"
        className={`nav ${activeTab === "deliveries" ? "active" : ""}`}
        onClick={() => setActiveTab("deliveries")}
      >
        <Package size={17} /> Deliveries Hub
        <span className="nav-count">{deliveriesCount}</span>
      </button>

      <button
        type="button"
        className={`nav ${activeTab === "map" ? "active" : ""}`}
        onClick={() => setActiveTab("map")}
      >
        <Navigation size={17} /> Dispatch Radar (Map)
      </button>

      <button
        type="button"
        className={`nav ${activeTab === "tracking" ? "active" : ""}`}
        onClick={() => setActiveTab("tracking")}
      >
        <Compass size={17} /> Public Tracking Portal
      </button>

      {/* Postcode & Fleet Tools */}
      <p className="nav-label second">NETWORK & COURIERS</p>
      <button
        type="button"
        className={`nav ${activeTab === "postcodes" ? "active" : ""}`}
        onClick={() => setActiveTab("postcodes")}
      >
        <MapPin size={17} /> Postcode Registry & Cleanser
      </button>

      <button
        type="button"
        className={`nav ${activeTab === "operators" ? "active" : ""}`}
        onClick={() => setActiveTab("operators")}
      >
        <Truck size={17} /> Courier Fleet
        {availableOperatorsCount > 0 && (
          <span className="nav-count" style={{ background: "#dcfce7", color: "#15803d" }}>
            {availableOperatorsCount} live
          </span>
        )}
      </button>

      {/* Management & Analytics */}
      <p className="nav-label second">INTELLIGENCE & SETTINGS</p>
      <button
        type="button"
        className={`nav ${activeTab === "analytics" ? "active" : ""}`}
        onClick={() => setActiveTab("analytics")}
      >
        <BarChart3 size={17} /> Zone Analytics & SLAs
      </button>

      <button
        type="button"
        className={`nav ${activeTab === "customers" ? "active" : ""}`}
        onClick={() => setActiveTab("customers")}
      >
        <Users size={17} /> Customers Directory
      </button>

      <button
        type="button"
        className={`nav ${activeTab === "settings" ? "active" : ""}`}
        onClick={() => setActiveTab("settings")}
      >
        <Settings2 size={17} /> Settings & API
      </button>

      {/* Help Card */}
      <div className="help">
        <CircleHelp size={18} color="#2563eb" />
        <b>Digital Postcodes in Nigeria</b>
        <small>Official 6-digit codes optimize last-mile dispatch across Lagos, Abuja & major cities.</small>
        <button type="button" onClick={() => setActiveTab("postcodes")}>
          Open Registry <ArrowRight size={13} />
        </button>
      </div>

      {/* User profile */}
      <div className="profile">
        <div className="avatar">GS</div>
        <div>
          <b>Godwin Simeon</b>
          <small>Operations Admin</small>
        </div>
        <ChevronDown size={14} color="#94a3b8" />
      </div>
    </aside>
  );
}
