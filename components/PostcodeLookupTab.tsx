"use client";

import React, { useState, useEffect, useMemo, useCallback } from "react";
import {
  fastApiClient,
  CleanseResult,
  PostcodeDirectoryEntry,
  PostcodeLookupResult,
} from "@/lib/fastapi-client";
import {
  NIGERIA_POSTCODES,
  STATES_LIST,
  cleanseAndStandardizeAddress,
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
      pillClass: "pill purple",
      color: "#7c3aed",
      bg: "#f5f3ff",
      border: "#ddd6fe",
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
      pillClass: "pill blue",
      color: "#2563eb",
      bg: "#eff6ff",
      border: "#bfdbfe",
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
  const [activeSubTab, setActiveSubTab] = useState<"directory" | "cleanser">("directory");

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
  const [liveVerifyToggle, setLiveVerifyToggle] = useState<boolean>(false);
  const [strictModeToggle, setStrictModeToggle] = useState<boolean>(false);

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
            ? `NIPOST Live Gateway (${res.dataset_version || "2026.1"}) · ${res.matches.length} matches`
            : `${res.provenance} · ${res.matches.length} matches`
        );
      } catch (err: any) {
        // Fallback to client-side dataset if FastAPI is offline or fails closed
        if (strict) {
          setDirectoryError(err.message || "Strict verification failed. Upstream gateway unavailable.");
          setDirectoryItems([]);
          setDirectorySourceInfo("Strict Mode: Fail-Closed Enforced");
        } else {
          // Graceful local demonstration fallback
          let local = NIGERIA_POSTCODES;
          if (state !== "All") {
            local = local.filter((item) => item.state.toLowerCase() === state.toLowerCase());
          }
          if (trimmed) {
            const q = trimmed.toLowerCase();
            local = local.filter(
              (item) =>
                item.postcode.includes(q) ||
                item.districtOrArea.toLowerCase().includes(q) ||
                item.lga.toLowerCase().includes(q) ||
                item.state.toLowerCase().includes(q)
            );
          }
          const mapped: PostcodeDirectoryEntry[] = local.map((l) => ({
            code: l.postcode,
            area: l.districtOrArea,
            state: l.state,
            lga: l.lga,
            postcode_type: "conventional_area",
            postcode_category: "local_address_reference",
            verification_status: "local_reference",
            provenance: "PostcodeLink Local Reference Dataset (Offline Fallback)",
            source_owner: "PostcodeLink",
            source_type: "local_reference",
          }));
          setDirectoryItems(mapped);
          setDirectorySourceInfo(
            `PostcodeLink Local Reference (Offline Demonstration) · ${mapped.length} records`
          );
        }
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
  const handleCleanseAddress = async () => {
    if (!rawAddressInput.trim()) return;

    setIsCleansing(true);
    setCleanseError(null);

    try {
      const result: CleanseResult = await fastApiClient.cleanseAddress({
        address: rawAddressInput.trim(),
        state: stateHint.trim() || undefined,
        area: areaHint.trim() || undefined,
        postcode: postcodeHint.trim() || undefined,
        strict: strictModeToggle,
        live_verify: liveVerifyToggle,
      });
      setCleanseResult(result);
    } catch (err: any) {
      if (strictModeToggle) {
        setCleanseError(
          `Strict Verification Block: ${err.message || "Upstream NIPOST gateway rejected or unavailable."}`
        );
        setCleanseResult(null);
      } else {
        // Fallback to local regex-based analysis with explicit local provenance
        try {
          const localAnalysis = cleanseAndStandardizeAddress(rawAddressInput);
          const fallbackResult: CleanseResult = {
            original_address: rawAddressInput,
            formatted_address: localAnalysis.standardizedAddress,
            area: localAnalysis.detectedArea || "General Area",
            state: localAnalysis.detectedState || "Nigeria",
            lga: localAnalysis.detectedLga || undefined,
            postcode: localAnalysis.matchedPostcode || "000000",
            postcode_type: "conventional_area",
            postcode_category: "local_address_reference",
            resolution_level: "area_district",
            postcode_status: localAnalysis.matchedPostcode ? "local_match" : "unverified",
            verification_status: "local_reference",
            confidence: localAnalysis.confidence === "high" ? 0.75 : 0.5,
            postcode_valid: Boolean(localAnalysis.matchedPostcode),
            address_consistent: true,
            dispatch_confidence: localAnalysis.confidence === "high" ? 0.75 : 0.5,
            source: "local_client_fallback",
            changes_made: [
              "Standardized street and building terms",
              `Detected administrative zone: ${localAnalysis.detectedArea || "General Area"}`,
              "Local regex fallback: verification status set to local_reference",
            ],
            provenance: "PostcodeLink Local Reference Dataset (Fallback)",
            source_owner: "PostcodeLink",
            source_type: "demonstration_fixture",
            checked_against_nipost: false,
            is_live_nipost: false,
            verification_source: "local_nipost_reference_dataset",
            fallback_used: true,
          };
          setCleanseResult(fallbackResult);
        } catch (innerErr: any) {
          setCleanseError(innerErr.message || "Failed to parse address.");
        }
      }
    } finally {
      setIsCleansing(false);
    }
  };

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
          background: "linear-gradient(135deg, #1e293b 0%, #0f172a 100%)",
          color: "#fff",
          padding: "24px 28px",
          borderRadius: "var(--radius-md)",
          marginBottom: "20px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "16px",
          boxShadow: "var(--shadow-md)",
        }}
      >
        <div>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              background: "rgba(59, 130, 246, 0.2)",
              border: "1px solid rgba(59, 130, 246, 0.4)",
              color: "#93c5fd",
              padding: "3px 10px",
              borderRadius: "20px",
              fontSize: "11px",
              fontWeight: 700,
              letterSpacing: "0.5px",
              marginBottom: "8px",
            }}
          >
            <ShieldCheck size={14} /> OFFICIAL NATIONAL POSTCODE INTELLIGENCE
          </div>
          <h1
            style={{
              fontSize: "22px",
              fontWeight: 800,
              fontFamily: "'Manrope', sans-serif",
              margin: "0 0 6px",
              color: "#fff",
            }}
          >
            Postcode Explorer & Address Cleansing Engine
          </h1>
          <p style={{ margin: 0, fontSize: "13px", color: "#94a3b8", maxWidth: "680px" }}>
            Authoritative Nigerian postal codes, digital address resolution, and fail-closed validation powered by direct FastAPI and NIPOST gateway integration.
          </p>
        </div>

        <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
          <div
            style={{
              background: "rgba(255, 255, 255, 0.08)",
              border: "1px solid rgba(255, 255, 255, 0.12)",
              borderRadius: "8px",
              padding: "8px 14px",
              textAlign: "right",
            }}
          >
            <div style={{ fontSize: "10px", color: "#94a3b8", fontWeight: 700 }}>VERIFICATION ARCHITECTURE</div>
            <div style={{ fontSize: "12px", color: "#38bdf8", fontWeight: 600, display: "flex", alignItems: "center", gap: "6px" }}>
              <Globe size={13} /> Two-Stage Live Orchestration
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
                        <Compass size={28} color="#94a3b8" style={{ margin: "0 auto 8px" }} />
                        <div style={{ fontWeight: 600, color: "#475569" }}>
                          No postcode records match your query "{searchQuery}".
                        </div>
                        <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "4px" }}>
                          Try searching by state capital (e.g. Ikeja, Garki, Port Harcourt) or 6-digit prefix.
                        </div>
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
                  background: liveVerifyToggle ? "#dcfce7" : "#f1f5f9",
                  color: liveVerifyToggle ? "#15803d" : "#64748b",
                  border: `1px solid ${liveVerifyToggle ? "#bbf7d0" : "#e2e8f0"}`,
                  padding: "4px 10px",
                  borderRadius: "12px",
                  fontWeight: 600,
                  display: "flex",
                  alignItems: "center",
                  gap: "5px",
                }}
              >
                <Globe size={13} /> {liveVerifyToggle ? "NIPOST Live Mode" : "Local Reference Mode"}
              </span>
            </div>
          </div>

          {/* Cleanser Controls: Live Toggle & Strict Toggle */}
          <div
            style={{
              background: "#f8fafc",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-sm)",
              padding: "14px 18px",
              marginBottom: "16px",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "14px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "20px", flexWrap: "wrap" }}>
              {/* Live NIPOST Gateway Toggle */}
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  fontSize: "12px",
                  fontWeight: 600,
                  cursor: "pointer",
                  color: liveVerifyToggle ? "#0f766e" : "#475569",
                }}
              >
                <input
                  type="checkbox"
                  checked={liveVerifyToggle}
                  onChange={(e) => setLiveVerifyToggle(e.target.checked)}
                  style={{ width: "16px", height: "16px", cursor: "pointer" }}
                />
                <Globe size={15} color={liveVerifyToggle ? "#0f766e" : "#64748b"} />
                Query Live NIPOST Gateway (`live_verify: true`)
              </label>

              {/* Strict Fail-Closed Mode Toggle */}
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  fontSize: "12px",
                  fontWeight: 600,
                  cursor: "pointer",
                  color: strictModeToggle ? "#dc2626" : "#475569",
                }}
              >
                <input
                  type="checkbox"
                  checked={strictModeToggle}
                  onChange={(e) => setStrictModeToggle(e.target.checked)}
                  style={{ width: "16px", height: "16px", cursor: "pointer" }}
                />
                <ShieldAlert size={15} color={strictModeToggle ? "#dc2626" : "#64748b"} />
                Strict Verification Mode (`strict: true`)
              </label>
            </div>

            <div style={{ fontSize: "11px", color: "#64748b" }}>
              {strictModeToggle
                ? "Fails closed with HTTP 502/503 if live gateway is offline"
                : "Gracefully falls back to local reference dataset if live gateway is unreachable"}
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
              onClick={handleCleanseAddress}
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
                {strictModeToggle && (
                  <div style={{ marginTop: "6px", fontSize: "11px", color: "#b91c1c" }}>
                    Strict verification prevented fallback to local demonstration data. Ensure NIPOST gateway is online or disable strict mode.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Cleanser Result Presentation */}
          {cleanseResult && (
            <div
              className="analyzer-card"
              style={{
                background: "#ffffff",
                border: "1px solid #bbf7d0",
                borderRadius: "var(--radius-md)",
                padding: "20px",
                boxShadow: "var(--shadow-sm)",
              }}
            >
              {/* Header with 6-Tier Badge and Confidence Meter */}
              {(() => {
                const badge = getVerificationBadgeConfig(
                  cleanseResult.postcode_status,
                  cleanseResult.is_live_nipost,
                  cleanseResult.is_partial_verification
                );

                return (
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
                      <CheckCircle2 size={22} color={badge.color} />
                      <div>
                        <b style={{ fontSize: "15px", color: "var(--ink)" }}>
                          Address Normalized & Cleansed
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
                );
              })()}

              {/* Three-Dimension Validation Metrics */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: "12px",
                  marginBottom: "16px",
                }}
              >
                <div
                  style={{
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: "6px",
                    padding: "12px",
                  }}
                >
                  <div style={{ fontSize: "10px", color: "#64748b", fontWeight: 700 }}>
                    1. POSTCODE SYNTAX VALIDITY
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                    {cleanseResult.postcode_valid ? (
                      <CheckCheck size={16} color="#16a34a" />
                    ) : (
                      <AlertCircle size={16} color="#dc2626" />
                    )}
                    <b style={{ fontSize: "13px", color: cleanseResult.postcode_valid ? "#16a34a" : "#dc2626" }}>
                      {cleanseResult.postcode_valid ? "Valid Postal Code" : "Invalid Syntax"}
                    </b>
                  </div>
                  <small style={{ color: "#64748b", fontSize: "11px", display: "block", marginTop: "2px" }}>
                    {cleanseResult.postcode_type === "digital_location"
                      ? "5-Component Digital Location"
                      : "Standard 6-Digit Zone"}
                  </small>
                </div>

                <div
                  style={{
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: "6px",
                    padding: "12px",
                  }}
                >
                  <div style={{ fontSize: "10px", color: "#64748b", fontWeight: 700 }}>
                    2. GEOGRAPHIC CONSISTENCY
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                    {cleanseResult.address_consistent ? (
                      <CheckCheck size={16} color="#16a34a" />
                    ) : (
                      <AlertTriangle size={16} color="#d97706" />
                    )}
                    <b style={{ fontSize: "13px", color: cleanseResult.address_consistent ? "#16a34a" : "#d97706" }}>
                      {cleanseResult.address_consistent ? "Consistent Area & State" : "Potential Boundary Mismatch"}
                    </b>
                  </div>
                  <small style={{ color: "#64748b", fontSize: "11px", display: "block", marginTop: "2px" }}>
                    Area: {cleanseResult.area} · State: {cleanseResult.state}
                  </small>
                </div>

                <div
                  style={{
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: "6px",
                    padding: "12px",
                  }}
                >
                  <div style={{ fontSize: "10px", color: "#64748b", fontWeight: 700 }}>
                    3. DISPATCH CONFIDENCE SCORE
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "4px" }}>
                    <b style={{ fontSize: "15px", color: "var(--ink)", fontFamily: "'JetBrains Mono', monospace" }}>
                      {Math.round(cleanseResult.dispatch_confidence * 100)}%
                    </b>
                    <div style={{ flex: 1, background: "#e2e8f0", height: "6px", borderRadius: "3px", overflow: "hidden" }}>
                      <div
                        style={{
                          width: `${Math.round(cleanseResult.dispatch_confidence * 100)}%`,
                          height: "100%",
                          background:
                            cleanseResult.dispatch_confidence >= 0.9
                              ? "#16a34a"
                              : cleanseResult.dispatch_confidence >= 0.7
                              ? "#d97706"
                              : "#dc2626",
                        }}
                      />
                    </div>
                  </div>
                  <small style={{ color: "#64748b", fontSize: "11px", display: "block", marginTop: "2px" }}>
                    Source Confidence: {cleanseResult.confidence}
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
                    background: "#f0fdf4",
                    border: "1px solid #bbf7d0",
                    borderRadius: "8px",
                    padding: "14px",
                  }}
                >
                  <div style={{ fontSize: "10px", color: "#166534", fontWeight: 700, textTransform: "uppercase" }}>
                    STANDARDIZED POSTAL CODE
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "4px" }}>
                    <span
                      style={{
                        fontFamily: "'JetBrains Mono', monospace",
                        fontSize: "20px",
                        fontWeight: 700,
                        color: "#166534",
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
                  <div style={{ fontSize: "11px", color: "#166534", marginTop: "4px" }}>
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
          )}
        </section>
      )}
    </div>
  );
}
