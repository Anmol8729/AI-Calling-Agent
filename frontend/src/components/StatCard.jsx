import { ArrowDownRight, ArrowUpRight } from "lucide-react";

export default function StatCard({ title, value, change, icon: Icon, tone = "dark", loading = false }) {
  const positive = !String(change).startsWith("-");
  const dark = tone === "dark";

  return (
    <div className={`rounded-3xl p-5 ${dark ? "border border-gray-900 bg-gray-950 shadow-2xl shadow-gray-950/15" : "panel"}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className={`text-sm ${dark ? "text-gray-400" : "text-gray-500"}`}>{title}</p>
          {/* A shimmer reads as "loading"; a bare "…" reads as broken. */}
          {loading ? (
            <div
              className={`mt-3 h-9 w-20 animate-pulse rounded-lg ${dark ? "bg-white/15" : "bg-gray-200/80"}`}
              aria-hidden="true"
            />
          ) : (
            <p className={`mt-3 text-3xl font-semibold tracking-tight ${dark ? "text-white" : "text-gray-950"}`}>{value}</p>
          )}
        </div>
        <div className={`grid h-11 w-11 place-items-center rounded-2xl ${dark ? "bg-white/10 text-white" : "bg-gray-100 text-gray-950"}`}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
      {/* Trend row only renders when a `change` is supplied — otherwise the
          wrapper alone would add empty space under every stat. */}
      {change ? (
        <div className={`mt-5 flex items-center gap-2 text-sm ${positive ? "text-emerald-500" : "text-red-500"}`}>
          {positive ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownRight className="h-4 w-4" />}
          <span>{change} vs last period</span>
        </div>
      ) : null}
    </div>
  );
}
