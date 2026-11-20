"""Optional click tracking via a Cloudflare Worker (/go/...). Links are HMAC-signed so the
worker is never an open redirect. If the tracker isn't configured, the raw affiliate link is used."""
from __future__ import annotations

import base64
import hashlib
import hmac
from urllib.parse import urlencode

from . import config


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def sig(payload: str, secret: str | None = None) -> str:
    return hmac.new((secret or config.TRACKER_SECRET).encode(), payload.encode(), hashlib.sha256).hexdigest()[:20]


def link(affiliate_link: str, product_id: str, source: str, post_id: int | str = 0, variant: str = "") -> str:
    if not (config.TRACKER_URL and config.TRACKER_SECRET):
        return affiliate_link
    u = _b64(affiliate_link)
    payload = f"{product_id}|{source}|{post_id}|{variant}|{u}"
    qs = urlencode({"s": source, "p": post_id, "v": variant, "u": u, "k": sig(payload)})
    return f"{config.TRACKER_URL}/go/{product_id}?{qs}"
