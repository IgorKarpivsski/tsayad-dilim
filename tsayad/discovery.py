"""Daily product discovery: query the official API across categories, filter, score,
generate affiliate links and fill the publishing queue."""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

from . import aliexpress as ae
from . import config, db, log, scoring

L = log.get("discovery")


def _categories() -> dict:
    return config.S.get("discovery.categories", {})


def _pick_keywords(n: int) -> list[tuple[str, str]]:
    """Rotate keywords so every category is covered across days; weight by learned performance."""
    learned = db.kv_get("category_boost", {})
    pairs = []
    for slug, c in _categories().items():
        w = c.get("weight", 0.8) * learned.get(slug, 1.0)
        for kw in c["kw"]:
            pairs.append((w * random.uniform(0.6, 1.4), slug, kw))
    pairs.sort(reverse=True)
    return [(slug, kw) for _, slug, kw in pairs[:n]]


def upsert(p: dict, slug: str, keyword: str, source: str) -> str:
    """Insert/refresh product, score it and set status. Returns the status."""
    cat = _categories().get(slug, {})
    now = db.now_iso()
    reason = scoring.hard_filters(p)
    sc, br = scoring.score(p, cat.get("weight", 0.8)) if not reason else (0.0, {})
    if not reason and sc < config.MIN_SCORE:
        reason = f"ציון נמוך ({sc})"
    existing = db.one("SELECT status, first_seen FROM products WHERE id=?", (p["id"],))
    if existing and existing["status"] == "published" and reason == "פורסם לאחרונה":
        status = "published"
    else:
        status = "rejected" if reason else "queued"
    with db.tx() as c:
        c.execute("""INSERT INTO products(id,title,title_he,category,keyword,source,image_url,images,price,original_price,
                currency,discount,feedback,orders,commission,shop_id,shop_url,detail_url,affiliate_link,score,score_breakdown,
                status,reject_reason,first_seen,last_seen,price_checked_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET title_he=excluded.title_he, image_url=excluded.image_url,
                images=excluded.images, price=excluded.price, original_price=excluded.original_price,
                discount=excluded.discount, feedback=excluded.feedback, orders=excluded.orders,
                commission=excluded.commission, detail_url=excluded.detail_url,
                affiliate_link=COALESCE(NULLIF(excluded.affiliate_link,''), products.affiliate_link),
                score=excluded.score, score_breakdown=excluded.score_breakdown,
                status=CASE WHEN products.status='published' AND excluded.status!='queued' THEN 'published' ELSE excluded.status END,
                reject_reason=excluded.reject_reason, last_seen=excluded.last_seen, price_checked_at=excluded.price_checked_at""",
                  (p["id"], p["title_he"], p["title_he"], slug, keyword, source, p["image_url"],
                   json.dumps(p.get("images", [])), p["price"], p.get("original_price"), p.get("currency", "ILS"),
                   p.get("discount", 0), p.get("feedback"), p.get("orders", 0), p.get("commission", 0),
                   p.get("shop_id"), p.get("shop_url"), p.get("detail_url"), p.get("affiliate_link", ""), sc,
                   json.dumps(br), status, reason, existing["first_seen"] if existing else now, now, now))
        if p.get("price"):
            c.execute("INSERT INTO price_history(product_id,price,ts) VALUES(?,?,?)", (p["id"], p["price"], now))
    return status


