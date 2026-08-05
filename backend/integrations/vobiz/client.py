import logging
from html import escape
from typing import Optional

import httpx

from backend.config.settings import settings

logger = logging.getLogger("vobiz-client")

class VobizClient:
    def __init__(self):
        self.auth_id = settings.VOBIZ_USERNAME
        self.auth_token = settings.VOBIZ_PASSWORD
        self.sip_domain = settings.VOBIZ_SIP_DOMAIN
        self.from_number = settings.VOBIZ_OUTBOUND_NUMBER
        self.base_url = f"https://api.vobiz.ai/api/v1/Account/{self.auth_id}/Call/"

    async def initiate_call(self, to_number: str, answer_url: str, hangup_url: Optional[str] = None) -> dict:
        """
        Triggers an outbound call via Vobiz Programmable Voice API.
        """
        headers = {
            "Content-Type": "application/json",
            "X-Auth-ID": self.auth_id,
            "X-Auth-Token": self.auth_token
        }
        
        payload = {
            "from": self.from_number,
            "to": to_number,
            "answer_url": answer_url,
            "answer_method": "POST"
        }
        if hangup_url:
            payload["hangup_url"] = hangup_url
            
        logger.info(f"Initiating Vobiz outbound call to {to_number} via API URL: {self.base_url}")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(self.base_url, headers=headers, json=payload)
                if response.status_code in [200, 201]:
                    logger.info(f"Vobiz outbound call successful: {response.json()}")
                    return {"success": True, "data": response.json()}
                else:
                    logger.error(f"Vobiz API call failed: {response.status_code} - {response.text}")
                    return {"success": False, "error": response.text}
            except Exception as e:
                logger.error(f"Error calling Vobiz API: {e}")
                return {"success": False, "error": str(e)}

    @staticmethod
    def get_stream_xml(ws_url: str) -> str:
        """Generate Vobiz XML that redirects call media to our WebSocket server.

        `ws_url` embeds the dialed/caller numbers, which arrive from the PUBLIC,
        unauthenticated /api/calls/twiml/inbound webhook. Interpolating them raw
        allowed XML injection: a request with
            to=</Stream><Say>..</Say><Dial>+91..</Dial><Stream>
        produced a response containing those verbs as real markup, letting an
        unauthenticated caller inject <Dial> (toll fraud) or <Say> into the
        call plan. An unescaped bare `&` also made the document malformed.
        Escaping the value fixes both.
        """
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream bidirectional="true" keepCallAlive="true" contentType="audio/x-l16;rate=8000">
        {escape(ws_url, quote=False)}
    </Stream>
</Response>
"""

    @staticmethod
    def get_hangup_xml() -> str:
        """
        Generate Vobiz XML to hang up the call.
        """
        return """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Goodbye and thank you.</Say>
    <Hangup />
</Response>
"""


class VobizNumbersAPI:
    """Vobiz REST API for number (DID) provisioning.

    Uses the dashboard's Auth ID / Auth Token with HTTP Basic auth — these are
    SEPARATE from the SIP trunk username/password used by VobizClient above.

    Vobiz does not auto-route newly purchased numbers: a number must be assigned
    to an inbound trunk, and that trunk's destination is our LiveKit SIP URI. One
    trunk serves every number, so provisioning is just "assign this DID to our
    trunk" — after which all inbound calls for it reach the voice agent.
    """

    def __init__(self):
        self.auth_id = settings.VOBIZ_AUTH_ID
        self.auth_token = settings.VOBIZ_AUTH_TOKEN
        self.trunk_group_id = settings.VOBIZ_TRUNK_GROUP_ID
        self.base_url = f"https://api.vobiz.ai/api/v1/Account/{self.auth_id}"

    @property
    def enabled(self) -> bool:
        return settings.number_provisioning_enabled

    def _auth(self):
        return (self.auth_id, self.auth_token)

    async def list_numbers(self) -> dict:
        """All numbers in the Vobiz account inventory.

        Returns {"success": bool, "numbers": [...]} where each number includes
        e164, status, capabilities and trunk_group_id (empty when unrouted).
        """
        url = f"{self.base_url}/numbers"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, auth=self._auth(), headers={"Content-Type": "application/json"})
            if resp.status_code != 200:
                logger.error(f"Vobiz list numbers failed: {resp.status_code} - {resp.text[:300]}")
                return {"success": False, "error": f"Vobiz returned {resp.status_code}", "numbers": []}
            data = resp.json() or {}
            return {"success": True, "numbers": data.get("items") or data.get("objects") or []}
        except Exception as e:
            logger.error(f"Vobiz list numbers error: {e}")
            return {"success": False, "error": str(e), "numbers": []}

    async def assign_to_trunk(self, e164: str) -> dict:
        """Point a number's inbound calls at our trunk (and so at LiveKit).

        PATCH /numbers/{number}/assign with {"trunk_group_id": ...}
        """
        url = f"{self.base_url}/numbers/{e164}/assign"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.patch(
                    url,
                    auth=self._auth(),
                    headers={"Content-Type": "application/json"},
                    json={"trunk_group_id": self.trunk_group_id},
                )
            if resp.status_code not in (200, 201, 202, 204):
                logger.error(f"Vobiz assign {e164} failed: {resp.status_code} - {resp.text[:300]}")
                return {"success": False, "error": f"Vobiz returned {resp.status_code}"}
            logger.info(f"Vobiz number {e164} assigned to trunk {self.trunk_group_id}")
            return {"success": True}
        except Exception as e:
            logger.error(f"Vobiz assign error for {e164}: {e}")
            return {"success": False, "error": str(e)}
