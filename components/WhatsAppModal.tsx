"use client";

import React, { useState } from "react";
import { Delivery, AppSettings } from "@/lib/types";
import {
  X,
  MessageCircle,
  Copy,
  Check,
  ExternalLink,
  Send,
  User,
  Truck
} from "lucide-react";

interface WhatsAppModalProps {
  delivery: Delivery;
  settings: AppSettings;
  onClose: () => void;
}

export function WhatsAppModal({ delivery, settings, onClose }: WhatsAppModalProps) {
  const [recipientMode, setRecipientMode] = useState<"customer" | "rider">("customer");
  const [copied, setCopied] = useState(false);

  // Clean phone number for WhatsApp wa.me link (e.g. +234 803 123 4567 -> 2348031234567)
  const formatWaPhone = (raw: string) => {
    return raw.replace(/\D/g, "");
  };

  const customerMessage = `Hello ${delivery.recipientName}, your order *${delivery.id}* from *${settings.merchantName}* is on its way!\n\n📍 Destination: ${delivery.destinationAddress}\n🏛️ NIPOST Postcode: ${delivery.verifiedPostcode ? `NG-${delivery.verifiedPostcode}` : 'Manual landmark'}\n🔑 Your 4-Digit Delivery PIN: *${delivery.otp || '4821'}*\n\nPlease give this PIN to the courier rider upon delivery.`;

  const riderMessage = `*NEW DISPATCH WAYBILL: ${delivery.id}*\n\n👤 Recipient: ${delivery.recipientName} (${delivery.recipientPhone})\n📍 Destination: ${delivery.destinationAddress}\n${delivery.landmark ? `🏛️ Landmark: ${delivery.landmark}\n` : ''}📮 Sector: ${delivery.destinationArea}, ${delivery.destinationState} [${delivery.verifiedPostcode || 'Unverified'}]\n📦 Package: ${delivery.packageDescription || 'Parcel'}\n💰 Fee: ₦${delivery.fee?.toLocaleString() || 'Prepaid'}\n\nMerchant: ${settings.merchantName} (${settings.merchantPhone})`;

  const activeMessage = recipientMode === "customer" ? customerMessage : riderMessage;
  const targetPhone = recipientMode === "customer" ? delivery.recipientPhone : "+234 803 451 9021";
  const waUrl = `https://wa.me/${formatWaPhone(targetPhone)}?text=${encodeURIComponent(activeMessage)}`;

  const handleCopy = () => {
    navigator.clipboard.writeText(activeMessage);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "520px" }}>
        <div className="modal-head">
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div style={{ width: "28px", height: "28px", borderRadius: "50%", background: "#25D366", color: "#fff", display: "grid", placeItems: "center" }}>
                <MessageCircle size={16} />
              </div>
              <h2 style={{ margin: 0, fontSize: "18px" }}>WhatsApp Dispatch & Tracking</h2>
            </div>
            <p className="sub">
              Send standardized delivery details and recipient OTP directly to WhatsApp.
            </p>
          </div>
          <button type="button" className="icon-btn" onClick={onClose}>
            <X size={17} />
          </button>
        </div>

        {/* Mode Selector */}
        <div style={{ display: "flex", gap: "8px", margin: "16px 0 14px" }}>
          <button
            type="button"
            className={`tab-btn ${recipientMode === "customer" ? "active" : ""}`}
            style={{ flex: 1, justifyContent: "center" }}
            onClick={() => setRecipientMode("customer")}
          >
            <User size={14} /> Send to Recipient
          </button>
          <button
            type="button"
            className={`tab-btn ${recipientMode === "rider" ? "active" : ""}`}
            style={{ flex: 1, justifyContent: "center" }}
            onClick={() => setRecipientMode("rider")}
          >
            <Truck size={14} /> Send to Courier Rider
          </button>
        </div>

        {/* Message Preview */}
        <div
          style={{
            background: "#f0fdf4",
            border: "1px solid #bbf7d0",
            borderRadius: "8px",
            padding: "14px",
            fontFamily: "'DM Sans', sans-serif",
            fontSize: "12px",
            whiteSpace: "pre-line",
            color: "#14532d",
            lineHeight: 1.6,
            marginBottom: "18px",
          }}
        >
          {activeMessage}
        </div>

        <div className="modal-actions" style={{ justifyContent: "space-between" }}>
          <button type="button" className="outline" onClick={handleCopy}>
            {copied ? <Check size={14} color="#16a34a" /> : <Copy size={14} />} {copied ? "Copied" : "Copy Message"}
          </button>

          <div style={{ display: "flex", gap: "8px" }}>
            <button type="button" className="outline" onClick={onClose}>
              Cancel
            </button>
            <a
              href={waUrl}
              target="_blank"
              rel="noreferrer"
              className="primary"
              style={{
                background: "#25D366",
                borderColor: "#25D366",
                textDecoration: "none",
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
              }}
            >
              <ExternalLink size={14} /> Open in WhatsApp
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
