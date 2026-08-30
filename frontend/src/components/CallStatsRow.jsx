import { ArrowDownRight, ArrowUpRight, CheckCircle2, Clock, Phone, PhoneMissed, Radio } from "lucide-react";
import MiniStat from "./ui/MiniStat";

/**
 * The five statistics above the call history.
 *
 * The card itself is ui/MiniStat, shared with the Patients page. Values come from
 * deriveCallStats, which reads the data the page already fetched.
 */
export default function CallStatsRow({ stats, loading = false }) {
  const s = stats || {};
  const change = s.todayChangePct;
  const up = typeof change === "number" && change >= 0;

  return (
    // 2-up on phones, 3-up on tablets, all 5 on wide screens. No horizontal scroll at
    // any width, which a single flex row would have forced on a phone.
    <section className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      <MiniStat
        icon={Radio}
        tone="emerald"
        label="Live now"
        value={s.liveNow ?? 0}
        sub={(s.liveNow ?? 0) === 0 ? "No live calls" : "In progress"}
        loading={loading}
      />
      <MiniStat
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
      <MiniStat
        icon={Clock}
        tone="violet"
        label="Total duration today"
        value={s.durationToday ?? "0m 0s"}
        sub="Across today's calls"
        loading={loading}
      />
      <MiniStat
        icon={CheckCircle2}
        tone="amber"
        label="Completed calls"
        value={s.completedToday ?? 0}
        sub={(s.today ?? 0) > 0 ? `${s.completedShare}% of today` : "No calls today"}
        loading={loading}
      />
      <MiniStat
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
