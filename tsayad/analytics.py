"""Real data only: clicks (from the optional tracker), orders/commissions (from the AliExpress
order API if your account has access), audience size (platform APIs). Nothing is estimated
and presented as fact – unavailable sources are reported as unavailable."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import aliexpress as ae
from . import config, db, http, log, social, telegram, tracking

L = log.get("analytics")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def sync_clicks() -> dict:
    if not (config.TRACKER_URL and config.TRACKER_SECRET):
        return {"status": "pending"}
    since = db.kv_get("clicks_synced_day", (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat())
    ts = str(int(datetime.now(timezone.utc).timestamp()))
    r = http.request("GET", f"{config.TRACKER_URL}/stats",
                     params={"since": since, "t": ts, "k": tracking.sig(f"stats|{since}|{ts}")})
    if r.status_code != 200:
        db.alert("error", f"סנכרון קליקים נכשל: HTTP {r.status_code}")
        return {"status": "failed"}
    rows = r.json().get("rows", [])
    with db.tx() as c:
        for row in rows:
            c.execute("INSERT INTO clicks(day,post_id,product_id,source,variant,count) VALUES(?,?,?,?,?,?) "
                      "ON CONFLICT(day,post_id,source) DO UPDATE SET count=excluded.count",
                      (row["day"], int(row.get("post_id") or 0), row["product_id"], row["source"], row.get("variant", ""),
                       int(row["n"])))
        c.execute("UPDATE posts SET clicks=(SELECT COALESCE(SUM(count),0) FROM clicks k WHERE k.post_id=posts.id)")
    db.kv_set("clicks_synced_day", (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat())
    return {"status": "ok", "rows": len(rows)}


def sync_orders() -> dict:
    if not ae.configured():
        return {"status": "pending"}
    last = db.kv_get("orders_synced")
    if last and datetime.now(timezone.utc) - datetime.fromisoformat(last) < timedelta(hours=6):
        return {"status": "not_due"}
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)
    fmt = "%Y-%m-%d %H:%M:%S"
    new = 0
    try:
        for status in ("Payment Completed", "Buyer Confirmed Receipt"):
            for page in range(1, 6):
                orders = ae.order_list(start.strftime(fmt), end.strftime(fmt), status=status, page=page)
                for o in orders:
                    oid = str(o.get("order_id") or o.get("sub_order_id") or "")
                    if not oid:
                        continue
                    existed = db.one("SELECT 1 FROM orders WHERE order_id=?", (oid,))
                    est = ae._num(o.get("estimated_paid_commission")) or ae._num(o.get("estimated_finished_commission"))
                    fin = ae._num(o.get("estimated_finished_commission")) if status == "Buyer Confirmed Receipt" else None
                    with db.tx() as c:
                        c.execute("""INSERT INTO orders(order_id,product_id,status,paid_amount,commission_est,commission_final,
                                 currency,created_at,paid_at,settled,raw,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                                 ON CONFLICT(order_id) DO UPDATE SET status=excluded.status,
                                 commission_final=COALESCE(excluded.commission_final, orders.commission_final),
                                 settled=excluded.settled, raw=excluded.raw, updated_at=excluded.updated_at""",
                                  (oid, str(o.get("product_id", "")), o.get("order_status", status),
                                   ae._num(o.get("paid_amount")), est, fin, o.get("settled_currency") or "USD",
                                   o.get("created_time"), o.get("paid_time"),
                                   1 if str(o.get("order_status", "")).lower().startswith("settled") else 0,
                                   json.dumps(o, ensure_ascii=False)[:4000], db.now_iso()))
                    if not existed:
                        new += 1
                if len(orders) < 50:
                    break
    except ae.AliExpressError as e:
        db.kv_set("orders_api", {"ok": False, "error": str(e)[:300], "at": db.now_iso()})
        return {"status": "unavailable", "error": str(e)}
    db.kv_set("orders_api", {"ok": True, "at": db.now_iso()})
    db.kv_set("orders_synced", db.now_iso())
    if new:
        db.alert("sale", f"נרשמו {new} הזמנות חדשות דרך הקישורים שלך (לפי AliExpress API).")
    return {"status": "ok", "new": new}


def snapshot_audience() -> dict:
    d = today()
    out = {}
    if config.TG_BOT_TOKEN and config.TG_CHANNEL_ID:
        n = telegram.member_count()
        if n is not None:
            db.metric_set(d, "tg_members", n)
            out["tg_members"] = n
    for key, fn in (("fb_followers", social.facebook_followers), ("ig_followers", social.instagram_followers)):
        try:
            n = fn()
        except Exception:  # noqa: BLE001
            n = None
        if n is not None:
            db.metric_set(d, key, n)
            out[key] = n
    return out


def kpis(days: int = 1) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sday = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    g = lambda sql, a=(): (db.one(sql, a) or {"n": 0})["n"] or 0  # noqa: E731
    orders_api = db.kv_get("orders_api", {})
    clicks_on = bool(config.TRACKER_URL and config.TRACKER_SECRET)

    def metric_delta(key):
        rows = db.q("SELECT value FROM metrics WHERE key=? AND day>=? ORDER BY day", (key, sday))
        return (rows[-1]["value"] - rows[0]["value"]) if len(rows) >= 2 else None

    latest = lambda key: (db.one("SELECT value FROM metrics WHERE key=? ORDER BY day DESC LIMIT 1", (key,)) or {"value": None})["value"]  # noqa: E731
    return {
        "products_found": g("SELECT COUNT(*) n FROM products WHERE first_seen>=?", (since,)),
        "queue": g("SELECT COUNT(*) n FROM products WHERE status='queued' AND link_ok=1"),
        "rejected": g("SELECT COUNT(*) n FROM products WHERE status='rejected' AND last_seen>=?", (since,)),
        "posts_ok": g("SELECT COUNT(*) n FROM posts WHERE status='published' AND published_at>=?", (since,)),
        "posts_failed": g("SELECT COUNT(*) n FROM posts WHERE status='failed' AND created_at>=?", (since,)),
        "drafts": g("SELECT COUNT(*) n FROM posts WHERE status='draft' AND created_at>=?", (since,)),
        "clicks": g("SELECT SUM(count) n FROM clicks WHERE day>=?", (sday,)) if clicks_on else None,
        "orders": g("SELECT COUNT(*) n FROM orders WHERE created_at>=?", (since[:19].replace("T", " "),)) if orders_api.get("ok") else None,
        "commission_est": g("SELECT SUM(commission_est) n FROM orders WHERE created_at>=?", (since[:19].replace("T", " "),)) if orders_api.get("ok") else None,
        "commission_final": g("SELECT SUM(commission_final) n FROM orders WHERE commission_final IS NOT NULL AND created_at>=?", (since[:19].replace("T", " "),)) if orders_api.get("ok") else None,
        "tg_members": latest("tg_members"),
        "tg_growth": metric_delta("tg_members"),
        "fb_followers": latest("fb_followers"),
        "ig_followers": latest("ig_followers"),
        "orders_api": orders_api,
        "clicks_tracking": clicks_on,
    }
