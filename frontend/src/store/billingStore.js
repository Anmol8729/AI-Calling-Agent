import { useEffect } from "react";
import { create } from "zustand";
import api from "../lib/api";

/**
 * Caches the tenant's billing summary (plan + this month's call usage).
 *
 * It is a store rather than per-page state because the Current Plan card now renders
 * on the Dashboard while the Billing page still needs the same `plan.key` and
 * `paymentsEnabled` from the identical response. Two independent fetches would let
 * the two screens disagree — one could show an upgraded plan while the other still
 * showed the old one until it happened to refetch.
 *
 * Same shape as clinicStore: the loading/loaded guard means many callers mounting at
 * once share a single request.
 */
export const useBillingStore = create((set, get) => ({
  summary: null,
  loaded: false,
  loading: false,
  fetchSummary: async (force = false) => {
    const { loading, loaded } = get();
    if (loading || (loaded && !force)) return;
    set({ loading: true });
    try {
      const res = await api.get("/billing/summary");
      if (res.data?.success) set({ summary: res.data.data, loaded: true });
    } catch {
      /* leave unloaded so a later mount can retry */
    } finally {
      set({ loading: false });
    }
  },
}));

/**
 * Billing summary for the current tenant, fetching it once on first mount.
 *
 * Call `useBillingStore.getState().fetchSummary(true)` after anything that changes the
 * plan (a successful payment) so every screen reading this store updates together.
 */
export function useBillingSummary() {
  const summary = useBillingStore((s) => s.summary);
  const loading = useBillingStore((s) => s.loading);
  const loaded = useBillingStore((s) => s.loaded);
  const fetchSummary = useBillingStore((s) => s.fetchSummary);
  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);
  return { summary, loading, loaded };
}
