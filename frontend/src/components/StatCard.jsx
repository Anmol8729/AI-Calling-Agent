import { ArrowDownRight, ArrowUpRight } from "lucide-react";

export default function StatCard({ title, value, change, icon: Icon, tone = "light", loading = false }) {
  const positive = !String(change).startsWith("-");
  const isDarkTone = tone === "dark";

  return (
    <div
      className={`rounded-[22px] p-5 border transition-all ${
        isDarkTone
          ? "bg-[#007BA7] text-white border-[#007BA7] shadow-[0_2px_8px_rgba(0,123,167,0.25)]"
          : "clarivo-panel"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className={`text-[12px] font-medium ${isDarkTone ? "text-white/80" : "text-[#64748B] dark:text-[#A1A1AA]"}`}>
            {title}
          </p>
          {loading ? (
            <div
              className={`mt-2 h-9 w-20 animate-pulse rounded-lg ${isDarkTone ? "bg-white/20" : "bg-[#E4E8EE] dark:bg-[#252A30]"}`}
              aria-hidden="true"
            />
          ) : (
            <p className={`mt-2 text-[28px] font-semibold tabular-nums tracking-tight ${isDarkTone ? "text-white" : "text-[#0F172A] dark:text-[#F5F7FA]"}`}>
              {value}
            </p>
          )}
        </div>
        <div
          className={`grid h-10 w-10 place-items-center rounded-full ${
            isDarkTone ? "bg-white/15 text-white" : "bg-[#007BA7]/10 text-[#007BA7]"
          }`}
        >
          <Icon className="h-5 w-5" />
        </div>
      </div>
      {change ? (
        <div
          className={`mt-3 flex items-center gap-1.5 text-[11.5px] font-semibold ${
            positive ? "text-[#22C55E]" : "text-[#EF4444]"
          }`}
        >
          {positive ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
          <span>{change} vs last period</span>
        </div>
      ) : null}
    </div>
  );
}
