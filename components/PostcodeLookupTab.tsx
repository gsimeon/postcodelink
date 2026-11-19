"use client";

import React, { useState, useEffect, useMemo, useCallback } from "react";
import {
  fastApiClient,
  CleanseResult,
  PostcodeDirectoryEntry,
  PostcodeLookupResult,
  CoverageReport,
} from "@/lib/fastapi-client";
import {
  STATES_LIST,
} from "@/lib/nigeria-postcodes";
import {
  Search,
  MapPin,
  Sparkles,
  Copy,
  Check,
  Plus,
  Compass,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  FileText,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  ShieldCheck,
  ShieldAlert,
  Globe,
  Database,
  Sliders,
  Code,
  Building,
  CheckCheck,
  ExternalLink,
} from "lucide-react";

interface PostcodeLookupTabProps {
  onStartDeliveryWithAddress: (address: string, postcode: string) => void;
}

export type VerificationTier =
  | "nipost_verified"
  | "partially_verified"
  | "local_match"
  | "format_valid"
  | "address_conflict"
  | "unavailable";

export type VerificationMode =
  | "local_standardization"
  | "nipost_validate"
  | "nipost_strict";

interface VerificationBadgeConfig {
  tier: VerificationTier;
  label: string;
  pillClass: string;
  color: string;
  bg: string;
  border: string;
  description: string;
}

export function getVerificationBadgeConfig(
  status?: string,
  isLive?: boolean,
  isPartial?: boolean
): VerificationBadgeConfig {
  if (isPartial || status === "partially_verified") {
    return {
      tier: "partially_verified",
      label: "PARTIALLY VERIFIED",
      pillClass: "pill blue",
      color: "#2563eb",
      bg: "#eff6ff",
      border: "#bfdbfe",
      description: "Postcode existence validated by NIPOST; address attributes enriched from local dataset",
    };
  }
  if (
    status === "official_verified" ||
    status === "nipost_verified" ||
    (status === "verified" && isLive)
  ) {
    return {
      tier: "nipost_verified",
      label: "NIPOST VERIFIED",
      pillClass: "pill green",
      color: "#16a34a",
      bg: "#eafaf1",
      border: "#bbf7d0",
      description: "Authoritative NIPOST National Postal Directory verification (Live Gateway)",
    };
  }
  if (
    status === "local_match" ||
    status === "local_reference" ||
    status === "verified"
  ) {
    return {
      tier: "local_match",
      label: "LOCAL REFERENCE MATCH",
      pillClass: "pill amber",
      color: "#d97706",
      bg: "#fffbeb",
      border: "#fde68a",
      description: "PostcodeLink local reference dataset match (non-governmental fallback)",
    };
  }
  if (status === "format_valid" || status === "estimated") {
    return {
      tier: "format_valid",
      label: "FORMAT VALID",
      pillClass: "pill cyan",
      color: "#0284c7",
      bg: "#f0f9ff",
      border: "#bae6fd",
      description: "Valid Nigerian postal syntax (pending authoritative upstream check)",
    };
  }
  if (status === "conflict" || status === "address_conflict") {
    return {
      tier: "address_conflict",
      label: "ADDRESS CONFLICT",
      pillClass: "pill red",
      color: "#dc2626",
      bg: "#fef2f2",
      border: "#fecaca",
      description: "Postcode conflicts with destination area or state administrative boundary",
    };
  }
  return {
    tier: "unavailable",
    label: "UNAVAILABLE / UNVERIFIED",
    pillClass: "pill gray",
    color: "#64748b",
    bg: "#f1f5f9",
    border: "#e2e8f0",
    description: "Postcode not found or upstream NIPOST verification gateway unreachable",
  };
}

