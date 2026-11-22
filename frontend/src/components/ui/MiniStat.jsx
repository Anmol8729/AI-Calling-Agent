const TONES = {
  emerald: "bg-[#22C55E]/10 text-[#22C55E]",
  blue: "bg-[#007BA7]/10 text-[#007BA7]",
  violet: "bg-[#6366F1]/10 text-[#6366F1]",
  amber: "bg-[#F59E0B]/10 text-[#F59E0B]",
  red: "bg-[#FF2D95]/10 text-[#FF2D95]",
};

export default function MiniStat({ icon: Icon, tone = "blue", label, value, sub, subTone, loading = false }) {
  return (
    <div className="clarivo-panel p-4">
      <div className="flex items-start gap-3">
        <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-full ${TONES[tone] || TONES.blue}`}>
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="truncate text-[11px] font-semibold uppercase tracking-wider text-[#64748B] dark:text-[#A1A1AA]">
            {label}
          </p>
          {loading ? (
            <div className="mt-1.5 h-7 w-16 animate-pulse rounded-lg bg-[#E4E8EE] dark:bg-[#252A30]" aria-hidden="true" />
          ) : (
            <p className="mt-0.5 text-[24px] font-semibold tracking-tight text-[#0F172A] dark:text-[#F5F7FA] tabular-nums">
              {value}
            </p>
          )}
          {!loading && sub ? (
            <p className={`mt-0.5 truncate text-[11.5px] ${subTone || "text-[#64748B] dark:text-[#A1A1AA]"}`}>
              {sub}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
