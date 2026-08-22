import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, Radio, Search, FileText, Download } from "lucide-react";
import api from "../lib/api";
import CallFilterBar from "../components/CallFilterBar";
import { buildCallFilter, EMPTY_FILTERS } from "../lib/callFilters";
import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";

const fmtDuration = (s) => `${Math.floor((s || 0) / 60)}m ${(s || 0) % 60}s`;

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
  const [selected, setSelected] = useState(null); // call whose transcript is open

  const refresh = useCallback(async () => {
    setRefreshing(true);
    const [liveRes, logsRes] = await Promise.all([
      api.get("/stats/live").catch(() => null),
      api.get("/calls/logs").catch(() => null),
    ]);
    setLive(liveRes?.data?.success ? liveRes.data.data || [] : []);
    setLogs(logsRes?.data?.success ? (logsRes.data.data || []).map(mapLog) : []);
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

  const clearFilters = () => {
    setDraft(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
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
    { key: "caller", header: "Caller" },
    { key: "phone", header: "Phone", render: (row) => row.phone || "—" },
    { key: "duration", header: "Duration", render: (row) => fmtDuration(row.durationSec) },
    { key: "status", header: "Outcome", render: (row) => <Badge tone={toneFor(row.status)}>{row.status}</Badge> },
    { key: "date", header: "When", render: (row) => (row.date ? new Date(row.date).toLocaleString() : "—") },
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

      {/* Live calls */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
            <Radio className="h-3 w-3" /> Live
          </span>
          <h2 className="text-lg font-semibold text-gray-950">Happening now</h2>
        </div>
        {live.length === 0 ? (
          <div className="panel rounded-3xl p-6 text-sm text-gray-400">{loading ? "Checking for live calls…" : "No live calls right now."}</div>
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
        onApply={() => setApplied(draft)}
        onClear={clearFilters}
        statusOptions={statusOptions}
        disabled={loading}
      />

      {/* Call history */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-gray-950">Call history</h2>
        <div className="panel flex flex-col gap-3 rounded-3xl p-4 md:flex-row">
          <label className="flex flex-1 items-center gap-3 rounded-2xl border border-gray-200 px-3 py-2">
            <Search className="h-4 w-4 text-gray-400" />
            <input
              className="w-full border-0 outline-none"
              placeholder="Search by caller, phone, or outcome..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
        </div>
        {/* Without this, a filter that matches nothing is indistinguishable from a
            tenant who has taken no calls. */}
        {filtersActive && !loading && (
          <p className="text-xs text-gray-500" aria-live="polite">
            Showing {filtered.length} of {logs.length} calls
          </p>
        )}
        <DataTable
          columns={columns}
          rows={filtered}
          loading={loading}
          emptyTitle={filtersActive ? "No calls match these filters" : "No calls yet"}
          {...(filtersActive ? { emptyDescription: "Try widening the date range or clearing a filter." } : {})}
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
