import { useCallback, useEffect, useState } from "react";
import { CalendarCheck, Clock, Hash, PhoneCall, Users } from "lucide-react";
import api from "../lib/api";
import StatCard from "../components/StatCard";
import Modal from "../components/Modal";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { useLabels } from "../store/clinicStore";
import { useBillingStore, useBillingSummary } from "../store/billingStore";
import { nf, formatPrice } from "../lib/money";

// Load the Razorpay Checkout script once, on demand.
function loadRazorpayScript() {
  return new Promise((resolve) => {
    if (window.Razorpay) return resolve(true);
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.body.appendChild(script);
  });
}

export default function Billing() {
  const labels = useLabels();
  // Shared with the Dashboard's Current Plan card, so an upgrade shows up on both.
  const { summary } = useBillingSummary();
  const [overview, setOverview] = useState(null);
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [banner, setBanner] = useState(null); // { type, text }
  const [processingPlan, setProcessingPlan] = useState(null);

  // Request-upgrade modal
  const [requestPlan, setRequestPlan] = useState(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    await Promise.all([
      // The summary itself comes from billingStore (fetched once, shared with the
      // Dashboard); force it so a just-completed payment is reflected here.
      useBillingStore.getState().fetchSummary(true),
      api.get("/billing/plans").then((r) => (r.data?.success ? setPlans(r.data.data || []) : null)).catch(() => {}),
      api.get("/stats/overview").then((r) => (r.data?.success ? setOverview(r.data.data) : null)).catch(() => {}),
    ]);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const totals = overview?.totals || {};
  const calls = overview?.calls || {};
  const plan = summary?.plan || {};
  const paymentsEnabled = !!summary?.paymentsEnabled;

  const payAndUpgrade = async (planKey) => {
    setBanner(null);
    setProcessingPlan(planKey);
    try {
      const res = await api.post("/billing/checkout", { plan: planKey });
      if (!res.data?.success) {
        setBanner({ type: "error", text: res.data?.message || "Could not start payment." });
        return;
      }
      const d = res.data.data;
      const ok = await loadRazorpayScript();
      if (!ok || !window.Razorpay) {
        setBanner({ type: "error", text: "Could not load the payment window. Check your connection." });
        return;
      }
      const rzp = new window.Razorpay({
        key: d.keyId,
        order_id: d.orderId,
        amount: d.amount,
        currency: d.currency,
        name: "Clarivo",
        description: `${d.planName} plan`,
        prefill: { name: d.businessName, email: d.email },
        theme: { color: "#111827" },
        handler: async (response) => {
          try {
            const v = await api.post("/billing/verify", {
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
            });
            if (v.data?.success) {
              setBanner({ type: "success", text: "Payment successful — your plan is upgraded." });
              load();
            } else {
              setBanner({ type: "error", text: v.data?.message || "Payment could not be verified." });
            }
          } catch {
            setBanner({ type: "error", text: "Payment verification failed. If you were charged, contact support." });
          }
        },
      });
      rzp.on("payment.failed", () => setBanner({ type: "error", text: "Payment failed. Please try again." }));
      rzp.open();
    } catch {
      setBanner({ type: "error", text: "Could not start payment. Please try again." });
    } finally {
      setProcessingPlan(null);
    }
  };

  const submitRequest = async () => {
    if (!requestPlan) return;
    setSubmitting(true);
    try {
      const res = await api.post("/billing/upgrade-request", { plan: requestPlan.key, note });
      if (res.data?.success) {
        setBanner({ type: "success", text: res.data.message || "Upgrade request submitted." });
        setRequestPlan(null);
        setNote("");
      } else {
        setBanner({ type: "error", text: res.data?.message || "Could not submit request." });
      }
    } catch {
      setBanner({ type: "error", text: "Could not submit request." });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="px-1 py-0.5">
        <h1 className="text-[26px] font-semibold text-[#0F172A] dark:text-[#F5F7FA] tracking-tight leading-[32px]">Plans</h1>
        <p className="text-[13.5px] text-[#475569] dark:text-[#A1A1AA] mt-1 leading-[20px]">
          Plans are priced by monthly call volume. Your current plan and usage are on the Dashboard.
        </p>
      </div>

      {banner && (
        <div
          className={`flex items-start justify-between gap-3 rounded-2xl border p-4 text-sm ${
            banner.type === "success"
              ? "border-emerald-100 bg-emerald-50 text-emerald-800"
              : "border-red-100 bg-red-50 text-red-800"
          }`}
        >
          <span>{banner.text}</span>
          <button className="text-xs font-medium opacity-70 hover:opacity-100" onClick={() => setBanner(null)}>Dismiss</button>
        </div>
      )}

      {/* Plan comparison (call-volume tiers). The Current Plan / usage card that used
          to sit above this now lives on the Dashboard, driven by the same
          billingStore — see components/CurrentPlanCard.jsx. */}
      <section>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {plans.map((p) => {
            const isCurrent = p.key === plan.key;
            const canPay = paymentsEnabled && p.price_inr > 0;
            return (
              <article
                key={p.key}
                className={`clarivo-panel flex flex-col p-5 justify-between gap-4 ${isCurrent ? "border-[#007BA7] ring-1 ring-[#007BA7]" : ""}`}
              >
                <div className="flex flex-col gap-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-[16px] font-semibold text-[#0F172A] dark:text-[#F5F7FA]">{p.name}</h3>
                    {isCurrent && <Badge tone="dark">Current</Badge>}
                  </div>
                  <div>
                    <p className="text-[28px] font-semibold text-[#0F172A] dark:text-[#F5F7FA] tabular-nums tracking-tight leading-[34px]">{nf.format(p.monthly_call_limit)}</p>
                    <p className="text-[12px] text-[#64748B] dark:text-[#A1A1AA]">calls / month</p>
                  </div>
                  <p className="text-[14px] font-semibold text-[#0F172A] dark:text-[#F5F7FA]">{formatPrice(p.price_inr)}</p>
                  {p.description && <p className="text-[12.5px] leading-[18px] text-[#64748B] dark:text-[#A1A1AA]">{p.description}</p>}
                </div>
                {!isCurrent && (
                  <div className="mt-2">
                    {canPay ? (
                      <Button
                        className="w-full"
                        disabled={processingPlan === p.key}
                        onClick={() => payAndUpgrade(p.key)}
                      >
                        {processingPlan === p.key ? "Starting…" : "Upgrade & Pay"}
                      </Button>
                    ) : (
                      <Button
                        variant="secondary"
                        className="w-full"
                        onClick={() => { setNote(""); setRequestPlan(p); }}
                      >
                        Request upgrade
                      </Button>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </section>

      {/* Broader usage snapshot */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold text-gray-950">Usage snapshot</h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <StatCard title="Total Calls" value={loading ? "…" : (totals.calls ?? 0)} icon={PhoneCall} tone="light" />
          <StatCard title="Total Minutes" value={loading ? "…" : (calls.totalMinutes ?? 0)} icon={Clock} tone="light" />
          <StatCard title={labels.bookings} value={loading ? "…" : (totals.appointments ?? 0)} icon={CalendarCheck} tone="light" />
          <StatCard title={labels.contacts} value={loading ? "…" : (totals.contacts ?? 0)} icon={Users} tone="light" />
          <StatCard title="Numbers Connected" value={loading ? "…" : (totals.numbers ?? 0)} icon={Hash} tone="light" />
        </div>
      </section>

      {!paymentsEnabled && (
        <p className="text-sm text-gray-400">
          Online payments aren't enabled yet. Use "Request upgrade" and our team will set up your plan.
        </p>
      )}

      <Modal
        open={!!requestPlan}
        onClose={() => setRequestPlan(null)}
        title={requestPlan ? `Request ${requestPlan.name} plan` : "Request upgrade"}
        description={requestPlan ? `${nf.format(requestPlan.monthly_call_limit)} calls / month. Our team will contact you to activate it.` : ""}
        footer={
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setRequestPlan(null)}>Cancel</Button>
            <Button onClick={submitRequest} disabled={submitting}>{submitting ? "Submitting…" : "Submit request"}</Button>
          </div>
        }
      >
        <label className="block text-xs font-semibold uppercase tracking-wider text-gray-500">Note (optional)</label>
        <textarea
          rows={3}
          className="mt-1 w-full rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-brand-500 focus:outline-none"
          placeholder="Anything we should know (expected call volume, timeline, etc.)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </Modal>
    </div>
  );
}
