/**
 * The Calls page header statistics, derived from data the page already loaded.
 *
 * Deliberately no new request: /calls/logs already returns the history and
 * /stats/live the active calls, so everything here is arithmetic over those. That also
 * means the cards can never disagree with the table below them.
 *
 * Timestamps are parsed with `new Date(...)` and compared on the LOCAL calendar day,
 * matching how the table renders them (`toLocaleString()`). Counting "today" any other
 * way would put a call in a card but not in the row list, or the reverse.
 */

/** Statuses the app already treats as a failed call — the backend has no "missed". */
const MISSED_STATUSES = new Set(["failed", "no-answer", "no_answer", "blocked"]);

const dayKey = (d) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;

/** "42m 18s", or "1h 05m" once it passes an hour, which reads better than "65m 3s". */
export function formatTotalDuration(totalSec) {
  const s = Math.max(0, Math.round(totalSec || 0));
  if (s >= 3600) {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return `${h}h ${String(m).padStart(2, "0")}m`;
  }
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

export function deriveCallStats(logs = [], live = []) {
  const now = new Date();
  const todayKey = dayKey(now);
  // Constructed rather than subtracting 86400000 so month and year rollover is handled.
  const yesterdayKey = dayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1));

  let today = 0;
  let yesterday = 0;
  let durationTodaySec = 0;
  let completedToday = 0;
  let missedToday = 0;

  for (const l of logs) {
    if (!l?.date) continue; // an undated row cannot be placed on a day
    const key = dayKey(new Date(l.date));
    if (key === yesterdayKey) yesterday += 1;
    if (key !== todayKey) continue;

    today += 1;
    durationTodaySec += l.durationSec || 0;
    const status = (l.status || "").toLowerCase();
    if (status === "completed") completedToday += 1;
    else if (MISSED_STATUSES.has(status)) missedToday += 1;
  }

  const share = (n) => (today > 0 ? Math.round((n / today) * 1000) / 10 : 0);

  return {
    liveNow: live.length,
    today,
    yesterday,
    // null, not 0: with no calls yesterday a percentage change is undefined, and
    // showing "+100%" or "0%" would both be inventions. The card omits the line.
    todayChangePct: yesterday > 0 ? Math.round(((today - yesterday) / yesterday) * 100) : null,
    durationTodaySec,
    durationToday: formatTotalDuration(durationTodaySec),
    completedToday,
    completedShare: share(completedToday),
    missedToday,
    missedShare: share(missedToday),
  };
}
