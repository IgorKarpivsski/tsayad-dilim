"""Quality score 0-100. Consumer value first – commission is deliberately capped at 10%
of the score so a high-commission junk item can never win."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from . import config, db


def hard_filters(p: dict) -> str | None:
    """Return a Hebrew rejection reason, or None if the product may be scored."""
    if not p.get("id"):
        return "אין מזהה מוצר"
    if not p.get("image_url"):
        return "אין תמונה"
    if not p.get("price") or p["price"] <= 0:
        return "מחיר לא מאומת"
    if len((p.get("title_he") or "").strip()) < 12:
        return "מידע חסר על המוצר"
    fb = p.get("feedback")
    if fb is None:
        return "אין נתוני משוב"
    if fb < config.MIN_FEEDBACK:
        return f"משוב חיובי נמוך ({fb:.0f}%)"
    if (p.get("orders") or 0) < config.MIN_ORDERS:
        return f"מעט מדי הזמנות ({p.get('orders') or 0})"
    # suspicious: perfect rating on low volume, or absurd discount
    if fb >= 99.5 and (p.get("orders") or 0) < 150:
        return "דירוג חשוד (מושלם על נפח נמוך)"
    if (p.get("discount") or 0) > 85:
        return "הנחה לא סבירה – חשד למחיר מנופח"
    if p.get("price", 0) > 2000:
        return "מחיר גבוה מדי לקהל היעד"
    recent = db.one("SELECT published_at FROM products WHERE id=? AND published_at IS NOT NULL", (p["id"],))
    if recent and recent["published_at"]:
        last = datetime.fromisoformat(recent["published_at"])
        if datetime.now(timezone.utc) - last < timedelta(days=config.REPOST_COOLDOWN_DAYS):
            return "פורסם לאחרונה"
    return None


def score(p: dict, category_weight: float = 0.85) -> tuple[float, dict]:
    fb = p.get("feedback") or 0
    orders = p.get("orders") or 0
    price = p.get("price") or 0
    parts = {
        # 30: buyer satisfaction (90%..100% -> 0..30)
        "satisfaction": max(0.0, min(30.0, (fb - 90) * 3.0)),
        # 25: proven demand, log scale (50 -> ~9, 1000 -> ~19, 10000 -> 25)
        "demand": max(0.0, min(25.0, (math.log10(max(orders, 1)) - 1.0) * 8.3)),
        # 10: discount (real value), capped at 60%
        "discount": min(p.get("discount") or 0, 60) / 60 * 10,
        # 10: price sweet spot for impulse buys in Israel
        "price_fit": 10.0 if 8 <= price <= 150 else 7.0 if price <= 300 else 4.0 if price <= 600 else 2.0,
        # 10: commission – capped so it never dominates
        "commission": min(p.get("commission") or 0, 12) / 12 * 10,
        # 10: relevance to the Israeli audience (category weight)
        "relevance": 10.0 * category_weight,
        # 5: data completeness
        "completeness": 5.0 if (p.get("images") and p.get("detail_url")) else 3.0,
    }
    total = round(sum(parts.values()), 1)
    return total, {k: round(v, 1) for k, v in parts.items()}
