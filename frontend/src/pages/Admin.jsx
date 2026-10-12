import { useEffect, useState, useCallback } from "react";
import { ShieldCheck, Pencil, Activity } from "lucide-react";
import api from "../lib/api";
import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";

const nf = new Intl.NumberFormat("en-IN");

function extractError(err) {
  const d = err?.response?.data;
  if (err?.response?.status === 403) return "You don't have platform admin access.";
  if (d) {
    if (d.message) return d.message;
    if (typeof d.error === "string" && d.error) return d.error;
    if (d.detail) return Array.isArray(d.detail) ? d.detail.map((x) => x.msg).join(", ") : d.detail;
  }
  return "Could not reach the server.";
}

export default function Admin() {
  const [tenants, setTenants] = useState([]);
  const [plans, setPlans] = useState([]);
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [banner, setBanner] = useState(null);
  const [busyReq, setBusyReq] = useState(null);

  const [selected, setSelected] = useState(null);
  const [planKey, setPlanKey] = useState("");
  const [allowance, setAllowance] = useState("");
  const [selectedStatus, setSelectedStatus] = useState("active");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  const [diag, setDiag] = useState([]);
  const [diagLoading, setDiagLoading] = useState(false);

  const runDiagnostics = async () => {
    setDiagLoading(true);
    try {
      const res = await api.get("/admin/diagnostics");
      if (res.data?.success) setDiag(res.data.data || []);
    } catch (err) {
      setBanner({ type: "error", text: extractError(err) });
    } finally {
      setDiagLoading(false);
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [tRes, pRes, rRes] = await Promise.all([
        api.get("/admin/tenants"),
        api.get("/admin/plans"),
        api.get("/admin/upgrade-requests"),
      ]);
      if (tRes.data?.success) setTenants(tRes.data.data || []);
      if (pRes.data?.success) setPlans(pRes.data.data || []);
      if (rRes.data?.success) setRequests(rRes.data.data || []);
    } catch (err) {
      setError(extractError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const resolveRequest = async (id, action) => {
    setBusyReq(id);
    setBanner(null);
    try {
      const res = await api.put(`/admin/upgrade-requests/${id}`, { action });
      if (res.data?.success) {
        setBanner({ type: "success", text: `Request ${action === "approve" ? "approved" : "rejected"}.` });
        load();
      } else {
        setBanner({ type: "error", text: res.data?.message || "Could not update request." });
      }
    } catch (err) {
      setBanner({ type: "error", text: extractError(err) });
    } finally {
      setBusyReq(null);
    }
  };

  const updateStatus = async (id, newStatus) => {
    setBanner(null);
    try {
      const res = await api.put(`/admin/tenants/${id}/status`, { status: newStatus });
      if (res.data?.success) {
        setBanner({ type: "success", text: `Tenant status updated to ${newStatus}.` });
        load();
      } else {
        setBanner({ type: "error", text: res.data?.message || "Could not update status." });
      }
    } catch (err) {
      setBanner({ type: "error", text: extractError(err) });
    }
  };

  useEffect(() => {
    load();
  }, [load]);

  const openEdit = (row) => {
    setFormError("");
    setPlanKey(row.subscription || "free");
    setAllowance(row.customAllowance ? String(row.customAllowance) : "");
    setSelectedStatus(row.status || "active");
    setSelected(row);
  };

  const save = async () => {
    if (!selected) return;
    setSaving(true);
    setFormError("");
    const parsed = allowance.trim() === "" ? 0 : parseInt(allowance, 10);
    if (allowance.trim() !== "" && (Number.isNaN(parsed) || parsed < 0)) {
      setFormError("Custom allowance must be a positive number, or blank to use the plan default.");
      setSaving(false);
      return;
    }
    try {
      const planPromise = api.put(`/admin/tenants/${selected.id}/plan`, {
        subscription: planKey,
        monthly_call_limit: parsed,
      });
      const statusPromise = (selectedStatus !== selected.status)
        ? api.put(`/admin/tenants/${selected.id}/status`, { status: selectedStatus })
        : Promise.resolve({ data: { success: true } });

      const [pRes, sRes] = await Promise.all([planPromise, statusPromise]);
      if (pRes.data?.success && sRes.data?.success) {
        setBanner({ type: "success", text: `Updated ${selected.name}.` });
        setSelected(null);
        load();
      } else {
        setFormError(pRes.data?.message || sRes.data?.message || "Could not update client.");
      }
    } catch (err) {
      setFormError(extractError(err));
    } finally {
      setSaving(false);
    }
  };

  const columns = [
    { key: "name", header: "Business" },
    { key: "industry", header: "Industry", render: (r) => r.industry || "—" },
    {
      key: "status",
      header: "Status",
      render: (r) => {
        const s = r.status || "active";
        const tone = s === "active" ? "success" : s === "pending" ? "warning" : "danger";
        return <Badge tone={tone}>{s}</Badge>;
      },
    },
    { key: "planName", header: "Plan", render: (r) => <Badge tone="neutral">{r.planName}</Badge> },
    {
      key: "monthlyCallLimit",
      header: "Allowance",
      render: (r) => (
        <span className="flex items-center gap-2">
          {nf.format(r.monthlyCallLimit)}/mo
          {r.customAllowance ? <Badge tone="warning">custom</Badge> : null}
        </span>
      ),
    },
    { key: "callsUsed", header: "Used (mo)", render: (r) => `${nf.format(r.callsUsed)} / ${nf.format(r.monthlyCallLimit)}` },
    { key: "teamSize", header: "Team", render: (r) => r.teamSize ?? 0 },
    { key: "createdAt", header: "Joined", render: (r) => (r.createdAt ? new Date(r.createdAt).toLocaleDateString() : "—") },
    {
      key: "actions",
      header: "Actions",
      render: (r) => (
        <Button variant="secondary" size="sm" onClick={() => openEdit(r)}>
          <Pencil className="h-3.5 w-3.5" /> Edit
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-6 w-6 text-gray-700" />
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-gray-950">Admin</h1>
          <p className="mt-1 text-sm text-gray-500">Assign plans and custom call allowances for each client.</p>
        </div>
      </div>

      {banner && (
        <div className="flex items-start justify-between gap-3 rounded-2xl border border-emerald-100 bg-emerald-50 p-4 text-sm text-emerald-800">
          <span>{banner.text}</span>
          <button className="text-xs font-medium opacity-70 hover:opacity-100" onClick={() => setBanner(null)}>Dismiss</button>
        </div>
      )}

      <section className="panel rounded-3xl p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-950">System diagnostics</h2>
            <p className="mt-1 text-sm text-gray-500">Check that each integration is configured and reachable before going live.</p>
          </div>
          <Button variant="secondary" onClick={runDiagnostics} disabled={diagLoading}>
            <Activity className="h-4 w-4" /> {diagLoading ? "Checking..." : "Run checks"}
          </Button>
        </div>
        {diag.length > 0 && (
          <ul className="mt-4 space-y-2">
            {diag.map((c) => (
              <li key={c.name} className="flex items-start justify-between gap-3 rounded-2xl border border-gray-100 p-3">
                <div>
                  <p className="text-sm font-medium text-gray-950">{c.name}</p>
                  <p className="text-xs text-gray-500">{c.detail}</p>
                </div>
                <Badge tone={c.status === "ok" ? "success" : c.status === "warn" ? "warning" : "danger"}>{c.status}</Badge>
              </li>
            ))}
          </ul>
        )}
      </section>

      {!error && tenants.some((t) => t.status === "pending") && (
        <section className="panel rounded-3xl p-5 border border-amber-200 bg-amber-50/40">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-amber-600" />
            <h2 className="text-lg font-semibold text-gray-950">Pending tenant approvals</h2>
          </div>
          <p className="mt-1 text-sm text-gray-500">New signups awaiting verification before their agents can receive or make calls.</p>
          <div className="mt-4 space-y-3">
            {tenants.filter((t) => t.status === "pending").map((t) => (
              <div key={t.id} className="flex flex-col gap-3 rounded-2xl border border-amber-100 bg-white p-4 sm:flex-row sm:items-center sm:justify-between shadow-xs">
                <div>
                  <p className="text-sm font-semibold text-gray-950">{t.name}</p>
                  <p className="text-xs text-gray-500">
                    Industry: {t.industry || "General"} · Joined {t.createdAt ? new Date(t.createdAt).toLocaleDateString() : "recently"}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => updateStatus(t.id, "active")}>Approve</Button>
                  <Button variant="secondary" size="sm" onClick={() => updateStatus(t.id, "suspended")}>Suspend</Button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {!error && requests.some((r) => r.status === "pending") && (
        <section className="panel rounded-3xl p-5">
          <h2 className="text-lg font-semibold text-gray-950">Pending upgrade requests</h2>
          <div className="mt-4 space-y-3">
            {requests.filter((r) => r.status === "pending").map((r) => (
              <div key={r.id} className="flex flex-col gap-3 rounded-2xl border border-gray-100 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-semibold text-gray-950">{r.business}</p>
                  <p className="text-xs text-gray-500">
                    {r.currentPlan || "—"} → <span className="font-medium text-gray-900">{r.requestedPlanName}</span>
                    {r.createdAt ? ` · ${new Date(r.createdAt).toLocaleDateString()}` : ""}
                  </p>
                  {r.note && <p className="mt-1 text-xs italic text-gray-500">{r.note}</p>}
                </div>
                <div className="flex gap-2">
                  <Button size="sm" disabled={busyReq === r.id} onClick={() => resolveRequest(r.id, "approve")}>Approve</Button>
                  <Button variant="secondary" size="sm" disabled={busyReq === r.id} onClick={() => resolveRequest(r.id, "reject")}>Reject</Button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {error ? (
        <div className="rounded-2xl border border-red-100 bg-red-50 p-4 text-sm text-red-800">{error}</div>
      ) : (
        <>
          <h2 className="text-lg font-semibold text-gray-950">Clients</h2>
          <DataTable columns={columns} rows={tenants} loading={loading} emptyTitle="No client businesses yet" />
        </>
      )}

      <Modal
        open={!!selected}
        onClose={() => setSelected(null)}
        title={selected ? `Edit client — ${selected.name}` : "Edit client"}
        description="Set the subscription plan, monthly call allowance, and account status."
        footer={
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setSelected(null)}>Cancel</Button>
            <Button onClick={save} disabled={saving}>{saving ? "Saving..." : "Save"}</Button>
          </div>
        }
      >
        {formError && (
          <div className="mb-4 rounded-2xl border border-red-100 bg-red-50 p-3 text-sm text-red-800">{formError}</div>
        )}
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-500">Status</label>
            <select
              className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-sm focus:border-brand-500 focus:outline-none"
              value={selectedStatus}
              onChange={(e) => setSelectedStatus(e.target.value)}
            >
              <option value="active">Active</option>
              <option value="pending">Pending</option>
              <option value="suspended">Suspended</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-500">Plan</label>
            <select
              className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-sm focus:border-brand-500 focus:outline-none"
              value={planKey}
              onChange={(e) => setPlanKey(e.target.value)}
            >
              {plans.map((p) => (
                <option key={p.key} value={p.key}>{p.name} ({nf.format(p.monthly_call_limit)}/mo)</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-500">Custom allowance (calls / month)</label>
            <input
              type="number"
              min="0"
              className="mt-1 w-full rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-brand-500 focus:outline-none"
              placeholder="Leave blank to use the plan default"
              value={allowance}
              onChange={(e) => setAllowance(e.target.value)}
            />
            <p className="mt-1 text-xs text-gray-400">Overrides the plan's allowance for this client only. Blank or 0 clears the override.</p>
          </div>
        </div>
      </Modal>
    </div>
  );
}
