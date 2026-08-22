import { Badge } from "./ui/Badge";
import { useBillingSummary } from "../store/billingStore";
import { nf, formatPrice, barTone } from "../lib/money";

/**
 * Current plan + this month's call usage.
 *
 * Moved here from the Billing page so the Dashboard can show it without a second
 * copy. It reads billingStore directly rather than taking props, so dropping it on a
 * page needs no wiring and it can never drift from what Billing reports — both read
 * the one cached /billing/summary response.
 *
 * Rendered on the Dashboard only. Billing still uses the same store for `plan.key`
 * and `paymentsEnabled`, but no longer draws this card.
 */
export default function CurrentPlanCard() {
  const { summary, loading, loaded } = useBillingSummary();

  // If the request failed there is no plan to describe. Showing the zeroed defaults
  // would read as a real "Trial, 0 of 0 calls", which is worse than showing nothing.
  if (!loading && !loaded) return null;

  const plan = summary?.plan || {};
  const usage = summary?.usage || {};
  const limit = usage.monthlyCallLimit ?? 0;
  const used = usage.callsUsed ?? 0;
  const remaining = usage.callsRemaining ?? 0;
  const percent = usage.percentUsed ?? 0;

  return (
    <article className="panel rounded-3xl p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">Current plan</span>
          <div className="mt-2 flex flex-wrap items-center gap-3">
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
        {/* flex-wrap so the period label drops below the usage line on a narrow
            screen instead of the two colliding. */}
        <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-1 text-sm">
          <span className="font-medium text-gray-950">
            {loading ? "…" : `${nf.format(used)} of ${nf.format(limit)} calls used`}
          </span>
          <span className="text-gray-500">{usage.periodLabel || ""}</span>
        </div>
        <div
          className="mt-2 h-3 w-full overflow-hidden rounded-full bg-gray-100"
          role="progressbar"
          aria-valuenow={Math.min(percent, 100)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Monthly call allowance used"
        >
          <div
            className={`h-full rounded-full transition-all ${barTone(percent)}`}
            style={{ width: `${Math.min(percent, 100)}%` }}
          />
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-gray-500">
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
  );
}
