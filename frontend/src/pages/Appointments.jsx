import {
  CalendarDays, CalendarPlus, ChevronDown, ChevronUp, Clock, Download, Loader2, RotateCcw,
  Search, SlidersHorizontal, Trash2,
} from "lucide-react";
import { useMemo, useState, useEffect, useCallback } from "react";
import api from "../lib/api";
import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import Pagination from "../components/Pagination";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { avatarTone, initialOf } from "../lib/avatar";
import { dateStamp, downloadCsv, toCsv } from "../lib/csv";
import {
  buildAppointmentFilter, dateKeyOf, DATE_PRESETS, resolveDateRange, shiftDays,
} from "../lib/appointmentFilters";
import { useLabels, useClinicStore } from "../store/clinicStore";
import { useAuthStore } from "../store/authStore";

const emptyForm = { patient_name: "", phone: "", appointment_at: "", duration_min: 30, reason: "" };
const DURATIONS = [15, 30, 45, 60, 90];
const PAGE_SIZES = [10, 25, 50];

function extractError(err) {
  const d = err?.response?.data;
  if (d) {
    if (d.message) return d.message;
    if (typeof d.error === "string" && d.error) return d.error;
    if (d.detail) {
      if (Array.isArray(d.detail)) {
        return d.detail.map((x) => `${x.loc?.[x.loc.length - 1]}: ${x.msg}`).join(", ");
      }
      return d.detail;
    }
  }
  if (err?.response?.status === 503) return "Database is not configured on the server.";
  return "Could not reach the server.";
}

const statusTone = (status) => {
  switch (status) {
    case "completed": return "success";
    case "cancelled": return "danger";
    case "scheduled": return "warning";
    default: return "neutral";
  }
};

const fmtWhen = (row) => {
  if (row.appointment_at) {
    const d = new Date(row.appointment_at);
    if (!Number.isNaN(d.getTime())) return d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  }
  return row.appointment_date || "—";
};

// toDateKey / dateKeyOf / shiftDays now live in lib/appointmentFilters.js — the filter
// predicate needs the same definitions, and two copies of date-key logic would drift.

