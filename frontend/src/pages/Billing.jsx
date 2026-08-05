import { useCallback, useEffect, useState } from "react";
import { CalendarCheck, Clock, Hash, PhoneCall, Users } from "lucide-react";
import api from "../lib/api";
import StatCard from "../components/StatCard";
import Modal from "../components/Modal";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { useLabels } from "../store/clinicStore";

const nf = new Intl.NumberFormat("en-IN");

function formatPrice(priceInr) {
  if (priceInr === null || priceInr === undefined) return "Pricing on request";
  if (priceInr === 0) return "Free";
  return `₹${nf.format(priceInr)}/mo`;
}

function barTone(percent) {
  if (percent >= 100) return "bg-red-500";
  if (percent >= 75) return "bg-amber-500";
  return "bg-emerald-500";
}

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
  const [overview, setOverview] = useState(null);
  const [summary, setSummary] = useState(null);
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
      api.get("/billing/summary").then((r) => (r.data?.success ? setSummary(r.data.data) : null)).catch(() => {}),
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
  const usage = summary?.usage || {};
  const paymentsEnabled = !!summary?.paymentsEnabled;
  const limit = usage.monthlyCallLimit ?? 0;
  const used = usage.callsUsed ?? 0;
  const remaining = usage.callsRemaining ?? 0;
  const percent = usage.percentUsed ?? 0;

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
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-gray-950">Plan &amp; Usage</h1>
        <p className="mt-2 text-sm text-gray-500">Your subscription plan and this month's call usage.</p>
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

      {/* Current plan + monthly call usage */}
      <article className="panel rounded-3xl p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">Current plan</span>
            <div className="mt-2 flex items-center gap-3">
              <p className="text-2xl font-semibold text-gray-950">{loading ? "…" : (plan.name || "Trial")}</p>
              {plan.customAllowance && <Badge tone="warning">Custom allowance</Badge>}
            </div>
            <p className="mt-1 text-sm text-gray-500">
              {loading ? "" : `${nf.format(limit)} calls / month · ${formatPrice(plan.priceInr)}`}
            </p>
          </div>
          <Badge tone="dark">Active</Badge>
        </div>

        <div className="mt-6">
          <div className="flex items-end justify-between text-sm">
            <span className="font-medium text-gray-950">
              {loading ? "…" : `${nf.format(used)} of ${nf.format(limit)} calls used`}
            </span>
            <span className="text-gray-500">{usage.periodLabel || ""}</span>
          </div>
          <div className="mt-2 h-3 w-full overflow-hidden rounded-full bg-gray-100">
            <div
              className={`h-full rounded-full transition-all ${barTone(percent)}`}
              style={{ width: `${Math.min(percent, 100)}%` }}
            />
          </div>
          <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
            <span>{percent}% used</span>
            <span>{nf.format(remaining)} calls remaining</span>
          </div>
          {percent >= 80 && percent < 100 && (
            <p className="mt-3 rounded-2xl border border-amber-100 bg-amber-50 p-3 text-xs text-amber-800">
              You've used {percent}% of this month's call allowance. Consider upgrading before you run out.
            </p>
          )}
          {percent >= 100 && (
            <p className="mt-3 rounded-2xl border border-red-100 bg-red-50 p-3 text-xs text-red-800">
              This month's call allowance is used up. Upgrade the plan to add capacity.
            </p>
          )}
        </div>
      </article>

      {/* Plan comparison (call-volume tiers) */}
      <section>
        <h2 className="text-lg font-semibold text-gray-950">Plans</h2>
        <p className="mt-1 text-sm text-gray-500">Plans are priced by monthly call volume.</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {plans.map((p) => {
            const isCurrent = p.key === plan.key;
            const canPay = paymentsEnabled && p.price_inr > 0;
            return (
              <article
                key={p.key}
                className={`panel flex flex-col rounded-3xl p-5 ${isCurrent ? "ring-2 ring-gray-950" : ""}`}
              >
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-semibold text-gray-950">{p.name}</h3>
                  {isCurrent && <Badge tone="dark">Current</Badge>}
                </div>
                <p className="mt-3 text-2xl font-semibold text-gray-950">{nf.format(p.monthly_call_limit)}</p>
                <p className="text-xs text-gray-500">calls / month</p>
                <p className="mt-3 text-sm font-medium text-gray-900">{formatPrice(p.price_inr)}</p>
                {p.description && <p className="mt-2 text-xs leading-5 text-gray-500">{p.description}</p>}
                {!isCurrent && (
                  <div className="mt-4">
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
          className="mt-1 w-full rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-gray-950 focus:outline-none"
          placeholder="Anything we should know (expected call volume, timeline, etc.)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </Modal>
    </div>
  );
}
