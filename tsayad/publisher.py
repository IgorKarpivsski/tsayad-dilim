"""Queue → verify → create content/media → publish → record. Idempotent and safe to re-run."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, content, db, discovery, log, media, social, telegram, tracking

L = log.get("publisher")
IL = ZoneInfo(config.TIMEZONE)
MEDIA_DIR = config.OUT_DIR / "site" / "media"


def platforms() -> dict:
    return config.S.get("publishing.platforms", {"telegram": True})


def is_due(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if now.astimezone(IL).hour in (config.QUIET_HOURS or []):
        return False
    last = db.kv_get("last_tg_post")
    if not last:
        return True
    # cron may fire late; tolerate 15 min so we never drift beyond the 2h target
    return now - datetime.fromisoformat(last) >= timedelta(minutes=config.POST_INTERVAL_MIN - 15)


def next_post_time() -> str | None:
    last = db.kv_get("last_tg_post")
    if not last:
        return None
    return (datetime.fromisoformat(last) + timedelta(minutes=config.POST_INTERVAL_MIN)).astimezone(IL).strftime("%d/%m %H:%M")


def _acquire_lock() -> bool:
    lock = db.kv_get("publish_lock")
    if lock and datetime.now(timezone.utc) - datetime.fromisoformat(lock) < timedelta(minutes=20):
        return False
    db.kv_set("publish_lock", db.now_iso())
    return True


def _release_lock() -> None:
    db.kv_set("publish_lock", None)


def pick_candidate() -> dict | None:
    recent_cats = [r["category"] for r in db.q(
        "SELECT p.category FROM posts s JOIN products p ON p.id=s.product_id WHERE s.platform='telegram' "
        "AND s.status='published' ORDER BY s.id DESC LIMIT 2")]
    rows = db.q("SELECT * FROM products WHERE status='queued' AND link_ok=1 ORDER BY score DESC LIMIT 30")
    for r in rows:
        if r["category"] not in recent_cats:
            return dict(r)
    return dict(rows[0]) if rows else None


def _verify(p: dict) -> tuple[dict | None, str | None]:
    fresh = discovery.refresh_price(p["id"])
    if fresh is None:
        checked = p.get("price_checked_at")
        if checked and datetime.now(timezone.utc) - datetime.fromisoformat(checked) < timedelta(hours=26):
            return p, None  # detail API unavailable – data from today's scan is still recent
        return None, "לא ניתן לאמת מחיר עדכני"
    if not fresh.get("price"):
        return None, "המוצר לא זמין"
    keep = ("category", "affiliate_link", "id")
    merged = {**p, **{k: v for k, v in fresh.items() if v not in (None, "", []) and k not in keep}}
    merged["affiliate_link"] = p["affiliate_link"]  # keep the link generated with our tracking id
    from . import scoring
    reason = scoring.hard_filters({**merged, "id": "__check__"})  # skip repost check
    return (None, reason) if reason else (merged, None)


def _reject(pid: str, reason: str) -> None:
    with db.tx() as c:
        c.execute("UPDATE products SET status='rejected', reject_reason=? WHERE id=?", (reason, pid))


def publish_one(force: bool = False) -> dict:
    if not force and not is_due():
        return {"status": "not_due", "next": next_post_time()}
    if not (config.TG_BOT_TOKEN and config.TG_CHANNEL_ID):
        return {"status": "pending", "error": "Telegram not connected"}
    if not _acquire_lock():
        return {"status": "locked"}
    try:
        for _ in range(6):  # try a few candidates; never publish a bad one just to hit the quota
            cand = pick_candidate()
            if not cand:
                db.alert("warning", "התור ריק – אין מוצר איכותי לפרסום כרגע (לא מפרסמים מוצר חלש רק כדי לעמוד במכסה).")
                return {"status": "empty_queue"}
            p, reason = _verify(cand)
            if not p:
                _reject(cand["id"], reason or "אימות נכשל")
                continue
            res = _publish(p)
            if res["status"] != "skipped":  # failures are retried on the NEXT run, not hammered now
                return res
        return {"status": "no_valid_candidate"}
    finally:
        _release_lock()


def _publish(p: dict) -> dict:
    style = content.pick_style()
    with db.tx() as c:
        cur = c.execute("INSERT INTO posts(product_id,platform,style,status,hour,created_at) VALUES(?,?,?,?,?,?)",
                        (p["id"], "telegram", style, "pending", datetime.now(IL).hour, db.now_iso()))
        post_id = cur.lastrowid
    link = tracking.link(p["affiliate_link"], p["id"], "tg", post_id, style)
    txt = content.build({**p, "category_slug": p.get("category")}, style, link)
    files = media.make_all(p, txt["headline"], MEDIA_DIR)
    if not files:
        _reject(p["id"], "תמונת מוצר לא זמינה")
        with db.tx() as c:
            c.execute("UPDATE posts SET status='skipped', error='no image' WHERE id=?", (post_id,))
        return {"status": "skipped"}
    try:
        mid = telegram.send_product(files["square"], txt["telegram"], link)
    except Exception as e:  # noqa: BLE001
        with db.tx() as c:
            c.execute("UPDATE posts SET status='failed', error=?, attempts=attempts+1, caption=? WHERE id=?",
                      (str(e)[:400], txt["telegram"], post_id))
        fails = db.one("SELECT COUNT(*) n FROM posts WHERE product_id=? AND status='failed'", (p["id"],))["n"]
        db.alert("error", f"פרסום לטלגרם נכשל ({fails}/3): {e}")
        if fails >= 3:
            _reject(p["id"], "פרסום נכשל 3 פעמים")
        return {"status": "failed_final" if fails >= 3 else "failed", "error": str(e)}
    now = db.now_iso()
    with db.tx() as c:
        c.execute("UPDATE posts SET status='published', external_id=?, caption=?, published_at=? WHERE id=?",
                  (str(mid), txt["telegram"], now, post_id))
        c.execute("UPDATE products SET status='published', published_at=? WHERE id=?", (now, p["id"]))
    db.kv_set("last_tg_post", now)
    fb_link = tracking.link(p["affiliate_link"], p["id"], "fb", post_id, style)
    txt["facebook"] = txt["facebook"].replace(link, fb_link)
    _queue_social(p, txt, files)
    L.info("published %s to telegram (msg %s, style %s)", p["id"], mid, style)
    return {"status": "published", "product": p["id"], "message_id": mid, "style": style}


def _queue_social(p: dict, txt: dict, files: dict) -> None:
    jobs = db.kv_get("social_jobs", [])
    jobs.append({"product_id": p["id"], "style": txt["style"], "facebook": txt["facebook"], "instagram": txt["instagram"],
                 "tiktok": txt["tiktok"]["caption"], "square": str(files["square"]), "vertical": str(files["vertical"]),
                 "video": str(files.get("video", "")), "created": db.now_iso()})
    db.kv_set("social_jobs", jobs[-10:])


def run_social() -> list[dict]:
    """Runs AFTER the site deploy, so the media files have public URLs for Instagram."""
    from pathlib import Path
    jobs, results, keep = db.kv_get("social_jobs", []), [], []
    pf = platforms()
    for j in jobs:
        pid = j["product_id"]
        for platform in ("facebook", "instagram", "tiktok"):
            if not pf.get(platform):
                continue
            done = db.one("SELECT 1 FROM posts WHERE product_id=? AND platform=? AND status IN ('published','draft')",
                          (pid, platform))
            if done:
                continue
            if platform == "facebook":
                res = social.facebook_photo(Path(j["square"]), j["facebook"]) if Path(j["square"]).exists() else {"status": "failed", "error": "media missing"}
            elif platform == "instagram":
                use_video = bool(j.get("video")) and Path(j["video"]).exists()
                fname = Path(j["video"] if use_video else j["square"]).name
                url = f"{config.BRAND['site_url']}/media/{fname}"
                res = social.instagram(url, j["instagram"], is_video=use_video)
            else:
                res = social.tiktok_draft(Path(j["video"]), j["tiktok"]) if j.get("video") and Path(j["video"]).exists() \
                    else {"status": "skipped", "error": "no video"}
            if res["status"] == "pending":
                continue  # not connected: nothing recorded, shown as Pending in the dashboard
            with db.tx() as c:
                c.execute("INSERT INTO posts(product_id,platform,style,status,external_id,error,hour,created_at,published_at) "
                          "VALUES(?,?,?,?,?,?,?,?,?)",
                          (pid, platform, j["style"], res["status"], res.get("external_id"), res.get("error"),
                           datetime.now(IL).hour, db.now_iso(), db.now_iso() if res["status"] == "published" else None))
            if res["status"] == "failed":
                db.alert("error", f"פרסום ל-{platform} נכשל: {res.get('error')}")
            results.append({"product": pid, "platform": platform, **res})
        # keep job for a retry only if something failed and it's younger than 6h
        failed = db.one("SELECT COUNT(*) n FROM posts WHERE product_id=? AND platform!='telegram' AND status='failed'", (pid,))["n"]
        if failed and datetime.now(timezone.utc) - datetime.fromisoformat(j["created"]) < timedelta(hours=6):
            keep.append(j)
    db.kv_set("social_jobs", keep)
    return results
