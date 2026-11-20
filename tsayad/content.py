"""Hebrew marketing copy. Rules: never invent price, discount, specs or benefits.
Facts (price, feedback %, orders, discount) come only from verified API data.
The AI writer (Gemini free tier, optional) may only phrase a hook from the product
title – its output is rejected if it contains numbers, prices or superlatives."""
from __future__ import annotations

import html
import json
import random
import re

from . import config, db, http, log

L = log.get("content")

DISCLOSURE = "גילוי נאות: זהו קישור שותפים – ייתכן שנקבל עמלה על רכישה דרכו, ללא תוספת עלות עבורך."
PRICE_NOTE = "המחיר נכון לזמן הבדיקה וייתכנו שינויים במחיר ובזמינות. עלויות משלוח, מסים ומכס (אם יחולו) מוצגים באתר המוכר."

STYLES = ["classic", "question", "short", "story"]

HEADLINES = {
    "classic": ["🔥 מציאה ששווה להכיר", "🔥 שווה בדיקה", "✨ מוצר שתפס לנו את העין", "🔥 דיל חדש בערוץ"],
    "question": ["🤔 גם אתם צריכים את זה?", "🤔 מכירים את זה?", "👀 ידעתם שיש דבר כזה?"],
    "short": ["⚡ על קצה המזלג", "⚡ קצר ולעניין", "⚡ דיל בקטנה"],
    "story": ["💡 מהמוצרים שהקונים הכי אוהבים", "💡 הקונים כבר הצביעו", "💡 נבחר בקפידה עבורכם"],
}

CATEGORY_HOOK = {
    "gadgets": "גאדג'ט קטן שעושה את החיים קצת יותר נוחים",
    "tech": "לחובבי טכנולוגיה",
    "phone": "לכל מי שהטלפון תמיד ביד",
    "gaming": "לגיימרים שבינינו",
    "home": "שדרוג קטן לבית",
    "kitchen": "למי שאוהב שהמטבח עובד חלק",
    "cleaning": "לניקיון קל ומהיר יותר",
    "storage": "לארגון וסדר בבית",
    "car": "בשביל הנסיעות שלכם",
    "lighting": "לתאורה שיוצרת אווירה",
    "pets": "לחברים על ארבע",
    "toys": "לילדים (ולמבוגרים שבפנים)",
    "tools": "אביזר שימושי שכדאי שיהיה",
    "gifts": "רעיון למתנה",
}


def money(v: float | None) -> str:
    return f"₪{v:,.2f}".replace(".00", "") if v else ""


def facts(p: dict) -> dict:
    disc = p.get("discount") or 0
    show_orig = p.get("original_price") and disc >= 10 and p["original_price"] > (p.get("price") or 0)
    return {
        "price": money(p.get("price")),
        "original": money(p.get("original_price")) if show_orig else "",
        "discount": f"{disc:.0f}%" if disc >= 10 else "",
        "feedback": f"{p['feedback']:.1f}% משוב חיובי" if p.get("feedback") else "",
        "orders": f"{int(p['orders']):,} הזמנות לאחרונה" if p.get("orders") else "",
    }


def short_title(title: str, n: int = 90) -> str:
    t = re.sub(r"\s+", " ", title or "").strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


# ------------------------------------------------------------------- AI (optional)
_BANNED = re.compile(r"\d|₪|\$|%|הכי זול|הזול ביותר|מבצע אחרון|חינם|מובטח|ללא מכס|פטור")


