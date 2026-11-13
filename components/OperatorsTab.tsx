"use client";

import React, { useState } from "react";
import { Operator } from "@/lib/types";
import {
  Truck,
  Plus,
  Phone,
  CheckCircle2,
  XCircle,
  Star,
  MapPin,
  X,
  UserCheck,
  Bike
} from "lucide-react";

interface OperatorsTabProps {
  operators: Operator[];
  onToggleAvailability: (operatorId: string) => void;
  onAddOperator: (op: Operator) => void;
}

export function OperatorsTab({
  operators,
  onToggleAvailability,
  onAddOperator,
}: OperatorsTabProps) {
  const [showAddModal, setShowAddModal] = useState(false);
  const [businessName, setBusinessName] = useState("");
  const [contactPerson, setContactPerson] = useState("");
  const [phone, setPhone] = useState("+234 ");
  const [vehicleType, setVehicleType] = useState<Operator["vehicleType"]>("Motorcycle");
  const [serviceAreasText, setServiceAreasText] = useState("Lekki Phase 1, Victoria Island (VI), Ikoyi");

  const availableCount = operators.filter((o) => o.isAvailable).length;
  const totalCompleted = operators.reduce((acc, curr) => acc + curr.completedDeliveries, 0);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!businessName.trim() || !contactPerson.trim()) return;

    const areas = serviceAreasText
      .split(/[,]+/)
      .map((s) => s.trim())
      .filter(Boolean);

    const newOp: Operator = {
      id: `op-${Date.now()}`,
      businessName: businessName.trim(),
      contactPerson: contactPerson.trim(),
      phone: phone.trim(),
      vehicleType,
      serviceAreas: areas.length > 0 ? areas : ["General Urban Delivery"],
      isAvailable: true,
      rating: 5.0,
      completedDeliveries: 0,
      activeDeliveriesCount: 0,
    };

    onAddOperator(newOp);
    setShowAddModal(false);
    setBusinessName("");
    setContactPerson("");
  };

  return (
    <div>
      {/* Top Metrics Grid */}
      <div className="metrics">
        <div className="metric">
          <div className="metric-top">
            <span>Logistics Partners</span>
            <i>
              <Truck size={17} />
            </i>
          </div>
          <strong>{operators.length}</strong>
          <small>Verified courier partners</small>
        </div>

        <div className="metric">
          <div className="metric-top">
            <span>Available Dispatch</span>
            <i>
              <UserCheck size={17} />
            </i>
          </div>
          <strong style={{ color: "#16a34a" }}>{availableCount}</strong>
          <small>Online & ready for orders</small>
        </div>

        <div className="metric">
          <div className="metric-top">
            <span>Completed Trips</span>
            <i>
              <CheckCircle2 size={17} />
            </i>
          </div>
          <strong>{totalCompleted.toLocaleString()}</strong>
          <small>Total network deliveries</small>
        </div>

        <div className="metric">
          <div className="metric-top">
            <span>Network Rating</span>
            <i>
              <Star size={17} />
            </i>
          </div>
          <strong>4.8</strong>
          <small>Average satisfaction</small>
        </div>
      </div>

      {/* Operator List Panel */}
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Logistics Dispatch Operators & Courier Fleet</h2>
            <p>Manage contracted delivery services, coverage areas, and real-time rider availability.</p>
          </div>
          <button type="button" className="primary" onClick={() => setShowAddModal(true)}>
            <Plus size={15} /> Add Operator
          </button>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>OPERATOR / COURIER</th>
                <th>CONTACT PERSON</th>
                <th>VEHICLE TYPE</th>
                <th>SERVICE COVERAGE AREAS</th>
                <th>RATING & TRIPS</th>
                <th>STATUS</th>
                <th>ACTION</th>
              </tr>
            </thead>
            <tbody>
              {operators.map((op) => (
                <tr key={op.id}>
                  <td>
                    <b style={{ fontSize: "13px" }}>{op.businessName}</b>
                    <small>Partner ID: {op.id}</small>
                  </td>

                  <td>
                    <b style={{ fontSize: "12px" }}>{op.contactPerson}</b>
                    <div style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "11px", color: "#2563eb", marginTop: "2px" }}>
                      <Phone size={11} /> {op.phone}
                    </div>
                  </td>

                  <td>
                    <span className="pill blue" style={{ fontSize: "11px" }}>
                      {op.vehicleType}
                    </span>
                  </td>

                  <td>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", maxWidth: "280px" }}>
                      {op.serviceAreas.map((area) => (
                        <span
                          key={area}
                          style={{
                            background: "#f1f5f9",
                            color: "#475569",
                            padding: "2px 6px",
                            borderRadius: "4px",
                            fontSize: "10px",
                          }}
                        >
                          {area}
                        </span>
                      ))}
                    </div>
                  </td>

                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                      <Star size={13} color="#f59e0b" fill="#f59e0b" />
                      <b style={{ fontSize: "12px" }}>{op.rating.toFixed(1)}</b>
                      <span style={{ fontSize: "11px", color: "#64748b" }}>
                        ({op.completedDeliveries} trips)
                      </span>
                    </div>
                  </td>

                  <td>
                    <span className={`pill ${op.isAvailable ? "green" : "amber"}`}>
                      <i /> {op.isAvailable ? "Available" : "Busy"}
                    </span>
                  </td>

                  <td>
                    <button
                      type="button"
                      className="outline"
                      style={{ height: "30px", fontSize: "11px", padding: "0 10px" }}
                      onClick={() => onToggleAvailability(op.id)}
                    >
                      {op.isAvailable ? "Set Busy" : "Set Available"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="table-foot">
          Showing {operators.length} registered logistics providers
          <span>PostcodeLink Partner Network</span>
        </div>
      </section>

      {/* Add Operator Modal */}
      {showAddModal && (
        <div className="overlay" onClick={() => setShowAddModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <div>
                <p className="eyebrow">NEW LOGISTICS PARTNER</p>
                <h2>Add Courier Operator</h2>
                <p className="sub">Register a new rider or delivery company to the dispatch network.</p>
              </div>
              <button type="button" className="icon-btn" onClick={() => setShowAddModal(false)}>
                <X size={17} />
              </button>
            </div>

            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label>Company / Operator Name *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Apex Couriers Lagos"
                  value={businessName}
                  onChange={(e) => setBusinessName(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label>Contact Person / Dispatch Lead *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Emeka Okoye"
                  value={contactPerson}
                  onChange={(e) => setContactPerson(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label>Phone Number *</label>
                <input
                  type="text"
                  required
                  placeholder="+234 803 000 0000"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label>Vehicle Fleet Type</label>
                <select
                  value={vehicleType}
                  onChange={(e) => setVehicleType(e.target.value as Operator["vehicleType"])}
                >
                  <option value="Motorcycle">Motorcycle (Dispatch Bike)</option>
                  <option value="Delivery Van">Delivery Van</option>
                  <option value="Tricycle (Keke)">Tricycle (Keke Express)</option>
                  <option value="Truck">Heavy Truck</option>
                  <option value="Bicycle">Bicycle (Eco Delivery)</option>
                </select>
              </div>

              <div className="form-group">
                <label>Service Coverage Areas (Comma-separated)</label>
                <textarea
                  placeholder="e.g. Lekki Phase 1, Victoria Island, Ikoyi, Yaba"
                  value={serviceAreasText}
                  onChange={(e) => setServiceAreasText(e.target.value)}
                />
              </div>

              <div className="modal-actions">
                <button type="button" className="outline" onClick={() => setShowAddModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="primary">
                  Save Operator
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

