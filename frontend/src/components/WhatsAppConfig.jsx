import { useEffect, useState } from "react";
import { MessageCircle, Eye, EyeOff, Loader2, PlugZap } from "lucide-react";
import { Button } from "./ui/Button";
import { Badge } from "./ui/Badge";
import { Section, Label, Hint, Field } from "./ui/Form";
import { inputClass } from "../lib/inputStyles";
import api from "../lib/api";

/**
 * WhatsApp Business API configuration.
 *
 * Deliberately NOT part of the page-wide Save on Setup.jsx. Credentials are checked
 * against the Cloud API and stored in one step (POST /clinics/whatsapp/verify), for
 * two reasons:
 *
 *   1. Saving credentials that do not work is the failure this section exists to
 *      prevent. The sender never raises — it logs a warning and returns False — so a
 *      bad token produces silence, not an error the tenant would ever see.
 *   2. The page Save writes prompts, the knowledge base and voice settings. Gating
 *      all of that on a WhatsApp check would block unrelated edits.
 *
 * The access token is write-only: the API returns `whatsapp_access_token_set`, never
 * the token, so this component can show that one is stored but can never display it.
 */

// Meta requires the language of an approved template to match exactly, so these are
// template language codes, not UI locales. India-first ordering.
const TEMPLATE_LANGUAGES = [
  { code: "en_US", label: "en_US — English (US)" },
  { code: "en_GB", label: "en_GB — English (UK)" },
  { code: "en", label: "en — English" },
  { code: "hi", label: "hi — Hindi" },
  { code: "bn", label: "bn — Bengali" },
  { code: "gu", label: "gu — Gujarati" },
  { code: "kn", label: "kn — Kannada" },
  { code: "ml", label: "ml — Malayalam" },
  { code: "mr", label: "mr — Marathi" },
  { code: "pa", label: "pa — Punjabi" },
  { code: "ta", label: "ta — Tamil" },
  { code: "te", label: "te — Telugu" },
  { code: "ur", label: "ur — Urdu" },
  { code: "ar", label: "ar — Arabic" },
  { code: "es", label: "es — Spanish" },
  { code: "fr", label: "fr — French" },
  { code: "de", label: "de — German" },
  { code: "pt_BR", label: "pt_BR — Portuguese (BR)" },
  { code: "id", label: "id — Indonesian" },
  { code: "zh_CN", label: "zh_CN — Chinese (Simplified)" },
];

const META_SETUP_DOCS = "https://developers.facebook.com/docs/whatsapp/cloud-api/get-started";

// Meta's Phone Number ID is a numeric object id (~15 digits) — not the phone number.
// Pasting the phone number is the single most common mistake here, so it is worth its
// own message rather than a generic "invalid".
function validatePhoneId(raw) {
  const v = (raw || "").trim();
  if (!v) return "Phone Number ID is required.";
  if (v.startsWith("+") || v.includes(" ")) {
    return "That looks like a phone number. Use the numeric Phone Number ID from Meta instead.";
  }
  if (!/^\d+$/.test(v)) return "Phone Number ID contains only digits.";
  if (v.length < 10 || v.length > 20) return "Phone Number ID should be around 15 digits.";
  return "";
}

function extractError(err) {
  const d = err?.response?.data;
  if (d?.message) return d.message;
  if (d?.detail) return Array.isArray(d.detail) ? d.detail.map((x) => x.msg).join(", ") : d.detail;
  return "Could not reach the server.";
}

