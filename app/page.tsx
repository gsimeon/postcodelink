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

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [operators, setOperators] = useState<Operator[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [settings, setSettings] = useState<AppSettings>(getStoredSettings());

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [prefillAddress, setPrefillAddress] = useState("");
  const [prefillPostcode, setPrefillPostcode] = useState("");
  const [selectedInspectDelivery, setSelectedInspectDelivery] = useState<Delivery | null>(null);
  const [notice, setNotice] = useState("PostcodeLink Nigeria · Standardized Digital Postcode Dispatch Gateway");

  // Load data on mount and listen to cross-component updates
  const loadData = useCallback(() => {
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
  const handleSaveDelivery = (newDelivery: Delivery) => {
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

  const handleUpdateStatus = (deliveryId: string, newStatus: DeliveryStatus, note: string) => {
    const res = updateDelivery(deliveryId, { status: newStatus });
    if (res.error) {
      setNotice(`Action blocked: ${res.error}`);
      return;
    }
    addDeliveryEvent(deliveryId, {
      status: newStatus,
      actor: "Godwin Simeon",
      actorRole: "merchant",
      note,
    });
    setNotice(`Updated ${deliveryId} status to ${newStatus.replace("_", " ")}.`);
  };

  const handleAssignOperator = (deliveryId: string, operatorId: string, operatorName: string) => {
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
              onAddCustomer={handleAddCustomer}
              onDispatchToCustomer={handleDispatchToCustomer}
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

          {/* Global Footer */}
          <footer>
            <div>
              © 2026 <b>PostcodeLink Nigeria</b> · Built for reliable last-mile delivery and digital postcode operations.
            </div>
            <div>
              <span>Official NIPOST 6-Digit Coding Framework</span>
            </div>
          </footer>
        </div>
      </section>

      {/* Create Delivery Modal */}
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

      {/* Selected Delivery Inspect Modal */}
      {selectedInspectDelivery && (
        <DeliveryDetailModal
          delivery={selectedInspectDelivery}
          operators={operators}
          settings={settings}
          onClose={() => setSelectedInspectDelivery(null)}
          onUpdateStatus={(id, st, note) => {
            handleUpdateStatus(id, st, note);
            const updated = deliveries.find((x) => x.id === id);
            if (updated) setSelectedInspectDelivery({ ...updated, status: st });
          }}
          onAssignOperator={(id, opId, opName) => {
            handleAssignOperator(id, opId, opName);
            const updated = deliveries.find((x) => x.id === id);
            if (updated) setSelectedInspectDelivery({ ...updated, operatorId: opId, operatorName: opName });
          }}
        />
      )}
    </main>
  );
}
