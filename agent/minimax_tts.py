"""
Custom LiveKit TTS plugin for MiniMax (speech-02-turbo).

LiveKit has no built-in MiniMax TTS plugin, so we wrap MiniMax's streaming
t2a_v2 endpoint. It streams raw 16-bit PCM which we push straight into LiveKit's
AudioEmitter. This mirrors the backend's stream_minimax_tts_pcm parsing (audio
hex lives at data.audio).
"""

import collections
import hashlib
import json
import logging
import os
import uuid
from pathlib import Path

try:  # stdlib on Python < 3.13; hard-clip fallback amplifier for raw PCM.
    import audioop
except Exception:  # pragma: no cover - audioop removed in 3.13
    audioop = None

try:  # numpy gives a smooth tanh limiter so loud audio stays clean (no clipping).
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

import httpx
from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    APIConnectOptions,
    tts,
)

logger = logging.getLogger("minimax-tts")

# --- Optional TTS audio cache (opt-in via AGENT_TTS_CACHE=1) ----------------
# Fixed, repeated lines (the per-tenant greeting, the silence hang-up line, and
# any short line the model reuses) are identical every call. When enabled, the
# FINAL post-limiter PCM is cached keyed by (text + voice + every synth param)
# and replayed instead of paying MiniMax again (TTS bills per character, so a hit
# costs nothing). OFF by default so it never alters verified call behaviour until
# you flip it on and run a test call. Only short lines are cached — long, unique
# sentences would just churn the cache.
#
# TWO TIERS:
#   1. RAM  — instant, but dies with the process. On Windows the worker is
#             recycled after EVERY call (AGENT_RECYCLE_AFTER_CALL, the LiveKit
#             teardown-panic workaround), so a RAM-only cache never gets a hit
#             across calls — the greeting is always the first line spoken.
#   2. DISK — survives the recycle, so the greeting is paid for ONCE ever instead
#             of once per call. Reading a small file (~5-15ms) is far cheaper than
#             a MiniMax round trip (~500ms), so this also improves latency.
# On Linux with AGENT_RECYCLE_AFTER_CALL=0 both tiers apply (RAM first, disk on a
# cold start / after a deploy).
_TTS_CACHE_ON = os.getenv("AGENT_TTS_CACHE", "0").strip().lower() not in ("", "0", "false", "no", "off")
_TTS_CACHE_MAXCHARS = int(os.getenv("AGENT_TTS_CACHE_MAXCHARS", "160") or "160")
_TTS_CACHE_MAXENTRIES = int(os.getenv("AGENT_TTS_CACHE_MAXENTRIES", "64") or "64")
_TTS_CACHE: "collections.OrderedDict" = collections.OrderedDict()

# Disk tier. Empty AGENT_TTS_CACHE_DIR disables it (RAM-only).
_TTS_CACHE_DIR = os.getenv("AGENT_TTS_CACHE_DIR", str(Path(__file__).resolve().parent / ".tts_cache")).strip()
# Safety cap so the folder can't grow without bound (audio is ~48 KB/second).
_TTS_CACHE_DISK_MB = float(os.getenv("AGENT_TTS_CACHE_DISK_MB", "200") or "200")


def _cache_path(key: tuple) -> "Path | None":
    """Filesystem path for a cache key, or None when the disk tier is disabled.

    The key is hashed (rather than used as a filename) because it contains the
    spoken text, which is Devanagari and can exceed filename limits.
    """
    if not _TTS_CACHE_DIR:
        return None
    digest = hashlib.sha256("\x1f".join(str(p) for p in key).encode("utf-8")).hexdigest()
    return Path(_TTS_CACHE_DIR) / f"{digest}.pcm"


def _disk_read(key: tuple) -> "bytes | None":
    """Load cached PCM from disk. Any failure just means 'miss'."""
    p = _cache_path(key)
    if p is None:
        return None
    try:
        if p.is_file():
            data = p.read_bytes()
            return data or None
    except Exception as e:  # noqa: BLE001 - a cache miss must never break a call
        logger.debug("TTS disk cache read failed: %s", e)
    return None


