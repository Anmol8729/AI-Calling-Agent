"""Make an outbound call via Vobiz Programmable Voice API.

Usage:
    python make_call.py --to +919876543210
    python make_call.py --to +919876543210 --answer-url https://your-server.com/api/calls/twiml/outbound
"""

import argparse
import asyncio
import logging
import os
import sys

# Ensure backend package is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.config.settings import settings
from backend.integrations.vobiz.client import VobizClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("outbound-caller")


async def main():
    parser = argparse.ArgumentParser(description="Trigger an outbound call via Vobiz API.")
    parser.add_argument("--to", required=True, help="Destination phone number in E.164 format (e.g. +919876543210)")
    parser.add_argument("--answer-url", default=None, help="Webhook URL for call answer events (default: SERVER_URL/api/calls/twiml/outbound)")
    parser.add_argument("--hangup-url", default=None, help="Webhook URL for hangup events")
    args = parser.parse_args()

    destination = args.to.strip()
    if not destination.startswith("+") or len(destination) < 8:
        logger.error("Phone number must start with '+' followed by country code and at least 7 digits.")
        sys.exit(1)

    if not (settings.VOBIZ_USERNAME and settings.VOBIZ_PASSWORD and settings.VOBIZ_OUTBOUND_NUMBER):
        logger.error("Vobiz credentials (VOBIZ_USERNAME, VOBIZ_PASSWORD, VOBIZ_OUTBOUND_NUMBER) missing in .env")
        sys.exit(1)

    answer_url = args.answer_url or f"{settings.SERVER_URL.rstrip('/')}/api/calls/twiml/outbound"
    client = VobizClient()

    logger.info(f"Initiating call from {settings.VOBIZ_OUTBOUND_NUMBER} to {destination}...")
    logger.info(f"Answer callback URL: {answer_url}")

    result = await client.initiate_call(
        to_number=destination,
        answer_url=answer_url,
        hangup_url=args.hangup_url,
    )

    if result.get("success"):
        logger.info("Call successfully dispatched via Vobiz.")
        logger.info(f"Response: {result.get('data')}")
    else:
        logger.error(f"Failed to dispatch call: {result.get('error')}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
