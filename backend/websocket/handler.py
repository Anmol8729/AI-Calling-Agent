"""Real-time WebSocket endpoints.

Only the dashboard notification stream lives here now.

Removed: `/media-stream` (2026-08-05)
------------------------------------
That endpoint was the original call pipeline — Vobiz streamed call audio to it and
it ran STT -> LLM -> TTS in-process. The product moved to
Vobiz -> LiveKit SIP -> the LiveKit agent (`agent/main.py`), which carries the
audio itself, so the route no longer served any real call. Two independent proofs:

  * `call_logs` sat at ZERO rows across many verified live calls even though this
    handler writes a row on its `start` event — so it never received one.
  * The agent has its own TTS (`agent/minimax_tts.py`) and STT (`deepgram.STT`);
    the backend's MiniMax modules were imported by nothing else.

It was also unauthenticated, and a probe against the running server confirmed the
consequences were live, not theoretical: an anonymous WebSocket handshake was
accepted, `?destination=` selected a real tenant, the server synthesised audio
back (billable MiniMax TTS + LLM), and a `call_logs` row was written into a real
clinic — letting anyone inject fake calls into a paying customer's dashboard and
burn through their monthly quota.

Deleted with it, as they had no other callers:
`backend/integrations/minimax/{llm,stt,tts}.py`.

If a provider ever needs a media-stream webhook again, it must ship with a signed,
short-lived token that names the tenant — the same pattern
`backend/services/call_tokens.py` now uses for the agent's endpoints.
"""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.services import events
from backend.services.auth_service import decode_access_token

logger = logging.getLogger("websocket")
router = APIRouter(tags=["Websocket"])


@router.websocket("/ws/notifications")
async def notifications_ws(websocket: WebSocket):
    """Real-time dashboard notifications for one clinic.

    Auth is a `?token=` query param because browsers cannot set an Authorization
    header on a WebSocket. The clinic id comes from the JWT payload, so no DB
    round-trip is needed on connect.

    Note: this trusts the token's `clinic_id` claim without re-reading the user, so
    a session revoked mid-stream (password change, suspension) keeps receiving
    events until it reconnects or the token expires. Acceptable for a
    notifications feed, which carries no data the tenant cannot already see, but it
    should be tightened when session revocation is extended to sockets.
    """
    token = websocket.query_params.get("token", "")
    payload = decode_access_token(token) if token else None
    # A scoped agent token must never open a dashboard stream.
    if payload and payload.get("scope"):
        payload = None
    clinic_id = (payload or {}).get("clinic_id")
    if not payload or not clinic_id:
        await websocket.close(code=4401)  # unauthorized
        return

    await websocket.accept()
    queue = events.subscribe(clinic_id)
    try:
        await websocket.send_json({"type": "connected"})
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                # Keeps the connection alive through proxies and surfaces dead sockets.
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.info(f"Notifications websocket closed: {e}")
    finally:
        events.unsubscribe(clinic_id, queue)
