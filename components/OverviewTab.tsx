"use client";

import React, { useState, useMemo } from "react";
import { Delivery, DeliveryStatus, Operator, AppSettings } from "@/lib/types";
import {
  Package,
  Truck,
  Clock3,
  CheckCircle2,
  Plus,
  Search,
  Settings2,
  ArrowDownToLine,
  MapPin,
  XCircle,
  Eye,
  ShieldCheck,
  AlertTriangle,
  ArrowRight,
  Sparkles
} from "lucide-react";
import { DeliveryDetailModal } from "./DeliveryDetailModal";
import { FastAPIProfile } from "@/lib/fastapi-client";

interface OverviewTabProps {
  deliveries: Delivery[];
  operators: Operator[];
  settings: AppSettings;
  profile?: FastAPIProfile | null;
  onOpenCreate: () => void;
  onNavigateTab: (tab: "deliveries" | "postcodes" | "operators" | "settings") => void;
  onUpdateStatus: (deliveryId: string, newStatus: DeliveryStatus, note: string) => void;
  onAssignOperator: (deliveryId: string, operatorId: string, operatorName: string) => void;
  notice: string;
}

export function OverviewTab({
  deliveries,
  operators,
  settings,
  profile,
  onOpenCreate,
  onNavigateTab,
  onUpdateStatus,
  onAssignOperator,
  notice,
}: OverviewTabProps) {
  const [query, setQuery] = useState("");
  const [selectedDelivery, setSelectedDelivery] = useState<Delivery | null>(null);

  const filtered = useMemo(() => {
    return deliveries.filter((d) =>
      [d.id, d.recipientName, d.destinationArea, d.status, d.destinationState, d.operatorName || ""]
        .join(" ")
        .toLowerCase()
        .includes(query.toLowerCase())
    );
  }, [deliveries, query]);

  const count = (status: DeliveryStatus) =>
    deliveries.filter((d) => d.status === status).length;

  const inTransitCount = count("in_transit");
  const pendingCount = count("pending_assignment");
  const deliveredCount = count("delivered");
  const verifiedCount = deliveries.filter((d) => d.postcodeStatus === "verified").length;
  const verifiedRate = deliveries.length > 0 ? Math.round((verifiedCount / deliveries.length) * 100) : 100;

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

  return (
    <div>
      {/* Welcome Banner */}
      <div className="welcome">
        <div>
          <p className="eyebrow">
            {new Date()
              .toLocaleDateString("en-US", {
                weekday: "long",
                month: "long",
                day: "numeric",
                year: "numeric",
              })
              .toUpperCase()}
          </p>
          <h1>
            Good day, {profile?.full_name ? profile.full_name.split(" ")[0] : "Godwin"} <span>✦</span>
          </h1>
          <p className="sub">
            Monitoring deliveries, digital postcodes, and courier dispatches across Nigeria.
          </p>
        </div>
        <div className="btn-group">
          <button
            type="button"
            className="outline"
            onClick={() => onNavigateTab("postcodes")}
          >
            <Sparkles size={16} /> Clean Address
          </button>
          <button type="button" className="primary" onClick={onOpenCreate}>
            <Plus size={16} /> Create Delivery
          </button>
        </div>
      </div>

      {/* Notice Ribbon */}
      <div className="notice">
        <div className="notice-left">
          <span className="notice-dot" />
          <span>{notice}</span>
        </div>
        <button
          type="button"
          style={{
            background: "transparent",
            border: "none",
            color: "#0f766e",
            fontSize: "11px",
            fontWeight: 600,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: "4px",
          }}
          onClick={() => onNavigateTab("postcodes")}
        >
          Explore NIPOST Registry <ArrowRight size={13} />
        </button>
      </div>

      {/* Metric Cards */}
      <div className="metrics">
        <div className="metric">
          <div className="metric-top">
            <span>Total Deliveries</span>
            <i>
              <Package size={17} />
            </i>
          </div>
          <strong>{String(deliveries.length).padStart(2, "0")}</strong>
          <small>Active in workspace</small>
        </div>

        <div className="metric">
          <div className="metric-top">
            <span>In Transit</span>
            <i>
              <Truck size={17} />
            </i>
          </div>
          <strong style={{ color: "#2563eb" }}>
            {String(inTransitCount).padStart(2, "0")}
          </strong>
          <small>Dispatched & on the way</small>
        </div>

        <div className="metric">
          <div className="metric-top">
            <span>Awaiting Assignment</span>
            <i>
              <Clock3 size={17} />
            </i>
          </div>
          <strong style={{ color: pendingCount > 0 ? "#d97706" : "inherit" }}>
            {String(pendingCount).padStart(2, "0")}
          </strong>
          <small>Needs logistics partner</small>
        </div>

        <div className="metric">
          <div className="metric-top">
            <span>Verified Postcodes</span>
            <i>
              <ShieldCheck size={17} />
            </i>
          </div>
          <strong style={{ color: "#16a34a" }}>{verifiedRate}%</strong>
          <small>{verifiedCount} of {deliveries.length} standardized</small>
        </div>
      </div>

      {/* Recent Deliveries Panel */}
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Recent Deliveries</h2>
            <p>Real-time delivery progress, assigned couriers, and digital routing codes.</p>
          </div>
          <div className="btn-group">
            <button
              type="button"
              className="outline"
              onClick={() => onNavigateTab("deliveries")}
            >
              View All ({deliveries.length})
            </button>
            <button type="button" className="outline" onClick={onOpenCreate}>
              <Plus size={14} /> New Delivery
            </button>
          </div>
        </div>

        <div className="filters">
          <div className="search">
            <Search size={16} />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by recipient, reference, area or state..."
            />
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>DELIVERY REF</th>
                <th>RECIPIENT</th>
                <th>DESTINATION & POSTCODE</th>
                <th>OPERATOR</th>
                <th>STATUS</th>
                <th>CREATED</th>
                <th>ACTION</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 5).map((d) => (
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
                      <b className="ref">{d.id}</b>
                    </button>
                  </td>

                  <td>
                    <b>{d.recipientName}</b>
                    <small>{d.recipientPhone}</small>
                  </td>

                  <td>
                    <b style={{ fontSize: "12px" }}>{d.destinationArea}</b>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "2px" }}>
                      <span style={{ fontSize: "11px", color: "#64748b" }}>{d.destinationState}</span>
                      {d.postcodeStatus === "verified" ? (
                        <span className="postcode-badge verified">
                          NG-{d.verifiedPostcode}
                        </span>
                      ) : (
                        <span className="postcode-badge unverified">
                          Unverified
                        </span>
                      )}
                    </div>
                  </td>

                  <td>
                    {d.operatorName && d.operatorName !== "Not assigned" ? (
                      <div>
                        <b>{d.operatorName}</b>
                        <small>Courier</small>
                      </div>
                    ) : (
                      <span className="pill amber" style={{ fontSize: "10px" }}>
                        Unassigned
                      </span>
                    )}
                  </td>

                  <td>
                    <span className={`pill ${statusColors[d.status]}`}>
                      <i /> {d.status.replace("_", " ")}
                    </span>
                  </td>

                  <td>{d.createdAt}</td>

                  <td>
                    <button
                      type="button"
                      className="outline"
                      style={{ height: "30px", fontSize: "11px", padding: "0 10px" }}
                      onClick={() => setSelectedDelivery(d)}
                    >
                      <Eye size={13} /> View
                    </button>
                  </td>
                </tr>
              ))}
              {!filtered.length && (
                <tr>
                  <td colSpan={7} className="empty">
                    No deliveries match that search.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="table-foot">
          Showing {Math.min(5, filtered.length)} of {deliveries.length} deliveries
          <span>Data persists in this browser session and local storage.</span>
        </div>
      </section>

      {/* Bottom Status Grid */}
      <div className="bottom-grid">
        <section className="panel mini">
          <div className="mini-title">
            <div>
              <h2>Postcode Resolution Service</h2>
              <p>Address lookup integration status</p>
            </div>
            <span className={`tag ${settings.nipostMode === "live" ? "connected" : ""}`}>
              {settings.nipostMode === "live" ? "Live Connected" : "Local Registry (Active)"}
            </span>
          </div>

          <div className="service-row">
            <div className="service-icon">
              <MapPin size={20} />
            </div>
            <div>
              <b>NIPOST Digital Postcode Registry</b>
              <small>
                {settings.nipostMode === "mock"
                  ? "Operating with verified 6-digit postal codes for Lagos, Abuja, Rivers, Oyo, Kano, etc."
                  : `Connecting to ${settings.nipostApiBaseUrl || "Production API"}`}
              </small>
            </div>
          </div>

          <div
            className="service-note"
            style={{
              background: "#eff6ff",
              borderColor: "#bfdbfe",
              color: "#1e40af",
            }}
          >
            <ShieldCheck size={16} /> Official 6-digit structure active: [Zone] + [District] + [Delivery Office].
          </div>
        </section>

        <section className="panel mini">
          <div className="mini-title">
            <div>
              <h2>PostcodeLink Operations Readiness</h2>
              <p>MVP setup checklist</p>
            </div>
          </div>

          <div className="check-row">
            <CheckCircle2 size={16} /> Next.js 15 + React 19 Shell & State <span>Ready</span>
          </div>
          <div className="check-row">
            <CheckCircle2 size={16} /> NIPOST 6-digit Nigerian Postcode Registry <span>Active (30+ zones)</span>
          </div>
          <div className="check-row">
            <CheckCircle2 size={16} /> Address Cleanser & Standardizer <span>Functional</span>
          </div>
          <div className="check-row">
            <CheckCircle2 size={16} /> Logistics Operators & Courier Dispatch <span>Available</span>
          </div>
          <div className="check-row">
            <CheckCircle2 size={16} /> Printable Consignment Waybill Slips <span>Ready</span>
          </div>
        </section>
      </div>

      {selectedDelivery && (
        <DeliveryDetailModal
          delivery={selectedDelivery}
          operators={operators}
          settings={settings}
          onClose={() => setSelectedDelivery(null)}
          onUpdateStatus={(id, st, n) => {
            onUpdateStatus(id, st, n);
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
    </div>
  );
}

