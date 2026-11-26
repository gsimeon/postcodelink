import React from "react";
import { CheckCircle2, ShieldAlert, AlertTriangle, FileQuestion, XCircle } from "lucide-react";

interface VerificationStatusBadgeProps {
  status?: string;
  isLiveNipost?: boolean;
  isPartial?: boolean;
  evidenceId?: string | null;
  validUntil?: string | null;
  fallbackUsed?: boolean;
}

export function isOfficiallyVerifiedEvidence({
  status,
  isLiveNipost,
  isPartial,
  fallbackUsed,
  evidenceId,
  validUntil,
}: VerificationStatusBadgeProps): boolean {
  const hasOfficialStatus =
    status === "official_verified" ||
    status === "officially_verified" ||
    status === "nipost_verified";
  if (!hasOfficialStatus || isLiveNipost !== true || isPartial || fallbackUsed) {
    return false;
  }
  if (!evidenceId || !evidenceId.trim()) {
    return false;
  }
  if (!validUntil || !validUntil.trim()) {
    return false;
  }
  const expiresMs = Date.parse(validUntil);
  if (Number.isNaN(expiresMs) || expiresMs <= Date.now()) {
    return false;
  }
  return true;
}

export const VerificationStatusBadge: React.FC<VerificationStatusBadgeProps> = ({
  status,
  isLiveNipost,
  isPartial,
  evidenceId,
  validUntil,
  fallbackUsed,
}) => {
  // 1. Officially Verified: fail-closed check requiring official status, live provider, non-empty evidenceId, and valid unexpired validUntil
  if (
    isOfficiallyVerifiedEvidence({
      status,
      isLiveNipost,
      isPartial,
      fallbackUsed,
      evidenceId,
      validUntil,
    })
  ) {
    return (
      <span
        title="Live authoritative evidence supports the claim"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "4px",
          padding: "3px 8px",
          borderRadius: "4px",
          fontSize: "11px",
          fontWeight: 700,
          background: "#ecfdf5",
          color: "#059669",
          border: "1px solid #a7f3d0",
        }}
      >
        <CheckCircle2 size={12} /> OFFICIALLY VERIFIED
      </span>
    );
  }

  // 2. Partially Verified: Existence confirmed, metadata incomplete
  if (
    status === "partially_verified" ||
    status === "partial_verification" ||
    status === "partial" ||
    (isLiveNipost && isPartial)
  ) {
    return (
      <span
        title="Existence confirmed, metadata incomplete"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "4px",
          padding: "3px 8px",
          borderRadius: "4px",
          fontSize: "11px",
          fontWeight: 700,
          background: "#eff6ff",
          color: "#2563eb",
          border: "1px solid #bfdbfe",
        }}
      >
        <CheckCircle2 size={12} /> PARTIALLY VERIFIED
      </span>
    );
  }

  // 3. Address Conflict: Supplied address conflicts with available evidence
  if (status === "address_conflict" || status === "conflict") {
    return (
      <span
        title="Supplied address conflicts with available evidence"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "4px",
          padding: "3px 8px",
          borderRadius: "4px",
          fontSize: "11px",
          fontWeight: 700,
          background: "#faf5ff",
          color: "#9333ea",
          border: "1px solid #e9d5ff",
        }}
      >
        <ShieldAlert size={12} /> ADDRESS CONFLICT
      </span>
    );
  }

  // 4. Local Reference Match: Matched against PostcodeLink's own dataset
  if (status === "local_reference" || status === "local_match") {
    return (
      <span
        title="Matched against PostcodeLink's own reference dataset"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "4px",
          padding: "3px 8px",
          borderRadius: "4px",
          fontSize: "11px",
          fontWeight: 600,
          background: "#fffbeb",
          color: "#b45309",
          border: "1px solid #fde68a",
        }}
      >
        <AlertTriangle size={12} /> LOCAL REFERENCE MATCH
      </span>
    );
  }

  // 5. Not Found vs Unavailable
  if (status === "not_found") {
    return (
      <span
        title="Postcode does not exist in registry or local dataset"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "4px",
          padding: "3px 8px",
          borderRadius: "4px",
          fontSize: "11px",
          fontWeight: 600,
          background: "#fef2f2",
          color: "#dc2626",
          border: "1px solid #fecaca",
        }}
      >
        <XCircle size={12} /> POSTCODE NOT FOUND
      </span>
    );
  }

  return (
    <span
      title="No reliable verification result could be obtained"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "4px",
        padding: "3px 8px",
        borderRadius: "4px",
        fontSize: "11px",
        fontWeight: 600,
        background: "#f1f5f9",
        color: "#64748b",
        border: "1px solid #e2e8f0",
      }}
    >
      <FileQuestion size={12} /> VERIFICATION UNAVAILABLE
    </span>
  );
};

