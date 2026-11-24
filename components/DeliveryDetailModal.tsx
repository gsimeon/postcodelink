"use client";

import React, { useState } from "react";
import { Delivery, DeliveryStatus, Operator, AppSettings } from "@/lib/types";
import { validateStateTransition } from "@/lib/state-machine";
import { verifyDeliveryOtp } from "@/lib/storage";
import {
  X,
  MapPin,
  Phone,
  Clock,
  Printer,
  Truck,
  CheckCircle2,
  AlertTriangle,
  Send,
  User,
  ShieldCheck,
  Package,
  MessageCircle,
  Key
} from "lucide-react";
import { WaybillModal } from "./WaybillModal";
import { WhatsAppModal } from "./WhatsAppModal";

interface DeliveryDetailModalProps {
  delivery: Delivery;
  operators: Operator[];
  settings: AppSettings;
  onClose: () => void;
  onUpdateStatus: (deliveryId: string, newStatus: DeliveryStatus, note: string) => void;
  onAssignOperator: (deliveryId: string, operatorId: string, operatorName: string) => void;
  onVerifyOtp?: (deliveryId: string, otp: string) => Promise<{ success: boolean; message: string }> | { success: boolean; message: string };
}

export function DeliveryDetailModal({
  delivery,
  operators,
  settings,
  onClose,
  onUpdateStatus,
  onAssignOperator,
  onVerifyOtp,
}: DeliveryDetailModalProps) {
  const [showWaybill, setShowWaybill] = useState(false);
  const [showWhatsApp, setShowWhatsApp] = useState(false);
  const [newStatus, setNewStatus] = useState<DeliveryStatus>(delivery.status);
  const [note, setNote] = useState("");
  const [selectedOperatorId, setSelectedOperatorId] = useState(delivery.operatorId || "");
  const [enteredOtp, setEnteredOtp] = useState("");
  const [otpError, setOtpError] = useState("");

  const [statusError, setStatusError] = useState("");

  const handleStatusChange = (e: React.FormEvent) => {
    e.preventDefault();
    if (newStatus === delivery.status && !note.trim()) return;

    if (newStatus !== delivery.status) {
      const check = validateStateTransition(delivery.status, newStatus);
      if (!check.valid) {
        setStatusError(check.message || "Invalid state transition.");
        return;
      }
    }
    setStatusError("");

    onUpdateStatus(
      delivery.id,
      newStatus,
      note.trim() || `Status updated to ${newStatus.replace("_", " ")}`
    );
    setNote("");
  };

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!enteredOtp.trim()) return;

    if (onVerifyOtp) {
      const res = await onVerifyOtp(delivery.id, enteredOtp.trim());
      if (!res.success) {
        setOtpError(res.message);
        return;
      }
    } else {
      const res = verifyDeliveryOtp(delivery.id, enteredOtp.trim());
      if (!res.success) {
        setOtpError(res.message);
        return;
      }
    }
    setOtpError("");
    setEnteredOtp("");
  };

  const handleOperatorChange = (opId: string) => {
    setSelectedOperatorId(opId);
    if (!opId) {
      onAssignOperator(delivery.id, "", "Not assigned");
    } else {
      const found = operators.find((o) => o.id === opId);
      if (found) {
        onAssignOperator(delivery.id, found.id, found.businessName);
      }
    }
  };

  const statusColors: Record<DeliveryStatus, string> = {
    draft: "gray",
    pending: "amber",
    pending_assignment: "amber",
    assigned: "blue",
    picked_up: "blue",
    in_transit: "blue",
    out_for_delivery: "blue",
    delivered: "green",
    failed: "red",
    cancelled: "red",
  };

  return (
    <>
      <div className="overlay" onClick={onClose}>
        <div className="modal large" onClick={(e) => e.stopPropagation()}>
          {/* Header */}
          <div className="modal-head">
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
                <b className="ref" style={{ fontSize: "18px" }}>
                  {delivery.id}
                </b>
                <span className={`pill ${statusColors[delivery.status]}`}>
                  <i /> {delivery.status.replace("_", " ")}
                </span>
                {delivery.postcodeStatus === "verified" ? (
                  <span className="postcode-badge verified">
                    <ShieldCheck size={12} /> Postcode Verified (NG-{delivery.verifiedPostcode})
                  </span>
                ) : (
                  <span className="postcode-badge unverified">
                    <AlertTriangle size={12} /> Unverified Address
                  </span>
                )}
              </div>
              <p className="sub">
                Created on {delivery.createdAt} · Last updated {delivery.updatedAt}
              </p>
            </div>

            <div style={{ display: "flex", gap: "8px" }}>
              <button
                type="button"
                className="outline"
                style={{ color: "#16a34a" }}
                onClick={() => setShowWhatsApp(true)}
              >
                <MessageCircle size={15} /> WhatsApp
              </button>
              <button
                type="button"
                className="outline"
                onClick={() => setShowWaybill(true)}
              >
                <Printer size={15} /> Waybill
              </button>
              <button type="button" className="icon-btn" onClick={onClose}>
                <X size={17} />
              </button>
            </div>
          </div>

          <div className="form-grid" style={{ marginBottom: "20px" }}>
            {/* Recipient Details Card */}
            <div
              style={{
                background: "#f8fafc",
                border: "1px solid var(--line)",
                borderRadius: "var(--radius-sm)",
                padding: "16px",
              }}
            >
              <div
                style={{
                  fontSize: "11px",
                  fontWeight: 700,
                  color: "#64748b",
                  textTransform: "uppercase",
                  letterSpacing: "0.8px",
                  marginBottom: "10px",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                <User size={14} /> Recipient Information
              </div>
              <b style={{ fontSize: "14px", color: "var(--ink)" }}>{delivery.recipientName}</b>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  fontSize: "12px",
                  color: "#475569",
                  marginTop: "6px",
                }}
              >
                <Phone size={13} color="#2563eb" />
                <a
                  href={`tel:${delivery.recipientPhone}`}
                  style={{ color: "#2563eb", textDecoration: "none" }}
                >
                  {delivery.recipientPhone}
                </a>
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: "6px",
                  fontSize: "12px",
                  color: "#475569",
                  marginTop: "8px",
                }}
              >
                <MapPin size={14} color="#64748b" style={{ flexShrink: 0, marginTop: "2px" }} />
                <div>
                  <div>{delivery.destinationAddress}</div>
                  {delivery.landmark && (
                    <div style={{ fontSize: "11px", color: "#166534", marginTop: "2px", fontWeight: 500 }}>
                      Landmark: {delivery.landmark}
                    </div>
                  )}
                  <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                    {delivery.destinationArea}, {delivery.destinationState}
                  </div>
                </div>
              </div>

              {/* Delivery OTP & Security */}
              <div style={{ marginTop: "12px", paddingTop: "10px", borderTop: "1px solid #e2e8f0" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: "11px", color: "#64748b" }}>
                    Delivery Confirmation PIN:
                  </span>
                  <span style={{ fontFamily: "monospace", fontSize: "14px", fontWeight: 800, color: "#166534", background: "#dcfce7", padding: "2px 8px", borderRadius: "4px" }}>
                    {delivery.otp || "4821"}
                  </span>
                </div>
              </div>
            </div>

            {/* Logistics & Dispatch Card */}
            <div
              style={{
                background: "#f8fafc",
                border: "1px solid var(--line)",
                borderRadius: "var(--radius-sm)",
                padding: "16px",
              }}
            >
              <div
                style={{
                  fontSize: "11px",
                  fontWeight: 700,
                  color: "#64748b",
                  textTransform: "uppercase",
                  letterSpacing: "0.8px",
                  marginBottom: "10px",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                <Truck size={14} /> Dispatch & Operator
              </div>

              <div style={{ marginBottom: "12px" }}>
                <label style={{ fontSize: "11px", color: "#64748b", display: "block", marginBottom: "4px" }}>
                  Assigned Logistics Courier:
                </label>
                <select
                  className="select-filter"
                  style={{ width: "100%" }}
                  value={selectedOperatorId}
                  onChange={(e) => handleOperatorChange(e.target.value)}
                >
                  <option value="">-- Unassigned (Needs Dispatch) --</option>
                  {operators.map((op) => (
                    <option key={op.id} value={op.id}>
                      {op.businessName} ({op.vehicleType}) {op.isAvailable ? "— Available" : "— Busy"}
                    </option>
                  ))}
                </select>
              </div>

              <div style={{ fontSize: "11px", color: "#475569" }}>
                <div>
                  Parcel: <b>{delivery.packageDescription || "General goods"}</b>
                </div>
                <div style={{ marginTop: "4px" }}>
                  Delivery Fee:{" "}
                  <b>{delivery.fee ? `₦${delivery.fee.toLocaleString()}` : "Not set"}</b>
                </div>
                {delivery.estimatedDeliveryTime && (
                  <div style={{ marginTop: "4px", color: "#2563eb" }}>
                    ETA: {delivery.estimatedDeliveryTime}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Quick OTP Verification Bar (if not yet delivered) */}
          {delivery.status !== "delivered" && (
            <form
              onSubmit={handleVerifyOtp}
              style={{
                background: "#f0fdf4",
                border: "1px solid #bbf7d0",
                borderRadius: "var(--radius-sm)",
                padding: "12px 14px",
                marginBottom: "16px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                flexWrap: "wrap",
                gap: "10px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <Key size={16} color="#166534" />
                <span style={{ fontSize: "12px", fontWeight: 700, color: "#166534" }}>
                  Confirm Delivery with Recipient PIN:
                </span>
              </div>
              <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                <input
                  type="text"
                  maxLength={4}
                  placeholder="Enter 4-digit OTP"
                  value={enteredOtp}
                  onChange={(e) => setEnteredOtp(e.target.value)}
                  style={{
                    width: "140px",
                    height: "34px",
                    border: "1px solid #86efac",
                    borderRadius: "6px",
                    textAlign: "center",
                    fontWeight: 700,
                    letterSpacing: "3px",
                  }}
                />
                <button type="submit" className="primary" style={{ height: "34px", background: "#16a34a", borderColor: "#16a34a" }}>
                  Verify & Mark Delivered
                </button>
              </div>
              {otpError && (
                <div style={{ width: "100%", fontSize: "11px", color: "#dc2626", fontWeight: 600 }}>
                  {otpError}
                </div>
              )}
            </form>
          )}

          {/* Status Update Action Bar */}
          <form
            onSubmit={handleStatusChange}
            style={{
              background: "#eff6ff",
              border: "1px solid #bfdbfe",
              borderRadius: "var(--radius-sm)",
              padding: "14px",
              marginBottom: "20px",
            }}
          >
            <div style={{ fontSize: "12px", fontWeight: 700, color: "#1e40af", marginBottom: "8px" }}>
              Quick Status Transition & Rider Dispatch Log
            </div>
            {statusError && (
              <div style={{ fontSize: "11px", color: "#b91c1c", background: "#fee2e2", border: "1px solid #fecaca", padding: "6px 10px", borderRadius: "4px", marginBottom: "8px", fontWeight: 600 }}>
                {statusError}
              </div>
            )}
            <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
              <select
                className="select-filter"
                style={{ height: "36px", background: "#fff" }}
                value={newStatus}
                onChange={(e) => setNewStatus(e.target.value as DeliveryStatus)}
              >
                <option value="pending_assignment">Pending Assignment</option>
                <option value="assigned">Assigned</option>
                <option value="in_transit">In Transit (Out for Delivery)</option>
                <option value="delivered">Delivered (Completed)</option>
                <option value="failed">Delivery Failed / Rescheduled</option>
                <option value="cancelled">Cancelled</option>
              </select>

              <input
                type="text"
                placeholder="Add event note (e.g. 'Rider arrived at gate, call placed')"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                style={{
                  flex: 1,
                  minWidth: "200px",
                  height: "36px",
                  border: "1px solid #cbd5e1",
                  borderRadius: "6px",
                  padding: "0 10px",
                  fontSize: "12px",
                }}
              />

              <button type="submit" className="primary" style={{ height: "36px" }}>
                <Send size={14} /> Update Status
              </button>
            </div>
          </form>

          {/* Event History Timeline */}
          <div>
            <div
              style={{
                fontSize: "12px",
                fontWeight: 700,
                color: "var(--ink)",
                display: "flex",
                alignItems: "center",
                gap: "6px",
                marginBottom: "8px",
              }}
            >
              <Clock size={15} color="#2563eb" /> Delivery Audit Trail & Event Timeline
            </div>

            <div className="timeline">
              {delivery.events.map((ev, index) => {
                return (
                  <div key={ev.id || index} className="timeline-item">
                    <div className={`timeline-dot ${ev.status === "delivered" ? "done" : ""}`} />
                    <div className="timeline-content">
                      <div className="timeline-header">
                        <span className="timeline-actor">
                          {ev.actor}{" "}
                          <span style={{ fontSize: "10px", color: "#64748b", fontWeight: 400 }}>
                            ({ev.actorRole})
                          </span>
                        </span>
                        <span className="timeline-time">{ev.timestamp}</span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px", margin: "4px 0" }}>
                        <span className={`pill ${statusColors[ev.status]}`} style={{ fontSize: "10px", padding: "2px 8px" }}>
                          {ev.status.replace("_", " ")}
                        </span>
                      </div>
                      {ev.note && <div className="timeline-note">{ev.note}</div>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="modal-actions">
            <button type="button" className="outline" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      </div>

      {showWaybill && (
        <WaybillModal
          delivery={delivery}
          settings={settings}
          onClose={() => setShowWaybill(false)}
        />
      )}

      {showWhatsApp && (
        <WhatsAppModal
          delivery={delivery}
          settings={settings}
          onClose={() => setShowWhatsApp(false)}
        />
      )}
    </>
  );
}
