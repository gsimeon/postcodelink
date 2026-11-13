"use client";

import React, { useState, useEffect } from "react";
import {
  Delivery,
  Operator,
  Customer
} from "@/lib/types";
import {
  NIGERIA_POSTCODES,
  STATES_LIST,
  getLgasForState,
  cleanseAndStandardizeAddress,
  lookupPostcode
} from "@/lib/nigeria-postcodes";
import {
  X,
  MapPin,
  CheckCircle2,
  Sparkles,
  ArrowRight,
  ShieldCheck,
  AlertCircle
} from "lucide-react";

interface CreateDeliveryModalProps {
  operators: Operator[];
  customers: Customer[];
  onClose: () => void;
  onSave: (delivery: Delivery) => void;
  initialAddress?: string;
  initialPostcode?: string;
}

export function CreateDeliveryModal({
  operators,
  customers,
  onClose,
  onSave,
  initialAddress = "",
  initialPostcode = "",
}: CreateDeliveryModalProps) {
  const [recipientName, setRecipientName] = useState("");
  const [recipientPhone, setRecipientPhone] = useState("+234 ");
  const [destinationAddress, setDestinationAddress] = useState(initialAddress);
  const [landmark, setLandmark] = useState("");
  const [state, setState] = useState("Lagos");
  const [lga, setLga] = useState("Eti-Osa");
  const [area, setArea] = useState("Lekki Phase 1");
  const [postcode, setPostcode] = useState(initialPostcode || "105102");
  const [packageDescription, setPackageDescription] = useState("Parcel (Standard)");
  const [fee, setFee] = useState<number>(3500);
  const [operatorId, setOperatorId] = useState("");
  const [isVerified, setIsVerified] = useState(true);
  const [errorMsg, setErrorMsg] = useState("");
  const [resolutionNote, setResolutionNote] = useState("");

  const lgas = getLgasForState(state);
  const areasInState = NIGERIA_POSTCODES.filter(
    (p) => p.state.toLowerCase() === state.toLowerCase()
  );

  // Auto-detect postcode when address or area changes
  useEffect(() => {
    if (destinationAddress.trim().length > 6) {
      const analysis = cleanseAndStandardizeAddress(destinationAddress);
      if (analysis.matchedPostcode) {
        setPostcode(analysis.matchedPostcode);
        setIsVerified(true);
        if (analysis.detectedState) setState(analysis.detectedState);
        if (analysis.detectedLga) setLga(analysis.detectedLga);
        if (analysis.detectedArea) setArea(analysis.detectedArea);
        setResolutionNote(`Matched NIPOST 6-digit code ${analysis.matchedPostcode} for ${analysis.detectedArea}`);
      }
    }
  }, [destinationAddress]);

  // Handle area change
  const handleAreaChange = (selectedArea: string) => {
    setArea(selectedArea);
    const found = NIGERIA_POSTCODES.find(
      (p) =>
        p.districtOrArea.toLowerCase() === selectedArea.toLowerCase() &&
        p.state.toLowerCase() === state.toLowerCase()
    );
    if (found) {
      setPostcode(found.postcode);
      setLga(found.lga);
      setIsVerified(true);
      setResolutionNote(`Official NIPOST code ${found.postcode} (${found.zone} zone)`);
    }
  };

  // Handle manual postcode entry
  const handlePostcodeChange = (code: string) => {
    setPostcode(code);
    const clean = code.trim();
    if (clean.length === 6 && /^\d+$/.test(clean)) {
      const match = lookupPostcode(clean);
      if (match) {
        setIsVerified(true);
        setState(match.state);
        setLga(match.lga);
        setArea(match.districtOrArea);
        setResolutionNote(`Verified NIPOST code for ${match.districtOrArea}, ${match.state}`);
      } else {
        setIsVerified(false);
        setResolutionNote("Custom 6-digit code outside primary digitized registry. Address stored as unverified.");
      }
    } else {
      setIsVerified(false);
    }
  };

  const handleSelectCustomer = (customerId: string) => {
    const cust = customers.find((c) => c.id === customerId);
    if (cust) {
      setRecipientName(cust.fullName);
      setRecipientPhone(cust.phone);
      setDestinationAddress(cust.defaultAddress);
      setArea(cust.area);
      setState(cust.state);
      setPostcode(cust.postcode);
      setIsVerified(true);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!recipientName.trim()) {
      setErrorMsg("Please enter the recipient's name.");
      return;
    }
    if (!destinationAddress.trim()) {
      setErrorMsg("Please enter the destination delivery address.");
      return;
    }

    const assignedOperator = operators.find((op) => op.id === operatorId);
    const deliveryId = `PL-${Math.floor(2050 + Math.random() * 800)}`;

    const newDelivery: Delivery = {
      id: deliveryId,
      recipientName: recipientName.trim(),
      recipientPhone: recipientPhone.trim(),
      destinationAddress: destinationAddress.trim(),
      landmark: landmark.trim() || undefined,
      destinationArea: area || "General District",
      destinationCity: state === "Abuja (FCT)" ? "Abuja" : state,
      destinationState: state,
      postcodeInput: postcode.trim(),
      postcodeStatus: isVerified && postcode.trim() ? "verified" : "unverified",
      verifiedPostcode: isVerified && postcode.trim() ? postcode.trim() : undefined,
      packageDescription: packageDescription.trim(),
      fee: Number(fee) || 0,
      operatorId: assignedOperator ? assignedOperator.id : undefined,
      operatorName: assignedOperator ? assignedOperator.businessName : "Not assigned",
      status: assignedOperator ? "assigned" : "pending_assignment",
      createdAt: "Just now",
      updatedAt: "Just now",
      events: [
        {
          id: `ev-${Date.now()}`,
          deliveryId,
          status: "draft",
          actor: "Merchant Admin",
          actorRole: "merchant",
          note: isVerified
            ? `Created with verified NIPOST postcode NG-${postcode}`
            : "Created with manual address fallback (unverified postcode)",
          timestamp: "Just now",
        },
        ...(assignedOperator
          ? [
              {
                id: `ev-${Date.now() + 1}`,
                deliveryId,
                status: "assigned" as const,
                actor: "Auto Dispatch",
                actorRole: "system" as const,
                note: `Assigned to ${assignedOperator.businessName} (${assignedOperator.vehicleType})`,
                timestamp: "Just now",
              },
            ]
          : []),
      ],
    };

    onSave(newDelivery);
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal large" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <p className="eyebrow">NEW DISPATCH</p>
            <h2>Create Delivery Order</h2>
            <p className="sub">
              PostcodeLink validates Nigerian digital postcodes to reduce rider calls and missed deliveries.
            </p>
          </div>
          <button type="button" className="icon-btn" onClick={onClose}>
            <X size={17} />
          </button>
        </div>

        {errorMsg && (
          <div
            style={{
              background: "#fee2e2",
              border: "1px solid #fecaca",
              color: "#991b1b",
              padding: "10px 14px",
              borderRadius: "6px",
              fontSize: "12px",
              marginBottom: "16px",
              display: "flex",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <AlertCircle size={15} /> {errorMsg}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          {/* Quick autofill from customer address book */}
          {customers.length > 0 && (
            <div style={{ marginBottom: "16px" }}>
              <label style={{ fontSize: "11px", color: "#64748b", fontWeight: 600, display: "block", marginBottom: "4px" }}>
                Autofill from saved customers (optional):
              </label>
              <select
                className="select-filter"
                style={{ width: "100%" }}
                onChange={(e) => handleSelectCustomer(e.target.value)}
                defaultValue=""
              >
                <option value="">-- Choose saved customer or type below --</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.fullName} · {c.area}, {c.state} ({c.phone})
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="form-grid">
            {/* Recipient Details */}
            <div className="form-group">
              <label>Recipient Full Name *</label>
              <input
                type="text"
                required
                placeholder="e.g. Chukwudi Adeleke"
                value={recipientName}
                onChange={(e) => setRecipientName(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>Recipient Phone Number *</label>
              <input
                type="text"
                required
                placeholder="+234 803 000 0000"
                value={recipientPhone}
                onChange={(e) => setRecipientPhone(e.target.value)}
              />
            </div>

            <div className="form-group full">
              <label>Destination Address (Street, Building, Landmark) *</label>
              <input
                type="text"
                required
                placeholder="e.g. 14 Admiralty Way, Opp. Ebeano Supermarket, Lekki Phase 1"
                value={destinationAddress}
                onChange={(e) => setDestinationAddress(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>Prominent Landmark (for Dispatch Rider)</label>
              <input
                type="text"
                placeholder="e.g. Opposite Yellow Gate, Beside Total filling station"
                value={landmark}
                onChange={(e) => setLandmark(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>State *</label>
              <select
                value={state}
                onChange={(e) => {
                  setState(e.target.value);
                  const firstArea = NIGERIA_POSTCODES.find((p) => p.state === e.target.value);
                  if (firstArea) {
                    handleAreaChange(firstArea.districtOrArea);
                  }
                }}
              >
                {STATES_LIST.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>Area / District *</label>
              <select
                value={area}
                onChange={(e) => handleAreaChange(e.target.value)}
              >
                {areasInState.map((a) => (
                  <option key={a.districtOrArea} value={a.districtOrArea}>
                    {a.districtOrArea} (NG-{a.postcode})
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>
                National Postcode (6 digits)
                {isVerified ? (
                  <span style={{ color: "#16a34a", marginLeft: "6px", fontSize: "11px" }}>
                    ✓ Verified
                  </span>
                ) : (
                  <span style={{ color: "#d97706", marginLeft: "6px", fontSize: "11px" }}>
                    Manual / Unverified
                  </span>
                )}
              </label>
              <input
                type="text"
                placeholder="e.g. 105102"
                maxLength={6}
                value={postcode}
                onChange={(e) => handlePostcodeChange(e.target.value)}
              />
            </div>
          </div>

          {/* Postcode Intelligence Feedback */}
          {resolutionNote && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "10px 14px",
                background: isVerified ? "#f0fdf4" : "#fffbeb",
                border: `1px solid ${isVerified ? "#bbf7d0" : "#fef3c7"}`,
                borderRadius: "6px",
                color: isVerified ? "#166534" : "#92400e",
                fontSize: "11px",
                margin: "4px 0 16px",
              }}
            >
              {isVerified ? <ShieldCheck size={16} /> : <AlertCircle size={16} />}
              <span>{resolutionNote}</span>
            </div>
          )}

          {/* Package & Dispatch Assignment */}
          <div className="form-grid">
            <div className="form-group">
              <label>Package Description</label>
              <input
                type="text"
                placeholder="e.g. Electronics, Clothing, Documents"
                value={packageDescription}
                onChange={(e) => setPackageDescription(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>Delivery Fee (₦ NGN)</label>
              <input
                type="number"
                min="0"
                step="100"
                value={fee}
                onChange={(e) => setFee(Number(e.target.value))}
              />
            </div>

            <div className="form-group full">
              <label>Assign Logistics Partner (Optional)</label>
              <select
                value={operatorId}
                onChange={(e) => setOperatorId(e.target.value)}
              >
                <option value="">-- Leave Unassigned (Dispatch Later) --</option>
                {operators.map((op) => (
                  <option key={op.id} value={op.id}>
                    {op.businessName} ({op.vehicleType}) · {op.serviceAreas.slice(0, 2).join(", ")} · {op.isAvailable ? "Available" : "Busy"}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="lookup-info">
            <MapPin size={17} style={{ flexShrink: 0 }} />
            <div>
              <b>NIPOST Digital Routing Enabled</b>
              <small>
                {isVerified
                  ? "Destination successfully resolved to official NIPOST delivery office. Routing code will print on the consignment slip."
                  : "Postcode unverified. The order will be created with manual delivery instructions so logistics riders can navigate via landmarks."}
              </small>
            </div>
          </div>

          <div className="modal-actions">
            <button type="button" className="outline" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="primary">
              Create Delivery Order <ArrowRight size={15} />
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

