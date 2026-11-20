"""End-to-end tests with recorded API responses (no live network). They prove the pipeline logic;
live connectivity is verified separately with `python -m tsayad check` once real keys exist."""
import io
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

FIX = Path(__file__).parent / "fixtures"


class FakeResp:
    def __init__(self, status=200, js=None, content=b"", headers=None):
        self.status_code, self._js, self.content = status, js, content or (json.dumps(js).encode() if js is not None else b"")
        self.headers = headers or {"Content-Type": "application/json"}
        self.text = self.content.decode(errors="ignore")

    def json(self):
        return self._js


def _jpeg():
    b = io.BytesIO()
    Image.new("RGB", (800, 800), (40, 120, 200)).save(b, "JPEG")
    return b.getvalue()


@pytest.fixture
def fake_net(monkeypatch):
    from tsayad import http
    calls = []
    query = json.loads((FIX / "product_query.json").read_text())

    def fake(method, url, **kw):
        calls.append((method, url, kw))
        if "aliexpress.com/sync" in url:
            m = kw["data"]["method"]
            if m == "aliexpress.affiliate.product.query":
                return FakeResp(js=query)
            if m == "aliexpress.affiliate.hotproduct.query":
                return FakeResp(js={"error_response": {"code": "InsufficientPermission", "msg": "no access"}})
            if m == "aliexpress.affiliate.link.generate":
                src = kw["data"]["source_values"].split(",")
                return FakeResp(js={"aliexpress_affiliate_link_generate_response": {"resp_result": {"resp_code": 200, "result": {
                    "promotion_links": {"promotion_link": [{"source_value": s, "promotion_link": "https://s.click.aliexpress.com/e/_gen"} for s in src]}}}}})
            if m == "aliexpress.affiliate.productdetail.get":
                pid = kw["data"]["product_ids"]
                prods = [p for p in query["aliexpress_affiliate_product_query_response"]["resp_result"]["result"]["products"]["product"]
                         if str(p["product_id"]) == pid]
                return FakeResp(js={"aliexpress_affiliate_productdetail_get_response": {"resp_result": {"resp_code": 200,
                                    "result": {"products": {"product": prods}}}}})
        if "alicdn.com" in url:
            return FakeResp(content=_jpeg(), headers={"Content-Type": "image/jpeg"})
        if "api.telegram.org" in url:
            meth = url.rsplit("/", 1)[1]
            if meth == "sendPhoto":
                return FakeResp(js={"ok": True, "result": {"message_id": 777}})
            return FakeResp(js={"ok": True, "result": {"message_id": 1}})
        return FakeResp(status=404, js={})

    monkeypatch.setattr(http, "request", fake)
    return calls


def test_signature_is_deterministic_and_sorted():
    from tsayad import aliexpress as ae
    s1 = ae.sign({"b": "2", "a": "1", "sign": "x"}, "secret")
    s2 = ae.sign({"a": "1", "b": "2"}, "secret")
    import hashlib, hmac
    assert s1 == s2 == hmac.new(b"secret", b"a1b2", hashlib.sha256).hexdigest().upper()


def test_normalize_and_filters(fake_net):
    from tsayad import aliexpress as ae, scoring
    prods = ae.product_query("phone holder")
    assert [p["id"] for p in prods][0] == "1005006000000001"
    good, low_fb, high_comm = prods
    assert good["price"] == 24.9 and good["discount"] == 50 and good["feedback"] == 97.2
    assert scoring.hard_filters(good) is None
    assert "משוב" in scoring.hard_filters(low_fb)
    # commission is capped: 50% commission can't outscore a better product
    s_good, _ = scoring.score(good, 1.0)
    s_comm, br = scoring.score(high_comm, 1.0)
    assert br["commission"] == 10.0 and s_good > s_comm


def test_scan_queue_and_links(fake_net):
    from tsayad import db, discovery
    stats = discovery.run_scan(force=True)
    assert stats["fetched"] >= 3
    q = {r["id"]: dict(r) for r in db.q("SELECT * FROM products")}
    assert q["1005006000000002"]["status"] == "rejected"
    assert q["1005006000000001"]["status"] == "queued" and q["1005006000000001"]["link_ok"] == 1
    # the product without a promotion link received one from link.generate (own tracking id)
    assert q["1005006000000003"]["affiliate_link"].startswith("https://s.click.aliexpress.com/")
    sent = [c for c in fake_net if "aliexpress" in c[1] and c[2]["data"]["method"] == "aliexpress.affiliate.link.generate"]
    assert sent and sent[0][2]["data"]["tracking_id"] == "tsayad_test"


