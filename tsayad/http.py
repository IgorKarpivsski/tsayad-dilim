"""Shared HTTP session with polite retries and a per-host minimum interval (rate limiting)."""
from __future__ import annotations

import time
from urllib.parse import urlparse

import requests

from . import log

L = log.get("http")
_session = requests.Session()
_session.headers["User-Agent"] = "TsayadBot/1.0 (+affiliate automation)"
_last_call: dict[str, float] = {}
MIN_INTERVAL = {"api-sg.aliexpress.com": 0.6, "api.telegram.org": 1.1, "graph.facebook.com": 1.0}


class HttpError(Exception):
    def __init__(self, msg: str, status: int | None = None, body: str = ""):
        super().__init__(msg)
        self.status = status
        self.body = body


def request(method: str, url: str, *, retries: int = 3, timeout: int = 30, **kw) -> requests.Response:
    host = urlparse(url).hostname or ""
    wait = MIN_INTERVAL.get(host, 0)
    delay = 2.0
    for attempt in range(1, retries + 1):
        gap = time.time() - _last_call.get(host, 0)
        if gap < wait:
            time.sleep(wait - gap)
        _last_call[host] = time.time()
        try:
            r = _session.request(method, url, timeout=timeout, **kw)
        except requests.RequestException as e:
            if attempt == retries:
                raise HttpError(f"network error {host}: {e}") from e
            L.warning("network error %s (attempt %d): %s", host, attempt, e)
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == retries:
                return r
            retry_after = r.headers.get("Retry-After")
            try:
                retry_after = float(retry_after) if retry_after else None
            except ValueError:
                retry_after = None
            if r.status_code == 429 and "telegram" in host:
                try:
                    retry_after = r.json().get("parameters", {}).get("retry_after", retry_after)
                except ValueError:
                    pass
            sleep_for = min(float(retry_after or delay), 60)
            L.warning("%s %s -> %s, retry in %.0fs", method, host, r.status_code, sleep_for)
            time.sleep(sleep_for)
            delay *= 2
            continue
        return r
    raise HttpError("unreachable")
