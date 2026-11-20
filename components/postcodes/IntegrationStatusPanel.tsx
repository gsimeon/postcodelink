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
    status: string;
    display_status: string;
  };
}

export const IntegrationStatusPanel: React.FC<IntegrationStatusPanelProps> = ({
  upstreamIntegration,
}) => {
  return (
    <div style={{ background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px", marginTop: "16px" }}>
      <h3 style={{ fontSize: "14px", fontWeight: 700, color: "#0f172a", marginBottom: "12px" }}>
        Upstream NIPOST Integration Readiness
      </h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "10px", fontSize: "12px" }}>
        <div>
          <span style={{ color: "#64748b" }}>Adapter Module: </span>
          <strong style={{ color: upstreamIntegration.adapter_installed ? "#16a34a" : "#dc2626" }}>
            {upstreamIntegration.adapter_installed ? "Installed (NIPOSTClient)" : "Missing"}
          </strong>
        </div>
        <div>
          <span style={{ color: "#64748b" }}>Gateway Config: </span>
          <strong style={{ color: upstreamIntegration.configuration_complete ? "#16a34a" : "#d97706" }}>
            {upstreamIntegration.configuration_complete ? "Complete" : "Incomplete (Missing Key/URL)"}
          </strong>
        </div>
        <div>
          <span style={{ color: "#64748b" }}>Auth Scheme: </span>
          <strong>{upstreamIntegration.auth_scheme.toUpperCase()}</strong>
        </div>
        <div>
          <span style={{ color: "#64748b" }}>Liveness Probe: </span>
          <strong style={{ color: upstreamIntegration.connectivity_healthy ? "#16a34a" : "#64748b" }}>
            {upstreamIntegration.connectivity_healthy ? "Online & Responsive" : "Pending Probe"}
          </strong>
        </div>
        <div>
          <span style={{ color: "#64748b" }}>Official Status: </span>
          <strong>{upstreamIntegration.display_status}</strong>
        </div>
      </div>
    </div>
  );
};