def test_publish_flow_no_duplicates(fake_net):
    from tsayad import db, discovery, publisher
    discovery.run_scan(force=True)
    r1 = publisher.publish_one()
    assert r1["status"] == "published" and r1["message_id"] == 777
    r2 = publisher.publish_one()          # not due yet (2h interval)
    assert r2["status"] == "not_due"
    r3 = publisher.publish_one(force=True)  # forced: must pick a DIFFERENT product
    assert r3["status"] == "published" and r3["product"] != r1["product"]
    pub = db.q("SELECT product_id FROM posts WHERE platform='telegram' AND status='published'")
    assert len({p["product_id"] for p in pub}) == len(pub) == 2
    cap = db.one("SELECT caption FROM posts WHERE id=1")["caption"]
    assert "גילוי נאות" in cap and "₪24.9" in cap and "t.example.workers.dev/go/" in cap
    # media were produced
    files = list((publisher.MEDIA_DIR).glob(f"{r1['product']}_*"))
    assert any(f.suffix == ".jpg" for f in files)


def test_empty_queue_never_posts_junk(fake_net, monkeypatch):
    from tsayad import db, publisher
    r = publisher.publish_one(force=True)
    assert r["status"] == "empty_queue"
    assert db.one("SELECT COUNT(*) n FROM posts")["n"] == 0


def test_telegram_failure_retry_and_alert(fake_net, monkeypatch):
    from tsayad import db, discovery, publisher, telegram
    discovery.run_scan(force=True)
    monkeypatch.setattr(telegram, "send_product", lambda *a: (_ for _ in ()).throw(telegram.TelegramError("429 Too Many")))
    r = publisher.publish_one(force=True)
    assert r["status"] == "failed"
    assert db.one("SELECT status FROM posts ORDER BY id DESC")["status"] == "failed"
    assert db.one("SELECT COUNT(*) n FROM alerts WHERE level='error'")["n"] >= 1
    assert db.one("SELECT COUNT(*) n FROM products WHERE status='published'")["n"] == 0  # not marked published


def test_lock_prevents_double_run(fake_net):
    from tsayad import db, discovery, publisher
    discovery.run_scan(force=True)
    db.kv_set("publish_lock", db.now_iso())
    assert publisher.publish_one(force=True)["status"] == "locked"


def test_content_never_invents():
    from tsayad import content
    p = {"title_he": "מחזיק טלפון מגנטי לרכב", "price": 24.9, "original_price": 25.5, "discount": 2, "feedback": 96.0,
         "orders": 800, "category": "car"}
    out = content.build(p, "classic", "https://s.click.aliexpress.com/e/_x")
    assert "<s>" not in out["telegram"]  # 2% isn't presented as a discount
    assert "הכי זול" not in out["telegram"] and len(out["telegram"]) <= 1024
    assert content._BANNED.search("רק ב-20 ₪")


def test_site_and_encrypted_dashboard(fake_net):
    from tsayad import config, crypto, dashboard, discovery, publisher, site
    discovery.run_scan(force=True)
    publisher.publish_one()
    out = site.build()
    assert (out / "index.html").exists() and (out / "sitemap.xml").exists() and (out / "robots.txt").exists()
    html = (out / "index.html").read_text()
    assert 'dir="rtl"' in html and "גילוי נאות" in html
    prod_pages = list((out / "p").glob("*/index.html"))
    assert prod_pages and 'rel="sponsored' in prod_pages[0].read_text()
    lock = dashboard.build()
    txt = lock.read_text()
    assert "מוצרים" not in txt.split("__BUNDLE__")[0][-10:]  # content is not readable
    bundle = json.loads(txt.split("const B = ")[1].split(";\n")[0])
    plain = crypto.password_decrypt(bundle, "pw-test")
    assert "AI BUSINESS IMPROVEMENTS" in plain and "מרכז הניהול" in plain


def test_dashboard_decrypts_in_browser_crypto(fake_net, tmp_path):
    """Same bundle decrypted with WebCrypto in Node – proves the browser unlock works."""
    from tsayad import crypto
    b = crypto.password_encrypt("שלום דשבורד", "pw-test")
    js = f"""
const B={json.dumps(b)};const b64=s=>Uint8Array.from(Buffer.from(s,'base64'));
(async()=>{{const base=await crypto.subtle.importKey('raw',new TextEncoder().encode('pw-test'),'PBKDF2',false,['deriveKey']);
const key=await crypto.subtle.deriveKey({{name:'PBKDF2',salt:b64(B.salt),iterations:B.iter,hash:'SHA-256'}},base,{{name:'AES-GCM',length:256}},false,['decrypt']);
const pt=await crypto.subtle.decrypt({{name:'AES-GCM',iv:b64(B.iv)}},key,b64(B.ct));console.log(new TextDecoder().decode(pt));}})();"""
    f = tmp_path / "t.js"
    f.write_text(js)
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "שלום דשבורד", out.stderr


def test_db_encryption_roundtrip():
    from tsayad import crypto
    k = crypto.new_key()
    assert crypto.decrypt_bytes(crypto.encrypt_bytes(b"sqlite-bytes", k), k) == b"sqlite-bytes"


def test_tracker_signature_matches_worker_format():
    from tsayad import tracking
    link = tracking.link("https://s.click.aliexpress.com/e/_x", "100", "tg", 5, "classic")
    assert link.startswith("https://t.example.workers.dev/go/100?") and "k=" in link


