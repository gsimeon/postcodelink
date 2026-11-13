"use client";

import React, { useState } from "react";
import { Delivery, Operator } from "@/lib/types";
import { cleanseAndStandardizeAddress } from "@/lib/nigeria-postcodes";
import { generateDeliveryReference, generateSecureOtp } from "@/lib/reference-generator";
import {
  X,
  Upload,
  FileSpreadsheet,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  ShieldCheck,
  Sparkles
} from "lucide-react";

interface BulkImportModalProps {
  operators: Operator[];
  onClose: () => void;
  onImport: (deliveries: Delivery[]) => void;
}

const SAMPLE_CSV = `Funke Akindele, +234 803 111 2233, 18 Admiralty Way near Ebeano Supermarket Lekki Phase 1 Lagos, Luxury Skincare Set, 4500
Emeka Okafor, +234 812 444 5566, Plot 102 Aminu Kano Crescent beside Zenith Bank Wuse 2 Abuja, Mechanical Keyboard, 6000
Bolanle Austen, +234 809 777 8899, 12 Isaac John Street Ikeja GRA Lagos, Bespoke Native Wear, 3500
Suleiman Bello, +234 805 222 3344, 45 Bodija Market Road near UI Ibadan Oyo, Engineering Books, 3200`;

export function BulkImportModal({
  operators,
  onClose,
  onImport,
}: BulkImportModalProps) {
  const [csvText, setCsvText] = useState(SAMPLE_CSV);
  const [defaultOperatorId, setDefaultOperatorId] = useState("");

  // Parse lines
  const parsedRows = React.useMemo(() => {
    const lines = csvText
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.length > 5);

    return lines.map((line, idx) => {
      const parts = line.split(",").map((p) => p.trim());
      const recipientName = parts[0] || `Customer ${idx + 1}`;
      const recipientPhone = parts[1] || "+234 800 000 0000";
      const rawAddress = parts[2] || "Lagos, Nigeria";
      const packageDescription = parts[3] || "General Merchandise";
      const fee = Number(parts[4]) || 3500;

      const analysis = cleanseAndStandardizeAddress(rawAddress);

      return {
        recipientName,
        recipientPhone,
        rawAddress,
        packageDescription,
        fee,
        analysis,
      };
    });
  }, [csvText]);

  const handleImportSubmit = () => {
    if (parsedRows.length === 0) return;

    const assignedOperator = operators.find((op) => op.id === defaultOperatorId);

    const newDeliveries: Delivery[] = parsedRows.map((row, idx) => {
      const deliveryId = generateDeliveryReference();
      const deliveryOtp = generateSecureOtp();
      const isVerified = Boolean(row.analysis.matchedPostcode && row.analysis.confidence === "high");

      return {
        id: deliveryId,
        recipientName: row.recipientName,
        recipientPhone: row.recipientPhone,
        destinationAddress: row.rawAddress,
        landmark: undefined,
        destinationArea: row.analysis.detectedArea || "General Metro",
        destinationCity: row.analysis.detectedState === "Abuja (FCT)" ? "Abuja" : "Lagos",
        destinationState: row.analysis.detectedState || "Lagos",
        postcodeInput: row.analysis.matchedPostcode || "",
        postcodeStatus: isVerified ? "verified" : "unverified",
        verifiedPostcode: isVerified ? row.analysis.matchedPostcode : undefined,
        packageDescription: row.packageDescription,
        fee: row.fee,
        operatorId: assignedOperator ? assignedOperator.id : undefined,
        operatorName: assignedOperator ? assignedOperator.businessName : "Not assigned",
        status: assignedOperator ? "assigned" : "pending_assignment",
        createdAt: "Just now",
        updatedAt: "Just now",
        otp: deliveryOtp,
        podVerified: false,
        coordinates: row.analysis.coordinates,
        estimatedDeliveryTime: "Same-day express dispatch",
        events: [
          {
            id: `ev-${Date.now()}-${idx}`,
            deliveryId,
            status: "draft",
            actor: "Bulk Importer Engine",
            actorRole: "merchant",
            note: isVerified
              ? `Imported from CSV with verified NIPOST code NG-${row.analysis.matchedPostcode}`
              : "Imported from CSV with manual landmark address",
            timestamp: "Just now",
          },
        ],
      };
    });

    onImport(newDeliveries);
  };

  const verifiedCount = parsedRows.filter((r) => r.analysis.matchedPostcode).length;

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal large" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "860px" }}>
        <div className="modal-head">
          <div>
            <p className="eyebrow">BATCH OPERATIONS</p>
            <h2>Bulk CSV & Batch Delivery Dispatch</h2>
            <p className="sub">
              Paste order data from Shopify, Instagram, or WhatsApp. The NIPOST engine auto-resolves digital postcodes for every line.
            </p>
          </div>
          <button type="button" className="icon-btn" onClick={onClose}>
            <X size={17} />
          </button>
        </div>

        {/* Text Area Input */}
        <div style={{ marginBottom: "16px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
            <label style={{ fontSize: "11px", fontWeight: 700, color: "#475569" }}>
              CSV Rows Format: <code style={{ color: "#2563eb" }}>Recipient, Phone, Address & Landmark, Package, Fee (NGN)</code>
            </label>
            <button
              type="button"
              className="outline"
              style={{ height: "26px", fontSize: "10px", padding: "0 8px" }}
              onClick={() => setCsvText(SAMPLE_CSV)}
            >
              Reset to Sample Batch
            </button>
          </div>

          <textarea
            style={{
              width: "100%",
              height: "100px",
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "11px",
              padding: "10px",
              border: "1px solid var(--line)",
              borderRadius: "6px",
              outline: "none",
            }}
            value={csvText}
            onChange={(e) => setCsvText(e.target.value)}
          />
        </div>

        {/* Batch Parsing Analysis Ribbon */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "#eff6ff",
            border: "1px solid #bfdbfe",
            padding: "10px 14px",
            borderRadius: "6px",
            fontSize: "12px",
            color: "#1e40af",
            marginBottom: "16px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <Sparkles size={16} color="#2563eb" />
            <span>
              Parsed <b>{parsedRows.length} orders</b> · Auto-verified{" "}
              <b>{verifiedCount} NIPOST codes</b> ({Math.round((verifiedCount / (parsedRows.length || 1)) * 100)}%)
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "11px", color: "#64748b" }}>Assign to Courier:</span>
            <select
              className="select-filter"
              style={{ height: "30px", fontSize: "11px" }}
              value={defaultOperatorId}
              onChange={(e) => setDefaultOperatorId(e.target.value)}
            >
              <option value="">-- Leave Unassigned --</option>
              {operators.map((op) => (
                <option key={op.id} value={op.id}>
                  {op.businessName}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Live Preview Table */}
        <div className="table-wrap" style={{ maxHeight: "240px", overflowY: "auto", marginBottom: "20px" }}>
          <table>
            <thead>
              <tr>
                <th>RECIPIENT</th>
                <th>RAW DESTINATION</th>
                <th>RESOLVED POSTCODE</th>
                <th>PACKAGE / FEE</th>
              </tr>
            </thead>
            <tbody>
              {parsedRows.map((r, i) => (
                <tr key={i}>
                  <td>
                    <b>{r.recipientName}</b>
                    <small>{r.recipientPhone}</small>
                  </td>
                  <td>
                    <div style={{ maxWidth: "260px", whiteSpace: "normal" }}>
                      {r.rawAddress}
                    </div>
                  </td>
                  <td>
                    {r.analysis.matchedPostcode ? (
                      <span className="postcode-badge verified">
                        <ShieldCheck size={11} /> NG-{r.analysis.matchedPostcode} ({r.analysis.detectedArea})
                      </span>
                    ) : (
                      <span className="postcode-badge unverified">
                        <AlertTriangle size={11} /> Manual Landmark
                      </span>
                    )}
                  </td>
                  <td>
                    <b>{r.packageDescription}</b>
                    <small style={{ color: "#0f766e" }}>₦{r.fee.toLocaleString()}</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="modal-actions">
          <button type="button" className="outline" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="primary" onClick={handleImportSubmit}>
            <Upload size={14} /> Import & Dispatch All {parsedRows.length} Orders
          </button>
        </div>
      </div>
    </div>
  );
}
