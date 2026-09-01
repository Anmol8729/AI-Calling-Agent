/**
 * VoxPilot AI — Public Landing Page
 *
 * Sections:
 *  1. Nav
 *  2. Hero  (headline + CTA)
 *  3. "Hear it for yourself"  ← tap-to-call card + callback form
 *  4. Features
 *  5. Footer
 *
 * Palette: gray-950 / white / glass  (matches the dashboard aesthetic).
 * Animations: CSS keyframes already in styles.css (.wave-bar, @keyframes wave).
 * No new libraries — lucide-react icons, existing axios client, plain state.
 */

import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Phone,
  PhoneCall,
  Bot,
  CalendarCheck,
  Users,
  Zap,
  ArrowRight,
  CheckCircle2,
  ChevronRight,
} from "lucide-react";
import api from "../lib/api";

// ─── tiny helpers ────────────────────────────────────────────────────────────

function formatPhone(raw) {
  if (!raw) return "";
  // Indian 10-digit: +91 XXXXX XXXXX
  const digits = raw.replace(/\D/g, "");
  if (digits.length === 12 && digits.startsWith("91")) {
    const local = digits.slice(2);
    return `+91 ${local.slice(0, 5)} ${local.slice(5)}`;
  }
  if (digits.length === 10) {
    return `+91 ${digits.slice(0, 5)} ${digits.slice(5)}`;
  }
  return raw; // return as-is for other formats
}

function extractError(err) {
  const d = err?.response?.data;
  if (d?.message) return d.message;
  if (d?.detail) return Array.isArray(d.detail) ? d.detail.map(x => x.msg).join(", ") : d.detail;
  return "Could not reach the server. Please try again.";
}

// ─── scroll-reveal hook ──────────────────────────────────────────────────────

function useReveal() {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setVisible(true); obs.disconnect(); } },
      { threshold: 0.12 }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
  return [ref, visible];
}

// ─── WaveAnimation ───────────────────────────────────────────────────────────

function WaveAnimation({ bars = 5, color = "#111827" }) {
  return (
    <div className="flex items-end gap-1" aria-hidden="true">
      {Array.from({ length: bars }).map((_, i) => (
        <div
          key={i}
          className="wave-bar"
          style={{
            background: color,
            animationDelay: `${i * 120}ms`,
          }}
        />
      ))}
    </div>
  );
}

// ─── TapToCallCard ───────────────────────────────────────────────────────────

function TapToCallCard({ phone }) {
  const [ref, visible] = useReveal();
  const formatted = formatPhone(phone);

  return (
    <div
      ref={ref}
      className={`glass-card rounded-3xl p-8 flex flex-col items-center text-center gap-6 transition-all duration-700 ${
        visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-8"
      }`}
    >
      {/* pulsing ring + phone icon */}
      <div className="relative flex items-center justify-center">
        <span className="absolute inline-flex h-20 w-20 rounded-full bg-emerald-500/20 animate-ping" />
        <div className="relative grid h-16 w-16 place-items-center rounded-full bg-emerald-500 shadow-lg shadow-emerald-500/30">
          <PhoneCall className="h-7 w-7 text-white" />
        </div>
      </div>

      <div>
        <p className="text-sm font-semibold uppercase tracking-widest text-gray-500 mb-2">
          Live demo line
        </p>
        {phone ? (
          <a
            href={`tel:${phone}`}
            className="text-3xl sm:text-4xl font-bold text-gray-950 hover:text-emerald-600 transition-colors"
          >
            {formatted}
          </a>
        ) : (
          <p className="text-2xl font-semibold text-gray-400">Coming soon</p>
        )}
      </div>

      <WaveAnimation bars={6} color="#10b981" />

      <p className="text-gray-600 text-sm max-w-xs leading-relaxed">
        {phone
          ? "Call now and talk to the AI receptionist — it's answering live, in Hindi, right now."
          : "We're setting up the demo line. Check back soon or request a callback below."}
      </p>

      {phone && (
        <a
          href={`tel:${phone}`}
          className="inline-flex items-center gap-2 rounded-2xl bg-brand-500 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-gray-950/20 hover:bg-gray-800 transition-colors"
        >
          <Phone className="h-4 w-4" /> Tap to call
        </a>
      )}
    </div>
  );
}

// ─── CallbackForm ─────────────────────────────────────────────────────────────