export default function WhatsAppConfig({ settings, disabled = false, onSaved }) {
  const [phoneId, setPhoneId] = useState("");
  const [token, setToken] = useState("");
  const [tokenSet, setTokenSet] = useState(false);
  const [showToken, setShowToken] = useState(false);
  const [lang, setLang] = useState("en_US");
  const [confirmTpl, setConfirmTpl] = useState("appointment_confirmation");
  const [reminderTpl, setReminderTpl] = useState("appointment_reminder");

  const [connected, setConnected] = useState(false);
  const [numberInfo, setNumberInfo] = useState(null);
  const [phoneIdError, setPhoneIdError] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null); // { type: "success" | "error", text }

  // Hydrated from the settings the parent already fetched — a second request for the
  // same document would just be a duplicate round trip.
  useEffect(() => {
    if (!settings) return;
    setPhoneId(settings.whatsapp_phone_number_id || "");
    setTokenSet(!!settings.whatsapp_access_token_set);
    setLang(settings.whatsapp_template_lang || "en_US");
    setConfirmTpl(settings.whatsapp_confirm_template || "appointment_confirmation");
    setReminderTpl(settings.whatsapp_reminder_template || "appointment_reminder");
    setConnected(!!settings.whatsapp_verified);
  }, [settings]);

  // Editing a credential invalidates the previous check, which the backend enforces
  // too. Reflecting it immediately keeps the badge from describing an older value
  // than the one on screen.
  const editPhoneId = (v) => {
    setPhoneId(v);
    if (phoneIdError) setPhoneIdError(validatePhoneId(v));
    if (connected) setConnected(false);
    setStatus(null);
  };
  const editToken = (v) => {
    setToken(v);
    if (connected) setConnected(false);
    setStatus(null);
  };

  const submit = async () => {
    const err = validatePhoneId(phoneId);
    setPhoneIdError(err);
    if (err) {
      setStatus({ type: "error", text: "Fix the highlighted field, then connect." });
      return;
    }
    if (!token.trim() && !tokenSet) {
      setStatus({ type: "error", text: "Paste your WhatsApp Cloud API access token." });
      return;
    }

    setBusy(true);
    setStatus(null);
    try {
      const res = await api.post("/clinics/whatsapp/verify", {
        whatsapp_phone_number_id: phoneId.trim(),
        // Blank re-checks the stored token; the browser never receives it to echo.
        whatsapp_access_token: token.trim(),
        whatsapp_template_lang: lang,
        whatsapp_confirm_template: confirmTpl.trim(),
        whatsapp_reminder_template: reminderTpl.trim(),
      });
      if (res.data?.success) {
        const d = res.data.data || {};
        setConnected(true);
        setTokenSet(true);
        setToken("");          // never keep it in component state after saving
        setShowToken(false);
        setNumberInfo(d.whatsapp_number_info || null);
        setStatus({ type: "success", text: res.data.message || "WhatsApp connected." });
        onSaved?.(d);
      } else {
        setConnected(false);
        setStatus({ type: "error", text: res.data?.message || "Could not verify these credentials." });
      }
    } catch (e) {
      setConnected(false);
      setStatus({ type: "error", text: extractError(e) });
    } finally {
      setBusy(false);
    }
  };

  const badge = busy
    ? <Badge tone="neutral">Checking…</Badge>
    : connected
      ? <Badge tone="success">Connected</Badge>
      : <Badge tone="danger">Not Connected</Badge>;

  return (
    <Section
      icon={MessageCircle}
      iconTone="bg-emerald-50 text-emerald-600"
      title="WhatsApp Business API Configuration"
      subtitle="Send appointment confirmations, reminders and notifications via WhatsApp automatically."
      action={<div aria-live="polite">{badge}</div>}
    >
      {status && (
        <div
          role={status.type === "error" ? "alert" : "status"}
          className={`rounded-2xl border p-4 text-sm ${
            status.type === "success"
              ? "border-emerald-100 bg-emerald-50 text-emerald-800"
              : "border-red-100 bg-red-50 text-red-800"
          }`}
        >
          {status.text}
          {status.type === "success" && numberInfo?.display_phone_number && (
            <span className="block text-emerald-700">
              Sending from {numberInfo.display_phone_number}
              {numberInfo.verified_name ? ` · ${numberInfo.verified_name}` : ""}
            </span>
          )}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id="wa-phone-id"
          label="WhatsApp Phone Number ID"
          value={phoneId}
          onChange={editPhoneId}
          onBlur={() => setPhoneIdError(validatePhoneId(phoneId))}
          placeholder="e.g. 123456789012345"
          hint="Enter your WhatsApp Business Phone Number ID from Meta"
          error={phoneIdError}
          disabled={disabled || busy}
          inputMode="numeric"
          maxLength={20}
        />

        <Field
          id="wa-token"
          label="Access Token"
          type={showToken ? "text" : "password"}
          value={token}
          onChange={editToken}
          placeholder={tokenSet ? "•••••••••••••••••• (stored — leave blank to keep)" : "Paste your permanent access token"}
          hint="Enter your WhatsApp Cloud API Access Token"
          disabled={disabled || busy}
          autoComplete="off"
          hintSlot={
            <a
              href={META_SETUP_DOCS}
              target="_blank"
              rel="noreferrer noopener"
              className="mt-1 shrink-0 text-xs font-medium text-emerald-600 hover:text-emerald-700 hover:underline"
            >
              How to get?
            </a>
          }
          rightSlot={
            <button
              type="button"
              onClick={() => setShowToken((v) => !v)}
              aria-label={showToken ? "Hide access token" : "Show access token"}
              aria-pressed={showToken}
              aria-controls="wa-token"
              disabled={disabled || busy}
              className="absolute right-1 top-1 grid h-[calc(100%-0.5rem)] w-9 place-items-center rounded-lg text-gray-400 hover:text-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-950 disabled:cursor-not-allowed"
            >
              {showToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          }
        />

        <div>
          <Label htmlFor="wa-lang">Template Language</Label>
          <select
            id="wa-lang"
            className={`${inputClass()} bg-white`}
            value={lang}
            onChange={(e) => setLang(e.target.value)}
            disabled={disabled || busy}
            aria-describedby="wa-lang-hint"
          >
            {/* A stored code Meta supports but this list omits must not be silently
                replaced on the next save. */}
            {!TEMPLATE_LANGUAGES.some((l) => l.code === lang) && lang && (
              <option value={lang}>{lang} — current</option>
            )}
            {TEMPLATE_LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>{l.label}</option>
            ))}
          </select>
          <Hint id="wa-lang-hint">Language for WhatsApp message templates</Hint>
        </div>

        <Field
          id="wa-confirm-tpl"
          label="Communication Template Name"
          value={confirmTpl}
          onChange={setConfirmTpl}
          placeholder="appointment_confirmation"
          hint="Template used for appointment confirmations"
          disabled={disabled || busy}
          autoComplete="off"
        />

        <div className="sm:col-span-2">
          <Field
            id="wa-reminder-tpl"
            label="Reminder Template Name"
            value={reminderTpl}
            onChange={setReminderTpl}
            placeholder="appointment_reminder"
            hint="Template used for appointment reminders"
            disabled={disabled || busy}
            autoComplete="off"
          />
        </div>
      </div>

      <div className="flex flex-col gap-3 border-t border-gray-100 pt-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-gray-400">
          Template names must match ones already approved in Meta Business Manager.
          Credentials are checked with WhatsApp before anything is saved.
        </p>
        <Button onClick={submit} disabled={disabled || busy} className="shrink-0">
          {busy
            ? <><Loader2 className="h-4 w-4 animate-spin" /> Verifying…</>
            : <><PlugZap className="h-4 w-4" /> {connected ? "Re-verify & save" : "Verify & save"}</>}
        </Button>
      </div>
    </Section>
  );
}
