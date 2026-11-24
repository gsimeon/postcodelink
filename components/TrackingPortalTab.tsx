"use client";

import React, { useState } from "react";
import { Delivery, AppSettings } from "@/lib/types";
import { fastApiClient, FastAPIPublicTracking } from "@/lib/fastapi-client";
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
  Lock,
  Shield,
  HelpCircle,
  ShieldAlert
} from "lucide-react";

interface TrackingPortalTabProps {
  deliveries: Delivery[];
  settings: AppSettings;
  onVerifyOtp: (deliveryId: string, otp: string) => { success: boolean; message: string; remainingAttempts?: number } | Promise<{ success: boolean; message: string; remainingAttempts?: number }>;
  isDemoMode?: boolean;
}

export function TrackingPortalTab({
  deliveries,
  settings,
  onVerifyOtp,
  isDemoMode = false,
}: TrackingPortalTabProps) {
  const [trackingInput, setTrackingInput] = useState("");
  const [searchedRef, setSearchedRef] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Active tracking state from server or demo fallback
  const [publicTracking, setPublicTracking] = useState<FastAPIPublicTracking | null>(null);
  const [isDemoView, setIsDemoView] = useState(false);
  const [demoDelivery, setDemoDelivery] = useState<Delivery | null>(null);

  // Server-side Recipient Challenge Verification
  const [phoneChallenge, setPhoneChallenge] = useState("");
  const [isChallengeVerifying, setIsChallengeVerifying] = useState(false);
  const [challengeVerified, setChallengeVerified] = useState(false);
  const [challengeError, setChallengeError] = useState("");

  // OTP Confirmation State
  const [enteredOtp, setEnteredOtp] = useState("");
  const [isOtpSubmitting, setIsOtpSubmitting] = useState(false);
  const [otpNotice, setOtpNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const handleSearch = async (e?: React.FormEvent, tokenOverride?: string) => {
    if (e) e.preventDefault();
    const token = (tokenOverride || trackingInput).trim();
    if (!token) return;

    setSearchedRef(token);
    setSearchError(null);
    setChallengeError("");
    setChallengeVerified(false);
    setOtpNotice(null);
    setEnteredOtp("");
    setPhoneChallenge("");

    const is32CharToken = /^[A-Za-z0-9_-]{32}$/.test(token);

    // If not a 32-character token
    if (!is32CharToken) {
      if (isDemoMode) {
        const localMatch = deliveries.find((d) => d.id.toLowerCase() === token.toLowerCase());
        if (localMatch) {
          setIsDemoView(true);
          setDemoDelivery(localMatch);
          setPublicTracking(null);
          return;
        }
      }

      setSearchError(
        "Public tracking requires an exact 32-character URL-safe tracking token sent via SMS/WhatsApp. " +
        "Human-readable delivery references (such as PL-2048) are restricted to authenticated merchant dashboard search to protect recipient privacy."
      );
      setPublicTracking(null);
      setDemoDelivery(null);
      return;
    }

    // Token search via FastAPI
    setIsLoading(true);
    try {
      const tracking = await fastApiClient.getTracking(token);
      setPublicTracking(tracking);
      setIsDemoView(false);
      setDemoDelivery(null);
    } catch (err: any) {
      setPublicTracking(null);
      setDemoDelivery(null);
      setSearchError(err.message || "Tracking record not found. Please verify the 32-character tracking link.");
    } finally {
      setIsLoading(false);
    }
  };

  // Server-side Recipient Challenge Handler
  const handleVerifyRecipient = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!phoneChallenge || phoneChallenge.trim().length !== 4) {
      setChallengeError("Please enter exactly 4 numeric digits.");
      return;
    }

    setChallengeError("");
    setIsChallengeVerifying(true);

    try {
      if (publicTracking) {
        await fastApiClient.verifyRecipientChallenge(searchedRef, phoneChallenge.trim());
        setChallengeVerified(true);
      } else if (demoDelivery) {
        // Demo mode local verification simulation
        const cleanPhone = demoDelivery.recipientPhone.replace(/\D/g, "");
        if (cleanPhone.endsWith(phoneChallenge.trim())) {
          setChallengeVerified(true);
        } else {
          setChallengeError("Last 4 digits did not match recipient phone.");
        }
      }
    } catch (err: any) {
      setChallengeError(err.message || "Identity challenge failed. Digits do not match recipient on record.");
    } finally {
      setIsChallengeVerifying(false);
    }
  };

  // Proof-of-delivery OTP submission via unauthenticated public confirmation endpoint
  const handleConfirmOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!enteredOtp.trim()) return;

    setIsOtpSubmitting(true);
    try {
      if (publicTracking) {
        const res = await fastApiClient.publicConfirmDelivery(
          searchedRef,
          enteredOtp.trim(),
          phoneChallenge ? phoneChallenge.trim() : undefined
        );
        if (res.success) {
          setOtpNotice({ type: "success", text: res.message });
          setEnteredOtp("");
          // Reload tracking to reflect delivered status
          const updated = await fastApiClient.getTracking(searchedRef);
          setPublicTracking(updated);
        } else {
          setOtpNotice({ type: "error", text: res.message });
        }
      } else if (demoDelivery) {
        const res = await onVerifyOtp(demoDelivery.id, enteredOtp.trim());
        if (res.success) {
          setOtpNotice({ type: "success", text: res.message });
          setEnteredOtp("");
          setDemoDelivery({
            ...demoDelivery,
            status: "delivered",
            podVerified: true,
          });
        } else {
          setOtpNotice({ type: "error", text: res.message });
        }
      }
    } catch (err: any) {
      setOtpNotice({ type: "error", text: err.message || "PIN verification failed." });
    } finally {
      setIsOtpSubmitting(false);
    }
  };

  // Step tracker helpers
  const steps = [
    { key: "pending", label: "Order Received", desc: "Registered at merchant hub" },
    { key: "assigned", label: "Postcode Routed", desc: "Assigned to courier partner" },
    { key: "in_transit", label: "Out for Delivery", desc: "Rider dispatched on route" },
    { key: "delivered", label: "Delivered", desc: "Confirmed with recipient OTP" },
  ];

  const activeStatus = publicTracking?.status || demoDelivery?.status || "pending";
  const getStepIndex = (status: string) => {
    if (status === "delivered") return 3;
    if (status === "in_transit" || status === "out_for_delivery" || status === "picked_up") return 2;
    if (status === "assigned") return 1;
    return 0;
  };
  const currentStepIdx = getStepIndex(activeStatus);

  const displayPostcode = publicTracking?.verified_postcode || demoDelivery?.verifiedPostcode;
  const isPostcodeVerified = (publicTracking?.postcode_status || demoDelivery?.postcodeStatus) === "verified";
  const isPodVerified = publicTracking?.pod_verified || demoDelivery?.podVerified;

  return (
    <div>
      {/* Top Banner */}
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>PostcodeLink Public Recipient Tracking</h2>
            <p>
              Recipients can securely track delivery milestones, view verified NIPOST routing metadata, and verify proof of delivery with server-side identity protection.
            </p>
          </div>
        </div>

        {/* Secure Search Bar */}
        <form onSubmit={(e) => handleSearch(e)} style={{ display: "flex", gap: "10px", maxWidth: "680px", margin: "14px 0 16px" }}>
          <div className="search" style={{ height: "44px", flex: 1 }}>
            <Search size={17} />
            <input
              type="text"
              placeholder="Enter 32-character secure tracking token..."
              value={trackingInput}
              onChange={(e) => setTrackingInput(e.target.value)}
              aria-label="Tracking Token Input"
            />
          </div>
          <button type="submit" className="primary" style={{ height: "44px", padding: "0 22px" }} disabled={isLoading}>
            {isLoading ? "Searching..." : "Track Parcel"}
          </button>
        </form>

        {/* Privacy Guidance Notice */}
        <div style={{ fontSize: "11px", color: "#64748b", display: "flex", alignItems: "center", gap: "6px", marginBottom: "14px" }}>
          <Shield size={13} color="#2563eb" />
          <span>
            <strong>Recipient Privacy Protection:</strong> Human-readable delivery IDs (e.g. <code>PL-2048</code>) are restricted from public search to prevent predictable scraping. Use the unique 32-character link sent via SMS.
          </span>
        </div>

        {/* Demonstration Simulator Helper */}
        {deliveries.length > 0 && (
          <div style={{ background: "#f8fafc", border: "1px dashed #cbd5e1", borderRadius: "6px", padding: "10px 14px", marginTop: "10px" }}>
            <div style={{ fontSize: "11px", fontWeight: 700, color: "#475569", marginBottom: "6px", display: "flex", alignItems: "center", gap: "6px" }}>
              <span className="pill gray" style={{ fontSize: "10px", padding: "2px 6px" }}>DEMONSTRATION SIMULATOR</span>
              Click a sample reference to test tracking workflows:
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
              {deliveries.slice(0, 4).map((d) => (
                <button
                  key={d.id}
                  type="button"
                  className="outline"
                  style={{ height: "26px", fontSize: "11px", padding: "0 10px" }}
                  onClick={() => {
                    const token = (d as any).tracking_token || d.id;
                    setTrackingInput(token);
                    handleSearch(undefined as any, token);
                  }}
                >
                  {d.id} ({d.recipientName.split(" ")[0]} · {d.status.replace("_", " ")})
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Error Message */}
      {searchError && (
        <section className="panel" style={{ borderLeft: "4px solid #dc2626", background: "#fef2f2", padding: "16px 20px" }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: "10px" }}>
            <AlertTriangle size={18} color="#dc2626" style={{ marginTop: "2px" }} />
            <div>
              <b style={{ color: "#991b1b", fontSize: "13px" }}>Tracking Lookup Notice</b>
              <p style={{ margin: "4px 0 0", fontSize: "12px", color: "#b91c1c" }}>{searchError}</p>
            </div>
          </div>
        </section>
      )}

      {/* Demonstration Mode Warning */}
      {isDemoView && demoDelivery && (
        <div style={{ background: "#fffbeb", border: "1px solid #fde68a", padding: "10px 16px", borderRadius: "6px", marginBottom: "16px", display: "flex", alignItems: "center", gap: "8px" }}>
          <AlertTriangle size={16} color="#d97706" />
          <span style={{ fontSize: "12px", color: "#92400e" }}>
            <strong>Demonstration Simulator View:</strong> Displaying simulated local delivery <code>{demoDelivery.id}</code>. In live production, all tracking requests are verified against FastAPI server tokens.
          </span>
        </div>
      )}

      {/* Active Parcel Tracking View */}
      {(publicTracking || demoDelivery) && (
        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: "20px" }}>
          {/* Main Journey Card */}
          <section className="panel" style={{ padding: "26px" }}>
            {/* Header info */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", borderBottom: "1px solid var(--line)", paddingBottom: "18px", marginBottom: "22px" }}>
              <div>
                <span className="eyebrow">SHIPMENT MILESTONES</span>
                <div style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "4px" }}>
                  <h1 style={{ fontFamily: "Manrope, sans-serif", fontSize: "22px", margin: 0, fontWeight: 800 }}>
                    {publicTracking?.id || demoDelivery?.id}
                  </h1>
                  <span className={`pill ${activeStatus === "delivered" ? "green" : activeStatus === "in_transit" || activeStatus === "out_for_delivery" ? "blue" : "amber"}`}>
                    <i /> {activeStatus.replace("_", " ")}
                  </span>
                </div>
                <div style={{ fontSize: "12px", color: "#64748b", marginTop: "4px" }}>
                  Destination Hub: <b style={{ color: "var(--ink)" }}>{publicTracking?.destination_general_location || `${demoDelivery?.destinationArea}, ${demoDelivery?.destinationState}`}</b>
                </div>
              </div>

              {isPostcodeVerified && displayPostcode ? (
                <div className="postcode-badge verified" style={{ padding: "6px 12px", fontSize: "12px" }}>
                  <ShieldCheck size={14} /> NG-{displayPostcode} (NIPOST Verified)
                </div>
              ) : (
                <div className="postcode-badge unverified" style={{ padding: "6px 12px", fontSize: "12px" }}>
                  <AlertTriangle size={14} /> Manual Routing
                </div>
              )}
            </div>

            {/* Interactive Step Progress Tracker */}
            <div style={{ margin: "28px 0 34px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", position: "relative", marginBottom: "8px" }}>
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

            {/* Privacy-Preserved Location & Routing Details */}
            <div className="form-grid">
              <div style={{ background: "#f8fafc", padding: "14px", borderRadius: "8px", border: "1px solid var(--line)" }}>
                <span style={{ fontSize: "10px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                  RECIPIENT & DESTINATION (PROTECTED)
                </span>
                <b style={{ fontSize: "13px", display: "block", marginTop: "4px" }}>
                  {publicTracking?.recipient_name_masked || (demoDelivery ? `${demoDelivery.recipientName.split(" ")[0]} ****` : "Recipient")}
                </b>
                <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                  Phone: {publicTracking?.recipient_phone_masked || (demoDelivery ? demoDelivery.recipientPhone.replace(/(\+?\d{3,6})\d{4}(\d{2})/, "$1 **** $2") : "***")}
                </div>
                <div style={{ fontSize: "11px", color: "#166534", marginTop: "2px" }}>
                  Area: {publicTracking?.destination_general_location || `${demoDelivery?.destinationArea}, ${demoDelivery?.destinationState}`}
                </div>
              </div>

              <div style={{ background: "#f8fafc", padding: "14px", borderRadius: "8px", border: "1px solid var(--line)" }}>
                <span style={{ fontSize: "10px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                  DISPATCH LOGISTICS
                </span>
                <b style={{ fontSize: "13px", display: "block", marginTop: "4px" }}>
                  {publicTracking?.assigned_operator_name || demoDelivery?.operatorName || "Awaiting Fleet Assignment"}
                </b>
                <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                  Verification PIN: <b>Sent via SMS to recipient</b>
                </div>
                <div style={{ fontSize: "11px", color: "#0f766e", marginTop: "2px", fontWeight: 600 }}>
                  Security: 6-Digit Cryptographic OTP
                </div>
              </div>
            </div>
          </section>

          {/* Right Column: Server-Side Phone Challenge & OTP Confirmation */}
          <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
            <section
              className="panel"
              style={{
                background: "linear-gradient(180deg, #ffffff, #f0fdf4)",
                border: "1px solid #bbf7d0",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#166534", fontWeight: 700, fontSize: "13px", marginBottom: "6px" }}>
                <Key size={16} /> Proof of Delivery Confirmation
              </div>
              <p style={{ fontSize: "11px", color: "#475569", margin: "0 0 12px", lineHeight: 1.5 }}>
                A 6-digit confirmation PIN is sent via transactional SMS (DND route) to the recipient. To prevent unauthorized interception, the PIN is never displayed in public tracking views.
              </p>

              {isPodVerified ? (
                <div style={{ background: "#dcfce7", border: "1px solid #86efac", color: "#166534", padding: "14px", borderRadius: "8px", textAlign: "center", fontWeight: 700, fontSize: "13px" }}>
                  <CheckCircle2 size={18} style={{ margin: "0 auto 4px" }} />
                  Proof of Delivery Confirmed
                  <div style={{ fontSize: "11px", fontWeight: 400, marginTop: "2px", color: "#14532d" }}>
                    Delivery authenticated with cryptographic OTP.
                  </div>
                </div>
              ) : challengeVerified ? (
                /* Unlocked OTP Confirmation Form */
                <form onSubmit={handleConfirmOtp} style={{ background: "#ffffff", border: "2px solid #86efac", borderRadius: "8px", padding: "16px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", color: "#166534", fontSize: "12px", fontWeight: 700, marginBottom: "4px" }}>
                    <ShieldCheck size={15} /> Recipient Identity Confirmed
                  </div>
                  <p style={{ fontSize: "11px", color: "#64748b", margin: "0 0 12px" }}>
                    Enter the 6-digit PIN received on your phone to complete delivery confirmation:
                  </p>

                  <div style={{ display: "flex", gap: "8px" }}>
                    <input
                      type="text"
                      maxLength={6}
                      placeholder="Enter 6-digit PIN"
                      value={enteredOtp}
                      onChange={(e) => setEnteredOtp(e.target.value)}
                      style={{
                        flex: 1,
                        height: "38px",
                        border: "1px solid #cbd5e1",
                        borderRadius: "6px",
                        textAlign: "center",
                        fontSize: "16px",
                        fontWeight: 700,
                        letterSpacing: "4px",
                      }}
                      aria-label="Confirmation OTP"
                    />
                    <button type="submit" className="primary" style={{ height: "38px", padding: "0 16px" }} disabled={isOtpSubmitting}>
                      {isOtpSubmitting ? "Verifying..." : "Confirm"}
                    </button>
                  </div>

                  {otpNotice && (
                    <div style={{ marginTop: "10px", fontSize: "11px", fontWeight: 600, color: otpNotice.type === "success" ? "#16a34a" : "#dc2626" }}>
                      {otpNotice.text}
                    </div>
                  )}
                </form>
              ) : (
                /* Server-Side Phone Verification Challenge */
                <div style={{ background: "#ffffff", border: "1px solid #cbd5e1", borderRadius: "8px", padding: "16px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", fontWeight: 700, color: "#1e293b", marginBottom: "4px" }}>
                    <Lock size={14} color="#64748b" /> Recipient Verification Gate
                  </div>
                  <p style={{ fontSize: "11px", color: "#64748b", margin: "0 0 12px" }}>
                    Are you the recipient? Confirm the last 4 digits of your phone number to unlock delivery confirmation:
                  </p>

                  <form onSubmit={handleVerifyRecipient}>
                    <div style={{ display: "flex", gap: "8px" }}>
                      <input
                        type="password"
                        maxLength={4}
                        placeholder="Last 4 digits"
                        value={phoneChallenge}
                        onChange={(e) => setPhoneChallenge(e.target.value)}
                        style={{
                          width: "120px",
                          height: "36px",
                          border: "1px solid #cbd5e1",
                          borderRadius: "6px",
                          textAlign: "center",
                          fontSize: "14px",
                          letterSpacing: "3px",
                        }}
                        aria-label="Last 4 digits of recipient phone"
                      />
                      <button type="submit" className="outline" style={{ height: "36px", fontSize: "12px" }} disabled={isChallengeVerifying}>
                        {isChallengeVerifying ? "Verifying..." : "Verify Identity"}
                      </button>
                    </div>

                    {challengeError && (
                      <div style={{ fontSize: "11px", color: "#dc2626", marginTop: "8px", display: "flex", alignItems: "center", gap: "4px" }}>
                        <ShieldAlert size={13} /> {challengeError}
                      </div>
                    )}
                  </form>
                </div>
              )}
            </section>

            {/* Courier & Dispatch Contact */}
            <section className="panel">
              <div style={{ fontSize: "12px", fontWeight: 700, color: "var(--ink)", marginBottom: "8px", display: "flex", alignItems: "center", gap: "6px" }}>
                <Truck size={15} color="#2563eb" /> Courier & Dispatch Partner
              </div>
              <b style={{ fontSize: "13px", display: "block" }}>
                {publicTracking?.assigned_operator_name || demoDelivery?.operatorName || "Fleet Partner Assigned"}
              </b>
              <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                Authorized PostcodeLink Logistics Partner
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  );
}
