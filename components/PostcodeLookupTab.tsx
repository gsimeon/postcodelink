"use client";

import React, { useState, useMemo } from "react";
import {
  NIGERIA_POSTCODES,
  STATES_LIST,
  cleanseAndStandardizeAddress,
  AddressAnalysis,
  PostcodeEntry
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
  FileText
} from "lucide-react";

interface PostcodeLookupTabProps {
  onStartDeliveryWithAddress: (address: string, postcode: string) => void;
}

export function PostcodeLookupTab({ onStartDeliveryWithAddress }: PostcodeLookupTabProps) {
  const [activeSubTab, setActiveSubTab] = useState<"directory" | "cleanser">("directory");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedState, setSelectedState] = useState<string>("All");
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  // Address Cleanser states
  const [rawAddressInput, setRawAddressInput] = useState(
    "Plot 14 Admiralty Way, opposite Ebeano Supermarket, Lekki Phase 1, Lagos"
  );
  const [addressAnalysis, setAddressAnalysis] = useState<AddressAnalysis | null>(() =>
    cleanseAndStandardizeAddress("Plot 14 Admiralty Way, opposite Ebeano Supermarket, Lekki Phase 1, Lagos")
  );
  const [copiedStandardized, setCopiedStandardized] = useState(false);

  const filteredEntries = useMemo(() => {
    let list = NIGERIA_POSTCODES;
    if (selectedState !== "All") {
      list = list.filter((item) => item.state.toLowerCase() === selectedState.toLowerCase());
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      list = list.filter(
        (item) =>
          item.postcode.includes(q) ||
          item.districtOrArea.toLowerCase().includes(q) ||
          item.lga.toLowerCase().includes(q) ||
          item.state.toLowerCase().includes(q) ||
          (item.notes && item.notes.toLowerCase().includes(q))
      );
    }
    return list;
  }, [searchQuery, selectedState]);

  const handleCopy = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  const handleAnalyzeAddress = () => {
    if (!rawAddressInput.trim()) return;
    const result = cleanseAndStandardizeAddress(rawAddressInput);
    setAddressAnalysis(result);
  };

  const handleCopyStandardized = () => {
    if (!addressAnalysis) return;
    navigator.clipboard.writeText(addressAnalysis.standardizedAddress);
    setCopiedStandardized(true);
    setTimeout(() => setCopiedStandardized(false), 2000);
  };

  return (
    <div>
      {/* Tab Switcher */}
      <div className="tab-bar">
        <button
          type="button"
          className={`tab-btn ${activeSubTab === "directory" ? "active" : ""}`}
          onClick={() => setActiveSubTab("directory")}
        >
          <Search size={15} /> National Postcode Directory ({NIGERIA_POSTCODES.length} zones)
        </button>
        <button
          type="button"
          className={`tab-btn ${activeSubTab === "cleanser" ? "active" : ""}`}
          onClick={() => setActiveSubTab("cleanser")}
        >
          <Sparkles size={15} /> Nigerian Address Cleanser & Standardizer
        </button>
      </div>

      {activeSubTab === "directory" ? (
        <>
          {/* Postcode Directory Header */}
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Nigerian Postal Service (NIPOST) Digital Postcode Registry</h2>
                <p>
                  Official 6-digit postal codes mapped to states, local government areas (LGAs), and last-mile dispatch offices.
                </p>
              </div>
            </div>

            {/* Filters */}
            <div className="filters">
              <div className="search">
                <Search size={16} />
                <input
                  type="text"
                  placeholder="Search by 6-digit postcode, area (e.g. Lekki, Wuse), LGA, or State..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>

              <select
                className="select-filter"
                value={selectedState}
                onChange={(e) => setSelectedState(e.target.value)}
              >
                <option value="All">All States (Nigeria)</option>
                {STATES_LIST.map((st) => (
                  <option key={st} value={st}>
                    {st}
                  </option>
                ))}
              </select>
            </div>

            {/* Table */}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>POSTCODE</th>
                    <th>AREA / DISTRICT</th>
                    <th>LGA & STATE</th>
                    <th>ZONE</th>
                    <th>DISPATCH HUB NOTES</th>
                    <th>ACTION</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredEntries.map((item) => (
                    <tr key={`${item.state}-${item.postcode}-${item.districtOrArea}`}>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <b className="ref" style={{ fontSize: "13px" }}>
                            {item.postcode}
                          </b>
                          <button
                            type="button"
                            className="icon-btn"
                            style={{ padding: "4px" }}
                            title="Copy postcode"
                            onClick={() => handleCopy(item.postcode)}
                          >
                            {copiedCode === item.postcode ? (
                              <Check size={12} color="#16a34a" />
                            ) : (
                              <Copy size={12} />
                            )}
                          </button>
                        </div>
                      </td>
                      <td>
                        <b style={{ fontSize: "13px" }}>{item.districtOrArea}</b>
                      </td>
                      <td>
                        <b>{item.lga}</b>
                        <small>{item.state}</small>
                      </td>
                      <td>
                        <span className="pill blue" style={{ fontSize: "10px" }}>
                          {item.zone}
                        </span>
                      </td>
                      <td>
                        <span style={{ fontSize: "11px", color: "#64748b" }}>
                          {item.notes || "Standard delivery area"}
                        </span>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="outline"
                          style={{ height: "30px", fontSize: "11px", padding: "0 10px" }}
                          onClick={() =>
                            onStartDeliveryWithAddress(
                              `${item.districtOrArea}, ${item.lga}, ${item.state}`,
                              item.postcode
                            )
                          }
                        >
                          <Plus size={13} /> Dispatch to Zone
                        </button>
                      </td>
                    </tr>
                  ))}
                  {filteredEntries.length === 0 && (
                    <tr>
                      <td colSpan={6} className="empty">
                        No official postcode zones match your query "{searchQuery}".
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="table-foot">
              Showing {filteredEntries.length} of {NIGERIA_POSTCODES.length} verified postal zones
              <span>NIPOST Digital Postcode Registry</span>
            </div>
          </section>

          {/* Educational Note */}
          <div className="bottom-grid">
            <section className="panel mini">
              <div className="mini-title">
                <div>
                  <h2>How Nigerian Postcodes Work</h2>
                  <p>NIPOST 6-digit structure</p>
                </div>
                <Compass size={18} color="#2563eb" />
              </div>
              <div style={{ marginTop: "14px", fontSize: "12px", color: "#475569", lineHeight: 1.6 }}>
                <div>
                  <b style={{ color: "var(--ink)" }}>Digit 1 (Zone):</b> 9 zones across Nigeria (e.g. 1 = Lagos, 9 = Abuja FCT, 5 = Rivers/Bayelsa).
                </div>
                <div style={{ marginTop: "6px" }}>
                  <b style={{ color: "var(--ink)" }}>Digits 1-3 (Dispatch District):</b> Directs parcels to the main state dispatch sort facility.
                </div>
                <div style={{ marginTop: "6px" }}>
                  <b style={{ color: "var(--ink)" }}>Digits 4-6 (Delivery Office):</b> Identifies the local post office or delivery cluster (e.g., Lekki Phase 1 is 105102).
                </div>
              </div>
            </section>

            <section className="panel mini">
              <div className="mini-title">
                <div>
                  <h2>Delivery Efficiency Impact</h2>
                  <p>Why Nigerian merchants need postcodes</p>
                </div>
                <CheckCircle2 size={18} color="#16a34a" />
              </div>
              <div style={{ marginTop: "14px", fontSize: "12px", color: "#475569", lineHeight: 1.6 }}>
                <div>
                  <b style={{ color: "var(--ink)" }}>68% Fewer Driver Calls:</b> Riders don't need to ask "where you dey?" when orders carry verified cluster codes.
                </div>
                <div style={{ marginTop: "6px" }}>
                  <b style={{ color: "var(--ink)" }}>Automated Zone Routing:</b> Automatically assign riders based on their local LGA/postcode coverage.
                </div>
                <div style={{ marginTop: "6px" }}>
                  <b style={{ color: "var(--ink)" }}>Zero-Friction Fallback:</b> Works seamlessly even when landmarks are supplied instead of formal street numbers.
                </div>
              </div>
            </section>
          </div>
        </>
      ) : (
        /* Address Cleanser & Standardizer View */
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Nigerian Address Cleanser & Standardizer</h2>
              <p>
                Paste unstructured customer delivery notes or text from WhatsApp/checkout to parse landmarks, detect LGAs, and attach verified postcodes.
              </p>
            </div>
          </div>

          <div style={{ marginBottom: "20px" }}>
            <label style={{ fontSize: "12px", fontWeight: 700, display: "block", marginBottom: "8px" }}>
              Unstructured Address / Customer Delivery Notes:
            </label>
            <textarea
              style={{
                width: "100%",
                height: "90px",
                border: "1px solid var(--line)",
                borderRadius: "var(--radius-sm)",
                padding: "12px",
                fontFamily: "'DM Sans', sans-serif",
                fontSize: "13px",
                color: "var(--ink)",
                outline: "none",
              }}
              value={rawAddressInput}
              onChange={(e) => setRawAddressInput(e.target.value)}
              placeholder="e.g. Shop 4 beside Total filling station, Admiralty Way Lekki Phase 1 Lagos"
            />
            <div style={{ display: "flex", gap: "10px", marginTop: "10px" }}>
              <button type="button" className="primary" onClick={handleAnalyzeAddress}>
                <Sparkles size={15} /> Parse & Resolve Postcode
              </button>
              <button
                type="button"
                className="outline"
                onClick={() => {
                  setRawAddressInput(
                    "Beside Access Bank, Plot 412 Aminu Kano Crescent, Wuse 2, Abuja"
                  );
                }}
              >
                Sample Abuja Address
              </button>
              <button
                type="button"
                className="outline"
                onClick={() => {
                  setRawAddressInput(
                    "8 Forces Avenue, Old GRA near Shell Camp, Port Harcourt Rivers State"
                  );
                }}
              >
                Sample Port Harcourt Address
              </button>
            </div>
          </div>

          {/* Analysis Results Card */}
          {addressAnalysis && (
            <div className="analyzer-card">
              <div className="analyzer-head">
                <CheckCircle2 size={18} />
                <span>Address Successfully Resolved & Standardized</span>
                <span
                  className={`pill ${
                    addressAnalysis.confidence === "high" ? "green" : "amber"
                  }`}
                  style={{ marginLeft: "auto", fontSize: "10px" }}
                >
                  {addressAnalysis.confidence.toUpperCase()} CONFIDENCE
                </span>
              </div>

              <div className="form-grid" style={{ marginBottom: "14px" }}>
                <div style={{ background: "#ffffff", padding: "12px", borderRadius: "6px", border: "1px solid #bbf7d0" }}>
                  <div style={{ fontSize: "10px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                    DETECTED POSTCODE (NIPOST)
                  </div>
                  <b style={{ fontSize: "18px", color: "#166534", fontFamily: "'JetBrains Mono', monospace" }}>
                    {addressAnalysis.matchedPostcode ? `NG-${addressAnalysis.matchedPostcode}` : "UNVERIFIED"}
                  </b>
                  <div style={{ fontSize: "11px", color: "#166534", marginTop: "2px" }}>
                    {addressAnalysis.notes}
                  </div>
                </div>

                <div style={{ background: "#ffffff", padding: "12px", borderRadius: "6px", border: "1px solid #bbf7d0" }}>
                  <div style={{ fontSize: "10px", color: "#64748b", fontWeight: 700, textTransform: "uppercase" }}>
                    DETECTED AREA & JURISDICTION
                  </div>
                  <b style={{ fontSize: "14px", color: "#166534" }}>
                    {addressAnalysis.detectedArea || "General"}
                  </b>
                  <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                    LGA: {addressAnalysis.detectedLga || "N/A"} · State: {addressAnalysis.detectedState || "N/A"}
                  </div>
                </div>
              </div>

              {/* Standardized Dispatch String */}
              <div
                style={{
                  background: "#ffffff",
                  padding: "14px",
                  borderRadius: "6px",
                  border: "1px solid #bbf7d0",
                }}
              >
                <div style={{ fontSize: "10px", color: "#64748b", fontWeight: 700, textTransform: "uppercase", marginBottom: "6px" }}>
                  STANDARDIZED DISPATCH LABEL (READY FOR WAYBILL & RIDER)
                </div>
                <div
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: "13px",
                    fontWeight: 600,
                    color: "#0f172a",
                    background: "#f8fafc",
                    padding: "10px 12px",
                    borderRadius: "4px",
                    border: "1px solid #e2e8f0",
                  }}
                >
                  {addressAnalysis.standardizedAddress}
                </div>

                <div style={{ display: "flex", gap: "10px", marginTop: "12px" }}>
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
                        addressAnalysis.standardizedAddress,
                        addressAnalysis.matchedPostcode || ""
                      )
                    }
                  >
                    <Plus size={15} /> Create Delivery With This Clean Address
                  </button>
                </div>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

