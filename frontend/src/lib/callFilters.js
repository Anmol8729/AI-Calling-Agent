/**
 * Shared shape and ranges for the call-history filters.
 *
 * Separate from CallFilterBar.jsx because a file that exports both components and
 * plain values breaks React Fast Refresh (react-refresh/only-export-components), and
 * the page needs these to build its filter predicate.
 */

/**
 * Duration buckets over `durationSec`, the seconds figure the mapped call log already
 * carries. Half-open [min, max) so the buckets tile the range with no gap and no
 * overlap: a 180s call is "3–5 min", never both "1–3" and "3–5".
 */
export const DURATION_RANGES = [
  { key: "under1", label: "Under 1 min", min: 0, max: 60 },
  { key: "1to3", label: "1–3 min", min: 60, max: 180 },
  { key: "3to5", label: "3–5 min", min: 180, max: 300 },
  { key: "over5", label: "5+ min", min: 300, max: Infinity },
];

/** Every filter off. Also the reset target for the Clear button. */
export const EMPTY_FILTERS = {
  from: "",
  to: "",
  status: "",
  caller: "",
  phone: "",
  duration: "",
};

/**
 * Build the call-history predicate for a set of applied filters plus the live search
 * text. Returns a function suitable for Array.prototype.filter.
 *
 * A factory rather than a per-row function so the parsing (dates, duration bucket,
 * digit-stripping) happens once per filter change instead of once per row.
 *
 * All conditions are AND-ed: selecting Completed + a date range + a duration bucket
 * keeps only the calls satisfying all three.
 */
export function buildCallFilter(applied = EMPTY_FILTERS, query = "") {
  const q = (query || "").trim().toLowerCase();
  const range = DURATION_RANGES.find((r) => r.key === applied.duration) || null;
  const callerQ = (applied.caller || "").trim().toLowerCase();
  const phoneQ = (applied.phone || "").replace(/\D/g, "");
  const status = (applied.status || "").trim().toLowerCase();

  // A date input yields "YYYY-MM-DD". Appending a time parses it in LOCAL time, which
  // is what someone picking "22 Aug" means. The bare string is parsed as UTC midnight,
  // which shifts the boundary by the timezone offset and drops or adds a day's calls.
  const from = applied.from ? new Date(`${applied.from}T00:00:00`) : null;
  const to = applied.to ? new Date(`${applied.to}T23:59:59.999`) : null;

  return (l) => {
    // The original search behaviour, unchanged: caller, phone and outcome in one box.
    if (q && !`${l.caller} ${l.phone} ${l.status}`.toLowerCase().includes(q)) return false;
    if (status && (l.status || "").toLowerCase() !== status) return false;
    if (callerQ && !(l.caller || "").toLowerCase().includes(callerQ)) return false;
    // Digits only, so "87870 27039" and "+918787027039" match each other.
    if (phoneQ && !(l.phone || "").replace(/\D/g, "").includes(phoneQ)) return false;
    if (range) {
      const d = l.durationSec || 0;
      if (d < range.min || d >= range.max) return false;
    }
    if (from || to) {
      if (!l.date) return false; // an undated call cannot be placed in a range
      const t = new Date(l.date);
      if (from && t < from) return false;
      if (to && t > to) return false;
    }
    return true;
  };
}
