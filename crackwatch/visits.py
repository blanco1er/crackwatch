"""Anonymous visit log of the hosted demo: did the judges try it, from where, how far did they go?

Kept per event (120 days, DynamoDB TTL): time, event type, an anonymous visitor id (salted hash of
IP + browser, never the IP itself), browser and system families, the referring site's host name,
the interface language, and for demo steps which sample or action it was and the agent's decision.
Never stored: IP address, photo content, file names, e-mail, name, precise location.
The owner's own devices and our test scripts are not logged (header `X-CrackWatch-Visit: internal`,
or the `cw_internal` cookie set once by a private link). Read only by the owner with his AWS profile
(`scripts/visits_report.py`); no public page shows it.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
from urllib.parse import urlparse

TTL_DAYS = 120
EVENT_TYPES = ("view", "sample", "upload", "inspect", "ticket", "card", "lang", "error")


def _secret() -> str:
    return os.environ.get("CW_VISIT_SECRET", "local")


def visitor_id(ip: str = "", ua: str = "") -> str:
    salt = hashlib.sha256(f"crackwatch-visits:{_secret()}".encode()).hexdigest()
    return hashlib.sha256(f"{salt}|{ip}|{ua}".encode()).hexdigest()[:16]


def internal_key() -> str:
    return hashlib.sha256(f"crackwatch-internal-visit:{_secret()}".encode()).hexdigest()[:32]


def ua_family(ua: str = "") -> dict:
    u = ua or ""
    if "Edg/" in u:
        b = "Edge"
    elif "OPR/" in u:
        b = "Opera"
    elif "Firefox/" in u:
        b = "Firefox"
    elif "Chrome/" in u:
        b = "Chrome"
    elif "Safari/" in u:
        b = "Safari"
    elif re.search(r"curl|python|node|bot|crawl|spider|headless|wget|httpie|go-http", u, re.I):
        b = "Bot or script"
    else:
        b = "Other"
    if re.search(r"iPhone|iPad|iOS", u):
        o = "iOS"
    elif "Android" in u:
        o = "Android"
    elif re.search(r"Mac OS X|Macintosh", u):
        o = "macOS"
    elif "Windows" in u:
        o = "Windows"
    elif "Linux" in u:
        o = "Linux"
    else:
        o = "Other"
    return {"browser": b, "os": o, "bot": b == "Bot or script" or "HeadlessChrome" in u}


def ref_host(ref: str = "", own_host: str = "") -> str:
    try:
        h = (urlparse(ref).hostname or "").removeprefix("www.")
    except ValueError:
        return ""
    return h if h and h != own_host else ""


def _cookie(header: str, name: str) -> str:
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return ""


def is_internal(headers: dict) -> bool:
    h = {k.lower(): v for k, v in (headers or {}).items()}
    if (h.get("x-crackwatch-visit") or "").lower() == "internal":
        return True
    return secrets.compare_digest(_cookie(h.get("cookie", ""), "cw_internal"), internal_key())


def _clean(s, n):
    s = re.sub(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", "[email]", str(s))
    s = re.sub(r"\+?(?:\d[\s().-]{0,2}){7,}\d", "[number]", s)
    return re.sub(r"\s+", " ", s).strip()[:n]


def log_visit(store, headers: dict, ip: str, ev: dict, now: float | None = None) -> bool:
    """One event. Returns False when not logged (internal visit, logging off, unknown type)."""
    if store is None or os.environ.get("CW_VISITS") == "off" or is_internal(headers):
        return False
    typ = str(ev.get("type", ""))[:20]
    if typ not in EVENT_TYPES:
        return False
    h = {k.lower(): v for k, v in (headers or {}).items()}
    ua = h.get("user-agent", "")
    fam = ua_family(ua)
    now = now or time.time()
    at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now * 1000) % 1000:03d}Z"
    row = {"at": at, "type": typ, "visitor": visitor_id(ip, ua), **fam,
           "ref": _clean(ev.get("ref"), 80) if ev.get("ref") is not None else ref_host(h.get("referer", ""), h.get("host", ""))}
    for k, n in (("lang", 8), ("sample", 20), ("action", 40), ("planner", 60), ("detail", 80), ("screen", 12), ("utm", 40)):
        if ev.get(k):
            row[k] = _clean(ev[k], n)
    store.put(f"VISIT#{at[:10]}", f"{at}#{row['visitor']}#{secrets.token_hex(2)}", row, ttl_days=TTL_DAYS)
    return True
