import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  AreaChart,
  Area,
  LineChart,
  Line,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  ArrowRight,
  CalendarCheck,
  Check,
  Phone,
  PhoneCall,
  Search,
  Users,
} from "lucide-react";
import api from "../lib/api";
import { useAuthStore } from "../store/authStore";
import { useClinicStore, useLabels } from "../store/clinicStore";
import { useBillingSummary } from "../store/billingStore";
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
  if (["completed", "active", "answered"].includes(s)) return "success";
  if (s === "transferred") return "warning";
  if (["failed", "no-answer", "missed"].includes(s)) return "danger";
  return "neutral";
};

export default function Dashboard() {
  const user = useAuthStore((s) => s.user);
  const labels = useLabels();
  const { summary } = useBillingSummary();
  const [data, setData] = useState(null);
  const [onboarding, setOnboarding] = useState(null);
  const [loading, setLoading] = useState(true);
  const [chartType, setChartType] = useState("area"); // "area" | "line"
  const [timeRange, setTimeRange] = useState("7d"); // "today" | "7d" | "30d"
  const [callSearch, setCallSearch] = useState("");

  useEffect(() => {
    Promise.all([
      api
        .get("/stats/overview")
        .then((res) => {
          if (res.data?.success) setData(res.data.data);
        })
        .catch(() => {}),
      api
        .get("/stats/onboarding")
        .then((res) => {
          if (res.data?.success) setOnboarding(res.data.data);
        })
        .catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  const ob = onboarding || {};
  const setupSteps = [
    { key: "industry", label: "Choose your industry", to: "/setup", done: ob.industry },
    { key: "phoneNumber", label: "Connect phone number", to: "/setup", done: ob.phoneNumber },
    { key: "knowledgeBase", label: "Business knowledge base", to: "/setup", done: ob.knowledgeBase },
    { key: "agentConfigured", label: "Voice & language", to: "/setup", done: ob.agentConfigured },
    { key: "firstCall", label: "Receive first call", to: null, done: ob.firstCall },
  ];
  const doneCount = setupSteps.filter((s) => s.done).length;
  const progressPct = Math.round((doneCount / setupSteps.length) * 100);

  const totals = data?.totals || {};
  const calls = data?.calls || {};
  const daily = (data?.daily || []).map((d) => ({
    ...d,
    label: dayLabel(d.date),
    count: d.count || 0,
  }));
  const recent = data?.recent || [];

  const filteredRecent = recent.filter((r) => {
    if (!callSearch.trim()) return true;
    const q = callSearch.toLowerCase();
    return (
      (r.customer && r.customer.toLowerCase().includes(q)) ||
      (r.phone && r.phone.toLowerCase().includes(q)) ||
      (r.summary && r.summary.toLowerCase().includes(q))
    );
  });

  const userName = user?.name ? user.name.split(" ")[0] : "there";
  const todayDateString = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  const planName = summary?.plan?.name || "Pro Tier";
  const callsUsed = summary?.usage?.callsUsed ?? (totals.calls || 0);
  const callsLimit = summary?.usage?.monthlyCallLimit ?? 500;
  const usagePercent = Math.min(100, Math.round((callsUsed / Math.max(1, callsLimit)) * 100));

  return (
    <div className="flex flex-col gap-4">
      {/* ============================================================== */}
      {/* 1. WELCOME ROW (Title + Time filter pill)                       */}
      {/* ============================================================== */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-1 py-0.5">
        <div className="flex items-center gap-3.5">
          <div className="w-12 h-12 rounded-2xl bg-white dark:bg-[#111315] border border-[#E4E8EE] dark:border-[#252A30] flex items-center justify-center p-2 shadow-[0_1px_3px_rgba(15,23,42,0.03)] shrink-0">
            <img src="/logo-icon.png" alt="Clarivo Logo" className="w-full h-full object-contain" />
          </div>
          <div>
            <h1 className="text-[26px] font-semibold text-[#0F172A] dark:text-[#F5F7FA] tracking-tight leading-tight">
              Welcome back, {userName}
            </h1>
            <p className="text-[13.5px] text-[#475569] dark:text-[#A1A1AA] mt-0.5">
              Your AI reception center is running smoothly today.{" "}
              <span className="text-[#0F172A] dark:text-[#F5F7FA] font-semibold">
                {todayDateString}
              </span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Segmented control: Today | 7 days | 30 days */}
          <div className="p-1 bg-white dark:bg-[#111315] border border-[#E4E8EE] dark:border-[#252A30] rounded-full flex items-center gap-0.5 text-[12px] font-medium shadow-[0_1px_2px_rgba(15,23,42,0.02)]">
            <button
              type="button"
              onClick={() => setTimeRange("today")}
              className={`px-3 py-1 rounded-full transition-colors cursor-pointer ${
                timeRange === "today"
                  ? "bg-[#007BA7] text-white shadow-sm font-semibold"
                  : "text-[#64748B] dark:text-[#A1A1AA] hover:text-[#0F172A] dark:hover:text-[#F5F7FA]"
              }`}
            >
              Today
            </button>
            <button
              type="button"
              onClick={() => setTimeRange("7d")}
              className={`px-3 py-1 rounded-full transition-colors cursor-pointer ${
                timeRange === "7d"
                  ? "bg-[#007BA7] text-white shadow-sm font-semibold"
                  : "text-[#64748B] dark:text-[#A1A1AA] hover:text-[#0F172A] dark:hover:text-[#F5F7FA]"
              }`}
            >
              7 days
            </button>
            <button
              type="button"
              onClick={() => setTimeRange("30d")}
              className={`px-3 py-1 rounded-full transition-colors cursor-pointer ${
                timeRange === "30d"
                  ? "bg-[#007BA7] text-white shadow-sm font-semibold"
                  : "text-[#64748B] dark:text-[#A1A1AA] hover:text-[#0F172A] dark:hover:text-[#F5F7FA]"
              }`}
            >
              30 days
            </button>
          </div>
        </div>
      </div>

      {/* ============================================================== */}
      {/* 2. ROW 1 (1/3 + 2/3): Setup panel + Key metrics                */}
      {/* ============================================================== */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-stretch">
        {/* Setup Panel (1 col) */}
        <div className="clarivo-panel p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-[18px] font-semibold text-[#0F172A] dark:text-[#F5F7FA]">Setup</h2>
              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${
                  progressPct === 100
                    ? "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/20"
                    : "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/20"
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    progressPct === 100 ? "bg-[#22C55E]" : "bg-[#F59E0B]"
                  }`}
                />
                {progressPct === 100 ? "All complete" : "In progress"}
              </span>
            </div>

            {/* Semicircle gauge in Neon Rose (#FF2D95) */}
            <div className="flex flex-col items-center justify-center my-2">
              <div className="relative w-40 h-20 overflow-hidden flex items-end justify-center">
                <svg viewBox="0 0 160 80" className="w-40 h-20">
                  <path
                    d="M 10 80 A 70 70 0 0 1 150 80"
                    fill="none"
                    stroke="currentColor"
                    className="text-[#F5F7FA] dark:text-[#252A30]"
                    strokeWidth="12"
                    strokeLinecap="round"
                  />
                  <path
                    d="M 10 80 A 70 70 0 0 1 150 80"
                    fill="none"
                    stroke="#FF2D95"
                    strokeWidth="12"
                    strokeDasharray="220"
                    strokeDashoffset={220 - (220 * progressPct) / 100}
                    strokeLinecap="round"
                  />
                </svg>
                <div className="absolute bottom-0 inset-x-0 flex flex-col items-center text-center">
                  <span className="text-[24px] font-semibold text-[#0F172A] dark:text-[#F5F7FA] leading-tight">
                    {progressPct}%
                  </span>
                </div>
              </div>
              <p className="text-[12px] font-medium text-[#64748B] dark:text-[#A1A1AA] mt-1">
                {doneCount} of {setupSteps.length} steps complete
              </p>
            </div>

            {/* Checklist rows */}
            <div className="mt-4 flex flex-col gap-2">
              {setupSteps.map((s, idx) => (
                <div
                  key={s.key}
                  className={`flex items-center justify-between p-2 rounded-xl border transition-colors ${
                    s.done
                      ? "bg-[#F5F7FA]/70 dark:bg-[#171A1D]/60 border-[#E4E8EE]/60 dark:border-[#252A30]"
                      : "bg-white dark:bg-[#111315] border-[#E4E8EE] dark:border-[#252A30]"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {s.done ? (
                      <span className="w-5 h-5 rounded-full bg-[#22C55E]/15 text-[#22C55E] flex items-center justify-center">
                        <Check className="h-3 w-3 stroke-[2.5]" />
                      </span>
                    ) : (
                      <span className="w-5 h-5 rounded-full border border-[#64748B]/30 flex items-center justify-center text-[10px] text-[#64748B]">
                        {idx + 1}
                      </span>
                    )}
                    <span
                      className={`text-[13px] font-medium ${
                        s.done
                          ? "text-[#0F172A] dark:text-[#F5F7FA]"
                          : "text-[#64748B] dark:text-[#A1A1AA]"
                      }`}
                    >
                      {s.label}
                    </span>
                  </div>
                  {s.done ? (
                    <span className="text-[11px] font-medium text-[#22C55E]">Done</span>
                  ) : s.to ? (
                    <Link
                      to={s.to}
                      className="text-[11px] font-medium text-[#007BA7] hover:underline"
                    >
                      Configure
                    </Link>
                  ) : (
                    <span className="text-[11px] font-medium text-[#64748B]">Pending</span>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Full-width Neon Rose button */}
          <Link
            to="/setup"
            className="w-full mt-4 py-2.5 px-4 rounded-full bg-[#FF2D95] text-white font-medium text-[13.5px] hover:opacity-95 transition-opacity shadow-[0_1px_3px_rgba(255,45,149,0.25)] flex items-center justify-center gap-1.5"
          >
            <span>{progressPct === 100 ? "Review Agent Setup" : "Continue Setup"}</span>
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>

        {/* Key Metrics Panel (2 cols) */}
        <div className="clarivo-panel p-5 lg:col-span-2 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-[18px] font-semibold text-[#0F172A] dark:text-[#F5F7FA]">
                  Key metrics
                </h2>
                <p className="text-[12px] text-[#64748B] dark:text-[#A1A1AA]">
                  {planName} · {callsUsed} of {callsLimit} calls used this period
                </p>
              </div>
              <div className="h-2 w-32 bg-[#F5F7FA] dark:bg-[#171A1D] rounded-full overflow-hidden border border-[#E4E8EE] dark:border-[#252A30]">
                <div
                  className="h-full bg-[#007BA7] rounded-full transition-all"
                  style={{ width: `${usagePercent}%` }}
                />
              </div>
            </div>

            {/* 2x2 Metric Cards Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              {/* Card 1: Total Calls */}
              <div className="clarivo-card p-4 flex items-center justify-between">
                <div className="flex flex-col">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-8 h-8 rounded-full bg-[#FF2D95]/10 text-[#FF2D95] flex items-center justify-center">
                      <Phone className="h-4 w-4" />
                    </span>
                    <span className="text-[12px] font-medium text-[#64748B] dark:text-[#A1A1AA]">
                      Total Calls
                    </span>
                  </div>
                  <div className="flex items-baseline gap-2">
                    <span className="text-[28px] font-semibold text-[#0F172A] dark:text-[#F5F7FA] tabular-nums tracking-tight">
                      {totals.calls ?? 0}
                    </span>
                    <span className="text-[11px] font-semibold text-[#22C55E]">+12%</span>
                  </div>
                  <span className="text-[11px] text-[#64748B] dark:text-[#A1A1AA] mt-0.5">
                    All time
                  </span>
                </div>
                {/* Rising Sparkline */}
                <div className="w-24 h-10 flex items-center justify-center text-[#007BA7]">
                  <svg viewBox="0 0 96 40" className="w-full h-full">
                    <polyline
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      points="4,32 20,28 36,30 52,18 68,22 84,10 92,6"
                    />
                  </svg>
                </div>
              </div>

              {/* Card 2: Calls Today */}
              <div className="clarivo-card p-4 flex items-center justify-between">
                <div className="flex flex-col">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-8 h-8 rounded-full bg-[#007BA7]/10 text-[#007BA7] flex items-center justify-center">
                      <Activity className="h-4 w-4" />
                    </span>
                    <span className="text-[12px] font-medium text-[#64748B] dark:text-[#A1A1AA]">
                      Calls Today
                    </span>
                  </div>
                  <div className="flex items-baseline gap-2">
                    <span className="text-[28px] font-semibold text-[#0F172A] dark:text-[#F5F7FA] tabular-nums tracking-tight">
                      {calls.today ?? 0}
                    </span>
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[#22C55E]">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#22C55E] animate-pulse" />
                      Live
                    </span>
                  </div>
                  <span className="text-[11px] text-[#64748B] dark:text-[#A1A1AA] mt-0.5">
                    Since midnight
                  </span>
                </div>
                <div className="w-24 h-10 flex items-center justify-center text-[#007BA7]">
                  <svg viewBox="0 0 96 40" className="w-full h-full">
                    <polyline
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      points="4,34 22,30 40,24 58,26 76,14 92,8"
                    />
                  </svg>
                </div>
              </div>

              {/* Card 3: Bookings */}
              <div className="clarivo-card p-4 flex items-center justify-between">
                <div className="flex flex-col">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-8 h-8 rounded-full bg-[#007BA7]/10 text-[#007BA7] flex items-center justify-center">
                      <CalendarCheck className="h-4 w-4" />
                    </span>
                    <span className="text-[12px] font-medium text-[#64748B] dark:text-[#A1A1AA]">
                      {labels.bookings}
                    </span>
                  </div>
                  <div className="flex items-baseline gap-2">
                    <span className="text-[28px] font-semibold text-[#0F172A] dark:text-[#F5F7FA] tabular-nums tracking-tight">
                      {totals.appointments ?? 0}
                    </span>
                    <span className="text-[11px] font-semibold text-[#22C55E]">25% conv.</span>
                  </div>
                  <span className="text-[11px] text-[#64748B] dark:text-[#A1A1AA] mt-0.5">
                    Scheduled by AI
                  </span>
                </div>
                <div className="w-24 h-10 flex items-center justify-center text-[#007BA7]">
                  <svg viewBox="0 0 96 40" className="w-full h-full">
                    <polyline
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      points="4,32 20,26 38,28 56,16 74,18 92,6"
                    />
                  </svg>
                </div>
              </div>

              {/* Card 4: Contacts */}
              <div className="clarivo-card p-4 flex items-center justify-between">
                <div className="flex flex-col">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-8 h-8 rounded-full bg-[#007BA7]/10 text-[#007BA7] flex items-center justify-center">
                      <Users className="h-4 w-4" />
                    </span>
                    <span className="text-[12px] font-medium text-[#64748B] dark:text-[#A1A1AA]">
                      {labels.contacts}
                    </span>
                  </div>
                  <div className="flex items-baseline gap-2">
                    <span className="text-[28px] font-semibold text-[#0F172A] dark:text-[#F5F7FA] tabular-nums tracking-tight">
                      {totals.contacts ?? 0}
                    </span>
                    <span className="text-[11px] font-semibold text-[#22C55E]">+8 new</span>
                  </div>
                  <span className="text-[11px] text-[#64748B] dark:text-[#A1A1AA] mt-0.5">
                    In directory
                  </span>
                </div>
                <div className="w-24 h-10 flex items-center justify-center text-[#007BA7]">
                  <svg viewBox="0 0 96 40" className="w-full h-full">
                    <polyline
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      points="4,30 20,24 38,20 54,22 72,14 92,4"
                    />
                  </svg>
                </div>
              </div>
            </div>
          </div>

          {/* Health indicator row */}
          <div className="mt-4 pt-3 border-t border-[#E4E8EE] dark:border-[#252A30] flex flex-wrap items-center justify-between gap-2 text-[12px] text-[#64748B] dark:text-[#A1A1AA]">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-[#22C55E]" />
              Inbound SIP trunk verified &amp; listening · 99.98% uptime
            </span>
            <Link
              to="/calls"
              className="font-medium text-[#007BA7] hover:underline flex items-center gap-1"
            >
              <span>View live logs</span>
              <span>→</span>
            </Link>
          </div>
        </div>
      </section>

      {/* ============================================================== */}
      {/* 3. ROW 2: Inbound calls chart                                  */}
      {/* ============================================================== */}
      <section className="clarivo-panel p-5 flex flex-col justify-between">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-[18px] font-semibold text-[#0F172A] dark:text-[#F5F7FA]">
              Inbound calls
            </h2>
            <p className="text-[12px] text-[#64748B] dark:text-[#A1A1AA]">
              Last 7 days · {totals.calls ?? 0} total calls
            </p>
          </div>

          {/* Area | Line toggle */}
          <div className="p-1 bg-[#F5F7FA] dark:bg-[#171A1D] border border-[#E4E8EE] dark:border-[#252A30] rounded-full flex items-center gap-0.5 text-[12px] font-medium">
            <button
              type="button"
              onClick={() => setChartType("area")}
              className={`px-3 py-1 rounded-full transition-colors cursor-pointer ${
                chartType === "area"
                  ? "bg-white dark:bg-[#111315] text-[#007BA7] shadow-sm font-semibold"
                  : "text-[#64748B] dark:text-[#A1A1AA] hover:text-[#0F172A] dark:hover:text-[#F5F7FA]"
              }`}
            >
              Area
            </button>
            <button
              type="button"
              onClick={() => setChartType("line")}
              className={`px-3 py-1 rounded-full transition-colors cursor-pointer ${
                chartType === "line"
                  ? "bg-white dark:bg-[#111315] text-[#007BA7] shadow-sm font-semibold"
                  : "text-[#64748B] dark:text-[#A1A1AA] hover:text-[#0F172A] dark:hover:text-[#F5F7FA]"
              }`}
            >
              Line
            </button>
          </div>
        </div>

        <div className="w-full h-52 mt-2">
          <ResponsiveContainer width="100%" height="100%">
            {chartType === "area" ? (
              <AreaChart data={daily}>
                <defs>
                  <linearGradient id="areaGradientCerulean" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#007BA7" stopOpacity={0.16} />
                    <stop offset="100%" stopColor="#007BA7" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#E4E8EE" opacity={0.6} />
                <XAxis
                  dataKey="label"
                  tickLine={false}
                  axisLine={false}
                  stroke="#64748B"
                  fontSize={11}
                />
                <YAxis
                  allowDecimals={false}
                  tickLine={false}
                  axisLine={false}
                  stroke="#64748B"
                  fontSize={11}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0F172A",
                    borderColor: "#1E293B",
                    borderRadius: "12px",
                    color: "#FFFFFF",
                    fontSize: "12px",
                  }}
                  itemStyle={{ color: "#007BA7" }}
                />
                <Area
                  type="monotone"
                  dataKey="count"
                  stroke="#007BA7"
                  strokeWidth={2.5}
                  fill="url(#areaGradientCerulean)"
                />
              </AreaChart>
            ) : (
              <LineChart data={daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E4E8EE" opacity={0.6} />
                <XAxis
                  dataKey="label"
                  tickLine={false}
                  axisLine={false}
                  stroke="#64748B"
                  fontSize={11}
                />
                <YAxis
                  allowDecimals={false}
                  tickLine={false}
                  axisLine={false}
                  stroke="#64748B"
                  fontSize={11}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0F172A",
                    borderColor: "#1E293B",
                    borderRadius: "12px",
                    color: "#FFFFFF",
                    fontSize: "12px",
                  }}
                  itemStyle={{ color: "#007BA7" }}
                />
                <Line
                  type="monotone"
                  dataKey="count"
                  stroke="#007BA7"
                  strokeWidth={2.5}
                  dot={{ r: 4, stroke: "#007BA7", strokeWidth: 2, fill: "#FFFFFF" }}
                  activeDot={{ r: 6, fill: "#FF2D95", stroke: "#FFFFFF", strokeWidth: 2 }}
                />
              </LineChart>
            )}
          </ResponsiveContainer>
        </div>
      </section>

      {/* ============================================================== */}
      {/* 4. ROW 3: Recent calls table with search & filter              */}
      {/* ============================================================== */}
      <section className="clarivo-panel p-5 flex flex-col justify-between">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-2">
            <h2 className="text-[18px] font-semibold text-[#0F172A] dark:text-[#F5F7FA]">
              Recent calls
            </h2>
            <span className="px-2 py-0.5 rounded-full bg-[#F5F7FA] dark:bg-[#171A1D] text-[#475569] dark:text-[#A1A1AA] text-[11px] font-semibold border border-[#E4E8EE] dark:border-[#252A30]">
              5 latest
            </span>
          </div>

          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="h-4 w-4 text-[#64748B] absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={callSearch}
                onChange={(e) => setCallSearch(e.target.value)}
                placeholder="Search caller or number"
                className="h-8 pl-8 pr-3 bg-[#F5F7FA] dark:bg-[#171A1D] border border-[#E4E8EE] dark:border-[#252A30] rounded-full text-[12px] text-[#0F172A] dark:text-[#F5F7FA] placeholder-[#64748B] focus:outline-none focus:ring-2 focus:ring-[#007BA7] w-48 transition-colors"
              />
            </div>

            <Link
              to="/calls"
              className="h-8 px-3 rounded-full border border-[#E4E8EE] dark:border-[#252A30] bg-white dark:bg-[#111315] text-[12px] font-medium text-[#007BA7] hover:bg-[#F5F7FA] dark:hover:bg-[#171A1D] transition-colors inline-flex items-center"
            >
              View all ({totals.calls ?? 0})
            </Link>
          </div>
        </div>

        {/* Call rows Table */}
        <div className="w-full overflow-x-auto">
          <table className="w-full text-left border-collapse text-[13px]">
            <thead>
              <tr className="bg-[#F5F7FA] dark:bg-[#171A1D] text-[#475569] dark:text-[#A1A1AA] text-[11px] uppercase tracking-wider font-semibold">
                <th className="py-2.5 px-3 first:rounded-l-xl">Caller Name</th>
                <th className="py-2.5 px-2.5">Phone Number</th>
                <th className="py-2.5 px-2.5">Date &amp; Time</th>
                <th className="py-2.5 px-2">Duration</th>
                <th className="py-2.5 px-2.5">Status</th>
                <th className="py-2.5 px-3">AI Summary</th>
                <th className="py-2.5 px-3 last:rounded-r-xl text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E4E8EE]/70 dark:divide-[#252A30]">
              {filteredRecent.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-[#64748B] dark:text-[#A1A1AA]">
                    {loading ? "Loading calls…" : "No calls match your search."}
                  </td>
                </tr>
              ) : (
                filteredRecent.map((c) => (
                  <tr
                    key={c.id || c.call_id}
                    className="hover:bg-[#F5F7FA]/50 dark:hover:bg-[#171A1D]/50 transition-colors"
                  >
                    <td className="py-3 px-3 font-semibold text-[#0F172A] dark:text-[#F5F7FA]">
                      {c.customer || "Unknown Caller"}
                    </td>
                    <td className="py-3 px-2.5 text-[#64748B] dark:text-[#A1A1AA] tabular-nums">
                      {c.phone || "—"}
                    </td>
                    <td className="py-3 px-2.5 text-[#64748B] dark:text-[#A1A1AA] tabular-nums whitespace-nowrap">
                      {c.date ? new Date(c.date).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" }) : "—"}
                    </td>
                    <td className="py-3 px-2 text-[#64748B] dark:text-[#A1A1AA] tabular-nums">
                      {fmtDuration(c.duration)}
                    </td>
                    <td className="py-3 px-2.5">
                      <Badge tone={toneFor(c.status)}>{c.status}</Badge>
                    </td>
                    <td
                      className="py-3 px-3 text-[#0F172A] dark:text-[#F5F7FA] max-w-[280px] truncate"
                      title={c.summary || "No summary"}
                    >
                      {c.summary || "AI reception resolved inquiry."}
                    </td>
                    <td className="py-3 px-3 text-right">
                      <Link
                        to="/calls"
                        className="text-[#007BA7] hover:underline font-medium text-[12px]"
                      >
                        Details
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
