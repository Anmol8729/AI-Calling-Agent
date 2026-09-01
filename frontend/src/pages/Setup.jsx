import { useCallback, useEffect, useState } from "react";
import {
  Save, Building2, Sparkles, MessageSquareCode, Languages, BookOpen,
  Plus, PhoneCall, CalendarPlus, Mic2,
} from "lucide-react";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { Section, Label, Hint, Field } from "../components/ui/Form";
import WhatsAppConfig from "../components/WhatsAppConfig";
import Modal from "../components/Modal";
import DataTable from "../components/DataTable";
import { INDUSTRIES } from "../lib/industries";
import { useClinicStore } from "../store/clinicStore";
import api from "../lib/api";

const LANGUAGES = [
  { code: "hi", label: "Hindi" }, { code: "en", label: "English" }, { code: "es", label: "Spanish" },
  { code: "fr", label: "French" }, { code: "de", label: "German" }, { code: "pt", label: "Portuguese" },
  { code: "it", label: "Italian" }, { code: "nl", label: "Dutch" }, { code: "ja", label: "Japanese" },
  { code: "ko", label: "Korean" }, { code: "zh", label: "Chinese" }, { code: "ru", label: "Russian" },
];

// MiniMax speech-02 system voices shown in the dropdown. Users can also pick
// "Custom / cloned voice" and paste a MiniMax cloned voice_id.
const VOICES = [
  { id: "Calm_Woman", label: "Calm Woman (default)" },
  { id: "Wise_Woman", label: "Wise Woman" },
  { id: "Friendly_Person", label: "Friendly Person" },
  { id: "Lovely_Girl", label: "Lovely Girl" },
  { id: "Sweet_Girl_2", label: "Sweet Girl" },
  { id: "Exuberant_Girl", label: "Exuberant Girl" },
  { id: "Patient_Man", label: "Patient Man" },
  { id: "Deep_Voice_Man", label: "Deep Voice Man" },
  { id: "Casual_Guy", label: "Casual Guy" },
  { id: "Elegant_Man", label: "Elegant Man" },
];

const KB_PLACEHOLDER = `Describe your business so the assistant can answer callers accurately. For example:

• What you offer (services / products)
• Opening hours and days
• Address and directions
• Pricing or fees
• Booking and cancellation policy
• Common questions callers ask`;

function extractError(err) {
  const d = err?.response?.data;
  if (d?.message) return d.message;
  if (typeof d?.error === "string" && d.error) return d.error;
  if (d?.detail) return Array.isArray(d.detail) ? d.detail.map((x) => x.msg).join(", ") : d.detail;
  return "Could not reach the server.";
}

