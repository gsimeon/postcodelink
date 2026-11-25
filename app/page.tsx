"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Delivery,
  DeliveryStatus,
  Operator,
  Customer,
  AppSettings
} from "@/lib/types";
import {
  getStoredDeliveries,
  saveDeliveries,
  addDelivery,
  bulkAddDeliveries,
  updateDelivery,
  deleteDelivery,
  addDeliveryEvent,
  verifyDeliveryOtp,
  getStoredOperators,
  saveOperators,
  updateOperator,
  addOperator,
  getStoredCustomers,
  saveCustomers,
  addCustomer,
  getStoredSettings,
  saveSettings,
  resetAllData
} from "@/lib/storage";

import {
  fastApiClient,
  FastAPIDelivery,
  FastAPIOperator,
  FastAPICustomer,
  FastAPIProfile,
} from "@/lib/fastapi-client";
import { mapFrontendToBackendStatus, mapBackendToFrontendStatus } from "@/lib/state-machine";

import { Sidebar, TabKey } from "@/components/Sidebar";
import { Header } from "@/components/Header";
import { OverviewTab } from "@/components/OverviewTab";
import { DeliveriesTab } from "@/components/DeliveriesTab";
import { DispatchMapTab } from "@/components/DispatchMapTab";
import { TrackingPortalTab } from "@/components/TrackingPortalTab";
import { PostcodeLookupTab } from "@/components/PostcodeLookupTab";
import { DeveloperConsoleTab } from "@/components/DeveloperConsoleTab";
import { OperatorsTab } from "@/components/OperatorsTab";
import { CustomersTab } from "@/components/CustomersTab";
import { AnalyticsTab } from "@/components/AnalyticsTab";
import { SettingsTab } from "@/components/SettingsTab";
import { CreateDeliveryModal } from "@/components/CreateDeliveryModal";
import { DeliveryDetailModal } from "@/components/DeliveryDetailModal";
import { AuthModal } from "@/components/AuthModal";

function mapFastAPIDelivery(fd: FastAPIDelivery): Delivery {
  const mappedStatus: DeliveryStatus = mapBackendToFrontendStatus(fd.status);

  return {
    id: fd.id,
    recipientName: fd.recipient_name,
    recipientPhone: fd.recipient_phone,
    destinationAddress: fd.destination_address,
    landmark: fd.destination_landmark,
    destinationArea: fd.destination_area,
    destinationCity: fd.destination_area,
    destinationState: fd.destination_state,
    postcodeInput: fd.postcode_input,
    postcodeStatus: (fd.postcode_status as any) || "unverified",
    verifiedPostcode: fd.verified_postcode,
    packageDescription: fd.package_description,
    fee: fd.fee,
    operatorId: fd.operator_id,
    operatorName: fd.assigned_operator?.business_name || (fd.operator_id ? "Assigned Fleet" : "Not assigned"),
    status: mappedStatus,
    createdAt: fd.created_at,
    updatedAt: fd.updated_at,
    events: (fd.events || []).map((e) => ({
      id: e.id,
      deliveryId: e.delivery_id,
      status: (e.status as any) || "in_transit",
      actor: e.actor_name,
      actorRole: (e.actor_role as any) || "merchant",
      note: e.note,
      timestamp: e.occurred_at,
    })),
    otpAttempts: fd.otp_attempts,
    otpMaxAttempts: fd.otp_max_attempts,
    podVerified: fd.pod_verified,
    podNote: fd.pod_note,
    coordinates: fd.lat && fd.lng ? { lat: fd.lat, lng: fd.lng } : undefined,
  };
}

function mapFastAPIOperator(fo: FastAPIOperator): Operator {
  let vType: Operator["vehicleType"] = "Motorcycle";
  if (fo.vehicle_type === "van") vType = "Delivery Van";
  else if (fo.vehicle_type === "truck") vType = "Truck";
  else if (fo.vehicle_type === "bicycle") vType = "Bicycle";

  return {
    id: fo.id,
    businessName: fo.business_name,
    contactPerson: fo.business_name,
    phone: fo.phone,
    vehicleType: vType,
    serviceAreas: fo.service_areas || [],
    isAvailable: fo.is_available,
    rating: fo.rating,
    completedDeliveries: fo.completed_deliveries,
    activeDeliveriesCount: fo.active_deliveries_count,
    currentZone: fo.service_areas?.[0] || "Lagos Metro",
  };
}

