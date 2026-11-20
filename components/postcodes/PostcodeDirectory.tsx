import React from "react";
import { PostcodeRecord } from "@/lib/fastapi-client";
import { Search, MapPin, Copy, Check, Shield } from "lucide-react";
import { VerificationStatusBadge } from "./VerificationStatusBadge";

interface PostcodeDirectoryProps {
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  selectedState: string;
  setSelectedState: (state: string) => void;
  strictLookup: boolean;
  setStrictLookup: (strict: boolean) => void;
  directoryItems: PostcodeRecord[];
  isLoadingDirectory: boolean;
  directoryError: string | null;
  directorySourceInfo: string;
  copiedCode: string | null;
  onCopyCode: (code: string) => void;
  onApplyPostcode?: (postcode: string, details?: any) => void;
  statesList: string[];
}

export const PostcodeDirectory: React.FC<PostcodeDirectoryProps> = ({
  searchQuery,
  setSearchQuery,
  selectedState,
  setSelectedState,
  strictLookup,
  setStrictLookup,
  directoryItems,
  isLoadingDirectory,
  directoryError,
  directorySourceInfo,
  copiedCode,
  onCopyCode,
  onApplyPostcode,
  statesList,
}) => {
  return (
    <div style={{ padding: "16px" }}>
      <div style={{ marginBottom: "16px" }}>
        <h2 style={{ fontSize: "18px", fontWeight: 700, margin: 0, color: "#0f172a" }}>
          Postcode Registry & Directory Explorer
        </h2>
        <p style={{ margin: "4px 0 0", fontSize: "12px", color: "#64748b" }}>
          Search authoritative 6-digit legacy and national digital postcodes across all 36 states and FCT.
        </p>
      </div>

      {/* Search & Filters */}
      <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", marginBottom: "12px" }}>
        <div style={{ flex: "1 1 240px", position: "relative" }}>
          <Search size={15} color="#94a3b8" style={{ position: "absolute", left: "10px", top: "10px" }} />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by code (e.g. 100001, LA-01-A04-IK-02) or area (e.g. Ikeja, Lekki)..."
            style={{
              width: "100%",
              padding: "8px 10px 8px 32px",
              borderRadius: "6px",
              border: "1px solid #cbd5e1",
              fontSize: "13px",
              boxSizing: "border-box",
            }}
          />
        </div>

        <select
          value={selectedState}
          onChange={(e) => setSelectedState(e.target.value)}
          style={{
            padding: "8px 12px",
            borderRadius: "6px",
            border: "1px solid #cbd5e1",
            fontSize: "13px",
            background: "#ffffff",
          }}
        >
          {statesList.map((st) => (
            <option key={st} value={st}>
              {st}
            </option>
          ))}
        </select>

        <label
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "6px",
            fontSize: "12px",
            fontWeight: 600,
            color: "#334155",
            cursor: "pointer",
            background: strictLookup ? "#fef2f2" : "#f8fafc",
            border: `1px solid ${strictLookup ? "#fca5a5" : "#cbd5e1"}`,
            padding: "6px 10px",
            borderRadius: "6px",
          }}
        >
          <input
            type="checkbox"
            checked={strictLookup}
            onChange={(e) => setStrictLookup(e.target.checked)}
          />
          <Shield size={13} color={strictLookup ? "#dc2626" : "#64748b"} />
          Strict Fail-Closed
        </label>
      </div>

      {directorySourceInfo && (
        <div style={{ fontSize: "11px", color: "#64748b", marginBottom: "12px" }}>
          {directorySourceInfo}
        </div>
      )}

      {directoryError && (
        <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: "8px", padding: "12px 16px", color: "#dc2626", fontSize: "13px", marginBottom: "16px" }}>
          <strong>Error:</strong> {directoryError}
        </div>
      )}

      {/* Directory Table */}
      <div style={{ overflowX: "auto", border: "1px solid #e2e8f0", borderRadius: "8px" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px", textAlign: "left" }}>
          <thead>
            <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0", color: "#475569", fontSize: "11px", fontWeight: 700, textTransform: "uppercase" }}>
              <th style={{ padding: "10px 14px" }}>Code</th>
              <th style={{ padding: "10px 14px" }}>Area / District</th>
              <th style={{ padding: "10px 14px" }}>LGA</th>
              <th style={{ padding: "10px 14px" }}>State</th>
              <th style={{ padding: "10px 14px" }}>Verification Status</th>
              <th style={{ padding: "10px 14px", textAlign: "right" }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoadingDirectory && directoryItems.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ padding: "30px", textAlign: "center", color: "#64748b" }}>
                  Searching Postcode Registry...
                </td>
              </tr>
            ) : directoryItems.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ padding: "30px", textAlign: "center", color: "#64748b" }}>
                  No postcodes match your search criteria.
                </td>
              </tr>
            ) : (
              directoryItems.map((item, idx) => (
                <tr key={`${item.code}-${idx}`} style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "10px 14px", fontWeight: 700, color: "#0f172a" }}>
                    {item.code}
                  </td>
                  <td style={{ padding: "10px 14px", color: "#1e293b" }}>
                    {item.area || "—"}
                  </td>
                  <td style={{ padding: "10px 14px", color: "#475569" }}>
                    {item.lga || "—"}
                  </td>
                  <td style={{ padding: "10px 14px", color: "#475569" }}>
                    {item.state || "—"}
                  </td>
                  <td style={{ padding: "10px 14px" }}>
                    <VerificationStatusBadge status={item.verification_status} isLiveNipost={item.verification_status === "official_verified"} />
                  </td>
                  <td style={{ padding: "10px 14px", textAlign: "right" }}>
                    <div style={{ display: "inline-flex", gap: "6px" }}>
                      <button
                        type="button"
                        onClick={() => onCopyCode(item.code)}
                        style={{
                          padding: "4px 8px",
                          borderRadius: "4px",
                          border: "1px solid #cbd5e1",
                          background: "#ffffff",
                          fontSize: "11px",
                          fontWeight: 600,
                          cursor: "pointer",
                        }}
                      >
                        {copiedCode === item.code ? <Check size={11} color="#16a34a" /> : <Copy size={11} />}
                      </button>
                      {onApplyPostcode && (
                        <button
                          type="button"
                          onClick={() => onApplyPostcode(item.code, item)}
                          style={{
                            padding: "4px 8px",
                            borderRadius: "4px",
                            border: "none",
                            background: "#0284c7",
                            color: "#ffffff",
                            fontSize: "11px",
                            fontWeight: 600,
                            cursor: "pointer",
                          }}
                        >
                          <MapPin size={11} /> Apply
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
