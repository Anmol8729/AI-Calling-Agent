import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, CalendarCheck, CheckCircle2, Circle, PhoneCall, Users } from "lucide-react";
import api from "../lib/api";
import { useLabels } from "../store/clinicStore";
import ChartCard from "../components/ChartCard";
import CurrentPlanCard from "../components/CurrentPlanCard";
import DataTable from "../components/DataTable";
import StatCard from "../components/StatCard";
import { Badge } from "../components/ui/Badge";

const fmtDuration = (s) => `${Math.floor((s || 0) / 60)}m ${(s || 0) % 60}s`;
const dayLabel = (iso) => {
  try {
    return new Date(iso).toLocaleDateString(undefined, { weekday: "short" });
  } catch {
    return iso;
  }
};
const toneFor = (status) => {
  const s = (status || "").toLowerCase();
  if (["completed", "active"].includes(s)) return "success";
  if (s === "transferred") return "warning";
  if (["failed", "no-answer"].includes(s)) return "danger";
  return "neutral";
};

export default function Dashboard() {
  const labels = useLabels();
  const [data, setData] = useState(null);
  const [onboarding, setOnboarding] = useState(null);
  const [loading, setLoading] = useState(true);

  // /stats/funnel is no longer requested: the conversion funnel it fed was removed,
  // and nothing else on this page reads it.
  useEffect(() => {
    Promise.all([
      api.get("/stats/overview").then((res) => { if (res.data?.success) setData(res.data.data); }).catch(() => {}),
      api.get("/stats/onboarding").then((res) => { if (res.data?.success) setOnboarding(res.data.data); }).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  const ob = onboarding || {};
  const setupSteps = [
    { key: "industry", label: "Choose your industry", to: "/setup", done: ob.industry },
    { key: "knowledgeBase", label: "Add your business knowledge base", to: "/setup", done: ob.knowledgeBase },
    { key: "phoneNumber", label: "Connect your phone number", to: "/setup", done: ob.phoneNumber },
    { key: "agentConfigured", label: "Set your agent's voice & language", to: "/setup", done: ob.agentConfigured },
    { key: "firstCall", label: "Receive your first call", to: null, done: ob.firstCall },
  ];
  const showChecklist = onboarding && !ob.complete;
  const doneCount = setupSteps.filter((s) => s.done).length;

  const totals = data?.totals || {};
  const calls = data?.calls || {};
  const daily = (data?.daily || []).map((d) => ({ ...d, label: dayLabel(d.date) }));
  const recent = data?.recent || [];

  const columns = [
    { key: "customer", header: "Caller" },
    { key: "phone", header: "Phone" },
    { key: "direction", header: "Direction", render: (row) => <span className="capitalize">{row.direction}</span> },
    { key: "duration", header: "Duration", render: (row) => fmtDuration(row.duration) },
    { key: "status", header: "Status", render: (row) => <Badge tone={toneFor(row.status)}>{row.status}</Badge> },
    { key: "date", header: "When", render: (row) => (row.date ? new Date(row.date).toLocaleString() : "—") },
  ];

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium text-gray-500">Inbound reception center</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight text-gray-950">Dashboard</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-500">A live view of calls, appointments, and your AI receptionist's activity.</p>
      </div>

      {/* Plan + allowance. Reads billingStore, the same cached /billing/summary the
          Billing page uses, so the two screens cannot disagree. */}
      <CurrentPlanCard />

      {showChecklist && (
        <section className="panel rounded-3xl border border-gray-100 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-950">Finish setting up</h2>
              <p className="mt-1 text-sm text-gray-500">Complete these steps to get your AI receptionist live.</p>
            </div>
            <span className="text-sm font-medium text-gray-500">{doneCount}/{setupSteps.length}</span>
          </div>
          <ul className="mt-4 space-y-2">
            {setupSteps.map((s) => (
              <li key={s.key} className="flex items-center gap-3">
                {s.done ? (
                  <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                ) : (
                  <Circle className="h-5 w-5 text-gray-300" />
                )}
                {s.done || !s.to ? (
                  <span className={`text-sm ${s.done ? "text-gray-400 line-through" : "text-gray-700"}`}>{s.label}</span>
                ) : (
                  <Link to={s.to} className="text-sm font-medium text-gray-900 hover:underline">{s.label}</Link>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 4 cards: 2-up until xl, then 4-up. Deliberately no 3-column step — that
          would leave the fourth card alone on its own row at tablet widths. */}
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard title="Total calls" value={totals.calls ?? 0} icon={PhoneCall} loading={loading} />
        <StatCard title="Calls today" value={calls.today ?? 0} icon={Activity} tone="light" loading={loading} />
        <StatCard title={labels.bookings} value={totals.appointments ?? 0} icon={CalendarCheck} tone="light" loading={loading} />
        <StatCard title={labels.contacts} value={totals.contacts ?? 0} icon={Users} tone="light" loading={loading} />
      </section>

      {/* One chart, so full width rather than a third of a three-column grid with two
          empty cells. The trend reads better with the extra room anyway. */}
      <ChartCard title="Daily inbound calls" description="Calls received over the last 7 days">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={daily}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} />
            <Tooltip />
            <Line type="monotone" dataKey="count" stroke="#111827" strokeWidth={3} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold text-gray-950">Recent calls</h2>
        <DataTable
          columns={columns}
          rows={recent}
          loading={loading}
          emptyTitle="No calls yet"
          emptyDescription="Every call your assistant answers will appear here, with who called and what happened."
          emptyIcon={PhoneCall}
        />
      </section>
    </div>
  );
}