function mapFastAPICustomer(fc: FastAPICustomer): Customer {
  return {
    id: fc.id,
    fullName: fc.full_name,
    phone: fc.phone,
    email: fc.email,
    defaultAddress: fc.default_address,
    area: fc.area,
    state: fc.state,
    postcode: fc.postcode || "",
    totalOrders: fc.total_orders,
  };
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabKey>("postcodes");
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [operators, setOperators] = useState<Operator[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [settings, setSettings] = useState<AppSettings>(getStoredSettings());
  const [isFastAPIConnected, setIsFastAPIConnected] = useState(false);
  const [isDemoMode, setIsDemoMode] = useState(false);
  const [currentProfile, setCurrentProfile] = useState<FastAPIProfile | null>(null);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [prefillAddress, setPrefillAddress] = useState("");
  const [prefillPostcode, setPrefillPostcode] = useState("");
  const [selectedInspectDelivery, setSelectedInspectDelivery] = useState<Delivery | null>(null);
  const [notice, setNotice] = useState("PostcodeLink Nigeria · Standardized Digital Postcode Dispatch Gateway");

  // Load data: Authoritative FastAPI data source with no silent split-brain
  const loadData = useCallback(async () => {
    try {
      const health = await fastApiClient.getHealth();
      if (health && health.status === "healthy") {
        setIsFastAPIConnected(true);

        if (!fastApiClient.isAuthenticated()) {
          await fastApiClient.restoreSession().catch(() => null);
        }

        if (fastApiClient.isAuthenticated()) {
          const [apiDeliveries, apiOperators, apiCustomers, profile] = await Promise.all([
            fastApiClient.listDeliveries().catch(() => []),
            fastApiClient.listOperators().catch(() => []),
            fastApiClient.listCustomers().catch(() => []),
            fastApiClient.getProfile().catch(() => null),
          ]);

          if (profile) {
            setCurrentProfile(profile);
          }
          // An empty array is a valid empty database state
          setDeliveries(apiDeliveries.map(mapFastAPIDelivery));
          setOperators(apiOperators.map(mapFastAPIOperator));
          setCustomers(apiCustomers.map(mapFastAPICustomer));
          setSettings(getStoredSettings());
          return;
        }
      }
    } catch {
      // Backend offline
    }

    setIsFastAPIConnected(false);
    if (isDemoMode) {
      setDeliveries(getStoredDeliveries());
      setOperators(getStoredOperators());
      setCustomers(getStoredCustomers());
    } else {
      setDeliveries([]);
      setOperators([]);
      setCustomers([]);
    }
    setSettings(getStoredSettings());
  }, [isDemoMode]);

  useEffect(() => {
    loadData();
    const handleUpdate = () => loadData();
    window.addEventListener("postcodelink-data-updated", handleUpdate);
    return () => window.removeEventListener("postcodelink-data-updated", handleUpdate);
  }, [loadData]);

  const handleExplicitLogin = async (email: string, pass: string) => {
    try {
      const res = await fastApiClient.login(email, pass);
      setCurrentProfile(res.profile);
      setNotice(`Authenticated as ${res.profile.full_name} (${res.profile.business_name || res.profile.role}).`);
      await loadData();
    } catch (err: any) {
      setNotice(`Authentication failed: ${err.message}`);
    }
  };

  const handleLogout = () => {
    fastApiClient.logout();
    setCurrentProfile(null);
    setNotice("Logged out of dispatch session.");
    loadData();
  };

  const unassignedCount = deliveries.filter((d) => d.status === "pending_assignment").length;
  const availableOperatorsCount = operators.filter((o) => o.isAvailable).length;

  // Handlers
  const handleSaveDelivery = async (newDelivery: Delivery) => {
    if (isFastAPIConnected && fastApiClient.isAuthenticated()) {
      try {
        const res = await fastApiClient.createDelivery({
          recipient_name: newDelivery.recipientName,
          recipient_phone: newDelivery.recipientPhone,
          destination_address: newDelivery.destinationAddress,
          destination_landmark: newDelivery.landmark,
          destination_area: newDelivery.destinationArea || "Ikeja",
          destination_state: newDelivery.destinationState || "Lagos",
          postcode_input: newDelivery.postcodeInput,
          package_description: newDelivery.packageDescription || "Parcel",
          fee: newDelivery.fee || 2500,
        });
        setNotice(`Order ${res.delivery.id} stored in database. PIN dispatched out-of-band to recipient phone.`);
        await loadData();
        setShowCreateModal(false);
        setPrefillAddress("");
        setPrefillPostcode("");
        return;
      } catch (err: any) {
        setNotice(`FastAPI Error: ${err.message}`);
        return;
      }
    }

    if (!isDemoMode) {
      setNotice("Operation blocked: Cannot create delivery while backend service is offline. Enable Demonstration Mode to test offline.");
      return;
    }

    addDelivery(newDelivery);
    setShowCreateModal(false);
    setPrefillAddress("");
    setPrefillPostcode("");
    setNotice(`[Demo Mode] Delivery order ${newDelivery.id} created successfully in local mock storage.`);
  };

  const handleBulkImport = async (newItems: Delivery[]) => {
    if (isFastAPIConnected && fastApiClient.isAuthenticated()) {
      try {
        const apiPayload = newItems.map((item) => ({
          recipient_name: item.recipientName,
          recipient_phone: item.recipientPhone,
          destination_address: item.destinationAddress,
          destination_landmark: item.landmark,
          destination_area: item.destinationArea || "Ikeja",
          destination_state: item.destinationState || "Lagos",
          postcode_input: item.postcodeInput,
          package_description: item.packageDescription || "Parcel",
          fee: item.fee || 2500,
        }));
        await fastApiClient.bulkCreateDeliveries(apiPayload);
        setNotice(`Batch import complete: ${newItems.length} deliveries registered in database.`);
        await loadData();
        return;
      } catch (err: any) {
        setNotice(`Bulk Import Error: ${err.message}`);
        return;
      }
    }

    if (!isDemoMode) {
      setNotice("Operation blocked: Cannot import deliveries while backend service is offline. Enable Demonstration Mode to test offline.");
      return;
    }

    bulkAddDeliveries(newItems);
    setNotice(`[Demo Mode] Batch import complete: ${newItems.length} deliveries dispatched to local mock storage.`);
  };

  const handleUpdateStatus = async (deliveryId: string, newStatus: DeliveryStatus, note: string) => {
    let apiStatus: string;
    try {
      apiStatus = mapFrontendToBackendStatus(newStatus);
    } catch (err: any) {
      setNotice(`Update Error: ${err.message}`);
      return;
    }

    if (isFastAPIConnected && fastApiClient.isAuthenticated()) {
      try {
        await fastApiClient.updateStatus(deliveryId, apiStatus, note);
        setNotice(`FastAPI: Updated ${deliveryId} status to ${newStatus.replace("_", " ")}.`);
        await loadData();
        return;
      } catch (err: any) {
        setNotice(`FastAPI Error: ${err.message}`);
        return;
      }
    }

    if (!isDemoMode) {
      setNotice("Operation blocked: Cannot update delivery status while backend service is offline. Enable Demonstration Mode to test offline.");
      return;
    }

    const res = updateDelivery(deliveryId, { status: newStatus });
    if (res.error) {
      setNotice(`Action blocked: ${res.error}`);
      return;
    }
    addDeliveryEvent(deliveryId, {
      status: newStatus,
      actor: "Operations Lead",
      actorRole: "merchant",
      note,
    });
    setNotice(`[Demo Mode] Updated ${deliveryId} status to ${newStatus.replace("_", " ")}.`);
  };

  const handleVerifyOtp = async (deliveryId: string, otp: string) => {
    if (isFastAPIConnected && fastApiClient.isAuthenticated()) {
      try {
        await fastApiClient.verifyOTP(deliveryId, otp);
        setNotice(`Proof of delivery verified for ${deliveryId} in database.`);
        await loadData();
        return { success: true, message: "Proof of delivery verified in database. Marked delivered." };
      } catch (err: any) {
        setNotice(`PIN verification failed: ${err.message}`);
        return { success: false, message: err.message || "PIN verification failed" };
      }
    }

    if (!isDemoMode) {
      setNotice("Verification blocked: Backend service is offline. Verification requires active server connection.");
      return { success: false, message: "Backend service is offline. Verification requires active server connection." };
    }

    const result = verifyDeliveryOtp(deliveryId, otp);
    if (result.success) {
      setNotice(`[Demo Mode] Proof of delivery verified for ${deliveryId}. Marked completed.`);
    }
    return result;
  };

  const handleAssignOperator = async (deliveryId: string, operatorId: string, operatorName: string) => {
    if (isFastAPIConnected && fastApiClient.isAuthenticated() && operatorId) {
      try {
        await fastApiClient.assignOperator(deliveryId, operatorId);
        setNotice(`FastAPI: Assigned ${deliveryId} to ${operatorName}.`);
        await loadData();
        return;
      } catch (err: any) {
        setNotice(`Assignment Error: ${err.message}`);
        return;
      }
    }

    if (!isDemoMode) {
      setNotice("Operation blocked: Cannot assign courier while backend service is offline. Enable Demonstration Mode to test offline.");
      return;
    }

    updateDelivery(deliveryId, {
      operatorId: operatorId || undefined,
      operatorName: operatorName || "Not assigned",
      status: operatorId ? "assigned" : "pending_assignment",
    });
    addDeliveryEvent(deliveryId, {
      status: operatorId ? "assigned" : "pending_assignment",
      actor: "Operations Lead",
      actorRole: "merchant",
      note: operatorId ? `Assigned to ${operatorName}` : "Unassigned from courier",
    });
    setNotice(`[Demo Mode] Assigned ${deliveryId} to ${operatorName}.`);
  };

  const handleDeleteDelivery = async (deliveryId: string) => {
    if (isFastAPIConnected && fastApiClient.isAuthenticated()) {
      try {
        await fastApiClient.deleteDelivery(deliveryId);
        setNotice(`Delivery ${deliveryId} deleted from database.`);
        await loadData();
        return;
      } catch (err: any) {
        setNotice(`Delete Error: ${err.message}`);
        return;
      }
    }

    if (!isDemoMode) {
      setNotice("Operation blocked: Cannot delete delivery while backend service is offline. Enable Demonstration Mode to test offline.");
      return;
    }

    deleteDelivery(deliveryId);
    setNotice(`[Demo Mode] Delivery ${deliveryId} removed from local mock storage.`);
  };

  const handleToggleOperator = (operatorId: string) => {
    const op = operators.find((o) => o.id === operatorId);
    if (op) {
      updateOperator(operatorId, { isAvailable: !op.isAvailable });
    }
  };

  const handleAddOperator = (newOp: Operator) => {
    addOperator(newOp);
    setNotice(`Logistics partner ${newOp.businessName} added.`);
  };

  const handleAddCustomer = async (newCustomer: Customer) => {
    if (isFastAPIConnected && fastApiClient.isAuthenticated()) {
      try {
        await fastApiClient.createCustomer({
          full_name: newCustomer.fullName,
          phone: newCustomer.phone,
          email: newCustomer.email,
          default_address: newCustomer.defaultAddress,
          area: newCustomer.area,
          state: newCustomer.state,
          postcode: newCustomer.postcode,
        });
        setNotice(`Customer ${newCustomer.fullName} saved to tenant directory.`);
        await loadData();
        return;
      } catch (err: any) {
        setNotice(`Customer Save Error: ${err.message}`);
        return;
      }
    }

    addCustomer(newCustomer);
    setNotice(`Customer ${newCustomer.fullName} saved to directory.`);
  };

  const handleDispatchToCustomer = (customer: Customer) => {
    setPrefillAddress(`${customer.defaultAddress}, ${customer.area}, ${customer.state}`);
    setPrefillPostcode(customer.postcode);
    setShowCreateModal(true);
  };

  const handleStartDeliveryWithAddress = (address: string, postcode: string) => {
    setPrefillAddress(address);
    setPrefillPostcode(postcode);
    setShowCreateModal(true);
  };

  const handleSaveSettings = (newSettings: AppSettings) => {
    saveSettings(newSettings);
    setNotice("Settings and dispatch hub preferences updated.");
  };

  const handleResetData = () => {
    resetAllData();
    loadData();
    setNotice("Demo workspace reset to initial sample state.");
  };

  const handleExportAllData = () => {
    const backup = {
      exportDate: new Date().toISOString(),
      deliveries: getStoredDeliveries(),
      operators: getStoredOperators(),
      customers: getStoredCustomers(),
      settings: getStoredSettings(),
    };
    const jsonStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(backup, null, 2));
    const link = document.createElement("a");
    link.setAttribute("href", jsonStr);
    link.setAttribute("download", `postcodelink_full_backup_${Date.now()}.json`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <main className="shell">
      {/* Sidebar */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        deliveriesCount={deliveries.length}
        unassignedCount={unassignedCount}
        availableOperatorsCount={availableOperatorsCount}
        profile={currentProfile}
      />

      {/* Main Content Area */}
      <section className="main">
        {/* Top Header */}
        <Header
          activeTab={activeTab}
          settings={settings}
          unassignedCount={unassignedCount}
        />

        {/* Live Backend Connection & Authentication Bar */}
        <div style={{ padding: "8px 24px", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #e2e8f0", backgroundColor: "#f8fafc", fontSize: "12px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span
              style={{
                display: "inline-block",
                width: "8px",
                height: "8px",
                borderRadius: "50%",
                backgroundColor: isFastAPIConnected ? "#10b981" : (isDemoMode ? "#f59e0b" : "#ef4444"),
              }}
            />
            <span style={{ color: isFastAPIConnected ? "#059669" : (isDemoMode ? "#d97706" : "#dc2626"), fontWeight: 600 }}>
              {isFastAPIConnected
                ? (fastApiClient.isAuthenticated() ? "FastAPI Authenticated · Tenant Isolated Database" : "FastAPI Online · Login Required")
                : (isDemoMode ? "Demonstration Mode Active · Local Mock Storage" : "Backend Offline · Service Unavailable")}
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            {!isFastAPIConnected && (
              <button
                type="button"
                onClick={() => {
                  const nextMode = !isDemoMode;
                  setIsDemoMode(nextMode);
                  if (!nextMode) {
                    setDeliveries([]);
                    setOperators([]);
                    setCustomers([]);
                    setNotice("Exited Demonstration Mode. Production offline state restored.");
                  } else {
                    setDeliveries(getStoredDeliveries());
                    setOperators(getStoredOperators());
                    setCustomers(getStoredCustomers());
                    setNotice("Demonstration Mode enabled: running with local mock storage.");
                  }
                }}
                style={{
                  padding: "3px 8px",
                  background: isDemoMode ? "#fef3c7" : "#fee2e2",
                  color: isDemoMode ? "#b45309" : "#b91c1c",
                  border: isDemoMode ? "1px solid #fde68a" : "1px solid #fca5a5",
                  borderRadius: "4px",
                  cursor: "pointer",
                  fontSize: "11px",
                  fontWeight: 600,
                }}
              >
                {isDemoMode ? "Exit Demo Mode" : "Enable Demo Mode"}
              </button>
            )}

            {fastApiClient.isAuthenticated() ? (
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ color: "#475569" }}>
                  Active Merchant: <strong>{currentProfile?.business_name || "Lagos Fulfillment Hub"}</strong>
                </span>
                <button
                  type="button"
                  onClick={handleLogout}
                  style={{
                    padding: "3px 8px",
                    background: "#fee2e2",
                    color: "#b91c1c",
                    border: "1px solid #fca5a5",
                    borderRadius: "4px",
                    cursor: "pointer",
                    fontSize: "11px",
                  }}
                >
                  Logout
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setShowAuthModal(true)}
                style={{
                  padding: "4px 12px",
                  background: "#2563eb",
                  color: "#ffffff",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                  fontSize: "11px",
                  fontWeight: 600,
                }}
              >
                Sign In
              </button>
            )}
          </div>
        </div>

        {/* Tab Content */}
        <div className="content">
          {!isFastAPIConnected && !isDemoMode && (
            <div style={{ background: "#fef2f2", border: "1px solid #f87171", borderRadius: "8px", padding: "12px 16px", marginBottom: "16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <strong style={{ color: "#991b1b" }}>Backend Service Unavailable</strong>
                <p style={{ margin: "4px 0 0", fontSize: "13px", color: "#b91c1c" }}>
                  Unable to connect to the PostcodeLink FastAPI service. Operations requiring persistence are disabled to prevent data divergence.
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setIsDemoMode(true);
                  setDeliveries(getStoredDeliveries());
                  setOperators(getStoredOperators());
                  setCustomers(getStoredCustomers());
                  setNotice("Demonstration Mode enabled: running with local mock storage.");
                }}
                style={{ padding: "6px 12px", background: "#b91c1c", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer", fontSize: "12px", fontWeight: "bold" }}
              >
                Enable Offline Demo Mode
              </button>
            </div>
          )}

          {!isFastAPIConnected && isDemoMode && (
            <div style={{ background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: "8px", padding: "10px 16px", marginBottom: "16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <strong style={{ color: "#92400e" }}>Demonstration Mode Active</strong>
                <p style={{ margin: "4px 0 0", fontSize: "12px", color: "#b45309" }}>
                  Running offline with browser mock storage. Changes will not be persisted to the server database.
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setIsDemoMode(false);
                  setDeliveries([]);
                  setOperators([]);
                  setCustomers([]);
                  setNotice("Exited Demonstration Mode. Production offline state restored.");
                }}
                style={{ padding: "4px 10px", background: "#f59e0b", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer", fontSize: "12px", fontWeight: "bold" }}
              >
                Exit Demo Mode
              </button>
            </div>
          )}
          {activeTab === "overview" && (
            <OverviewTab
              deliveries={deliveries}
              operators={operators}
              settings={settings}
              profile={currentProfile}
              onOpenCreate={() => setShowCreateModal(true)}
              onNavigateTab={(tab) => setActiveTab(tab)}
              onUpdateStatus={handleUpdateStatus}
              onAssignOperator={handleAssignOperator}
              notice={notice}
              onVerifyOtp={handleVerifyOtp}
            />
          )}

          {activeTab === "deliveries" && (
            <DeliveriesTab
              deliveries={deliveries}
              operators={operators}
              settings={settings}
              onOpenCreate={() => setShowCreateModal(true)}
              onBulkImport={handleBulkImport}
              onUpdateStatus={handleUpdateStatus}
              onAssignOperator={handleAssignOperator}
              onDeleteDelivery={handleDeleteDelivery}
              onVerifyOtp={handleVerifyOtp}
            />
          )}

          {activeTab === "map" && (
            <DispatchMapTab
              deliveries={deliveries}
              operators={operators}
              settings={settings}
              onSelectDelivery={(d) => setSelectedInspectDelivery(d)}
            />
          )}

          {activeTab === "tracking" && (
            <TrackingPortalTab
              deliveries={deliveries}
              settings={settings}
              onVerifyOtp={handleVerifyOtp}
              isDemoMode={isDemoMode}
            />
          )}

          {activeTab === "postcodes" && (
            <PostcodeLookupTab
              onStartDeliveryWithAddress={handleStartDeliveryWithAddress}
            />
          )}

          {activeTab === "developer" && <DeveloperConsoleTab />}

          {activeTab === "operators" && (
            <OperatorsTab
              operators={operators}
              onToggleAvailability={handleToggleOperator}
              onAddOperator={handleAddOperator}
            />
          )}

          {activeTab === "customers" && (
            <CustomersTab
              customers={customers}
              onDispatchToCustomer={handleDispatchToCustomer}
              onAddCustomer={handleAddCustomer}
            />
          )}

          {activeTab === "analytics" && (
            <AnalyticsTab
              deliveries={deliveries}
              operators={operators}
            />
          )}

          {activeTab === "settings" && (
            <SettingsTab
              settings={settings}
              onSaveSettings={handleSaveSettings}
              onResetData={handleResetData}
              onExportAllData={handleExportAllData}
            />
          )}
        </div>
      </section>

      {/* Modals */}
      {showCreateModal && (
        <CreateDeliveryModal
          operators={operators}
          customers={customers}
          onClose={() => {
            setShowCreateModal(false);
            setPrefillAddress("");
            setPrefillPostcode("");
          }}
          onSave={handleSaveDelivery}
          initialAddress={prefillAddress}
          initialPostcode={prefillPostcode}
        />
      )}

      {selectedInspectDelivery && (
        <DeliveryDetailModal
          delivery={selectedInspectDelivery}
          operators={operators}
          settings={settings}
          onClose={() => setSelectedInspectDelivery(null)}
          onUpdateStatus={handleUpdateStatus}
          onAssignOperator={handleAssignOperator}
          onVerifyOtp={handleVerifyOtp}
        />
      )}

      {showAuthModal && (
        <AuthModal
          isOpen={showAuthModal}
          onClose={() => setShowAuthModal(false)}
          onSuccess={loadData}
        />
      )}
    </main>
  );
}
