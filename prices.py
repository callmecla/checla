"""Module 3: Multi-exchange price and latency monitor.

Polls public ticker endpoints (no API keys) from several exchanges, times
each request, and compares mid prices against the median.

What it tells you:
  - Latency: round-trip time per exchange. The first sample includes DNS +
    TLS setup; later samples reuse the connection and are more representative.
  - Divergence: how far each exchange's mid price sits from the median.
  - Spread: gap between the highest and lowest exchange.

Caveats worth knowing:
  - Binance quotes USDT, the others quote USD. A gap of ~0.05-0.2% can just
    be the USDT/USD basis, so thresholds are deliberately not tiny.
  - This is polling over HTTPS, so numbers are a few seconds old. It is a
    sanity monitor, not a trading feed. WebSockets would be the upgrade.
"""
from __future__ import annotations

import statistics
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx

ASSETS = ["BTC", "ETH", "SOL"]

_KRAKEN_PAIRS = {"BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD"}


def _binance_url(a: str) -> str:
    return f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={a}USDT"


def _binance_parse(j: dict) -> tuple[float, float]:
    return float(j["bidPrice"]), float(j["askPrice"])


def _coinbase_url(a: str) -> str:
    return f"https://api.exchange.coinbase.com/products/{a}-USD/ticker"


def _coinbase_parse(j: dict) -> tuple[float, float]:
    return float(j["bid"]), float(j["ask"])


def _kraken_url(a: str) -> str:
    return f"https://api.kraken.com/0/public/Ticker?pair={_KRAKEN_PAIRS[a]}"


def _kraken_parse(j: dict) -> tuple[float, float]:
    if j.get("error"):
        raise ValueError(j["error"][0])
    r = next(iter(j["result"].values()))
    return float(r["b"][0]), float(r["a"][0])


def _bitstamp_url(a: str) -> str:
    return f"https://www.bitstamp.net/api/v2/ticker/{a.lower()}usd/"


def _bitstamp_parse(j: dict) -> tuple[float, float]:
    return float(j["bid"]), float(j["ask"])


# name -> (quote currency, url builder, parser)
EXCHANGES = {
    "Binance": ("USDT", _binance_url, _binance_parse),
    "Coinbase": ("USD", _coinbase_url, _coinbase_parse),
    "Kraken": ("USD", _kraken_url, _kraken_parse),
    "Bitstamp": ("USD", _bitstamp_url, _bitstamp_parse),
}


@dataclass
class Quote:
    exchange: str
    quote_ccy: str
    bid: float = 0.0
    ask: float = 0.0
    latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    error: str = ""
    divergence_pct: float = 0.0
    level: str = "ok"  # ok | warn | bad

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def book_spread_pct(self) -> float:
        return (self.ask - self.bid) / self.mid * 100 if self.ok and self.mid else 0.0


@dataclass
class Snapshot:
    asset: str
    quotes: list[Quote]
    median: float = 0.0
    spread_pct: float = 0.0
    level: str = "ok"
    message: str = ""
    notes: list[str] = field(default_factory=list)


def analyze(
    asset: str,
    quotes: list[Quote],
    warn_pct: float = 0.3,
    bad_pct: float = 1.0,
    slow_ms: float = 1500,
) -> Snapshot:
    """Pure function: quotes in, verdict out (easy to test without network)."""
    snap = Snapshot(asset=asset, quotes=quotes)
    live = [q for q in quotes if q.ok]

    for q in quotes:
        if not q.ok:
            q.level = "bad"
        elif q.latency_ms > slow_ms:
            q.level = "warn"

    if not live:
        snap.level = "warn"
        snap.message = "No exchange returned usable data. Check your connection, or run the Network tab."
        return snap

    snap.median = statistics.median(q.mid for q in live)
    for q in live:
        q.divergence_pct = (q.mid - snap.median) / snap.median * 100

    if len(live) < 2:
        snap.level = "warn"
        snap.message = "Only one exchange responded, so nothing to compare."
        return snap

    mids = [q.mid for q in live]
    snap.spread_pct = (max(mids) - min(mids)) / snap.median * 100

    for q in live:
        d = abs(q.divergence_pct)
        if d >= bad_pct:
            q.level = "bad"
        elif d >= warn_pct and q.level == "ok":
            q.level = "warn"

    if snap.spread_pct >= bad_pct:
        snap.level = "bad"
        snap.message = f"Large divergence: {snap.spread_pct:.2f}% between exchanges."
    elif snap.spread_pct >= warn_pct:
        snap.level = "warn"
        snap.message = f"Noticeable divergence: {snap.spread_pct:.2f}% between exchanges."
    else:
        snap.message = f"Prices agree. Spread {snap.spread_pct:.3f}% across {len(live)} exchanges."

    slow = [q.exchange for q in live if q.latency_ms > slow_ms]
    if slow:
        snap.notes.append(f"Slow response (>{slow_ms:.0f} ms): {', '.join(slow)}.")
        if snap.level == "ok":
            snap.level = "warn"
    down = [q.exchange for q in quotes if not q.ok]
    if down:
        snap.notes.append(f"Unreachable: {', '.join(down)}.")
    return snap


class Monitor:
    """Holds one persistent HTTP client per exchange so latency reflects
    request time on a warm connection, not a fresh TLS handshake each poll."""

    def __init__(self, transport: httpx.BaseTransport | None = None, **thresholds):
        self.thresholds = thresholds
        self.clients = {
            name: httpx.Client(
                timeout=5,
                headers={"user-agent": "Checla/0.1"},
                transport=transport,
            )
            for name in EXCHANGES
        }
        self.history = {name: deque(maxlen=10) for name in EXCHANGES}

    def _fetch(self, name: str, asset: str) -> Quote:
        ccy, url_fn, parse = EXCHANGES[name]
        q = Quote(exchange=name, quote_ccy=ccy)
        try:
            t0 = time.perf_counter()
            r = self.clients[name].get(url_fn(asset))
            q.latency_ms = (time.perf_counter() - t0) * 1000
            r.raise_for_status()
            q.bid, q.ask = parse(r.json())
            if q.bid <= 0 or q.ask <= 0:
                raise ValueError("non-positive price")
            self.history[name].append(q.latency_ms)
            q.avg_latency_ms = sum(self.history[name]) / len(self.history[name])
        except httpx.HTTPStatusError as e:
            q.error = f"HTTP {e.response.status_code}"
        except httpx.HTTPError as e:
            q.error = type(e).__name__
        except (KeyError, ValueError, TypeError, StopIteration) as e:
            q.error = f"bad response ({e})"
        return q

    def poll(self, asset: str) -> Snapshot:
        with ThreadPoolExecutor(max_workers=len(EXCHANGES)) as pool:
            quotes = list(pool.map(lambda n: self._fetch(n, asset), EXCHANGES))
        return analyze(asset, quotes, **self.thresholds)

    def close(self) -> None:
        for c in self.clients.values():
            c.close()
