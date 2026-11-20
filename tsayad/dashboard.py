"""Hebrew management dashboard: a static page encrypted with AES-GCM (password = DASHBOARD_PASSWORD).
Served from the same free Cloudflare Pages site at /admin/ – nothing readable without the password."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import analytics, config, crypto, db, publisher

TPL = Path(__file__).parent / "templates" / "dashboard"
IL = ZoneInfo(config.TIMEZONE)

NOTES = {
    "aliexpress": "App Key + Secret + Tracking ID. ראה docs/SETUP_ALIEXPRESS.md",
    "telegram": "בוט + ערוץ (הבוט אדמין עם הרשאת פרסום)",
    "telegram_alerts": "צ'אט פרטי שלך לקבלת התראות ודוחות",
    "facebook": "עמוד עסקי + Page Token ארוך-טווח",
    "instagram": "חשבון מקצועי מקושר לעמוד הפייסבוק",
    "tiktok": "נשלח כטיוטה לאפליקציה (פרסום ציבורי אוטומטי מחייב Audit של TikTok)",
    "ai_writer": "Gemini (מכסה חינמית) – אופציונלי, יש כתיבה מובנית בלי AI",
    "click_tracker": "Cloudflare Worker – בלי זה אין מדידת קליקים ולמידה",
    "dashboard": "הסיסמה לעמוד הזה",
    "data_encryption": "הצפנת מסד הנתונים בריפו",
}


def rows(sql, args=()):
    return [dict(r) for r in db.q(sql, args)]


def data() -> dict:
    conns = analytics_status()
    d = {
        "generated": datetime.now(IL).strftime("%d/%m/%Y %H:%M"),
        "last_run": (db.kv_get("last_run") or "—"),
        "next_post": publisher.next_post_time(),
        "counts": {
            "products": db.one("SELECT COUNT(*) n FROM products")["n"],
            "queued": db.one("SELECT COUNT(*) n FROM products WHERE status='queued' AND link_ok=1")["n"],
            "posts_ok": db.one("SELECT COUNT(*) n FROM posts WHERE status='published'")["n"],
        },
        "k1": analytics.kpis(1), "k30": analytics.kpis(30),
        "alerts": rows("SELECT ts, level, message FROM alerts ORDER BY id DESC LIMIT 25"),
        "products": rows("""SELECT p.status, p.title_he, p.score, p.price, p.discount, p.feedback, p.orders, p.commission, p.category,
                         p.affiliate_link, p.detail_url, p.reject_reason, COALESCE((SELECT SUM(clicks) FROM posts s WHERE s.product_id=p.id),0) clicks
                         FROM products p ORDER BY CASE p.status WHEN 'queued' THEN 0 WHEN 'published' THEN 1 ELSE 2 END, p.score DESC LIMIT 400"""),
        "posts": rows("""SELECT s.created_at, s.platform, s.status, s.style, substr(p.title_he,1,70) title, s.clicks, s.external_id, s.error
                      FROM posts s LEFT JOIN products p ON p.id=s.product_id ORDER BY s.id DESC LIMIT 300"""),
        "orders": rows("SELECT created_at, status, product_id, paid_amount, commission_est, commission_final FROM orders ORDER BY created_at DESC LIMIT 200"),
        "rev": {
            "pending": db.one("SELECT COUNT(*) n FROM orders WHERE status='Payment Completed'")["n"] if db.kv_get("orders_api", {}).get("ok") else None,
            "confirmed": db.one("SELECT COUNT(*) n FROM orders WHERE status!='Payment Completed'")["n"] if db.kv_get("orders_api", {}).get("ok") else None,
            "paid": None,  # AliExpress pays out via the portal; not exposed by the order API
        },
        "sources": rows("SELECT source, SUM(count) n FROM clicks GROUP BY source ORDER BY n DESC"),
        "audience": rows("""SELECT day, MAX(CASE WHEN key='tg_members' THEN value END) tg_members,
                         MAX(CASE WHEN key='fb_followers' THEN value END) fb_followers,
                         MAX(CASE WHEN key='ig_followers' THEN value END) ig_followers
                         FROM metrics WHERE key IN ('tg_members','fb_followers','ig_followers') GROUP BY day ORDER BY day DESC LIMIT 60"""),
        "cat_perf": rows("""SELECT p.category k, COUNT(*) posts, SUM(s.clicks) clicks FROM posts s JOIN products p ON p.id=s.product_id
                         WHERE s.platform='telegram' AND s.status='published' AND s.published_at>=datetime('now','-30 day') GROUP BY 1 ORDER BY 3 DESC"""),
        "style_perf": rows("""SELECT style k, COUNT(*) posts, SUM(clicks) clicks FROM posts WHERE platform='telegram' AND status='published'
                           AND published_at>=datetime('now','-30 day') GROUP BY 1 ORDER BY 3 DESC"""),
        "top": rows("""SELECT substr(p.title_he,1,80) title, SUM(s.clicks) clicks FROM posts s JOIN products p ON p.id=s.product_id
                    GROUP BY s.product_id ORDER BY 2 DESC LIMIT 15"""),
        "recs": rows("SELECT * FROM recommendations WHERE status='open' ORDER BY score DESC"),
        "learn": [{"k": a} for a in (db.kv_get("learn_log", []) or [])[-15:]],
        "connections": [{"name": k, "status": v, "note": NOTES.get(k, "")} for k, v in conns.items()],
        "settings": [{"k": "מרווח פרסום (דקות)", "v": config.POST_INTERVAL_MIN},
                     {"k": "שעות שקטות", "v": ", ".join(map(str, config.QUIET_HOURS)) or "אין (24/7)"},
                     {"k": "ציון מינימלי", "v": config.MIN_SCORE}, {"k": "משוב חיובי מינימלי %", "v": config.MIN_FEEDBACK},
                     {"k": "הזמנות מינימום", "v": config.MIN_ORDERS}, {"k": "צינון לפני פרסום חוזר (ימים)", "v": config.REPOST_COOLDOWN_DAYS},
                     {"k": "משקלי סגנונות", "v": json.dumps(db.kv_get("style_weights", {}), ensure_ascii=False)},
                     {"k": "עדיפות קטגוריות (נלמד)", "v": json.dumps(db.kv_get("category_boost", {}), ensure_ascii=False)}],
    }
    return d


def analytics_status() -> dict:
    conns = config.status_of_connections()
    live = db.kv_get("live_checks", {})
    for k, ok in live.items():
        if conns.get(k) == "configured":
            conns[k] = "active" if ok else "failed"
    return conns


def render_plain() -> str:
    app = (TPL / "app.html").read_text(encoding="utf-8")
    payload = json.dumps(data(), ensure_ascii=False, default=str).replace("</", "<\\/")
    return app.replace("__DATA__", payload)


def build(out: Path | None = None) -> Path | None:
    out = out or (config.OUT_DIR / "site" / "admin")
    out.mkdir(parents=True, exist_ok=True)
    html = render_plain()
    if not config.DASHBOARD_PASSWORD:
        # never publish an unprotected dashboard; keep a local copy only
        local = config.DATA_DIR / "dashboard_local.html"
        local.write_text(html, encoding="utf-8")
        (out / "index.html").write_text("<meta charset=utf-8><p dir=rtl>הדשבורד ממתין להגדרת DASHBOARD_PASSWORD.</p>", encoding="utf-8")
        return local
    bundle = crypto.password_encrypt(html, config.DASHBOARD_PASSWORD)
    lock = (TPL / "lock.html").read_text(encoding="utf-8").replace("__BUNDLE__", json.dumps(bundle))
    (out / "index.html").write_text(lock, encoding="utf-8")
    return out / "index.html"
