import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, CalendarCheck, CheckCircle2, Circle, PhoneCall, Target, Timer, TrendingUp, Users } from "lucide-react";
import api from "../lib/api";
import { useLabels } from "../store/clinicStore";
import ChartCard from "../components/ChartCard";
import DataTable from "../components/DataTable";
import StatCard from "../components/StatCard";
import { Badge } from "../components/ui/Badge";

const COLORS = ["#111827", "#6b7280", "#d1d5db", "#f59e0b", "#10b981", "#ef4444"];
const STAGE_COLORS = ["bg-gray-950", "bg-gray-600", "bg-emerald-500"];
const nf = new Intl.NumberFormat("en-IN");

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
  const [funnel, setFunnel] = useState(null);
  const [onboarding, setOnboarding] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get("/stats/overview").then((res) => { if (res.data?.success) setData(res.data.data); }).catch(() => {}),
      api.get("/stats/funnel").then((res) => { if (res.data?.success) setFunnel(res.data.data); }).catch(() => {}),
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
  const outcomes = data?.outcomes || [];
  const recent = data?.recent || [];

  const f = funnel || {};
  const stages = [
    { label: "Calls received", value: f.calls ?? 0 },
    { label: "Answered", value: f.answered ?? 0 },
    { label: `${labels.bookings} booked`, value: f.appointments ?? 0 },
  ];
  const maxStage = Math.max(f.calls ?? 0, 1);

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

      {/* 5 cards: 2-up on small, 3-up on md (so the last row holds 2, not 1),
          then 5-up on xl. Avoids a single orphaned card at tablet widths. */}
      <section className="grid gap-4 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-5">
        <StatCard title="Total calls" value={totals.calls ?? 0} icon={PhoneCall} loading={loading} />
        <StatCard title="Calls today" value={calls.today ?? 0} icon={Activity} tone="light" loading={loading} />
        <StatCard title={labels.bookings} value={totals.appointments ?? 0} icon={CalendarCheck} tone="light" loading={loading} />
        <StatCard title={labels.contacts} value={totals.contacts ?? 0} icon={Users} tone="light" loading={loading} />
        <StatCard title="Avg duration" value={fmtDuration(calls.avgDurationSec)} icon={Timer} tone="light" loading={loading} />
      </section>

      <section className="grid gap-6 xl:grid-cols-3">
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

        <ChartCard title="Call outcomes" description="Distribution by status">
          {outcomes.length === 0 ? (
            <div className="grid h-full place-items-center px-6 text-center text-sm text-gray-400">
              This fills in once your assistant starts taking calls.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={outcomes} dataKey="count" nameKey="status" innerRadius={62} outerRadius={98} paddingAngle={4}>
                  {outcomes.map((entry, index) => (
                    <Cell key={entry.status} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard title="Calls this week" description="Total received in the last 7 days">
          <div className="grid h-full place-items-center">
            <div className="text-center">
              {loading ? (
                <div className="mx-auto h-14 w-24 animate-pulse rounded-xl bg-gray-200/80" aria-hidden="true" />
              ) : (
                <p className="text-6xl font-semibold tracking-tight text-gray-950">{calls.last7Days ?? 0}</p>
              )}
              <p className="mt-2 text-sm text-gray-500">{calls.active ?? 0} active right now</p>
            </div>
          </div>
        </ChartCard>
      </section>

      {/* Conversion funnel (last 30 days) */}
      <section className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-950">Conversion funnel</h2>
          <p className="text-sm text-gray-500">Last {f.periodDays ?? 30} days</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <StatCard title="Answer rate" value={`${f.answerRate ?? 0}%`} icon={Target} tone="light" loading={loading} />
          <StatCard title="Booking conversion" value={`${f.conversionRate ?? 0}%`} icon={TrendingUp} tone="light" loading={loading} />
          <StatCard title="Calls answered" value={nf.format(f.answered ?? 0)} icon={PhoneCall} tone="light" loading={loading} />
        </div>
        <div className="panel rounded-3xl p-6">
          {(f.calls ?? 0) === 0 ? (
            <div className="grid place-items-center py-8 text-center text-sm text-gray-400">
              No calls in the last {f.periodDays ?? 30} days yet — your funnel appears here after the first call.
            </div>
          ) : (
            <div className="space-y-4">
              {stages.map((s, i) => (
                <div key={s.label}>
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span className="text-gray-600">{s.label}</span>
                    <span className="font-semibold text-gray-950">{nf.format(s.value)}</span>
                  </div>
                  <div className="h-3 w-full overflow-hidden rounded-full bg-gray-100">
                    <div className={`h-full rounded-full ${STAGE_COLORS[i]}`} style={{ width: `${Math.max((s.value / maxStage) * 100, s.value > 0 ? 4 : 0)}%` }} />
                  </div>
                </div>
              ))}
              <p className="pt-1 text-xs text-gray-400">
                {nf.format(f.leads ?? 0)} {labels.contacts.toLowerCase()} captured
              </p>
            </div>
          )}
        </div>
      </section>

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
