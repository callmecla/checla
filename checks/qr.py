"""Module 2: QR payment inspector.

Handles two kinds of QR content:
  1. EMVCo merchant-presented payloads (QR Ph, PromptPay, QRIS, etc.):
     tag-length-value parsing, CRC16 validation, plain-language fields.
  2. URLs: structural red flags plus a manual redirect-chain walk.

A valid CRC only proves the QR wasn't corrupted. Scammers can generate
perfectly valid QRs that pay THEIR account, so the real check is that the
merchant name shown here matches who you think you're paying.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

CURRENCIES = {
    "608": "PHP", "840": "USD", "360": "IDR", "702": "SGD",
    "764": "THB", "458": "MYR", "704": "VND", "156": "CNY",
}
SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd",
    "cutt.ly", "rebrand.ly", "shorturl.at", "tiny.cc",
}


@dataclass
class Finding:
    level: str  # ok | warn | bad
    text: str


@dataclass
class QRResult:
    kind: str  # payment | url | text
    fields: dict[str, str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    hops: list[str] = field(default_factory=list)

    @property
    def level(self) -> str:
        levels = {f.level for f in self.findings}
        if "bad" in levels:
            return "bad"
        if "warn" in levels:
            return "warn"
        return "ok"


# ---------- EMVCo parsing ----------

def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def parse_tlv(s: str) -> list[tuple[str, str]]:
    out, i = [], 0
    while i < len(s):
        if i + 4 > len(s):
            raise ValueError("truncated tag header")
        tag, length = s[i:i + 2], s[i + 2:i + 4]
        if not length.isdigit():
            raise ValueError(f"bad length at tag {tag}")
        end = i + 4 + int(length)
        if end > len(s):
            raise ValueError(f"tag {tag} runs past end of payload")
        out.append((tag, s[i + 4:end]))
        i = end
    return out


def analyze_emv(payload: str) -> QRResult:
    res = QRResult(kind="payment")
    try:
        tags = parse_tlv(payload)
    except ValueError as e:
        res.findings.append(Finding("bad", f"Malformed payment QR: {e}."))
        return res
    t = dict(tags)

    # CRC: tag 63 must be last; covers everything up to and including "6304".
    if not tags or tags[-1][0] != "63" or len(tags[-1][1]) != 4:
        res.findings.append(Finding("bad", "Missing or misplaced checksum (tag 63)."))
    else:
        expected = f"{crc16_ccitt(payload[:-4].encode()):04X}"
        if expected != tags[-1][1].upper():
            res.findings.append(Finding("bad", "Checksum is invalid. This QR was altered or is corrupted."))
        else:
            res.findings.append(Finding("ok", "Checksum valid (QR is intact)."))

    # Initiation method
    method = t.get("01")
    if method == "11":
        res.fields["Type"] = "Static (reusable)"
    elif method == "12":
        res.fields["Type"] = "Dynamic (one-time)"
    else:
        res.fields["Type"] = "Unknown"
        res.findings.append(Finding("warn", "Unknown QR type (tag 01)."))

    # Merchant account info: tags 26-51, nested
    networks = []
    for tag, val in tags:
        if tag.isdigit() and 26 <= int(tag) <= 51:
            try:
                sub = dict(parse_tlv(val))
            except ValueError:
                res.findings.append(Finding("warn", f"Could not read account block {tag}."))
                continue
            guid = sub.get("00", "unknown")
            ident = sub.get("01", "")
            networks.append(f"{guid}" + (f" ({ident})" if ident else ""))
    if networks:
        res.fields["Pays via"] = "; ".join(networks)
    else:
        res.findings.append(Finding("bad", "No merchant account information found."))

    # Merchant identity
    name = t.get("59", "").strip()
    if name:
        res.fields["Merchant"] = name
    else:
        res.findings.append(Finding("warn", "No merchant name in the QR."))
    if t.get("60"):
        res.fields["City"] = t["60"]
    if t.get("58"):
        res.fields["Country"] = t["58"]
    if t.get("52"):
        res.fields["Category code"] = t["52"]

    # Currency and amount
    cur = CURRENCIES.get(t.get("53", ""), t.get("53", "?"))
    res.fields["Currency"] = cur
    if t.get("54"):
        res.fields["Amount"] = f"{t['54']} {cur}"
    elif method == "12":
        res.findings.append(Finding("warn", "Dynamic QR with no amount is unusual."))
    else:
        res.fields["Amount"] = "Not set (you type it in)"

    res.findings.append(
        Finding("warn", "Confirm the merchant name matches who you are paying. "
                        "A valid QR can still point to a scammer's account.")
    )
    return res


# ---------- URL analysis ----------

def _host_flags(url: str, res: QRResult, label: str = "") -> None:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    pre = f"{label}: " if label else ""
    if p.scheme != "https":
        res.findings.append(Finding("warn", f"{pre}not using HTTPS."))
    if "@" in (p.netloc or ""):
        res.findings.append(Finding("bad", f"{pre}contains a '@' that disguises the real host."))
    try:
        ipaddress.ip_address(host)
        res.findings.append(Finding("warn", f"{pre}points to a raw IP address instead of a domain."))
    except ValueError:
        pass
    if "xn--" in host:
        res.findings.append(Finding("warn", f"{pre}punycode domain (can imitate lookalike characters)."))
    if host in SHORTENERS:
        res.findings.append(Finding("warn", f"{pre}link shortener hides the real destination."))


def follow_chain(url: str, max_hops: int = 6) -> list[str]:
    """Walk redirects manually, never reading the page body."""
    hops = [url]
    with httpx.Client(timeout=6, follow_redirects=False) as c:
        for _ in range(max_hops):
            try:
                with c.stream("GET", hops[-1], headers={"user-agent": "Checla/0.1"}) as r:
                    loc = r.headers.get("location")
                    if r.status_code in (301, 302, 303, 307, 308) and loc:
                        hops.append(urljoin(hops[-1], loc))
                        continue
            except httpx.HTTPError:
                hops.append("(connection failed)")
            break
    return hops


def analyze_url(url: str) -> QRResult:
    res = QRResult(kind="url", fields={"URL": url})
    _host_flags(url, res)
    res.hops = follow_chain(url)
    if res.hops[-1] == "(connection failed)":
        res.findings.append(Finding("warn", "Could not reach the link to follow redirects."))
        return res
    if len(res.hops) > 1:
        first, last = urlparse(res.hops[0]).hostname, urlparse(res.hops[-1]).hostname
        res.fields["Final destination"] = res.hops[-1]
        if first != last:
            res.findings.append(Finding("warn", f"Redirects from {first} to a different site: {last}."))
        _host_flags(res.hops[-1], res, "Final destination")
        if len(res.hops) > 4:
            res.findings.append(Finding("warn", "Long redirect chain."))
    if res.level == "ok":
        res.findings.append(Finding("ok", "No structural red flags found."))
    return res


# ---------- entry point ----------

def analyze(text: str) -> QRResult:
    text = text.strip()
    if text.lower().startswith(("http://", "https://")):
        return analyze_url(text)
    if text.startswith("000201"):
        return analyze_emv(text)
    res = QRResult(kind="text", fields={"Content": text[:200]})
    res.findings.append(Finding("warn", "Not a payment QR or a web link."))
    return res
