import {
  ArrowDownRight, ArrowUpRight, Download, Loader2, Phone, PhoneMissed, RotateCcw, Search,
  Trash2, UserPlus, Users,
} from "lucide-react";
import { useMemo, useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { useLabels } from "../store/clinicStore";

import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import Pagination from "../components/Pagination";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import MiniStat from "../components/ui/MiniStat";
import { avatarTone, initialOf } from "../lib/avatar";
import { dateStamp, downloadCsv, toCsv } from "../lib/csv";
import { derivePatientStats } from "../lib/patientStats";
import { useAuthStore } from "../store/authStore";

const emptyForm = { name: "", phone: "", email: "", age: "", gender: "", notes: "" };
const PAGE_SIZES = [10, 25, 50];

// Exactly the columns the table shows. Deliberately no id, clinic_id or created_by —
// those are internal keys, of no use in a spreadsheet and not ours to hand out.
const CSV_COLUMNS = [
  { header: "Name", value: (r) => r.name },
  // Written as the plain number. Prefixing with = or a tab would make Excel show it as
  // text, but it would also corrupt the field for every other reader.
  { header: "Phone", value: (r) => r.phone },
  { header: "Email", value: (r) => (r.email === "N/A" ? "" : r.email) },
  { header: "Details", value: (r) => r.company },
  { header: "Notes", value: (r) => (r.lastContacted === "None" ? "" : r.lastContacted) },
  { header: "Source", value: (r) => (r.source === "manual" ? "Manual" : "Agent") },
  { header: "Status", value: (r) => r.status },
];

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

function formatPatient(p) {
  // `history` is filled in by the agent when it deals with this caller, so a non-empty
  // history means the receptionist has recognised them on a call. Both the Status column
  // and the recognised/not-recognised statistics read this one field, which is why they
  // can never disagree.
  const recognised = !!(p.history && p.history.length > 0);
  return {
    id: p.id,
    name: p.name,
    phone: p.phone,
    email: p.email || "N/A",
    company: p.gender ? `${p.gender}, Age ${p.age || "N/A"}` : "Contact",
    lastContacted: p.follow_up_notes || "None",
    status: recognised ? "Returning" : "New",
    source: p.source || "agent",
    recognised,
    createdAt: p.created_at || null,
  };
}

export default function Contacts() {
  const labels = useLabels();
  const navigate = useNavigate();
  // Staff may read and create contacts, but not delete them. Mirrors Sidebar's
  // role check. This only hides the button — `DELETE /api/patients/{id}` is guarded
  // by require_non_staff, so a staff token gets a 403 either way.
  const user = useAuthStore((state) => state.user);
  const isStaff = user?.role === "staff";
  const [list, setList] = useState([]);
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(false);

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  const [banner, setBanner] = useState(null); // { type: "success" | "error", text }
  const [exporting, setExporting] = useState(false);

  // Deleting a contact is permanent, so it goes through a confirm step that names
  // the record. `confirmRow` doubles as the modal's open flag.
  const [confirmRow, setConfirmRow] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const loadContacts = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/patients/");
      if (res.data && res.data.success) {
        setList((res.data.data || []).map(formatPatient));
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

  useEffect(() => {
    loadContacts();
  }, [loadContacts]);

  // Header figures, from the list already fetched — no extra request, so they cannot
  // disagree with the table below.
  const stats = useMemo(() => derivePatientStats(list), [list]);

  // Offered values come from the data, so a filter can never advertise a source or
  // status that no row has and then return an empty table with no explanation.
  const sourceOptions = useMemo(
    () => [...new Set(list.map((c) => c.source).filter(Boolean))].sort(),
    [list],
  );
  const statusOptions = useMemo(
    () => [...new Set(list.map((c) => c.status).filter(Boolean))].sort(),
    [list],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    // Phone digits compared separately so "79871 01876" finds "917987101876".
    const qDigits = query.replace(/\D/g, "");
    return list.filter((contact) => {
      if (sourceFilter && contact.source !== sourceFilter) return false;
      if (statusFilter && contact.status !== statusFilter) return false;
      if (!q) return true;
      // Phone was NOT searchable before — the placeholder offered it, the filter did not.
      const haystack = `${contact.name} ${contact.company} ${contact.email}`.toLowerCase();
      if (haystack.includes(q)) return true;
      return !!qDigits && (contact.phone || "").replace(/\D/g, "").includes(qDigits);
    });
  }, [query, list, sourceFilter, statusFilter]);

  // Clamped during render rather than reset from an effect: a narrower result set can be
  // shorter than the current offset and the page must be valid on this same render.
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const paged = useMemo(
    () => filtered.slice((safePage - 1) * pageSize, safePage * pageSize),
    [filtered, safePage, pageSize],
  );

  // Exports `filtered`, not `paged`: the filtered set is every matching record across
  // all pages, so the file follows the search and filters while ignoring which page
  // happens to be open. With no filters set, that is the whole list.
  const exportCsv = () => {
    setBanner(null);
    if (filtered.length === 0) {
      setBanner({ type: "error", text: `No ${labels.contacts.toLowerCase()} found to export.` });
      return;
    }
    setExporting(true);
    try {
      const slug = labels.contacts.toLowerCase().replace(/[^a-z0-9]+/g, "-");
      downloadCsv(`clarivo-${slug}-${dateStamp()}.csv`, toCsv(CSV_COLUMNS, filtered));
      setBanner({
        type: "success",
        text: `Exported ${filtered.length} ${labels.contacts.toLowerCase()}${
          filtersActive ? " matching the current filters" : ""
        }.`,
      });
    } catch {
      setBanner({ type: "error", text: `Unable to export ${labels.contacts.toLowerCase()}. Please try again.` });
    } finally {
      setExporting(false);
    }
  };

  const filtersActive = !!(query.trim() || sourceFilter || statusFilter);
  const clearFilters = () => {
    setQuery("");
    setSourceFilter("");
    setStatusFilter("");
    setPage(1);
  };

  const updateField = (key) => (event) => setForm((prev) => ({ ...prev, [key]: event.target.value }));

  const submitContact = async () => {
    setFormError("");
    if (!form.name.trim() || !form.phone.trim()) {
      setFormError("Name and phone are required.");
      return;
    }
    const payload = {
      name: form.name.trim(),
      phone: form.phone.trim(),
      email: form.email.trim() || null,
      gender: form.gender.trim() || null,
      follow_up_notes: form.notes.trim() || null,
      history: [],
    };
    const ageNum = parseInt(form.age, 10);
    if (!Number.isNaN(ageNum)) payload.age = ageNum;

    setSubmitting(true);
    try {
      const res = await api.post("/patients/", payload);
      if (res.data && res.data.success) {
        setOpen(false);
        setForm(emptyForm);
        setBanner({ type: "success", text: `Added ${payload.name}.` });
        loadContacts();
      } else {
        setFormError((res.data && res.data.message) || "Could not add contact.");
      }
    } catch (err) {
      setFormError(extractError(err));
    } finally {
      setSubmitting(false);
    }
  };

  const confirmDelete = async () => {
    if (!confirmRow) return;
    setDeleting(true);
    setBanner(null);
    try {
      const res = await api.delete(`/patients/${confirmRow.id}`);
      if (res.data && res.data.success) {
        setConfirmRow(null);
        setBanner({ type: "success", text: `Deleted ${confirmRow.name}.` });
        loadContacts();
      } else {
        setBanner({ type: "error", text: (res.data && res.data.message) || "Could not delete." });
      }
    } catch (err) {
      // A 403 here means the role check server-side disagreed with the UI.
      setBanner({ type: "error", text: extractError(err) });
    } finally {
      setDeleting(false);
    }
  };

  const columns = [
    {
      key: "name",
      header: "Name",
      render: (row) => (
        <div className="flex items-center gap-2.5">
          <span
            className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-semibold ${avatarTone(row.name)}`}
            aria-hidden="true"
          >
            {initialOf(row.name)}
          </span>
          <span className="font-medium text-gray-950">{row.name}</span>
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
          "N/A"
        ),
    },
    { key: "email", header: "Email", render: (row) => <span className={row.email === "N/A" ? "text-gray-400" : ""}>{row.email}</span> },
    { key: "company", header: "Details" },
    { key: "lastContacted", header: "Notes", render: (row) => <span className={row.lastContacted === "None" ? "text-gray-400" : ""}>{row.lastContacted}</span> },
    {
      key: "source",
      header: "Source",
      render: (row) => (
        <Badge tone={row.source === "manual" ? "neutral" : "dark"}>
          {row.source === "manual" ? "Manual" : "Agent"}
        </Badge>
      ),
    },
    {
      key: "status",
      header: "Status",
      // "New" is informational, not a warning: the agent simply has not met them yet.
      render: (row) => <Badge tone={row.status === "Returning" ? "success" : "info"}>{row.status}</Badge>,
    },
    {
      key: "actions",
      header: "Actions",
      render: (row) => (
        <div className="flex items-center justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => navigate(`/contacts/${row.id}`)}>View</Button>
          {!isStaff && (
            <button
              type="button"
              onClick={() => setConfirmRow(row)}
              title={`Delete ${row.name}`}
              aria-label={`Delete ${row.name}`}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-gray-200 text-gray-400 transition hover:border-red-200 hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-1 py-0.5">
        <div>
          <h1 className="text-[26px] font-semibold text-[#0F172A] dark:text-[#F5F7FA] tracking-tight leading-tight">{labels.contacts}</h1>
          <p className="text-[13.5px] text-[#475569] dark:text-[#A1A1AA] mt-0.5">Add and manage {labels.contact.toLowerCase()} records the AI receptionist uses to recognise inbound callers.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <Button
            variant="secondary"
            onClick={exportCsv}
            disabled={exporting || loading}
            title={
              filtersActive
                ? `Export the ${filtered.length} matching ${labels.contacts.toLowerCase()}`
                : `Export all ${labels.contacts.toLowerCase()}`
            }
          >
            {exporting ? (
              <><Loader2 className="h-4 w-4 animate-spin" /> Exporting...</>
            ) : (
              <><Download className="h-4 w-4" /> Export CSV</>
            )}
          </Button>
          <Button variant="accent" onClick={() => { setFormError(""); setForm(emptyForm); setOpen(true); }}>
            <UserPlus className="h-4 w-4" /> Add {labels.contact.toLowerCase()}
          </Button>
        </div>
      </div>

      {/* All four figures are derived from the list already loaded — no extra request. */}
      <section className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <MiniStat
          icon={Users}
          tone="violet"
          label={`Total ${labels.contacts.toLowerCase()}`}
          value={stats.total}
          sub="All time"
          loading={loading}
        />
        <MiniStat
          icon={Phone}
          tone="emerald"
          label="Recognised callers"
          value={stats.recognised}
          sub={stats.total > 0 ? `${stats.recognisedShare}% of total` : "None yet"}
          loading={loading}
        />
        <MiniStat
          icon={UserPlus}
          tone="amber"
          label="New this month"
          value={stats.newThisMonth}
          // Omitted when nothing was added last month: a percentage against zero is
          // undefined, and any figure here would be invented.
          sub={
            typeof stats.newChangePct === "number" ? (
              <span className="inline-flex items-center gap-1">
                {stats.newChangePct >= 0
                  ? <ArrowUpRight className="h-3 w-3" />
                  : <ArrowDownRight className="h-3 w-3" />}
                {Math.abs(stats.newChangePct)}% vs last month
              </span>
            ) : null
          }
          subTone={
            typeof stats.newChangePct === "number"
              ? (stats.newChangePct >= 0 ? "text-emerald-600" : "text-red-600")
              : undefined
          }
          loading={loading}
        />
        <MiniStat
          icon={PhoneMissed}
          tone="red"
          label="Not recognised yet"
          value={stats.notRecognised}
          sub={stats.total > 0 ? `${stats.notRecognisedShare}% of total` : "None yet"}
          loading={loading}
        />
      </section>
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
        <p className="text-xs text-gray-400">Couldn't reach the backend. Sign in and ensure the API is running to see and manage {labels.contacts.toLowerCase()}.</p>
      )}

      <div className="clarivo-panel grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_11rem_11rem_auto] xl:items-end">
        <label className="flex items-center gap-2.5 rounded-[14px] border border-[#E4E8EE] dark:border-[#252A30] bg-[#F5F7FA] dark:bg-[#171A1D] px-3.5 py-2">
          <Search className="h-4 w-4 shrink-0 text-[#64748B] dark:text-[#A1A1AA]" />
          <input
            className="w-full border-0 bg-transparent p-0 text-[13px] outline-none placeholder:text-[#64748B] dark:placeholder:text-[#A1A1AA] text-[#0F172A] dark:text-[#F5F7FA]"
            placeholder={`Search ${labels.contacts.toLowerCase()} by name, phone, or email...`}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(1);
            }}
            aria-label={`Search ${labels.contacts.toLowerCase()}`}
          />
        </label>

        <div className="rounded-[14px] border border-[#E4E8EE] dark:border-[#252A30] bg-[#F5F7FA] dark:bg-[#171A1D] px-3.5 py-2">
          <span className="block text-[10px] font-semibold uppercase tracking-wider text-[#64748B] dark:text-[#A1A1AA]">Source</span>
          <select
            className="mt-0.5 w-full border-0 bg-transparent p-0 text-[13px] text-[#0F172A] dark:text-[#F5F7FA] outline-none"
            value={sourceFilter}
            onChange={(e) => { setSourceFilter(e.target.value); setPage(1); }}
            aria-label="Filter by source"
          >
            <option value="">All sources</option>
            {sourceOptions.map((s) => (
              <option key={s} value={s}>{s === "manual" ? "Manual" : "Agent"}</option>
            ))}
          </select>
        </div>

        <div className="rounded-[14px] border border-[#E4E8EE] dark:border-[#252A30] bg-[#F5F7FA] dark:bg-[#171A1D] px-3.5 py-2">
          <span className="block text-[10px] font-semibold uppercase tracking-wider text-[#64748B] dark:text-[#A1A1AA]">Status</span>
          <select
            className="mt-0.5 w-full border-0 bg-transparent p-0 text-[13px] text-[#0F172A] dark:text-[#F5F7FA] outline-none"
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
            aria-label="Filter by status"
          >
            <option value="">All status</option>
            {statusOptions.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        <Button variant="secondary" onClick={clearFilters} disabled={!filtersActive} className="sm:col-span-2 xl:col-span-1">
          <RotateCcw className="h-4 w-4" /> Clear filters
        </Button>
      </div>

      {filtersActive && !loading && (
        <p className="-mt-2 text-xs text-gray-500" aria-live="polite">
          {filtered.length} of {list.length} {labels.contacts.toLowerCase()} match
        </p>
      )}

      <DataTable
        columns={columns}
        rows={paged}
        loading={loading}
        emptyTitle={
          filtersActive
            ? `No ${labels.contacts.toLowerCase()} match these filters`
            : `No ${labels.contacts.toLowerCase()} yet, add your first one`
        }
        {...(filtersActive ? { emptyDescription: "Try a different search, or clear the filters." } : {})}
      />

      <Pagination
        page={safePage}
        pageSize={pageSize}
        total={filtered.length}
        onChange={setPage}
        unit={labels.contacts.toLowerCase()}
        label={`${labels.contacts} pages`}
        pageSizeOptions={PAGE_SIZES}
        onPageSizeChange={(n) => { setPageSize(n); setPage(1); }}
      />

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={`Add ${labels.contact.toLowerCase()}`}
        description={`Create a ${labels.contact.toLowerCase()} record. Name and phone are required.`}
        footer={
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={submitContact} disabled={submitting}>{submitting ? "Saving..." : "Save contact"}</Button>
          </div>
        }
      >
        {formError && (
          <div className="mb-4 rounded-2xl border border-red-100 bg-red-50 p-3 text-sm text-red-800">{formError}</div>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name *" value={form.name} onChange={updateField("name")} placeholder="Jane Doe" />
          <Field label="Phone *" value={form.phone} onChange={updateField("phone")} placeholder="+91XXXXXXXXXX" />
          <Field label="Email" type="email" value={form.email} onChange={updateField("email")} placeholder="Email address (optional)" />
          <Field label="Age" type="number" value={form.age} onChange={updateField("age")} placeholder="35" />
          <Field label="Gender" value={form.gender} onChange={updateField("gender")} placeholder="Female / Male / Other" />
          <Field label="Follow-up notes" value={form.notes} onChange={updateField("notes")} placeholder="Prefers morning calls" />
        </div>
      </Modal>

      <Modal
        open={!!confirmRow}
        onClose={() => setConfirmRow(null)}
        title={`Delete ${labels.contact.toLowerCase()}?`}
        description="This cannot be undone."
        footer={
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setConfirmRow(null)} disabled={deleting}>Keep</Button>
            <Button variant="danger" onClick={confirmDelete} disabled={deleting}>
              {deleting ? "Deleting..." : "Delete permanently"}
            </Button>
          </div>
        }
      >
        <p className="text-sm text-gray-700">
          <span className="font-semibold text-gray-950">{confirmRow?.name}</span>
          {confirmRow?.phone ? ` (${confirmRow.phone})` : ""} will be removed from your{" "}
          {labels.contacts.toLowerCase()}.
        </p>
        <p className="mt-3 text-sm text-gray-500">
          The AI receptionist will no longer recognise this number on an inbound call, so the caller
          will be treated as new. Past {labels.bookings.toLowerCase()} and call records are kept.
        </p>
      </Modal>
    </div>
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
