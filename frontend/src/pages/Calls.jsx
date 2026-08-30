import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, Radio, Search, FileText, Download, Phone, CalendarDays, Headphones } from "lucide-react";
import api from "../lib/api";
import CallFilterBar from "../components/CallFilterBar";
import CallStatsRow from "../components/CallStatsRow";
import Pagination from "../components/Pagination";
import { buildCallFilter, EMPTY_FILTERS } from "../lib/callFilters";
import { deriveCallStats } from "../lib/callStats";
import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";

const PAGE_SIZE = 10;

const fmtDuration = (s) => `${Math.floor((s || 0) / 60)}m ${(s || 0) % 60}s`;

// "no-answer" -> "No answer". The stored values are lowercase and hyphenated; printing
// them verbatim in a badge reads like a database dump rather than an outcome.
const humanizeStatus = (s) => {
  const t = (s || "unknown").replace(/[-_]+/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
};

const initialOf = (s) => (s || "?").trim().charAt(0).toUpperCase();

// Tint derived from the caller string, so one caller keeps the same colour across rows
// and refreshes instead of shuffling on every render.
const AVATAR_TONES = [
  "bg-blue-50 text-blue-700",
  "bg-emerald-50 text-emerald-700",
  "bg-violet-50 text-violet-700",
  "bg-amber-50 text-amber-700",
  "bg-rose-50 text-rose-700",
];
const avatarTone = (s) => {
  let h = 0;
  for (let i = 0; i < (s || "").length; i += 1) h = (h * 31 + s.charCodeAt(i)) % 997;
  return AVATAR_TONES[h % AVATAR_TONES.length];
};

const toneFor = (status) => {
  const s = (status || "").toLowerCase();
  if (["completed", "active"].includes(s)) return "success";
  if (s === "transferred") return "warning";
  if (["failed", "no-answer", "blocked"].includes(s)) return "danger";
  return "neutral";
};

const mapLog = (log) => ({
  id: log.call_id || log.id,
  caller: log.caller_name || log.phone || "Unknown",
  phone: log.phone || "",
  direction: log.direction || "inbound",
  durationSec: log.duration || 0,
  status: log.status || "unknown",
  transcript: Array.isArray(log.transcript) ? log.transcript : [],
  date: log.created_at || null,
});

export default function Calls() {
  const [live, setLive] = useState([]);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [query, setQuery] = useState("");
  // Two copies on purpose: `draft` is what the filter bar edits, `applied` is what the
  // table filters by. That is what makes "Apply Filters" a real action. The search box
  // stays live, as it was before.
  const [draft, setDraft] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState(null); // call whose transcript is open

  const refresh = useCallback(async () => {
    setRefreshing(true);
    const [liveRes, logsRes] = await Promise.all([
      api.get("/stats/live").catch(() => null),
      api.get("/calls/logs").catch(() => null),
    ]);
    setLive(liveRes?.data?.success ? liveRes.data.data || [] : []);
    setLogs(logsRes?.data?.success ? (logsRes.data.data || []).map(mapLog) : []);
    setPage(1);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    api.get("/stats/live")
      .then((r) => setLive(r.data?.success ? r.data.data || [] : []))
      .catch(() => setLive([]));
    api.get("/calls/logs")
      .then((r) => setLogs(r.data?.success ? (r.data.data || []).map(mapLog) : []))
      .catch(() => setLogs([]))
      .finally(() => setLoading(false));
  }, []);

  // Offer only statuses that actually occur in this tenant's history. A fixed list
  // would advertise outcomes the backend never writes, so choosing one would return an
  // empty table with no explanation.
  const statusOptions = useMemo(
    () => [...new Set(logs.map((l) => (l.status || "").trim()).filter(Boolean))].sort(),
    [logs],
  );

  // The original search predicate, extended with the filter bar rather than replaced,
  // so both narrow the same list and combining them needs no special cases.
  const filtered = useMemo(
    () => logs.filter(buildCallFilter(applied, query)),
    [query, logs, applied],
  );

  const filtersActive = Object.values(applied).some(Boolean) || !!query.trim();

  // Header figures, computed from the rows already loaded — no extra request, and they
  // therefore cannot disagree with the table below.
  const stats = useMemo(() => deriveCallStats(logs, live), [logs, live]);

  // Clamped during render rather than reset from an effect. A narrower result set can be
  // shorter than the current offset, and the page has to be valid on THIS render — an
  // effect would paint one empty table first, and setState in an effect body cascades.
  // Every control that changes the result set also sends the user back to page 1.
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);

  const paged = useMemo(
    () => filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE),
    [filtered, safePage],
  );

  const changeQuery = (v) => {
    setQuery(v);
    setPage(1);
  };

  const applyFilters = () => {
    setApplied(draft);
    setPage(1);
  };

  const clearFilters = () => {
    setDraft(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    setPage(1);
  };

  const downloadCall = (row) => {
    const payload = {
      call_id: row.id, caller: row.caller, phone: row.phone, direction: row.direction,
      status: row.status, duration: fmtDuration(row.durationSec), date: row.date, transcript: row.transcript,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `call-${row.id}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const columns = [
    {
      key: "caller",
      header: "Caller",
      render: (row) => (
        <div className="flex items-center gap-2.5">
          <span
            className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-semibold ${avatarTone(row.caller)}`}
            aria-hidden="true"
          >
            {initialOf(row.caller)}
          </span>
          <span className="font-medium text-gray-950">{row.caller}</span>
        </div>
      ),
    },
    {
      key: "phone",
      header: "Phone",
      render: (row) =>
        row.phone ? (
          <span className="inline-flex items-center gap-1.5">
            <Phone className="h-3.5 w-3.5 shrink-0 text-gray-400" aria-hidden="true" />
            {row.phone}
          </span>
        ) : (
          "—"
        ),
    },
    { key: "duration", header: "Duration", render: (row) => fmtDuration(row.durationSec) },
    { key: "status", header: "Outcome", render: (row) => <Badge tone={toneFor(row.status)}>{humanizeStatus(row.status)}</Badge> },
    {
      key: "date",
      header: "When",
      render: (row) =>
        row.date ? (
          <span className="inline-flex items-center gap-1.5">
            <CalendarDays className="h-3.5 w-3.5 shrink-0 text-gray-400" aria-hidden="true" />
            {new Date(row.date).toLocaleString()}
          </span>
        ) : (
          "—"
        ),
    },
    {
      key: "actions",
      header: "Actions",
      render: (row) => (
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" title={row.transcript.length ? "View transcript" : "No transcript"} disabled={!row.transcript.length} onClick={() => setSelected(row)}>
            <FileText className="h-3.5 w-3.5" />
          </Button>
          <Button variant="secondary" size="sm" title="Download call (JSON)" onClick={() => downloadCall(row)}>
            <Download className="h-3.5 w-3.5" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-gray-950">Calls</h1>
          <p className="mt-2 text-sm text-gray-500">Live calls happening now, and the full history handled by your AI receptionist.</p>
        </div>
        <Button variant="secondary" onClick={refresh} disabled={refreshing}>
          <RefreshCw className="h-4 w-4" /> {refreshing ? "Refreshing..." : "Refresh"}
        </Button>
      </div>

      <CallStatsRow stats={stats} loading={loading} />

      {/* Live calls */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
            <Radio className="h-3 w-3" /> Live
          </span>
          <h2 className="text-lg font-semibold text-gray-950">Happening now</h2>
        </div>
        {live.length === 0 ? (
          <div className="relative overflow-hidden rounded-3xl border border-emerald-100 bg-emerald-50/60 p-6">
            <div className="relative flex items-start gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-2xl bg-emerald-100 text-emerald-700">
                <Radio className="h-4 w-4" />
              </span>
              <div>
                <p className="text-sm font-semibold text-gray-950">
                  {loading ? "Checking for live calls…" : "No live calls right now"}
                </p>
                <p className="mt-0.5 text-sm text-emerald-900/60">
                  You'll see active calls here as they happen.
                </p>
              </div>
            </div>
            {/* Decorative, and hidden on phones where it would sit under the text. */}
            <Headphones
              className="pointer-events-none absolute -bottom-4 right-5 hidden h-24 w-24 text-emerald-600/15 sm:block"
              aria-hidden="true"
            />
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-3">
            {live.map((call) => (
              <article key={call.id} className="panel rounded-3xl p-5">
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="text-lg font-semibold text-gray-950">{call.caller}</h3>
                    <p className="text-sm text-gray-500">{call.phone || "—"}</p>
                  </div>
                  <span className="flex items-center gap-1 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
                    <Radio className="h-3 w-3" /> Live
                  </span>
                </div>
                <div className="mt-4 space-y-1 text-sm text-gray-500">
                  <p>Exchanges: <span className="text-gray-900">{call.turns}</span></p>
                  <p>Started: <span className="text-gray-900">{call.startedAt ? new Date(call.startedAt).toLocaleTimeString() : "—"}</span></p>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* Filters sit above the Call history heading, matching the reference. */}
      <CallFilterBar
        value={draft}
        onChange={setDraft}
        onApply={applyFilters}
        onClear={clearFilters}
        statusOptions={statusOptions}
        disabled={loading}
      />

      {/* Call history */}
      <section className="space-y-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-950">Call history</h2>
            <p className="mt-0.5 text-sm text-gray-500">
              Browse and review all calls handled by your AI receptionist.
            </p>
            {/* Without this, a filter that matches few rows is indistinguishable from a
                tenant who has barely taken any calls. */}
            {filtersActive && !loading && (
              <p className="mt-1 text-xs text-gray-500" aria-live="polite">
                {filtered.length} of {logs.length} calls match
              </p>
            )}
          </div>
          <label className="flex items-center gap-2.5 rounded-2xl border border-gray-200 bg-white px-3 py-2 sm:w-80">
            <Search className="h-4 w-4 shrink-0 text-gray-400" />
            <input
              className="w-full border-0 bg-transparent p-0 text-sm outline-none placeholder:text-gray-400"
              placeholder="Search by caller, phone, or outcome..."
              value={query}
              onChange={(e) => changeQuery(e.target.value)}
              aria-label="Search calls"
            />
          </label>
        </div>
        <DataTable
          columns={columns}
          rows={paged}
          loading={loading}
          emptyTitle={filtersActive ? "No calls match these filters" : "No calls yet"}
          {...(filtersActive ? { emptyDescription: "Try widening the date range or clearing a filter." } : {})}
        />
        <Pagination
          page={safePage}
          pageSize={PAGE_SIZE}
          total={filtered.length}
          onChange={setPage}
          unit="calls"
        />
      </section>

      <Modal
        open={!!selected}
        onClose={() => setSelected(null)}
        title="Call transcript"
        description={selected ? `${selected.caller} · ${fmtDuration(selected.durationSec)} · ${selected.date ? new Date(selected.date).toLocaleString() : ""}` : ""}
        footer={
          <div className="flex justify-end gap-3">
            {selected && (
              <Button variant="secondary" onClick={() => downloadCall(selected)}>
                <Download className="h-4 w-4" /> Download
              </Button>
            )}
            <Button onClick={() => setSelected(null)}>Close</Button>
          </div>
        }
      >
        {selected && selected.transcript.length > 0 ? (
          <div className="space-y-3">
            {selected.transcript.map((turn, i) => {
              const isCaller = (turn.role || "").toLowerCase() === "user";
              return (
                <div key={i} className={`flex ${isCaller ? "justify-start" : "justify-end"}`}>
                  <div className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm ${isCaller ? "bg-gray-100 text-gray-900" : "bg-gray-950 text-white"}`}>
                    <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider opacity-60">{isCaller ? "Caller" : "AI Receptionist"}</p>
                    {turn.content}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-gray-400">No transcript recorded for this call.</p>
        )}
      </Modal>
    </div>
  );
}
