import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, Radio, Search, FileText, Download, Phone, CalendarDays, Headphones } from "lucide-react";
import api from "../lib/api";
import CallFilterBar from "../components/CallFilterBar";
import CallStatsRow from "../components/CallStatsRow";
import Pagination from "../components/Pagination";
import { buildCallFilter, EMPTY_FILTERS } from "../lib/callFilters";
import { deriveCallStats } from "../lib/callStats";
import { avatarTone, initialOf } from "../lib/avatar";
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
    <div className="flex flex-col gap-4">
      {/* 1. Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-1 py-0.5">
        <div>
          <h1 className="text-[26px] font-semibold text-[#0F172A] dark:text-[#F5F7FA] tracking-tight leading-tight">
            Calls
          </h1>
          <p className="text-[13.5px] text-[#475569] dark:text-[#A1A1AA] mt-0.5">
            Every conversation your AI receptionist handles, with who called and what happened.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={refresh} disabled={refreshing}>
            <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
            <span>{refreshing ? "Refreshing..." : "Refresh"}</span>
          </Button>
        </div>
      </div>

      {/* 2. Stats Row */}
      <CallStatsRow stats={stats} loading={loading} />

      {/* 3. Live calls */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 rounded-full bg-[#22C55E]/10 text-[#22C55E] px-2.5 py-0.5 text-[11px] font-semibold">
            <Radio className="h-3 w-3 animate-pulse" /> Live
          </span>
          <h2 className="text-[18px] font-semibold text-[#0F172A] dark:text-[#F5F7FA]">Happening now</h2>
        </div>
        {live.length === 0 ? (
          <div className="clarivo-panel p-5 relative overflow-hidden">
            <div className="relative flex items-start gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[#22C55E]/10 text-[#22C55E]">
                <Radio className="h-4 w-4" />
              </span>
              <div>
                <p className="text-sm font-semibold text-[#0F172A] dark:text-[#F5F7FA]">
                  {loading ? "Checking for live calls…" : "No live calls right now"}
                </p>
                <p className="mt-0.5 text-xs text-[#64748B] dark:text-[#A1A1AA]">
                  You'll see active calls here as they happen.
                </p>
              </div>
            </div>
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-3">
            {live.map((call) => (
              <article key={call.id} className="clarivo-card p-4">
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="text-base font-semibold text-[#0F172A] dark:text-[#F5F7FA]">{call.caller}</h3>
                    <p className="text-xs text-[#64748B] dark:text-[#A1A1AA]">{call.phone || "—"}</p>
                  </div>
                  <span className="flex items-center gap-1 rounded-full bg-[#22C55E]/10 px-2.5 py-0.5 text-[11px] font-semibold text-[#22C55E]">
                    <Radio className="h-3 w-3" /> Live
                  </span>
                </div>
                <div className="mt-3 space-y-1 text-xs text-[#64748B] dark:text-[#A1A1AA]">
                  <p>Exchanges: <span className="font-semibold text-[#0F172A] dark:text-[#F5F7FA]">{call.turns}</span></p>
                  <p>Started: <span className="font-semibold text-[#0F172A] dark:text-[#F5F7FA]">{call.startedAt ? new Date(call.startedAt).toLocaleTimeString() : "—"}</span></p>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* 4. Filters */}
      <CallFilterBar
        value={draft}
        onChange={setDraft}
        onApply={applyFilters}
        onClear={clearFilters}
        statusOptions={statusOptions}
        disabled={loading}
      />

      {/* 5. Call history */}
      <section className="space-y-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-[18px] font-semibold text-[#0F172A] dark:text-[#F5F7FA]">Call history</h2>
            <p className="mt-0.5 text-xs text-[#64748B] dark:text-[#A1A1AA]">
              Browse and review all calls handled by your AI receptionist.
            </p>
            {filtersActive && !loading && (
              <p className="mt-1 text-xs text-[#007BA7] font-medium" aria-live="polite">
                {filtered.length} of {logs.length} calls match
              </p>
            )}
          </div>
          <div className="relative sm:w-80">
            <Search className="h-4 w-4 text-[#64748B] dark:text-[#A1A1AA] absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              className="h-10 w-full pl-10 pr-4 rounded-full border border-[#E4E8EE] dark:border-[#252A30] bg-[#F5F7FA] dark:bg-[#171A1D] text-[13px] text-[#0F172A] dark:text-[#F5F7FA] placeholder-[#64748B] outline-none focus:ring-2 focus:ring-[#007BA7] transition-colors"
              placeholder="Search by caller, phone, or outcome..."
              value={query}
              onChange={(e) => changeQuery(e.target.value)}
              aria-label="Search calls"
            />
          </div>
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
                  <div className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm ${isCaller ? "bg-gray-100 text-gray-900" : "bg-brand-500 text-white"}`}>
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