def _disk_write(key: tuple, pcm: bytes) -> None:
    """Store PCM on disk, then prune the folder if it grew past the size cap.

    Writes to a temp file and renames, so a crash mid-write can never leave a
    truncated file that would later play as clipped audio.
    """
    p = _cache_path(key)
    if p is None or not pcm:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(pcm)
        tmp.replace(p)  # atomic on the same filesystem
        _disk_prune()
    except Exception as e:  # noqa: BLE001 - caching is best-effort
        logger.debug("TTS disk cache write failed: %s", e)


def _disk_prune() -> None:
    """Keep the cache folder under the size cap, deleting least-recently-used first."""
    try:
        d = Path(_TTS_CACHE_DIR)
        files = [(f.stat().st_mtime, f.stat().st_size, f) for f in d.glob("*.pcm")]
        total = sum(s for _, s, _ in files)
        cap = _TTS_CACHE_DISK_MB * 1024 * 1024
        if total <= cap:
            return
        for _mtime, size, f in sorted(files):  # oldest mtime first
            try:
                f.unlink()
                total -= size
            except Exception:  # noqa: BLE001
                pass
            if total <= cap:
                break
    except Exception as e:  # noqa: BLE001
        logger.debug("TTS disk cache prune failed: %s", e)


def _amplify_pcm(pcm: bytes, gain: float) -> bytes:
    """Loudness boost for 16-bit mono PCM using a soft-KNEE limiter.

    Samples below the knee (80% of full scale) are amplified purely linearly and
    left untouched — so the body of the speech stays natural (no "computerized"
    coloration) — while only the loud peaks above the knee are rounded off smoothly
    (no harsh clipping / "cutting"). Falls back to audioop.mul if numpy is missing,
    and returns the input unchanged when gain == 1.0.
    """
    if not gain or gain == 1.0 or not pcm:
        return pcm
    if _np is not None:
        try:
            s = _np.frombuffer(pcm, dtype=_np.int16).astype(_np.float32) * gain
            ceil = 32767.0
            knee = 0.8 * ceil
            a = _np.abs(s)
            over = a > knee
            if bool(over.any()):
                head = ceil - knee
                s = _np.where(
                    over,
                    _np.sign(s) * (knee + head * _np.tanh((a - knee) / head)),
                    s,
                )
            _np.clip(s, -ceil, ceil, out=s)
            return s.astype(_np.int16).tobytes()
        except Exception:
            pass
    if audioop is not None:
        try:
            return audioop.mul(pcm, 2, gain)
        except Exception:
            pass
    return pcm


