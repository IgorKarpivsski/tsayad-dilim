"""AI Business Manager.
Learns only from real measured data. Autonomous actions are limited to free, internal,
low-risk tuning (category weights, writing-style weights, posting-hour preferences).
Anything with cost, permission changes, external commitments or reputation risk is written
as a recommendation and requires the owner's approval."""
from __future__ import annotations

import json
from collections import defaultdict

from . import config, content, db, http, log

L = log.get("manager")

MIN_SAMPLE = 20  # posts per variant before any conclusion

# Seed backlog – the "AI BUSINESS IMPROVEMENTS" board. score = expected impact × ease.
IDEAS = [
    ("price_drop_alerts", "התראות ירידת מחיר", "אנשים מחכים למחיר טוב יותר ולא קונים",
     "פוסטים 'ירד מחיר!' על מוצרים שכבר פורסמו – המרה גבוהה, אפס עלות", "₪0", "בינונית", "1-2 ימים", "גבוהה", "כן", 88),
    ("coupon_engine", "מנוע קופונים", "קונים מחפשים קופונים לפני רכישה",
     "פוסט קופונים יומי מתוך featuredpromo/מבצעי האפיליאייט הרשמיים", "₪0", "בינונית", "2-3 ימים", "גבוהה", "כן (בכפוף להרשאות API)", 84),
    ("seo_guides", "מדריכי SEO אוטומטיים", "אין תנועה אורגנית מגוגל בהתחלה",
     "עמודי 'הכי שווים ב-X' לפי קטגוריה עם עדכון שבועי – תנועה חינמית לטווח ארוך", "₪0", "נמוכה", "1 יום", "גבוהה", "כן", 82),
    ("telegram_directories", "רישום באינדקסים של טלגרם", "ערוץ חדש לא מופיע בחיפושים",
     "רישום ידני חד-פעמי ב-tgstat ובאינדקסים ישראליים מאושרים", "₪0", "נמוכה", "30 דקות", "בינונית", "לא – פעולה חד-פעמית שלך", 80),
    ("weekly_top10", "טופ 10 שבועי", "פוסטים בודדים נשכחים מהר",
     "פוסט סיכום שבועי של המוצרים הכי נלחצים – תוכן לשיתוף", "₪0", "נמוכה", "חצי יום", "בינונית", "כן", 76),
    ("whatsapp_channel", "ערוץ WhatsApp", "חלק גדול מהישראלים לא בטלגרם",
     "הרחבת חשיפה לקהל רחב יותר (העתקה ידנית או API רשמי בלבד)", "₪0", "נמוכה", "1 שעה", "גבוהה", "חלקית", 75),
    ("vip_channel", "ערוץ VIP / דילי בזק", "דילים חמים מאבדים ערך תוך שעות",
     "ערוץ שני עם התראות מהירות לדילים עם הנחה חריגה", "₪0", "בינונית", "1 יום", "בינונית", "כן", 66),
    ("referral", "חבר מביא חבר", "צמיחה אורגנית איטית",
     "קישורי הזמנה אישיים של טלגרם + תחרות חודשית (פרס רק באישורך)", "עלות פרס אופציונלית", "בינונית", "2 ימים", "בינונית", "חלקית – פרסים דורשים אישור", 60),
    ("newsletter", "ניוזלטר שבועי", "אין ערוץ בבעלות מלאה שלך",
     "רשימת תפוצה בחינם (Buttondown/Brevo free) – נכס שלא תלוי בפלטפורמה", "₪0 עד מכסה", "נמוכה", "חצי יום", "בינונית", "כן", 58),
    ("influencer_collabs", "שיתופי פעולה עם יוצרים קטנים", "קשה להגיע לקהל ראשון",
     "החלפת אזכורים עם ערוצים/יוצרים ישראלים בתחום – רק בהסכמה ובגילוי נאות", "₪0", "בינונית", "שוטף", "גבוהה", "לא – דורש אישורך", 57),
]


