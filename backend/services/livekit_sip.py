"""Per-tenant LiveKit SIP inbound trunks.

Clarivo no longer subscribes to phone numbers on its customers' behalf. Each customer
keeps their number with their own operator and forwards it to a SIP trunk that belongs
to them alone. This module is the control plane for those trunks — the first code in
the backend to talk to LiveKit at all.

**Why per-tenant and not one shared trunk.** A shared trunk (what this replaced, and
what still exists by hand for the legacy Vobiz numbers) has exactly one set of
credentials and distinguishes tenants only by the dialed number. That is fine while we
own every number in the pool. The moment customers bring their own it fails twice:
anyone holding the shared credentials could present any number and be answered as that
tenant, and we would have no way to prove a number belongs to whoever typed it in.

Giving each tenant its own trunk fixes both, and the second one for free. The digest
credentials are generated here and shown in exactly one place — that tenant's own
dashboard. So a call that authenticates with them, for a number they have claimed, can
only have been forwarded by whoever controls both. That is what lets
`PhoneNumber.verification_status` be satisfied by the customer's own first test call,
rather than by an SMS OTP this codebase has no provider for.

The other half of that guarantee is not here: the resolution path must reject a call
arriving on tenant A's trunk for a number belonging to tenant B. Per-tenant credentials
authenticate the tenant; only that check stops the tenant claiming someone else's line.

**Failure policy.** Nothing in this module raises. Every function returns a result dict
and the caller decides what to tell the customer. A trunk that cannot be created is a
tenant who sees "still setting this up" — it must never be a 500 on a request that also
recorded their phone number, because then the number is saved and the trunk silently is
not.

**Two operational caveats, both confirmed against the live project.**

A trunk whose `numbers` list is EMPTY means "accept any dialed number" — not "accept
none". The legacy hand-made Vobiz trunk is exactly that shape, so it can match a call for
a number that also belongs to a per-tenant trunk; LiveKit will not even allow a second
such trunk to exist. Two consequences run through this module: a trunk is never created
or left with an empty number list, and `_warn_about_catchall_config` logs when it finds
one. Likewise a dispatch rule with no `trunk_ids` applies to every trunk. Both are fixed
in the LiveKit console by giving the legacy trunk an explicit number list and scoping its
rule to it.

Updates are done as a full `replace_trunk` rather than field-by-field, because the
partial API cannot express an empty list at all — see that function for the detail.
"""

import json
import logging
import secrets
import string

from backend.config.settings import settings

logger = logging.getLogger("livekit-sip")

# Room name prefix for the per-caller rooms LiveKit creates. The agent uses
# `ctx.room.name` as the call id, so this shows up in call logs.
ROOM_PREFIX = "clarivo"

# Username charset kept to lowercase alphanumerics + underscore, and the password to
# plain alphanumerics. These get typed (or pasted) into a telecom operator's trunk
# configuration form, and provider portals are notorious for mangling or rejecting
# punctuation. A shorter charset costs a few bits of entropy; a password the customer
# cannot enter costs a support ticket. 32 alphanumerics is ~190 bits, far past need.
_PW_ALPHABET = string.ascii_letters + string.digits
_PW_LENGTH = 32


def enabled() -> bool:
    """True when the backend holds LiveKit credentials and can manage trunks."""
    return settings.livekit_sip_enabled


def sip_host() -> str:
    """Hostname the customer's operator sends SIP to ("" if not derivable)."""
    return settings.livekit_sip_host


def generate_credentials() -> tuple[str, str]:
    """A fresh (username, password) pair for one tenant's trunk.

    The username is prefixed so it is identifiable in an operator's config and in
    LiveKit's logs, and carries no tenant identifier: it is shown to the customer and
    handed to a third party, so it should not leak our internal clinic id.
    """
    suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(12))
    username = f"clv_{suffix}"
    password = "".join(secrets.choice(_PW_ALPHABET) for _ in range(_PW_LENGTH))
    return username, password


