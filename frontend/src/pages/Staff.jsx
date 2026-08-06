import { RotateCcw, ShieldOff, Trash2, UserPlus, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import api from "../lib/api";
import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";

// Mirrors backend/schemas/auth.py: MIN_PASSWORD_LENGTH plus three of four character
// classes. Checked here only to fail fast with a clear message — the server is the
// one that actually enforces it. The old copy of this form said "min. 6 characters",
// which the API rejected, so the doctor got a 422 with no idea what was wrong.
const MIN_PASSWORD_LENGTH = 10;

function passwordProblem(value) {
  if (value.length < MIN_PASSWORD_LENGTH) {
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((re) => re.test(value)).length;
  if (classes < 3) {
    return "Password must combine at least three of: lowercase, uppercase, numbers, symbols.";
  }
  return null;
}

// Saves the doctor from inventing one — the usual reason people push back on a
// password policy. crypto.getRandomValues, not Math.random.
function suggestPassword() {
  const alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%&*?";
  const bytes = new Uint32Array(16);
  crypto.getRandomValues(bytes);
  return [...bytes].map((n) => alphabet[n % alphabet.length]).join("");
}

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
  if (err?.response?.status === 403) return "Only the clinic owner can manage staff.";
  return "Could not reach the server.";
}

const fmtDate = (value) => {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString([], { dateStyle: "medium" });
};

const emptyForm = { name: "", email: "", password: "" };

export default function Staff() {
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(false);
  const [banner, setBanner] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const [removeRow, setRemoveRow] = useState(null);

  const loadStaff = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/auth/staff");
      if (res.data?.success) {
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

  useEffect(() => {
    loadStaff();
  }, [loadStaff]);

  const activeCount = useMemo(() => list.filter((m) => m.is_active).length, [list]);

  const updateField = (key) => (event) => setForm((prev) => ({ ...prev, [key]: event.target.value }));

  const openAdd = () => {
    setFormError("");
    setForm(emptyForm);
    setShowPassword(false);
    setOpen(true);
  };

  const submitStaff = async () => {
    setFormError("");
    if (!form.name.trim() || !form.email.trim()) {
      setFormError("Name and email are required.");
      return;
    }
    const problem = passwordProblem(form.password);
    if (problem) {
      setFormError(problem);
      return;
    }
    setSubmitting(true);
    try {
      const res = await api.post("/auth/staff", {
        name: form.name.trim(),
        email: form.email.trim(),
        password: form.password,
      });
      if (res.data?.success) {
        setOpen(false);
        setBanner({
          type: "success",
          text: `Added ${form.name.trim()}. Give them the password you just set — it is not emailed.`,
        });
        setForm(emptyForm);
        loadStaff();
      } else {
        setFormError(res.data?.message || "Could not create the staff account.");
      }
    } catch (err) {
      setFormError(extractError(err));
    } finally {
      setSubmitting(false);
    }
  };

  const setAccess = async (row, active) => {
    setBanner(null);
    setBusyId(row.id);
    try {
      const res = await api.patch(`/auth/staff/${row.id}`, { active });
      if (res.data?.success) {
        setBanner({ type: "success", text: res.data.message });
        loadStaff();
      } else {
        setBanner({ type: "error", text: res.data?.message || "Could not update access." });
      }
    } catch (err) {
      setBanner({ type: "error", text: extractError(err) });
    } finally {
      setBusyId(null);
    }
  };

  const removeStaff = async (row) => {
    setBanner(null);
    setBusyId(row.id);
    try {
      const res = await api.delete(`/auth/staff/${row.id}`);
      if (res.data?.success) {
        setRemoveRow(null);
        setBanner({ type: "success", text: res.data.message });
        loadStaff();
      } else {
        setBanner({ type: "error", text: res.data?.message || "Could not remove." });
      }
    } catch (err) {
      setBanner({ type: "error", text: extractError(err) });
    } finally {
      setBusyId(null);
    }
  };

  const columns = [
    { key: "name", header: "Name" },
    { key: "email", header: "Email" },
    {
      key: "is_active",
      header: "Access",
      render: (row) => (
        <Badge tone={row.is_active ? "success" : "danger"}>
          {row.is_active ? "Active" : "Suspended"}
        </Badge>
      ),
    },
    { key: "created_at", header: "Added", render: (row) => fmtDate(row.created_at) },
    {
      key: "last_login_at",
      header: "Last sign-in",
      render: (row) => (row.last_login_at ? fmtDate(row.last_login_at) : "Never"),
    },
    {
      key: "actions",
      header: "Actions",
      render: (row) => (
        <div className="flex justify-end gap-2">
          {row.is_active ? (
            <Button
              variant="secondary"
              size="sm"
              disabled={busyId === row.id}
              onClick={() => setAccess(row, false)}
            >
              <ShieldOff className="h-3.5 w-3.5" /> {busyId === row.id ? "..." : "Suspend"}
            </Button>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              disabled={busyId === row.id}
              onClick={() => setAccess(row, true)}
            >
              <RotateCcw className="h-3.5 w-3.5" /> {busyId === row.id ? "..." : "Restore"}
            </Button>
          )}
          <Button variant="danger" size="sm" disabled={busyId === row.id} onClick={() => setRemoveRow(row)}>
            <Trash2 className="h-3.5 w-3.5" /> Remove
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-gray-950">Staff</h1>
          <p className="mt-2 text-sm text-gray-500">
            Staff can see contacts, appointments, calls and messages, and can add contacts and book
            appointments. They cannot delete records, cancel or move appointments, change agent
            settings, or touch billing.
          </p>
        </div>
        <Button onClick={openAdd}>
          <UserPlus className="h-4 w-4" /> Add staff
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
        <p className="text-xs text-gray-400">
          Couldn't reach the backend. Sign in and ensure the API is running to manage staff.
        </p>
      )}

      {!loading && live && list.length > 0 && (
        <p className="text-xs text-gray-500">
          {list.length} staff account{list.length === 1 ? "" : "s"} · {activeCount} active
        </p>
      )}

      <DataTable
        columns={columns}
        rows={list}
        loading={loading}
        emptyTitle="No staff accounts yet"
        emptyDescription="Add a receptionist so they can answer the desk without seeing your billing or agent settings."
        emptyIcon={Users}
        emptyAction={
          <Button onClick={openAdd}>
            <UserPlus className="h-4 w-4" /> Add staff
          </Button>
        }
      />

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Add staff"
        description="They sign in with this email and password. Nothing is emailed, so pass the password on yourself."
        footer={
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setOpen(false)} disabled={submitting}>Cancel</Button>
            <Button onClick={submitStaff} disabled={submitting}>
              {submitting ? "Creating..." : "Create staff account"}
            </Button>
          </div>
        }
      >
        {formError && (
          <div className="mb-4 rounded-2xl border border-red-100 bg-red-50 p-3 text-sm text-red-800">{formError}</div>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name *" value={form.name} onChange={updateField("name")} placeholder="Jane Smith" />
          <Field
            label="Email *"
            type="email"
            value={form.email}
            onChange={updateField("email")}
            placeholder="jane@yourclinic.com"
          />
          <div className="sm:col-span-2">
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-500">
              Password *
            </label>
            <div className="mt-1 flex gap-2">
              <input
                type={showPassword ? "text" : "password"}
                className="w-full rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-gray-950 focus:outline-none"
                placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
                value={form.password}
                onChange={updateField("password")}
              />
              <Button
                variant="secondary"
                onClick={() => {
                  setForm((prev) => ({ ...prev, password: suggestPassword() }));
                  setShowPassword(true);
                }}
              >
                Generate
              </Button>
            </div>
            <label className="mt-2 flex items-center gap-2 text-xs text-gray-500">
              <input
                type="checkbox"
                checked={showPassword}
                onChange={(e) => setShowPassword(e.target.checked)}
              />
              Show password so you can copy it
            </label>
            <p className="mt-1 text-xs text-gray-400">
              {MIN_PASSWORD_LENGTH}+ characters and at least three of: lowercase, uppercase, numbers,
              symbols.
            </p>
          </div>
        </div>
      </Modal>

      <Modal
        open={!!removeRow}
        onClose={() => setRemoveRow(null)}
        title="Remove this staff account?"
        description={removeRow ? `${removeRow.name} — ${removeRow.email}` : ""}
        footer={
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setRemoveRow(null)} disabled={busyId === removeRow?.id}>
              Keep
            </Button>
            <Button
              variant="danger"
              onClick={() => removeStaff(removeRow)}
              disabled={busyId === removeRow?.id}
            >
              {busyId === removeRow?.id ? "Removing..." : "Remove permanently"}
            </Button>
          </div>
        }
      >
        <p className="text-sm text-gray-700">
          The account is deleted and they are signed out everywhere immediately. This cannot be
          undone — you would have to create the account again.
        </p>
        <p className="mt-3 text-sm text-gray-500">
          Contacts they added are kept, and the audit trail still shows what they did. If they are
          only away for a while, <strong>Suspend</strong> does the same thing to their access while
          keeping the account.
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