class MiniMaxTTS(tts.TTS):
    def __init__(
        self,
        *,
        api_key: str,
        group_id: str | None = None,
        base_url: str = "https://api.minimax.io/v1",
        model: str = "speech-02-turbo",
        voice: str = "male-qn-qingse",
        language_boost: str = "Hindi",
        sample_rate: int = 24000,
        volume: float = 1.0,
        speed: float = 1.0,
        gain: float = 1.0,
        emotion: str = "",
        fallback_voice: str = "Calm_Woman",
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=sample_rate,
            num_channels=1,
        )
        if not api_key:
            raise ValueError("MiniMaxTTS requires a MiniMax API key")
        self._api_key = api_key
        self._group_id = group_id
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._voice = voice
        self._language_boost = language_boost
        # MiniMax voice_setting: vol (0,10] louder>1.0; speed 1.0 = normal.
        self._volume = volume
        self._speed = speed
        # Emotional delivery (e.g. "happy"), supported by speech-2.5+/2.8 models.
        # Empty => the field is omitted entirely, so older models are unaffected.
        self._emotion = (emotion or "").strip()
        # Safety net: a tenant can paste ANY voice id in the dashboard (including a
        # mistyped cloned voice id). MiniMax then rejects every synthesis and the
        # caller hears NOTHING for the whole call. If the configured voice fails and
        # produces no audio, we retry once with this known-good voice and stick to it
        # for the rest of the call. Set to "" to disable the fallback.
        self._fallback_voice = (fallback_voice or "").strip()
        # Extra digital gain applied to the decoded PCM AFTER synthesis, so the
        # line is loud enough on telephony even when MiniMax's own vol tops out.
        self._gain = gain
        # One keep-alive HTTP connection reused across sentences — see _client().
        self._http: "httpx.AsyncClient | None" = None

    def cache_key(self, text: str) -> tuple:
        """Cache key for `text` under the CURRENT settings. Covers every parameter
        that changes the audio, so a different voice/emotion/speed can never return
        the wrong clip."""
        return (
            text, self._voice, self._model, self._speed, self._volume,
            float(self._gain or 1.0), self.sample_rate, self._language_boost, self._emotion,
        )

    def has_cached(self, text: str) -> bool:
        """True when `text` is already cached (RAM or disk), so synthesizing it will
        cost nothing and need no warm connection. Lets the caller skip the TTS
        warm-up wait and hear the greeting sooner."""
        if not _TTS_CACHE_ON or not text:
            return False
        key = self.cache_key(text)
        if key in _TTS_CACHE:
            return True
        p = _cache_path(key)
        try:
            return bool(p is not None and p.is_file() and p.stat().st_size > 0)
        except Exception:  # noqa: BLE001
            return False

    def _voice_setting(self, voice: str | None = None) -> dict:
        """The voice_setting payload, built in ONE place so the warm-up and the real
        synthesis can never drift apart. `emotion` is included only when set, since
        it is supported by speech-2.5+/2.8 but not by the older models. Pass `voice`
        to override the configured voice (used by the fallback retry)."""
        vs = {"voice_id": voice or self._voice, "speed": self._speed, "vol": self._volume, "pitch": 0}
        if self._emotion:
            vs["emotion"] = self._emotion
        return vs

    def _client(self) -> httpx.AsyncClient:
        # Reuse one keep-alive connection across sentences. A fresh TLS handshake
        # to MiniMax per sentence costs ~1.4s; reusing it drops first-audio from
        # ~1.9s to ~0.5s on later sentences of the same call.
        if self._http is None or self._http.is_closed:
            # Keep the TLS connection warm for the whole call. httpx's default
            # keepalive_expiry is only 5s, so a caller pause longer than that lets
            # the connection go cold and re-adds the ~1.4s handshake on the next
            # turn. A long expiry keeps first-audio ~0.5s on every turn after the first.
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=1, keepalive_expiry=300.0),
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
        self._http = None
        await super().aclose()

    async def warm_up(self) -> None:
        """Open the HTTP/TLS connection to MiniMax ahead of time so the FIRST real
        synthesis (the call's greeting) doesn't pay the ~1.4s cold handshake. Sends
        a tiny throwaway synth and stops as soon as the first byte arrives; the
        connection stays in the keep-alive pool for the greeting. Best-effort.

        NOTE: named warm_up (not prewarm) on purpose — livekit's TTS base class has
        its own synchronous prewarm() that the framework calls un-awaited; overriding
        it with an async def breaks that call ("coroutine was never awaited")."""
        url = f"{self._base_url}/t2a_v2"
        if self._group_id:
            url += f"?GroupId={self._group_id}"
        payload = {
            "model": self._model,
            "text": "नमस्ते",
            "stream": True,
            "language_boost": self._language_boost,
            "voice_setting": self._voice_setting(),
            "audio_setting": {"sample_rate": self.sample_rate, "bitrate": 128000, "format": "pcm", "channel": 1},
            "stream_options": {"exclude_aggregated_audio": True},
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        try:
            client = self._client()
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                # Fully drain the (tiny) response so httpx returns the connection to
                # its keep-alive pool. Breaking early leaves a half-read response,
                # which makes httpx CLOSE the connection — then the greeting would
                # still pay a cold handshake, defeating the warm-up.
                async for _line in resp.aiter_lines():
                    pass
        except Exception:
            pass

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> "tts.ChunkedStream":
        return _MiniMaxChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class _MiniMaxChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: "tts.AudioEmitter") -> None:
        t: MiniMaxTTS = self._tts  # set by tts.ChunkedStream.__init__

        url = f"{t._base_url}/t2a_v2"
        if t._group_id:
            url += f"?GroupId={t._group_id}"

        payload = {
            "model": t._model,
            "text": self.input_text,
            "stream": True,
            "language_boost": t._language_boost,
            "voice_setting": t._voice_setting(),
            "audio_setting": {
                "sample_rate": t.sample_rate,
                "bitrate": 128000,
                "format": "pcm",
                "channel": 1,
            },
            "stream_options": {"exclude_aggregated_audio": True},
        }
        headers = {"Authorization": f"Bearer {t._api_key}", "Content-Type": "application/json"}

        output_emitter.initialize(
            request_id=uuid.uuid4().hex,
            sample_rate=t.sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
        )

        # Covers the text AND every parameter that affects the audio, so a different
        # voice / speed / gain / emotion can never return the wrong cached clip.
        cache_key = t.cache_key(self.input_text)
        cacheable = _TTS_CACHE_ON and 0 < len(self.input_text) <= _TTS_CACHE_MAXCHARS

        # Cache HIT: replay stored PCM and skip MiniMax entirely (the actual saving).
        # RAM first, then disk — the disk tier is what survives the per-call worker
        # recycle on Windows, so the greeting is synthesized once ever, not per call.
        if cacheable:
            cached = _TTS_CACHE.get(cache_key)
            tier = "ram"
            if cached is not None:
                _TTS_CACHE.move_to_end(cache_key)
            else:
                cached = _disk_read(cache_key)
                if cached is not None:
                    tier = "disk"
                    # Promote into RAM so later turns in this call skip the file read.
                    _TTS_CACHE[cache_key] = cached
                    _TTS_CACHE.move_to_end(cache_key)
                    while len(_TTS_CACHE) > _TTS_CACHE_MAXENTRIES:
                        _TTS_CACHE.popitem(last=False)
            if cached:
                for i in range(0, len(cached), 32000):
                    output_emitter.push(cached[i:i + 32000])
                output_emitter.flush()
                logger.info(
                    "TTS cache hit (%s, %d bytes): %r", tier, len(cached), self.input_text[:40]
                )
                return

        acc = bytearray() if cacheable else None
        client = t._client()

        async def _attempt(voice: str) -> int:
            """Synthesize with `voice`, pushing audio as it streams. Returns the number
            of PCM bytes pushed. Raises on HTTP/transport errors."""
            payload["voice_setting"] = t._voice_setting(voice)
            pushed = 0
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise RuntimeError(f"MiniMax TTS HTTP {resp.status_code}: {body[:200]!r}")
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    try:
                        data_json = json.loads(line[5:].strip())
                    except (ValueError, TypeError):
                        continue
                    # In t2a_v2 the audio hex is nested at data.audio.
                    chunk = data_json.get("data")
                    hex_audio = ""
                    if isinstance(chunk, dict):
                        hex_audio = chunk.get("audio", "") or ""
                    elif isinstance(chunk, str):
                        hex_audio = chunk
                    if hex_audio:
                        pcm = _amplify_pcm(bytes.fromhex(hex_audio), float(t._gain or 1.0))
                        if acc is not None:
                            acc.extend(pcm)
                        output_emitter.push(pcm)
                        pushed += len(pcm)
            return pushed

        # A bad voice id (e.g. a mistyped cloned voice) makes MiniMax fail on EVERY
        # turn, so the caller hears silence for the whole call. Detect that — an error
        # OR a 200 that returned no audio — and retry once with the known-good voice.
        # We only retry when NOTHING was pushed yet, otherwise the caller would hear
        # the first part of the line twice.
        primary = t._voice
        fb = t._fallback_voice
        used_fallback = False
        try:
            pushed = await _attempt(primary)
            err = None
        except Exception as e:  # noqa: BLE001 - retried below, re-raised if no fallback
            pushed, err = 0, e

        if pushed == 0 and fb and primary != fb:
            if acc is not None:
                acc.clear()
            logger.warning(
                "TTS voice %r produced no audio (%s) — falling back to %r for the rest of this call.",
                primary, err or "empty response", fb,
            )
            used_fallback = True
            pushed = await _attempt(fb)
            if pushed:
                # Stick to the good voice so every later turn skips the failing one
                # (each failed attempt would otherwise add latency to every reply).
                t._voice = fb
        elif pushed == 0 and err is not None:
            raise err

        output_emitter.flush()

        # Cache MISS just finished: store the final audio in BOTH tiers + evict LRU.
        # Skipped when the fallback voice was used, because cache_key was built from
        # the ORIGINAL voice — storing fallback audio under it would keep serving the
        # wrong voice even after the configured one starts working again. Later lines
        # in this call are keyed correctly (t._voice is now the fallback) and do cache.
        if acc and not used_fallback:
            audio = bytes(acc)
            _TTS_CACHE[cache_key] = audio
            _TTS_CACHE.move_to_end(cache_key)
            while len(_TTS_CACHE) > _TTS_CACHE_MAXENTRIES:
                _TTS_CACHE.popitem(last=False)
            _disk_write(cache_key, audio)
