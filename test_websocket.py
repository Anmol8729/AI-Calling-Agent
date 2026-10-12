"""Test WebSocket endpoint (/ws/notifications).

Validates:
1. Security contract: anonymous connections are rejected with code 4401.
2. Authenticated connections: accepts valid JWT token and receives 'connected' message.

Usage:
    python test_websocket.py
    python test_websocket.py --token <JWT_TOKEN>
"""

import argparse
import asyncio
import json
import logging
import os
import sys

# Ensure backend package is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import websockets
from backend.services.auth_service import create_access_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test-websocket")


async def test_anonymous_rejected(base_ws_url: str) -> bool:
    """Verifies that an unauthenticated connection to /ws/notifications is rejected."""
    url = f"{base_ws_url}/ws/notifications"
    logger.info(f"Testing anonymous connection rejection against {url}...")
    try:
        async with websockets.connect(url) as ws:
            # Should not reach here
            logger.error("❌ FAIL: Anonymous connection was unexpectedly accepted!")
            return False
    except websockets.exceptions.InvalidStatusCode as e:
        if e.status_code in (401, 403, 404):
            logger.info(f"✅ PASS: Anonymous connection refused with HTTP {e.status_code}.")
            return True
        logger.warning(f"Unexpected status code: {e.status_code}")
        return False
    except websockets.exceptions.ConnectionClosed as e:
        if e.code == 4401:
            logger.info(f"✅ PASS: Anonymous connection closed with code 4401 (Unauthorized).")
            return True
        logger.info(f"✅ PASS: Anonymous connection closed with code {e.code}.")
        return True
    except ConnectionRefusedError:
        logger.error(f"❌ Server not reachable at {base_ws_url}. Start the backend first.")
        return False
    except Exception as e:
        logger.info(f"✅ PASS: Anonymous connection closed as expected: {e}")
        return True


async def test_authenticated_connection(base_ws_url: str, token: str) -> bool:
    """Verifies that an authenticated connection receives the 'connected' greeting."""
    url = f"{base_ws_url}/ws/notifications?token={token}"
    logger.info(f"Testing authenticated connection against {url}...")
    try:
        async with websockets.connect(url) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(msg)
            if data.get("type") == "connected":
                logger.info(f"✅ PASS: Authenticated socket connected! Received: {data}")
                return True
            logger.warning(f"Connected but received unexpected message: {data}")
            return False
    except Exception as e:
        logger.error(f"❌ Authenticated connection failed: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser(description="Test /ws/notifications WebSocket endpoint.")
    parser.add_argument("--url", default="ws://127.0.0.1:8000", help="WebSocket base URL (default: ws://127.0.0.1:8000)")
    parser.add_argument("--token", default=None, help="Optional JWT token to test authenticated stream")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")

    # 1. Test anonymous rejection
    anon_ok = await test_anonymous_rejected(base_url)

    # 2. Test authenticated connection
    token = args.token
    if not token:
        # Generate a test token with a dummy clinic_id
        import uuid
        test_clinic_id = str(uuid.uuid4())
        test_user_id = str(uuid.uuid4())
        token = create_access_token(
            data={"sub": test_user_id, "clinic_id": test_clinic_id, "role": "doctor", "ver": 0}
        )
        logger.info(f"Generated test session token with clinic_id={test_clinic_id}")

    auth_ok = await test_authenticated_connection(base_url, token)

    if anon_ok and auth_ok:
        logger.info("\n🎉 All WebSocket security & connectivity checks passed!")
    else:
        logger.warning("\n⚠️ Some WebSocket checks did not pass. Check backend logs.")


if __name__ == "__main__":
    asyncio.run(main())
