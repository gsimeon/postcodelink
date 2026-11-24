import React from "react";
import { VerificationMode, CleanseResult } from "@/lib/fastapi-client";
import { Sparkles, Shield, AlertTriangle, CheckCircle2 } from "lucide-react";
import { AddressResultCard } from "./AddressResultCard";

interface AddressCleanserProps {
  rawAddressInput: string;
  setRawAddressInput: (val: string) => void;
  stateHint: string;
  setStateHint: (val: string) => void;
  areaHint: string;
  setAreaHint: (val: string) => void;
  postcodeHint: string;
  setPostcodeHint: (val: string) => void;
  verificationMode: VerificationMode;
  setVerificationMode: (mode: VerificationMode) => void;
  isCleansing: boolean;
  cleanseResult: CleanseResult | null;
  cleanseError: string | null;
  copiedStandardized: boolean;
  copiedJson: boolean;
  onCleanse: (modeOverride?: VerificationMode) => void;
  onCopyStandardized: () => void;
  onCopyJson: () => void;
  onApplyPostcode?: (postcode: string, details?: any) => void;
  onStartDeliveryWithAddress?: (address: string, postcode: string) => void;
}

export const AddressCleanser: React.FC<AddressCleanserProps> = ({
  rawAddressInput,
  setRawAddressInput,
  stateHint,
  setStateHint,
  areaHint,
  setAreaHint,
  postcodeHint,
  setPostcodeHint,
  verificationMode,
  setVerificationMode,
  isCleansing,
  cleanseResult,
  cleanseError,
  copiedStandardized,
  copiedJson,
  onCleanse,
  onCopyStandardized,
  onCopyJson,
  onApplyPostcode,
  onStartDeliveryWithAddress,
}) => {
  return (
    <div style={{ padding: "16px" }}>
      <div style={{ marginBottom: "16px" }}>
        <h2 style={{ fontSize: "18px", fontWeight: 700, margin: 0, color: "#0f172a" }}>
          Address Standardisation & NIPOST Verification
        </h2>
        <p style={{ margin: "4px 0 0", fontSize: "12px", color: "#64748b" }}>
          Cleanse, normalise, and verify Nigerian delivery addresses against official national postcode infrastructure.
        </p>
      </div>

      {/* Verification Mode Selector */}
      <div style={{ marginBottom: "16px" }}>
        <label style={{ display: "block", fontSize: "12px", fontWeight: 700, color: "#334155", marginBottom: "6px" }}>
          VERIFICATION MODE
        </label>
        <div
          role="radiogroup"
          aria-label="Verification mode selection"
          style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "10px" }}
        >
          <button
            type="button"
            role="radio"
            aria-checked={verificationMode === "nipost_validate"}
            onClick={() => setVerificationMode("nipost_validate")}
            style={{
              padding: "12px",
              borderRadius: "6px",
              border: `2px solid ${verificationMode === "nipost_validate" ? "#0284c7" : "#e2e8f0"}`,
              background: verificationMode === "nipost_validate" ? "#f0f9ff" : "#ffffff",
              cursor: "pointer",
              textAlign: "left",
              fontFamily: "inherit",
              width: "100%",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 700, fontSize: "13px", color: "#0f172a" }}>
              <CheckCircle2 size={15} color="#0284c7" />
              NIPOST Live Verify
            </div>
            <p style={{ margin: "4px 0 0", fontSize: "11px", color: "#64748b" }}>
              Verifies against live NIPOST API; gracefully falls back to local reference if gateway is unreachable.
            </p>
          </button>

          <button
            type="button"
            role="radio"
            aria-checked={verificationMode === "nipost_strict"}
            onClick={() => setVerificationMode("nipost_strict")}
            style={{
              padding: "12px",
              borderRadius: "6px",
              border: `2px solid ${verificationMode === "nipost_strict" ? "#dc2626" : "#e2e8f0"}`,
              background: verificationMode === "nipost_strict" ? "#fef2f2" : "#ffffff",
              cursor: "pointer",
              textAlign: "left",
              fontFamily: "inherit",
              width: "100%",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 700, fontSize: "13px", color: "#0f172a" }}>
              <Shield size={15} color="#dc2626" />
              Strict Fail-Closed
            </div>
            <p style={{ margin: "4px 0 0", fontSize: "11px", color: "#64748b" }}>
              Requires live NIPOST verification; strictly fails closed if gateway is unconfigured or unavailable.
            </p>
          </button>

          <button
            type="button"
            role="radio"
            aria-checked={verificationMode === "local_standardization"}
            onClick={() => setVerificationMode("local_standardization")}
            style={{
              padding: "12px",
              borderRadius: "6px",
              border: `2px solid ${verificationMode === "local_standardization" ? "#d97706" : "#e2e8f0"}`,
              background: verificationMode === "local_standardization" ? "#fffbeb" : "#ffffff",
              cursor: "pointer",
              textAlign: "left",
              fontFamily: "inherit",
              width: "100%",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 700, fontSize: "13px", color: "#0f172a" }}>
              <AlertTriangle size={15} color="#d97706" />
              Local Standardisation Only
            </div>
            <p style={{ margin: "4px 0 0", fontSize: "11px", color: "#64748b" }}>
              Uses local reference rules without contacting upstream NIPOST endpoints.
            </p>
          </button>
        </div>
      </div>

      {/* Address Input Form */}
      <div style={{ marginBottom: "16px" }}>
        <label style={{ display: "block", fontSize: "12px", fontWeight: 700, color: "#334155", marginBottom: "6px" }}>
          RAW ADDRESS TEXT
        </label>
        <textarea
          rows={3}
          value={rawAddressInput}
          onChange={(e) => setRawAddressInput(e.target.value)}
          placeholder="Enter Nigerian delivery address (e.g. Plot 14 Admiralty Way, Lekki Phase 1, Lagos)"
          style={{
            width: "100%",
            padding: "10px 12px",
            borderRadius: "6px",
            border: "1px solid #cbd5e1",
            fontSize: "13px",
            boxSizing: "border-box",
            resize: "vertical",
          }}
        />
      </div>

      {/* Optional Hints */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "10px", marginBottom: "16px" }}>
        <div>
          <label style={{ display: "block", fontSize: "11px", fontWeight: 600, color: "#64748b", marginBottom: "4px" }}>
            State Hint (Optional)
          </label>
          <input
            type="text"
            value={stateHint}
            onChange={(e) => setStateHint(e.target.value)}
            placeholder="e.g. Lagos"
            style={{ width: "100%", padding: "8px 10px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "12px", boxSizing: "border-box" }}
          />
        </div>
        <div>
          <label style={{ display: "block", fontSize: "11px", fontWeight: 600, color: "#64748b", marginBottom: "4px" }}>
            Area Hint (Optional)
          </label>
          <input
            type="text"
            value={areaHint}
            onChange={(e) => setAreaHint(e.target.value)}
            placeholder="e.g. Lekki Phase 1"
            style={{ width: "100%", padding: "8px 10px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "12px", boxSizing: "border-box" }}
          />
        </div>
        <div>
          <label style={{ display: "block", fontSize: "11px", fontWeight: 600, color: "#64748b", marginBottom: "4px" }}>
            Postcode Hint (Optional)
          </label>
          <input
            type="text"
            value={postcodeHint}
            onChange={(e) => setPostcodeHint(e.target.value)}
            placeholder="e.g. 105102"
            style={{ width: "100%", padding: "8px 10px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "12px", boxSizing: "border-box" }}
          />
        </div>
      </div>

      <button
        type="button"
        onClick={() => onCleanse()}
        disabled={isCleansing || !rawAddressInput.trim()}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "6px",
          padding: "10px 18px",
          borderRadius: "6px",
          border: "none",
          background: "#0284c7",
          color: "#ffffff",
          fontSize: "13px",
          fontWeight: 700,
          cursor: isCleansing || !rawAddressInput.trim() ? "not-allowed" : "pointer",
          opacity: isCleansing || !rawAddressInput.trim() ? 0.6 : 1,
        }}
      >
        <Sparkles size={15} />
        {isCleansing ? "Cleansing & Verifying..." : "Cleanse & Standardise Address"}
      </button>

      {cleanseError && (
        <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: "8px", padding: "12px 16px", color: "#dc2626", fontSize: "13px", marginTop: "16px" }}>
          <strong>Error:</strong> {cleanseError}
        </div>
      )}

      {cleanseResult && (
        <AddressResultCard
          result={cleanseResult}
          copiedStandardized={copiedStandardized}
          copiedJson={copiedJson}
          onCopyStandardized={onCopyStandardized}
          onCopyJson={onCopyJson}
          onApplyPostcode={onApplyPostcode}
          onStartDeliveryWithAddress={onStartDeliveryWithAddress}
        />
      )}
    </div>
  );
};
