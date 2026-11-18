import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type { FilterOptions, Health } from "../api/types";

interface AppState {
  filters: FilterOptions | null;
  filtersLoading: boolean;
  filtersError: string | null;
  reloadFilters: () => void;
  currency: string;
  setCurrency: (value: string) => void;
  health: Health | null;
  healthError: boolean;
}

const AppStateContext = createContext<AppState | null>(null);

const CURRENCY_KEY = "cloudpilot.currency";

export function AppStateProvider({ children }: { children: React.ReactNode }) {
  const [filters, setFilters] = useState<FilterOptions | null>(null);
  const [filtersLoading, setFiltersLoading] = useState(true);
  const [filtersError, setFiltersError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [nonce, setNonce] = useState(0);
  const [currency, setCurrencyState] = useState<string>(
    () => window.localStorage.getItem(CURRENCY_KEY) ?? "",
  );

  useEffect(() => {
    const controller = new AbortController();
    setFiltersLoading(true);
    api
      .filters(controller.signal)
      .then((value) => {
        setFilters(value);
        setFiltersError(null);
        setFiltersLoading(false);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setFiltersError(caught instanceof Error ? caught.message : "Could not load filters.");
        setFiltersLoading(false);
      });
    api
      .health(controller.signal)
      .then((value) => {
        setHealth(value);
        setHealthError(false);
      })
      .catch(() => {
        if (!controller.signal.aborted) setHealthError(true);
      });
    return () => controller.abort();
  }, [nonce]);

  // Keep the selected currency valid as data changes.
  useEffect(() => {
    if (!filters) return;
    if (!currency || !filters.currencies.includes(currency)) {
      const next = filters.currencies[0] ?? "";
      if (next !== currency) {
        setCurrencyState(next);
        if (next) window.localStorage.setItem(CURRENCY_KEY, next);
        else window.localStorage.removeItem(CURRENCY_KEY);
      }
    }
  }, [currency, filters]);

  const setCurrency = useCallback((value: string) => {
    setCurrencyState(value);
    if (value) window.localStorage.setItem(CURRENCY_KEY, value);
    else window.localStorage.removeItem(CURRENCY_KEY);
  }, []);

  const reloadFilters = useCallback(() => setNonce((value) => value + 1), []);

  const value = useMemo<AppState>(
    () => ({
      filters,
      filtersLoading,
      filtersError,
      reloadFilters,
      currency,
      setCurrency,
      health,
      healthError,
    }),
    [filters, filtersLoading, filtersError, reloadFilters, currency, setCurrency, health, healthError],
  );

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

export function useAppState(): AppState {
  const context = useContext(AppStateContext);
  if (!context) throw new Error("useAppState must be used inside AppStateProvider");
  return context;
}
