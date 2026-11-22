import { Badge } from "./ui/Badge";
import { useBillingSummary } from "../store/billingStore";
import { nf, formatPrice, barTone } from "../lib/money";

export default function CurrentPlanCard() {
  const { summary, loading, loaded } = useBillingSummary();

  if (!loading && !loaded) return null;

  const plan = summary?.plan || {};
  const usage = summary?.usage || {};
  const limit = usage.monthlyCallLimit ?? 0;
  const used = usage.callsUsed ?? 0;
  const remaining = usage.callsRemaining ?? 0;
  const percent = usage.percentUsed ?? 0;

  return (
    <article className="clarivo-panel p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[#64748B] dark:text-[#A1A1AA]">
            Current plan
          </span>
          <div className="mt-1 flex flex-wrap items-center gap-3">
            <p className="text-[24px] font-semibold text-[#0F172A] dark:text-[#F5F7FA]">
              {loading ? "…" : plan.name || "Trial"}
            </p>
            {plan.customAllowance && <Badge tone="warning">Custom allowance</Badge>}
          </div>
          <p className="mt-1 text-[13px] text-[#64748B] dark:text-[#A1A1AA]">
            {loading ? "" : `${nf.format(limit)} calls / month · ${formatPrice(plan.priceInr)}`}
          </p>
        </div>
        <Badge tone="dark">Active</Badge>
      </div>

      <div className="mt-5">
        <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-1 text-[13px]">
          <span className="font-medium text-[#0F172A] dark:text-[#F5F7FA]">
            {loading ? "…" : `${nf.format(used)} of ${nf.format(limit)} calls used`}
          </span>
          <span className="text-[#64748B] dark:text-[#A1A1AA]">{usage.periodLabel || ""}</span>
        </div>
        <div
          className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-[#F5F7FA] dark:bg-[#171A1D] border border-[#E4E8EE] dark:border-[#252A30]"
          role="progressbar"
          aria-valuenow={Math.min(percent, 100)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full rounded-full bg-[#007BA7] transition-all"
            style={{ width: `${Math.min(percent, 100)}%` }}
          />
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[11.5px] text-[#64748B] dark:text-[#A1A1AA]">
          <span>{percent}% used</span>
          <span>{nf.format(remaining)} calls remaining</span>
        </div>
        {percent >= 80 && percent < 100 && (
          <p className="mt-3 rounded-[12px] border border-amber-200 bg-amber-50 dark:bg-amber-950/20 p-3 text-xs text-amber-800 dark:text-amber-300">
            You've used {percent}% of this month's call allowance. Consider upgrading before you run out.
          </p>
        )}
        {percent >= 100 && (
          <p className="mt-3 rounded-[12px] border border-red-200 bg-red-50 dark:bg-red-950/20 p-3 text-xs text-red-800 dark:text-red-300">
            This month's call allowance is used up. Upgrade the plan to add capacity.
          </p>
        )}
      </div>
    </article>
  );
}
