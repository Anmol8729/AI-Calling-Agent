/**
 * Date keys, range presets and the search/filter predicate for the Appointments page.
 *
 * Kept out of the page so the date arithmetic — the part that goes subtly wrong — can be
 * tested without a browser.
 *
 * Only fields the Appointment record actually has are filtered on: status, and the day
 * the row belongs to. There is no doctor, type or source column on an appointment, so
 * there is nothing to filter by for those.
 */

/**
 * Local YYYY-MM-DD.
 *
 * Deliberately NOT toISOString().slice(0,10): that converts to UTC first, so a 00:30 IST
 * booking would be filed under the previous day.
 */
export const toDateKey = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/**
 * Which day a row belongs to. Time mode has a real timestamp; token mode only carries
 * token_date. Rows with neither (legacy free-text bookings) return "" and sort last.
 */
export const dateKeyOf = (row) => {
  if (row?.appointment_at) {
    const d = new Date(row.appointment_at);
    if (!Number.isNaN(d.getTime())) return toDateKey(d);
  }
  if (row?.token_date) return String(row.token_date).slice(0, 10);
  return "";
};

export const shiftDays = (n, base = new Date()) => {
  const d = new Date(base.getFullYear(), base.getMonth(), base.getDate() + n);
  return toDateKey(d);
};

export const DATE_PRESETS = [
  { key: "all", label: "All dates" },
  { key: "today", label: "Today" },
  { key: "tomorrow", label: "Tomorrow" },
  { key: "week", label: "This week" },
  { key: "month", label: "This month" },
  { key: "custom", label: "Custom" },
];

/**
 * Inclusive [from, to] day keys for a preset, or nulls for "all".
 *
 * The week runs Monday to Sunday (ISO). getDay() calls Sunday 0, so it is remapped —
 * without that, Sunday would start a new week and the day's bookings would vanish from
 * "This week" for anyone looking on a Sunday.
 */
export function resolveDateRange(preset, customFrom = "", customTo = "", base = new Date()) {
  const today = new Date(base.getFullYear(), base.getMonth(), base.getDate());

  switch (preset) {
    case "today":
      return { from: toDateKey(today), to: toDateKey(today) };
    case "tomorrow": {
      const t = shiftDays(1, today);
      return { from: t, to: t };
    }
    case "week": {
      const dow = (today.getDay() + 6) % 7; // Monday = 0
      const monday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - dow);
      const sunday = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 6);
      return { from: toDateKey(monday), to: toDateKey(sunday) };
    }
    case "month": {
      const first = new Date(today.getFullYear(), today.getMonth(), 1);
      // Day 0 of next month is the last day of this one, so February and leap years
      // need no special case.
      const last = new Date(today.getFullYear(), today.getMonth() + 1, 0);
      return { from: toDateKey(first), to: toDateKey(last) };
    }
    case "custom":
      // Either end may be left open, which reads naturally as "from then on" or
      // "up to then".
      return { from: customFrom || null, to: customTo || null };
    default:
      return { from: null, to: null };
  }
}

/**
 * Build the predicate for the current search, status and date range.
 *
 * A factory, so the parsing happens once per filter change rather than once per row.
 * Conditions are AND-ed.
 *
 * @param whenLabel formats a row for the free-text search, so searching the displayed
 *                  date string keeps working exactly as it did.
 */
export function buildAppointmentFilter({ query = "", status = "", from = null, to = null }, whenLabel = () => "") {
  const q = query.trim().toLowerCase();
  const wantStatus = status.trim().toLowerCase();

  return (a) => {
    if (wantStatus && (a.status || "").toLowerCase() !== wantStatus) return false;

    if (from || to) {
      const key = dateKeyOf(a);
      // An undated row cannot be placed in a range.
      if (!key) return false;
      // YYYY-MM-DD compares correctly as a string, so no Date objects per row.
      if (from && key < from) return false;
      if (to && key > to) return false;
    }

    if (!q) return true;
    return `${a.patient_name} ${a.reason || ""} ${a.status} ${whenLabel(a)}`.toLowerCase().includes(q);
  };
}
