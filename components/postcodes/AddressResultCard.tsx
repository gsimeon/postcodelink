import React from "react";
import { CleanseResult } from "@/lib/fastapi-client";
import { Copy, Check, MapPin } from "lucide-react";
import { VerificationStatusBadge } from "./VerificationStatusBadge";
import { ProvenancePanel } from "./ProvenancePanel";

interface AddressResultCardProps {
  result: CleanseResult;
  copiedStandardized: boolean;
  copiedJson: boolean;
  onCopyStandardized: () => void;
  onCopyJson: () => void;
  onApplyPostcode?: (postcode: string, details?: any) => void;
  onStartDeliveryWithAddress?: (address: string, postcode: string) => void;
}

export const AddressResultCard: React.FC<AddressResultCardProps> = ({
  result,
  copiedStandardized,
  copiedJson,
  onCopyStandardized,
  onCopyJson,
  onApplyPostcode,
  onStartDeliveryWithAddress,
}) => {
  return (
    <div style={{ background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px", marginTop: "16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "8px", marginBottom: "12px" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
            <span style={{ fontSize: "18px", fontWeight: 800, color: "#0f172a" }}>
              {result.postcode || "No Postcode Assigned"}
            </span>
            <VerificationStatusBadge
              status={result.verification_status}
              isLiveNipost={result.is_live_nipost}
              isPartial={result.is_partial_verification}
            />
          </div>
          <div style={{ fontSize: "12px", color: "#64748b" }}>
            Parsing Completeness: <strong>{Math.round(result.confidence * 100)}%</strong> · Dispatch Routing Score: <strong>{Math.round((result.dispatch_confidence || 0) * 100)}%</strong>
          </div>
          <div style={{ fontSize: "10px", color: "#94a3b8", marginTop: "2px", fontStyle: "italic" }}>
            Heuristic syntax & territory completeness metric. Does not guarantee physical building existence or delivery carrier SLA.
          </div>
        </div>

        <div style={{ display: "flex", gap: "8px" }}>
          <button
            type="button"
            onClick={onCopyStandardized}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "4px",
              padding: "6px 10px",
              borderRadius: "4px",
              border: "1px solid #cbd5e1",
              background: "#ffffff",
              fontSize: "11px",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {copiedStandardized ? <Check size={12} color="#16a34a" /> : <Copy size={12} />}
            {copiedStandardized ? "Copied" : "Copy Address"}
          </button>
          {onApplyPostcode && result.postcode && (
            <button
              type="button"
              onClick={() => onApplyPostcode(result.postcode, result)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
                padding: "6px 12px",
                borderRadius: "4px",
                border: "none",
                background: "#0284c7",
                color: "#ffffff",
                fontSize: "11px",
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              <MapPin size={12} /> Apply to Order
            </button>
          )}
          {onStartDeliveryWithAddress && result.postcode && (
            <button
              type="button"
              onClick={() => onStartDeliveryWithAddress(result.formatted_address, result.postcode)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
                padding: "6px 12px",
                borderRadius: "4px",
                border: "none",
                background: "#059669",
                color: "#ffffff",
                fontSize: "11px",
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              <MapPin size={12} /> Dispatch to Address
            </button>
          )}
        </div>
      </div>

      <div style={{ background: "#f8fafc", padding: "12px", borderRadius: "6px", marginBottom: "12px" }}>
        <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase", marginBottom: "2px" }}>
          Standardized Address
        </div>
        <div style={{ fontSize: "14px", fontWeight: 600, color: "#1e293b" }}>
          {result.formatted_address}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "10px", fontSize: "12px", marginBottom: "12px" }}>
        <div>
          <span style={{ color: "#64748b" }}>Area: </span>
          <strong>{result.area || "—"}</strong>
        </div>
        <div>
          <span style={{ color: "#64748b" }}>LGA: </span>
          <strong>{result.lga || "—"}</strong>
        </div>
        <div>
          <span style={{ color: "#64748b" }}>State: </span>
          <strong>{result.state || "—"}</strong>
        </div>
        <div>
          <span style={{ color: "#64748b" }}>Resolution: </span>
          <strong>{result.resolution_level || "area_district"}</strong>
        </div>
      </div>

      {result.changes_made && result.changes_made.length > 0 && (
        <div style={{ fontSize: "11px", color: "#475569", marginBottom: "12px" }}>
          <strong style={{ color: "#334155" }}>Corrections Applied:</strong>
          <ul style={{ margin: "4px 0 0", paddingLeft: "18px" }}>
            {result.changes_made.map((ch, idx) => (
              <li key={idx}>{ch}</li>
            ))}
          </ul>
        </div>
      )}

      <ProvenancePanel
        provenance={result.provenance}
        source={result.source}
        datasetVersion={result.dataset_version}
        evidenceId={result.evidence_id}
        verificationMethod={result.verification_method}
      />
    </div>
  );
};
