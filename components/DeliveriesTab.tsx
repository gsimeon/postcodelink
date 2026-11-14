"use client";

import React, { useState, useMemo } from "react";
import { Delivery, DeliveryStatus, Operator, AppSettings } from "@/lib/types";
import {
  Search,
  Plus,
  ArrowDownToLine,
  Filter,
  CheckCircle2,
  Clock,
  Truck,
  Printer,
  ChevronRight,
  ShieldCheck,
  AlertTriangle,
  Trash2,
  Eye,
  MessageCircle,
  Upload,
  Key
} from "lucide-react";
import { DeliveryDetailModal } from "./DeliveryDetailModal";
import { WaybillModal } from "./WaybillModal";
import { WhatsAppModal } from "./WhatsAppModal";
import { BulkImportModal } from "./BulkImportModal";

interface DeliveriesTabProps {
  deliveries: Delivery[];
  operators: Operator[];
  settings: AppSettings;
  onOpenCreate: () => void;
  onBulkImport: (newDeliveries: Delivery[]) => void;
  onUpdateStatus: (deliveryId: string, newStatus: DeliveryStatus, note: string) => void;
  onAssignOperator: (deliveryId: string, operatorId: string, operatorName: string) => void;
  onDeleteDelivery: (deliveryId: string) => void;
}

