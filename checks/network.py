"""Module 1: Network integrity check.

Compares system DNS answers against DNS-over-HTTPS (DoH) answers and
inspects the TLS certificate issuer for a set of finance domains.
Plain sockets/ssl/HTTPS only, so it runs the same on Android and iOS.
"""
from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass, field

import httpx

DOMAINS = [
    "www.paypal.com",
    "www.gcash.com",
    "www.bdo.com.ph",
    "www.bpi.com.ph",
    "www.binance.com",
    "www.coinbase.com",
]

DOH_URL = "https://cloudflare-dns.com/dns-query"


@dataclass
class DomainResult:
    domain: str
    system_ips: set[str] = field(default_factory=set)
    doh_ips: set[str] = field(default_factory=set)
    issuer: str = ""
    tls_ok: bool = False
    notes: list[str] = field(default_factory=list)
    level: str = "ok"  # ok | warn | bad


def system_resolve(domain: str) -> set[str]:
    try:
        infos = socket.getaddrinfo(domain, 443, socket.AF_INET, socket.SOCK_STREAM)
        return {i[4][0] for i in infos}
    except OSError:
        return set()


def doh_resolve(domain: str) -> set[str]:
    try:
        r = httpx.get(
            DOH_URL,
            params={"name": domain, "type": "A"},
            headers={"accept": "application/dns-json"},
            timeout=6,
        )
        r.raise_for_status()
        return {a["data"] for a in r.json().get("Answer", []) if a.get("type") == 1}
    except Exception:
        return set()


def tls_issuer(domain: str) -> tuple[bool, str]:
    """Full chain validation against the OS trust store; returns issuer org."""
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((domain, 443), timeout=6) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as tls:
                cert = tls.getpeercert()
        issuer = dict(x[0] for x in cert.get("issuer", ()))
        return True, issuer.get("organizationName") or issuer.get("commonName", "unknown")
    except ssl.SSLError as e:
        return False, f"TLS error: {e.reason or e}"
    except OSError as e:
        return False, f"connection failed: {e}"


def check_domain(domain: str) -> DomainResult:
    res = DomainResult(domain=domain)
    res.system_ips = system_resolve(domain)
    res.doh_ips = doh_resolve(domain)
    res.tls_ok, res.issuer = tls_issuer(domain)

    if not res.tls_ok:
        res.level = "bad"
        res.notes.append(f"Certificate check failed ({res.issuer}). Do not log in.")
    if not res.system_ips:
        res.level = "bad" if res.level != "bad" else res.level
        res.notes.append("System DNS returned nothing.")
    elif res.doh_ips and not (res.system_ips & res.doh_ips):
        # CDNs return different IPs by region/resolver, so DNS mismatch alone
        # is only a warning. A mismatch PLUS a TLS problem is the real signal.
        if res.level == "ok":
            res.level = "warn"
        res.notes.append("System DNS and DoH disagree (can be normal for CDNs).")
    if not res.doh_ips:
        res.notes.append("DoH lookup unavailable; DNS comparison skipped.")
    return res


def overall_verdict(results: list[DomainResult]) -> tuple[str, str]:
    bad = [r for r in results if r.level == "bad"]
    warn = [r for r in results if r.level == "warn"]
    if bad:
        return "bad", f"Don't log in here. {len(bad)} domain(s) failed certificate or DNS checks."
    if len(warn) >= 2:
        return "warn", "Suspicious. Several domains resolve differently than expected."
    return "ok", "Looks fine. Certificates validated and DNS is consistent."


def run_all(domains: list[str] | None = None) -> list[DomainResult]:
    return [check_domain(d) for d in (domains or DOMAINS)]
