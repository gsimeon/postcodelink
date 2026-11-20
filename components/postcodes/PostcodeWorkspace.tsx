import React, { useState, useEffect, useCallback, useRef } from "react";
import { fastApiClient, PostcodeRecord, CleanseResult, VerificationMode, CoverageReport } from "@/lib/fastapi-client";
import { MapPin, Sparkles, Database } from "lucide-react";
import { PostcodeDirectory } from "./PostcodeDirectory";
import { AddressCleanser } from "./AddressCleanser";
import { CoverageDashboard } from "./CoverageDashboard";

interface PostcodeWorkspaceProps {
  onApplyPostcode?: (postcode: string, details?: any) => void;
  onStartDeliveryWithAddress?: (address: string, postcode: string) => void;
  initialPostcode?: string;
}

export const PostcodeWorkspace: React.FC<PostcodeWorkspaceProps> = ({
  onApplyPostcode,
  onStartDeliveryWithAddress,
  initialPostcode,
}) => {
  const [activeSubTab, setActiveSubTab] = useState<"directory" | "cleanser" | "coverage">("directory");

  // Directory Search States
  const [searchQuery, setSearchQuery] = useState<string>(initialPostcode || "");
  const [selectedState, setSelectedState] = useState<string>("All");
  const [strictLookup, setStrictLookup] = useState<boolean>(false);
  const [directoryItems, setDirectoryItems] = useState<PostcodeRecord[]>([]);
  const [isLoadingDirectory, setIsLoadingDirectory] = useState<boolean>(false);
  const [directoryError, setDirectoryError] = useState<string | null>(null);
  const [directorySourceInfo, setDirectorySourceInfo] = useState<string>("");
  const [copiedCode, setCopiedCode] = useState<string | null>(null);
  const searchRequestIdRef = useRef<number>(0);

  // Address Cleanser States
  const [rawAddressInput, setRawAddressInput] = useState<string>(
    "Plot 14 Admiralty Way, Lekki Phase 1, Lagos State"
  );
  const [stateHint, setStateHint] = useState<string>("Lagos");
  const [areaHint, setAreaHint] = useState<string>("Lekki Phase 1");
  const [postcodeHint, setPostcodeHint] = useState<string>("105102");
  const [verificationMode, setVerificationMode] = useState<VerificationMode>("nipost_validate");
  const [isCleansing, setIsCleansing] = useState<boolean>(false);
  const [cleanseResult, setCleanseResult] = useState<CleanseResult | null>(null);
  const [cleanseError, setCleanseError] = useState<string | null>(null);
  const [copiedStandardized, setCopiedStandardized] = useState<boolean>(false);
  const [copiedJson, setCopiedJson] = useState<boolean>(false);

  // Coverage Report States
  const [coverageReport, setCoverageReport] = useState<CoverageReport | null>(null);
  const [isLoadingCoverage, setIsLoadingCoverage] = useState<boolean>(false);
  const [coverageError, setCoverageError] = useState<string | null>(null);

  // Sequential Request-Protected Debounced Directory Search
  useEffect(() => {
    const requestId = ++searchRequestIdRef.current;
    const timer = setTimeout(async () => {
      setIsLoadingDirectory(true);
      setDirectoryError(null);

      const trimmed = searchQuery.trim();
      const isCode =
        /^\d{6}$/.test(trimmed) ||
        /^[A-Z]{2}-\d{2}-[A-Z0-9]{3}-[A-Z0-9]{2}-\d{2}$/i.test(trimmed);

      try {
        const res = await fastApiClient.lookupPostcodes({
          code: isCode ? trimmed : undefined,
          area: !isCode && trimmed ? trimmed : undefined,
          state: selectedState !== "All" ? selectedState : undefined,
          strict: strictLookup,
        });

        if (requestId === searchRequestIdRef.current) {
          setDirectoryItems(res.matches || []);
          setDirectorySourceInfo(
            res.is_live_nipost
              ? (res.dataset_version ? `NIPOST Live Gateway (${res.dataset_version}) · ${res.matches.length} matches` : `NIPOST Live Gateway · ${res.matches.length} matches`)
              : `${res.provenance} · ${res.matches.length} matches`
          );
        }
      } catch (err: any) {
        if (requestId === searchRequestIdRef.current) {
          setDirectoryError(
            err.message ||
              "Unable to reach FastAPI Postcode Registry. Postcode exploration is managed exclusively by FastAPI to prevent split-brain datasets."
          );
          setDirectoryItems([]);
          setDirectorySourceInfo(strictLookup ? "Strict Mode: Fail-Closed Enforced" : "Registry Service Unavailable");
        }
      } finally {
        if (requestId === searchRequestIdRef.current) {
          setIsLoadingDirectory(false);
        }
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [searchQuery, selectedState, strictLookup]);

  // Address Cleanser Callback
  const handleCleanse = useCallback(
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

  // Coverage Fetch Callback
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

  const statesList = [
    "All", "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue",
    "Borno", "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu", "Abuja FCT",
    "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi", "Kogi", "Kwara",
    "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo", "Osun", "Oyo", "Plateau", "Rivers",
    "Sokoto", "Taraba", "Yobe", "Zamfara",
  ];

  return (
    <div style={{ background: "#ffffff", borderRadius: "12px", border: "1px solid #e2e8f0", overflow: "hidden" }}>
      {/* Tab Navigation */}
      <div style={{ display: "flex", borderBottom: "1px solid #e2e8f0", background: "#f8fafc" }}>
        <button
          type="button"
          onClick={() => setActiveSubTab("directory")}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "8px",
            padding: "12px 18px",
            fontSize: "13px",
            fontWeight: 700,
            border: "none",
            borderBottom: activeSubTab === "directory" ? "2px solid #0284c7" : "2px solid transparent",
            background: activeSubTab === "directory" ? "#ffffff" : "transparent",
            color: activeSubTab === "directory" ? "#0284c7" : "#64748b",
            cursor: "pointer",
          }}
        >
          <MapPin size={15} /> Postcode Registry
        </button>
        <button
          type="button"
          onClick={() => setActiveSubTab("cleanser")}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "8px",
            padding: "12px 18px",
            fontSize: "13px",
            fontWeight: 700,
            border: "none",
            borderBottom: activeSubTab === "cleanser" ? "2px solid #0284c7" : "2px solid transparent",
            background: activeSubTab === "cleanser" ? "#ffffff" : "transparent",
            color: activeSubTab === "cleanser" ? "#0284c7" : "#64748b",
            cursor: "pointer",
          }}
        >
          <Sparkles size={15} /> Address Cleanser & Normaliser
        </button>
        <button
          type="button"
          onClick={() => {
            setActiveSubTab("coverage");
            if (!coverageReport && !isLoadingCoverage) {
              fetchCoverageReport();
            }
          }}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "8px",
            padding: "12px 18px",
            fontSize: "13px",
            fontWeight: 700,
            border: "none",
            borderBottom: activeSubTab === "coverage" ? "2px solid #0284c7" : "2px solid transparent",
            background: activeSubTab === "coverage" ? "#ffffff" : "transparent",
            color: activeSubTab === "coverage" ? "#0284c7" : "#64748b",
            cursor: "pointer",
          }}
        >
          <Database size={15} /> Coverage & Upstream Readiness
        </button>
      </div>

      {/* Subtab Content */}
      {activeSubTab === "directory" && (
        <PostcodeDirectory
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
          selectedState={selectedState}
          setSelectedState={setSelectedState}
          strictLookup={strictLookup}
          setStrictLookup={setStrictLookup}
          directoryItems={directoryItems}
          isLoadingDirectory={isLoadingDirectory}
          directoryError={directoryError}
          directorySourceInfo={directorySourceInfo}
          copiedCode={copiedCode}
          onCopyCode={handleCopyCode}
          onApplyPostcode={onApplyPostcode}
          statesList={statesList}
        />
      )}

      {activeSubTab === "cleanser" && (
        <AddressCleanser
          rawAddressInput={rawAddressInput}
          setRawAddressInput={setRawAddressInput}
          stateHint={stateHint}
          setStateHint={setStateHint}
          areaHint={areaHint}
          setAreaHint={setAreaHint}
          postcodeHint={postcodeHint}
          setPostcodeHint={setPostcodeHint}
          verificationMode={verificationMode}
          setVerificationMode={setVerificationMode}
          isCleansing={isCleansing}
          cleanseResult={cleanseResult}
          cleanseError={cleanseError}
          copiedStandardized={copiedStandardized}
          copiedJson={copiedJson}
          onCleanse={handleCleanse}
          onCopyStandardized={handleCopyStandardized}
          onCopyJson={handleCopyJson}
          onApplyPostcode={onApplyPostcode}
          onStartDeliveryWithAddress={onStartDeliveryWithAddress}
        />
      )}

      {activeSubTab === "coverage" && (
        <CoverageDashboard
          coverageReport={coverageReport}
          isLoadingCoverage={isLoadingCoverage}
          coverageError={coverageError}
          onRefresh={fetchCoverageReport}
        />
      )}
    </div>
  );
};