def _result(ok: bool, error: str = "", **extra) -> dict:
    out = {"ok": ok, "error": error}
    out.update(extra)
    return out


def _disabled_result() -> dict:
    return _result(
        False,
        "Phone-number connections aren't fully configured on the server yet. "
        "Your number is saved — support will finish the setup.",
    )


def _api():
    """A LiveKitAPI client, or None when unavailable.

    The import is deferred so that a backend without `livekit-api` installed still
    boots and serves every other route; only trunk management degrades.
    """
    if not enabled():
        return None
    try:
        from livekit import api  # noqa: PLC0415 — deliberate lazy import
    except Exception as e:  # pragma: no cover - import guard
        logger.error(f"livekit-api is not installed, cannot manage SIP trunks: {e}")
        return None
    try:
        return api.LiveKitAPI(
            settings.LIVEKIT_URL,
            settings.LIVEKIT_API_KEY,
            settings.LIVEKIT_API_SECRET,
        )
    except Exception as e:
        logger.error(f"Could not build a LiveKit client: {e}")
        return None


def parse_allowed_addresses(allowed_addresses) -> list:
    """Split the stored comma/newline-separated IP allowlist into a list.

    Public because the route layer normalises the customer's input with the same
    function it will later be sent through — two parsers would eventually disagree
    about whitespace and the stored value would stop matching the live trunk.
    """
    raw = (allowed_addresses or "").replace("\n", ",")
    return [part.strip() for part in raw.split(",") if part.strip()]


def _trunk_name(clinic_name: str) -> str:
    name = (clinic_name or "").strip() or "Clarivo tenant"
    return f"Clarivo — {name}"[:120]


async def _warn_about_catchall_config(lkapi) -> None:
    """Log LiveKit-side config that would compete with per-tenant trunks.

    Best-effort diagnostics only, but both of these are real and neither is visible
    from inside this application:

      * A **trunk with an empty `numbers` list means "any number"**, not "no numbers".
        The legacy hand-made Vobiz trunk is exactly that, so it can match a call for a
        number that also belongs to a per-tenant trunk. When the legacy trunk wins, the
        call arrives without our `clarivo.trunk_id` attribute, the backend falls back to
        resolving by dialed number, and a customer's still-unverified number is refused —
        so the customer's line never comes up and nothing says why.
      * A **dispatch rule with no `trunk_ids` applies to every trunk**, including ours,
        so two rules compete for the same call.

    Both are fixed in the LiveKit console: give the legacy trunk an explicit list
    containing only the numbers Clarivo itself subscribes to, and scope its dispatch rule
    to that trunk.
    """
    try:
        from livekit import api  # noqa: PLC0415

        trunks = await lkapi.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())
        catchall_trunks = [
            t.sip_trunk_id for t in (trunks.items or []) if not list(t.numbers or [])
        ]
        if catchall_trunks:
            logger.warning(
                "LiveKit inbound trunk(s) %s have an EMPTY numbers list, which means "
                "they accept ANY dialed number and can therefore intercept calls meant "
                "for a per-tenant trunk. Give them an explicit numbers list in the "
                "LiveKit console.",
                catchall_trunks,
            )

        rules = await lkapi.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())
        catchall_rules = [
            r.sip_dispatch_rule_id for r in (rules.items or []) if not list(r.trunk_ids or [])
        ]
        if catchall_rules:
            logger.warning(
                "LiveKit dispatch rule(s) %s have no trunk_ids, so they match EVERY "
                "trunk including per-tenant ones. Scope them to the legacy trunk in the "
                "LiveKit console, or inbound calls may be dispatched by the wrong rule.",
                catchall_rules,
            )
    except Exception as e:
        logger.debug(f"Could not inspect existing LiveKit SIP config: {e}")