function CallbackForm() {
  const [ref, visible] = useReveal();
  const [form, setForm] = useState({ name: "", phone: "", note: "" });
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null); // { type: "success"|"error", text }

  const set = (k) => (e) => setForm((p) => ({ ...p, [k]: e.target.value }));

  const submit = async () => {
    setResult(null);
    if (!form.name.trim() || !form.phone.trim()) {
      setResult({ type: "error", text: "Name and phone number are required." });
      return;
    }
    setSubmitting(true);
    try {
      const res = await api.post("/public/demo-request", {
        name: form.name.trim(),
        phone: form.phone.trim(),
        note: form.note.trim() || undefined,
      });
      if (res.data?.success) {
        setResult({ type: "success", text: "Got it! We'll call you back shortly." });
        setForm({ name: "", phone: "", note: "" });
      } else {
        setResult({ type: "error", text: res.data?.message || "Something went wrong." });
      }
    } catch (err) {
      setResult({ type: "error", text: extractError(err) });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      ref={ref}
      className={`glass-card rounded-3xl p-8 flex flex-col gap-5 transition-all duration-700 delay-150 ${
        visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-8"
      }`}
    >
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-1">
          Prefer we call you?
        </p>
        <h3 className="text-xl font-semibold text-gray-950">Request a callback</h3>
        <p className="mt-1 text-sm text-gray-500">
          Leave your number and we'll have the AI agent call you — or a human from our team if you'd like a walkthrough.
        </p>
      </div>

      {result && (
        <div
          className={`rounded-2xl border p-3 text-sm ${
            result.type === "success"
              ? "border-emerald-100 bg-emerald-50 text-emerald-800"
              : "border-red-100 bg-red-50 text-red-800"
          }`}
        >
          {result.text}
        </div>
      )}

      <div className="space-y-3">
        <LandingField
          label="Your name *"
          placeholder="Dr. Ravi Sharma"
          value={form.name}
          onChange={set("name")}
        />
        <LandingField
          label="Phone number *"
          placeholder="+91 98765 43210"
          type="tel"
          value={form.phone}
          onChange={set("phone")}
        />
        <LandingField
          label="Anything specific? (optional)"
          placeholder="I run a dental clinic with ~40 patients/day"
          value={form.note}
          onChange={set("note")}
        />
      </div>

      <button
        onClick={submit}
        disabled={submitting}
        className="inline-flex items-center justify-center gap-2 rounded-xl bg-brand-500 px-5 py-3 text-sm font-semibold text-white shadow-sm hover:bg-gray-800 transition-colors disabled:opacity-50 disabled:pointer-events-none"
      >
        {submitting ? "Sending…" : (
          <><ChevronRight className="h-4 w-4" /> Request callback</>
        )}
      </button>

      <p className="text-xs text-gray-400">
        This is a callback request only — no auto-dialling, no spam.
      </p>
    </div>
  );
}

function LandingField({ label, ...props }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">{label}</span>
      <input
        className="w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-brand-500 focus:ring-4 focus:ring-gray-950/8 transition"
        {...props}
      />
    </label>
  );
}

// ─── Feature card ─────────────────────────────────────────────────────────────

const FEATURES = [
  {
    icon: Bot,
    title: "Speaks fluent Hindi",
    body: "Understands callers naturally, answers in Hindi, and switches context mid-conversation without getting confused.",
  },
  {
    icon: CalendarCheck,
    title: "Books appointments live",
    body: "Checks real availability, assigns the next token or picks a time slot, and saves the booking directly to your dashboard.",
  },
  {
    icon: Users,
    title: "Knows your patients",
    body: "Recognises returning callers by phone number — greets them by name and surfaces their last visit in seconds.",
  },
  {
    icon: Zap,
    title: "Zero missed calls",
    body: "Answers instantly, 24/7. No hold music. No voicemail. Every caller gets a response even at 2 am.",
  },
];

function FeatureCard({ icon: Icon, title, body, delay = 0 }) {
  const [ref, visible] = useReveal();
  return (
    <div
      ref={ref}
      className={`glass-card rounded-3xl p-6 flex flex-col gap-4 transition-all duration-700 ${
        visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-8"
      }`}
      style={{ transitionDelay: `${delay}ms` }}
    >
      <div className="grid h-10 w-10 place-items-center rounded-2xl bg-brand-500 text-white shadow-lg shadow-gray-950/20">
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <h3 className="font-semibold text-gray-950">{title}</h3>
        <p className="mt-1 text-sm text-gray-500 leading-relaxed">{body}</p>
      </div>
    </div>
  );
}

// ─── Main Landing page ────────────────────────────────────────────────────────

