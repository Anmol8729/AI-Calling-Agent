"""
Clarivo LiveKit voice agent.

Runs the call pipeline: Deepgram STT -> MiniMax LLM (OpenAI-compatible) ->
MiniMax TTS (custom plugin). It joins the LiveKit room created for each inbound
SIP call (Vobiz trunk -> LiveKit SIP) and acts as a full receptionist in Hindi:
it recognises callers, registers new contacts, checks availability / queue, and
books appointments — all persisted to the dashboard's Supabase DB via secured
backend endpoints (POST /api/calls/agent-*). It also adapts per business (name,
booking mode, knowledge base) fetched at the start of each call.

The FastAPI backend is unchanged in behaviour; this is a separate worker process.
Config is read from the shared root .env (same file the backend uses).

Run:  python main.py dev      (dev mode, connects to LiveKit Cloud as a worker)
"""

import asyncio
import contextvars
import logging
import os
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load the shared root .env (one level up), so MINIMAX_*, DEEPGRAM_*, LIVEKIT_*,
# AGENT_* are all available to the agent.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from livekit import agents  # noqa: E402
from livekit.agents import (  # noqa: E402
    Agent,
    AgentSession,
    RoomInputOptions,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
    get_job_context,
)
from livekit.plugins import deepgram, noise_cancellation, openai, silero  # noqa: E402

from livekit.agents import llm as _lk_llm  # noqa: E402

from minimax_tts import MiniMaxTTS  # noqa: E402

logger = logging.getLogger("clarivo-agent")

# --- Compatibility shim -----------------------------------------------------
# MiniMax's streaming chat responses can include a usage object whose token
# counts are null. LiveKit builds CompletionUsage(completion_tokens=int, ...)
# from it and crashes on None; that surfaces as a retryable "Connection error",
# so the agent retries for ~10-15s and then goes SILENT mid-call. Coerce those
# nulls to 0 so the turn completes normally. (Targets pinned livekit-agents 1.6.6;
# the parser calls `llm.CompletionUsage(...)`, so patching the module attr works.)
_OrigCompletionUsage = _lk_llm.CompletionUsage


def _lenient_completion_usage(*args, **kwargs):
    for _key in ("completion_tokens", "prompt_tokens", "total_tokens", "prompt_cached_tokens"):
        if kwargs.get(_key) is None:
            kwargs[_key] = 0
    return _OrigCompletionUsage(*args, **kwargs)


_lk_llm.CompletionUsage = _lenient_completion_usage


def _strip_chat_extra(chat_ctx: "_lk_llm.ChatContext") -> "_lk_llm.ChatContext":
    """Return a copy of `chat_ctx` with every item's provider-specific `.extra` cleared.

    LiveKit stashes provider blobs (Gemini "thought signatures" under the "google"
    key, etc.) on each chat item's `.extra`, then re-emits them as an
    `extra_content` property on assistant / tool_call messages for EVERY
    OpenAI-compatible provider (see livekit/agents/llm/_provider_format/openai.py,
    `_EXTRA_CONTENT_KEYS = ("google", "livekit", "xai")`).

    Because the FallbackAdapter shares ONE chat context across the whole chain, a
    single Gemini turn poisons it for stricter providers. Groq validates the schema
    and rejects the request outright:

        400 'messages.7' : for 'role:assistant' the following must be satisfied
            [('messages.7' : property 'extra_content' is unsupported)]

    Net effect on a live call: Groq worked only until the first assistant tool call,
    then failed on every turn -> with Gemini 503/429 at the same time, ALL LLMs were
    unavailable and the caller heard silence.

    `ChatContext.copy()` reuses the same item objects, so mutating `.extra` in place
    would also strip Gemini's own signatures. Copy just the dirty items instead.
    """
    items = []
    dirty = False
    for item in chat_ctx.items:
        if getattr(item, "extra", None):
            item = item.model_copy(update={"extra": {}})
            dirty = True
        items.append(item)
    return _lk_llm.ChatContext(items) if dirty else chat_ctx


class _StrictSchemaLLM(openai.LLM):
    """openai.LLM for providers that reject unknown message properties (Groq, MiniMax).

    Only sanitises the outgoing payload; nothing else about the plugin changes.
    """

    def chat(self, *, chat_ctx: "_lk_llm.ChatContext", **kwargs):  # type: ignore[override]
        return super().chat(chat_ctx=_strip_chat_extra(chat_ctx), **kwargs)


