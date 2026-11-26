"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Delivery,
  Operator,
  Customer,
  AppSettings,
} from "@/lib/types";
import {
  getStoredDeliveries,
  getStoredOperators,
  getStoredCustomers,
  getStoredSettings,
} from "@/lib/storage";
import { fastApiClient, FastAPIProfile } from "@/lib/fastapi-client";
import {
  mapFastAPICustomer,
  mapFastAPIDelivery,
  mapFastAPIOperator,
} from "@/lib/mappers";

const DEFAULT_NOTICE =
  "PostcodeLink Nigeria · Standardized Digital Postcode Dispatch Gateway";

export type DataLoadStatus = "idle" | "loading" | "loaded" | "error";

export interface ResourceErrors {
  deliveries?: string;
  operators?: string;
  customers?: string;
}

export function useWorkspaceSession() {
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [operators, setOperators] = useState<Operator[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [settings, setSettings] = useState<AppSettings>(getStoredSettings());
  const [isFastAPIConnected, setIsFastAPIConnected] = useState(false);
  const [isDemoMode, setIsDemoMode] = useState(false);
  const [currentProfile, setCurrentProfile] = useState<FastAPIProfile | null>(null);
  const [notice, setNotice] = useState(DEFAULT_NOTICE);
  const [dataStatus, setDataStatus] = useState<DataLoadStatus>("idle");
  const [dataError, setDataError] = useState<string | null>(null);
  const [resourceErrors, setResourceErrors] = useState<ResourceErrors>({});

  // Load data: Authoritative FastAPI data source with explicit loaded-empty vs API-error distinction
  const loadData = useCallback(async () => {
    try {
      const health = await fastApiClient.getHealth();
      if (health && health.status === "healthy") {
        setIsFastAPIConnected(true);

        if (!fastApiClient.isAuthenticated()) {
          await fastApiClient.restoreSession().catch(() => null);
        }

        if (fastApiClient.isAuthenticated()) {
          setDataStatus("loading");
          const [delivRes, opsRes, custRes, profileRes] =
            await Promise.allSettled([
              fastApiClient.listDeliveries(),
              fastApiClient.listOperators(),
              fastApiClient.listCustomers(),
              fastApiClient.getProfile(),
            ]);

          if (profileRes.status === "fulfilled" && profileRes.value) {
            setCurrentProfile(profileRes.value);
          }

          const errors: ResourceErrors = {};
          if (delivRes.status === "fulfilled") {
            setDeliveries(delivRes.value.map(mapFastAPIDelivery));
          } else {
            errors.deliveries =
              delivRes.reason instanceof Error
                ? delivRes.reason.message
                : "Failed to load deliveries";
          }

          if (opsRes.status === "fulfilled") {
            setOperators(opsRes.value.map(mapFastAPIOperator));
          } else {
            errors.operators =
              opsRes.reason instanceof Error
                ? opsRes.reason.message
                : "Failed to load operators";
          }

          if (custRes.status === "fulfilled") {
            setCustomers(custRes.value.map(mapFastAPICustomer));
          } else {
            errors.customers =
              custRes.reason instanceof Error
                ? custRes.reason.message
                : "Failed to load customers";
          }

          setSettings(getStoredSettings());
          setResourceErrors(errors);

          const failedResources = Object.keys(errors);
          if (failedResources.length > 0) {
            setDataStatus("error");
            setDataError(
              `Could not refresh ${failedResources.join(", ")} from the backend API. Existing records were preserved; retry to sync.`
            );
          } else {
            setDataStatus("loaded");
            setDataError(null);
          }
          return;
        }

        setDataStatus("idle");
        setDataError(null);
        setResourceErrors({});
      }
    } catch {
      // Backend offline
    }

    setIsFastAPIConnected(false);
    setDataError(null);
    setResourceErrors({});
    if (isDemoMode) {
      setDeliveries(getStoredDeliveries());
      setOperators(getStoredOperators());
      setCustomers(getStoredCustomers());
      setDataStatus("loaded");
    } else {
      setDeliveries([]);
      setOperators([]);
      setCustomers([]);
      setDataStatus("idle");
    }
    setSettings(getStoredSettings());
  }, [isDemoMode]);

  useEffect(() => {
    loadData();
    const handleUpdate = () => loadData();
    window.addEventListener("postcodelink-data-updated", handleUpdate);
    return () =>
      window.removeEventListener("postcodelink-data-updated", handleUpdate);
  }, [loadData]);

  const handleExplicitLogin = useCallback(
    async (email: string, pass: string) => {
      try {
        const res = await fastApiClient.login(email, pass);
        setCurrentProfile(res.profile);
        setNotice(
          `Authenticated as ${res.profile.full_name} (${res.profile.business_name || res.profile.role}).`
        );
        await loadData();
      } catch (err: unknown) {
        const message =
          err instanceof Error ? err.message : "Authentication error";
        setNotice(`Authentication failed: ${message}`);
      }
    },
    [loadData]
  );

  const handleLogout = useCallback(() => {
    fastApiClient.logout();
    setCurrentProfile(null);
    setDataStatus("idle");
    setDataError(null);
    setResourceErrors({});
    setNotice("Logged out of dispatch session.");
    loadData();
  }, [loadData]);

  return {
    deliveries,
    setDeliveries,
    operators,
    setOperators,
    customers,
    setCustomers,
    settings,
    setSettings,
    isFastAPIConnected,
    isDemoMode,
    setIsDemoMode,
    currentProfile,
    setCurrentProfile,
    notice,
    setNotice,
    dataStatus,
    dataError,
    resourceErrors,
    loadData,
    handleExplicitLogin,
    handleLogout,
  };
}