export default function Landing() {
  const [demoPhone, setDemoPhone] = useState("");

  useEffect(() => {
    api.get("/public/demo-info")
      .then((r) => { if (r.data?.success) setDemoPhone(r.data.data?.demo_phone_number || ""); })
      .catch(() => {});
  }, []);

  return (
    <div className="min-h-screen bg-[#f6f7f9] text-gray-950" style={{ fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif" }}>

      {/* ── Nav ── */}
      <header className="sticky top-0 z-50 border-b border-gray-100 bg-white/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="grid h-9 w-9 place-items-center rounded-xl bg-brand-500 text-white shadow-lg shadow-gray-950/20">
              <Bot className="h-5 w-5" />
            </div>
            <span className="text-sm font-semibold text-gray-950">VoxPilot AI</span>
          </div>
          <nav className="hidden sm:flex items-center gap-6 text-sm text-gray-500">
            <a href="#demo" className="hover:text-gray-950 transition-colors">Demo</a>
            <a href="#features" className="hover:text-gray-950 transition-colors">Features</a>
          </nav>
          <div className="flex items-center gap-3">
            <Link
              to="/login"
              className="text-sm font-medium text-gray-600 hover:text-gray-950 transition-colors"
            >
              Sign in
            </Link>
            <Link
              to="/register"
              className="inline-flex items-center gap-1.5 rounded-xl bg-brand-500 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-gray-800 transition-colors"
            >
              Get started <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      </header>

      {/* ── Hero ── */}
      <section className="relative overflow-hidden py-24 sm:py-32">
        {/* soft gradient blob */}
        <div className="pointer-events-none absolute -top-40 left-1/2 -translate-x-1/2 h-[600px] w-[900px] rounded-full bg-gradient-to-br from-emerald-100/60 via-gray-100/0 to-blue-100/40 blur-3xl" />

        <div className="relative mx-auto max-w-4xl px-6 text-center">
          <span className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-semibold text-gray-600 shadow-sm mb-6">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
            Live on inbound calls right now
          </span>

          <h1 className="text-4xl sm:text-6xl font-bold tracking-tight text-gray-950 leading-tight">
            Your clinic's AI receptionist.{" "}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-600 to-teal-500">
              Speaks Hindi.
            </span>{" "}
            Never misses a call.
          </h1>

          <p className="mt-6 text-lg text-gray-500 max-w-2xl mx-auto leading-relaxed">
            VoxPilot answers every inbound call, books appointments in real time, and saves patient details to your dashboard — so you can focus on the people in front of you.
          </p>

          <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
            <a
              href="#demo"
              className="inline-flex items-center gap-2 rounded-2xl bg-brand-500 px-7 py-3.5 text-sm font-semibold text-white shadow-lg shadow-gray-950/20 hover:bg-gray-800 transition-colors"
            >
              <PhoneCall className="h-4 w-4" /> Try it now — call for free
            </a>
            <Link
              to="/register"
              className="inline-flex items-center gap-2 rounded-2xl border border-gray-200 bg-white px-7 py-3.5 text-sm font-semibold text-gray-950 shadow-sm hover:bg-gray-50 transition-colors"
            >
              Start free trial <ArrowRight className="h-4 w-4" />
            </Link>
          </div>

          {/* trust row */}
          <div className="mt-12 flex flex-wrap items-center justify-center gap-5 text-xs text-gray-400 font-medium">
            {["No missed calls", "Real appointments booked", "Hindi-first voice AI", "Multi-clinic ready"].map((t) => (
              <span key={t} className="flex items-center gap-1.5">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> {t}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ── "Hear it for yourself" ── */}
      <section id="demo" className="py-20 sm:py-28">
        <div className="mx-auto max-w-6xl px-6">
          <div className="text-center mb-14">
            <p className="text-xs font-semibold uppercase tracking-widest text-emerald-600 mb-3">Live demo</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-gray-950">Hear it for yourself</h2>
            <p className="mt-3 text-gray-500 max-w-xl mx-auto text-sm leading-relaxed">
              Our demo line is connected to the real AI agent right now. Call it and book a test appointment — or request a callback and we'll come to you.
            </p>
          </div>

          <div className="grid gap-6 lg:grid-cols-2 max-w-4xl mx-auto">
            <TapToCallCard phone={demoPhone} />
            <CallbackForm />
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section id="features" className="py-20 sm:py-28 bg-white/60">
        <div className="mx-auto max-w-6xl px-6">
          <div className="text-center mb-14">
            <p className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-3">What it does</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-gray-950">Built for Indian clinics</h2>
            <p className="mt-3 text-gray-500 max-w-xl mx-auto text-sm leading-relaxed">
              Every feature was designed around real inbound call patterns — so it works on day one, not after months of training.
            </p>
          </div>

          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map((f, i) => (
              <FeatureCard key={f.title} {...f} delay={i * 80} />
            ))}
          </div>
        </div>
      </section>

      {/* ── Bottom CTA ── */}
      <section className="py-24">
        <div className="mx-auto max-w-2xl px-6 text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-gray-950">
            Ready to stop missing calls?
          </h2>
          <p className="mt-4 text-gray-500 text-sm">
            Set up takes under 10 minutes. No hardware. No SIM. Just connect your number and go.
          </p>
          <Link
            to="/register"
            className="mt-8 inline-flex items-center gap-2 rounded-2xl bg-brand-500 px-8 py-4 text-sm font-semibold text-white shadow-xl shadow-gray-950/20 hover:bg-gray-800 transition-colors"
          >
            Create your free account <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t border-gray-100 bg-white py-10">
        <div className="mx-auto max-w-6xl px-6 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-gray-400">
          <div className="flex items-center gap-2">
            <div className="grid h-7 w-7 place-items-center rounded-lg bg-brand-500 text-white">
              <Bot className="h-4 w-4" />
            </div>
            <span className="font-semibold text-gray-950">VoxPilot AI</span>
          </div>
          <p>© {new Date().getFullYear()} VoxPilot AI. All rights reserved.</p>
          <div className="flex gap-5">
            <Link to="/login" className="hover:text-gray-950 transition-colors">Sign in</Link>
            <Link to="/register" className="hover:text-gray-950 transition-colors">Get started</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
