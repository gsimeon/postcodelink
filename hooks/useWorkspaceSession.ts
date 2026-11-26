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

export function useWorkspaceSession() {
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [operators, setOperators] = useState<Operator[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [settings, setSettings] = useState<AppSettings>(getStoredSettings());
  const [isFastAPIConnected, setIsFastAPIConnected] = useState(false);
  const [isDemoMode, setIsDemoMode] = useState(false);
  const [currentProfile, setCurrentProfile] = useState<FastAPIProfile | null>(null);
  const [notice, setNotice] = useState(DEFAULT_NOTICE);

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
          const [apiDeliveries, apiOperators, apiCustomers, profile] =
            await Promise.all([
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
    loadData,
    handleExplicitLogin,
    handleLogout,
  };
}
