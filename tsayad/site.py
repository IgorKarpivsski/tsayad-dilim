"""Static, SEO-friendly Hebrew RTL site → deployed free to Cloudflare Pages."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config, content, db, log, media, tracking

L = log.get("site")
TPL = Path(__file__).parent / "templates" / "site"


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TPL)), autoescape=select_autoescape(["html"]))


def _products(limit: int = 600) -> list[dict]:
    rows = db.q("SELECT * FROM products WHERE status='published' AND published_at>=datetime('now','-120 day') "
                "ORDER BY published_at DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        p = dict(r)
        p["f"] = content.facts(p)
        out.append(p)
    return out


def build(out: Path | None = None) -> Path:
    out = out or (config.OUT_DIR / "site")
    out.mkdir(parents=True, exist_ok=True)
    (out / "assets").mkdir(exist_ok=True)
    shutil.copy(config.FONT_PATH, out / "assets" / "Heebo.ttf")
    media.brand_assets(out / "assets")
    env = _env()
    cats = config.S.get("discovery.categories", {})
    base = config.BRAND["site_url"]
    ctx = dict(brand=config.BRAND, c=config.BRAND["colors"], cats=cats, disclosure=content.DISCLOSURE,
               price_note=content.PRICE_NOTE, og_image=f"{base}/assets/banner.png", jsonld=None)
    prods = _products()
    urls = [base + "/"]

    def write(rel: str, html: str):
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")

    write("index.html", env.get_template("list.html").render(
        **ctx, title=f"{config.BRAND['name_he']} | דילים מאליאקספרס בעברית – מסוננים ובדוקים",
        description="דילים מ-AliExpress בעברית ובשקלים: מוצרים עם משוב חיובי גבוה וביקוש מוכח, מתעדכן כל שעתיים.",
        canonical=base + "/", heading=config.BRAND["slogan"],
        intro="מוצרים שעברו סינון אוטומטי: משוב חיובי גבוה, מאות הזמנות ומחיר מאומת. מתעדכן לאורך היום.",
        products=prods[:60]))
    for slug, cat in cats.items():
        items = [p for p in prods if p["category"] == slug]
        write(f"c/{slug}/index.html", env.get_template("list.html").render(
            **ctx, title=f"{cat['he']} מאליאקספרס – דילים נבחרים | {config.BRAND['name_he']}",
            description=f"הדילים הכי שווים בקטגוריית {cat['he']} מ-AliExpress, בעברית ובשקלים.",
            canonical=f"{base}/c/{slug}/", heading=f"{cat['he']} – דילים נבחרים",
            intro=f"מוצרים נבחרים בקטגוריית {cat['he']}, מסודרים מהחדש לישן.", products=items))
        urls.append(f"{base}/c/{slug}/")
    sales = [p for p in prods if (p.get("discount") or 0) >= 30]
    write("c/deals/index.html", env.get_template("list.html").render(
        **ctx, title=f"מבצעים חמים – הנחות של 30% ומעלה | {config.BRAND['name_he']}", description="מוצרים בהנחה משמעותית לפי נתוני AliExpress.",
        canonical=f"{base}/c/deals/", heading="מבצעים חמים", intro="מוצרים עם הנחה של 30% ומעלה בזמן הבדיקה.", products=sales))
    urls.append(f"{base}/c/deals/")
    for p in prods:
        buy = tracking.link(p["affiliate_link"], p["id"], "web")
        upd = (p.get("price_checked_at") or p.get("published_at") or "")[:10]
        ld = {"@context": "https://schema.org", "@type": "Product", "name": p["title_he"], "image": p["image_url"],
              "offers": {"@type": "Offer", "price": p["price"], "priceCurrency": "ILS", "url": f"{base}/p/{p['id']}/"}}
        write(f"p/{p['id']}/index.html", env.get_template("product.html").render(
            **{**ctx, "jsonld": json.dumps(ld, ensure_ascii=False)},
            title=f"{content.short_title(p['title_he'], 60)} – {p['f']['price']} | {config.BRAND['name_he']}",
            description=f"{content.short_title(p['title_he'], 110)}. {p['f']['feedback']}.",
            canonical=f"{base}/p/{p['id']}/", p=p, buy=buy, updated=upd,
            cat_he=cats.get(p["category"], {}).get("he", ""), hook=content.CATEGORY_HOOK.get(p["category"], "")))
        urls.append(f"{base}/p/{p['id']}/")
    write("about/index.html", env.get_template("about.html").render(
        **ctx, title=f"אודות וגילוי נאות | {config.BRAND['name_he']}", description="איך אנחנו בוחרים מוצרים, גילוי נאות ופרטיות.",
        canonical=f"{base}/about/"))
    urls.append(f"{base}/about/")
    today = datetime.now(timezone.utc).date().isoformat()
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"<url><loc>{escape(u)}</loc><lastmod>{today}</lastmod></url>" for u in urls]
    sm.append("</urlset>")
    write("sitemap.xml", "\n".join(sm))
    write("robots.txt", f"User-agent: *\nAllow: /\nDisallow: /admin/\nSitemap: {base}/sitemap.xml\n")
    write("_headers", "/media/*\n  Cache-Control: public, max-age=86400\n/admin/*\n  X-Robots-Tag: noindex\n  Cache-Control: no-store\n")
    write("404.html", env.get_template("list.html").render(**ctx, title="העמוד לא נמצא", description="", canonical=base,
                                                         heading="העמוד לא נמצא", intro="אולי המוצר כבר לא זמין. הנה הדילים האחרונים:",
                                                         products=prods[:12]))
    L.info("site built: %d products, %d urls", len(prods), len(urls))
    return out
