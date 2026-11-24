"""Module 4: FX / remittance true-cost calculator.

You type what a provider's app shows (what you pay in total, what the
recipient gets). This module compares that to a reference exchange rate and
reports the real cost: fee and hidden markup combined.

Reference rate sources (no API keys):
  1. Frankfurter (ECB data). The v1 endpoint is deprecated in favour of v2
     but documented as still working.
  2. ExchangeRate-API open endpoint (fallback). Rate limited, so results are
     cached; its terms require an attribution link when its rates are shown.

Be aware: both publish DAILY reference rates, not live mid-market rates.
Costs computed from them can be off by a few tenths of a percent on a
volatile day, so thresholds are not razor thin and the UI says so.

Why wise.com's comparison API is not used: it requires an auth token, which
can't be shipped safely inside a mobile app.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

CURRENCIES = ["USD", "EUR", "GBP", "SGD", "AUD", "CAD", "JPY", "HKD", "AED", "SAR", "PHP"]

# Cost thresholds, percent of the amount sent. The UN SDG 10.c target is to
# bring remittance costs below 3%.
OK_PCT = 1.5
WARN_PCT = 3.0
SUSPICIOUSLY_GOOD_PCT = -0.5  # better than the reference by more than this

CACHE_TTL = 3600  # seconds; the free ER-API endpoint asks for <= 1 request/hour
_cache: dict[tuple[str, str], tuple[float, "MidRate"]] = {}
_transport: httpx.BaseTransport | None = None  # tests can inject a mock


class RateError(Exception):
    pass


@dataclass
class MidRate:
    base: str
    quote: str
    rate: float
    date: str
    source: str  # "Frankfurter (ECB)" | "ExchangeRate-API"


# ---------- reference rate ----------

def _frankfurter(c: httpx.Client, base: str, quote: str) -> MidRate:
    r = c.get(
        "https://api.frankfurter.dev/v1/latest",
        params={"base": base, "symbols": quote},
    )
    r.raise_for_status()
    j = r.json()
    rate = float(j["rates"][quote])
    if rate <= 0:
        raise ValueError("non-positive rate")
    return MidRate(base, quote, rate, str(j.get("date", "")), "Frankfurter (ECB)")


def _erapi(c: httpx.Client, base: str, quote: str) -> MidRate:
    r = c.get(f"https://open.er-api.com/v6/latest/{base}")
    r.raise_for_status()
    j = r.json()
    if j.get("result") != "success":
        raise ValueError(j.get("error-type", "api error"))
    rate = float(j["rates"][quote])
    if rate <= 0:
        raise ValueError("non-positive rate")
    # "Fri, 21 Nov 2026 00:00:01 +0000" -> "21 Nov 2026"
    stamp = " ".join(str(j.get("time_last_update_utc", "")).split(" ")[1:4])
    return MidRate(base, quote, rate, stamp, "ExchangeRate-API")


def fetch_mid(base: str, quote: str) -> MidRate:
    base, quote = base.upper().strip(), quote.upper().strip()
    if base == quote:
        raise RateError("Pick two different currencies.")

    hit = _cache.get((base, quote))
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]

    errors = []
    with httpx.Client(timeout=8, headers={"user-agent": "Checla/0.1"}, transport=_transport) as c:
        for fn in (_frankfurter, _erapi):
            try:
                mid = fn(c, base, quote)
            except httpx.HTTPStatusError as e:
                errors.append(f"{fn.__name__.strip('_')}: HTTP {e.response.status_code}")
            except httpx.HTTPError as e:
                errors.append(f"{fn.__name__.strip('_')}: {type(e).__name__}")
            except (KeyError, ValueError, TypeError) as e:
                errors.append(f"{fn.__name__.strip('_')}: bad response ({e})")
            else:
                _cache[(base, quote)] = (time.time(), mid)
                return mid
    raise RateError("Couldn't get a reference rate. " + "; ".join(errors))


# ---------- true-cost math ----------

@dataclass
class Quote:
    name: str
    pays: float  # total the sender pays, in the source currency, all fees included
    gets: float  # what the recipient receives, in the target currency
    rate_shown: float | None = None  # the rate the provider advertises, optional


@dataclass
class Result:
    quote: Quote
    effective_rate: float
    ideal_gets: float  # what the reference rate would have given for the same pay amount
    lost_target: float
    lost_source: float
    cost_pct: float  # fee + markup, as a percent of the amount paid
    markup_pct: float | None = None  # how far the advertised rate is below the reference
    implied_fee: float | None = None  # in the source currency
    level: str = "ok"  # ok | warn | bad
    notes: list[str] = field(default_factory=list)


def evaluate(q: Quote, mid: float) -> Result:
    if q.pays <= 0 or q.gets <= 0:
        raise ValueError("Amounts must be greater than zero.")
    if mid <= 0:
        raise ValueError("Reference rate must be positive.")

    ideal = q.pays * mid
    lost_t = ideal - q.gets
    res = Result(
        quote=q,
        effective_rate=q.gets / q.pays,
        ideal_gets=ideal,
        lost_target=lost_t,
        lost_source=lost_t / mid,
        cost_pct=lost_t / ideal * 100,
    )

    if q.rate_shown:
        if q.rate_shown <= 0:
            raise ValueError("Rate shown must be positive.")
        # all-in cost = 1 - (1 - fee_share) * (1 - markup)  =>  split it exactly
        res.markup_pct = (1 - q.rate_shown / mid) * 100
        res.implied_fee = q.pays - q.gets / q.rate_shown
        if res.implied_fee < -0.005 * q.pays:
            res.notes.append("Rate shown and amounts don't add up (implied fee is negative). Re-check the numbers.")
        elif res.implied_fee < 0.005 * q.pays and (res.markup_pct or 0) >= 1:
            res.notes.append("Advertised as low or no fee, but the cost is in the exchange rate.")

    if res.cost_pct <= SUSPICIOUSLY_GOOD_PCT:
        res.level = "warn"
        res.notes.append(
            "Better than the reference rate. The daily reference may be out of date, or a number was mistyped."
        )
    elif res.cost_pct > WARN_PCT:
        res.level = "bad"
    elif res.cost_pct > OK_PCT:
        res.level = "warn"
    return res


def rank(quotes: list[Quote], mid: float) -> list[Result]:
    """Cheapest first."""
    return sorted((evaluate(q, mid) for q in quotes), key=lambda r: r.cost_pct)