export function PostcodeLookupTab({ onStartDeliveryWithAddress }: PostcodeLookupTabProps) {
  const [activeSubTab, setActiveSubTab] = useState<"directory" | "cleanser" | "coverage">("directory");

  // Coverage Report States
  const [coverageReport, setCoverageReport] = useState<CoverageReport | null>(null);
  const [isLoadingCoverage, setIsLoadingCoverage] = useState<boolean>(false);
  const [coverageError, setCoverageError] = useState<string | null>(null);

  const fetchCoverageReport = useCallback(async () => {
    setIsLoadingCoverage(true);
    setCoverageError(null);
    try {
      const data = await fastApiClient.getCoverageReport();
      setCoverageReport(data);
    } catch (err: any) {
      setCoverageError(err.message || "Failed to load coverage report from FastAPI registry.");
    } finally {
      setIsLoadingCoverage(false);
    }
  }, []);

  // Directory / Explorer States
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedState, setSelectedState] = useState<string>("All");
  const [strictLookup, setStrictLookup] = useState<boolean>(false);
  const [directoryItems, setDirectoryItems] = useState<PostcodeDirectoryEntry[]>([]);
  const [isLoadingDirectory, setIsLoadingDirectory] = useState<boolean>(false);
  const [directorySourceInfo, setDirectorySourceInfo] = useState<string>("");
  const [directoryError, setDirectoryError] = useState<string | null>(null);
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  // Address Cleanser States
  const [rawAddressInput, setRawAddressInput] = useState(
    "Plot 14 Admiralty Way, opposite Ebeano Supermarket, Lekki Phase 1, Lagos"
  );
  const [stateHint, setStateHint] = useState<string>("");
  const [areaHint, setAreaHint] = useState<string>("");
  const [postcodeHint, setPostcodeHint] = useState<string>("");
  const [verificationMode, setVerificationMode] = useState<VerificationMode>("nipost_validate");

  // WAI-ARIA Radio Group Keyboard Navigation
  const handleRadioKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const modes: VerificationMode[] = [
      "local_standardization",
      "nipost_validate",
      "nipost_strict",
    ];
    const currentIndex = modes.indexOf(verificationMode);
    if (currentIndex === -1) return;

    let nextIndex = currentIndex;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      nextIndex = (currentIndex + 1) % modes.length;
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      nextIndex = (currentIndex - 1 + modes.length) % modes.length;
    }

    if (nextIndex !== currentIndex) {
      const nextMode = modes[nextIndex];
      setVerificationMode(nextMode);
      const buttons = e.currentTarget.querySelectorAll<HTMLButtonElement>('button[role="radio"]');
      buttons[nextIndex]?.focus();
    }
  };

  const [isCleansing, setIsCleansing] = useState<boolean>(false);
  const [cleanseResult, setCleanseResult] = useState<CleanseResult | null>(null);
  const [cleanseError, setCleanseError] = useState<string | null>(null);
  const [showJsonInspector, setShowJsonInspector] = useState<boolean>(false);
  const [copiedStandardized, setCopiedStandardized] = useState<boolean>(false);
  const [copiedJson, setCopiedJson] = useState<boolean>(false);

  // 1. Initial Directory Fetch & Debounced Search against FastAPI
  const fetchDirectory = useCallback(
    async (query: string, state: string, strict: boolean) => {
      setIsLoadingDirectory(true);
      setDirectoryError(null);

      const trimmed = query.trim();
      const isCode =
        /^\d{6}$/.test(trimmed) ||
        /^[A-Z]{2}-\d{2}-[A-Z0-9]{3}-[A-Z0-9]{2}-\d{2}$/i.test(trimmed);

      try {
        const res: PostcodeLookupResult = await fastApiClient.lookupPostcodes({
          code: isCode ? trimmed : undefined,
          area: !isCode && trimmed ? trimmed : undefined,
          state: state !== "All" ? state : undefined,
          strict: strict,
        });

        setDirectoryItems(res.matches || []);
        setDirectorySourceInfo(
          res.is_live_nipost
            ? (res.dataset_version ? `NIPOST Live Gateway (${res.dataset_version}) · ${res.matches.length} matches` : `NIPOST Live Gateway · ${res.matches.length} matches`)
            : `${res.provenance} · ${res.matches.length} matches`
        );
      } catch (err: any) {
        setDirectoryError(
          err.message ||
            "Unable to reach FastAPI Postcode Registry. Postcode exploration is managed exclusively by FastAPI to prevent split-brain datasets."
        );
        setDirectoryItems([]);
        setDirectorySourceInfo(strict ? "Strict Mode: Fail-Closed Enforced" : "Registry Service Unavailable");
      } finally {
        setIsLoadingDirectory(false);
      }
    },
    []
  );

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchDirectory(searchQuery, selectedState, strictLookup);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, selectedState, strictLookup, fetchDirectory]);

  // 2. Address Cleansing via FastAPI /api/v1/postcodes/cleanse
  const handleCleanseAddress = useCallback(
    async (modeOverride?: VerificationMode) => {
      if (!rawAddressInput.trim()) return;

      setIsCleansing(true);
      setCleanseError(null);

      const activeMode = modeOverride || verificationMode;
      const isLive = activeMode !== "local_standardization";
      const isStrict = activeMode === "nipost_strict";

      try {
        const result: CleanseResult = await fastApiClient.cleanseAddress({
          address: rawAddressInput.trim(),
          state: stateHint.trim() || undefined,
          area: areaHint.trim() || undefined,
          postcode: postcodeHint.trim() || undefined,
          strict: isStrict,
          live_verify: isLive,
          verification_mode: activeMode,
        });
        setCleanseResult(result);
      } catch (err: any) {
        setCleanseError(
          err.message ||
            "Unable to reach FastAPI backend. Address cleansing is managed exclusively by FastAPI to prevent split-brain logic."
        );
        setCleanseResult(null);
      } finally {
        setIsCleansing(false);
      }
    },
    [rawAddressInput, stateHint, areaHint, postcodeHint, verificationMode]
  );

  // Perform initial cleanse on component mount
  useEffect(() => {
    handleCleanseAddress();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCopyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  const handleCopyStandardized = () => {
    if (!cleanseResult) return;
    navigator.clipboard.writeText(cleanseResult.formatted_address);
    setCopiedStandardized(true);
    setTimeout(() => setCopiedStandardized(false), 2000);
  };

  const handleCopyJson = () => {
    if (!cleanseResult) return;
    navigator.clipboard.writeText(JSON.stringify(cleanseResult, null, 2));
    setCopiedJson(true);
    setTimeout(() => setCopiedJson(false), 2000);
  };

  return (
    <div style={{ maxWidth: "1280px", margin: "0 auto" }}>
      {/* Top Banner / Intelligence Header */}
      <div
        style={{
          background: "#ffffff",
          color: "var(--ink)",
          padding: "20px 24px",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--line)",
          marginBottom: "20px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "16px",
          boxShadow: "var(--shadow-sm)",
        }}
      >
        <div>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              background: "#eff6ff",
              border: "1px solid #bfdbfe",
              color: "#1d4ed8",
              padding: "3px 10px",
              borderRadius: "20px",
              fontSize: "11px",
              fontWeight: 700,
              letterSpacing: "0.5px",
              marginBottom: "8px",
            }}
          >
            <ShieldCheck size={14} /> POSTCODE INTELLIGENCE PLATFORM
          </div>
          <h1
            style={{
              fontSize: "22px",
              fontWeight: 800,
              fontFamily: "'Manrope', sans-serif",
              margin: "0 0 6px",
              color: "var(--ink)",
            }}
          >
            Postcode Explorer & Address Verification
          </h1>
          <p style={{ margin: 0, fontSize: "13px", color: "#64748b", maxWidth: "680px" }}>
            Standardized Nigerian postal codes, digital address resolution, and verification adapter powered by FastAPI with NIPOST gateway integration.
          </p>
        </div>

        <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
          <div
            style={{
              background: "#f8fafc",
              border: "1px solid var(--line)",
              borderRadius: "8px",
              padding: "8px 14px",
              textAlign: "right",
            }}
          >
            <div style={{ fontSize: "10px", color: "#64748b", fontWeight: 700 }}>GATEWAY STATUS</div>
            <div style={{ fontSize: "12px", color: "#0f766e", fontWeight: 600, display: "flex", alignItems: "center", gap: "6px" }}>
              <Globe size={13} /> Adapter Active (NIPOST Two-Stage)
            </div>
          </div>
        </div>
      </div>

      {/* Sub-Tab Navigation Bar */}
      <div className="tab-bar" style={{ marginBottom: "20px" }}>
        <button
          type="button"
          className={`tab-btn ${activeSubTab === "directory" ? "active" : ""}`}
          onClick={() => setActiveSubTab("directory")}
        >
          <Search size={15} /> National Postcode Explorer
        </button>
        <button
          type="button"
          className={`tab-btn ${activeSubTab === "cleanser" ? "active" : ""}`}
          onClick={() => setActiveSubTab("cleanser")}
        >
          <Sparkles size={15} /> Nigerian Address Cleanser & Standardizer
        </button>
        <button
          type="button"
          className={`tab-btn ${activeSubTab === "coverage" ? "active" : ""}`}
          onClick={() => {
            setActiveSubTab("coverage");
            if (!coverageReport && !isLoadingCoverage) {
              fetchCoverageReport();
            }
          }}
        >
          <Database size={15} /> Data Coverage & Upstream Readiness
        </button>
      </div>

      {/* SUBTAB 1: POSTCODE DIRECTORY & EXPLORER */}
      {activeSubTab === "directory" && (
        <>
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>National Postal Code Directory & Registry Search</h2>
                <p>
                  Search official 6-digit conventional postal codes and 5-component digital location codes directly from FastAPI with real-time provenance tracking.
                </p>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                {isLoadingDirectory && (
                  <span style={{ fontSize: "12px", color: "#64748b", display: "flex", alignItems: "center", gap: "6px" }}>
                    <RefreshCw size={13} className="spin" /> Querying API...
                  </span>
                )}
                <span style={{ fontSize: "11px", color: "#64748b", background: "#f1f5f9", padding: "4px 10px", borderRadius: "12px" }}>
                  {directorySourceInfo || "FastAPI Registry"}
                </span>
              </div>
            </div>

            {/* Filter Bar with Search, State Select, and Strict Toggle */}
            <div className="filters" style={{ flexWrap: "wrap", gap: "12px" }}>
              <div className="search" style={{ flex: "1 1 300px" }}>
                <Search size={16} />
                <input
                  type="text"
                  placeholder="Search by 6-digit code, digital code (e.g. FC-02-A09-DB-09), area (Lekki, Wuse), or LGA..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>

              <select
                className="select-filter"
                value={selectedState}
                onChange={(e) => setSelectedState(e.target.value)}
                style={{ minWidth: "160px" }}
              >
                <option value="All">All States (Nigeria)</option>
                {STATES_LIST.map((st) => (
                  <option key={st} value={st}>
                    {st}
                  </option>
                ))}
              </select>

              {/* Strict Mode Toggle for Lookup */}
              <label
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "8px",
                  fontSize: "12px",
                  fontWeight: 600,
                  color: strictLookup ? "#dc2626" : "#475569",
                  background: strictLookup ? "#fef2f2" : "#f8fafc",
                  border: `1px solid ${strictLookup ? "#fecaca" : "#e2e8f0"}`,
                  padding: "0 12px",
                  borderRadius: "var(--radius-sm)",
                  cursor: "pointer",
                  height: "38px",
                  userSelect: "none",
                }}
                title="Strict Verification Mode: Fails closed if upstream NIPOST is unavailable or unauthorized"
              >
                <input
                  type="checkbox"
                  checked={strictLookup}
                  onChange={(e) => setStrictLookup(e.target.checked)}
                  style={{ cursor: "pointer" }}
                />
                <ShieldAlert size={15} color={strictLookup ? "#dc2626" : "#64748b"} />
                Strict Fail-Closed Mode
              </label>
            </div>

            {/* Strict Error Alert */}
            {directoryError && (
              <div
                style={{
                  background: "#fef2f2",
                  border: "1px solid #fecaca",
                  borderRadius: "var(--radius-sm)",
                  padding: "12px 16px",
                  margin: "12px 0",
                  color: "#991b1b",
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  fontSize: "12px",
                }}
              >
                <AlertCircle size={16} />
                <div>
                  <strong>Strict Verification Block:</strong> {directoryError}
                </div>
              </div>
            )}

            {/* Directory Results Table */}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>POSTAL CODE</th>
                    <th>AREA / DISTRICT</th>
                    <th>LGA & STATE</th>
                    <th>VERIFICATION TIER</th>
                    <th>PROVENANCE & DATASET</th>
                    <th>ACTION</th>
                  </tr>
                </thead>
                <tbody>
                  {directoryItems.map((item, idx) => {
                    const badge = getVerificationBadgeConfig(
                      item.verification_status,
                      item.provenance?.includes("Live API"),
                      Boolean(item.verification_method === "validator")
                    );

                    return (
                      <tr key={`${item.code}-${item.area}-${idx}`}>
                        <td>
                          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                            <b
                              className="ref"
                              style={{
                                fontSize: "13px",
                                fontFamily: "'JetBrains Mono', monospace",
                              }}
                            >
                              {item.code}
                            </b>
                            <button
                              type="button"
                              className="icon-btn"
                              style={{ padding: "4px" }}
                              title="Copy postal code"
                              onClick={() => handleCopyCode(item.code)}
                            >
                              {copiedCode === item.code ? (
                                <Check size={12} color="#16a34a" />
                              ) : (
                                <Copy size={12} />
                              )}
                            </button>
                          </div>
                          {item.postcode_type === "digital_location" && (
                            <span
                              style={{
                                fontSize: "9px",
                                color: "#0284c7",
                                background: "#e0f2fe",
                                padding: "1px 5px",
                                borderRadius: "3px",
                                fontWeight: 700,
                              }}
                            >
                              DIGITAL POSTCODE
                            </span>
                          )}
                        </td>
                        <td>
                          <b style={{ fontSize: "13px" }}>{item.area}</b>
                          {item.building_reference && (
                            <small style={{ color: "#0284c7" }}>
                              <Building size={11} style={{ display: "inline", marginRight: "3px" }} />
                              {item.building_reference}
                            </small>
                          )}
                        </td>
                        <td>
                          <b>{item.lga || "LGA Not Specified"}</b>
                          <small>{item.state}</small>
                        </td>
                        <td>
                          <span
                            className={badge.pillClass}
                            style={{ fontSize: "10px", padding: "3px 8px" }}
                            title={badge.description}
                          >
                            <i></i> {badge.label}
                          </span>
                        </td>
                        <td>
                          <div style={{ fontSize: "11px", color: "#475569" }}>
                            {item.provenance || "PostcodeLink Dataset"}
                          </div>
                          <div style={{ fontSize: "10px", color: "#94a3b8" }}>
                            Version: {item.dataset_version || "2024.2"}
                            {item.evidence_id && ` · Ev: ${item.evidence_id.slice(0, 8)}`}
                          </div>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="outline"
                            style={{ height: "30px", fontSize: "11px", padding: "0 10px" }}
                            onClick={() =>
                              onStartDeliveryWithAddress(
                                `${item.area}, ${item.lga || ""}, ${item.state}`,
                                item.code
                              )
                            }
                          >
                            <Plus size={13} /> Dispatch to Zone
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                  {directoryItems.length === 0 && !isLoadingDirectory && (
                    <tr>
                      <td colSpan={6} className="empty" style={{ padding: "36px", textAlign: "center" }}>
                        {directoryError ? (
                          <>
                            <AlertCircle size={28} color="#dc2626" style={{ margin: "0 auto 8px" }} />
                            <div style={{ fontWeight: 600, color: "#991b1b" }}>
                              FastAPI Directory Query Failed
                            </div>
                            <div style={{ fontSize: "12px", color: "#64748b", marginTop: "4px" }}>
                              {directoryError}. Verify FastAPI backend connectivity and configuration.
                            </div>
                          </>
                        ) : (
                          <>
                            <Compass size={28} color="#94a3b8" style={{ margin: "0 auto 8px" }} />
                            <div style={{ fontWeight: 600, color: "#475569" }}>
                              {searchQuery ? `No postcode records match "${searchQuery}".` : "No postcode records found."}
                            </div>
                            <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "4px" }}>
                              Try searching by state capital (e.g. Ikeja, Garki, Port Harcourt) or 6-digit prefix.
                            </div>
                          </>
                        )}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="table-foot" style={{ display: "flex", justifyContent: "space-between" }}>
              <span>Showing {directoryItems.length} records</span>
              <span>PostcodeLink Unified Nigeria Postcode Intelligence Platform</span>
            </div>
          </section>

          {/* Educational Panels */}
          <div className="bottom-grid" style={{ marginTop: "20px" }}>
            <section className="panel mini">
              <div className="mini-title">
                <div>
                  <h2>Understanding Nigerian Postal Formats</h2>
                  <p>Conventional 6-Digit vs Digital Postcode</p>
                </div>
                <Compass size={18} color="#2563eb" />
              </div>
              <div style={{ marginTop: "14px", fontSize: "12px", color: "#475569", lineHeight: 1.6 }}>
                <div>
                  <b style={{ color: "var(--ink)" }}>Conventional 6-Digit Area Code (e.g. 105102):</b>
                  <div>Hierarchical structure: Digit 1 (Zone) · Digits 1-3 (Dispatch District) · Digits 4-6 (Delivery Office).</div>
                </div>
                <div style={{ marginTop: "8px" }}>
                  <b style={{ color: "var(--ink)" }}>Digital Location Postcode (e.g. FC-02-A09-DB-09):</b>
                  <div>Five individual components: State (FC) - District (02) - Area (A09) - Block (DB) - Building (09).</div>
                </div>
              </div>
            </section>

            <section className="panel mini">
              <div className="mini-title">
                <div>
                  <h2>Verification Provenance Tiers</h2>
                  <p>Transparent government vs local metadata</p>
                </div>
                <CheckCircle2 size={18} color="#16a34a" />
              </div>
              <div style={{ marginTop: "14px", fontSize: "12px", color: "#475569", lineHeight: 1.6 }}>
                <div>
                  <b style={{ color: "#16a34a" }}>NIPOST Verified (0.95+):</b> Live verification confirmed by official NIPOST gateway API with verifiable SHA-256 evidence record.
                </div>
                <div style={{ marginTop: "8px" }}>
                  <b style={{ color: "#7c3aed" }}>Partially Verified (0.85):</b> Code existence validated by NIPOST Validator; address metadata enriched from local database.
                </div>
                <div style={{ marginTop: "8px" }}>
                  <b style={{ color: "#d97706" }}>Local Reference (0.75):</b> Matched against local dataset fixtures; never misrepresented as authoritative government verification.
                </div>
              </div>
            </section>
          </div>
        </>
      )}

      {/* SUBTAB 2: NIGERIAN ADDRESS CLEANSER & STANDARDIZER */}
      {activeSubTab === "cleanser" && (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Nigerian Address Cleanser & Standardizer</h2>
              <p>
                Normalize unstructured street text, detect landmark cues, match administrative boundaries, and resolve verified postcodes via FastAPI.
              </p>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <span
                style={{
                  fontSize: "11px",
                  background:
                    verificationMode === "nipost_strict"
                      ? "#fef2f2"
                      : verificationMode === "nipost_validate"
                      ? "#dcfce7"
                      : "#eff6ff",
                  color:
                    verificationMode === "nipost_strict"
                      ? "#b91c1c"
                      : verificationMode === "nipost_validate"
                      ? "#15803d"
                      : "#1d4ed8",
                  border: `1px solid ${
                    verificationMode === "nipost_strict"
                      ? "#fecaca"
                      : verificationMode === "nipost_validate"
                      ? "#bbf7d0"
                      : "#bfdbfe"
                  }`,
                  padding: "4px 10px",
                  borderRadius: "12px",
                  fontWeight: 600,
                  display: "flex",
                  alignItems: "center",
                  gap: "5px",
                }}
              >
                {verificationMode === "nipost_strict" && (
                  <>
                    <ShieldAlert size={13} /> Strict Fail-Closed Mode
                  </>
                )}
                {verificationMode === "nipost_validate" && (
                  <>
                    <Globe size={13} /> NIPOST Live Validation Mode
                  </>
                )}
                {verificationMode === "local_standardization" && (
                  <>
                    <Database size={13} /> Local Standardisation Mode
                  </>
                )}
              </span>
            </div>
          </div>

          {/* 3-Way Explicit Verification Mode Selector */}
          <div style={{ marginBottom: "18px" }}>
            <label
              id="verification-mode-label"
              style={{
                fontSize: "12px",
                fontWeight: 700,
                color: "var(--ink)",
                display: "block",
                marginBottom: "8px",
              }}
            >
              Verification & Cleansing Mode:
            </label>
            <div
              role="radiogroup"
              aria-labelledby="verification-mode-label"
              onKeyDown={handleRadioKeyDown}
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                gap: "12px",
              }}
            >
              {/* Option 1: Local Standardisation */}
              <button
                type="button"
                role="radio"
                aria-checked={verificationMode === "local_standardization"}
                tabIndex={verificationMode === "local_standardization" ? 0 : -1}
                onClick={() => setVerificationMode("local_standardization")}
                style={{
                  border: `2px solid ${
                    verificationMode === "local_standardization" ? "#2563eb" : "#e2e8f0"
                  }`,
                  background:
                    verificationMode === "local_standardization" ? "#eff6ff" : "#ffffff",
                  borderRadius: "var(--radius-sm)",
                  padding: "12px 14px",
                  cursor: "pointer",
                  textAlign: "left",
                  width: "100%",
                  fontFamily: "inherit",
                  transition: "all 0.15s ease",
                  outline: "none",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    marginBottom: "4px",
                  }}
                >
                  <Database
                    size={16}
                    color={
                      verificationMode === "local_standardization" ? "#2563eb" : "#64748b"
                    }
                  />
                  <b
                    style={{
                      fontSize: "13px",
                      color:
                        verificationMode === "local_standardization"
                          ? "#1e40af"
                          : "#1e293b",
                    }}
                  >
                    Local Standardisation
                  </b>
                  {verificationMode === "local_standardization" && (
                    <span
                      style={{
                        marginLeft: "auto",
                        fontSize: "10px",
                        fontWeight: 700,
                        color: "#2563eb",
                      }}
                    >
                      ACTIVE
                    </span>
                  )}
                </div>
                <div style={{ fontSize: "11px", color: "#64748b", lineHeight: 1.4 }}>
                  Format address syntax & match against local reference dataset (offline; zero external network calls).
                </div>
              </button>

              {/* Option 2: NIPOST Validation & Autofill */}
              <button
                type="button"
                role="radio"
                aria-checked={verificationMode === "nipost_validate"}
                tabIndex={verificationMode === "nipost_validate" ? 0 : -1}
                onClick={() => setVerificationMode("nipost_validate")}
                style={{
                  border: `2px solid ${
                    verificationMode === "nipost_validate" ? "#16a34a" : "#e2e8f0"
                  }`,
                  background:
                    verificationMode === "nipost_validate" ? "#f0fdf4" : "#ffffff",
                  borderRadius: "var(--radius-sm)",
                  padding: "12px 14px",
                  cursor: "pointer",
                  textAlign: "left",
                  width: "100%",
                  fontFamily: "inherit",
                  transition: "all 0.15s ease",
                  outline: "none",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    marginBottom: "4px",
                  }}
                >
                  <Globe
                    size={16}
                    color={
                      verificationMode === "nipost_validate" ? "#16a34a" : "#64748b"
                    }
                  />
                  <b
                    style={{
                      fontSize: "13px",
                      color:
                        verificationMode === "nipost_validate"
                          ? "#166534"
                          : "#1e293b",
                    }}
                  >
                    NIPOST Validation & Autofill
                  </b>
                  {verificationMode === "nipost_validate" && (
                    <span
                      style={{
                        marginLeft: "auto",
                        fontSize: "10px",
                        fontWeight: 700,
                        color: "#16a34a",
                      }}
                    >
                      ACTIVE
                    </span>
                  )}
                </div>
                <div style={{ fontSize: "11px", color: "#64748b", lineHeight: 1.4 }}>
                  Live upstream check with graceful fallback to local reference data if gateway is offline.
                </div>
              </button>

              {/* Option 3: Strict Fail-Closed Verification */}
              <button
                type="button"
                role="radio"
                aria-checked={verificationMode === "nipost_strict"}
                tabIndex={verificationMode === "nipost_strict" ? 0 : -1}
                onClick={() => setVerificationMode("nipost_strict")}
                style={{
                  border: `2px solid ${
                    verificationMode === "nipost_strict" ? "#dc2626" : "#e2e8f0"
                  }`,
                  background:
                    verificationMode === "nipost_strict" ? "#fef2f2" : "#ffffff",
                  borderRadius: "var(--radius-sm)",
                  padding: "12px 14px",
                  cursor: "pointer",
                  textAlign: "left",
                  width: "100%",
                  fontFamily: "inherit",
                  transition: "all 0.15s ease",
                  outline: "none",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    marginBottom: "4px",
                  }}
                >
                  <ShieldAlert
                    size={16}
                    color={
                      verificationMode === "nipost_strict" ? "#dc2626" : "#64748b"
                    }
                  />
                  <b
                    style={{
                      fontSize: "13px",
                      color:
                        verificationMode === "nipost_strict"
                          ? "#991b1b"
                          : "#1e293b",
                    }}
                  >
                    Strict Fail-Closed Verification
                  </b>
                  {verificationMode === "nipost_strict" && (
                    <span
                      style={{
                        marginLeft: "auto",
                        fontSize: "10px",
                        fontWeight: 700,
                        color: "#dc2626",
                      }}
                    >
                      ACTIVE
                    </span>
                  )}
                </div>
                <div style={{ fontSize: "11px", color: "#64748b", lineHeight: 1.4 }}>
                  Authoritative NIPOST evidence required. Fails closed with error if upstream rejects or fails.
                </div>
              </button>
            </div>
          </div>

          {/* Input Textarea */}
          <div style={{ marginBottom: "16px" }}>
            <label style={{ fontSize: "12px", fontWeight: 700, display: "block", marginBottom: "6px" }}>
              Unstructured Address / Delivery Notes:
            </label>
            <textarea
              style={{
                width: "100%",
                height: "85px",
                border: "1px solid var(--line)",
                borderRadius: "var(--radius-sm)",
                padding: "12px",
                fontFamily: "'DM Sans', sans-serif",
                fontSize: "13px",
                color: "var(--ink)",
                outline: "none",
                resize: "vertical",
              }}
              value={rawAddressInput}
              onChange={(e) => setRawAddressInput(e.target.value)}
              placeholder="e.g. Plot 14 Admiralty Way, opposite Ebeano Supermarket, Lekki Phase 1, Lagos"
            />
          </div>

          {/* Optional Explicit Hints */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: "12px",
              marginBottom: "16px",
            }}
          >
            <div>
              <label style={{ fontSize: "11px", fontWeight: 700, color: "#64748b", display: "block", marginBottom: "4px" }}>
                STATE HINT (OPTIONAL)
              </label>
              <input
                type="text"
                placeholder="e.g. Lagos, Abuja FCT, Rivers"
                value={stateHint}
                onChange={(e) => setStateHint(e.target.value)}
                style={{
                  width: "100%",
                  height: "36px",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius-sm)",
                  padding: "0 10px",
                  fontSize: "12px",
                }}
              />
            </div>
            <div>
              <label style={{ fontSize: "11px", fontWeight: 700, color: "#64748b", display: "block", marginBottom: "4px" }}>
                AREA HINT (OPTIONAL)
              </label>
              <input
                type="text"
                placeholder="e.g. Lekki Phase 1, Wuse 2"
                value={areaHint}
                onChange={(e) => setAreaHint(e.target.value)}
                style={{
                  width: "100%",
                  height: "36px",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius-sm)",
                  padding: "0 10px",
                  fontSize: "12px",
                }}
              />
            </div>
            <div>
              <label style={{ fontSize: "11px", fontWeight: 700, color: "#64748b", display: "block", marginBottom: "4px" }}>
                POSTCODE HINT (OPTIONAL)
              </label>
              <input
                type="text"
                placeholder="e.g. 105102 or FC-02-A09-DB-09"
                value={postcodeHint}
                onChange={(e) => setPostcodeHint(e.target.value)}
                style={{
                  width: "100%",
                  height: "36px",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius-sm)",
                  padding: "0 10px",
                  fontSize: "12px",
                }}
              />
            </div>
          </div>

          {/* Action & Sample Buttons */}
          <div
            style={{
              display: "flex",
              gap: "10px",
              flexWrap: "wrap",
              alignItems: "center",
              marginBottom: "20px",
            }}
          >
            <button
              type="button"
              className="primary"
              onClick={() => handleCleanseAddress()}
              disabled={isCleansing || !rawAddressInput.trim()}
            >
              {isCleansing ? (
                <>
                  <RefreshCw size={15} className="spin" /> Cleansing via FastAPI...
                </>
              ) : (
                <>
                  <Sparkles size={15} /> Cleanse & Standardize Address
                </>
              )}
            </button>

            <button
              type="button"
              className="outline"
              onClick={() => {
                setRawAddressInput("Plot 14 Admiralty Way, opposite Ebeano Supermarket, Lekki Phase 1, Lagos");
                setStateHint("Lagos");
                setAreaHint("Lekki Phase 1");
                setPostcodeHint("105102");
              }}
            >
              Sample Lagos (Lekki)
            </button>

            <button
              type="button"
              className="outline"
              onClick={() => {
                setRawAddressInput("Beside Access Bank, Plot 412 Aminu Kano Crescent, Wuse 2, Abuja");
                setStateHint("Abuja FCT");
                setAreaHint("Wuse 2");
                setPostcodeHint("900288");
              }}
            >
              Sample Abuja (Wuse 2)
            </button>

            <button
              type="button"
              className="outline"
              onClick={() => {
                setRawAddressInput("8 Forces Avenue, Old GRA near Shell Camp, Port Harcourt Rivers State");
                setStateHint("Rivers");
                setAreaHint("Old GRA");
                setPostcodeHint("500241");
              }}
            >
              Sample Port Harcourt
            </button>

            <button
              type="button"
              className="outline"
              onClick={() => {
                setRawAddressInput("Ahmadu Bello Way, Central Business District, Abuja");
                setStateHint("Abuja FCT");
                setAreaHint("Central Business District");
                setPostcodeHint("FC-02-A09-DB-09");
              }}
            >
              Sample Digital Postcode (FC-02)
            </button>
          </div>

          {/* Cleanser Error Alert */}
          {cleanseError && (
            <div
              style={{
                background: "#fef2f2",
                border: "1px solid #fecaca",
                borderRadius: "var(--radius-sm)",
                padding: "14px 18px",
                marginBottom: "20px",
                color: "#991b1b",
                display: "flex",
                alignItems: "flex-start",
                gap: "12px",
                fontSize: "13px",
              }}
            >
              <AlertCircle size={18} style={{ flexShrink: 0, marginTop: "2px" }} />
              <div>
                <b>Cleansing Blocked:</b>
                <div style={{ marginTop: "4px" }}>{cleanseError}</div>
                {verificationMode === "nipost_strict" && (
                  <div style={{ marginTop: "6px", fontSize: "11px", color: "#b91c1c" }}>
                    Strict verification prevented fallback to local demonstration data. Ensure NIPOST gateway is online or switch to standardisation/validation mode.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Cleanser Result Presentation */}
          {cleanseResult && (() => {
            const badge = getVerificationBadgeConfig(
              cleanseResult.postcode_status,
              cleanseResult.is_live_nipost,
              cleanseResult.is_partial_verification
            );

            const cardBorder =
              badge.tier === "nipost_verified"
                ? "#bbf7d0"
                : badge.tier === "partially_verified"
                ? "#ddd6fe"
                : badge.tier === "local_match"
                ? "#fde68a"
                : badge.tier === "address_conflict"
                ? "#fecaca"
                : "#e2e8f0";

            const cardBg =
              badge.tier === "address_conflict" ? "#fffdfd" : "#ffffff";

            const resultHeadline =
              badge.tier === "nipost_verified"
                ? "Address Cleansed & Officially Verified (NIPOST Live)"
                : badge.tier === "partially_verified"
                ? "Address Cleansed & Validated (NIPOST Two-Stage)"
                : badge.tier === "local_match"
                ? "Address Normalized (Local Reference Registry)"
                : badge.tier === "address_conflict"
                ? "Address Discrepancy Detected (Local Reference)"
                : "Address Syntax Formatted";

            const ResultIcon =
              badge.tier === "address_conflict"
                ? AlertTriangle
                : badge.tier === "unavailable"
                ? AlertCircle
                : CheckCircle2;

            const heuristicScore =
              cleanseResult.match_quality_score !== undefined
                ? cleanseResult.match_quality_score
                : cleanseResult.confidence;

            return (
              <div
                className="analyzer-card"
                style={{
                  background: cardBg,
                  border: `1px solid ${cardBorder}`,
                  borderRadius: "var(--radius-md)",
                  padding: "20px",
                  boxShadow: "var(--shadow-sm)",
                }}
              >
                {/* Header with Tier Badge and Heuristic Quality */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: "12px",
                    paddingBottom: "16px",
                    borderBottom: "1px solid #e2e8f0",
                    marginBottom: "16px",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <ResultIcon size={22} color={badge.color} />
                    <div>
                      <b style={{ fontSize: "15px", color: "var(--ink)" }}>
                        {resultHeadline}
                      </b>
                      <div style={{ fontSize: "12px", color: "#64748b" }}>
                        Resolution: {cleanseResult.resolution_level === "building_location" ? "Precise Building Location" : "Area Dispatch District"}
                      </div>
                    </div>
                  </div>

                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <span
                      className={badge.pillClass}
                      style={{ fontSize: "11px", padding: "5px 12px" }}
                      title={badge.description}
                    >
                      <i></i> {badge.label}
                    </span>
                  </div>
                </div>

                {/* Five-Dimension Verification & Trust Metrics */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
                    gap: "10px",
                    marginBottom: "16px",
                  }}
                >
                  {/* 1. Address Syntax */}
                  <div
                    style={{
                      background: "#f8fafc",
                      border: "1px solid #e2e8f0",
                      borderRadius: "6px",
                      padding: "10px 12px",
                    }}
                  >
                    <div style={{ fontSize: "10px", color: "#64748b", fontWeight: 700 }}>
                      1. FORMAT SYNTAX
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                      {cleanseResult.postcode_valid ? (
                        <CheckCheck size={15} color="#16a34a" />
                      ) : (
                        <AlertCircle size={15} color="#dc2626" />
                      )}
                      <b style={{ fontSize: "12px", color: cleanseResult.postcode_valid ? "#16a34a" : "#dc2626" }}>
                        {cleanseResult.postcode_valid ? "Valid Syntax" : "Invalid Syntax"}
                      </b>
                    </div>
                    <small style={{ color: "#64748b", fontSize: "11px", display: "block", marginTop: "2px" }}>
                      {cleanseResult.postcode_type === "digital_location"
                        ? "5-Part Digital Code"
                        : "6-Digit Postal Zone"}
                    </small>
                  </div>

                  {/* 2. Registry Existence */}
                  <div
                    style={{
                      background: "#f8fafc",
                      border: "1px solid #e2e8f0",
                      borderRadius: "6px",
                      padding: "10px 12px",
                    }}
                  >
                    <div style={{ fontSize: "10px", color: "#64748b", fontWeight: 700 }}>
                      2. REGISTRY EXISTENCE
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                      {cleanseResult.postcode_exists === true ? (
                        <CheckCheck size={15} color="#16a34a" />
                      ) : cleanseResult.postcode_exists === false ? (
                        <AlertCircle size={15} color="#dc2626" />
                      ) : cleanseResult.postcode_status !== "unverified" ? (
                        <CheckCheck size={15} color="#d97706" />
                      ) : (
                        <AlertCircle size={15} color="#dc2626" />
                      )}
                      <b
                        style={{
                          fontSize: "12px",
                          color:
                            cleanseResult.postcode_exists === true
                              ? "#16a34a"
                              : cleanseResult.postcode_exists === false
                              ? "#dc2626"
                              : cleanseResult.postcode_status !== "unverified"
                              ? "#d97706"
                              : "#dc2626",
                        }}
                      >
                        {cleanseResult.postcode_exists === true
                          ? "Confirmed in Registry"
                          : cleanseResult.postcode_exists === false
                          ? "Not Found in Registry"
                          : cleanseResult.postcode_status !== "unverified"
                          ? "Local Registry Match"
                          : "Unmatched"}
                      </b>
                    </div>
                    <small style={{ color: "#64748b", fontSize: "11px", display: "block", marginTop: "2px" }}>
                      {cleanseResult.resolution_level === "building_location"
                        ? "Building Location"
                        : "Area Dispatch District"}
                    </small>
                  </div>

                  {/* 3. Upstream Gateway / Provenance */}
                  <div
                    style={{
                      background: "#f8fafc",
                      border: "1px solid #e2e8f0",
                      borderRadius: "6px",
                      padding: "10px 12px",
                    }}
                  >
                    <div style={{ fontSize: "10px", color: "#64748b", fontWeight: 700 }}>
                      3. UPSTREAM GATEWAY
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                      {cleanseResult.is_live_nipost ? (
                        <CheckCheck size={15} color="#2563eb" />
                      ) : cleanseResult.upstream_contacted ? (
                        <AlertCircle size={15} color="#d97706" />
                      ) : cleanseResult.fallback_used ? (
                        <AlertTriangle size={15} color="#d97706" />
                      ) : (
                        <Compass size={15} color="#64748b" />
                      )}
                      <b
                        style={{
                          fontSize: "12px",
                          color: cleanseResult.is_live_nipost
                            ? "#2563eb"
                            : cleanseResult.upstream_contacted
                            ? "#d97706"
                            : cleanseResult.fallback_used
                            ? "#d97706"
                            : "#475569",
                        }}
                      >
                        {cleanseResult.is_live_nipost
                          ? cleanseResult.is_partial_verification
                            ? "Validated (Two-Stage)"
                            : "Official Verified"
                          : cleanseResult.upstream_contacted
                          ? "Contacted (Postcode Missing)"
                          : cleanseResult.fallback_used
                          ? "Fallback to Local"
                          : "Reference Only"}
                      </b>
                    </div>
                    <small style={{ color: "#64748b", fontSize: "11px", display: "block", marginTop: "2px" }}>
                      {cleanseResult.evidence_id
                        ? `SHA-256 Ev: ${cleanseResult.evidence_id.slice(0, 8)}`
                        : cleanseResult.upstream_contacted
                        ? "Gateway Contacted (No Match)"
                        : "Offline Reference Fixture"}
                    </small>
                  </div>

                  {/* 4. Geographic Consistency */}
                  <div
                    style={{
                      background: "#f8fafc",
                      border: "1px solid #e2e8f0",
                      borderRadius: "6px",
                      padding: "10px 12px",
                    }}
                  >
                    <div style={{ fontSize: "10px", color: "#64748b", fontWeight: 700 }}>
                      4. BOUNDARY CONSISTENCY
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                      {cleanseResult.address_consistent ? (
                        <CheckCheck size={15} color="#16a34a" />
                      ) : (
                        <AlertTriangle size={15} color="#d97706" />
                      )}
                      <b style={{ fontSize: "12px", color: cleanseResult.address_consistent ? "#16a34a" : "#d97706" }}>
                        {cleanseResult.address_consistent ? "Consistent Area" : "Boundary Discrepancy"}
                      </b>
                    </div>
                    <small style={{ color: "#64748b", fontSize: "11px", display: "block", marginTop: "2px" }}>
                      {cleanseResult.area || "Area"}, {cleanseResult.state || "State"}
                    </small>
                  </div>

                  {/* 5. Internal Match Quality Score */}
                  <div
                    style={{
                      background: "#f8fafc",
                      border: "1px solid #e2e8f0",
                      borderRadius: "6px",
                      padding: "10px 12px",
                    }}
                  >
                    <div style={{ fontSize: "10px", color: "#64748b", fontWeight: 700 }}>
                      5. MATCH QUALITY (HEURISTIC)
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "4px" }}>
                      <b style={{ fontSize: "14px", color: "var(--ink)", fontFamily: "'JetBrains Mono', monospace" }}>
                        {Math.round(heuristicScore * 100)}%
                      </b>
                      <div style={{ flex: 1, background: "#e2e8f0", height: "6px", borderRadius: "3px", overflow: "hidden" }}>
                        <div
                          style={{
                            width: `${Math.round(heuristicScore * 100)}%`,
                            height: "100%",
                            background:
                              heuristicScore >= 0.9
                                ? "#16a34a"
                                : heuristicScore >= 0.7
                                ? "#d97706"
                                : "#dc2626",
                          }}
                        />
                      </div>
                    </div>
                    <small style={{ color: "#64748b", fontSize: "10px", display: "block", marginTop: "2px" }} title="Internal match quality heuristic, not an empirical delivery probability">
                      Score: {heuristicScore.toFixed(2)} · Match heuristic
                    </small>
                  </div>
                </div>

                {/* Resolved Postal Information Card */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                    gap: "14px",
                    marginBottom: "16px",
                  }}
                >
                  <div
                    style={{
                      background:
                        badge.tier === "nipost_verified"
                          ? "#f0fdf4"
                          : badge.tier === "address_conflict"
                          ? "#fef2f2"
                          : "#f8fafc",
                      border: `1px solid ${cardBorder}`,
                      borderRadius: "8px",
                      padding: "14px",
                    }}
                  >
                    <div style={{ fontSize: "10px", color: badge.color, fontWeight: 700, textTransform: "uppercase" }}>
                      STANDARDIZED POSTAL CODE
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "4px" }}>
                      <span
                        style={{
                          fontFamily: "'JetBrains Mono', monospace",
                          fontSize: "20px",
                          fontWeight: 700,
                          color: badge.color,
                        }}
                      >
                        {cleanseResult.postcode}
                      </span>
                      <button
                        type="button"
                        className="icon-btn"
                        onClick={() => handleCopyCode(cleanseResult.postcode)}
                        title="Copy postcode"
                      >
                        {copiedCode === cleanseResult.postcode ? (
                          <Check size={14} color="#16a34a" />
                        ) : (
                          <Copy size={14} />
                        )}
                      </button>
                    </div>
                    <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}>
                      Category: {cleanseResult.postcode_category || "legacy_postal_code"}
                    </div>
                  </div>

                <div
                  style={{
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: "8px",
                    padding: "14px",
                  }}
                >
                  <div style={{ fontSize: "10px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                    PROVENANCE & AUDIT TRAIL
                  </div>
                  <b style={{ fontSize: "13px", color: "var(--ink)", display: "block", marginTop: "4px" }}>
                    {cleanseResult.provenance || "PostcodeLink Dataset"}
                  </b>
                  <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}>
                    Owner: {cleanseResult.source_owner || "NIPOST / PostcodeLink"}
                    {cleanseResult.evidence_id && ` · Ev ID: ${cleanseResult.evidence_id.slice(0, 8)}`}
                    {cleanseResult.valid_until && ` · Valid: ${cleanseResult.valid_until.slice(0, 10)}`}
                  </div>
                </div>
              </div>

              {/* Standardized Dispatch Label Box */}
              <div
                style={{
                  background: "#f8fafc",
                  border: "1px solid #e2e8f0",
                  borderRadius: "8px",
                  padding: "16px",
                  marginBottom: "16px",
                }}
              >
                <div
                  style={{
                    fontSize: "11px",
                    fontWeight: 700,
                    color: "#64748b",
                    textTransform: "uppercase",
                    letterSpacing: "0.5px",
                    marginBottom: "8px",
                  }}
                >
                  STANDARDIZED DISPATCH LABEL (WAYBILL & COURIER READY)
                </div>
                <div
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: "13px",
                    fontWeight: 600,
                    color: "#0f172a",
                    background: "#ffffff",
                    padding: "12px 14px",
                    borderRadius: "6px",
                    border: "1px solid #cbd5e1",
                    wordBreak: "break-word",
                  }}
                >
                  {cleanseResult.formatted_address}
                </div>

                {/* Changes Made List */}
                {cleanseResult.changes_made && cleanseResult.changes_made.length > 0 && (
                  <div style={{ marginTop: "12px" }}>
                    <div style={{ fontSize: "11px", fontWeight: 700, color: "#64748b", marginBottom: "6px" }}>
                      CLEANSING AUDIT TRAIL:
                    </div>
                    <ul style={{ margin: 0, paddingLeft: "18px", fontSize: "12px", color: "#475569" }}>
                      {cleanseResult.changes_made.map((ch, idx) => (
                        <li key={idx} style={{ marginBottom: "2px" }}>
                          {ch}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Primary Action Buttons */}
                <div style={{ display: "flex", gap: "10px", marginTop: "16px", flexWrap: "wrap" }}>
                  <button type="button" className="outline" onClick={handleCopyStandardized}>
                    {copiedStandardized ? (
                      <>
                        <Check size={14} color="#16a34a" /> Copied to Clipboard
                      </>
                    ) : (
                      <>
                        <Copy size={14} /> Copy Standardized Address
                      </>
                    )}
                  </button>

                  <button
                    type="button"
                    className="primary"
                    onClick={() =>
                      onStartDeliveryWithAddress(
                        cleanseResult.formatted_address,
                        cleanseResult.postcode
                      )
                    }
                  >
                    <Plus size={15} /> Create Delivery With This Clean Address
                  </button>
                </div>
              </div>

              {/* Collapsible API Contract & Raw JSON Inspector */}
              <div
                style={{
                  border: "1px solid #e2e8f0",
                  borderRadius: "8px",
                  overflow: "hidden",
                  marginTop: "16px",
                }}
              >
                <button
                  type="button"
                  onClick={() => setShowJsonInspector(!showJsonInspector)}
                  style={{
                    width: "100%",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "10px 16px",
                    background: "#f8fafc",
                    border: "none",
                    cursor: "pointer",
                    fontSize: "12px",
                    fontWeight: 600,
                    color: "#334155",
                  }}
                >
                  <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <Code size={15} color="#2563eb" />
                    FastAPI Contract & Raw JSON Inspector (/api/v1/postcodes/cleanse)
                  </span>
                  {showJsonInspector ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </button>

                {showJsonInspector && (
                  <div style={{ padding: "14px 16px", background: "#0f172a", color: "#f8fafc" }}>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        marginBottom: "10px",
                        fontSize: "11px",
                        color: "#94a3b8",
                      }}
                    >
                      <span>Direct FastAPI Response Payload</span>
                      <button
                        type="button"
                        onClick={handleCopyJson}
                        style={{
                          background: "rgba(255, 255, 255, 0.1)",
                          border: "1px solid rgba(255, 255, 255, 0.2)",
                          color: "#fff",
                          padding: "3px 8px",
                          borderRadius: "4px",
                          cursor: "pointer",
                          fontSize: "11px",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "4px",
                        }}
                      >
                        {copiedJson ? (
                          <>
                            <Check size={12} color="#4ade80" /> Copied
                          </>
                        ) : (
                          <>
                            <Copy size={12} /> Copy JSON
                          </>
                        )}
                      </button>
                    </div>
                    <pre
                      style={{
                        margin: 0,
                        fontSize: "11px",
                        fontFamily: "'JetBrains Mono', monospace",
                        color: "#38bdf8",
                        overflowX: "auto",
                        maxHeight: "260px",
                        lineHeight: 1.5,
                      }}
                    >
                      {JSON.stringify(cleanseResult, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </div>
            );
          })()}
        </section>
      )}

      {/* SUBTAB 3: DATA COVERAGE & UPSTREAM READINESS */}
      {activeSubTab === "coverage" && (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Dataset Coverage & Upstream Adapter Status</h2>
              <p>
                Verifiable operational metrics: geographic breadth, coordinates, building-level digital codes, and live NIPOST integration readiness.
              </p>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <button
                type="button"
                className="outline"
                onClick={fetchCoverageReport}
                disabled={isLoadingCoverage}
                style={{ height: "32px", fontSize: "12px", display: "inline-flex", alignItems: "center", gap: "6px" }}
              >
                <RefreshCw size={13} className={isLoadingCoverage ? "spin" : ""} />
                Refresh Coverage
              </button>
            </div>
          </div>

          {coverageError && (
            <div
              style={{
                background: "#fef2f2",
                border: "1px solid #fecaca",
                borderRadius: "var(--radius-sm)",
                padding: "12px 16px",
                margin: "12px 0",
                color: "#991b1b",
                display: "flex",
                alignItems: "center",
                gap: "10px",
                fontSize: "12px",
              }}
            >
              <AlertCircle size={16} />
              <div>
                <strong>Coverage Query Error:</strong> {coverageError}
              </div>
            </div>
          )}

          {isLoadingCoverage && !coverageReport && (
            <div style={{ padding: "40px", textAlign: "center", color: "#64748b", fontSize: "13px" }}>
              <RefreshCw size={24} className="spin" style={{ margin: "0 auto 10px" }} />
              <div>Querying FastAPI Dataset Coverage Report...</div>
            </div>
          )}

          {coverageReport && (
            <>
              {/* Top Key Metrics */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: "14px",
                  marginBottom: "14px",
                }}
              >
                <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px" }}>
                  <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                    STATES COVERED
                  </div>
                  <div style={{ fontSize: "24px", fontWeight: 800, color: "var(--ink)", marginTop: "4px" }}>
                    {coverageReport.scope_states_count}{" "}
                    <span style={{ fontSize: "14px", fontWeight: 600, color: "#64748b" }}>/ 37</span>
                  </div>
                  <small style={{ fontSize: "11px", color: "#64748b" }}>
                    Active regional directories
                  </small>
                </div>

                <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px" }}>
                  <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                    TOTAL REFERENCE POSTCODES
                  </div>
                  <div style={{ fontSize: "24px", fontWeight: 800, color: "var(--ink)", marginTop: "4px" }}>
                    {coverageReport.total_reference_records.toLocaleString()}
                  </div>
                  <small style={{ fontSize: "11px", color: "#64748b" }}>
                    Edition {coverageReport.version}
                  </small>
                </div>

                <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px" }}>
                  <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                    GEO-REFERENCED (GPS)
                  </div>
                  <div style={{ fontSize: "24px", fontWeight: 800, color: "#0f766e", marginTop: "4px" }}>
                    {coverageReport.records_with_coordinates.toLocaleString()}
                  </div>
                  <small style={{ fontSize: "11px", color: "#64748b" }}>
                    {Math.round((coverageReport.records_with_coordinates / Math.max(1, coverageReport.total_reference_records)) * 100)}% with lat/lng coordinates
                  </small>
                </div>

                <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px" }}>
                  <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                    DIGITAL BUILDING CODES
                  </div>
                  <div style={{ fontSize: "24px", fontWeight: 800, color: "#1d4ed8", marginTop: "4px" }}>
                    {(coverageReport.national_digital_postcode_records ?? coverageReport.digital_building_level_records).toLocaleString()}
                  </div>
                  <small style={{ fontSize: "11px", color: "#64748b" }}>
                    5-part canonical digital codes
                  </small>
                </div>
              </div>

              {/* Data Governance & Breakdown Dimensions */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: "14px",
                  marginBottom: "20px",
                }}
              >
                <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "14px" }}>
                  <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                    LEGACY 6-DIGIT CODES
                  </div>
                  <div style={{ fontSize: "20px", fontWeight: 700, color: "#475569", marginTop: "4px" }}>
                    {(coverageReport.legacy_six_digit_records ?? 0).toLocaleString()}
                  </div>
                  <small style={{ fontSize: "11px", color: "#64748b" }}>
                    Conventional postal areas
                  </small>
                </div>

                <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "14px" }}>
                  <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                    COMPLETE METADATA
                  </div>
                  <div style={{ fontSize: "20px", fontWeight: 700, color: "#0f766e", marginTop: "4px" }}>
                    {(coverageReport.records_with_complete_metadata ?? 0).toLocaleString()}
                  </div>
                  <small style={{ fontSize: "11px", color: "#64748b" }}>
                    Area, state, LGA & GPS coordinates
                  </small>
                </div>

                <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "14px" }}>
                  <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                    EVIDENCE-BACKED PROVENANCE
                  </div>
                  <div style={{ fontSize: "20px", fontWeight: 700, color: "#16a34a", marginTop: "4px" }}>
                    {(coverageReport.records_with_valid_evidence ?? 0).toLocaleString()}
                  </div>
                  <small style={{ fontSize: "11px", color: "#64748b" }}>
                    Active unexpired NIPOST audit evidence
                  </small>
                </div>

                <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "14px" }}>
                  <div style={{ fontSize: "11px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                    LOCAL DEMO FIXTURES
                  </div>
                  <div style={{ fontSize: "20px", fontWeight: 700, color: "#d97706", marginTop: "4px" }}>
                    {(coverageReport.local_demonstration_fixtures ?? 0).toLocaleString()}
                  </div>
                  <small style={{ fontSize: "11px", color: "#64748b" }}>
                    Demonstration & reference fixtures
                  </small>
                </div>
              </div>

              {/* Two Column Grid: State Breakdown & Adapter Status */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
                  gap: "20px",
                }}
              >
                {/* Column 1: State Breakdown Table */}
                <div style={{ border: "1px solid #e2e8f0", borderRadius: "8px", overflow: "hidden" }}>
                  <div style={{ padding: "12px 16px", background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
                    <b style={{ fontSize: "13px", color: "var(--ink)" }}>Regional State Breakdown</b>
                  </div>
                  <div style={{ maxHeight: "320px", overflowY: "auto" }}>
                    <table>
                      <thead>
                        <tr>
                          <th style={{ fontSize: "11px" }}>STATE</th>
                          <th style={{ fontSize: "11px", textAlign: "right" }}>POSTCODES</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(coverageReport.records_per_state || {}).map(([state, count]) => (
                          <tr key={state}>
                            <td style={{ fontSize: "12px", fontWeight: 600 }}>{state}</td>
                            <td style={{ fontSize: "12px", textAlign: "right", fontFamily: "'JetBrains Mono', monospace" }}>
                              {count}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Column 2: Upstream NIPOST Integration Readiness */}
                <div style={{ border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px", background: "#ffffff" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "14px" }}>
                    <Globe size={18} color="#0f766e" />
                    <b style={{ fontSize: "14px", color: "var(--ink)" }}>
                      Upstream NIPOST Gateway Readiness
                    </b>
                  </div>

                  <div style={{ display: "flex", flexDirection: "column", gap: "10px", fontSize: "12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #f1f5f9", paddingBottom: "6px" }}>
                      <span style={{ color: "#64748b" }}>Adapter Module:</span>
                      <span style={{ fontWeight: 600, color: coverageReport.upstream_integration.adapter_installed ? "#16a34a" : "#dc2626" }}>
                        {coverageReport.upstream_integration.adapter_installed ? "Installed (NIPOSTClient)" : "Missing"}
                      </span>
                    </div>

                    <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #f1f5f9", paddingBottom: "6px" }}>
                      <span style={{ color: "#64748b" }}>Configuration Status:</span>
                      <span style={{ fontWeight: 600, color: coverageReport.upstream_integration.configuration_complete ? "#16a34a" : "#d97706" }}>
                        {coverageReport.upstream_integration.configuration_complete ? "Complete" : "Incomplete (Missing Key/URL)"}
                      </span>
                    </div>

                    <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #f1f5f9", paddingBottom: "6px" }}>
                      <span style={{ color: "#64748b" }}>Authentication Scheme:</span>
                      <span style={{ fontWeight: 600, fontFamily: "'JetBrains Mono', monospace" }}>
                        {coverageReport.upstream_integration.auth_scheme}
                      </span>
                    </div>

                    <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #f1f5f9", paddingBottom: "6px" }}>
                      <span style={{ color: "#64748b" }}>Gateway Endpoint (Base URL):</span>
                      <span style={{ fontWeight: 600, color: coverageReport.upstream_integration.base_url_set ? "#16a34a" : "#dc2626" }}>
                        {coverageReport.upstream_integration.base_url_set ? "Configured" : "Not Set"}
                      </span>
                    </div>

                    <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #f1f5f9", paddingBottom: "6px" }}>
                      <span style={{ color: "#64748b" }}>Production API Key:</span>
                      <span style={{ fontWeight: 600, color: coverageReport.upstream_integration.credentials_set ? "#16a34a" : "#dc2626" }}>
                        {coverageReport.upstream_integration.credentials_set ? "Configured (Protected)" : "Missing / Unconfigured"}
                      </span>
                    </div>

                    <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #f1f5f9", paddingBottom: "6px" }}>
                      <span style={{ color: "#64748b" }}>Operational Status:</span>
                      <span
                        style={{
                          fontWeight: 700,
                          color:
                            coverageReport.upstream_integration.status === "ready"
                              ? "#16a34a"
                              : coverageReport.upstream_integration.status === "awaiting_credentials"
                              ? "#d97706"
                              : "#64748b",
                        }}
                      >
                        {coverageReport.upstream_integration.display_status}
                      </span>
                    </div>
                  </div>

                  <div
                    style={{
                      background: "#f8fafc",
                      border: "1px solid #e2e8f0",
                      borderRadius: "6px",
                      padding: "10px 12px",
                      marginTop: "14px",
                      fontSize: "11px",
                      color: "#475569",
                      lineHeight: 1.5,
                    }}
                  >
                    <strong>Provenance Integrity Disclosure:</strong> PostcodeLink guarantees strict verification separation. Local reference records are never promoted to official NIPOST verification without live upstream confirmation and cryptographically signed SHA-256 evidence.
                  </div>
                </div>
              </div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
