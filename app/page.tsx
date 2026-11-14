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
} from "@/lib/fastapi-client";

import { Sidebar, TabKey } from "@/components/Sidebar";
import { Header } from "@/components/Header";
import { OverviewTab } from "@/components/OverviewTab";
import { DeliveriesTab } from "@/components/DeliveriesTab";
import { DispatchMapTab } from "@/components/DispatchMapTab";
import { TrackingPortalTab } from "@/components/TrackingPortalTab";
import { PostcodeLookupTab } from "@/components/PostcodeLookupTab";
import { OperatorsTab } from "@/components/OperatorsTab";
import { CustomersTab } from "@/components/CustomersTab";
import { AnalyticsTab } from "@/components/AnalyticsTab";
import { SettingsTab } from "@/components/SettingsTab";
import { CreateDeliveryModal } from "@/components/CreateDeliveryModal";
import { DeliveryDetailModal } from "@/components/DeliveryDetailModal";

function mapFastAPIDelivery(fd: FastAPIDelivery): Delivery {
  let mappedStatus: DeliveryStatus = "draft";
  if (fd.status === "pending") mappedStatus = "pending_assignment";
  else if (fd.status === "assigned") mappedStatus = "assigned";
  else if (fd.status === "picked_up" || fd.status === "in_transit" || fd.status === "out_for_delivery") mappedStatus = "in_transit";
  else if (fd.status === "delivered") mappedStatus = "delivered";
  else if (fd.status === "cancelled") mappedStatus = "cancelled";
  else if (fd.status === "failed") mappedStatus = "failed";

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
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [operators, setOperators] = useState<Operator[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [settings, setSettings] = useState<AppSettings>(getStoredSettings());
  const [isFastAPIConnected, setIsFastAPIConnected] = useState(false);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [prefillAddress, setPrefillAddress] = useState("");
  const [prefillPostcode, setPrefillPostcode] = useState("");
  const [selectedInspectDelivery, setSelectedInspectDelivery] = useState<Delivery | null>(null);
  const [notice, setNotice] = useState("PostcodeLink Nigeria · Standardized Digital Postcode Dispatch Gateway");

  // Load data: Primary FastAPI with offline local storage fallback
  const loadData = useCallback(async () => {
    try {
      const health = await fastApiClient.getHealth();
      if (health && health.status === "healthy") {
        setIsFastAPIConnected(true);
        const [apiDeliveries, apiOperators, apiCustomers] = await Promise.all([
          fastApiClient.listDeliveries().catch(() => []),
          fastApiClient.listOperators().catch(() => []),
          fastApiClient.listCustomers().catch(() => []),
        ]);

        if (apiDeliveries && apiDeliveries.length > 0) {
          setDeliveries(apiDeliveries.map(mapFastAPIDelivery));
        } else {
          setDeliveries(getStoredDeliveries());
        }

        if (apiOperators && apiOperators.length > 0) {
          setOperators(apiOperators.map(mapFastAPIOperator));
        } else {
          setOperators(getStoredOperators());
        }

        if (apiCustomers && apiCustomers.length > 0) {
          setCustomers(apiCustomers.map(mapFastAPICustomer));
        } else {
          setCustomers(getStoredCustomers());
        }

        setSettings(getStoredSettings());
        return;
      }
    } catch {
      // Backend not running, use fallback
    }

    setIsFastAPIConnected(false);
    setDeliveries(getStoredDeliveries());
    setOperators(getStoredOperators());
    setCustomers(getStoredCustomers());
    setSettings(getStoredSettings());
  }, []);

  useEffect(() => {
    loadData();
    const handleUpdate = () => loadData();
    window.addEventListener("postcodelink-data-updated", handleUpdate);
    return () => window.removeEventListener("postcodelink-data-updated", handleUpdate);
  }, [loadData]);

  const unassignedCount = deliveries.filter((d) => d.status === "pending_assignment").length;
  const availableOperatorsCount = operators.filter((o) => o.isAvailable).length;

  // Handlers
  const handleSaveDelivery = async (newDelivery: Delivery) => {
    if (isFastAPIConnected) {
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
        setNotice(`Order ${res.delivery.id} stored in FastAPI DB. Confirmation PIN: ${res.notification_dispatch.delivery_pin}`);
        await loadData();
        setShowCreateModal(false);
        setPrefillAddress("");
        setPrefillPostcode("");
        return;
      } catch (err: any) {
        setNotice(`FastAPI Note: ${err.message}. Saved locally.`);
      }
    }

    addDelivery(newDelivery);
    setShowCreateModal(false);
    setPrefillAddress("");
    setPrefillPostcode("");
    setNotice(`Delivery order ${newDelivery.id} created successfully.`);
  };

  const handleBulkImport = (newItems: Delivery[]) => {
    bulkAddDeliveries(newItems);
    setNotice(`Batch import complete: ${newItems.length} deliveries dispatched to network.`);
  };

  const handleUpdateStatus = async (deliveryId: string, newStatus: DeliveryStatus, note: string) => {
    if (isFastAPIConnected) {
      try {
        let apiStatus = "pending";
        if (newStatus === "assigned") apiStatus = "assigned";
        else if (newStatus === "in_transit") apiStatus = "in_transit";
        else if (newStatus === "delivered") apiStatus = "delivered";
        else if (newStatus === "cancelled") apiStatus = "cancelled";
        else if (newStatus === "failed") apiStatus = "failed";

        await fastApiClient.updateStatus(deliveryId, apiStatus, note);
        setNotice(`FastAPI: Updated ${deliveryId} status to ${newStatus.replace("_", " ")}.`);
        await loadData();
        return;
      } catch (err: any) {
        setNotice(`FastAPI Error: ${err.message}`);
      }
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
    setNotice(`Updated ${deliveryId} status to ${newStatus.replace("_", " ")}.`);
  };

  const handleVerifyOtp = async (deliveryId: string, otp: string) => {
    if (isFastAPIConnected) {
      try {
        await fastApiClient.verifyOTP(deliveryId, otp);
        setNotice(`Proof of delivery verified for ${deliveryId} in FastAPI database.`);
        await loadData();
        return { success: true, message: "Proof of delivery verified in FastAPI database. Marked delivered." };
      } catch (err: any) {
        setNotice(`PIN verification failed: ${err.message}`);
        return { success: false, message: err.message || "PIN verification failed" };
      }
    }

    const result = verifyDeliveryOtp(deliveryId, otp);
    if (result.success) {
      setNotice(`Proof of delivery verified for ${deliveryId}. Marked completed.`);
    }
    return result;
  };

  const handleAssignOperator = async (deliveryId: string, operatorId: string, operatorName: string) => {
    if (isFastAPIConnected && operatorId) {
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
    setNotice(`Assigned ${deliveryId} to ${operatorName}.`);
  };

  const handleDeleteDelivery = (deliveryId: string) => {
    deleteDelivery(deliveryId);
    setNotice(`Delivery ${deliveryId} removed from records.`);
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

  const handleAddCustomer = (newCustomer: Customer) => {
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
      />

      {/* Main Content Area */}
      <section className="main">
        {/* Top Header */}
        <Header
          activeTab={activeTab}
          settings={settings}
          unassignedCount={unassignedCount}
        />

        {/* Live Backend Connection Indicator */}
        <div style={{ padding: "8px 24px 0", display: "flex", alignItems: "center", gap: "8px", fontSize: "12px" }}>
          <span
            style={{
              display: "inline-block",
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              backgroundColor: isFastAPIConnected ? "#10b981" : "#f59e0b",
            }}
          />
          <span style={{ color: isFastAPIConnected ? "#059669" : "#d97706", fontWeight: 600 }}>
            {isFastAPIConnected
              ? "FastAPI Relational Database Connected (RBAC & Hashed OTP Active)"
              : "Offline Local Mode (Start FastAPI via `npm run backend:dev` to sync)"}
          </span>
        </div>

        {/* Tab Content */}
        <div className="content">
          {activeTab === "overview" && (
            <OverviewTab
              deliveries={deliveries}
              operators={operators}
              settings={settings}
              onOpenCreate={() => setShowCreateModal(true)}
              onNavigateTab={(tab) => setActiveTab(tab)}
              onUpdateStatus={handleUpdateStatus}
              onAssignOperator={handleAssignOperator}
              notice={notice}
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
            />
          )}

          {activeTab === "postcodes" && (
            <PostcodeLookupTab
              onStartDeliveryWithAddress={handleStartDeliveryWithAddress}
            />
          )}

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
        />
      )}
    </main>
  );
}
