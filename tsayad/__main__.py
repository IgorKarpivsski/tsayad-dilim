"""Command line entry point.

  python -m tsayad tick         # the autopilot step (run hourly by GitHub Actions)
  python -m tsayad social       # social publishing (after the site deploy)
  python -m tsayad check        # live connection checks (AliExpress permissions, Telegram admin rights…)
  python -m tsayad scan         # force a product scan now
  python -m tsayad publish      # force one Telegram post now
  python -m tsayad site | dashboard | report daily|weekly | brand
  python -m tsayad keygen       # generate DATA_KEY / TRACKER_SECRET
  python -m tsayad backup FILE | restore FILE
  python -m tsayad status
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

from . import (aliexpress, analytics, config, crypto, dashboard, db, discovery, log, manager, publisher, reports, site,
               storage, telegram)

L = log.get("cli")


def _run(task: str, fn, *a, **kw):
    t0 = time.time()
    with db.tx() as c:
        rid = c.execute("INSERT INTO runs(task,started,status) VALUES(?,?,?)", (task, db.now_iso(), "running")).lastrowid
    try:
        res = fn(*a, **kw)
        status = "ok"
    except Exception as e:  # noqa: BLE001 – one failing module must not stop the others
        res = {"error": str(e)}
        status = "error"
        L.error("%s failed: %s\n%s", task, e, traceback.format_exc())
        db.alert("error", f"המשימה {task} נכשלה: {e}")
    with db.tx() as c:
        c.execute("UPDATE runs SET finished=?, status=?, info=? WHERE id=?",
                  (db.now_iso(), status, json.dumps(res, ensure_ascii=False, default=str)[:2000], rid))
    L.info("%s -> %s (%.1fs) %s", task, status, time.time() - t0, str(res)[:300])
    return res


def tick() -> dict:
    out = {"restore": storage.restore()}
    db.connect()
    manager.seed()
    if aliexpress.configured():
        out["scan"] = _run("scan", discovery.run_scan)
        out["publish"] = _run("publish", publisher.publish_one)
    else:
        db.kv_set("pending_reason", "AliExpress not configured")
        out["scan"] = out["publish"] = {"status": "pending"}
    out["clicks"] = _run("clicks", analytics.sync_clicks)
    out["orders"] = _run("orders", analytics.sync_orders)
    if db.kv_get("audience_day") != analytics.today():
        out["audience"] = _run("audience", analytics.snapshot_audience)
        db.kv_set("audience_day", analytics.today())
        lr = _run("learn", manager.learn)
        if lr.get("actions"):
            db.kv_set("learn_log", (db.kv_get("learn_log", []) + lr["actions"])[-50:])
    out["health"] = manager.health_checks()
    out["reports"] = _run("reports", reports.maybe_send)
    db.kv_set("last_run", db.now_iso())
    _run("site", site.build)
    _run("dashboard", dashboard.build)
    out["alerts_sent"] = telegram.flush_alerts()
    db.close()
    return out


def social_phase() -> dict:
    db.connect()
    res = _run("social", publisher.run_social)
    telegram.flush_alerts()
    return {"social": res}


def check() -> dict:
    db.connect()
    res, live = {}, {}
    if aliexpress.configured():
        res["aliexpress"] = aliexpress.probe_permissions()
        live["aliexpress"] = res["aliexpress"]["aliexpress.affiliate.product.query"]["ok"]
    else:
        res["aliexpress"] = "pending – set AE_APP_KEY, AE_APP_SECRET, AE_TRACKING_ID"
    if config.TG_BOT_TOKEN and config.TG_CHANNEL_ID:
        try:
            res["telegram"] = telegram.channel_check()
            live["telegram"] = res["telegram"]["can_post"]
        except Exception as e:  # noqa: BLE001
            res["telegram"] = f"error: {e}"
            live["telegram"] = False
    else:
        res["telegram"] = "pending"
    if config.TG_ADMIN_CHAT_ID:
        live["telegram_alerts"] = telegram.notify_admin("✅ צייד הדילים: חיבור ההתראות עובד.")
    res["connections"] = config.status_of_connections()
    db.kv_set("live_checks", live)
    return res


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "tick":
        r = tick()
    elif cmd == "social":
        storage.restore()
        r = social_phase()
    elif cmd == "check":
        storage.restore()
        r = check()
    elif cmd == "scan":
        storage.restore(); db.connect()
        r = discovery.run_scan(force=True)
    elif cmd == "publish":
        storage.restore(); db.connect()
        r = publisher.publish_one(force=True)
    elif cmd == "site":
        db.connect(); r = str(site.build())
    elif cmd == "dashboard":
        db.connect(); r = str(dashboard.build())
    elif cmd == "report":
        db.connect(); text = reports.weekly_text() if len(argv) > 2 and argv[2] == "weekly" else reports.daily_text()
        print(text); r = {"sent": telegram.notify_admin(text)}
    elif cmd == "brand":
        from . import media
        r = [str(p) for p in media.brand_assets(config.ROOT / "assets" / "brand")]
    elif cmd == "keygen":
        import secrets
        r = {"DATA_KEY": crypto.new_key(), "TRACKER_SECRET": secrets.token_urlsafe(32),
             "DASHBOARD_PASSWORD (suggestion)": secrets.token_urlsafe(12)}
    elif cmd == "save":
        r = storage.save("manual save")
    elif cmd == "backup":
        storage.restore(); db.connect(); r = str(storage.export_backup(Path(argv[2])))
    elif cmd == "restore":
        storage.import_backup(Path(argv[2])); r = "restored"
    elif cmd == "status":
        storage.restore(); db.connect()
        r = {"connections": config.status_of_connections(), "kpis_24h": analytics.kpis(1),
             "next_post": publisher.next_post_time()}
    else:
        print(__doc__)
        return 2
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
