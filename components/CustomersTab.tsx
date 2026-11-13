"use client";

import React, { useState } from "react";
import { Customer } from "@/lib/types";
import {
  Users,
  Plus,
  Phone,
  Mail,
  MapPin,
  CheckCircle2,
  Package,
  X,
  ShieldCheck
} from "lucide-react";
import { NIGERIA_POSTCODES, STATES_LIST } from "@/lib/nigeria-postcodes";

interface CustomersTabProps {
  customers: Customer[];
  onAddCustomer: (customer: Customer) => void;
  onDispatchToCustomer: (customer: Customer) => void;
}

export function CustomersTab({
  customers,
  onAddCustomer,
  onDispatchToCustomer,
}: CustomersTabProps) {
  const [showAddModal, setShowAddModal] = useState(false);
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("+234 ");
  const [email, setEmail] = useState("");
  const [defaultAddress, setDefaultAddress] = useState("");
  const [state, setState] = useState("Lagos");
  const [area, setArea] = useState("Lekki Phase 1");
  const [postcode, setPostcode] = useState("105102");

  const areasInState = NIGERIA_POSTCODES.filter(
    (p) => p.state.toLowerCase() === state.toLowerCase()
  );

  const handleAreaChange = (selectedArea: string) => {
    setArea(selectedArea);
    const found = NIGERIA_POSTCODES.find(
      (p) =>
        p.districtOrArea.toLowerCase() === selectedArea.toLowerCase() &&
        p.state.toLowerCase() === state.toLowerCase()
    );
    if (found) {
      setPostcode(found.postcode);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!fullName.trim() || !defaultAddress.trim()) return;

    const newCustomer: Customer = {
      id: `cust-${Date.now()}`,
      fullName: fullName.trim(),
      phone: phone.trim(),
      email: email.trim() || undefined,
      defaultAddress: defaultAddress.trim(),
      area,
      state,
      postcode,
      totalOrders: 0,
    };

    onAddCustomer(newCustomer);
    setShowAddModal(false);
    setFullName("");
    setDefaultAddress("");
    setEmail("");
  };

  return (
    <div>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Customer Address Book & Recipient Directory</h2>
            <p>
              Pre-validated delivery destinations with standardized Nigerian digital postcodes for regular clients.
            </p>
          </div>
          <button type="button" className="primary" onClick={() => setShowAddModal(true)}>
            <Plus size={15} /> Add Customer
          </button>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>CUSTOMER NAME</th>
                <th>CONTACT DETAILS</th>
                <th>DEFAULT DESTINATION ADDRESS</th>
                <th>POSTCODE</th>
                <th>ORDERS</th>
                <th>ACTION</th>
              </tr>
            </thead>
            <tbody>
              {customers.map((c) => (
                <tr key={c.id}>
                  <td>
                    <b style={{ fontSize: "13px" }}>{c.fullName}</b>
                    <small>Customer ID: {c.id}</small>
                  </td>

                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: "5px", fontSize: "12px", color: "#2563eb" }}>
                      <Phone size={12} /> {c.phone}
                    </div>
                    {c.email && (
                      <div style={{ display: "flex", alignItems: "center", gap: "5px", fontSize: "11px", color: "#64748b", marginTop: "3px" }}>
                        <Mail size={11} /> {c.email}
                      </div>
                    )}
                  </td>

                  <td>
                    <div style={{ maxWidth: "260px", whiteSpace: "normal" }}>
                      <b style={{ fontSize: "12px" }}>{c.defaultAddress}</b>
                      <small>
                        {c.area}, {c.state}
                      </small>
                    </div>
                  </td>

                  <td>
                    <span className="postcode-badge verified">
                      <ShieldCheck size={11} /> NG-{c.postcode}
                    </span>
                  </td>

                  <td>
                    <span className="pill blue" style={{ fontSize: "11px" }}>
                      {c.totalOrders} deliveries
                    </span>
                  </td>

                  <td>
                    <button
                      type="button"
                      className="outline"
                      style={{ height: "30px", fontSize: "11px", padding: "0 10px" }}
                      onClick={() => onDispatchToCustomer(c)}
                    >
                      <Package size={13} /> Send Delivery
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="table-foot">
          Showing {customers.length} saved customer destination profiles
          <span>PostcodeLink Recipient Registry</span>
        </div>
      </section>

      {/* Add Customer Modal */}
      {showAddModal && (
        <div className="overlay" onClick={() => setShowAddModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <div>
                <p className="eyebrow">NEW CUSTOMER PROFILE</p>
                <h2>Add Recipient Profile</h2>
                <p className="sub">Save pre-verified delivery addresses for repeat orders.</p>
              </div>
              <button type="button" className="icon-btn" onClick={() => setShowAddModal(false)}>
                <X size={17} />
              </button>
            </div>

            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label>Full Name *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Babatunde Sanwo"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                />
              </div>

              <div className="form-grid">
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
                  <label>Email Address</label>
                  <input
                    type="email"
                    placeholder="customer@domain.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
              </div>

              <div className="form-group">
                <label>Default Street Address & Landmark *</label>
                <input
                  type="text"
                  required
                  placeholder="Street, house number, prominent landmark"
                  value={defaultAddress}
                  onChange={(e) => setDefaultAddress(e.target.value)}
                />
              </div>

              <div className="form-grid">
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
                    {STATES_LIST.map((st) => (
                      <option key={st} value={st}>
                        {st}
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
              </div>

              <div className="form-group">
                <label>Verified NIPOST Postcode</label>
                <input
                  type="text"
                  value={postcode}
                  readOnly
                  style={{ background: "#f8fafc", fontWeight: 600 }}
                />
              </div>

              <div className="modal-actions">
                <button type="button" className="outline" onClick={() => setShowAddModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="primary">
                  Save Customer
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