def ensure_links(limit: int = 40) -> int:
    """Generate affiliate links (own tracking id) for queued products missing a valid one."""
    rows = db.q("SELECT id, detail_url, affiliate_link FROM products WHERE status='queued' "
                "ORDER BY score DESC LIMIT ?", (limit,))
    need = [r for r in rows if not ae.is_valid_affiliate_link(r["affiliate_link"]) and r["detail_url"]]
    fixed = 0
    for i in range(0, len(need), 20):
        chunk = need[i:i + 20]
        try:
            mapping = ae.generate_links([r["detail_url"] for r in chunk])
        except ae.AliExpressError as e:
            L.error("link.generate failed: %s", e)
            db.alert("error", f"יצירת קישורי Affiliate נכשלה: {e}")
            break
        with db.tx() as c:
            for r in chunk:
                link = mapping.get(r["detail_url"])
                if link and ae.is_valid_affiliate_link(link):
                    c.execute("UPDATE products SET affiliate_link=?, link_ok=1, link_checked_at=? WHERE id=?",
                              (link, db.now_iso(), r["id"]))
                    fixed += 1
                else:
                    c.execute("UPDATE products SET status='rejected', reject_reason=? WHERE id=?",
                              ("קישור Affiliate לא נוצר", r["id"]))
    # products whose link came from the API response already are valid by format
    with db.tx() as c:
        c.execute("UPDATE products SET link_ok=1, link_checked_at=COALESCE(link_checked_at, ?) "
                  "WHERE status='queued' AND affiliate_link LIKE 'https://s.click.aliexpress.com/%'", (db.now_iso(),))
    return fixed


def due() -> bool:
    last = db.kv_get("last_scan")
    if not last:
        return True
    return datetime.now(timezone.utc) - datetime.fromisoformat(last) >= timedelta(hours=config.SCAN_EVERY_HOURS)


def queue_size() -> int:
    return db.one("SELECT COUNT(*) n FROM products WHERE status='queued' AND link_ok=1")["n"]


def run_scan(force: bool = False) -> dict:
    if not force and not due() and queue_size() >= 12:
        return {"skipped": True}
    stats = {"fetched": 0, "queued": 0, "rejected": 0, "errors": 0}
    n = int(config.S.get("discovery.keywords_per_scan", 18))
    pages = int(config.S.get("discovery.pages_per_keyword", 1))
    for slug, kw in _pick_keywords(n):
        for page in range(1, pages + 1):
            try:
                items = ae.product_query(kw, page=page)
            except ae.AliExpressError as e:
                stats["errors"] += 1
                L.error("query %s failed: %s", kw, e)
                if stats["errors"] >= 4:
                    db.alert("error", f"חיבור AliExpress API נכשל שוב ושוב: {e}")
                    db.kv_set("last_scan_error", str(e))
                    return stats
                continue
            for p in items:
                stats["fetched"] += 1
                st = upsert(p, slug, kw, "query")
                stats["queued" if st == "queued" else "rejected"] += (st in ("queued", "rejected"))
    # hot products: higher commission campaigns – still go through the same quality gate
    for slug in random.sample(list(_categories()), k=min(3, len(_categories()))):
        try:
            for p in ae.hot_products(_categories()[slug]["kw"][0]):
                stats["fetched"] += 1
                st = upsert(p, slug, "hot", "hot")
                stats["queued" if st == "queued" else "rejected"] += (st in ("queued", "rejected"))
        except ae.AliExpressError as e:
            L.warning("hotproduct.query unavailable: %s", e)
            break
    stats["links_generated"] = ensure_links()
    db.kv_set("last_scan", db.now_iso())
    db.metric_set(datetime.now(timezone.utc).date().isoformat(), "products_found", stats["fetched"])
    if queue_size() == 0:
        db.alert("warning", "אין מוצרים איכותיים בתור – לא יפורסם מוצר עד הסריקה הבאה.")
    L.info("scan done %s", stats)
    return stats


def refresh_price(product_id: str) -> dict | None:
    """Re-verify price/availability right before publishing. Returns fresh data or None."""
    try:
        fresh = ae.product_detail([product_id])
    except ae.AliExpressError as e:
        L.warning("detail.get failed for %s: %s", product_id, e)
        return None
    if not fresh:
        return None
    p = fresh[0]
    with db.tx() as c:
        c.execute("UPDATE products SET price=?, original_price=?, discount=?, feedback=?, orders=?, price_checked_at=? WHERE id=?",
                  (p["price"], p.get("original_price"), p.get("discount", 0), p.get("feedback"), p.get("orders", 0),
                   db.now_iso(), product_id))
        c.execute("INSERT INTO price_history(product_id,price,ts) VALUES(?,?,?)", (product_id, p["price"], db.now_iso()))
    return p
