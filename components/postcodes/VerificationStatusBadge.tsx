import React from "react";
import { CheckCircle2, ShieldAlert, AlertTriangle, FileQuestion } from "lucide-react";

interface VerificationStatusBadgeProps {
  status?: string;
  isLiveNipost?: boolean;
  isPartial?: boolean;
}

export const VerificationStatusBadge: React.FC<VerificationStatusBadgeProps> = ({
  status,
  isLiveNipost,
  isPartial,
}) => {
  if (status === "official_verified" || (isLiveNipost && !isPartial)) {
    return (
      <span
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
        <CheckCircle2 size={12} /> NIPOST VERIFIED
      </span>
    );
  }

  if (status === "partially_verified" || (isLiveNipost && isPartial)) {
    return (
      <span
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
        <CheckCircle2 size={12} /> EXISTENCE VERIFIED (VALIDATOR)
      </span>
    );
  }

  if (status === "local_reference") {
    return (
      <span
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
        <AlertTriangle size={12} /> LOCAL REFERENCE
      </span>
    );
  }

  return (
    <span
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
      <FileQuestion size={12} /> UNVERIFIED
    </span>
  );
};
