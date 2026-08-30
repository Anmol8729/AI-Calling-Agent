import { Calendar, Filter, RotateCcw, Search } from "lucide-react";
import { Button } from "./ui/Button";
import { DURATION_RANGES } from "../lib/callFilters";

/**
 * Filter bar for the call history.
 *
 * Controlled and presentational: the page owns both the draft values edited here and
 * the applied values the table actually filters by. That split is what makes "Apply
 * Filters" mean something — editing a select does not re-filter the table until the
 * button is pressed, while the separate search box below stays live as it always was.
 *
 * `statusOptions` is passed in rather than hardcoded. The backend writes statuses like
 * "no-answer", "transferred" and "blocked", so a fixed list of friendly names would
 * offer filters that match no row and quietly return an empty table.
 */

/** A bordered control group: tiny caption above, borderless field inside. */
function Group({ label, icon: Icon, children }) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white px-3 py-2">
      <div className="flex items-center gap-1.5">
        {Icon && <Icon className="h-3 w-3 shrink-0 text-gray-400" />}
        <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">{label}</span>
      </div>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}

const FIELD = "w-full border-0 bg-transparent p-0 text-sm text-gray-900 outline-none placeholder:text-gray-400";

export default function CallFilterBar({ value, onChange, onApply, onClear, statusOptions = [], disabled = false }) {
  const set = (patch) => onChange({ ...value, ...patch });

  return (
    <form
      className="panel flex flex-col gap-3 rounded-3xl p-4 xl:flex-row xl:items-end"
      onSubmit={(e) => { e.preventDefault(); onApply(); }}
      aria-label="Filter call history"
    >
      {/* 6 columns so the date range can take two of them and the remaining four
          controls each take one, all on a single row at xl. */}
      <div className="grid flex-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {/* Widest control: two dates plus a separator never fit the same column as a
            single select, which is what squeezed them into "dd-mm-yyyy – d". */}
        <div className="sm:col-span-2 lg:col-span-2 xl:col-span-2">
          <Group label="Date range" icon={Calendar}>
            {/* Two native date inputs rather than a custom range picker: no new
                dependency, a real keyboard-accessible calendar, and the platform picker
                on mobile. */}
            <div className="flex items-center gap-1.5">
              <input
                type="date"
                className={`${FIELD} min-w-0 flex-1`}
                value={value.from}
                max={value.to || undefined}
                onChange={(e) => set({ from: e.target.value })}
                disabled={disabled}
                aria-label="From date"
              />
              <span className="shrink-0 text-gray-300">–</span>
              <input
                type="date"
                className={`${FIELD} min-w-0 flex-1`}
                value={value.to}
                min={value.from || undefined}
                onChange={(e) => set({ to: e.target.value })}
                disabled={disabled}
                aria-label="To date"
              />
            </div>
          </Group>
        </div>

        <Group label="Status">
          <select
            className={`${FIELD} -ml-0.5`}
            value={value.status}
            onChange={(e) => set({ status: e.target.value })}
            disabled={disabled}
            aria-label="Status"
          >
            <option value="">All Status</option>
            {statusOptions.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </Group>

        <Group label="Caller" icon={Search}>
          <input
            type="search"
            className={FIELD}
            placeholder="Search caller..."
            value={value.caller}
            onChange={(e) => set({ caller: e.target.value })}
            disabled={disabled}
            aria-label="Caller"
          />
        </Group>

        <Group label="Phone" icon={Search}>
          <input
            type="search"
            inputMode="tel"
            className={FIELD}
            placeholder="Search phone..."
            value={value.phone}
            onChange={(e) => set({ phone: e.target.value })}
            disabled={disabled}
            aria-label="Phone"
          />
        </Group>

        <Group label="Duration">
          <select
            className={`${FIELD} -ml-0.5`}
            value={value.duration}
            onChange={(e) => set({ duration: e.target.value })}
            disabled={disabled}
            aria-label="Duration"
          >
            <option value="">All Duration</option>
            {DURATION_RANGES.map((r) => (
              <option key={r.key} value={r.key}>{r.label}</option>
            ))}
          </select>
        </Group>
      </div>

      <div className="flex gap-2">
        <Button type="submit" className="flex-1 xl:flex-none" disabled={disabled}>
          <Filter className="h-4 w-4" /> Apply Filters
        </Button>
        <Button type="button" variant="secondary" className="flex-1 xl:flex-none" onClick={onClear} disabled={disabled}>
          <RotateCcw className="h-4 w-4" /> Clear
        </Button>
      </div>
    </form>
  );
}
