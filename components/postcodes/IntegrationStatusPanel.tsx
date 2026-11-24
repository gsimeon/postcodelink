import React from "react";
import { CheckCircle2, AlertTriangle, ShieldAlert } from "lucide-react";

interface IntegrationStatusPanelProps {
  upstreamIntegration: {
    adapter_installed: boolean;
    configuration_complete: boolean;
    base_url_set: boolean;
    credentials_set: boolean;
    auth_scheme: string;
    connectivity_healthy?: boolean;
    authentication_verified?: boolean;
    contract_verified?: boolean;
    production_authorized?: boolean;
    last_checked_at?: string | null;
    status: string;
    display_status: string;
  };
}

export const IntegrationStatusPanel: React.FC<IntegrationStatusPanelProps> = ({
  upstreamIntegration,
}) => {
  return (
    <div style={{ background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px", marginTop: "16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
        <h3 style={{ fontSize: "14px", fontWeight: 700, color: "#0f172a", margin: 0 }}>
          Upstream NIPOST / FMCIDE Integration Readiness
        </h3>
        <span
          style={{
            fontSize: "11px",
            fontWeight: 700,
            padding: "2px 8px",
            borderRadius: "4px",
            background: upstreamIntegration.production_authorized ? "#dcfce7" : "#f1f5f9",
            color: upstreamIntegration.production_authorized ? "#166534" : "#475569",
          }}
        >
          {upstreamIntegration.display_status}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: "10px", fontSize: "12px" }}>
        {/* 1. Adapter */}
        <div style={{ background: "#f8fafc", padding: "8px 12px", borderRadius: "6px", border: "1px solid #f1f5f9" }}>
          <span style={{ color: "#64748b", display: "block", fontSize: "10px", textTransform: "uppercase", fontWeight: 700 }}>1. Adapter Module</span>
          <strong style={{ color: upstreamIntegration.adapter_installed ? "#16a34a" : "#dc2626" }}>
            {upstreamIntegration.adapter_installed ? "Installed (NIPOSTClient)" : "Missing"}
          </strong>
        </div>

        {/* 2. Configuration */}
        <div style={{ background: "#f8fafc", padding: "8px 12px", borderRadius: "6px", border: "1px solid #f1f5f9" }}>
          <span style={{ color: "#64748b", display: "block", fontSize: "10px", textTransform: "uppercase", fontWeight: 700 }}>2. Gateway Config</span>
          <strong style={{ color: upstreamIntegration.configuration_complete ? "#16a34a" : "#d97706" }}>
            {upstreamIntegration.configuration_complete ? `Complete (${upstreamIntegration.auth_scheme.toUpperCase()})` : "Incomplete (Missing Key/URL)"}
          </strong>
        </div>

        {/* 3. Connectivity */}
        <div style={{ background: "#f8fafc", padding: "8px 12px", borderRadius: "6px", border: "1px solid #f1f5f9" }}>
          <span style={{ color: "#64748b", display: "block", fontSize: "10px", textTransform: "uppercase", fontWeight: 700 }}>3. Connectivity & Liveness</span>
          <strong style={{ color: upstreamIntegration.connectivity_healthy ? "#16a34a" : "#64748b" }}>
            {upstreamIntegration.connectivity_healthy ? "Online & Responsive" : "Pending Active Probe"}
          </strong>
          {upstreamIntegration.last_checked_at && (
            <span style={{ display: "block", fontSize: "10px", color: "#94a3b8", marginTop: "2px" }}>
              Checked: {new Date(upstreamIntegration.last_checked_at).toLocaleTimeString()}
            </span>
          )}
        </div>

        {/* 4. Authentication */}
        <div style={{ background: "#f8fafc", padding: "8px 12px", borderRadius: "6px", border: "1px solid #f1f5f9" }}>
          <span style={{ color: "#64748b", display: "block", fontSize: "10px", textTransform: "uppercase", fontWeight: 700 }}>4. Authentication</span>
          <strong style={{ color: upstreamIntegration.authentication_verified ? "#16a34a" : "#64748b" }}>
            {upstreamIntegration.authentication_verified ? "Cryptographically Verified" : "Unverified / Standby"}
          </strong>
        </div>

        {/* 5. Contract Integrity */}
        <div style={{ background: "#f8fafc", padding: "8px 12px", borderRadius: "6px", border: "1px solid #f1f5f9" }}>
          <span style={{ color: "#64748b", display: "block", fontSize: "10px", textTransform: "uppercase", fontWeight: 700 }}>5. Contract & Schema</span>
          <strong style={{ color: upstreamIntegration.contract_verified ? "#16a34a" : "#64748b" }}>
            {upstreamIntegration.contract_verified ? "Validated (Pydantic / OpenAPI)" : "Contract Validation Standby"}
          </strong>
        </div>

        {/* 6. Production Authorization */}
        <div style={{ background: "#f8fafc", padding: "8px 12px", borderRadius: "6px", border: "1px solid #f1f5f9" }}>
          <span style={{ color: "#64748b", display: "block", fontSize: "10px", textTransform: "uppercase", fontWeight: 700 }}>6. Production Authorization</span>
          <strong style={{ color: upstreamIntegration.production_authorized ? "#16a34a" : "#d97706" }}>
            {upstreamIntegration.production_authorized ? "Officially Authorized" : "Sandbox / Pre-production"}
          </strong>
        </div>
      </div>
    </div>
  );
};