def test_restart_recovery_and_reports(fake_net):
    from tsayad import db, discovery, publisher, reports
    discovery.run_scan(force=True)
    publisher.publish_one()
    db.close()          # simulate crash / new runner with same DB
    db.connect()
    assert publisher.is_due() is False
    txt = reports.daily_text()
    assert "דוח יומי" in txt and "פורסמו בהצלחה: 1" in txt


def test_manager_without_click_data_does_nothing():
    from tsayad import config, manager
    old = config.TRACKER_URL
    config.TRACKER_URL = ""
    try:
        assert manager.learn()["status"] == "no_click_data"
    finally:
        config.TRACKER_URL = old


def test_worker_redirect_and_stats_signed(tmp_path):
    """Runs the real Cloudflare Worker code in Node with a fake D1 and links signed by Python."""
    from urllib.parse import urlparse
    from tsayad import tracking
    link = tracking.link("https://s.click.aliexpress.com/e/_abc", "1005", "tg", 7, "short")
    path = urlparse(link).path + "?" + urlparse(link).query
    since, ts = "2026-01-01", "TS"
    js = f"""
import w from '{(Path(__file__).parent.parent / 'worker/src/index.js').as_posix()}';
const runs=[]; const DB={{prepare:(q)=>({{bind:(...a)=>({{run:async()=>runs.push(a),all:async()=>({{results:[{{day:'2026-11-20',n:3}}]}})}})}})}};
const env={{TRACKER_SECRET:'s3cr3t',DB,SITE_URL:'https://x.pages.dev'}}; const ctx={{waitUntil:p=>p}};
const r=await w.fetch(new Request('https://w.dev{path}',{{headers:{{'user-agent':'Mozilla'}}}}),env,ctx);
const bad=await w.fetch(new Request('https://w.dev/go/1005?s=tg&p=7&v=short&u=aHR0cHM6Ly9ldmlsLmNvbS8&k=000'),env,ctx);
const t=String(Math.floor(Date.now()/1000));
const crypto2=globalThis.crypto; const k=await crypto2.subtle.importKey('raw',new TextEncoder().encode('s3cr3t'),{{name:'HMAC',hash:'SHA-256'}},false,['sign']);
const sig=[...new Uint8Array(await crypto2.subtle.sign('HMAC',k,new TextEncoder().encode('stats|{since}|'+t)))].map(b=>b.toString(16).padStart(2,'0')).join('').slice(0,20);
const st=await w.fetch(new Request('https://w.dev/stats?since={since}&t='+t+'&k='+sig),env,ctx);
const st2=await w.fetch(new Request('https://w.dev/stats?since={since}&t='+t+'&k=bad'),env,ctx);
console.log(JSON.stringify({{status:r.status,loc:r.headers.get('location'),runs:runs.length,bad:bad.headers.get('location'),stats:st.status,stats_bad:st2.status}}));
"""
    f = tmp_path / "w.mjs"
    f.write_text(js)
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=60)
    res = json.loads(out.stdout.strip() or "{}") if out.returncode == 0 else {}
    assert res, out.stderr
    assert res["status"] == 302 and res["loc"] == "https://s.click.aliexpress.com/e/_abc" and res["runs"] == 1
    assert res["bad"].startswith("https://x.pages.dev")        # forged link -> no open redirect
    assert res["stats"] == 200 and res["stats_bad"] == 403
    # python signs stats the same way the worker verifies
    assert len(tracking.sig("stats|a|b")) == 20


def test_dashboard_tabs_render_without_js_errors(fake_net, tmp_path):
    """Renders every dashboard tab in jsdom (skipped if jsdom isn't installed)."""
    import os
    from tsayad import dashboard, discovery, publisher
    jsdom_dir = os.environ.get("JSDOM_DIR", "/tmp/jsd")
    if not Path(jsdom_dir, "node_modules", "jsdom").exists():
        pytest.skip("jsdom not installed")
    discovery.run_scan(force=True)
    publisher.publish_one()
    html = dashboard.render_plain()
    (tmp_path / "d.html").write_text(html, encoding="utf-8")
    js = f"""
const {{JSDOM}} = require('{jsdom_dir}/node_modules/jsdom');
const fs=require('fs'); const errs=[];
const dom=new JSDOM(fs.readFileSync('{tmp_path}/d.html','utf8'),{{runScripts:'dangerously',url:'https://x.pages.dev/admin/'}});
dom.window.addEventListener('error',e=>errs.push(e.message));
const out={{}};
for (const b of dom.window.document.querySelectorAll('nav button')) {{ b.click(); out[b.dataset.id]=dom.window.document.getElementById('main').textContent.length; }}
console.log(JSON.stringify({{errs,out}}));"""
    f = tmp_path / "t.js"
    f.write_text(js)
    r = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=60)
    res = json.loads(r.stdout.strip())
    assert not res["errs"], res["errs"]
    assert set(res["out"]) == {"home", "products", "posts", "revenue", "marketing", "ai", "settings"}
    assert all(v > 50 for v in res["out"].values())
