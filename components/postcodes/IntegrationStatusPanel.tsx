import React, { useState } from "react";
import { RefreshCw } from "lucide-react";
import { fastApiClient } from "@/lib/fastapi-client";

interface IntegrationStatusPanelProps {
  upstreamIntegration: {
    adapter_installed: boolean;
    configuration_complete: boolean;
    base_url_set: boolean;
    credentials_set: boolean;
    auth_scheme: string;
    upstream_environment?: string;
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
  const [liveOverride, setLiveOverride] = useState<Partial<IntegrationStatusPanelProps["upstreamIntegration"]> | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);

  const effective = liveOverride ? { ...upstreamIntegration, ...liveOverride } : upstreamIntegration;
  const isAuthenticated = typeof window !== "undefined" && fastApiClient.isAuthenticated();

  const handleCheckHealth = async () => {
    setIsChecking(true);
    setProbeError(null);
    try {
      const res = await fastApiClient.triggerNipostHealthCheck();
      setLiveOverride(res);
    } catch (err: any) {
      setProbeError(err.message || "Admin privileges required to probe NIPOST connection.");
    } finally {
      setIsChecking(false);
    }
  };

  return (
    <div style={{ background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px", marginTop: "16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px", flexWrap: "wrap", gap: "8px" }}>
        <h3 style={{ fontSize: "14px", fontWeight: 700, color: "#0f172a", margin: 0 }}>
          Upstream NIPOST / FMCIDE Integration Readiness
        </h3>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {isAuthenticated && (
            <button
              type="button"
              onClick={handleCheckHealth}
              disabled={isChecking}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "5px",
                padding: "4px 10px",
                borderRadius: "4px",
                border: "1px solid #cbd5e1",
                background: "#ffffff",
                fontSize: "11px",
                fontWeight: 600,
                cursor: isChecking ? "not-allowed" : "pointer",
                color: "#334155",
              }}
            >
              <RefreshCw size={11} className={isChecking ? "spin" : ""} />
              {isChecking ? "Checking..." : "Check NIPOST Connection"}
            </button>
          )}
          <span
            style={{
              fontSize: "11px",
              fontWeight: 700,
              padding: "2px 8px",
              borderRadius: "4px",
              background: effective.production_authorized ? "#dcfce7" : "#f1f5f9",
              color: effective.production_authorized ? "#166534" : "#475569",
            }}
          >
            {effective.display_status}
          </span>
        </div>
      </div>

      {probeError && (
        <div style={{ fontSize: "11px", color: "#b91c1c", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: "6px", padding: "6px 10px", marginBottom: "10px" }}>
          {probeError}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: "10px", fontSize: "12px" }}>
        {/* 1. Adapter */}
        <div style={{ background: "#f8fafc", padding: "8px 12px", borderRadius: "6px", border: "1px solid #f1f5f9" }}>
          <span style={{ color: "#64748b", display: "block", fontSize: "10px", textTransform: "uppercase", fontWeight: 700 }}>1. Adapter Module</span>
          <strong style={{ color: effective.adapter_installed ? "#16a34a" : "#dc2626" }}>
            {effective.adapter_installed ? "Installed (NIPOSTClient)" : "Missing"}
          </strong>
        </div>

        {/* 2. Configuration & Upstream Environment */}
        <div style={{ background: "#f8fafc", padding: "8px 12px", borderRadius: "6px", border: "1px solid #f1f5f9" }}>
          <span style={{ color: "#64748b", display: "block", fontSize: "10px", textTransform: "uppercase", fontWeight: 700 }}>2. Gateway Config & Env</span>
          <strong style={{ color: effective.configuration_complete ? "#16a34a" : "#d97706" }}>
            {effective.configuration_complete
              ? `Complete (${effective.auth_scheme.toUpperCase()} · ${effective.upstream_environment || "unclassified"})`
              : "Incomplete (Missing Key/URL)"}
          </strong>
        </div>

        {/* 3. Connectivity */}
        <div style={{ background: "#f8fafc", padding: "8px 12px", borderRadius: "6px", border: "1px solid #f1f5f9" }}>
          <span style={{ color: "#64748b", display: "block", fontSize: "10px", textTransform: "uppercase", fontWeight: 700 }}>3. Connectivity & Liveness</span>
          <strong style={{ color: effective.connectivity_healthy ? "#16a34a" : "#64748b" }}>
            {effective.connectivity_healthy ? "Reachable" : "Not Checked / Unreachable"}
          </strong>
          {effective.last_checked_at && (
            <span style={{ display: "block", fontSize: "10px", color: "#94a3b8", marginTop: "2px" }}>
              Checked: {new Date(effective.last_checked_at).toLocaleTimeString()}
            </span>
          )}
        </div>

        {/* 4. Authentication */}
        <div style={{ background: "#f8fafc", padding: "8px 12px", borderRadius: "6px", border: "1px solid #f1f5f9" }}>
          <span style={{ color: "#64748b", display: "block", fontSize: "10px", textTransform: "uppercase", fontWeight: 700 }}>4. Authentication</span>
          <strong style={{ color: effective.authentication_verified ? "#16a34a" : "#64748b" }}>
            {effective.authentication_verified ? "Credentials Accepted" : "Unverified / Standby"}
          </strong>
        </div>

        {/* 5. Contract Integrity */}
        <div style={{ background: "#f8fafc", padding: "8px 12px", borderRadius: "6px", border: "1px solid #f1f5f9" }}>
          <span style={{ color: "#64748b", display: "block", fontSize: "10px", textTransform: "uppercase", fontWeight: 700 }}>5. Contract & Schema</span>
          <strong style={{ color: effective.contract_verified ? "#16a34a" : "#64748b" }}>
            {effective.contract_verified ? "Response Contract Verified" : "Contract Standby"}
          </strong>
        </div>

        {/* 6. Commercial Authorization (strictly separate from credential environment) */}
        <div style={{ background: "#f8fafc", padding: "8px 12px", borderRadius: "6px", border: "1px solid #f1f5f9" }}>
          <span style={{ color: "#64748b", display: "block", fontSize: "10px", textTransform: "uppercase", fontWeight: 700 }}>6. Commercial Authorization</span>
          <strong style={{ color: effective.production_authorized ? "#16a34a" : "#d97706" }}>
            {effective.production_authorized ? "Commercial Access Approved" : "Written Approval Pending"}
          </strong>
        </div>
      </div>
    </div>
  );
};
