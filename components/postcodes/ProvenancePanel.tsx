import React from "react";
import { ShieldCheck, Info, Database } from "lucide-react";

interface ProvenancePanelProps {
  provenance?: string;
  source?: string;
  datasetVersion?: string;
  evidenceId?: string | number | null;
  verificationMethod?: string;
}

export const ProvenancePanel: React.FC<ProvenancePanelProps> = ({
  provenance,
  source,
  datasetVersion,
  evidenceId,
  verificationMethod,
}) => {
  return (
    <div
      style={{
        background: "#f8fafc",
        border: "1px solid #e2e8f0",
        borderRadius: "8px",
        padding: "12px 16px",
        fontSize: "12px",
        color: "#334155",
        marginTop: "12px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 700, color: "#1e293b", marginBottom: "6px" }}>
        <ShieldCheck size={14} color="#0284c7" />
        Data Provenance & Audit Trail
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "8px" }}>
        <div>
          <span style={{ color: "#64748b" }}>Data Source: </span>
          <strong>{source || "PostcodeLink Intelligence"}</strong>
        </div>
        {datasetVersion && (
          <div>
            <span style={{ color: "#64748b" }}>Dataset Release: </span>
            <strong>{datasetVersion}</strong>
          </div>
        )}
        {verificationMethod && (
          <div>
            <span style={{ color: "#64748b" }}>Pipeline Method: </span>
            <code>{verificationMethod}</code>
          </div>
        )}
        {evidenceId ? (
          <div>
            <span style={{ color: "#64748b" }}>Evidence Audit ID: </span>
            <code>#{evidenceId}</code>
          </div>
        ) : null}
      </div>
      {provenance && (
        <div style={{ marginTop: "6px", color: "#475569", fontStyle: "italic" }}>
          {provenance}
        </div>
      )}
    </div>
  );
};
