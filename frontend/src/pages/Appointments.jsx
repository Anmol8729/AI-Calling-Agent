import { CalendarDays, CalendarPlus, Trash2 } from "lucide-react";
import { useMemo, useState, useEffect, useCallback } from "react";
import api from "../lib/api";
import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { useLabels, useClinicStore } from "../store/clinicStore";
import { useAuthStore } from "../store/authStore";

const emptyForm = { patient_name: "", phone: "", appointment_at: "", duration_min: 30, reason: "" };
const DURATIONS = [15, 30, 45, 60, 90];

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

// Local YYYY-MM-DD. Deliberately NOT toISOString().slice(0,10): that converts to
// UTC first, so a 00:30 IST booking would be filed under the previous day.
const toDateKey = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

// Which day a row belongs to. Time mode has a real timestamp; token mode only has
// token_date. Rows with neither (legacy imports) group under "" and sort last.
const dateKeyOf = (row) => {
  if (row.appointment_at) {
    const d = new Date(row.appointment_at);
    if (!Number.isNaN(d.getTime())) return toDateKey(d);
  }
  if (row.token_date) return String(row.token_date).slice(0, 10);
  return "";
};

const shiftDays = (n) => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return toDateKey(d);
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
  const [dateFilter, setDateFilter] = useState("");
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

  const filtered = useMemo(
    () =>
      list.filter((a) => {
        const matchesText = `${a.patient_name} ${a.reason || ""} ${a.status} ${fmtWhen(a)}`
          .toLowerCase()
          .includes(query.toLowerCase());
        const matchesDate = !dateFilter || dateKeyOf(a) === dateFilter;
        return matchesText && matchesDate;
      }),
    [query, dateFilter, list],
  );

  // One section per date. Sorted ascending so the nearest day is at the top, with
  // undated rows last — the list arrives ordered by time, so rows inside a group
  // keep that order for free.
  const groups = useMemo(() => {
    const buckets = new Map();
    for (const row of filtered) {
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
  }, [filtered]);

  // Dates that actually have bookings, for the quick-jump chips.
  const availableDates = useMemo(() => {
    const keys = new Set(list.map(dateKeyOf).filter(Boolean));
    return [...keys].sort();
  }, [list]);

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
        <div className="flex gap-2">
          {!isToken && (
            <Button variant="secondary" size="sm" onClick={() => openReschedule(row)}>Reschedule</Button>
          )}
          <Button variant="secondary" size="sm" disabled={busyId === row.id} onClick={() => setConfirmRow(row)}>
            {busyId === row.id ? "..." : "Cancel"}
          </Button>
          <Button variant="danger" size="sm" disabled={busyId === row.id} onClick={() => setDeleteRow(row)}>
            <Trash2 className="h-3.5 w-3.5" /> Delete
          </Button>
        </div>
      );
    },
  };

  const columns = isToken
    ? [
        { key: "token_number", header: "Token", render: (row) => (row.token_number != null ? `#${row.token_number}` : "—") },
        { key: "patient_name", header: "Name" },
        { key: "reason", header: "Reason", render: (row) => row.reason || "—" },
        { key: "status", header: "Status", render: (row) => <Badge tone={statusTone(row.status)}>{row.status}</Badge> },
        actionsColumn,
      ]
    : [
        { key: "patient_name", header: "Name" },
        { key: "appointment_at", header: "When", render: (row) => fmtWhen(row) },
        { key: "duration_min", header: "Length", render: (row) => `${row.duration_min || 30}m` },
        { key: "reason", header: "Reason", render: (row) => row.reason || "—" },
        { key: "status", header: "Status", render: (row) => <Badge tone={statusTone(row.status)}>{row.status}</Badge> },
        actionsColumn,
      ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-gray-950">{labels.bookings}</h1>
          <p className="mt-2 text-sm text-gray-500">
            {isToken
              ? `${labels.bookings} by daily token number. Give walk-ins a token here, and advance "Now serving" as each patient is seen.`
              : `${labels.bookings} booked by the AI receptionist and your team. Walk-ins can be added here — the AI won't double-book a taken slot.`}
          </p>
        </div>
        <Button onClick={openBooking}>
          <CalendarPlus className="h-4 w-4" /> {isToken ? "Give token" : `Book ${labels.booking.toLowerCase()}`}
        </Button>
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
                  className="w-20 rounded-xl border border-gray-200 px-3 py-2 text-sm focus:border-gray-950 focus:outline-none"
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

      <div className="panel flex flex-col gap-3 rounded-3xl p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <input
            className="w-full flex-1 rounded-2xl border border-gray-200 px-3.5 py-2 text-sm outline-none focus:border-gray-950"
            placeholder="Search by name, reason, or status..."
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-2 rounded-2xl border border-gray-200 px-3 py-2">
              <CalendarDays className="h-4 w-4 text-gray-400" />
              <input
                type="date"
                className="border-0 text-sm outline-none"
                value={dateFilter}
                onChange={(event) => setDateFilter(event.target.value)}
                aria-label={`Filter ${labels.bookings.toLowerCase()} by date`}
              />
            </label>
            {dateFilter && (
              <Button variant="ghost" size="sm" onClick={() => setDateFilter("")}>Clear</Button>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <FilterChip active={!dateFilter} onClick={() => setDateFilter("")}>
            All dates
          </FilterChip>
          <FilterChip active={dateFilter === shiftDays(0)} onClick={() => setDateFilter(shiftDays(0))}>
            Today
          </FilterChip>
          <FilterChip active={dateFilter === shiftDays(1)} onClick={() => setDateFilter(shiftDays(1))}>
            Tomorrow
          </FilterChip>
          {dateFilter && !availableDates.includes(dateFilter) && (
            <span className="text-xs text-gray-400">
              Nothing booked on {groupLabel(dateFilter)}.
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
            dateFilter
              ? `No ${labels.bookings.toLowerCase()} on ${groupLabel(dateFilter)}`
              : `No ${labels.bookings.toLowerCase()} yet`
          }
        />
      ) : (
        <div className="space-y-8">
          {groups.map((group) => (
            <section key={group.key || "undated"} className="space-y-3">
              <div className="flex items-baseline justify-between gap-3">
                <h2 className="text-lg font-semibold tracking-tight text-gray-950">{group.label}</h2>
                <span className="text-xs font-medium text-gray-500">
                  {group.rows.length} {group.rows.length === 1 ? labels.booking.toLowerCase() : labels.bookings.toLowerCase()}
                </span>
              </div>
              <DataTable columns={columns} rows={group.rows} loading={false} />
            </section>
          ))}
        </div>
      )}

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
              className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-sm focus:border-gray-950 focus:outline-none"
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
                  className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-sm focus:border-gray-950 focus:outline-none"
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
              className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-sm focus:border-gray-950 focus:outline-none"
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
          ? "border-gray-950 bg-gray-950 text-white"
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
        className="w-full rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-gray-950 focus:outline-none"
        value={value}
        onChange={onChange}
        placeholder={placeholder}
      />
    </label>
  );
}
