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
  onVerifyOtp: (deliveryId: string, otp: string) => { success: boolean; message: string; remainingAttempts?: number } | Promise<{ success: boolean; message: string; remainingAttempts?: number }>;
}

export function TrackingPortalTab({
  deliveries,
  settings,
  onVerifyOtp,
}: TrackingPortalTabProps) {
  const [trackingInput, setTrackingInput] = useState("PL-2048");
  const [searchedRef, setSearchedRef] = useState("PL-2048");
  const [enteredOtp, setEnteredOtp] = useState("");
  const [otpNotice, setOtpNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [copiedOtp, setCopiedOtp] = useState(false);

  // P0 Security: OTP masking & identity challenge
  const [isPinRevealed, setIsPinRevealed] = useState(false);
  const [phoneChallenge, setPhoneChallenge] = useState("");
  const [challengeError, setChallengeError] = useState("");

  const delivery = deliveries.find(
    (d) =>
      d.id.toLowerCase() === searchedRef.trim().toLowerCase() ||
      ((d as any).tracking_token && (d as any).tracking_token === searchedRef.trim())
  );

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSearchedRef(trackingInput.trim());
    setOtpNotice(null);
    setIsPinRevealed(false);
    setPhoneChallenge("");
    setChallengeError("");
  };

  const handleCopyOtp = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedOtp(true);
    setTimeout(() => setCopiedOtp(false), 2000);
  };

  // Challenge verification: verify recipient owns this parcel before revealing the PIN
  const handleRevealPin = (e: React.FormEvent) => {
    e.preventDefault();
    if (!delivery) return;
    const cleanPhone = delivery.recipientPhone.replace(/\D/g, "");
    const lastFour = cleanPhone.slice(-4);
    if (phoneChallenge.trim() === lastFour) {
      setIsPinRevealed(true);
      setChallengeError("");
    } else {
      setChallengeError("Last 4 digits did not match recipient phone.");
    }
  };

  const handleConfirmOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!delivery) return;
    const res = await onVerifyOtp(delivery.id, enteredOtp.trim());
    if (res.success) {
      setOtpNotice({ type: "success", text: res.message });
      setEnteredOtp("");
    } else {
      setOtpNotice({ type: "error", text: res.message });
    }
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
              Recipients and merchants can track live delivery progress, view verified NIPOST routing codes, and confirm proof of delivery via OTP.
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
                setOtpNotice(null);
                setIsPinRevealed(false);
                setPhoneChallenge("");
                setChallengeError("");
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
            {/* P0 Security: Protected Proof of Delivery PIN (OTP) Card */}
            <section
              className="panel"
              style={{
                background: "linear-gradient(180deg, #ffffff, #f0fdf4)",
                border: "1px solid #bbf7d0",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#166534", fontWeight: 700, fontSize: "13px", marginBottom: "6px" }}>
                <Key size={16} /> Delivery Confirmation PIN (OTP)
              </div>
              <p style={{ fontSize: "11px", color: "#475569", margin: "0 0 12px", lineHeight: 1.5 }}>
                A 4-digit security PIN has been dispatched to recipient <b>{maskedPhone}</b>. Give this PIN to the courier upon delivery.
              </p>

              {delivery.podVerified ? (
                <div style={{ background: "#dcfce7", border: "1px solid #86efac", color: "#166534", padding: "12px", borderRadius: "8px", textAlign: "center", fontWeight: 700, fontSize: "13px" }}>
                  ✓ Proof of Delivery Verified
                  <div style={{ fontSize: "10px", fontWeight: 400, marginTop: "2px" }}>
                    {delivery.podNote || "Authenticated via OTP"}
                  </div>
                </div>
              ) : isPinRevealed ? (
                /* Authenticated PIN View */
                <div style={{ background: "#ffffff", border: "2px dashed #86efac", borderRadius: "8px", padding: "16px", textAlign: "center" }}>
                  <div style={{ fontSize: "10px", color: "#64748b", letterSpacing: "1px", fontWeight: 700, textTransform: "uppercase" }}>
                    CONFIRMATION PIN (AUTHENTICATED)
                  </div>
                  <div
                    style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: "30px",
                      fontWeight: 800,
                      letterSpacing: "8px",
                      color: "#166534",
                      margin: "6px 0",
                    }}
                  >
                    {delivery.otp || "4821"}
                  </div>
                  <div style={{ display: "flex", gap: "6px", justifyContent: "center" }}>
                    <button
                      type="button"
                      className="outline"
                      style={{ height: "26px", fontSize: "11px", padding: "0 8px" }}
                      onClick={() => handleCopyOtp(delivery.otp || "4821")}
                    >
                      {copiedOtp ? <Check size={12} color="#16a34a" /> : <Copy size={12} />} Copy PIN
                    </button>
                    <button
                      type="button"
                      className="outline"
                      style={{ height: "26px", fontSize: "11px", padding: "0 8px" }}
                      onClick={() => setIsPinRevealed(false)}
                    >
                      <EyeOff size={12} /> Hide
                    </button>
                  </div>
                </div>
              ) : (
                /* Masked Public View with Identity Challenge */
                <div style={{ background: "#f8fafc", border: "1px solid var(--line)", borderRadius: "8px", padding: "14px" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "#475569" }}>
                      <Lock size={14} color="#64748b" />
                      <span>Security PIN: <b style={{ letterSpacing: "4px" }}>••••</b></span>
                    </div>
                    <span style={{ fontSize: "10px", background: "#e2e8f0", padding: "2px 6px", borderRadius: "4px" }}>
                      Masked for Privacy
                    </span>
                  </div>

                  <form onSubmit={handleRevealPin} style={{ marginTop: "10px", borderTop: "1px solid #e2e8f0", paddingTop: "10px" }}>
                    <label style={{ fontSize: "10px", color: "#64748b", display: "block", marginBottom: "4px" }}>
                      Are you the recipient? Enter last 4 digits of phone ({maskedPhone}):
                    </label>
                    <div style={{ display: "flex", gap: "6px" }}>
                      <input
                        type="password"
                        maxLength={4}
                        placeholder="Last 4 digits"
                        value={phoneChallenge}
                        onChange={(e) => setPhoneChallenge(e.target.value)}
                        style={{
                          width: "110px",
                          height: "30px",
                          border: "1px solid #cbd5e1",
                          borderRadius: "4px",
                          textAlign: "center",
                          fontSize: "12px",
                          letterSpacing: "2px",
                        }}
                      />
                      <button type="submit" className="outline" style={{ height: "30px", fontSize: "11px" }}>
                        <Eye size={12} /> Reveal PIN
                      </button>
                    </div>
                    {challengeError && (
                      <div style={{ fontSize: "10px", color: "#dc2626", marginTop: "4px" }}>
                        {challengeError}
                      </div>
                    )}
                  </form>
                </div>
              )}

              {/* Courier Rider OTP Verification Form (with attempt limits) */}
              {!delivery.podVerified && (
                <form onSubmit={handleConfirmOtp} style={{ marginTop: "16px", borderTop: "1px solid #e2e8f0", paddingTop: "14px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#475569", display: "block", marginBottom: "4px" }}>
                    Courier Rider: Verify Recipient PIN on Delivery
                  </label>
                  <small style={{ fontSize: "10px", color: "#64748b", display: "block", marginBottom: "6px" }}>
                    Enforces 3-attempt limit with 15-minute lockout to prevent brute-force.
                  </small>
                  <div style={{ display: "flex", gap: "8px" }}>
                    <input
                      type="text"
                      maxLength={4}
                      placeholder="Enter 4-digit PIN"
                      value={enteredOtp}
                      onChange={(e) => setEnteredOtp(e.target.value)}
                      style={{
                        flex: 1,
                        height: "36px",
                        border: "1px solid #cbd5e1",
                        borderRadius: "6px",
                        textAlign: "center",
                        fontSize: "14px",
                        fontWeight: 700,
                        letterSpacing: "4px",
                      }}
                    />
                    <button type="submit" className="primary" style={{ height: "36px" }}>
                      Authenticate
                    </button>
                  </div>
                  {otpNotice && (
                    <div
                      style={{
                        marginTop: "8px",
                        fontSize: "11px",
                        color: otpNotice.type === "success" ? "#16a34a" : "#dc2626",
                        fontWeight: 600,
                      }}
                    >
                      {otpNotice.text}
                    </div>
                  )}
                </form>
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
          <h3>No Shipment Found for &quot;{searchedRef}&quot;</h3>
          <p style={{ color: "#64748b", fontSize: "12px", maxWidth: "420px", margin: "auto" }}>
            Please verify the tracking reference code (e.g. <code>PL-2048</code>) sent in your merchant order confirmation.
          </p>
        </section>
      )}
    </div>
  );
}
