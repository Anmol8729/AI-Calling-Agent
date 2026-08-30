/**
 * Compact statistic card: coloured icon chip, label, value, one supporting line.
 *
 * Extracted from CallStatsRow when the Patients page needed the same card. Distinct
 * from StatCard, which is the large-value KPI tile the Dashboard uses — reshaping that
 * one to fit these rows would have changed the Dashboard too.
 *
 * The tone map stays unexported so this file exports only a component, which is what
 * React Fast Refresh requires.
 */

const TONES = {
  emerald: "bg-emerald-50 text-emerald-600",
  blue: "bg-blue-50 text-blue-600",
  violet: "bg-violet-50 text-violet-600",
  amber: "bg-amber-50 text-amber-600",
  red: "bg-red-50 text-red-600",
};

export default function MiniStat({ icon: Icon, tone = "blue", label, value, sub, subTone, loading = false }) {
  return (
    <div className="panel rounded-3xl p-4">
      <div className="flex items-start gap-3">
        <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-2xl ${TONES[tone] || TONES.blue}`}>
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
