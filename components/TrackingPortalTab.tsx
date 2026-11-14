"use client";

import React, { useState } from "react";
import { Delivery, AppSettings } from "@/lib/types";
import {
  Search,
  Package,
  MapPin,
  Clock,
  ShieldCheck,
  CheckCircle2,
  Phone,
  MessageCircle,
  Truck,
  AlertTriangle,
  Key,
  Copy,
  Check,
  ExternalLink,
  ChevronRight,
  Eye,
  EyeOff,
  Lock
} from "lucide-react";

interface TrackingPortalTabProps {
  deliveries: Delivery[];
  settings: AppSettings;
}

export function TrackingPortalTab({
  deliveries,
  settings,
}: TrackingPortalTabProps) {
  const [trackingInput, setTrackingInput] = useState("PL-2048");
  const [searchedRef, setSearchedRef] = useState("PL-2048");

  const delivery = deliveries.find(
    (d) => d.id.toLowerCase() === searchedRef.trim().toLowerCase()
  );

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSearchedRef(trackingInput.trim());
  };

  // Tracking steps
  const steps = [
    { key: "draft", label: "Order Placed", desc: "Received at merchant hub" },
    { key: "assigned", label: "Postcode Verified", desc: "Assigned to courier partner" },
    { key: "in_transit", label: "Out for Delivery", desc: "Rider on delivery route" },
    { key: "delivered", label: "Delivered", desc: "Confirmed with OTP" },
  ];

  const getStepIndex = (status: Delivery["status"]) => {
    if (status === "delivered") return 3;
    if (status === "in_transit") return 2;
    if (status === "assigned") return 1;
    return 0;
  };

  const currentStepIdx = delivery ? getStepIndex(delivery.status) : 0;

  // Masked phone display for privacy (e.g. +234 802 *** **02)
  const maskedPhone = delivery
    ? delivery.recipientPhone.replace(/(\+?\d{3,6})\d{4}(\d{2})/, "$1 *** **$2")
    : "";

  return (
    <div>
      {/* Top Banner */}
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>PostcodeLink Customer Tracking Portal</h2>
            <p>
              Recipients and merchants can track delivery progress and postcode status.
            </p>
          </div>
        </div>

        {/* Search Bar */}
        <form onSubmit={handleSearch} style={{ display: "flex", gap: "10px", maxWidth: "600px", margin: "10px 0 20px" }}>
          <div className="search" style={{ height: "42px" }}>
            <Search size={17} />
            <input
              type="text"
              placeholder="Enter Delivery Reference (e.g. PL-2048, PL-2047, PL-2046)..."
              value={trackingInput}
              onChange={(e) => setTrackingInput(e.target.value)}
            />
          </div>
          <button type="submit" className="primary" style={{ height: "42px", padding: "0 20px" }}>
            Track Parcel
          </button>
        </form>

        {/* Quick sample chips */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", fontSize: "11px", color: "#64748b" }}>
          <span>Try sample references:</span>
          {deliveries.slice(0, 4).map((d) => (
            <button
              key={d.id}
              type="button"
              className="outline"
              style={{ height: "26px", fontSize: "10px", padding: "0 8px" }}
              onClick={() => {
                setTrackingInput(d.id);
                setSearchedRef(d.id);
              }}
            >
              {d.id} ({d.recipientName.split(" ")[0]} · {d.status.replace("_", " ")})
            </button>
          ))}
        </div>
      </section>

      {delivery ? (
        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: "20px" }}>
          {/* Main Journey Card */}
          <section className="panel" style={{ padding: "28px" }}>
            {/* Header info */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", borderBottom: "1px solid var(--line)", paddingBottom: "18px", marginBottom: "22px" }}>
              <div>
                <span className="eyebrow">SHIPMENT TRACKING</span>
                <div style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "4px" }}>
                  <h1 style={{ fontFamily: "Manrope, sans-serif", fontSize: "24px", margin: 0, fontWeight: 800 }}>
                    {delivery.id}
                  </h1>
                  <span className={`pill ${delivery.status === "delivered" ? "green" : delivery.status === "in_transit" ? "blue" : "amber"}`}>
                    <i /> {delivery.status.replace("_", " ")}
                  </span>
                </div>
                <div style={{ fontSize: "12px", color: "#64748b", marginTop: "4px" }}>
                  Estimated Delivery: <b style={{ color: "var(--ink)" }}>{delivery.estimatedDeliveryTime || "In regular business hours"}</b>
                </div>
              </div>

              {delivery.postcodeStatus === "verified" ? (
                <div className="postcode-badge verified" style={{ padding: "6px 12px", fontSize: "12px" }}>
                  <ShieldCheck size={14} /> NG-{delivery.verifiedPostcode} (NIPOST Verified)
                </div>
              ) : (
                <div className="postcode-badge unverified" style={{ padding: "6px 12px", fontSize: "12px" }}>
                  <AlertTriangle size={14} /> Manual Landmark Routing
                </div>
              )}
            </div>

            {/* Interactive Step Progress Tracker */}
            <div style={{ margin: "28px 0 34px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", position: "relative", marginBottom: "8px" }}>
                {/* Connecting bar */}
                <div
                  style={{
                    position: "absolute",
                    top: "14px",
                    left: "20px",
                    right: "20px",
                    height: "3px",
                    background: "#e2e8f0",
                    zIndex: 0,
                  }}
                >
                  <div
                    style={{
                      height: "100%",
                      background: "#2563eb",
                      width: `${(currentStepIdx / (steps.length - 1)) * 100}%`,
                      transition: "width 0.3s ease",
                    }}
                  />
                </div>

                {steps.map((st, idx) => {
                  const isDone = idx <= currentStepIdx;
                  const isCurrent = idx === currentStepIdx;
                  return (
                    <div
                      key={st.key}
                      style={{
                        position: "relative",
                        zIndex: 1,
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        width: "100px",
                        textAlign: "center",
                      }}
                    >
                      <div
                        style={{
                          width: "30px",
                          height: "30px",
                          borderRadius: "50%",
                          background: isDone ? "#2563eb" : "#ffffff",
                          color: isDone ? "#ffffff" : "#94a3b8",
                          border: `3px solid ${isDone ? "#2563eb" : "#cbd5e1"}`,
                          display: "grid",
                          placeItems: "center",
                          fontSize: "12px",
                          fontWeight: 700,
                          boxShadow: isCurrent ? "0 0 0 4px rgba(37,99,235,0.2)" : "none",
                        }}
                      >
                        {isDone ? "✓" : idx + 1}
                      </div>
                      <b style={{ fontSize: "11px", marginTop: "8px", color: isDone ? "var(--ink)" : "#94a3b8" }}>
                        {st.label}
                      </b>
                      <small style={{ fontSize: "9px", color: "#64748b", marginTop: "2px" }}>
                        {st.desc}
                      </small>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Destination & Package Details */}
            <div className="form-grid">
              <div style={{ background: "#f8fafc", padding: "14px", borderRadius: "8px", border: "1px solid var(--line)" }}>
                <span style={{ fontSize: "10px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                  DESTINATION ADDRESS
                </span>
                <b style={{ fontSize: "13px", display: "block", marginTop: "4px" }}>{delivery.destinationAddress}</b>
                {delivery.landmark && (
                  <div style={{ fontSize: "11px", color: "#166534", marginTop: "2px" }}>
                    Landmark: {delivery.landmark}
                  </div>
                )}
                <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                  {delivery.destinationArea}, {delivery.destinationState}
                </div>
              </div>

              <div style={{ background: "#f8fafc", padding: "14px", borderRadius: "8px", border: "1px solid var(--line)" }}>
                <span style={{ fontSize: "10px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                  PACKAGE & LOGISTICS
                </span>
                <b style={{ fontSize: "13px", display: "block", marginTop: "4px" }}>{delivery.packageDescription || "Parcel"}</b>
                <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                  Courier: <b>{delivery.operatorName || "Awaiting assignment"}</b>
                </div>
                <div style={{ fontSize: "11px", color: "#0f766e", marginTop: "2px", fontWeight: 600 }}>
                  Delivery Fee: ₦{delivery.fee?.toLocaleString() || "Prepaid"}
                </div>
              </div>
            </div>
          </section>

          {/* Right Column: Protected Security PIN & Courier Contact */}
          <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
            {/* POD remains disabled until backed by authenticated server-side storage. */}
            <section className="panel">
              <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 700, fontSize: "13px", marginBottom: "8px" }}>
                <ShieldCheck size={16} /> Proof of Delivery
              </div>
              {delivery.podVerified ? (
                <div style={{ background: "#dcfce7", border: "1px solid #86efac", color: "#166534", padding: "12px", borderRadius: "8px", fontWeight: 700, fontSize: "13px" }}>
                  Proof of Delivery marked as verified
                </div>
              ) : (
                <p style={{ fontSize: "12px", color: "#64748b", lineHeight: 1.5, margin: 0 }}>
                  Secure PIN verification is temporarily unavailable while server-side OTP storage and authenticated rider access are being configured. No PIN is displayed or verified in this public tracking view.
                </p>
              )}
            </section>

            {/* Courier & Support Card */}
            <section className="panel">
              <div style={{ fontSize: "12px", fontWeight: 700, color: "var(--ink)", marginBottom: "12px", display: "flex", alignItems: "center", gap: "6px" }}>
                <Truck size={15} color="#2563eb" /> Courier & Dispatch Contact
              </div>

              <b style={{ fontSize: "13px", display: "block" }}>{delivery.operatorName || "Unassigned"}</b>
              <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                Official Courier Partner
              </div>

              <div style={{ display: "flex", gap: "8px", marginTop: "14px" }}>
                <a
                  href={`tel:${delivery.recipientPhone}`}
                  className="outline"
                  style={{ flex: 1, height: "36px", textDecoration: "none", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}
                >
                  <Phone size={14} color="#2563eb" /> Call Rider
                </a>
                <a
                  href={`https://wa.me/2348034519021?text=${encodeURIComponent(`Hello, I am tracking parcel ${delivery.id} heading to ${delivery.destinationArea}.`)}`}
                  target="_blank"
                  rel="noreferrer"
                  className="primary"
                  style={{ flex: 1, height: "36px", background: "#25D366", borderColor: "#25D366", textDecoration: "none", display: "inline-flex", alignItems: "center", justifyContent: "center", gap: "6px" }}
                >
                  <MessageCircle size={14} /> WhatsApp
                </a>
              </div>
            </section>
          </div>
        </div>
      ) : (
        <section className="panel" style={{ textAlign: "center", padding: "48px 20px" }}>
          <Package size={40} color="#94a3b8" style={{ margin: "auto", marginBottom: "12px" }} />
          <h3>No Shipment Found for "{searchedRef}"</h3>
          <p style={{ color: "#64748b", fontSize: "12px", maxWidth: "420px", margin: "auto" }}>
            Please verify the tracking reference code (e.g. <code>PL-2048</code>) sent in your merchant order confirmation.
          </p>
        </section>
      )}
    </div>
  );
}
