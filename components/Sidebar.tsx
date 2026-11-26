"use client";

import React from "react";
import { FastAPIProfile } from "@/lib/fastapi-client";
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
  Upload,
  Key
} from "lucide-react";

export type TabKey =
  | "overview"
  | "deliveries"
  | "map"
  | "tracking"
  | "postcodes"
  | "developer"
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
  profile?: FastAPIProfile | null;
}

export function Sidebar({
  activeTab,
  setActiveTab,
  deliveriesCount,
  unassignedCount,
  availableOperatorsCount,
  profile,
}: SidebarProps) {
  const userInitials = profile?.full_name
    ? profile.full_name
        .split(" ")
        .filter(Boolean)
        .map((n) => n[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : "AU";

  const workspaceInitial = profile?.business_name
    ? profile.business_name[0].toUpperCase()
    : "P";

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
        <div className="avatar">{workspaceInitial}</div>
        <div>
          <b>{profile?.business_name || "Postcode Intelligence"}</b>
          <small>{profile?.role ? `${profile.role.toUpperCase()} Workspace` : "Postcode Intelligence Core"}</small>
        </div>
        <ChevronDown size={14} color="#94a3b8" />
      </div>

      {/* Primary Workspace Navigation: Postcode Intelligence */}
      <p className="nav-label">POSTCODE INTELLIGENCE (CORE)</p>
      <button
        type="button"
        className={`nav ${activeTab === "postcodes" ? "active" : ""}`}
        onClick={() => setActiveTab("postcodes")}
      >
        <MapPin size={17} /> Postcode Explorer & Cleanser
      </button>

      <button
        type="button"
        className={`nav ${activeTab === "developer" ? "active" : ""}`}
        onClick={() => setActiveTab("developer")}
      >
        <Key size={17} /> Developer API Console
      </button>

      {/* Decoupled Downstream Logistics Module */}
      <p className="nav-label second">LOGISTICS & DISPATCH (MODULE)</p>
      <button
        type="button"
        className={`nav ${activeTab === "overview" ? "active" : ""}`}
        onClick={() => setActiveTab("overview")}
      >
        <Activity size={17} /> Operations Overview
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

      {/* Fleet & Network Tools */}
      <p className="nav-label second">FLEET & NETWORK</p>
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

      <button
        type="button"
        className={`nav ${activeTab === "customers" ? "active" : ""}`}
        onClick={() => setActiveTab("customers")}
      >
        <Users size={17} /> Customers Directory
      </button>

      {/* Intelligence & Settings */}
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
        className={`nav ${activeTab === "settings" ? "active" : ""}`}
        onClick={() => setActiveTab("settings")}
      >
        <Settings2 size={17} /> Settings & API
      </button>

      {/* Help Card */}
      <div className="help">
        <CircleHelp size={18} color="#2563eb" />
        <b>Nigerian Digital Postcodes</b>
        <small>Validates 11-character digital codes (SS-LL-DDD-AA-BB) and legacy 6-digit references. Local pilot records are not independently NIPOST-verified.</small>
        <button type="button" onClick={() => setActiveTab("postcodes")}>
          Open Explorer <ArrowRight size={13} />
        </button>
      </div>

      {/* User profile */}
      <div className="profile">
        <div className="avatar">{userInitials}</div>
        <div>
          <b>{profile?.full_name || "Account User"}</b>
          <small>{profile?.role ? `${profile.role.toUpperCase()} User` : "Operations Admin"}</small>
        </div>
        <ChevronDown size={14} color="#94a3b8" />
      </div>
    </aside>
  );
}