// Time only, for the table's own column. The full date is already the group heading.
const fmtTime = (row) => {
  if (row.appointment_at) {
    const d = new Date(row.appointment_at);
    if (!Number.isNaN(d.getTime())) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return "—";
};

// "Today" / "Tomorrow" are what people scan for; anything else gets a full date.
const groupLabel = (key) => {
  if (!key) return "No date set";
  if (key === shiftDays(0)) return "Today";
  if (key === shiftDays(1)) return "Tomorrow";
  if (key === shiftDays(-1)) return "Yesterday";
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString([], {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
};

// Only fields an Appointment actually carries. No Email, Doctor or Source column: an
// appointment record has none of those, and inventing them would put made-up data in a
// file people will treat as a record. No id or clinic_id either — internal keys.
const CSV_COLUMNS = [
  { header: "Token", value: (r) => (r.token_number != null ? r.token_number : "") },
  { header: "Name", value: (r) => r.patient_name },
  { header: "Phone", value: (r) => r.phone || "" },
  { header: "Reason", value: (r) => r.reason || "" },
  { header: "Date", value: (r) => dateKeyOf(r) },
  { header: "Time", value: (r) => (fmtTime(r) === "—" ? "" : fmtTime(r)) },
  { header: "Length (min)", value: (r) => r.duration_min || "" },
  { header: "Status", value: (r) => r.status || "" },
];

export default function Appointments() {
  const labels = useLabels();
  const bookingMode = useClinicStore((s) => s.clinic?.booking_mode) || "time";
  const isToken = bookingMode === "token";
  // Staff can book, but cancelling or moving a booking is a doctor/manager action.
  // The API enforces it too (require_non_staff on PUT, PUT /reschedule and DELETE);
  // this just keeps the UI from offering a button that would 403.
  const user = useAuthStore((state) => state.user);
  const isStaff = user?.role === "staff";
  const [list, setList] = useState([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [datePreset, setDatePreset] = useState("all");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);
  const [exporting, setExporting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(false);

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  const [contacts, setContacts] = useState([]);
  const [selectedContactId, setSelectedContactId] = useState("");

  const [banner, setBanner] = useState(null);
  const [busyId, setBusyId] = useState(null);
  // Cancelling is confirmed first — it is one click next to "Reschedule" and the
  // patient has already been told a time.
  const [confirmRow, setConfirmRow] = useState(null);
  // Permanent delete is a separate confirm: cancelling keeps the record, this does not.
  const [deleteRow, setDeleteRow] = useState(null);

  // Token/queue mode state ("Now serving" panel)
  const [queue, setQueue] = useState({ current_number: 0, total_issued: 0 });
  const [queueBusy, setQueueBusy] = useState(false);
  const [setNum, setSetNum] = useState("");

  // Reschedule modal
  const [reRow, setReRow] = useState(null);
  const [reAt, setReAt] = useState("");
  const [reDur, setReDur] = useState(30);
  const [reSubmitting, setReSubmitting] = useState(false);
  const [reError, setReError] = useState("");

  const loadAppointments = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/appointments/");
      if (res.data && res.data.success) {
        setList(res.data.data || []);
        setLive(true);
      } else {
        setList([]);
        setLive(false);
      }
    } catch {
      setList([]);
      setLive(false);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadQueue = useCallback(async () => {
    try {
      const res = await api.get("/appointments/queue");
      if (res.data?.success && res.data.data?.status) setQueue(res.data.data.status);
    } catch {
      /* ignore — panel just shows the last known values */
    }
  }, []);

  useEffect(() => {
    loadAppointments();
    api.get("/patients/")
      .then((r) => setContacts(r.data?.success ? r.data.data || [] : []))
      .catch(() => setContacts([]));
  }, [loadAppointments]);

  useEffect(() => {
    if (isToken) loadQueue();
  }, [isToken, loadQueue]);

  const queueNext = async () => {
    setQueueBusy(true);
    try {
      const res = await api.post("/appointments/queue/next");
      if (res.data?.success && res.data.data) setQueue((q) => ({ ...q, ...res.data.data }));
      else setBanner({ type: "error", text: res.data?.message || "Could not update the queue." });
    } catch (err) {
      setBanner({ type: "error", text: extractError(err) });
    } finally {
      setQueueBusy(false);
    }
  };

  const queueSetTo = async (n) => {
    setQueueBusy(true);
    try {
      const res = await api.post("/appointments/queue/set", { number: Number(n) || 0 });
      if (res.data?.success && res.data.data) {
        setQueue((q) => ({ ...q, ...res.data.data }));
        setSetNum("");
      } else {
        setBanner({ type: "error", text: res.data?.message || "Could not update the queue." });
      }
    } catch (err) {
      setBanner({ type: "error", text: extractError(err) });
    } finally {
      setQueueBusy(false);
    }
  };

  const onSelectContact = (event) => {
    const id = event.target.value;
    setSelectedContactId(id);
    if (id) {
      const c = contacts.find((x) => String(x.id) === id);
      if (c) setForm((prev) => ({ ...prev, patient_name: c.name || "", phone: c.phone || "" }));
    } else {
      setForm((prev) => ({ ...prev, patient_name: "", phone: "" }));
    }
  };

  const openBooking = () => {
    setFormError("");
    setForm(emptyForm);
    setSelectedContactId("");
    setOpen(true);
  };

  // Statuses offered come from the data, so the filter can never advertise one that no
  // row has and then return an empty list with no explanation.
  const statusOptions = useMemo(
    () => [...new Set(list.map((a) => (a.status || "").trim()).filter(Boolean))].sort(),
    [list],
  );

  const range = useMemo(
    () => resolveDateRange(datePreset, customFrom, customTo),
    [datePreset, customFrom, customTo],
  );

  // fmtWhen is passed in so searching the displayed date string keeps working as before.
  const filtered = useMemo(
    () => list.filter(buildAppointmentFilter({ query, status: statusFilter, ...range }, fmtWhen)),
    [list, query, statusFilter, range],
  );

  const filtersActive = !!(query.trim() || statusFilter || datePreset !== "all");

  const clearAll = () => {
    setQuery("");
    setStatusFilter("");
    setDatePreset("all");
    setCustomFrom("");
    setCustomTo("");
    setPage(1);
  };

  // Clamped during render rather than reset from an effect: a narrower result set can be
  // shorter than the current offset and the page must be valid on this same render.
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const paged = useMemo(
    () => filtered.slice((safePage - 1) * pageSize, safePage * pageSize),
    [filtered, safePage, pageSize],
  );

  // Exports `filtered`, never `paged`: every matching row across all pages.
  const exportCsv = () => {
    setBanner(null);
    if (filtered.length === 0) {
      setBanner({ type: "error", text: `No ${labels.bookings.toLowerCase()} found to export.` });
      return;
    }
    setExporting(true);
    try {
      const slug = labels.bookings.toLowerCase().replace(/[^a-z0-9]+/g, "-");
      downloadCsv(`clarivo-${slug}-${dateStamp()}.csv`, toCsv(CSV_COLUMNS, filtered));
      setBanner({
        type: "success",
        text: `Exported ${filtered.length} ${labels.bookings.toLowerCase()}${
          filtersActive ? " matching the current filters" : ""
        }.`,
      });
    } catch {
      setBanner({ type: "error", text: `Unable to export ${labels.bookings.toLowerCase()}. Please try again.` });
    } finally {
      setExporting(false);
    }
  };

  // One section per date. Sorted ascending so the nearest day is at the top, with
  // undated rows last — the list arrives ordered by time, so rows inside a group
  // keep that order for free.
  // Groups are built from the CURRENT PAGE, so "Showing 1 to 10 of N" counts
  // appointments rather than date sections, and a group is never split across pages in a
  // way that shows a heading with no rows under it.
  const groups = useMemo(() => {
    const buckets = new Map();
    for (const row of paged) {
      const key = dateKeyOf(row);
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(row);
    }
    return [...buckets.entries()]
      .sort(([a], [b]) => {
        if (a === b) return 0;
        if (!a) return 1; // undated last
        if (!b) return -1;
        return a < b ? -1 : 1;
      })
      .map(([key, rows]) => ({ key, rows, label: groupLabel(key) }));
  }, [paged]);

  const updateField = (key) => (event) => setForm((prev) => ({ ...prev, [key]: event.target.value }));

  const submitAppointment = async () => {
    setFormError("");
    if (!form.patient_name.trim()) {
      setFormError(isToken ? "Name is required." : "Name and date/time are required.");
      return;
    }
    if (!isToken && !form.appointment_at) {
      setFormError("Name and date/time are required.");
      return;
    }
    const payload = {
      patient_id: selectedContactId || "manual",
      patient_name: form.patient_name.trim(),
      phone: form.phone.trim() || null,
      reason: form.reason.trim() || null,
      status: "scheduled",
    };
    if (!isToken) {
      payload.appointment_at = form.appointment_at; // datetime-local value = naive local wall time
      payload.duration_min = Number(form.duration_min) || 30;
    }
    setSubmitting(true);
    try {
      const res = await api.post("/appointments/", payload);
      if (res.data && res.data.success) {
        setOpen(false);
        setForm(emptyForm);
        setSelectedContactId("");
        const tokenNo = res.data.data?.token_number;
        setBanner({
          type: "success",
          text: isToken && tokenNo != null
            ? `Token #${tokenNo} given to ${payload.patient_name}.`
            : `${labels.booking} booked for ${payload.patient_name}.`,
        });
        loadAppointments();
        if (isToken) loadQueue();
      } else {
        setFormError((res.data && res.data.message) || "Could not book.");
      }
    } catch (err) {
      // A 409 means the slot overlaps an existing booking (time mode).
      setFormError(extractError(err));
    } finally {
      setSubmitting(false);
    }
  };

  const openReschedule = (row) => {
    setReError("");
    setReRow(row);
    setReAt(row.appointment_at ? String(row.appointment_at).slice(0, 16) : "");
    setReDur(row.duration_min || 30);
  };

  const submitReschedule = async () => {
    if (!reAt) {
      setReError("Pick a new date & time.");
      return;
    }
    setReSubmitting(true);
    setReError("");
    try {
      const res = await api.put(`/appointments/${reRow.id}/reschedule`, {
        appointment_at: reAt,
        duration_min: Number(reDur) || 30,
      });
      if (res.data?.success) {
        setReRow(null);
        setBanner({ type: "success", text: `Rescheduled ${labels.booking.toLowerCase()} for ${reRow.patient_name}.` });
        loadAppointments();
      } else {
        setReError(res.data?.message || "Could not reschedule.");
      }
    } catch (err) {
      setReError(extractError(err));
    } finally {
      setReSubmitting(false);
    }
  };

  const cancelAppointment = async (row) => {
    setBanner(null);
    setBusyId(row.id);
    try {
      const res = await api.delete(`/appointments/${row.id}`);
      if (res.data && res.data.success) {
        setConfirmRow(null);
        setBanner({ type: "success", text: `Cancelled ${labels.booking.toLowerCase()} for ${row.patient_name}.` });
        loadAppointments();
        if (isToken) loadQueue();
      } else {
        setBanner({ type: "error", text: (res.data && res.data.message) || "Could not cancel." });
      }
    } catch (err) {
      // A 403 means the server disagreed with the UI about this user's role.
      setBanner({ type: "error", text: extractError(err) });
    } finally {
      setBusyId(null);
    }
  };

  const deleteAppointment = async (row) => {
    setBanner(null);
    setBusyId(row.id);
    try {
      const res = await api.delete(`/appointments/${row.id}/permanent`);
      if (res.data && res.data.success) {
        setDeleteRow(null);
        setBanner({ type: "success", text: `Deleted ${labels.booking.toLowerCase()} for ${row.patient_name}.` });
        loadAppointments();
        if (isToken) loadQueue();
      } else {
        setBanner({ type: "error", text: (res.data && res.data.message) || "Could not delete." });
      }
    } catch (err) {
      setBanner({ type: "error", text: extractError(err) });
    } finally {
      setBusyId(null);
    }
  };

  const actionsColumn = {
    key: "actions",
    header: "Actions",
    render: (row) => {
      // Staff see the schedule but get no controls over it.
      if (isStaff) return <span className="text-xs text-gray-400">View only</span>;

      // An already-cancelled row has nothing left to cancel or move, but it is
      // exactly the kind of clutter worth removing — so Delete stays available.
      if (row.status === "cancelled") {
        return (
          <Button variant="ghost" size="sm" disabled={busyId === row.id} onClick={() => setDeleteRow(row)}>
            <Trash2 className="h-3.5 w-3.5" /> {busyId === row.id ? "..." : "Delete"}
          </Button>
        );
      }

      return (
        <div className="flex items-center gap-2">
          {!isToken && (
            <Button variant="secondary" size="sm" onClick={() => openReschedule(row)}>Reschedule</Button>
          )}
          <Button variant="secondary" size="sm" disabled={busyId === row.id} onClick={() => setConfirmRow(row)}>
            {busyId === row.id ? "..." : "Cancel"}
          </Button>
          {/* Icon-only, so Cancel reads as the ordinary action and delete does not
              compete with it. Same confirmation modal as before. */}
          <button
            type="button"
            disabled={busyId === row.id}
            onClick={() => setDeleteRow(row)}
            title={`Delete ${row.patient_name}'s ${labels.booking.toLowerCase()}`}
            aria-label={`Delete ${row.patient_name}'s ${labels.booking.toLowerCase()}`}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-gray-200 text-gray-400 transition hover:border-red-200 hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-40"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      );
    },
  };

  const tokenColumn = {
    key: "token_number",
    header: "Token",
    render: (row) =>
      row.token_number != null ? (
        <span className="inline-flex items-center rounded-full bg-violet-50 px-2.5 py-1 text-xs font-semibold tabular-nums text-violet-700 ring-1 ring-violet-100">
          #{row.token_number}
        </span>
      ) : (
        "—"
      ),
  };

  const nameColumn = {
    key: "patient_name",
    header: "Name",
    render: (row) => (
      <div className="flex items-center gap-2.5">
        <span
          className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-semibold ${avatarTone(row.patient_name)}`}
          aria-hidden="true"
        >
          {initialOf(row.patient_name)}
        </span>
        <span className="font-medium text-gray-950">{row.patient_name}</span>
      </div>
    ),
  };

  const reasonColumn = {
    key: "reason",
    header: "Reason",
    render: (row) => (row.reason ? row.reason : <span className="text-gray-400">—</span>),
  };

  const statusColumn = {
    key: "status",
    header: "Status",
    render: (row) => <Badge tone={statusTone(row.status)}>{row.status}</Badge>,
  };

  const timeColumn = {
    key: "appointment_at",
    header: "Time",
    render: (row) => {
      const t = fmtTime(row);
      return t === "—" ? (
        <span className="text-gray-400">—</span>
      ) : (
        <span className="inline-flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5 shrink-0 text-gray-400" aria-hidden="true" />
          {t}
        </span>
      );
    },
  };

  const columns = isToken
    ? [tokenColumn, nameColumn, reasonColumn, statusColumn, actionsColumn]
    : [
        nameColumn,
        timeColumn,
        { key: "duration_min", header: "Length", render: (row) => `${row.duration_min || 30}m` },
        reasonColumn,
        statusColumn,
        actionsColumn,
      ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-1 py-0.5">
        <div>
          <h1 className="text-[26px] font-semibold text-[#0F172A] dark:text-[#F5F7FA] tracking-tight leading-tight">{labels.bookings}</h1>
          <p className="text-[13.5px] text-[#475569] dark:text-[#A1A1AA] mt-0.5 max-w-2xl">
            {isToken
              ? `${labels.bookings} by daily token number. Give walk-ins a token here, and advance "Now serving" as each patient is seen.`
              : `${labels.bookings} booked by the AI receptionist and your team. Walk-ins can be added here — the AI won't double-book a taken slot.`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <Button
            variant="secondary"
            onClick={exportCsv}
            disabled={exporting || loading}
            title={
              filtersActive
                ? `Export the ${filtered.length} matching ${labels.bookings.toLowerCase()}`
                : `Export all ${labels.bookings.toLowerCase()}`
            }
          >
            {exporting ? (
              <><Loader2 className="h-4 w-4 animate-spin" /> Exporting...</>
            ) : (
              <><Download className="h-4 w-4" /> Export CSV</>
            )}
          </Button>
          <Button variant="accent" onClick={openBooking}>
            <CalendarPlus className="h-4 w-4" /> {isToken ? "Give token" : `Book ${labels.booking.toLowerCase()}`}
          </Button>
        </div>
      </div>

      {banner && (
        <div
          className={`flex items-start justify-between gap-3 rounded-2xl border p-4 text-sm ${
            banner.type === "success"
              ? "border-emerald-100 bg-emerald-50 text-emerald-800"
              : "border-red-100 bg-red-50 text-red-800"
          }`}
        >
          <span>{banner.text}</span>
          <button className="text-xs font-medium opacity-70 hover:opacity-100" onClick={() => setBanner(null)}>
            Dismiss
          </button>
        </div>
      )}

      {!loading && !live && (
        <p className="text-xs text-gray-400">Couldn't reach the backend. Sign in and ensure the API is running to see live {labels.bookings.toLowerCase()}.</p>
      )}

      {isToken && (
        <div className="panel rounded-3xl border border-gray-100 bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">Now serving</p>
              <p className="mt-1 text-5xl font-semibold tabular-nums text-gray-950">{queue.current_number || 0}</p>
              <p className="mt-1 text-xs text-gray-400">
                {queue.total_issued || 0} token{(queue.total_issued || 0) === 1 ? "" : "s"} issued today
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={queueNext} disabled={queueBusy}>Next patient</Button>
              <Button variant="secondary" onClick={() => queueSetTo(0)} disabled={queueBusy}>Reset</Button>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min="0"
                  className="w-20 rounded-xl border border-gray-200 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
                  placeholder="#"
                  value={setNum}
                  onChange={(e) => setSetNum(e.target.value)}
                />
                <Button variant="secondary" onClick={() => queueSetTo(setNum)} disabled={queueBusy || setNum === ""}>Set</Button>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="clarivo-panel flex flex-col gap-3 p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <label className="flex flex-1 items-center gap-2.5 rounded-[14px] border border-[#E4E8EE] dark:border-[#252A30] bg-[#F5F7FA] dark:bg-[#171A1D] px-3.5 py-2">
            <Search className="h-4 w-4 shrink-0 text-[#64748B] dark:text-[#A1A1AA]" />
            <input
              className="w-full border-0 bg-transparent p-0 text-[13px] outline-none placeholder:text-[#64748B] dark:placeholder:text-[#A1A1AA] text-[#0F172A] dark:text-[#F5F7FA]"
              placeholder="Search by name, reason, or status..."
              value={query}
              onChange={(event) => { setQuery(event.target.value); setPage(1); }}
              aria-label={`Search ${labels.bookings.toLowerCase()}`}
            />
          </label>

          <div className="flex items-center gap-2 rounded-[14px] border border-[#E4E8EE] dark:border-[#252A30] bg-[#F5F7FA] dark:bg-[#171A1D] px-3.5 py-2">
            <CalendarDays className="h-4 w-4 shrink-0 text-[#64748B] dark:text-[#A1A1AA]" />
            <input
              type="date"
              className="min-w-0 flex-1 border-0 bg-transparent p-0 text-[13px] outline-none text-[#0F172A] dark:text-[#F5F7FA]"
              value={range.from || ""}
              max={range.to || undefined}
              onChange={(e) => { setDatePreset("custom"); setCustomFrom(e.target.value); setPage(1); }}
              aria-label="From date"
            />
            <span className="shrink-0 text-[#64748B] dark:text-[#A1A1AA]">–</span>
            <input
              type="date"
              className="min-w-0 flex-1 border-0 bg-transparent p-0 text-[13px] outline-none text-[#0F172A] dark:text-[#F5F7FA]"
              value={range.to || ""}
              min={range.from || undefined}
              onChange={(e) => { setDatePreset("custom"); setCustomTo(e.target.value); setPage(1); }}
              aria-label="To date"
            />
          </div>

          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => setShowFilters((v) => !v)} aria-expanded={showFilters}>
              <SlidersHorizontal className="h-4 w-4" /> Filters
              {showFilters ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </Button>
            <Button variant="secondary" onClick={clearAll} disabled={!filtersActive}>
              <RotateCcw className="h-4 w-4" /> Clear all
            </Button>
          </div>
        </div>

        {showFilters && (
          <div className="grid gap-3 border-t border-gray-100 pt-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-2xl border border-gray-200 bg-white px-3 py-2">
              <span className="block text-[10px] font-semibold uppercase tracking-wider text-gray-400">Status</span>
              <select
                className="mt-0.5 w-full border-0 bg-transparent p-0 text-sm text-gray-900 outline-none"
                value={statusFilter}
                onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
                aria-label="Filter by status"
              >
                <option value="">All status</option>
                {statusOptions.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            {/* Doctor, type and source filters are deliberately absent: an appointment
                record carries no such fields, so those controls could only ever be
                decoration over data that does not exist. */}
            <p className="text-xs leading-5 text-gray-400 sm:col-span-1 lg:col-span-3">
              Status is the only stored attribute to filter on — {labels.bookings.toLowerCase()} carry
              no doctor, type or source field. Use the search box for anything in the name or reason.
            </p>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {DATE_PRESETS.map((p) => (
            <FilterChip
              key={p.key}
              active={datePreset === p.key}
              onClick={() => {
                setDatePreset(p.key);
                if (p.key !== "custom") { setCustomFrom(""); setCustomTo(""); }
                setPage(1);
              }}
            >
              {p.label}
            </FilterChip>
          ))}
          {filtersActive && !loading && (
            <span className="ml-auto text-xs text-gray-500" aria-live="polite">
              {filtered.length} of {list.length} {labels.bookings.toLowerCase()} match
            </span>
          )}
        </div>
      </div>

      {groups.length === 0 ? (
        <DataTable
          columns={columns}
          rows={[]}
          loading={loading}
          emptyTitle={
            filtersActive
              ? `No ${labels.bookings.toLowerCase()} match these filters`
              : `No ${labels.bookings.toLowerCase()} yet`
          }
          {...(filtersActive
            ? { emptyDescription: "Try a wider date range, or clear the filters." }
            : {})}
        />
      ) : (
        <div className="space-y-8">
          {groups.map((group) => (
            <section key={group.key || "undated"} className="space-y-3">
              <div className="flex items-baseline justify-between gap-3">
                <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight text-gray-950">
                  <CalendarDays className="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
                  {group.label}
                </h2>
                <span className="text-xs font-medium text-gray-500">
                  {group.rows.length} {group.rows.length === 1 ? labels.booking.toLowerCase() : labels.bookings.toLowerCase()}
                </span>
              </div>
              <DataTable columns={columns} rows={group.rows} loading={false} />
            </section>
          ))}
        </div>
      )}

      <Pagination
        page={safePage}
        pageSize={pageSize}
        total={filtered.length}
        onChange={setPage}
        unit={labels.bookings.toLowerCase()}
        label={`${labels.bookings} pages`}
        pageSizeOptions={PAGE_SIZES}
        onPageSizeChange={(n) => { setPageSize(n); setPage(1); }}
      />

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={isToken ? "Give a token" : `Book ${labels.booking.toLowerCase()}`}
        description={
          isToken
            ? "Add someone to today's queue — they get the next token number automatically."
            : `Add a ${labels.booking.toLowerCase()} (e.g. a walk-in). If the slot is already taken you'll be asked to pick another.`
        }
        footer={
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={submitAppointment} disabled={submitting}>
              {submitting ? "Saving..." : isToken ? "Give token" : `Book ${labels.booking.toLowerCase()}`}
            </Button>
          </div>
        }
      >
        {formError && (
          <div className="mb-4 rounded-2xl border border-red-100 bg-red-50 p-3 text-sm text-red-800">{formError}</div>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-500">Existing {labels.contact.toLowerCase()}</label>
            <select
              className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-sm focus:border-brand-500 focus:outline-none"
              value={selectedContactId}
              onChange={onSelectContact}
            >
              <option value="">New {labels.contact.toLowerCase()} / walk-in</option>
              {contacts.map((c) => (
                <option key={c.id} value={c.id}>{c.name}{c.phone ? ` — ${c.phone}` : ""}</option>
              ))}
            </select>
            <p className="mt-1 text-xs text-gray-400">Pick a saved {labels.contact.toLowerCase()} to auto-fill their name and phone, or leave as "New" for a walk-in.</p>
          </div>
          <Field label="Name *" value={form.patient_name} onChange={updateField("patient_name")} placeholder="Jane Doe" />
          <Field label="Phone (for WhatsApp)" value={form.phone} onChange={updateField("phone")} placeholder="+9198XXXXXXXX" />
          {!isToken && (
            <>
              <Field label="Date & time *" type="datetime-local" value={form.appointment_at} onChange={updateField("appointment_at")} />
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-gray-500">Length</label>
                <select
                  className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-sm focus:border-brand-500 focus:outline-none"
                  value={form.duration_min}
                  onChange={updateField("duration_min")}
                >
                  {DURATIONS.map((m) => <option key={m} value={m}>{m} min</option>)}
                </select>
              </div>
            </>
          )}
          <div className="sm:col-span-2">
            <Field label="Reason" value={form.reason} onChange={updateField("reason")} placeholder="e.g. consultation, site visit, table for 4" />
          </div>
        </div>
      </Modal>

      <Modal
        open={!!reRow}
        onClose={() => setReRow(null)}
        title={`Reschedule ${labels.booking.toLowerCase()}`}
        description={reRow ? `${reRow.patient_name} — currently ${fmtWhen(reRow)}` : ""}
        footer={
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setReRow(null)}>Cancel</Button>
            <Button onClick={submitReschedule} disabled={reSubmitting}>{reSubmitting ? "Saving..." : "Reschedule"}</Button>
          </div>
        }
      >
        {reError && <div className="mb-4 rounded-2xl border border-red-100 bg-red-50 p-3 text-sm text-red-800">{reError}</div>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="New date & time *" type="datetime-local" value={reAt} onChange={(e) => setReAt(e.target.value)} />
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-500">Length</label>
            <select
              className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-sm focus:border-brand-500 focus:outline-none"
              value={reDur}
              onChange={(e) => setReDur(e.target.value)}
            >
              {DURATIONS.map((m) => <option key={m} value={m}>{m} min</option>)}
            </select>
          </div>
        </div>
      </Modal>

      <Modal
        open={!!confirmRow}
        onClose={() => setConfirmRow(null)}
        title={`Cancel this ${labels.booking.toLowerCase()}?`}
        description={confirmRow ? `${confirmRow.patient_name} — ${fmtWhen(confirmRow)}` : ""}
        footer={
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setConfirmRow(null)} disabled={busyId === confirmRow?.id}>
              Keep it
            </Button>
            <Button
              variant="danger"
              onClick={() => cancelAppointment(confirmRow)}
              disabled={busyId === confirmRow?.id}
            >
              {busyId === confirmRow?.id ? "Cancelling..." : `Cancel ${labels.booking.toLowerCase()}`}
            </Button>
          </div>
        }
      >
        <p className="text-sm text-gray-700">
          The {labels.booking.toLowerCase()} is marked cancelled and the slot opens up again, so the AI
          receptionist can offer that time to another caller.
        </p>
        <p className="mt-3 text-sm text-gray-500">
          The record is kept (not deleted), so it still shows in history. Nobody is notified
          automatically — tell {confirmRow?.patient_name || "the patient"} yourself.
        </p>
      </Modal>

      <Modal
        open={!!deleteRow}
        onClose={() => setDeleteRow(null)}
        title={`Delete this ${labels.booking.toLowerCase()} permanently?`}
        description={deleteRow ? `${deleteRow.patient_name} — ${fmtWhen(deleteRow)}` : ""}
        footer={
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setDeleteRow(null)} disabled={busyId === deleteRow?.id}>
              Keep it
            </Button>
            <Button
              variant="danger"
              onClick={() => deleteAppointment(deleteRow)}
              disabled={busyId === deleteRow?.id}
            >
              {busyId === deleteRow?.id ? "Deleting..." : "Delete permanently"}
            </Button>
          </div>
        }
      >
        <p className="text-sm text-gray-700">
          The row is removed for good and will not appear in history or reports. This cannot be
          undone.
        </p>
        {deleteRow?.status !== "cancelled" && (
          <p className="mt-3 text-sm text-gray-500">
            If the {labels.booking.toLowerCase()} simply is not happening, <strong>Cancel</strong> is
            usually the better choice — it frees the slot but keeps the record.
          </p>
        )}
        {deleteRow?.token_number != null && deleteRow?.token_date === shiftDays(0) && (
          <p className="mt-3 rounded-2xl border border-amber-100 bg-amber-50 p-3 text-sm text-amber-900">
            This is token <strong>#{deleteRow.token_number}</strong> for today. Today's numbering
            counts up from the highest token still on file, so deleting this one can hand the same
            number to the next patient. Mid-queue, cancel it instead.
          </p>
        )}
      </Modal>
    </div>
  );
}

function FilterChip({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
        active
          ? "border-brand-500 bg-brand-500 text-white"
          : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
      }`}
    >
      {children}
    </button>
  );
}

function Field({ label, value, onChange, placeholder, type = "text" }) {
  return (
    <label className="space-y-1.5">
      <span className="block text-xs font-semibold uppercase tracking-wider text-gray-500">{label}</span>
      <input
        type={type}
        className="w-full rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-brand-500 focus:outline-none"
        value={value}
        onChange={onChange}
        placeholder={placeholder}
      />
    </label>
  );
}