def seed() -> None:
    with db.tx() as c:
        for key, title, problem, benefit, cost, cx, t, impact, auto, score in IDEAS:
            c.execute("""INSERT OR IGNORE INTO recommendations(key,title,problem,benefit,cost,complexity,time_to_implement,
                      impact,automatable,score,status,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (key, title, problem, benefit, cost, cx, t, impact, auto, score, "open", "seed", db.now_iso(), db.now_iso()))


def recommend(key, title, problem, benefit, impact="בינונית", score=60, cost="₪0", complexity="נמוכה",
              time_="מיידי", automatable="כן", source="data") -> None:
    with db.tx() as c:
        c.execute("""INSERT INTO recommendations(key,title,problem,benefit,cost,complexity,time_to_implement,impact,automatable,
                  score,status,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,'open',?,?,?)
                  ON CONFLICT(key) DO UPDATE SET problem=excluded.problem, benefit=excluded.benefit, score=excluded.score,
                  updated_at=excluded.updated_at""",
                  (key, title, problem, benefit, cost, complexity, time_, impact, automatable, score, source,
                   db.now_iso(), db.now_iso()))


def _ctr_by(field: str, days: int = 30) -> dict:
    rows = db.q(f"""SELECT {field} k, COUNT(*) posts, COALESCE(SUM(clicks),0) clicks FROM posts s
                   JOIN products p ON p.id=s.product_id
                   WHERE s.platform='telegram' AND s.status='published' AND s.published_at>=datetime('now','-{int(days)} day')
                   GROUP BY {field}""")
    return {r["k"]: {"posts": r["posts"], "clicks": r["clicks"], "cpp": r["clicks"] / r["posts"]} for r in rows if r["posts"]}


def learn() -> dict:
    """Adjust internal weights from real clicks. Changes one dimension at a time (round-robin)
    so effects stay attributable."""
    actions = []
    if not (config.TRACKER_URL and config.TRACKER_SECRET):
        return {"status": "no_click_data", "note": "ללא מעקב קליקים אין נתונים אמיתיים ללמידה – לא בוצעו שינויים."}
    dim = db.kv_get("learn_dim", 0) % 3
    if dim == 0:  # writing styles (A/B)
        stats = _ctr_by("s.style")
        if len(stats) >= 2 and all(v["posts"] >= MIN_SAMPLE for v in stats.values()):
            avg = sum(v["cpp"] for v in stats.values()) / len(stats) or 1
            w = {s: round(max(0.3, min(3.0, stats.get(s, {"cpp": avg})["cpp"] / avg)), 2) for s in content.STYLES}
            db.kv_set("style_weights", w)
            actions.append(f"עודכנו משקלי סגנונות כתיבה: {w}")
    elif dim == 1:  # categories
        stats = _ctr_by("p.category")
        ready = {k: v for k, v in stats.items() if v["posts"] >= 8}
        if len(ready) >= 3:
            avg = sum(v["cpp"] for v in ready.values()) / len(ready) or 1
            boost = {k: round(max(0.5, min(1.8, v["cpp"] / avg)), 2) for k, v in ready.items()}
            db.kv_set("category_boost", boost)
            actions.append(f"עודכנה עדיפות קטגוריות: {boost}")
            weak = [k for k, b in boost.items() if b <= 0.6]
            if weak:
                recommend("weak_categories", "קטגוריות חלשות", f"קטגוריות עם מעט קליקים: {', '.join(weak)}",
                          "שקול להחליף מילות חיפוש או להסיר את הקטגוריה", score=55)
    else:  # hours
        stats = _ctr_by("s.hour")
        ready = {k: v for k, v in stats.items() if v["posts"] >= 6}
        if len(ready) >= 6:
            best = sorted(ready.items(), key=lambda kv: kv[1]["cpp"], reverse=True)[:4]
            db.kv_set("best_hours", [h for h, _ in best])
            recommend("best_hours", "שעות פרסום מנצחות",
                      f"השעות עם הכי הרבה קליקים לפוסט: {', '.join(str(h) + ':00' for h, _ in best)}",
                      "להוסיף פרסום נוסף בשעות האלה (לא משנה את מינימום הפרסום)", score=62)
    db.kv_set("learn_dim", dim + 1)
    return {"status": "ok", "actions": actions}


def health_checks() -> list[str]:
    issues = []
    q = db.one("SELECT COUNT(*) n FROM products WHERE status='queued' AND link_ok=1")["n"]
    if q < 12:
        issues.append(f"בתור רק {q} מוצרים (פחות מיום פרסום).")
        recommend("queue_low", "הרחבת מילות חיפוש", f"התור נמוך ({q})", "להוסיף מילות מפתח/קטגוריות או להוריד מעט את סף הציון",
                  score=70, automatable="חלקית")
    fail = db.one("SELECT COUNT(*) n FROM posts WHERE status='failed' AND created_at>=datetime('now','-1 day')")["n"]
    if fail >= 3:
        issues.append(f"{fail} פרסומים נכשלו ב-24 השעות האחרונות.")
    rej = db.q("SELECT reject_reason r, COUNT(*) n FROM products WHERE status='rejected' GROUP BY reject_reason ORDER BY n DESC LIMIT 3")
    if rej and rej[0]["n"] > 200:
        issues.append(f"סיבת הפסילה המובילה: {rej[0]['r']} ({rej[0]['n']}).")
    return issues


def ai_ideas() -> int:
    """Weekly: ask the free LLM for fresh growth ideas from aggregated (non-personal) stats. Labelled 'ai'."""
    if not config.GEMINI_API_KEY:
        return 0
    stats = {"by_category": _ctr_by("p.category"), "by_style": _ctr_by("s.style")}
    prompt = ("אתה יועץ צמיחה לערוץ דילים ישראלי בטלגרם (אליאקספרס, אפיליאייט, תקציב אפס). "
              "על סמך הנתונים הבאים הצע 3 רעיונות חדשים, חוקיים, ללא ספאם וללא עלות. "
              "החזר JSON: [{\"key\":\"...\",\"title\":\"...\",\"problem\":\"...\",\"benefit\":\"...\",\"impact\":\"גבוהה|בינונית|נמוכה\"}]\n"
              + json.dumps(stats, ensure_ascii=False)[:3000])
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}"
    try:
        r = http.request("POST", url, retries=2, json={"contents": [{"parts": [{"text": prompt}]}],
                                                       "generationConfig": {"responseMimeType": "application/json"}})
        ideas = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    except Exception as e:  # noqa: BLE001
        L.warning("ai ideas failed: %s", e)
        return 0
    n = 0
    for i in ideas[:3]:
        if i.get("key") and i.get("title"):
            recommend("ai_" + str(i["key"])[:40], i["title"], i.get("problem", ""), i.get("benefit", ""),
                      impact=i.get("impact", "בינונית"), score=50, automatable="לבדיקה", source="ai")
            n += 1
    return n
