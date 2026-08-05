"""
Subscription plans catalog.

Plans are defined by MONTHLY CALL VOLUME (the product's unit of value):
    Trial   -> 50 calls / month   (default for new sign-ups)
    Starter -> 1,000 calls / month
    Growth  -> 3,000 calls / month
    Scale   -> 5,000 calls / month

Pricing is intentionally decoupled from the call tiers. Set `price_inr` for each
plan when you decide your pricing â€” until then it stays None and the dashboard
shows "Pricing on request". Everything here is editable in one place; no code
elsewhere hard-codes call limits or prices.

Per-tenant override: `tenants.monthly_call_limit` (nullable). When set, it wins
over the plan's default allowance, so you can give any client a custom allowance
(e.g. an enterprise deal for 12,000 calls) without adding a new plan.
"""

from typing import Optional

# The tenant's `subscription` column stores one of these keys. "free" is the
# default assigned at registration and maps to the Trial tier.
PLANS = [
    {
        "key": "free",
        "name": "Trial",
        "monthly_call_limit": 50,
        # Spend control: each DID costs real money (~Rs100 setup + Rs500/month).
        # One is enough to evaluate the product end to end.
        "included_numbers": 1,
        "price_inr": 0,  # free trial
        "description": "Try the AI receptionist with a small monthly allowance.",
    },
    {
        "key": "starter",
        "name": "Starter",
        "monthly_call_limit": 1000,
        "included_numbers": 2,
        "price_inr": None,  # TODO: set your price (INR / month)
        "description": "Up to 1,000 answered calls per month.",
    },
    {
        "key": "growth",
        "name": "Growth",
        "monthly_call_limit": 3000,
        "included_numbers": 5,
        "price_inr": None,  # TODO: set your price (INR / month)
        "description": "Up to 3,000 answered calls per month.",
    },
    {
        "key": "scale",
        "name": "Scale",
        "monthly_call_limit": 5000,
        "included_numbers": 10,
        "price_inr": None,  # TODO: set your price (INR / month)
        "description": "Up to 5,000 answered calls per month.",
    },
]

_PLANS_BY_KEY = {p["key"]: p for p in PLANS}

# Fallback plan when a tenant has an unknown/empty subscription key.
DEFAULT_PLAN_KEY = "free"


def list_plans() -> list:
    """All plans, in display order (used by the Billing page)."""
    return PLANS


def get_plan(key: Optional[str]) -> dict:
    """Return the plan for a subscription key, falling back to the Trial plan."""
    if key and key.strip().lower() in _PLANS_BY_KEY:
        return _PLANS_BY_KEY[key.strip().lower()]
    return _PLANS_BY_KEY[DEFAULT_PLAN_KEY]


def is_valid_plan(key: Optional[str]) -> bool:
    return bool(key) and key.strip().lower() in _PLANS_BY_KEY


def effective_call_limit(subscription_key: Optional[str], override: Optional[int]) -> int:
    """The tenant's monthly call allowance.

    A per-tenant `monthly_call_limit` override (any positive integer) takes
    precedence; otherwise the plan's default allowance is used.
    """
    if override is not None and override > 0:
        return int(override)
    return int(get_plan(subscription_key)["monthly_call_limit"])


def included_numbers(subscription_key: Optional[str], override: Optional[int] = None) -> int:
    """How many phone numbers a plan may claim.

    This is a SPEND control, not a feature flag. Every DID carries a real cost
    (roughly â‚¹100 setup plus â‚¹500/month at the time of writing), and claiming one
    consumes a number from a finite pool that other clients also draw from. Before
    this cap, any account â€” including a free trial â€” could hit `POST
    /phone-numbers/provision` in a loop and run up an unbounded bill.

    Trial gets exactly one so a client can still evaluate the product end to end.
    A per-tenant `number_limit` override lets you agree a bigger allowance for one
    customer without inventing a new plan, mirroring `monthly_call_limit`.
    """
    if override is not None and override > 0:
        return int(override)
    return int(get_plan(subscription_key).get("included_numbers", 1))
