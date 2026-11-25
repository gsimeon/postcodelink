import React from "react";
import { CoverageReport } from "@/lib/fastapi-client";
import { RefreshCw, Database } from "lucide-react";
import { IntegrationStatusPanel } from "./IntegrationStatusPanel";

interface CoverageDashboardProps {
  coverageReport: CoverageReport | null;
  isLoadingCoverage: boolean;
  coverageError: string | null;
  onRefresh: () => void;
}

export const CoverageDashboard: React.FC<CoverageDashboardProps> = ({
  coverageReport,
  isLoadingCoverage,
  coverageError,
  onRefresh,
}) => {
  return (
    <div style={{ padding: "16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px", flexWrap: "wrap", gap: "12px" }}>
        <div>
          <h2 style={{ fontSize: "18px", fontWeight: 700, margin: 0, color: "#0f172a" }}>
            Postcode Coverage & Data Quality
          </h2>
          <p style={{ margin: "4px 0 0", fontSize: "12px", color: "#64748b" }}>
            Explore the currently available postcode dataset, its geographic coverage, data sources, verification levels and freshness. Coverage figures reflect the records currently available, not national completeness.
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoadingCoverage}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "6px",
            padding: "8px 14px",
            borderRadius: "6px",
            border: "1px solid #cbd5e1",
            background: "#ffffff",
            fontSize: "12px",
            fontWeight: 600,
            cursor: isLoadingCoverage ? "not-allowed" : "pointer",
            color: "#334155",
          }}
        >
          <RefreshCw size={13} className={isLoadingCoverage ? "spin" : ""} />
          Refresh Coverage
        </button>
      </div>

      {coverageError && (
        <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: "8px", padding: "12px 16px", color: "#dc2626", fontSize: "13px", marginBottom: "16px" }}>
          <strong>Coverage Query Error:</strong> {coverageError}
        </div>
      )}

      {isLoadingCoverage && !coverageReport && (
        <div style={{ padding: "40px", textAlign: "center", color: "#64748b", fontSize: "14px" }}>
          Querying FastAPI Dataset Coverage Report...
        </div>
      )}

      {coverageReport && (
        <>
          {/* Active Data Source Indicator */}
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
              background: "#f0fdf4",
              border: "1px solid #bbf7d0",
              padding: "6px 14px",
              borderRadius: "6px",
              fontSize: "12px",
              color: "#166534",
              marginBottom: "16px",
              fontWeight: 600,
            }}
          >
            <Database size={14} />
            <span>Active Data Source:</span>
            <span style={{ textTransform: "capitalize" }}>
              {(coverageReport.dataset_source || coverageReport.source || "database_directory") === "database_directory"
                ? "Database Directory (PostgreSQL / SQLite)"
                : "Demonstration Reference Dataset (In-Memory Fallback)"}
            </span>
          </div>

          {/* Top Key Metrics */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: "14px",
              marginBottom: "14px",
            }}
          >
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px" }}>
              <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                STATES COVERED
              </div>
              <div style={{ fontSize: "24px", fontWeight: 800, color: "#0f172a", marginTop: "4px" }}>
                {coverageReport.scope_states_count}
              </div>
              <small style={{ fontSize: "11px", color: "#64748b" }}>States in loaded dataset</small>
            </div>

            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px" }}>
              <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                TOTAL REFERENCE POSTCODES
              </div>
              <div style={{ fontSize: "24px", fontWeight: 800, color: "#0f172a", marginTop: "4px" }}>
                {coverageReport.total_reference_records.toLocaleString()}
              </div>
              <small style={{ fontSize: "11px", color: "#64748b" }}>Edition {coverageReport.version}</small>
            </div>

            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px" }}>
              <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                GEO-REFERENCED (GPS)
              </div>
              <div style={{ fontSize: "24px", fontWeight: 800, color: "#0f766e", marginTop: "4px" }}>
                {coverageReport.records_with_coordinates.toLocaleString()}
              </div>
              <small style={{ fontSize: "11px", color: "#64748b" }}>
                {Math.round((coverageReport.records_with_coordinates / Math.max(1, coverageReport.total_reference_records)) * 100)}% with coordinates
              </small>
            </div>

            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px" }}>
              <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                FORMAT-VALID DIGITAL REFERENCES
              </div>
              <div style={{ fontSize: "24px", fontWeight: 800, color: "#4338ca", marginTop: "4px" }}>
                {(coverageReport.format_valid_digital_references ?? coverageReport.national_digital_postcode_records ?? 0).toLocaleString()}
              </div>
              <small style={{ fontSize: "11px", color: "#64748b" }}>Syntax-valid local/pilot digital codes (not NIPOST-verified)</small>
            </div>

            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px" }}>
              <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                NIPOST-CONFIRMED POSTCODES
              </div>
              <div style={{ fontSize: "24px", fontWeight: 800, color: "#15803d", marginTop: "4px" }}>
                {(coverageReport.nipost_confirmed_postcodes ?? coverageReport.records_with_valid_evidence ?? 0).toLocaleString()}
              </div>
              <small style={{ fontSize: "11px", color: "#64748b" }}>Active authoritative existence evidence</small>
            </div>

            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px" }}>
              <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                NIPOST-CONFIRMED METADATA
              </div>
              <div style={{ fontSize: "24px", fontWeight: 800, color: "#0284c7", marginTop: "4px" }}>
                {(coverageReport.nipost_confirmed_address_metadata ?? 0).toLocaleString()}
              </div>
              <small style={{ fontSize: "11px", color: "#64748b" }}>Records with upstream address autofill evidence</small>
            </div>
          </div>

          {/* Upstream Integration Readiness */}
          <IntegrationStatusPanel upstreamIntegration={coverageReport.upstream_integration} />
        </>
      )}
    </div>
  );
};
