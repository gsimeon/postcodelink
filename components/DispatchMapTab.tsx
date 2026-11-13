"use client";

import React, { useState, useMemo } from "react";
import { Delivery, Operator, AppSettings } from "@/lib/types";
import {
  MapPin,
  Truck,
  Navigation,
  Eye,
  CheckCircle2,
  Clock,
  Layers,
  Filter,
  ShieldCheck,
  Compass,
  ArrowRight
} from "lucide-react";

interface DispatchMapTabProps {
  deliveries: Delivery[];
  operators: Operator[];
  settings: AppSettings;
  onSelectDelivery: (delivery: Delivery) => void;
}

type MapRegion = "lagos" | "abuja" | "national";

export function DispatchMapTab({
  deliveries,
  operators,
  settings,
  onSelectDelivery,
}: DispatchMapTabProps) {
  const [region, setRegion] = useState<MapRegion>("lagos");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [selectedPin, setSelectedPin] = useState<Delivery | null>(null);

  // Region boundaries and coordinate projections for SVG canvas (width: 800, height: 450)
  const regionConfigs = {
    lagos: {
      title: "Lagos Metropolitan Dispatch Zone (01-Zone)",
      minLat: 6.40,
      maxLat: 6.66,
      minLng: 3.25,
      maxLng: 3.60,
      landmarks: [
        { name: "Lekki Phase 1", x: 620, y: 320, code: "105102" },
        { name: "Victoria Island", x: 500, y: 350, code: "101241" },
        { name: "Ikoyi", x: 530, y: 300, code: "101233" },
        { name: "Yaba / Sabo (Hub)", x: 410, y: 220, code: "101212" },
        { name: "Ikeja / Alausa", x: 380, y: 110, code: "100001" },
        { name: "Ikeja GRA", x: 370, y: 150, code: "100271" },
        { name: "Maryland", x: 420, y: 170, code: "100211" },
        { name: "Festac Town", x: 190, y: 300, code: "102102" },
        { name: "Magodo", x: 450, y: 90, code: "100248" },
      ]
    },
    abuja: {
      title: "Abuja (FCT) Federal Capital Territory (09-Zone)",
      minLat: 8.95,
      maxLat: 9.18,
      minLng: 7.30,
      maxLng: 7.60,
      landmarks: [
        { name: "Garki Area 1-11", x: 490, y: 270, code: "900001" },
        { name: "Wuse 2", x: 440, y: 200, code: "900288" },
        { name: "Maitama District", x: 520, y: 160, code: "900271" },
        { name: "Central Business District", x: 500, y: 230, code: "900211" },
        { name: "Gwarinpa Estate", x: 260, y: 140, code: "900108" },
        { name: "Kubwa", x: 150, y: 80, code: "901101" },
        { name: "Lugbe / Airport Rd", x: 200, y: 360, code: "900107" },
      ]
    },
    national: {
      title: "Nigeria National Dispatch Topology (All Zones)",
      minLat: 4.5,
      maxLat: 13.5,
      minLng: 3.0,
      maxLng: 14.0,
      landmarks: [
        { name: "Lagos Hub", x: 140, y: 340, code: "100001" },
        { name: "Ibadan (Oyo)", x: 170, y: 310, code: "200001" },
        { name: "Abuja FCT", x: 380, y: 240, code: "900001" },
        { name: "Port Harcourt (Rivers)", x: 340, y: 390, code: "500001" },
        { name: "Kano Municipal", x: 450, y: 120, code: "700001" },
        { name: "Kaduna North", x: 370, y: 170, code: "800001" },
        { name: "Enugu", x: 380, y: 350, code: "400001" },
        { name: "Benin City (Edo)", x: 270, y: 350, code: "300001" },
      ]
    }
  };

  const currentConfig = regionConfigs[region];

  // Map latitude/longitude to SVG x,y
  const projectCoords = (lat: number, lng: number) => {
    const { minLat, maxLat, minLng, maxLng } = currentConfig;
    const x = ((lng - minLng) / (maxLng - minLng)) * 720 + 40;
    const y = ((maxLat - lat) / (maxLat - minLat)) * 360 + 45;
    return {
      x: Math.max(30, Math.min(770, x)),
      y: Math.max(30, Math.min(420, y)),
    };
  };

  // Filter deliveries for map
  const activeDeliveries = useMemo(() => {
    return deliveries.filter((d) => {
      if (statusFilter !== "all" && d.status !== statusFilter) return false;
      if (region === "lagos" && d.destinationState !== "Lagos") return false;
      if (region === "abuja" && d.destinationState !== "Abuja (FCT)") return false;
      return true;
    });
  }, [deliveries, statusFilter, region]);

  return (
    <div>
      {/* Map Control Bar */}
      <section className="panel" style={{ padding: "18px 22px", marginBottom: "16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <Navigation size={18} color="#2563eb" />
              <h2 style={{ fontSize: "16px", margin: 0 }}>Interactive Dispatch Radar & Fleet Map</h2>
            </div>
            <p style={{ margin: "2px 0 0", fontSize: "11px", color: "#64748b" }}>
              {currentConfig.title} · Visualizing {activeDeliveries.length} orders & {operators.filter(o => o.isAvailable).length} active couriers
            </p>
          </div>

          {/* Region Switcher Pills */}
          <div style={{ display: "flex", gap: "6px" }}>
            <button
              type="button"
              className={`pill ${region === "lagos" ? "blue" : "gray"}`}
              style={{ cursor: "pointer", border: "none" }}
              onClick={() => { setRegion("lagos"); setSelectedPin(null); }}
            >
              Lagos Metro (01)
            </button>
            <button
              type="button"
              className={`pill ${region === "abuja" ? "blue" : "gray"}`}
              style={{ cursor: "pointer", border: "none" }}
              onClick={() => { setRegion("abuja"); setSelectedPin(null); }}
            >
              Abuja FCT (09)
            </button>
            <button
              type="button"
              className={`pill ${region === "national" ? "blue" : "gray"}`}
              style={{ cursor: "pointer", border: "none" }}
              onClick={() => { setRegion("national"); setSelectedPin(null); }}
            >
              National Nigeria
            </button>
          </div>

          {/* Status Filter */}
          <select
            className="select-filter"
            style={{ height: "34px", fontSize: "11px" }}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="all">All Delivery Statuses</option>
            <option value="in_transit">In Transit Only</option>
            <option value="pending_assignment">Awaiting Dispatch Only</option>
            <option value="delivered">Delivered Only</option>
          </select>
        </div>
      </section>

      {/* Main SVG Radar Map Canvas */}
      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 0.7fr", gap: "20px" }}>
        <section
          className="panel"
          style={{
            position: "relative",
            background: "linear-gradient(145deg, #0b132b, #1c2541)",
            padding: 0,
            overflow: "hidden",
            borderRadius: "12px",
            minHeight: "460px",
            boxShadow: "0 10px 30px rgba(11,19,43,0.3)",
          }}
        >
          {/* Radar background grid lines */}
          <svg
            viewBox="0 0 800 450"
            style={{ width: "100%", height: "100%", display: "block" }}
          >
            {/* Background grid */}
            <defs>
              <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
                <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#253252" strokeWidth="0.5" />
              </pattern>
              <radialGradient id="radarSweep" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.15" />
                <stop offset="100%" stopColor="#0b132b" stopOpacity="0" />
              </radialGradient>
            </defs>

            <rect width="800" height="450" fill="url(#grid)" />
            <circle cx="400" cy="225" r="200" fill="url(#radarSweep)" stroke="#253252" strokeWidth="1" strokeDasharray="4 4" />
            <circle cx="400" cy="225" r="100" fill="none" stroke="#253252" strokeWidth="1" />

            {/* Region landmarks / District nodes */}
            {currentConfig.landmarks.map((lm, i) => (
              <g key={lm.name} transform={`translate(${lm.x}, ${lm.y})`}>
                <circle r="4" fill="#3b82f6" opacity="0.6" />
                <text
                  x="8"
                  y="4"
                  fill="#94a3b8"
                  fontSize="9"
                  fontFamily="'DM Sans', sans-serif"
                  fontWeight="600"
                >
                  {lm.name} ({lm.code})
                </text>
              </g>
            ))}

            {/* Merchant Hub Pin (Origin) */}
            {region === "lagos" && (
              <g transform="translate(410, 220)">
                <circle r="14" fill="#2563eb" opacity="0.25">
                  <animate attributeName="r" values="8;22;8" dur="3s" repeatCount="indefinite" />
                </circle>
                <circle r="8" fill="#2563eb" stroke="#ffffff" strokeWidth="2" />
                <text x="-40" y="-14" fill="#60a5fa" fontSize="10" fontWeight="800">
                  ★ HUB: Sabo-Yaba
                </text>
              </g>
            )}

            {/* Delivery Pins */}
            {activeDeliveries.map((d) => {
              const pos = d.coordinates
                ? projectCoords(d.coordinates.lat, d.coordinates.lng)
                : { x: 300, y: 200 };

              const isSelected = selectedPin?.id === d.id;
              const pinColor =
                d.status === "delivered"
                  ? "#22c55e"
                  : d.status === "in_transit"
                  ? "#38bdf8"
                  : "#f59e0b";

              return (
                <g
                  key={d.id}
                  transform={`translate(${pos.x}, ${pos.y})`}
                  style={{ cursor: "pointer" }}
                  onClick={() => setSelectedPin(d)}
                >
                  {/* Pulse ring for in-transit */}
                  {d.status === "in_transit" && (
                    <circle r="16" fill={pinColor} opacity="0.3">
                      <animate attributeName="r" values="8;20;8" dur="2s" repeatCount="indefinite" />
                    </circle>
                  )}
                  <circle
                    r={isSelected ? "11" : "8"}
                    fill={pinColor}
                    stroke="#ffffff"
                    strokeWidth={isSelected ? "3" : "1.5"}
                  />
                  <text
                    x="12"
                    y="4"
                    fill="#ffffff"
                    fontSize="10"
                    fontWeight="700"
                    fontFamily="'JetBrains Mono', monospace"
                  >
                    {d.id}
                  </text>
                </g>
              );
            })}
          </svg>

          {/* Map Legend Overlay */}
          <div
            style={{
              position: "absolute",
              bottom: "14px",
              left: "14px",
              background: "rgba(11, 19, 43, 0.85)",
              backdropFilter: "blur(6px)",
              padding: "10px 14px",
              borderRadius: "8px",
              border: "1px solid #253252",
              display: "flex",
              gap: "14px",
              fontSize: "11px",
              color: "#cbd5e1",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#38bdf8" }} />
              In Transit
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#f59e0b" }} />
              Awaiting Rider
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#22c55e" }} />
              Delivered
            </div>
          </div>
        </section>

        {/* Right Info / Selected Pin Drawer */}
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {selectedPin ? (
            <section className="panel" style={{ border: "2px solid #2563eb" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <div>
                  <span className="ref" style={{ fontSize: "14px" }}>{selectedPin.id}</span>
                  <b style={{ display: "block", fontSize: "14px", marginTop: "2px" }}>
                    {selectedPin.recipientName}
                  </b>
                </div>
                <span className={`pill ${selectedPin.status === "delivered" ? "green" : selectedPin.status === "in_transit" ? "blue" : "amber"}`}>
                  {selectedPin.status.replace("_", " ")}
                </span>
              </div>

              <div style={{ fontSize: "12px", color: "#475569", marginBottom: "12px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "4px" }}>
                  <MapPin size={13} color="#2563eb" /> {selectedPin.destinationAddress}
                </div>
                {selectedPin.landmark && (
                  <div style={{ fontSize: "11px", color: "#166534", marginLeft: "19px" }}>
                    Landmark: {selectedPin.landmark}
                  </div>
                )}
                <div style={{ marginLeft: "19px", fontSize: "11px", color: "#64748b" }}>
                  {selectedPin.destinationArea}, {selectedPin.destinationState}
                </div>
              </div>

              <div
                style={{
                  background: "#f8fafc",
                  padding: "10px",
                  borderRadius: "6px",
                  border: "1px solid var(--line)",
                  fontSize: "11px",
                  marginBottom: "14px",
                }}
              >
                <div>
                  NIPOST Routing: <b>{selectedPin.verifiedPostcode ? `NG-${selectedPin.verifiedPostcode}` : "Manual Address"}</b>
                </div>
                <div style={{ marginTop: "3px" }}>
                  Courier: <b>{selectedPin.operatorName || "Unassigned"}</b>
                </div>
                <div style={{ marginTop: "3px" }}>
                  Security PIN: <b style={{ fontFamily: "monospace" }}>{selectedPin.otp || "4821"}</b>
                </div>
              </div>

              <button
                type="button"
                className="primary"
                style={{ width: "100%", height: "36px" }}
                onClick={() => onSelectDelivery(selectedPin)}
              >
                <Eye size={14} /> Open Full Details & Audit Trail
              </button>
            </section>
          ) : (
            <section className="panel" style={{ textAlign: "center", padding: "24px 16px" }}>
              <Navigation size={28} color="#94a3b8" style={{ margin: "auto", marginBottom: "8px" }} />
              <b style={{ fontSize: "13px" }}>Select any Radar Pin</b>
              <p style={{ fontSize: "11px", color: "#64748b", margin: "4px 0 0" }}>
                Click on any marker on the map to inspect parcel routing, recipient information, and rider location.
              </p>
            </section>
          )}

          {/* Active Courier Fleet Status */}
          <section className="panel">
            <div className="panel-head" style={{ marginBottom: "12px" }}>
              <div>
                <h2>Available Courier Fleet</h2>
                <p>On-duty dispatch riders in this sector</p>
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {operators.slice(0, 3).map((op) => (
                <div
                  key={op.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "8px 10px",
                    background: "#f8fafc",
                    borderRadius: "6px",
                    border: "1px solid var(--line)",
                    fontSize: "11px",
                  }}
                >
                  <div>
                    <b>{op.businessName}</b>
                    <small style={{ display: "block", color: "#64748b" }}>
                      {op.vehicleType} · {op.currentZone || "Lagos Metro"}
                    </small>
                  </div>
                  <span className={`pill ${op.isAvailable ? "green" : "amber"}`} style={{ fontSize: "9px" }}>
                    {op.isAvailable ? "Ready" : "Busy"}
                  </span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
