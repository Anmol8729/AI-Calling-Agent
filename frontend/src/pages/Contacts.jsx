import { Search, Trash2, UserPlus } from "lucide-react";
import { useMemo, useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { useLabels } from "../store/clinicStore";

import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { useAuthStore } from "../store/authStore";

const emptyForm = { name: "", phone: "", email: "", age: "", gender: "", notes: "" };

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
  return {
    id: p.id,
    name: p.name,
    phone: p.phone,
    email: p.email || "N/A",
    company: p.gender ? `${p.gender}, Age ${p.age || "N/A"}` : "Contact",
    lastContacted: p.follow_up_notes || "None",
    status: p.history && p.history.length > 0 ? "Returning" : "New",
    source: p.source || "agent",
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
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(false);

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  const [banner, setBanner] = useState(null); // { type: "success" | "error", text }

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

  const filtered = useMemo(
    () =>
      list.filter((contact) =>
        `${contact.name} ${contact.company} ${contact.email}`.toLowerCase().includes(query.toLowerCase()),
      ),
    [query, list],
  );

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
    { key: "name", header: "Name" },
    { key: "phone", header: "Phone" },
    { key: "email", header: "Email" },
    { key: "company", header: "Details" },
    { key: "lastContacted", header: "Notes" },
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
      render: (row) => <Badge tone={row.status === "Returning" ? "success" : "neutral"}>{row.status}</Badge>,
    },
    {
      key: "actions",
      header: "",
      render: (row) => (
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => navigate(`/contacts/${row.id}`)}>View</Button>
          {!isStaff && (
            <Button variant="danger" size="sm" onClick={() => setConfirmRow(row)}>
              <Trash2 className="h-3.5 w-3.5" /> Delete
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-gray-950">{labels.contacts}</h1>
          <p className="mt-2 text-sm text-gray-500">Add and manage {labels.contact.toLowerCase()} records the AI receptionist uses to recognise inbound callers.</p>
        </div>
        <Button onClick={() => { setFormError(""); setForm(emptyForm); setOpen(true); }}>
          <UserPlus className="h-4 w-4" /> Add {labels.contact.toLowerCase()}
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
        <p className="text-xs text-gray-400">Couldn't reach the backend. Sign in and ensure the API is running to see and manage {labels.contacts.toLowerCase()}.</p>
      )}

      <div className="panel flex flex-col gap-3 rounded-3xl p-4 md:flex-row">
        <label className="flex flex-1 items-center gap-3 rounded-2xl border border-gray-200 px-3 py-2">
          <Search className="h-4 w-4 text-gray-400" />
          <input
            className="w-full border-0 outline-none"
            placeholder={`Search ${labels.contacts.toLowerCase()}...`}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>

      <DataTable columns={columns} rows={filtered} loading={loading} emptyTitle={`No ${labels.contacts.toLowerCase()} yet, add your first one`} />

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
        className="w-full rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-gray-950 focus:outline-none"
        value={value}
        onChange={onChange}
        placeholder={placeholder}
      />
    </label>
  );
}
