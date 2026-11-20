"""Facebook Page, Instagram (Graph API) and TikTok (Content Posting API) publishers.
Official APIs only. Every function returns a dict with an honest 'status':
  published – the platform returned a post id
  draft     – uploaded to the creator inbox/drafts; a human must press publish
  pending   – not connected
  failed    – error (kept for retry)"""
from __future__ import annotations

import time
from pathlib import Path

from . import config, db, http, log

L = log.get("social")
GRAPH = f"https://graph.facebook.com/{config.GRAPH_VERSION}"


def _daily_count(platform: str) -> int:
    return db.one("SELECT COUNT(*) n FROM posts WHERE platform=? AND status IN ('published','draft') "
                  "AND created_at >= datetime('now','-1 day')", (platform,))["n"]


# ------------------------------------------------------------------ Facebook Page
def facebook_photo(photo: Path, message: str) -> dict:
    if not (config.FB_PAGE_ID and config.FB_PAGE_TOKEN):
        return {"status": "pending", "error": "Facebook not connected"}
    if _daily_count("facebook") >= int(config.S.get("publishing.facebook_daily_cap", 12)):
        return {"status": "skipped", "error": "daily cap"}
    with open(photo, "rb") as fh:
        r = http.request("POST", f"{GRAPH}/{config.FB_PAGE_ID}/photos",
                         data={"message": message, "access_token": config.FB_PAGE_TOKEN, "published": "true"},
                         files={"source": fh}, timeout=90)
    js = r.json() if r.content else {}
    if r.status_code == 200 and (js.get("post_id") or js.get("id")):
        return {"status": "published", "external_id": js.get("post_id") or js.get("id")}
    return {"status": "failed", "error": str(js.get("error", js))[:400]}


def facebook_followers() -> int | None:
    if not (config.FB_PAGE_ID and config.FB_PAGE_TOKEN):
        return None
    r = http.request("GET", f"{GRAPH}/{config.FB_PAGE_ID}",
                     params={"fields": "followers_count,fan_count", "access_token": config.FB_PAGE_TOKEN})
    js = r.json()
    return js.get("followers_count") or js.get("fan_count")


# ------------------------------------------------------------------ Instagram
def _ig_wait(container: str, timeout_s: int = 240) -> str:
    end = time.time() + timeout_s
    status = "IN_PROGRESS"
    while time.time() < end:
        r = http.request("GET", f"{GRAPH}/{container}", params={"fields": "status_code", "access_token": config.FB_PAGE_TOKEN})
        status = r.json().get("status_code", "ERROR")
        if status in ("FINISHED", "ERROR", "EXPIRED"):
            return status
        time.sleep(8)
    return status


def instagram(media_url: str, caption: str, is_video: bool = False) -> dict:
    """media_url must be publicly reachable (our Cloudflare Pages site hosts it)."""
    if not (config.IG_USER_ID and config.FB_PAGE_TOKEN):
        return {"status": "pending", "error": "Instagram not connected"}
    if _daily_count("instagram") >= int(config.S.get("publishing.instagram_daily_cap", 20)):
        return {"status": "skipped", "error": "daily cap (Meta limit is per 24h)"}
    payload = {"caption": caption[:2200], "access_token": config.FB_PAGE_TOKEN}
    if is_video:
        payload.update(media_type="REELS", video_url=media_url, share_to_feed="true")
    else:
        payload["image_url"] = media_url
    r = http.request("POST", f"{GRAPH}/{config.IG_USER_ID}/media", data=payload)
    js = r.json()
    cid = js.get("id")
    if not cid:
        return {"status": "failed", "error": str(js.get("error", js))[:400]}
    st = _ig_wait(cid) if is_video else "FINISHED"
    if st != "FINISHED":
        return {"status": "failed", "error": f"container status {st}"}
    r = http.request("POST", f"{GRAPH}/{config.IG_USER_ID}/media_publish",
                     data={"creation_id": cid, "access_token": config.FB_PAGE_TOKEN})
    js = r.json()
    if js.get("id"):
        return {"status": "published", "external_id": js["id"]}
    return {"status": "failed", "error": str(js.get("error", js))[:400]}


def instagram_followers() -> int | None:
    if not (config.IG_USER_ID and config.FB_PAGE_TOKEN):
        return None
    r = http.request("GET", f"{GRAPH}/{config.IG_USER_ID}", params={"fields": "followers_count", "access_token": config.FB_PAGE_TOKEN})
    return r.json().get("followers_count")


# ------------------------------------------------------------------ TikTok
TT = "https://open.tiktokapis.com"


def _tiktok_token() -> str | None:
    """Access tokens live 24h; refresh tokens ~1 year. The newest refresh token is stored encrypted in the DB."""
    cached = db.kv_get("tiktok_token", {})
    if cached.get("access_token") and cached.get("expires_at", 0) > time.time() + 300:
        return cached["access_token"]
    refresh = cached.get("refresh_token") or config.TIKTOK_REFRESH_TOKEN
    if not (config.TIKTOK_CLIENT_KEY and config.TIKTOK_CLIENT_SECRET and refresh):
        return None
    r = http.request("POST", f"{TT}/v2/oauth/token/", data={
        "client_key": config.TIKTOK_CLIENT_KEY, "client_secret": config.TIKTOK_CLIENT_SECRET,
        "grant_type": "refresh_token", "refresh_token": refresh},
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    js = r.json()
    if not js.get("access_token"):
        db.alert("action", f"TikTok: חידוש הטוקן נכשל – יש לחבר מחדש ({js.get('error_description') or js.get('error')})")
        return None
    db.kv_set("tiktok_token", {"access_token": js["access_token"], "refresh_token": js.get("refresh_token", refresh),
                               "expires_at": time.time() + int(js.get("expires_in", 86400))})
    return js["access_token"]


def tiktok_draft(video: Path, caption: str) -> dict:
    """Uploads to the creator's TikTok inbox as a DRAFT (Upload API, scope video.upload).
    Direct public posting requires TikTok's app audit – until then posts would be private only.
    The owner opens TikTok → notification → adds a trending sound → Post."""
    token = _tiktok_token()
    if not token:
        return {"status": "pending", "error": "TikTok not connected"}
    size = video.stat().st_size
    r = http.request("POST", f"{TT}/v2/post/publish/inbox/video/init/",
                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
                     json={"source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}})
    js = r.json()
    data = js.get("data", {})
    if not data.get("upload_url"):
        return {"status": "failed", "error": str(js.get("error", js))[:400]}
    with open(video, "rb") as fh:
        up = http.request("PUT", data["upload_url"], data=fh.read(), timeout=180, headers={
            "Content-Type": "video/mp4", "Content-Range": f"bytes 0-{size - 1}/{size}", "Content-Length": str(size)})
    if up.status_code not in (200, 201):
        return {"status": "failed", "error": f"upload HTTP {up.status_code}"}
    db.alert("action", f"TikTok: טיוטה חדשה מחכה לך באפליקציה. כיתוב מוצע:\n{caption}")
    return {"status": "draft", "external_id": data.get("publish_id")}