export function DeliveriesTab({
  deliveries,
  operators,
  settings,
  onOpenCreate,
  onBulkImport,
  onUpdateStatus,
  onAssignOperator,
  onDeleteDelivery,
}: DeliveriesTabProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [stateFilter, setStateFilter] = useState<string>("all");
  const [operatorFilter, setOperatorFilter] = useState<string>("all");
  const [selectedDelivery, setSelectedDelivery] = useState<Delivery | null>(null);
  const [waybillDelivery, setWaybillDelivery] = useState<Delivery | null>(null);
  const [whatsAppDelivery, setWhatsAppDelivery] = useState<Delivery | null>(null);
  const [showBulkModal, setShowBulkModal] = useState(false);

  const filtered = useMemo(() => {
    return deliveries.filter((d) => {
      // Search
      const text = [
        d.id,
        d.recipientName,
        d.recipientPhone,
        d.destinationAddress,
        d.destinationArea,
        d.destinationState,
        d.landmark || "",
        d.operatorName || "",
        d.verifiedPostcode || "",
        d.otp || "",
      ]
        .join(" ")
        .toLowerCase();
      if (searchQuery.trim() && !text.includes(searchQuery.toLowerCase())) {
        return false;
      }
      // Status
      if (statusFilter !== "all" && d.status !== statusFilter) {
        return false;
      }
      // State
      if (stateFilter !== "all" && d.destinationState.toLowerCase() !== stateFilter.toLowerCase()) {
        return false;
      }
      // Operator
      if (operatorFilter !== "all") {
        if (operatorFilter === "unassigned" && d.operatorId) return false;
        if (operatorFilter !== "unassigned" && d.operatorId !== operatorFilter) return false;
      }
      return true;
    });
  }, [deliveries, searchQuery, statusFilter, stateFilter, operatorFilter]);

  const statusColors: Record<DeliveryStatus, string> = {
    draft: "gray",
    pending: "amber",
    pending_assignment: "amber",
    assigned: "blue",
    picked_up: "blue",
    in_transit: "blue",
    out_for_delivery: "blue",
    delivered: "green",
    failed: "red",
    cancelled: "red",
  };

  const handleExportCSV = () => {
    const headers = [
      "ID",
      "Recipient",
      "Phone",
      "Address",
      "Area",
      "State",
      "Postcode",
      "PostcodeStatus",
      "Operator",
      "Status",
      "Fee_NGN",
      "OTP",
      "Created",
    ];
    const rows = filtered.map((d) => [
      d.id,
      `"${d.recipientName}"`,
      `"${d.recipientPhone}"`,
      `"${d.destinationAddress}"`,
      `"${d.destinationArea}"`,
      `"${d.destinationState}"`,
      `"${d.verifiedPostcode || d.postcodeInput}"`,
      d.postcodeStatus,
      `"${d.operatorName || ""}"`,
      d.status,
      d.fee || 0,
      d.otp || "",
      `"${d.createdAt}"`,
    ]);
    const csvContent =
      "data:text/csv;charset=utf-8," +
      [headers.join(","), ...rows.map((e) => e.join(","))].join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `postcodelink_deliveries_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Deliveries Management Hub</h2>
            <p>
              Monitor dispatch lifecycles, view routing codes, and assign logistics operators across Nigeria.
            </p>
          </div>
          <div className="btn-group">
            <button type="button" className="outline" onClick={() => setShowBulkModal(true)}>
              <Upload size={14} /> Bulk Batch Import
            </button>
            <button type="button" className="outline" onClick={handleExportCSV}>
              <ArrowDownToLine size={14} /> Export CSV
            </button>
            <button type="button" className="primary" onClick={onOpenCreate}>
              <Plus size={14} /> Create Delivery
            </button>
          </div>
        </div>

        {/* Status Filter Tabs */}
        <div style={{ display: "flex", gap: "8px", overflowX: "auto", paddingBottom: "8px", marginBottom: "14px" }}>
          {[
            { key: "all", label: "All Deliveries", count: deliveries.length },
            {
              key: "pending_assignment",
              label: "Awaiting Dispatch",
              count: deliveries.filter((d) => d.status === "pending_assignment").length,
            },
            {
              key: "assigned",
              label: "Assigned",
              count: deliveries.filter((d) => d.status === "assigned").length,
            },
            {
              key: "in_transit",
              label: "In Transit",
              count: deliveries.filter((d) => d.status === "in_transit").length,
            },
            {
              key: "delivered",
              label: "Delivered",
              count: deliveries.filter((d) => d.status === "delivered").length,
            },
          ].map((tab) => (
            <button
              key={tab.key}
              type="button"
              className={`pill ${statusFilter === tab.key ? "blue" : "gray"}`}
              style={{ cursor: "pointer", border: "none", fontSize: "12px", padding: "6px 12px" }}
              onClick={() => setStatusFilter(tab.key)}
            >
              {tab.label} <b style={{ marginLeft: "4px" }}>({tab.count})</b>
            </button>
          ))}
        </div>

        {/* Search & Select Filters */}
        <div className="filters">
          <div className="search">
            <Search size={16} />
            <input
              type="text"
              placeholder="Search by recipient, phone, area, postcode, or reference..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          <select
            className="select-filter"
            value={stateFilter}
            onChange={(e) => setStateFilter(e.target.value)}
          >
            <option value="all">All States</option>
            <option value="Lagos">Lagos</option>
            <option value="Abuja (FCT)">Abuja (FCT)</option>
            <option value="Rivers">Rivers</option>
            <option value="Oyo">Oyo</option>
            <option value="Kano">Kano</option>
            <option value="Kaduna">Kaduna</option>
            <option value="Enugu">Enugu</option>
          </select>

          <select
            className="select-filter"
            value={operatorFilter}
            onChange={(e) => setOperatorFilter(e.target.value)}
          >
            <option value="all">All Operators</option>
            <option value="unassigned">Unassigned Only</option>
            {operators.map((op) => (
              <option key={op.id} value={op.id}>
                {op.businessName}
              </option>
            ))}
          </select>
        </div>

        {/* Deliveries Table */}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>REF / ID</th>
                <th>RECIPIENT</th>
                <th>DESTINATION & POSTCODE</th>
                <th>PACKAGE / FEE</th>
                <th>OPERATOR</th>
                <th>PIN (OTP)</th>
                <th>STATUS</th>
                <th>ACTIONS</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((d) => (
                <tr key={d.id}>
                  <td>
                    <button
                      type="button"
                      style={{
                        background: "transparent",
                        border: "none",
                        padding: 0,
                        cursor: "pointer",
                        textAlign: "left",
                      }}
                      onClick={() => setSelectedDelivery(d)}
                    >
                      <b className="ref" style={{ fontSize: "12px" }}>
                        {d.id}
                      </b>
                      <small>{d.createdAt}</small>
                    </button>
                  </td>

                  <td>
                    <b style={{ fontSize: "12px" }}>{d.recipientName}</b>
                    <small>{d.recipientPhone}</small>
                  </td>

                  <td>
                    <div style={{ maxWidth: "260px", whiteSpace: "normal" }}>
                      <b style={{ fontSize: "12px" }}>{d.destinationAddress}</b>
                      {d.landmark && (
                        <div style={{ fontSize: "10px", color: "#166534", marginTop: "1px" }}>
                          Landmark: {d.landmark}
                        </div>
                      )}
                      <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                        <span style={{ fontSize: "11px", color: "#64748b" }}>
                          {d.destinationArea}, {d.destinationState}
                        </span>
                        {d.postcodeStatus === "verified" ? (
                          <span className="postcode-badge verified">
                            <ShieldCheck size={10} /> NG-{d.verifiedPostcode}
                          </span>
                        ) : (
                          <span className="postcode-badge unverified">
                            <AlertTriangle size={10} /> Unverified
                          </span>
                        )}
                      </div>
                    </div>
                  </td>

                  <td>
                    <div style={{ fontSize: "12px", color: "var(--ink)", fontWeight: 500 }}>
                      {d.packageDescription || "Parcel"}
                    </div>
                    <small style={{ color: "#0f766e", fontWeight: 600 }}>
                      {d.fee ? `₦${d.fee.toLocaleString()}` : "Free"}
                    </small>
                  </td>

                  <td>
                    {d.operatorName && d.operatorName !== "Not assigned" ? (
                      <div>
                        <b style={{ fontSize: "12px" }}>{d.operatorName}</b>
                        <small>Active dispatch</small>
                      </div>
                    ) : (
                      <span className="pill amber" style={{ fontSize: "10px" }}>
                        Needs Rider
                      </span>
                    )}
                  </td>

                  <td>
                    <span
                      style={{
                        fontFamily: "'JetBrains Mono', monospace",
                        fontSize: "11px",
                        background: d.podVerified ? "#dcfce7" : "#f1f5f9",
                        color: d.podVerified ? "#15803d" : "#475569",
                        padding: "2px 6px",
                        borderRadius: "4px",
                        fontWeight: 700,
                      }}
                    >
                      {d.otp || "4821"}
                    </span>
                  </td>

                  <td>
                    <span className={`pill ${statusColors[d.status]}`}>
                      <i /> {d.status.replace("_", " ")}
                    </span>
                  </td>

                  <td>
                    <div style={{ display: "flex", gap: "5px" }}>
                      <button
                        type="button"
                        className="outline"
                        style={{ height: "30px", padding: "0 8px", fontSize: "11px" }}
                        title="View Full History & Tracking"
                        onClick={() => setSelectedDelivery(d)}
                      >
                        <Eye size={13} />
                      </button>
                      <button
                        type="button"
                        className="outline"
                        style={{ height: "30px", padding: "0 8px", fontSize: "11px", color: "#16a34a" }}
                        title="Share on WhatsApp"
                        onClick={() => setWhatsAppDelivery(d)}
                      >
                        <MessageCircle size={13} />
                      </button>
                      <button
                        type="button"
                        className="outline"
                        style={{ height: "30px", padding: "0 8px", fontSize: "11px" }}
                        title="Print Waybill"
                        onClick={() => setWaybillDelivery(d)}
                      >
                        <Printer size={13} />
                      </button>
                      <button
                        type="button"
                        className="outline"
                        style={{ height: "30px", padding: "0 8px", fontSize: "11px", color: "#dc2626" }}
                        title="Delete record"
                        onClick={() => {
                          if (confirm(`Delete delivery record ${d.id}?`)) {
                            onDeleteDelivery(d.id);
                          }
                        }}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}

              {filtered.length === 0 && (
                <tr>
                  <td colSpan={8} className="empty">
                    No deliveries match the selected filters or search terms.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="table-foot">
          Showing {filtered.length} of {deliveries.length} total deliveries
          <span>PostcodeLink Dispatch Engine</span>
        </div>
      </section>

      {/* Details, Waybill, WhatsApp, and Bulk Modals */}
      {selectedDelivery && (
        <DeliveryDetailModal
          delivery={selectedDelivery}
          operators={operators}
          settings={settings}
          onClose={() => setSelectedDelivery(null)}
          onUpdateStatus={(id, st, note) => {
            onUpdateStatus(id, st, note);
            const updated = deliveries.find((x) => x.id === id);
            if (updated) setSelectedDelivery({ ...updated, status: st });
          }}
          onAssignOperator={(id, opId, opName) => {
            onAssignOperator(id, opId, opName);
            const updated = deliveries.find((x) => x.id === id);
            if (updated) setSelectedDelivery({ ...updated, operatorId: opId, operatorName: opName });
          }}
        />
      )}

      {waybillDelivery && (
        <WaybillModal
          delivery={waybillDelivery}
          settings={settings}
          onClose={() => setWaybillDelivery(null)}
        />
      )}

      {whatsAppDelivery && (
        <WhatsAppModal
          delivery={whatsAppDelivery}
          settings={settings}
          onClose={() => setWhatsAppDelivery(null)}
        />
      )}

      {showBulkModal && (
        <BulkImportModal
          operators={operators}
          onClose={() => setShowBulkModal(false)}
          onImport={(newItems) => {
            onBulkImport(newItems);
            setShowBulkModal(false);
          }}
        />
      )}
    </div>
  );
}