async def create_trunk(
    *,
    clinic_id,
    clinic_name: str,
    numbers: list,
    auth_username: str,
    auth_password: str,
    allowed_addresses=None,
) -> dict:
    """Create this tenant's inbound trunk and the dispatch rule that feeds the agent.

    Returns {"ok": True, "trunk_id": ..., "dispatch_rule_id": ...} or
    {"ok": False, "error": "<message safe to show the customer>"}.

    If the dispatch rule cannot be created the trunk is deleted again. A trunk with no
    rule accepts the customer's calls and then drops them, which presents to the caller
    as ringing into silence — strictly worse than the trunk not existing, because the
    customer's operator config looks correct.
    """
    if not list(numbers or []):
        # An empty numbers list does NOT mean "accepts nothing" — LiveKit reads it as
        # "accepts ANY dialed number", and it refuses to create a second such trunk while
        # another exists. Creating one here would either fail or turn this tenant's trunk
        # into a catch-all for the whole platform.
        return _result(False, "Connect a phone number before setting up the connection.")

    lkapi = _api()
    if lkapi is None:
        return _disabled_result()

    from livekit import api  # noqa: PLC0415

    trunk_id = ""
    try:
        trunk = await lkapi.sip.create_inbound_trunk(
            api.CreateSIPInboundTrunkRequest(
                trunk=api.SIPInboundTrunkInfo(
                    name=_trunk_name(clinic_name),
                    # Lets a human in the LiveKit console tell whose trunk this is.
                    metadata=json.dumps({"clarivo_clinic_id": str(clinic_id)}),
                    numbers=list(numbers),
                    allowed_addresses=parse_allowed_addresses(allowed_addresses),
                    auth_username=auth_username,
                    auth_password=auth_password,
                )
            )
        )
        trunk_id = trunk.sip_trunk_id

        await _warn_about_catchall_config(lkapi)

        rule = await lkapi.sip.create_dispatch_rule(
            api.CreateSIPDispatchRuleRequest(
                name=_trunk_name(clinic_name),
                trunk_ids=[trunk_id],
                # One room per caller, so concurrent callers to the same business do
                # not land in a shared room. The agent already treats the room name
                # as the call id.
                rule=api.SIPDispatchRule(
                    dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                        room_prefix=ROOM_PREFIX
                    )
                ),
                # Stamped onto the SIP participant. The agent forwards this to
                # /agent-context so tenant resolution does not have to depend on
                # LiveKit's own attribute naming, and never has to trust a clinic id
                # supplied by the agent — the backend maps this opaque trunk id to a
                # tenant itself.
                attributes={"clarivo.trunk_id": trunk_id},
                room_config=api.RoomConfiguration(
                    agents=[api.RoomAgentDispatch(agent_name=settings.LIVEKIT_AGENT_NAME)]
                ),
            )
        )
        logger.info(
            f"Created SIP trunk {trunk_id} + dispatch rule {rule.sip_dispatch_rule_id} "
            f"for clinic {clinic_id} ({len(list(numbers or []))} number(s))"
        )
        return _result(True, trunk_id=trunk_id, dispatch_rule_id=rule.sip_dispatch_rule_id)

    except Exception as e:
        logger.error(f"Could not create SIP trunk for clinic {clinic_id}: {e}")
        if trunk_id:
            try:
                await lkapi.sip.delete_trunk(
                    api.DeleteSIPTrunkRequest(sip_trunk_id=trunk_id)
                )
                logger.info(f"Rolled back orphaned SIP trunk {trunk_id}")
            except Exception as cleanup_error:
                # Worth shouting about: an orphaned trunk answers calls and drops
                # them, and only a human can remove it now.
                logger.error(
                    f"ORPHANED SIP trunk {trunk_id} for clinic {clinic_id} could not be "
                    f"deleted ({cleanup_error}). Remove it in the LiveKit console."
                )
        return _result(False, "Could not set up the phone connection. Please try again.")
    finally:
        await _aclose(lkapi)