def ai_hook(p: dict) -> str | None:
    if not config.GEMINI_API_KEY:
        return None
    budget = db.kv_get("ai_calls_today", {"day": "", "n": 0})
    today = db.now_iso()[:10]
    if budget.get("day") != today:
        budget = {"day": today, "n": 0}
    if budget["n"] >= 15:  # stay well inside the free tier
        return None
    prompt = ("כתוב משפט שיווקי קצר (עד 18 מילים) בעברית טבעית על המוצר הבא, על סמך הכותרת בלבד. "
              "אסור לכלול מספרים, מחירים, אחוזים, הבטחות, השוואות מחיר או מאפיינים שלא מופיעים בכותרת. "
              "החזר JSON בלבד: {\"hook\": \"...\"}\nכותרת: " + (p.get("title_he") or ""))
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
           f"?key={config.GEMINI_API_KEY}")
    try:
        r = http.request("POST", url, retries=2, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"}})
        budget["n"] += 1
        db.kv_set("ai_calls_today", budget)
        if r.status_code != 200:
            L.warning("gemini %s: %s", r.status_code, r.text[:200])
            return None
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        hook = json.loads(text).get("hook", "").strip()
    except Exception as e:  # noqa: BLE001
        L.warning("gemini failed: %s", e)
        return None
    if not hook or len(hook) > 140 or _BANNED.search(hook):
        return None
    return hook


# ------------------------------------------------------------------- builders
def pick_style() -> str:
    weights = db.kv_get("style_weights", {s: 1.0 for s in STYLES})
    return random.choices(STYLES, weights=[weights.get(s, 1.0) for s in STYLES])[0]


def build(p: dict, style: str, link: str) -> dict:
    """Return captions for every platform from the same verified facts."""
    f = facts(p)
    head = random.choice(HEADLINES[style])
    hook = ai_hook(p) or CATEGORY_HOOK.get(p.get("category_slug") or p.get("category") or "", "")
    title = short_title(p.get("title_he") or "", 110 if style != "short" else 70)
    e = html.escape

    price_line = f"💰 מחיר: <b>{f['price']}</b>"
    if f["original"]:
        price_line += f" <s>{f['original']}</s> ({f['discount']} הנחה)"
    lines = [f"<b>{e(head)}</b>", "", e(title)]
    if hook and style != "short":
        lines += ["", e(hook)]
    lines += ["", price_line]
    if f["feedback"]:
        lines.append(f"⭐ {f['feedback']}")
    if f["orders"] and style != "short":
        lines.append(f"📦 {f['orders']}")
    lines += ["", f"🛒 לרכישה: {e(link)}", "", f"<i>{e(PRICE_NOTE)}</i>", f"<i>{e(DISCLOSURE)}</i>"]
    tg = "\n".join(lines)
    if len(tg) > 1024:  # Telegram photo caption limit
        lines = [f"<b>{e(head)}</b>", e(short_title(title, 70)), price_line, f"🛒 {e(link)}", f"<i>{e(DISCLOSURE)}</i>"]
        tg = "\n".join(lines)

    plain_price = f"💰 {f['price']}" + (f" (במקום {f['original']})" if f["original"] else "")
    channel = f"https://t.me/{config.BRAND['telegram_username']}"
    fb = "\n".join(x for x in [head, "", title, hook, "", plain_price, f"⭐ {f['feedback']}" if f["feedback"] else "",
                               "", f"🛒 לרכישה: {link}", "", f"עוד דילים כל יום בערוץ הטלגרם: {channel}",
                               "", PRICE_NOTE, DISCLOSURE] if x is not None)
    ig = "\n".join([head, "", title, hook, "", plain_price, "",
                    "🔗 הקישור לרכישה בערוץ הטלגרם שלנו (קישור בביו)", "", DISCLOSURE, "",
                    "#דילים #אליאקספרס #מבצעים #קניותברשת #גאדג׳טים #צייד_הדילים"])
    tiktok = {
        "script": [head, title, hook or "", f"עכשיו ב-{f['price']}", "הקישור בערוץ הטלגרם – בביו"],
        "caption": f"{head} {short_title(title, 60)} | הקישור בביו 👆 #דילים #אליאקספרס #צייד_הדילים #fyp",
    }
    return {"style": style, "telegram": tg, "facebook": fb, "instagram": ig, "tiktok": tiktok,
            "headline": head, "hook": hook, "facts": f}