export default function Setup() {
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [bookingMode, setBookingMode] = useState("time");
  const [notifyEmail, setNotifyEmail] = useState("");
  const [language, setLanguage] = useState("hi");
  const [greeting, setGreeting] = useState("");
  const [behavior, setBehavior] = useState("");
  const [voice, setVoice] = useState("");
  const [voiceCustom, setVoiceCustom] = useState(false);
  const [knowledge, setKnowledge] = useState("");

  // WhatsApp config owns its own state and its own save, because its credentials are
  // verified with Meta before being stored. It only needs the fetched settings.
  const [settings, setSettings] = useState(null);

  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState(null); // { type, text }

  useEffect(() => {
    api.get("/clinics/settings")
      .then((res) => {
        if (res.data?.success) {
          const d = res.data.data;
          useClinicStore.getState().setClinic(d);
          setSettings(d);
          setName(d.name || "");
          setIndustry(d.industry || "");
          setBookingMode(d.booking_mode || "time");
          setNotifyEmail(d.notify_email || "");
          setLanguage(d.language || "hi");
          setGreeting(d.initial_greeting || "");
          setBehavior(d.system_prompt || "");
          setVoice(d.voice || "");
          setVoiceCustom(!!d.voice && !VOICES.some((v) => v.id === d.voice));
          setKnowledge(d.knowledge_base || "");
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));

    api.get("/industries")
      .then((res) => { if (res.data?.success && Array.isArray(res.data.data)) setTemplates(res.data.data); })
      .catch(() => {});
  }, []);

  const applyTemplate = () => {
    const tmpl = templates.find((t) => t.key === industry);
    if (!tmpl) {
      setStatus({ type: "error", text: "Pick an industry first, then apply its template." });
      return;
    }
    if ((behavior.trim() || greeting.trim()) && !window.confirm(
      `Replace the current greeting and behaviour with the "${tmpl.label}" starter template? Your other settings are untouched.`
    )) return;
    setBehavior(tmpl.system_prompt || "");
    setGreeting(tmpl.initial_greeting || "");
    setStatus({ type: "success", text: `Loaded the ${tmpl.label} template. Review it and click Save.` });
  };

  const handleSave = () => {
    setSaving(true);
    setStatus(null);
    api.put("/clinics/settings", {
      name,
      industry,
      booking_mode: bookingMode,
      notify_email: notifyEmail,
      language,
      initial_greeting: greeting,
      system_prompt: behavior,
      voice,
      knowledge_base: knowledge,
      // WhatsApp fields are intentionally absent: they are saved by WhatsAppConfig
      // only after Meta accepts them. Sending them here too would let this Save
      // overwrite verified credentials with whatever the form last held, and would
      // clear the verified flag on every unrelated edit.
    })
      .then((res) => {
        if (res.data?.success) {
          if (res.data.data) {
            useClinicStore.getState().setClinic(res.data.data);
            setSettings(res.data.data);
          }
          setStatus({ type: "success", text: "Saved. Changes apply on the next call." });
        } else {
          setStatus({ type: "error", text: res.data?.message || "Failed to save." });
        }
      })
      .catch(() => setStatus({ type: "error", text: "Failed to connect to the server." }))
      .finally(() => setSaving(false));
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-gray-950">Agent Setup</h1>
        <p className="mt-2 text-sm text-gray-500">Everything your AI receptionist needs: your business info, how it talks, and your phone number.</p>
      </div>

      {status && (
        <div className={`rounded-2xl border p-4 text-sm ${status.type === "success" ? "border-emerald-100 bg-emerald-50 text-emerald-800" : "border-red-100 bg-red-50 text-red-800"}`}>
          {status.text}
        </div>
      )}

      {/* Industry */}
      <Section icon={Building2} title="Industry">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1">
            <Label>Your industry</Label>
            <select
              className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-sm focus:border-brand-500 focus:outline-none"
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
            >
              <option value="">Not set</option>
              {INDUSTRIES.map((opt) => <option key={opt.key} value={opt.key}>{opt.label}</option>)}
            </select>
            <Hint>Applying a template fills in a ready-made greeting and behaviour for your industry.</Hint>
          </div>
          <Button variant="secondary" onClick={applyTemplate} disabled={!industry}>
            <Sparkles className="h-4 w-4" /> Apply template
          </Button>
        </div>
      </Section>

      {/* Business details */}
      <Section icon={Building2} title="Business details">
        <Field label="Business name" value={name} onChange={setName} placeholder="Your business name" />
        <Field label="Booking alert email" value={notifyEmail} onChange={setNotifyEmail} placeholder="you@business.com" hint="Where we email you when the assistant books someone. Blank uses your account email." />
      </Section>

      {/* Booking mode */}
      <Section icon={CalendarPlus} title="Booking">
        <Label>How you book appointments</Label>
        <select
          className="mt-1 w-full max-w-sm rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-sm focus:border-brand-500 focus:outline-none"
          value={bookingMode}
          onChange={(e) => setBookingMode(e.target.value)}
        >
          <option value="time">Time slots — fixed appointment times</option>
          <option value="token">Token queue — daily number, no fixed time</option>
        </select>
        <Hint>Token queue suits businesses that serve people by a daily number instead of exact times — callers are told their token number. Your Appointments page and the assistant adapt automatically.</Hint>
      </Section>

      {/* Language */}
      <Section icon={Languages} title="Language">
        <Label>Language your callers speak</Label>
        <select
          className="mt-1 w-full max-w-sm rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-sm focus:border-brand-500 focus:outline-none"
          value={language || "hi"}
          onChange={(e) => setLanguage(e.target.value)}
        >
          {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
        </select>
        <Hint>Drives what the assistant understands and the voice it speaks in.</Hint>
      </Section>

      {/* Voice */}
      <Section icon={Mic2} title="Voice">
        <Label>Assistant voice</Label>
        <select
          className="mt-1 w-full max-w-sm rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-sm focus:border-brand-500 focus:outline-none"
          value={voiceCustom ? "__custom__" : (voice || "Calm_Woman")}
          onChange={(e) => {
            if (e.target.value === "__custom__") { setVoiceCustom(true); setVoice(""); }
            else { setVoiceCustom(false); setVoice(e.target.value); }
          }}
        >
          {VOICES.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
          <option value="__custom__">Custom / cloned voice…</option>
        </select>
        {voiceCustom && (
          <input
            type="text"
            className="mt-2 w-full max-w-sm rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-brand-500 focus:outline-none"
            value={voice}
            onChange={(e) => setVoice(e.target.value)}
            placeholder="Paste your cloned voice ID"
          />
        )}
        <Hint>Pick a built-in voice, or use a custom cloned voice. Contact us to have a voice cloned for your business.</Hint>
      </Section>

      {/* Knowledge base */}
      <Section icon={BookOpen} title="What your assistant knows">
        <Label>Business information</Label>
        <textarea
          rows={12}
          className="mt-1 w-full rounded-2xl border border-gray-200 p-4 text-sm leading-6 focus:border-brand-500 focus:outline-none"
          placeholder={KB_PLACEHOLDER}
          value={knowledge}
          onChange={(e) => setKnowledge(e.target.value)}
          disabled={loading}
        />
        <Hint>Write it like you'd brief a new receptionist. Plain text and bullet points work great.</Hint>
      </Section>

      {/* Behaviour */}
      <Section icon={MessageSquareCode} title="How your assistant behaves">
        <Field label="Opening greeting" value={greeting} onChange={setGreeting} placeholder="Greet the caller warmly and ask how you can help them today." hint="The first thing your assistant says when it answers." />
        <div>
          <Label>How your assistant should behave</Label>
          <textarea
            rows={5}
            className="mt-1 w-full rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-brand-500 focus:outline-none"
            value={behavior}
            onChange={(e) => setBehavior(e.target.value)}
            placeholder="You are a warm, professional receptionist for a business. Book appointments and answer questions using the business information..."
          />
          <Hint>Describe how it should talk and what to do on a call. The industry template fills this in for you.</Hint>
        </div>
      </Section>

      {/* WhatsApp — verifies with Meta and saves itself, so it sits outside the
          page-wide Save below. */}
      <WhatsAppConfig
        settings={settings}
        disabled={loading}
        onSaved={(d) => {
          useClinicStore.getState().setClinic(d);
          setSettings(d);
        }}
      />

      {/* The "Advanced > AI model" field was removed: nothing ever read
          tenants.llm_model. The agent builds its LLM chain from AGENT_LLM_ORDER and
          the per-provider env vars, so a model typed here was stored and ignored
          while the page still answered "Saved. Changes apply on the next call." */}

      <div className="flex justify-end">
        <Button onClick={handleSave} disabled={saving || loading}>
          <Save className="h-4 w-4" /> {saving ? "Saving..." : "Save"}
        </Button>
      </div>

      {/* Phone numbers (separate CRUD) */}
      <PhoneNumbersSection />
    </div>
  );
}

function PhoneNumbersSection() {
  const [numbers, setNumbers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [banner, setBanner] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ number: "", label: "" });
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  // One-click provisioning: whether the platform can hand out a ready number.
  const [provisionInfo, setProvisionInfo] = useState({ enabled: false, available: 0 });
  const [provisioning, setProvisioning] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/phone-numbers/");
      setNumbers(res.data?.success ? res.data.data || [] : []);
    } catch {
      setNumbers([]);
    } finally {
      setLoading(false);
    }
    try {
      const info = await api.get("/phone-numbers/provision-info");
      if (info.data?.success) setProvisionInfo(info.data.data || { enabled: false, available: 0 });
    } catch {
      setProvisionInfo({ enabled: false, available: 0 });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const connect = async () => {
    setFormError("");
    if (!form.number.trim()) { setFormError("Enter the phone number you want to connect."); return; }
    setSubmitting(true);
    try {
      const res = await api.post("/phone-numbers/", { number: form.number.trim(), label: form.label.trim() || null });
      if (res.data?.success) {
        setOpen(false);
        setForm({ number: "", label: "" });
        setBanner({ type: "success", text: "Number connected. Point its provider webhook at your Clarivo inbound URL to receive calls." });
        load();
      } else {
        setFormError(res.data?.message || "Could not connect the number.");
      }
    } catch (err) {
      setFormError(extractError(err));
    } finally {
      setSubmitting(false);
    }
  };

  // Claim a ready-to-use number: the backend picks a free one, routes it to the
  // voice agent, and links it to this business — no provider setup needed.
  const getNumber = async () => {
    setBanner(null);
    setProvisioning(true);
    try {
      const res = await api.post("/phone-numbers/provision", {});
      if (res.data?.success) {
        setBanner({ type: "success", text: res.data.message || "Your number is ready to receive calls." });
        load();
      } else {
        setBanner({ type: "error", text: res.data?.message || "Could not get a number right now." });
      }
    } catch (err) {
      setBanner({ type: "error", text: extractError(err) });
    } finally {
      setProvisioning(false);
    }
  };

  const openConnect = () => {
    setFormError("");
    setForm({ number: "", label: "" });
    setOpen(true);
  };

  const toggleStatus = async (row) => {
    setBanner(null);
    setBusyId(row.id);
    const next = row.status === "active" ? "inactive" : "active";
    try {
      const res = await api.put(`/phone-numbers/${row.id}`, { status: next });
      if (res.data?.success) setNumbers((prev) => prev.map((n) => (n.id === row.id ? { ...n, status: next } : n)));
      else setBanner({ type: "error", text: res.data?.message || "Could not update the number." });
    } catch (err) {
      setBanner({ type: "error", text: extractError(err) });
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (row) => {
    setBanner(null);
    setBusyId(row.id);
    try {
      const res = await api.delete(`/phone-numbers/${row.id}`);
      if (res.data?.success) { setBanner({ type: "success", text: `Removed ${row.number}.` }); load(); }
      else setBanner({ type: "error", text: res.data?.message || "Could not remove the number." });
    } catch (err) {
      setBanner({ type: "error", text: extractError(err) });
    } finally {
      setBusyId(null);
    }
  };

  const columns = [
    { key: "number", header: "Phone number" },
    { key: "label", header: "Label", render: (row) => row.label || "—" },
    { key: "status", header: "Status", render: (row) => <Badge tone={row.status === "active" ? "success" : "neutral"}>{row.status}</Badge> },
    {
      key: "actions",
      header: "Actions",
      render: (row) => (
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" disabled={busyId === row.id} onClick={() => toggleStatus(row)}>
            {row.status === "active" ? "Deactivate" : "Activate"}
          </Button>
          <Button variant="danger" size="sm" disabled={busyId === row.id} onClick={() => remove(row)}>Remove</Button>
        </div>
      ),
    },
  ];

  return (
    <Section icon={PhoneCall} title="Your phone numbers" action={
      <div className="flex flex-wrap gap-2">
        {provisionInfo.enabled && (
          <Button onClick={getNumber} disabled={provisioning}>
            {provisioning ? "Setting up..." : "Get a number"}
          </Button>
        )}
        {provisionInfo.enabled ? (
          <Button variant="secondary" onClick={openConnect}>
            <Plus className="h-4 w-4" /> Connect number
          </Button>
        ) : (
          <Button onClick={openConnect}>
            <Plus className="h-4 w-4" /> Connect number
          </Button>
        )}
      </div>
    }>
      <p className="text-sm text-gray-500">
        {provisionInfo.enabled
          ? "Get a number in one click and it's instantly ready to take calls — no provider setup. Or connect a number you already own."
          : "Connect a number you own with your telephony provider. Calls to an active number are answered by your assistant."}
      </p>

      {banner && (
        <div className={`flex items-start justify-between gap-3 rounded-2xl border p-4 text-sm ${banner.type === "success" ? "border-emerald-100 bg-emerald-50 text-emerald-800" : "border-red-100 bg-red-50 text-red-800"}`}>
          <span>{banner.text}</span>
          <button className="text-xs font-medium opacity-70 hover:opacity-100" onClick={() => setBanner(null)}>Dismiss</button>
        </div>
      )}

      <DataTable
        columns={columns}
        rows={numbers}
        loading={loading}
        emptyTitle="No numbers connected yet"
        emptyDescription={
          provisionInfo.enabled
            ? "Your assistant needs a phone number to answer calls. Get one in a click, or connect a number you already own."
            : "Your assistant needs a phone number to answer calls. Connect a number you own with your telephony provider."
        }
        emptyIcon={PhoneCall}
        emptyAction={
          provisionInfo.enabled ? (
            <Button onClick={getNumber} disabled={provisioning}>
              {provisioning ? "Setting up..." : "Get a number"}
            </Button>
          ) : (
            <Button onClick={openConnect}>
              <Plus className="h-4 w-4" /> Connect number
            </Button>
          )
        }
      />

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Connect a phone number"
        description="Enter a number you already own with your telephony provider."
        footer={
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={connect} disabled={submitting}>{submitting ? "Connecting..." : "Connect"}</Button>
          </div>
        }
      >
        {formError && <div className="mb-4 rounded-2xl border border-red-100 bg-red-50 p-3 text-sm text-red-800">{formError}</div>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Phone number" value={form.number} onChange={(v) => setForm((f) => ({ ...f, number: v }))} placeholder="+919812345678" />
          <Field label="Label" value={form.label} onChange={(v) => setForm((f) => ({ ...f, label: v }))} placeholder="Main line" />
        </div>
        <p className="mt-4 flex items-start gap-2 text-xs text-gray-400">
          <PhoneCall className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          Use this if you already own a number with a telephony provider. We'll email you the details needed to
          point it at your assistant — or use "Get a number" for instant setup.
        </p>
      </Modal>
    </Section>
  );
}

// Section / Label / Hint / Field now live in components/ui/Form.jsx — WhatsAppConfig
// needs the same inputs, and two copies of them would drift apart.
