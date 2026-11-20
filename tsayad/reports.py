"""Daily (21:00) and weekly (Sunday 10:00) Telegram reports to the owner, Israel time."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from . import analytics, config, db, manager, publisher, telegram

IL = ZoneInfo(config.TIMEZONE)


def _fmt(v, money=False):
    if v is None:
        return "לא זמין"
    return f"${v:,.2f}" if money else f"{v:,.0f}"


def daily_text() -> str:
    k = analytics.kpis(1)
    top = db.q("SELECT p.title_he t, s.clicks c FROM posts s JOIN products p ON p.id=s.product_id "
               "WHERE s.platform='telegram' AND s.published_at>=datetime('now','-1 day') ORDER BY s.clicks DESC LIMIT 3")
    issues = manager.health_checks()
    lines = [
        "<b>📊 דוח יומי – צייד הדילים</b>",
        f"מוצרים שאותרו: {_fmt(k['products_found'])} | בתור: {_fmt(k['queue'])}",
        f"פורסמו בהצלחה: {_fmt(k['posts_ok'])} | נכשלו: {_fmt(k['posts_failed'])} | טיוטות TikTok: {_fmt(k['drafts'])}",
        f"קליקים: {_fmt(k['clicks']) if k['clicks_tracking'] else 'מעקב קליקים לא מחובר'}",
        f"הזמנות: {_fmt(k['orders'])} | עמלה צפויה: {_fmt(k['commission_est'], True)}"
        + ("" if k["orders_api"].get("ok") else " (נתוני מכירות לא זמינים דרך ה-API – בדוק בפורטל)"),
        f"חברים בערוץ: {_fmt(k['tg_members'])}" + (f" ({k['tg_growth']:+.0f})" if k["tg_growth"] is not None else ""),
        f"הפרסום הבא: {publisher.next_post_time() or 'בהרצה הקרובה'}",
    ]
    if top:
        lines.append("\n<b>מובילים היום:</b>")
        lines += [f"• {t['t'][:50]} – {t['c']} קליקים" for t in top]
    if issues:
        lines.append("\n<b>תקלות / לטיפול:</b>")
        lines += [f"• {i}" for i in issues]
    return "\n".join(lines)


def weekly_text() -> str:
    k = analytics.kpis(7)
    recs = db.q("SELECT title, benefit FROM recommendations WHERE status='open' ORDER BY score DESC LIMIT 3")
    plat = db.q("SELECT platform, status, COUNT(*) n FROM posts WHERE created_at>=datetime('now','-7 day') GROUP BY platform, status")
    lines = ["<b>🗓️ דוח שבועי – צייד הדילים</b>",
             f"פרסומים מוצלחים: {_fmt(k['posts_ok'])} | קליקים: {_fmt(k['clicks'])}",
             f"הזמנות: {_fmt(k['orders'])} | עמלה צפויה: {_fmt(k['commission_est'], True)} | מאושרת: {_fmt(k['commission_final'], True)}",
             f"גידול בערוץ: {_fmt(k['tg_growth'])} | עוקבים FB: {_fmt(k['fb_followers'])} | IG: {_fmt(k['ig_followers'])}",
             "הוצאות: ₪0 (כל השירותים במכסה החינמית)", "", "<b>ביצועי פלטפורמות:</b>"]
    lines += [f"• {r['platform']}: {r['status']} × {r['n']}" for r in plat] or ["• אין נתונים"]
    lines += ["", "<b>הצעות ייעול מובילות:</b>"] + [f"• {r['title']} – {r['benefit']}" for r in recs]
    lines += ["", "<b>יעד לשבוע הבא:</b> 84+ פרסומים מוצלחים בטלגרם, 0 כשלים חוזרים, צמיחה בחברים בערוץ."]
    return "\n".join(lines)


def maybe_send() -> list[str]:
    now = datetime.now(IL)
    sent = []
    dkey = now.strftime("%Y-%m-%d")
    if now.hour >= 21 and db.kv_get("daily_report") != dkey:
        if telegram.notify_admin(daily_text()):
            db.kv_set("daily_report", dkey)
            sent.append("daily")
    wkey = now.strftime("%G-W%V")
    if now.weekday() == 6 and now.hour >= 10 and db.kv_get("weekly_report") != wkey:
        manager.ai_ideas()
        if telegram.notify_admin(weekly_text()):
            db.kv_set("weekly_report", wkey)
            sent.append("weekly")
    return sent
