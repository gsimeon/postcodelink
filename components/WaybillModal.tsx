"use client";

import React from "react";
import { Delivery, AppSettings } from "@/lib/types";
import { X, Printer, MapPin, CheckCircle, Package } from "lucide-react";

interface WaybillModalProps {
  delivery: Delivery;
  settings: AppSettings;
  onClose: () => void;
}

export function WaybillModal({ delivery, settings, onClose }: WaybillModalProps) {
  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div
        className="modal large"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: "680px" }}
      >
        <div className="modal-head">
          <div>
            <p className="eyebrow">CONSIGNMENT & DISPATCH NOTE</p>
            <h2>Official Delivery Waybill</h2>
            <p className="sub">Standardized dispatch slip with verified Nigerian digital postcode.</p>
          </div>
          <div style={{ display: "flex", gap: "8px" }}>
            <button type="button" className="primary" onClick={handlePrint}>
              <Printer size={15} /> Print Slip
            </button>
            <button type="button" className="icon-btn" onClick={onClose}>
              <X size={17} />
            </button>
          </div>
        </div>

        {/* Printable Waybill Sheet */}
        <div className="waybill-preview" id="waybill-print-sheet">
          <div className="waybill-head">
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <div className="brand-mark" style={{ width: "32px", height: "32px" }}>
                  <MapPin size={18} />
                </div>
                <div>
                  <b style={{ fontSize: "16px", letterSpacing: "-0.3px" }}>PostcodeLink</b>
                  <span style={{ fontSize: "9px", color: "var(--blue)", fontWeight: 800, marginLeft: "4px" }}>
                    NIGERIA
                  </span>
                </div>
              </div>
              <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}>
                National Digital Postcode Dispatch Gateway
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: "11px", color: "#64748b" }}>WAYBILL REFERENCE</div>
              <div className="waybill-barcode">{delivery.id}</div>
              <div style={{ fontSize: "10px", color: "#94a3b8" }}>Date: {delivery.createdAt}</div>
            </div>
          </div>

          {/* Sender & Receiver Boxes */}
          <div className="waybill-grid">
            <div className="waybill-box">
              <label>FROM (SENDER / MERCHANT)</label>
              <b style={{ fontSize: "13px" }}>{settings.merchantName}</b>
              <div style={{ fontSize: "11px", color: "#475569", marginTop: "4px" }}>
                {settings.merchantAddress}
              </div>
              <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                {settings.merchantLga}, {settings.merchantState}
              </div>
              <div style={{ fontSize: "11px", color: "#1e293b", marginTop: "4px", fontWeight: 600 }}>
                Tel: {settings.merchantPhone}
              </div>
            </div>

            <div className="waybill-box" style={{ background: "#f0fdf4", borderColor: "#bbf7d0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <label style={{ color: "#166534" }}>TO (RECIPIENT / DESTINATION)</label>
                {delivery.postcodeStatus === "verified" && (
                  <span className="postcode-badge verified" style={{ fontSize: "10px" }}>
                    <CheckCircle size={10} /> Verified NIPOST
                  </span>
                )}
              </div>
              <b style={{ fontSize: "13px", color: "#14532d" }}>{delivery.recipientName}</b>
              <div style={{ fontSize: "11px", color: "#166534", marginTop: "4px", fontWeight: 500 }}>
                {delivery.destinationAddress}
              </div>
              {delivery.landmark && (
                <div style={{ fontSize: "10px", color: "#15803d", marginTop: "3px", fontStyle: "italic" }}>
                  Landmark: {delivery.landmark}
                </div>
              )}
              <div style={{ fontSize: "11px", color: "#166534", marginTop: "2px" }}>
                {delivery.destinationArea}, {delivery.destinationState}
              </div>
              <div style={{ fontSize: "11px", color: "#14532d", marginTop: "4px", fontWeight: 600 }}>
                Tel: {delivery.recipientPhone}
              </div>
            </div>
          </div>

          {/* Postcode Routing Strip */}
          <div
            style={{
              background: "#1e293b",
              color: "#ffffff",
              padding: "12px 16px",
              borderRadius: "6px",
              margin: "16px 0",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div>
              <div style={{ fontSize: "9px", color: "#94a3b8", letterSpacing: "1px", fontWeight: 700 }}>
                OFFICIAL NIGERIAN POSTCODE ROUTING CODE
              </div>
              <div
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: "20px",
                  fontWeight: 800,
                  color: "#38bdf8",
                  letterSpacing: "2px",
                }}
              >
                {delivery.verifiedPostcode ? `NG-${delivery.verifiedPostcode}` : delivery.postcodeInput || "UNVERIFIED"}
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: "10px", color: "#94a3b8" }}>PRIMARY DISPATCH CLUSTER</div>
              <div style={{ fontSize: "12px", fontWeight: 700 }}>
                {delivery.destinationArea} ({delivery.destinationState})
              </div>
            </div>
          </div>

          {/* Package Details & Operator */}
          <div className="waybill-grid" style={{ borderBottom: "none" }}>
            <div className="waybill-box">
              <label>PACKAGE DESCRIPTION</label>
              <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", fontWeight: 600 }}>
                <Package size={14} color="#2563eb" /> {delivery.packageDescription || "Standard Parcel"}
              </div>
              <div style={{ fontSize: "11px", color: "#64748b", marginTop: "6px" }}>
                Declared Delivery Fee:{" "}
                <b style={{ color: "#0f172a" }}>
                  {delivery.fee ? `₦${delivery.fee.toLocaleString()}` : "Prepaid"}
                </b>
              </div>
            </div>

            <div className="waybill-box">
              <label>ASSIGNED LOGISTICS OPERATOR</label>
              <b style={{ fontSize: "12px" }}>{delivery.operatorName || "Unassigned"}</b>
              <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}>
                Status: <span style={{ textTransform: "capitalize", fontWeight: 600 }}>{delivery.status.replace("_", " ")}</span>
              </div>
              <div style={{ fontSize: "10px", color: "#94a3b8", marginTop: "4px" }}>
                Track via PostcodeLink dispatch network
              </div>
            </div>
          </div>

          {/* Signature Strip */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: "24px",
              marginTop: "24px",
              paddingTop: "16px",
              borderTop: "1px dashed #cbd5e1",
            }}
          >
            <div>
              <div style={{ borderBottom: "1px solid #94a3b8", height: "30px" }} />
              <div style={{ fontSize: "10px", color: "#64748b", marginTop: "4px", textAlign: "center" }}>
                Courier / Dispatch Rider Signature & Date
              </div>
            </div>
            <div>
              <div style={{ borderBottom: "1px solid #94a3b8", height: "30px" }} />
              <div style={{ fontSize: "10px", color: "#64748b", marginTop: "4px", textAlign: "center" }}>
                Recipient Signature & OTP Confirmation
              </div>
            </div>
          </div>
        </div>

        <div className="modal-actions">
          <button type="button" className="outline" onClick={onClose}>
            Close
          </button>
          <button type="button" className="primary" onClick={handlePrint}>
            <Printer size={15} /> Print Dispatch Slip
          </button>
        </div>
      </div>
    </div>
  );
}