async def replace_trunk(
    *,
    trunk_id: str,
    clinic_id,
    clinic_name: str,
    numbers: list,
    auth_username: str,
    auth_password: str,
    allowed_addresses=None,
) -> dict:
    """Push the COMPLETE desired state of an existing trunk. Used for every update.

    A full replace rather than a partial field update, deliberately, after the partial
    API turned out not to be able to express what this feature needs:

      * `update_inbound_trunk_fields` turns a plain `[]` into a `ListUpdate` with none of
        set/add/remove/clear populated, which the server rejects as
        `unsupported list update operation`.
      * Passing `ListUpdate(clear=True)` does not help either — the SDK copies only
        `set`, `add` and `remove` out of it, so `clear` is silently dropped and the
        message is empty again. Both verified against the live API.

    That made clearing the IP allowlist impossible, which broke credential rotation for
    every tenant that had no allowlist — i.e. the default. Since this application is the
    source of truth for the whole trunk anyway, sending the complete state is both
    simpler and free of that class of bug.

    `numbers` must be non-empty: LiveKit reads an empty list as "accept ANY dialed
    number", so an emptied trunk would start catching other tenants' calls. The caller
    deletes the trunk in that case instead.
    """
    if not trunk_id:
        return _result(False, "This tenant has no SIP trunk yet.")
    if not list(numbers or []):
        return _result(False, "A connection needs at least one number.")
    lkapi = _api()
    if lkapi is None:
        return _disabled_result()

    from livekit import api  # noqa: PLC0415

    try:
        await lkapi.sip.update_inbound_trunk(
            trunk_id,
            api.SIPInboundTrunkInfo(
                name=_trunk_name(clinic_name),
                metadata=json.dumps({"clarivo_clinic_id": str(clinic_id)}),
                numbers=list(numbers),
                allowed_addresses=parse_allowed_addresses(allowed_addresses),
                auth_username=auth_username,
                auth_password=auth_password,
            ),
        )
        logger.info(
            f"Updated SIP trunk {trunk_id}: {len(list(numbers))} number(s), "
            f"{len(parse_allowed_addresses(allowed_addresses))} allowed address(es)"
        )
        return _result(True)
    except Exception as e:
        logger.error(f"Could not update SIP trunk {trunk_id}: {e}")
        return _result(False, "Could not update the phone connection. Please try again.")
    finally:
        await _aclose(lkapi)


async def delete_trunk(*, trunk_id: str, dispatch_rule_id: str = "") -> dict:
    """Remove a tenant's trunk and its dispatch rule.

    The rule goes first: deleting the trunk while a rule still references it leaves a
    rule pointing at nothing, which is harmless but accumulates. Both steps are
    independently tolerant of an already-deleted object, because this is also the
    cleanup path after a partial failure.
    """
    lkapi = _api()
    if lkapi is None:
        return _disabled_result()

    from livekit import api  # noqa: PLC0415

    errors = []
    try:
        if dispatch_rule_id:
            try:
                await lkapi.sip.delete_dispatch_rule(
                    api.DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=dispatch_rule_id)
                )
            except Exception as e:
                errors.append(f"dispatch rule {dispatch_rule_id}: {e}")
        if trunk_id:
            try:
                await lkapi.sip.delete_trunk(
                    api.DeleteSIPTrunkRequest(sip_trunk_id=trunk_id)
                )
            except Exception as e:
                errors.append(f"trunk {trunk_id}: {e}")
        if errors:
            logger.error("Could not fully delete SIP resources: %s", "; ".join(errors))
            return _result(False, "Could not fully remove the phone connection.")
        logger.info(f"Deleted SIP trunk {trunk_id} and dispatch rule {dispatch_rule_id or '-'}")
        return _result(True)
    finally:
        await _aclose(lkapi)


async def _aclose(lkapi) -> None:
    """Close the client's HTTP session. Never raises."""
    try:
        await lkapi.aclose()
    except Exception as e:  # pragma: no cover
        logger.debug(f"LiveKit client close failed: {e}")