# Where the FastAPI backend lives + the shared secret for the internal agent
# endpoints. Both read from the root .env. If the secret is empty, all DB actions
# are disabled (the backend returns 401), so set AGENT_INTERNAL_SECRET in .env.
BACKEND_URL = os.getenv("AGENT_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
# AGENT_INTERNAL_SECRET only — deliberately NO fallback to JWT_SECRET.
# The backend dropped that fallback (see backend/services/call_tokens.py and
# routes/calls.py): reusing the session-signing key as an API credential meant
# leaking it anywhere in the call path also let an attacker mint user sessions.
# Keeping the fallback here would be worse than useless — the agent would sign
# with JWT_SECRET while the backend rejects anything not derived from
# AGENT_INTERNAL_SECRET, so every booking would 401 for a non-obvious reason.
# Empty is the honest state: DB actions are disabled and the log line below says so.
INTERNAL_SECRET = os.getenv("AGENT_INTERNAL_SECRET", "")

# STT language code -> MiniMax TTS language hint (mirrors the backend handler).
_LANG_BOOST = {
    "hi": "Hindi", "en": "English", "es": "Spanish", "fr": "French",
    "de": "German", "pt": "Portuguese", "it": "Italian", "nl": "Dutch",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "ru": "Russian",
}  

# Known-good MiniMax speech-02 human voices. A tenant's stored voice is honoured
# only if it's one of these (so a stale old voice id can't degrade the call).
_GOOD_VOICES = {
    "Wise_Woman", "Friendly_Person", "Inspirational_girl", "Deep_Voice_Man",
    "Calm_Woman", "Casual_Guy", "Lively_Girl", "Patient_Man", "Young_Knight",
    "Determined_Man", "Lovely_Girl", "Decent_Boy", "Imposing_Manner",
    "Elegant_Man", "Abbess", "Sweet_Girl_2", "Exuberant_Girl",
}

# Persona + hard tool-use rules. The LLM tends to NARRATE actions (invent a token
# number, say "booked") instead of calling tools, so the rules are stated firmly
# and injected FIRST (most salient) in _build_system_prompt().
TOOL_RULES = (
    "CRITICAL RULES — follow these exactly:\n"
    "- You do NOT know any token number, queue position, slot availability, or booking status on "
    "your own. These facts exist ONLY after you call the matching tool and read its result.\n"
    "- NEVER tell the caller an appointment is booked, NEVER say a token number, NEVER say which "
    "number is being served or how many people are ahead, and NEVER say a time is free — UNLESS a "
    "tool you called in this same conversation returned that exact value. Do not guess or make up "
    "numbers. If you have not called the tool yet, call it first.\n"
    "- To actually book, you MUST call book_appointment. Just saying 'booked' does nothing.\n"
    "- To hang up, you MUST call end_call. Just saying goodbye does NOT end the call.\n"
    "- NEVER speak or write code, function names, JSON, or tool-call syntax (for example never say "
    "'functions.book_appointment(...)'). To use a tool, just call it — the caller only ever hears "
    "plain Hindi.\n"
    "- Before booking, get the caller's REAL name and CONFIRM it (how to ask + confirm is under "
    "PATIENT INTAKE below). Never treat filler words like 'ji boliye', 'haan', 'hello', 'bataiye', "
    "'namaste' as a name.\n"
    "- Do NOT push, suggest, or bring up booking on your own. Begin collecting booking details (name, "
    "age, reason) and call book_appointment ONLY when the caller ASKS to book an appointment or to get "
    "a token/number. If the caller only has a question, answer it and do not ask for their details."
)

BASE_PERSONA = (
    "You are a warm, friendly, human female phone receptionist. Speak naturally, like a real person "
    "on the phone — never robotic, no long lists. Ask only one thing at a time and keep each reply "
    "to ONE short sentence. If "
    "something isn't in your business information, say you'll have someone follow up rather than "
    "guessing. When the caller is done (bye, thanks, 'theek hai'), say one short goodbye and then "
    "call end_call. Reply with ONLY the words to speak, in Hindi — never your thoughts or any "
    "English explanation."
)

TOKEN_MODE_GUIDE = (
    "\n\nBOOKING — this business uses TOKEN NUMBERS (a daily queue, no fixed times). Do this ONLY when "
    "the caller asks to book or get a token/number:\n"
    "- First complete PATIENT INTAKE below (CONFIRMED name, age, reason). Do NOT ask for a date or "
    "time. Then CALL book_appointment and tell the caller the EXACT token number it returned.\n"
    "- If the caller asks which number is being served or how long till their turn, CALL check_queue "
    "and say only what it returns."
)

TIME_MODE_GUIDE = (
    "\n\nBOOKING — this business uses fixed TIME SLOTS. Do this ONLY when the caller asks to book an "
    "appointment:\n"
    "- Complete PATIENT INTAKE below (CONFIRMED name, age, reason), plus the day + time they want. "
    "Convert the time to ISO-8601 (e.g. 2026-07-02T15:00) using the current date, CALL "
    "check_availability, and if free CALL book_appointment with that ISO time and the patient "
    "details. If taken, offer another time. Only confirm after book_appointment returns."
)

TOOLS_GUIDE = (
    "\n\nOTHER TOOLS: use lookup_caller to recognise a returning caller by their number and greet "
    "them by name; use register_patient to save a new caller's name as a contact when they are not "
    "booking."
)

# Healthcare intake: collected step-by-step before a booking. Injected via
# _build_system_prompt so the model asks for the patient's name (confirmed),
# age, and reason one at a time — and passes them to book_appointment.
PATIENT_INTAKE_GUIDE = (
    "\n\nWHEN TO BOOK — begin the booking flow ONLY when the caller asks to book an appointment or to "
    "get a token/number (e.g. 'appointment chahiye', 'token laga do', 'dikhana hai', 'number laga do'). "
    "If they only have a question (timings, address, services, fees, etc.), just answer it from your "
    "business information and ask if there is anything else — do NOT ask their name, age, or reason "
    "then, and do NOT bring up booking yourself.\n"
    "\nPATIENT INTAKE — this is a healthcare centre, so ONCE the caller wants to book (and only then), "
    "collect the patient's details ONE at a time, each in one short Hindi sentence, in this order:\n"
    "1. NAME — ask the patient's full name. If it was unclear, garbled, or you are unsure, say you "
    "couldn't hear properly and ask them to repeat it slowly (ask them to spell it if still unclear). "
    "Then confirm it back, e.g. 'मैं कन्फ़र्म कर लूँ, आपका नाम ___ है ना?', and wait for a yes.\n"
    "2. AGE — ask the patient's age (umar) in years.\n"
    "3. REASON — ask briefly what problem or symptom they want to see the doctor for.\n"
    "Only after you have a CONFIRMED name AND the age, call book_appointment with patient_name, age, "
    "reason, and gender (ONLY if the caller mentions it). Never invent any of these details; if the "
    "caller refuses a detail, proceed without it rather than making one up."
)

# Always appended (even when the tenant has its own system_prompt) so pure Hindi
# is enforced regardless of the base persona.
LANGUAGE_RULE = (
    "\n\nLANGUAGE — VERY IMPORTANT: Reply ONLY in natural, everyday spoken Hindi written in "
    "DEVANAGARI script. Do NOT use Hinglish, do NOT romanize Hindi, and do NOT mix in English words "
    "— always use the common Hindi word instead. The ONLY exception is an unavoidable proper name "
    "such as the business name. For example, say 'आपकी बुकिंग हो गई है', not 'aapki booking ho gayi'."
    # Your text is fed straight to a text-to-speech voice, which reads it LITERALLY.
    # Observed on a live call: the model shortened डॉक्टर to 'डॉ.' and the voice spoke it
    # as "दो" (= "two"), so the caller heard "today two Anjali Rao is". Abbreviations and
    # ASCII digits are the two things that break the spoken output, so both are banned.
    "\n\nSPOKEN OUTPUT — your words go straight to a voice that reads them EXACTLY as written, "
    "so write everything the way it should be SPOKEN OUT LOUD:\n"
    "- NEVER abbreviate. Always write 'डॉक्टर' in full — never 'डॉ.'. No short forms of any kind.\n"
    "- Write numbers in Devanagari digits (१०, ३००, २) rather than English digits (10, 300, 2).\n"
    "- Do not use symbols the voice cannot say, such as /, &, %, or brackets — write the word."
)

# Always appended (like LANGUAGE_RULE) so brevity still applies when a tenant has
# its own system_prompt.
#
# Observed on a live call: given a detailed knowledge base the model recites
# EVERYTHING it knows. Asked only "which doctor is in right now?", it read out both
# doctors' full weekly schedules - ~250 characters, 4.3 seconds of speech. That is
# the single most expensive habit it has: MiniMax TTS bills per CHARACTER and is
# about half of the per-call cost, so ~390 wasted characters is ~Rs 2.25 per call.
# It also makes the caller wait and does not sound like a receptionist.
# A hard number ("at most 25 words") is obeyed far better than "be brief".
# A second sentence is not just wordy, it is AUDIBLE: this TTS plugin is
# non-streaming, so LiveKit synthesizes each sentence in a separate request. Every
# extra sentence adds its own ~0.6s time-to-first-byte, and the caller hears that as
# a gap in the middle of the reply ("flush audio emitter due to slow audio
# generation" in the logs). One sentence = one request = no gap.
BREVITY_RULE = (
    "\n\nLENGTH — VERY IMPORTANT: Reply with EXACTLY ONE sentence of at most 25 words, and "
    "NEVER write a second sentence. Answer ONLY what the caller actually asked. Do NOT "
    "volunteer extra facts, do NOT list other doctors, days, timings, prices or services "
    "they did not ask for, and do NOT repeat anything you already said. If the full answer "
    "genuinely needs more, give the single most useful fact in that one sentence and ask "
    "whether they want the rest."
)

DEFAULT_GREETING = "नमस्ते! मैं आपकी कैसे मदद कर सकती हूँ?"


# ---------------------------------------------------------------------------
# Text helpers (think-tag stripper)
# ---------------------------------------------------------------------------

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def _suffix_prefix_len(s: str, tag: str) -> int:
    """Longest k where the last k chars of s equal the first k chars of tag.

    Holds back a partial tag ("<thi") that the next streamed chunk may complete,
    so tag detection survives chunk boundaries.
    """
    for k in range(min(len(s), len(tag) - 1), 0, -1):
        if s[-k:] == tag[:k]:
            return k
    return 0


async def _strip_think_stream(text):
    """Remove <think>...</think> spans from a streamed text iterator.

    Safety net: some MiniMax reasoning models (M1/M2/M3) emit chain-of-thought
    inside the reply content, which must NOT be spoken. With the default
    non-reasoning model (MiniMax-Text-01) there are no tags and this is a no-op
    apart from a tiny end-buffer that flushes at stream end.
    """
    buf = ""
    in_think = False
    async for chunk in text:
        if not chunk:
            continue
        buf += chunk
        out = ""
        while buf:
            if not in_think:
                i = buf.find(_THINK_OPEN)
                if i == -1:
                    hold = _suffix_prefix_len(buf, _THINK_OPEN)
                    if hold:
                        out += buf[:-hold]
                        buf = buf[-hold:]
                    else:
                        out += buf
                        buf = ""
                    break
                out += buf[:i]
                buf = buf[i + len(_THINK_OPEN):]
                in_think = True
            else:
                j = buf.find(_THINK_CLOSE)
                if j == -1:
                    hold = _suffix_prefix_len(buf, _THINK_CLOSE)
                    buf = buf[-hold:] if hold else ""
                    break
                buf = buf[j + len(_THINK_CLOSE):]
                in_think = False
        if out:
            yield out
    if buf and not in_think:
        yield buf


# Spans that must NEVER be spoken, as (opening marker, closing marker) pairs.
# Models keep inventing new ways to write a tool call as plain TEXT instead of
# actually calling it, and whatever they write ends up in the TTS stream:
#   <think>...</think>                     reasoning models (MiniMax M1/M2/M3)
#   ```functions.end_call({})```           MiniMax-Text-01
#   <function=end_call>{}</function>       Groq llama-3.3-70b  (observed on a live call)
#   <tool_call>...</tool_call>             common Qwen/llama chat templates
# "<function" (no '=') is used on purpose so <function=x>, <function_call> and
# <functions...> are all caught. It cannot match "</function>" because of the slash.
_TTS_STRIP_SPANS = (
    (_THINK_OPEN, _THINK_CLOSE),
    ("```", "```"),
    ("<function", "</function>"),
    ("<tool_call>", "</tool_call>"),
)


async def _clean_tts_stream(text):
    """Remove every span in _TTS_STRIP_SPANS from the streamed TTS text, so the caller
    only ever hears plain speech - never reasoning, code, or tool-call syntax.

    Robust to a marker being split across streamed chunks: when the tail of the
    buffer looks like the start of a marker, that tail is held back until the next
    chunk arrives instead of being spoken."""
    buf = ""
    active = -1  # index into _TTS_STRIP_SPANS, or -1 when outside any span
    async for chunk in text:
        if not chunk:
            continue
        buf += chunk
        out = ""
        while buf:
            if active == -1:
                # Find the EARLIEST opening marker of any span.
                best_i, best_span = -1, -1
                for idx, (opener, _closer) in enumerate(_TTS_STRIP_SPANS):
                    i = buf.find(opener)
                    if i != -1 and (best_i == -1 or i < best_i):
                        best_i, best_span = i, idx
                if best_i == -1:
                    # No marker. Hold back a possible partial marker at the tail.
                    hold = max(
                        (_suffix_prefix_len(buf, opener) for opener, _ in _TTS_STRIP_SPANS),
                        default=0,
                    )
                    if hold:
                        out += buf[:-hold]
                        buf = buf[-hold:]
                    else:
                        out += buf
                        buf = ""
                    break
                out += buf[:best_i]
                buf = buf[best_i + len(_TTS_STRIP_SPANS[best_span][0]):]
                active = best_span
            else:
                closer = _TTS_STRIP_SPANS[active][1]
                j = buf.find(closer)
                if j == -1:
                    # Still inside the span: drop everything except a partial closer.
                    hold = _suffix_prefix_len(buf, closer)
                    buf = buf[-hold:] if hold else ""
                    break
                buf = buf[j + len(closer):]
                active = -1
        if out:
            yield out
    # Anything left mid-span is tool syntax the model never closed - drop it.
    if buf and active == -1:
        yield buf


# ---------------------------------------------------------------------------
# Backend + SIP helpers
# ---------------------------------------------------------------------------

def _sip_numbers(room):
    """(dialed DID, caller number) from the SIP participant attributes.

    LiveKit sets sip.trunkPhoneNumber (the called number = our DID) and
    sip.phoneNumber (the caller) on the SIP participant. (None, None) if absent.
    """
    did = caller = None
    try:
        for p in room.remote_participants.values():
            attrs = getattr(p, "attributes", None) or {}
            did = did or attrs.get("sip.trunkPhoneNumber")
            caller = caller or attrs.get("sip.phoneNumber")
    except Exception:
        pass
    return did, caller


async def _resolve_sip_numbers(ctx):
    """Wait for the SIP caller to actually JOIN, then read the dialed DID + caller
    number from its attributes.

    Reading at entrypoint start (before the participant has joined) returns
    (None, None), which forces the single-clinic fallback (get_only_tenant) and
    breaks multi-clinic routing. We also log the full attribute/metadata set so we
    can see exactly which keys LiveKit's SIP trunk populates (the DID may live under
    a different key, or need to be added via the SIP dispatch rule)."""
    part = None
    try:
        part = await asyncio.wait_for(ctx.wait_for_participant(), timeout=8.0)
    except Exception as e:
        logger.warning(f"wait_for_participant timed out/failed: {e}")
    if part is None:
        return _sip_numbers(ctx.room)
    attrs = dict(getattr(part, "attributes", None) or {})
    logger.info(
        f"SIP participant joined: identity={getattr(part, 'identity', None)!r} "
        f"kind={getattr(part, 'kind', None)} name={getattr(part, 'name', None)!r} "
        f"attrs={attrs} metadata={getattr(part, 'metadata', None)!r}"
    )
    did = attrs.get("sip.trunkPhoneNumber") or attrs.get("sip.dnis")
    caller = attrs.get("sip.phoneNumber") or attrs.get("sip.from")
    return did, caller


def _try_parse_iso(s):
    """Return an ISO-8601 string if `s` parses as a datetime, else None."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
    except Exception:
        return None


# Per-call token issued by /api/calls/agent-context. It scopes this worker to ONE
# clinic and ONE call, so the long-lived shared secret is no longer sent to (or
# usable against) any other endpoint.
#
# A ContextVar, not a module global: with AGENT_RECYCLE_AFTER_CALL=0 (the Linux
# setting) one worker process serves several calls, potentially concurrently, and a
# global would let call B overwrite call A's token and write into the wrong tenant.
# Each LiveKit job runs in its own task tree, and asyncio.create_task copies the
# current context, so every background report inherits the right call's token.
_CALL_TOKEN: contextvars.ContextVar = contextvars.ContextVar("clarivo_call_token", default="")


async def _agent_post(path: str, body: dict, timeout: float = 15.0):
    """POST to a backend internal agent endpoint.

    Sends the per-call token when one has been issued; only the /agent-context
    bootstrap falls back to the shared secret. Returns (status_code, data_dict).
    Raises on transport errors (callers handle).
    """
    token = _CALL_TOKEN.get()
    headers = (
        {"Authorization": f"Bearer {token}"} if token
        else {"X-Internal-Secret": INTERNAL_SECRET}
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{BACKEND_URL}{path}", headers=headers, json=body)
    try:
        data = resp.json()
    except Exception:
        data = {}
    return resp.status_code, data


async def _fetch_context(did, call_id=None):
    """Load per-call business config from the backend, and capture the call token.

    This is the ONLY request that uses the shared secret. The backend resolves the
    clinic from the dialed DID and returns a token bound to (clinic, call); storing
    it here means every later request is scoped to just this call. {} on failure.
    """
    if not INTERNAL_SECRET:
        return {}
    try:
        # Force the bootstrap to use the shared secret even if a previous call in
        # this process left a token in a parent context.
        _CALL_TOKEN.set("")
        status, data = await _agent_post(
            "/api/calls/agent-context", {"did": did, "call_id": call_id}
        )
        if status == 200 and data.get("success"):
            ctx_data = data.get("data") or {}
            token = ctx_data.get("call_token") or ""
            if token:
                _CALL_TOKEN.set(token)
            else:
                logger.error(
                    "agent-context returned no call_token — bookings and call logs "
                    "will fail. Is the backend up to date?"
                )
            return ctx_data
        logger.warning(f"agent-context -> {status} {data.get('message')}")
    except Exception as e:
        logger.warning(f"agent-context failed: {e}")
    return {}


# ---------------------------------------------------------------------------
# Call logging (feeds the dashboard's Calls page / live view / funnel / quota)
# ---------------------------------------------------------------------------
# Every one of those views reads the backend's `call_logs` table. It used to be
# filled by the /media-stream websocket, which this LiveKit architecture no longer
# uses — so it stayed empty and the dashboard showed no calls at all. We report the
# lifecycle here instead.
#
# These are strictly FIRE-AND-FORGET: a call log is never worth adding latency to a
# live conversation, so nothing here is awaited on the critical path and every
# failure is swallowed after logging.

_bg_tasks: set = set()


def _fire(coro):
    """Run a coroutine in the background without blocking the conversation."""
    task = asyncio.create_task(coro)
    # Hold a reference until it finishes, otherwise the task can be garbage
    # collected mid-flight and Python warns about it.
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def _report(path: str, body: dict) -> None:
    if not INTERNAL_SECRET:
        return
    try:
        status, data = await _agent_post(path, body, timeout=10.0)
        if status != 200:
            logger.warning(f"{path} -> {status} {data.get('message')}")
    except Exception as e:
        logger.warning(f"{path} failed: {e}")


async def _warm_llm(agent_llm) -> None:
    """Open the LLM's HTTP/TLS connection early with a tiny throwaway completion, so
    the FIRST real user turn doesn't pay a cold ~2-3s handshake (logs showed the
    first turn's TTFT ~3.9s cold vs ~1.5s warm). Since the worker is recycled after
    each call on Windows, every call otherwise starts cold. Best-effort."""
    try:
        cctx = _lk_llm.ChatContext.empty()
        cctx.add_message(role="user", content="hi")
        stream = agent_llm.chat(chat_ctx=cctx)
        try:
            async for _ in stream:
                break  # first token proves the connection is up; discard the rest
        finally:
            await stream.aclose()
    except Exception as e:
        logger.debug(f"LLM warm-up skipped: {e}")


def _build_system_prompt(ctx_data: dict) -> str:
    """Tailor the system prompt to the business + its booking mode + knowledge."""
    business = ctx_data.get("business_name") or "our business"
    mode = (ctx_data.get("booking_mode") or "time").strip().lower()
    custom = (ctx_data.get("system_prompt") or "").strip()
    kb = (ctx_data.get("knowledge_base") or "").strip()
    now_str = datetime.now().strftime("%A, %d %B %Y, %I:%M %p")

    parts = [TOOL_RULES, "\n\n", custom or BASE_PERSONA]
    parts.append(
        f"\n\nYou are the receptionist for {business}. The current date and time is {now_str}."
    )
    parts.append(LANGUAGE_RULE)
    parts.append(BREVITY_RULE)
    parts.append(TOKEN_MODE_GUIDE if mode == "token" else TIME_MODE_GUIDE)
    parts.append(PATIENT_INTAKE_GUIDE)
    parts.append(TOOLS_GUIDE)
    if kb:
        # "Answer only the part that was asked" is repeated here on purpose: this block
        # is where the model gets its urge to recite the whole knowledge base, so the
        # limit lands better next to the facts themselves than only in BREVITY_RULE.
        parts.append(
            "\n\nBusiness information you can use to answer the caller (rely on these facts; if a "
            "question isn't covered, say you'll have someone follow up). Quote ONLY the one detail "
            "the caller asked for — never read out a whole list, schedule, or price table:\n" + kb
        )
    return "".join(parts)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class VoxAgent(Agent):
    """Inbound receptionist: recognises callers, registers contacts, checks
    availability/queue, books appointments, and ends the call — all via secured
    backend calls so everything lands in the dashboard's Supabase DB."""

    def __init__(self, instructions: str, clinic_id=None, did=None, booking_mode=None) -> None:
        super().__init__(instructions=instructions)
        self._clinic_id = clinic_id
        self._did = did
        self._booking_mode = booking_mode

    # --- helpers -----------------------------------------------------------

    def _call_body(self) -> dict:
        """Common identity for backend calls: the live caller number.

        The clinic is NOT sent any more — the backend reads it from the per-call
        token, so a request can no longer name the tenant it writes to.
        `booking_mode` stays as a hint that saves the backend one tenant read; it
        is re-read from the DB if it is not a value the backend recognises.
        """
        _live_did, caller = _sip_numbers(get_job_context().room)
        return {
            "caller_phone": caller,
            "booking_mode": self._booking_mode,
        }

    # Strip <think>...</think> and ```code``` before it is spoken, so the caller
    # never hears reasoning or a tool call written as text. tts_node text is plain str.
    def tts_node(self, text, model_settings):
        return Agent.default.tts_node(self, _clean_tts_stream(text), model_settings)

    # --- tools -------------------------------------------------------------

    @function_tool
    async def lookup_caller(self, ctx: RunContext):
        """Recognise the current caller by their phone number: whether they're a
        known contact, their name, any notes, and their nearest upcoming
        appointment. Use to greet returning callers by name."""
        if not INTERNAL_SECRET:
            return "Record abhi check nahi kar pa rahi."
        try:
            status, data = await _agent_post("/api/calls/agent-lookup", self._call_body())
        except Exception as e:
            logger.error(f"lookup_caller failed: {e}")
            return "Record abhi check nahi kar pa rahi."
        if status == 200 and data.get("success"):
            d = data.get("data") or {}
            if d.get("known"):
                name = d.get("name") or "caller"
                up = d.get("upcoming") or {}
                if up.get("when"):
                    return f"Returning caller: {name}. Unki ek appointment hai: {up.get('when')}."
                return f"Returning caller: {name}."
            return "Naya caller hai, koi record nahi. Naam poochho."
        return "Record abhi check nahi kar pa rahi."

    @function_tool
    async def register_patient(
        self,
        ctx: RunContext,
        patient_name: str,
        age: int = 0,
        gender: str = "",
        note: str = "",
    ):
        """Register the caller as a new patient/contact (or update their details) so
        they appear in the dashboard. Call this when you learn a new caller's name
        (and, for a healthcare centre, their age), or when they want to be
        registered without booking.

        Args:
            patient_name: the caller's full, confirmed name.
            age: the patient's age in years, if given (0 if unknown).
            gender: the patient's gender, only if the caller mentions it.
            note: an optional short note about the caller (e.g. their query).
        """
        if not INTERNAL_SECRET:
            return "Details abhi save nahi kar pa rahi. Team unhe call karegi."
        body = self._call_body()
        body.update({
            "patient_name": patient_name,
            "age": age if age and age > 0 else None,
            "gender": (gender or "").strip() or None,
            "note": note or None,
        })
        try:
            status, data = await _agent_post("/api/calls/agent-patient", body)
        except Exception as e:
            logger.error(f"register_patient failed: {e}")
            return "Details abhi save nahi kar pa rahi."
        if status == 200 and data.get("success"):
            return f"{patient_name} ji ka record save ho gaya."
        return "Details abhi save nahi kar pa rahi."

    @function_tool
    async def check_availability(self, ctx: RunContext, preferred_time: str):
        """Check whether a specific date/time is free before offering or confirming
        it (time-slot businesses). preferred_time must be an ISO-8601 datetime such
        as 2026-07-02T15:00, computed from the caller's requested day/time."""
        if not INTERNAL_SECRET:
            return "Abhi calendar check nahi kar pa rahi."
        appt_at = _try_parse_iso(preferred_time)
        if not appt_at:
            return "Kripya ek specific din aur samay batayein."
        # No clinic_id: the backend takes it from the per-call token.
        body = {"appointment_at": appt_at}
        try:
            status, data = await _agent_post("/api/calls/agent-availability", body)
        except Exception as e:
            logger.error(f"check_availability failed: {e}")
            return "Abhi calendar check nahi kar pa rahi."
        if status == 200 and data.get("success"):
            if (data.get("data") or {}).get("available"):
                return "Yeh samay available hai."
            return "Yeh samay pehle se booked hai; koi doosra samay suggest karein."
        return "Abhi calendar check nahi kar pa rahi."

    @function_tool
    async def check_queue(self, ctx: RunContext):
        """Report the live token/queue status: which token is being served now and,
        if known, the caller's own token and how many people are ahead. Use for
        questions like 'number kya chal raha hai' (token businesses)."""
        if not INTERNAL_SECRET:
            return "Abhi queue check nahi kar pa rahi."
        try:
            status, data = await _agent_post("/api/calls/agent-queue", self._call_body())
        except Exception as e:
            logger.error(f"check_queue failed: {e}")
            return "Abhi queue check nahi kar pa rahi."
        if status == 200 and data.get("success"):
            s = data.get("data") or {}
            cur = int(s.get("current_number") or 0)
            total = int(s.get("total_issued") or 0)
            ct = s.get("caller_token")
            ahead = s.get("ahead")
            if cur > 0:
                base = f"Abhi token number {cur} chal raha hai."
            elif total > 0:
                base = "Aaj queue abhi shuru nahi hui hai."
            else:
                base = "Aaj abhi tak koi token issue nahi hua."
            if ct is not None:
                if ahead and ahead > 0:
                    return f"{base} Aapka token {ct} hai; aapse aage lagbhag {ahead} log hain."
                return f"{base} Aapka token {ct} hai; abhi aapki baari hai."
            return base
        return "Abhi queue check nahi kar pa rahi."

    @function_tool
    async def book_appointment(
        self,
        ctx: RunContext,
        patient_name: str,
        age: int = 0,
        reason: str = "",
        gender: str = "",
        preferred_time: str = "",
    ):
        """Save the caller's appointment into the system. Call this ONCE you have
        the caller's CONFIRMED name and age (for time-slot businesses, also the
        preferred time).

        Args:
            patient_name: the caller's full, confirmed name (confirm it first).
            age: the patient's age in years (use 0 only if the caller refused to give it).
            reason: short reason / symptom for the visit, if given.
            gender: the patient's gender, only if the caller mentions it.
            preferred_time: for time-slot businesses, the desired time as ISO-8601
                (e.g. 2026-07-02T15:00). Leave empty for token/queue businesses.
        """
        if not INTERNAL_SECRET:
            logger.warning("book_appointment: AGENT_INTERNAL_SECRET not set — cannot save booking")
            return ("Abhi booking system se connect nahi ho pa raha. Caller ko boliye ki humari "
                    "team unhe thodi der mein call karegi.")
        body = self._call_body()
        body.update({
            "patient_name": patient_name,
            "age": age if age and age > 0 else None,
            "gender": (gender or "").strip() or None,
            "reason": reason or None,
            "appointment_date": preferred_time or None,
        })
        appt_at = _try_parse_iso(preferred_time)
        if appt_at:
            body["appointment_at"] = appt_at
        logger.info(f"book_appointment: clinic={self._clinic_id} name={patient_name!r} when={preferred_time!r}")
        try:
            status, data = await _agent_post("/api/calls/agent-book", body)
        except Exception as e:
            logger.error(f"book_appointment failed: {e}")
            return "Booking save karne mein dikkat aa rahi hai. Caller ko boliye koi unhe call karega."
        if status == 200 and data.get("success"):
            d = data.get("data") or {}
            if d.get("booking_mode") == "token" and d.get("token_number"):
                return f"Appointment book ho gayi. Caller ka token number {d['token_number']} hai."
            display = d.get("display")
            if display and display != "Unspecified":
                return f"Appointment book ho gayi — {display}."
            return "Appointment book ho gayi."
        if status == 409:
            return "Yeh samay pehle se booked hai. Caller se koi doosra samay poochhiye."
        logger.warning(f"book_appointment: backend said {status} {data}")
        return "Booking save nahi ho payi. Caller ko boliye ki koi unhe jaldi call karega."

    @function_tool
    async def end_call(self, ctx: RunContext):
        """End and hang up the phone call. You MUST call this to end a call — just
        saying goodbye does NOT hang up. Call it as soon as the caller signals they
        are done (bye, thanks, 'theek hai', 'bas itna hi') or their request is fully
        handled. Say one short goodbye line first, then call this immediately."""
        # Let the current spoken line (the goodbye) finish before hanging up.
        await ctx.wait_for_playout()
        await get_job_context().delete_room()


def prewarm(proc: agents.JobProcess) -> None:
    # Load the VAD once per worker process (not per call). A shorter
    # min_silence_duration detects end-of-turn faster => snappier replies. Raise
    # AGENT_VAD_MIN_SILENCE if the agent starts replying before the caller finishes.
    proc.userdata["vad"] = silero.VAD.load(
        min_silence_duration=float(os.getenv("AGENT_VAD_MIN_SILENCE", "0.4") or "0.4"),
    )


async def entrypoint(ctx: agents.JobContext) -> None:
    await ctx.connect()
    logger.info(f"Agent joined room: {ctx.room.name}")

    # Windows stability workaround: LiveKit's native (Rust) layer can panic during
    # room teardown at call-end ("malformed serialized RtcError"), leaving the
    # worker process alive but unable to accept the NEXT call. Force a clean process
    # exit once the job ends so the run-agent wrapper immediately launches a fresh
    # worker. Disable with AGENT_RECYCLE_AFTER_CALL=0 (e.g. on Linux, where this
    # native panic does not occur and one worker can serve many calls).
    if os.getenv("AGENT_RECYCLE_AFTER_CALL", "1").strip() != "0":
        async def _recycle_worker():
            # os._exit skips all cleanup, so let the in-flight call-log reports land
            # first — otherwise the call would never be marked completed and would
            # sit "active" forever on the dashboard's live view.
            if _bg_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*list(_bg_tasks), return_exceptions=True), timeout=3.0
                    )
                except Exception:
                    pass
            logger.info("Call ended — recycling worker process (Windows teardown workaround).")
            os._exit(0)
        ctx.add_shutdown_callback(_recycle_worker)

    # Resolve who was called (DID) + fetch this business's config so the agent
    # greets, behaves, and books correctly for that specific clinic. We WAIT for the
    # SIP participant so the DID is actually available (reading too early gave
    # None -> single-clinic fallback, which can't work for multiple clinics).
    did, caller = await _resolve_sip_numbers(ctx)

    # Stale-dispatch guard. After a network outage LiveKit delivers the job requests
    # it queued up, including ones for calls the caller already abandoned. Those rooms
    # are EMPTY: _resolve_sip_numbers logs "wait_for_participant timed out" and the DID
    # comes back None. Continuing would run a whole session against nobody - greeting
    # synthesis, a Deepgram socket and an LLM call, all billable - and when a REAL job
    # is running in the same process at the same time (observed live: two jobs 5s
    # apart), the two sessions fight over the audio and the caller hears broken speech.
    # Nothing to talk to => end the job now. The room is left for LiveKit to reap.
    if not ctx.room.remote_participants:
        logger.warning(
            "No participant in room %s after waiting - stale/duplicate dispatch, ending job.",
            ctx.room.name,
        )
        return

    # The room name is unique per call, so it doubles as the call id. Needed BEFORE
    # fetching context, because the per-call token is bound to it.
    call_id = ctx.room.name

    ctx_data = await _fetch_context(did, call_id)
    clinic_id = ctx_data.get("clinic_id")
    business_name = ctx_data.get("business_name") or "our business"
    logger.info(f"Call context: did={did} caller={caller} clinic={clinic_id} business={business_name!r}")

    # Log the call so the dashboard can show it — live now, and in history after.
    # The clinic is taken from the call token server-side, so it is not sent here.
    _fire(_report("/api/calls/agent-call-start", {
        "call_id": call_id,
        "caller_phone": caller,
        "direction": "inbound",
    }))

    system_prompt = os.getenv("AGENT_SYSTEM_PROMPT") or _build_system_prompt(ctx_data)

    greeting = os.getenv("AGENT_GREETING")
    if not greeting:
        greeting = (
            f"नमस्ते! {business_name} में आपका स्वागत है। मैं आपकी कैसे मदद कर सकती हूँ?"
            if business_name and business_name != "our business"
            else DEFAULT_GREETING
        )

    # Per-tenant language + voice (voice only if a known-good speech-02 id), else
    # the good defaults. .env can force these via DEEPGRAM_LANGUAGE / MINIMAX_TTS_VOICE.
    language = os.getenv("DEEPGRAM_LANGUAGE") or ctx_data.get("language") or "hi"
    # Honor ANY voice the dashboard set (a built-in voice id OR a MiniMax cloned
    # voice id). Env override wins; falls back to a good default when unset.
    tenant_voice = (ctx_data.get("voice") or "").strip()
    voice = os.getenv("MINIMAX_TTS_VOICE") or tenant_voice or "Calm_Woman"
    lang_boost = os.getenv("MINIMAX_LANGUAGE_BOOST") or _LANG_BOOST.get(language.lower(), "Hindi")

    # LLM: prefer Groq (reliable tool-calling + very low latency) when GROQ_API_KEY
    # is set; otherwise fall back to MiniMax. Both use the OpenAI-compatible client.
    # TTS stays MiniMax below, so the cloned voice is unchanged.
    _gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    _groq_key = os.getenv("GROQ_API_KEY", "").strip()
    # AGENT_LLM_PROVIDER forces a provider (gemini | groq | minimax) so the two can be
    # A/B tested on real calls WITHOUT deleting keys from .env. Empty = the default
    # auto order below (Gemini -> Groq -> MiniMax).
    #
    # Measured from a home connection in India with this exact system prompt:
    #   Gemini gemini-flash-latest : ~2.5-3.2s to first token
    #   Groq   llama-3.3-70b       : ~0.2-0.7s to first token
    # Groq is far snappier, but its FREE tier (~12k tokens/min) can 429 mid-call and
    # the agent then goes silent — so it needs either a paid tier or AGENT_PREEMPTIVE=0
    # (which halves tokens by not firing a second speculative request per turn).
    _provider = os.getenv("AGENT_LLM_PROVIDER", "").strip().lower()
    if _provider == "groq" and not _groq_key:
        logger.warning("AGENT_LLM_PROVIDER=groq but GROQ_API_KEY is empty — falling back to auto.")
        _provider = ""
    if _provider == "gemini" and not _gemini_key:
        logger.warning("AGENT_LLM_PROVIDER=gemini but GEMINI_API_KEY is empty — falling back to auto.")
        _provider = ""
    # Ordered LLM chain: the first entry serves the call, the rest are failovers.
    # AGENT_LLM_ORDER sets that order, e.g. "groq,gemini,minimax". This matters a lot:
    # whichever provider is first pays the latency, and if it is rate-limited every
    # turn wastes a failed attempt (up to attempt_timeout of caller silence) before
    # failing over. Put the provider with real quota FIRST.
    _order = [
        p.strip().lower()
        for p in os.getenv("AGENT_LLM_ORDER", "gemini,groq,minimax").split(",")
        if p.strip()
    ] or ["gemini", "groq", "minimax"]
    # AGENT_LLM_PROVIDER pins a SINGLE provider (no failover) so one can be A/B tested
    # on real calls in isolation. It overrides AGENT_LLM_ORDER.
    #
    # This is a DIAGNOSTIC setting and it is dangerous to leave on. Pinned means the
    # FallbackAdapter is never built, so the moment that one provider rate-limits or
    # times out the caller hears silence — there is nothing behind it. Observed live
    # with AGENT_LLM_PROVIDER=gemini on a free key: `generate_content_free_tier_requests,
    # limit: 5` per MINUTE, and a call spends 1-2 requests per turn, so the agent went
    # quiet after roughly three turns. Note that is a REQUEST-count cap, separate from
    # the token-per-minute allowance mentioned in _add_gemini below — the request cap
    # is the one that bites.
    #
    # So: warn every time, and refuse outright in production. The backend's
    # check_production_config() blocks boot on the same setting, which catches it
    # before a single call arrives instead of after a client complains.
    if _provider:
        _order = [_provider]
        _env = (os.getenv("ENV", "") or "").strip().lower()
        _msg = (
            f"AGENT_LLM_PROVIDER={_provider} pins ONE provider and DISABLES failover. "
            "If it rate-limits or stalls, the caller hears silence. Unset it (or use "
            "AGENT_LLM_ORDER=groq,gemini,minimax) for anything other than A/B testing."
        )
        if _env in ("production", "prod"):
            raise RuntimeError(f"Refusing to serve calls in production: {_msg}")
        logger.warning(_msg)
    _chain: list = []
    _labels: list = []

    def _add_gemini() -> None:
        if not _gemini_key:
            return
        # Google Gemini via its OpenAI-compatible endpoint. Its free tier is generous
        # on TOKENS (~250k/min vs Groq free's ~12k), so the large prompt + tools +
        # knowledge base does not blow the token budget.
        #
        # But there is a SECOND, separate free-tier cap that does bite:
        # `generate_content_free_tier_requests, limit: 5` per minute — a REQUEST count.
        # A call spends 1-2 requests per turn, so Gemini alone runs dry after roughly
        # three turns and the caller hears silence. That is why Gemini must not be the
        # only provider on a free key: keep Groq and MiniMax behind it (they have
        # independent quotas), or enable billing on the Google project.
        # gemini-flash-lite-latest: fastest option that is actually reliable here.
        # Measured against this agent's real payload (~1.8k-token prompt + 6 tools),
        # 6/6 successful streams at ~1.3s to first token, vs ~2.4s for
        # gemini-flash-latest. It had hung server-side once before; a re-probe showed
        # that was transient. gemini-2.0-flash / -flash-lite return 429 on this key,
        # and Groq is faster still but its token-per-minute cap silences long calls.
        # Override via GEMINI_LLM_MODEL.
        _gemini_model = os.getenv("GEMINI_LLM_MODEL", "gemini-flash-lite-latest")
        _gemini_base = os.getenv(
            "GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        _chain.append(openai.LLM(
            model=_gemini_model, api_key=_gemini_key, base_url=_gemini_base, temperature=0.3,
        ))
        _labels.append(f"gemini:{_gemini_model}")
        # Optional second Gemini model. OFF by default: the `-latest` aliases both
        # resolve to the same underlying model family on ONE project, so they share
        # `generate_content_free_tier_requests` (limit 5/min on a free key — observed
        # live). That is fake redundancy: when the primary 429s the second one 429s
        # too, and it still burns an `attempt_timeout` slot of caller silence.
        # Real redundancy comes from a DIFFERENT provider (Groq / MiniMax below).
        # Set GEMINI_FALLBACK_MODEL only once the project is on a paid tier.
        _gemini_fallback = os.getenv("GEMINI_FALLBACK_MODEL", "").strip()
        if _gemini_fallback and _gemini_fallback != _gemini_model:
            _chain.append(openai.LLM(
                model=_gemini_fallback, api_key=_gemini_key, base_url=_gemini_base, temperature=0.3,
            ))
            _labels.append(f"gemini:{_gemini_fallback}")

    def _add_groq() -> None:
        if not _groq_key:
            return
        # _StrictSchemaLLM, not openai.LLM: Groq 400s on the `extra_content` property
        # that LiveKit copies out of Gemini's replies into the shared chat context.
        _groq_model = os.getenv("GROQ_LLM_MODEL", "llama-3.3-70b-versatile")
        _chain.append(_StrictSchemaLLM(
            model=_groq_model,
            api_key=_groq_key,
            base_url=os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1"),
            temperature=0.3,
        ))
        _labels.append(f"groq:{_groq_model}")

    def _add_minimax() -> None:
        # MiniMax is kept in the chain whenever a key exists — not only when nothing
        # else is configured. Its quota is separate from Gemini's and Groq's, so it is
        # the only thing left when both of those are rate-limited at the same time
        # (observed live: all 3 LLMs unavailable -> caller heard silence). Quality is
        # worse (MiniMax-Text-01 sometimes writes tool calls as plain text), so keep it
        # LAST in AGENT_LLM_ORDER; set AGENT_MINIMAX_LAST_RESORT=0 to drop it entirely.
        _minimax_key = os.getenv("MINIMAX_API_KEY", "").strip()
        if not _minimax_key:
            return
        if _chain and (
            os.getenv("AGENT_MINIMAX_LAST_RESORT", "1").strip() == "0" or _provider
        ):
            return
        _minimax_model = os.getenv("MINIMAX_LLM_MODEL", "MiniMax-Text-01")
        _chain.append(_StrictSchemaLLM(
            model=_minimax_model,
            api_key=_minimax_key,
            base_url=os.getenv("MINIMAX_API_BASE", "https://api.minimax.io/v1"),
            temperature=0.3,
        ))
        _labels.append(f"minimax:{_minimax_model}")

    _builders = {"gemini": _add_gemini, "groq": _add_groq, "minimax": _add_minimax}
    for _name in _order:
        _builder = _builders.get(_name)
        if _builder is None:
            logger.warning(f"AGENT_LLM_ORDER: unknown provider '{_name}' — ignored.")
            continue
        _builder()
    if not _chain:
        # Nothing matched (e.g. AGENT_LLM_ORDER typo'd, or no keys at all). Try every
        # provider so the call still gets answered rather than failing outright.
        for _builder in _builders.values():
            _builder()

    if len(_chain) > 1:
        # Fail OVER instead of retrying a provider that is down. Without this, a 503
        # from the primary meant ~23s of retries against the same dead model while the
        # caller heard nothing and hung up (observed on a real call). max_retry_per_llm=0
        # means "don't retry, move on"; attempt_timeout also catches a provider that
        # accepts the request but never streams (the earlier flash-lite hang).
        agent_llm = _lk_llm.FallbackAdapter(
            _chain,
            attempt_timeout=float(os.getenv("AGENT_LLM_ATTEMPT_TIMEOUT", "6") or "6"),
            max_retry_per_llm=0,
        )
        logger.info(f"LLM = {_labels[0]} (fallbacks: {', '.join(_labels[1:])})")
    else:
        agent_llm = _chain[0]
        # Was logger.info, which read like any other startup line and did not say what
        # it costs. A single-provider chain is the one configuration with no safety net,
        # so it is the one that should stand out in the log.
        logger.warning(f"LLM = {_labels[0]} (NO FALLBACK — a single failure goes silent)")

    # Build the TTS engine up front so its HTTP/TLS connection to MiniMax can be
    # warmed in the background (task below) WHILE the session starts. The greeting
    # is the first synth of a fresh (recycled) process, so without this warm-up it
    # pays a ~1.4s cold handshake before the caller hears anything.
    tts_engine = MiniMaxTTS(
        api_key=os.getenv("MINIMAX_API_KEY", ""),
        group_id=os.getenv("MINIMAX_GROUP_ID"),
        base_url=os.getenv("MINIMAX_API_BASE", "https://api.minimax.io/v1"),
        model=os.getenv("MINIMAX_TTS_MODEL", "speech-2.6-turbo"),
        voice=voice,
        language_boost=lang_boost,
        # The PSTN leg is 8 kHz, so requesting 24 kHz meant synthesizing and streaming
        # 3x the bytes only for them to be downsampled. 8 kHz gives faster first audio
        # (and stops the "slow audio generation" emitter underruns) with no audible
        # loss on a phone call. Raise it only if this agent ever serves web/WebRTC
        # callers, where the extra bandwidth is actually heard.
        sample_rate=int(os.getenv("MINIMAX_TTS_SAMPLE_RATE", "8000") or "8000"),
        # Clean, unclipped MiniMax volume (1.0); loudness comes from the downstream
        # tanh limiter (gain) so audio is loud but CLEAR.
        volume=float(os.getenv("MINIMAX_TTS_VOL", "1.0") or "1.0"),
        speed=float(os.getenv("MINIMAX_TTS_SPEED", "1.0") or "1.0"),
        gain=float(os.getenv("MINIMAX_TTS_GAIN", "2.0") or "2.0"),
        # Emotional delivery, e.g. "happy" — makes speech-2.8 sound noticeably more
        # human. Only sent when set (older TTS models don't support it).
        emotion=os.getenv("MINIMAX_TTS_EMOTION", "").strip(),
    )
    # Kick off the connection warm-ups now (TTS + LLM), in parallel with the
    # session start below, so the greeting and the first user turn don't pay cold
    # handshakes. TTS is awaited before the greeting; the LLM warm finishes during
    # greeting playback, before the caller's first turn.
    _tts_warm = asyncio.create_task(tts_engine.warm_up())
    _llm_warm = asyncio.create_task(_warm_llm(agent_llm))

    # Monthly call quota exceeded (decided server-side in /agent-context, which is the
    # only place the tenant is known before the conversation starts). Say one line and
    # hang up: no STT, no LLM, no tools, so an over-quota call cannot book anything and
    # costs nothing beyond a few seconds of TTS.
    #
    # Handled here rather than earlier because it needs the tenant's voice and language
    # to speak at all — refusing before that point would mean silence, which is exactly
    # what a caller should NOT hear.
    if ctx_data.get("quota_exceeded"):
        message = (ctx_data.get("quota_message") or "").strip() or (
            "Sorry, we are unable to take your call at the moment. Please try again later."
        )
        logger.warning(
            f"Call {call_id} refused: clinic {clinic_id} is over its monthly call quota. "
            "Speaking the quota message and hanging up."
        )
        _llm_warm.cancel()
        try:
            await asyncio.wait_for(_tts_warm, timeout=3.0)
        except Exception:  # noqa: BLE001 — a cold TTS still speaks, just slower
            pass
        try:
            quota_session = AgentSession(tts=tts_engine)
            await quota_session.start(agent=Agent(instructions=""), room=ctx.room)
            # Same guard as the greeting below: if the caller hangs up while the
            # session is still starting, say() raises "AgentSession isn't running",
            # and unguarded that crashed the job (and the worker, under the Windows
            # recycle) on every early hang-up.
            await quota_session.say(message, allow_interruptions=False)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Quota message not played — caller likely disconnected: {e}")
        finally:
            # Close the call log so the dashboard does not leave it "active" forever,
            # then delete the room to release the SIP leg.
            await _report("/api/calls/agent-call-end", {"call_id": call_id, "status": "completed"})
            try:
                await get_job_context().delete_room()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"delete_room after quota refusal failed: {e}")
        return

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(
            model=os.getenv("DEEPGRAM_MODEL", "nova-2"),
            language=language,
            api_key=os.getenv("DEEPGRAM_API_KEY"),
        ),
        # LLM chosen above (Gemini / Groq / MiniMax). TTS built + warmed above.
        llm=agent_llm,
        tts=tts_engine,
        # Respond faster: start generating early, don't wait long after the caller
        # stops speaking. max_endpointing_delay was 2.0s — the biggest source of a
        # "late" reply; 1.0s feels snappy on the phone. Raise AGENT_MAX_ENDPOINTING
        # if the AI starts cutting callers off mid-sentence.
        # preemptive_generation lowers latency but can fire a 2nd LLM request per
        # turn (doubling token use) — set AGENT_PREEMPTIVE=0 to conserve Groq's
        # tight free-tier quota. Leave on for Gemini (huge free quota).
        preemptive_generation=(os.getenv("AGENT_PREEMPTIVE", "1").strip() != "0"),
        min_endpointing_delay=float(os.getenv("AGENT_MIN_ENDPOINTING", "0.4") or "0.4"),
        max_endpointing_delay=float(os.getenv("AGENT_MAX_ENDPOINTING", "1.0") or "1.0"),
        # Mark the caller "away" after this many seconds of silence; we hang up on
        # that (the LLM doesn't reliably call end_call when the caller just goes
        # quiet). Tunable via .env without code changes.
        user_away_timeout=float(os.getenv("AGENT_SILENCE_HANGUP_SEC", "10") or "10"),
    )

    # Per-turn latency metrics -> logs, so we can see exactly where time goes
    # (EOU end_of_utterance_delay = how long we waited after the caller stopped;
    # LLM ttft = time to first token; TTS ttfb = time to first audio byte).
    # Grep the agent output for "[latency]" after a test call.
    def _on_metrics(ev):
        m = ev.metrics
        parts = [type(m).__name__]
        for attr in ("end_of_utterance_delay", "transcription_delay", "ttft", "ttfb", "duration"):
            v = getattr(m, attr, None)
            if isinstance(v, (int, float)):
                parts.append(f"{attr}={v:.3f}")
        logger.info("[latency] " + " ".join(parts))

    session.on("metrics_collected", _on_metrics)

    # Mirror the conversation into the call log so the dashboard can show a real
    # transcript (Calls page + contact history). Fire-and-forget per turn.
    def _on_conversation_item(ev):
        item = getattr(ev, "item", None)
        role = getattr(item, "role", None)
        if role not in ("user", "assistant"):
            return  # skip tool calls / handoffs — only spoken turns are useful here
        text_content = (getattr(item, "text_content", None) or "").strip()
        if not text_content:
            return
        _fire(_report("/api/calls/agent-call-transcript", {
            "call_id": call_id,
            "role": role,
            "content": text_content,
        }))

    session.on("conversation_item_added", _on_conversation_item)

    # Close the call out (status + duration) when the session ends. Registered as a
    # shutdown callback as well as the session `close` event, because on Windows the
    # native layer can panic during teardown and kill the process — whichever fires
    # first wins, and the backend call is idempotent.
    _ended = {"done": False}

    async def _close_call_log(status: str = "completed"):
        if _ended["done"]:
            return
        _ended["done"] = True
        await _report("/api/calls/agent-call-end", {"call_id": call_id, "status": status})

    def _on_session_close(ev):
        reason = getattr(ev, "reason", None)
        logger.info(f"Session closed (reason={reason}) — closing call log.")
        _fire(_close_call_log("completed"))

    session.on("close", _on_session_close)
    ctx.add_shutdown_callback(lambda: _close_call_log("completed"))

    await session.start(
        VoxAgent(instructions=system_prompt, clinic_id=clinic_id, did=did,
                 booking_mode=(ctx_data.get("booking_mode") or "time")),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            # Telephony-tuned echo + noise cancellation so the agent doesn't
            # transcribe its own voice.
            noise_cancellation=noise_cancellation.BVCTelephony(),
        ),
    )

    # If the caller goes silent for user_away_timeout seconds, the session marks
    # them "away". The LLM doesn't reliably call end_call on silence, so we say a
    # short closing line and hang up.
    async def _hangup_after_silence():
        try:
            await session.say(
                "लगता है आप अभी व्यस्त हैं। मैं फ़ोन रख रही हूँ, धन्यवाद!",
                allow_interruptions=False,
            )
        except Exception:
            pass
        try:
            await get_job_context().delete_room()
        except Exception:
            pass

    def _on_user_state_changed(ev):
        if getattr(ev, "new_state", None) == "away":
            asyncio.create_task(_hangup_after_silence())

    session.on("user_state_changed", _on_user_state_changed)

    # Ensure the TTS connection warm-up (started above) has finished so the greeting
    # plays right away instead of paying a cold handshake. SKIPPED when the greeting
    # audio is already cached: there is no MiniMax request to make, so waiting up to
    # 3s here would only delay the caller hearing us.
    if not tts_engine.has_cached(greeting):
        try:
            await asyncio.wait_for(_tts_warm, timeout=3.0)
        except Exception:
            pass
    else:
        logger.info("Greeting already cached — skipping TTS warm-up wait.")

    # Speak the opening greeting once connected. Guarded: if the caller hangs up
    # while the session is still starting, session.say raises "AgentSession isn't
    # running". Unguarded that became an UNHANDLED exception which crashed the job
    # (and, with the Windows recycle, killed the worker) on every early hang-up.
    try:
        await session.say(greeting, allow_interruptions=True)
    except Exception as e:
        logger.warning(f"Greeting not played — caller likely disconnected early: {e}")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            # Explicit agent name so a LiveKit SIP dispatch rule can target it.
            # WARNING: this string must match `agent_name` on the LiveKit SIP
            # dispatch rule exactly, or LiveKit has nothing to hand the call to and
            # every inbound call goes unanswered. Changing it means updating the
            # dispatch rule in LiveKit at the same time (see docs/DEPLOYMENT.md).
            # Override per-environment via AGENT_NAME.
            agent_name=os.getenv("AGENT_NAME", "clarivo-inbound"),
            # Keep a job process pre-warmed so an incoming call doesn't wait for a
            # fresh one to spin up (the "no warmed process available" gap before the
            # greeting). Tune via AGENT_IDLE_PROCESSES.
            num_idle_processes=int(os.getenv("AGENT_IDLE_PROCESSES", "1") or "1"),
        )
    )
