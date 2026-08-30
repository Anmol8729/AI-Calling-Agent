import { ArrowDownRight, ArrowUpRight, CheckCircle2, Clock, Phone, PhoneMissed, Radio } from "lucide-react";

/**
 * The five compact statistics above the call history.
 *
 * Separate from StatCard on purpose: that one is the large-value KPI tile the Dashboard
 * uses (3xl figure, 11x11 icon, "vs last period" row). Reshaping it to fit here would
 * change the Dashboard too. This is a smaller, denser card with a coloured icon chip
 * and one supporting line.
 *
 * Values come from deriveCallStats, which reads the data the page already fetched.
 */

const TONES = {
  emerald: "bg-emerald-50 text-emerald-600",
  blue: "bg-blue-50 text-blue-600",
  violet: "bg-violet-50 text-violet-600",
  amber: "bg-amber-50 text-amber-600",
  red: "bg-red-50 text-red-600",
};

function Card({ icon: Icon, tone, label, value, sub, subTone, loading }) {
  return (
    <div className="panel rounded-3xl p-4">
      <div className="flex items-start gap-3">
        <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-2xl ${TONES[tone]}`}>
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-gray-500">{label}</p>
          {loading ? (
            <div className="mt-1.5 h-7 w-16 animate-pulse rounded-lg bg-gray-200/80" aria-hidden="true" />
          ) : (
            <p className="mt-0.5 text-2xl font-semibold tracking-tight text-gray-950">{value}</p>
          )}
          {!loading && sub ? (
            <p className={`mt-0.5 truncate text-xs ${subTone || "text-gray-400"}`}>{sub}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default function CallStatsRow({ stats, loading = false }) {
  const s = stats || {};
  const change = s.todayChangePct;
  const up = typeof change === "number" && change >= 0;

  return (
    // 2-up on phones, 3-up on tablets, all 5 on wide screens. No horizontal scroll at
    // any width, which a single flex row would have forced on a phone.
    <section className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      <Card
        icon={Radio}
        tone="emerald"
        label="Live now"
        value={s.liveNow ?? 0}
        sub={(s.liveNow ?? 0) === 0 ? "No live calls" : "In progress"}
        loading={loading}
      />
      <Card
        icon={Phone}
        tone="blue"
        label="Total calls today"
        value={s.today ?? 0}
        // Omitted entirely when there were no calls yesterday — a percentage against
        // zero is undefined, and any number here would be made up.
        sub={
          typeof change === "number" ? (
            <span className="inline-flex items-center gap-1">
              {up ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
              {Math.abs(change)}% vs yesterday
            </span>
          ) : null
        }
        subTone={typeof change === "number" ? (up ? "text-emerald-600" : "text-red-600") : undefined}
        loading={loading}
      />
      <Card
        icon={Clock}
        tone="violet"
        label="Total duration today"
        value={s.durationToday ?? "0m 0s"}
        sub="Across today's calls"
        loading={loading}
      />
      <Card
        icon={CheckCircle2}
        tone="amber"
        label="Completed calls"
        value={s.completedToday ?? 0}
        sub={(s.today ?? 0) > 0 ? `${s.completedShare}% of today` : "No calls today"}
        loading={loading}
      />
      <Card
        icon={PhoneMissed}
        tone="red"
        label="Missed calls"
        value={s.missedToday ?? 0}
        sub={(s.today ?? 0) > 0 ? `${s.missedShare}% of today` : "No calls today"}
        loading={loading}
      />
    </section>
  );
}
