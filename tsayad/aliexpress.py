"""Official AliExpress Open Platform (Affiliate) client.

Gateway: https://api-sg.aliexpress.com/sync  (business APIs)
Signature (sign_method=sha256): sort all params (except `sign`) by key, concatenate
key+value with no separators, HMAC-SHA256 with the App Secret, uppercase hex.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Any

from . import config, http, log

L = log.get("aliexpress")

PRODUCT_FIELDS = ",".join([
    "product_id", "product_title", "product_main_image_url", "product_small_image_urls",
    "target_sale_price", "target_sale_price_currency", "target_original_price",
    "target_original_price_currency", "discount", "evaluate_rate", "lastest_volume",
    "commission_rate", "hot_product_commission_rate", "promotion_link", "product_detail_url",
    "first_level_category_name", "second_level_category_name", "shop_id", "shop_url", "ship_to_days",
])


class AliExpressError(Exception):
    pass


def sign(params: dict[str, Any], secret: str, api_path: str = "") -> str:
    """api_path is only used for /rest system APIs (e.g. token APIs); business APIs pass ''."""
    base = api_path + "".join(f"{k}{params[k]}" for k in sorted(params) if k != "sign" and params[k] is not None)
    return hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest().upper()


def configured() -> bool:
    return bool(config.AE_APP_KEY and config.AE_APP_SECRET and config.AE_TRACKING_ID)


def call(method: str, **biz: Any) -> dict:
    if not configured():
        raise AliExpressError("AliExpress not configured (AE_APP_KEY / AE_APP_SECRET / AE_TRACKING_ID)")
    params: dict[str, Any] = {
        "app_key": config.AE_APP_KEY,
        "method": method,
        "timestamp": str(int(time.time() * 1000)),
        "sign_method": "sha256",
        "format": "json",
        "v": "2.0",
    }
    params.update({k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
                   for k, v in biz.items() if v is not None and v != ""})
    params["sign"] = sign(params, config.AE_APP_SECRET)
    r = http.request("POST", config.AE_GATEWAY, data=params,
                     headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"})
    try:
        data = r.json()
    except ValueError as e:
        raise AliExpressError(f"{method}: non-JSON response HTTP {r.status_code}") from e
    if "error_response" in data:
        er = data["error_response"]
        raise AliExpressError(f"{method}: {er.get('code')} {er.get('msg')} {er.get('sub_msg', '')}".strip())
    key = method.replace(".", "_") + "_response"
    body = data.get(key, data)
    resp = body.get("resp_result", body)
    code = resp.get("resp_code")
    if code not in (None, 200, "200"):
        raise AliExpressError(f"{method}: resp_code={code} {resp.get('resp_msg')}")
    return resp.get("result", resp) or {}


# ---------------------------------------------------------------------------
def _pct(v) -> float | None:
    if v in (None, ""):
        return None
    m = re.search(r"[\d.]+", str(v))
    return float(m.group()) if m else None


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except ValueError:
        return None


def normalize(p: dict) -> dict:
    imgs = p.get("product_small_image_urls") or {}
    if isinstance(imgs, dict):
        imgs = imgs.get("string", [])
    price = _num(p.get("target_sale_price"))
    orig = _num(p.get("target_original_price"))
    disc = _pct(p.get("discount"))
    if disc is None and price and orig and orig > price:
        disc = round((1 - price / orig) * 100)
    return {
        "id": str(p.get("product_id", "")),
        "title_he": (p.get("product_title") or "").strip(),
        "image_url": p.get("product_main_image_url") or "",
        "images": imgs if isinstance(imgs, list) else [],
        "price": price,
        "original_price": orig,
        "currency": p.get("target_sale_price_currency") or "ILS",
        "discount": disc or 0.0,
        "feedback": _pct(p.get("evaluate_rate")),
        "orders": int(_num(p.get("lastest_volume")) or 0),
        "commission": _pct(p.get("hot_product_commission_rate")) or _pct(p.get("commission_rate")) or 0.0,
        "detail_url": p.get("product_detail_url") or "",
        "affiliate_link": p.get("promotion_link") or "",
        "category": p.get("second_level_category_name") or p.get("first_level_category_name") or "",
        "shop_id": str(p.get("shop_id") or ""),
        "shop_url": p.get("shop_url") or "",
        "ship_to_days": p.get("ship_to_days"),
    }


def _products(result: dict) -> list[dict]:
    prods = (result.get("products") or {})
    if isinstance(prods, dict):
        prods = prods.get("product", [])
    return [normalize(p) for p in (prods or [])]


COMMON = dict(target_currency="ILS", target_language="HE", ship_to_country="IL")


def product_query(keywords: str, page: int = 1, page_size: int = 50, sort: str = "LAST_VOLUME_DESC",
                  category_ids: str | None = None) -> list[dict]:
    res = call("aliexpress.affiliate.product.query", keywords=keywords, category_ids=category_ids,
               page_no=page, page_size=page_size, sort=sort, fields=PRODUCT_FIELDS,
               tracking_id=config.AE_TRACKING_ID, **COMMON)
    return _products(res)


def hot_products(keywords: str = "", page: int = 1, page_size: int = 50, category_ids: str | None = None) -> list[dict]:
    res = call("aliexpress.affiliate.hotproduct.query", keywords=keywords, category_ids=category_ids,
               page_no=page, page_size=page_size, sort="LAST_VOLUME_DESC", fields=PRODUCT_FIELDS,
               tracking_id=config.AE_TRACKING_ID, **COMMON)
    return _products(res)


def product_detail(product_ids: list[str]) -> list[dict]:
    res = call("aliexpress.affiliate.productdetail.get", product_ids=",".join(product_ids),
               fields=PRODUCT_FIELDS, tracking_id=config.AE_TRACKING_ID, country="IL",
               target_currency="ILS", target_language="HE")
    return _products(res)


def categories() -> list[dict]:
    res = call("aliexpress.affiliate.category.get")
    cats = res.get("categories") or {}
    return cats.get("category", []) if isinstance(cats, dict) else cats


def generate_links(urls: list[str]) -> dict[str, str]:
    """Returns {source_url: promotion_link} using YOUR tracking id only."""
    res = call("aliexpress.affiliate.link.generate", promotion_link_type="0",
               source_values=",".join(urls), tracking_id=config.AE_TRACKING_ID)
    links = (res.get("promotion_links") or {})
    if isinstance(links, dict):
        links = links.get("promotion_link", [])
    return {l.get("source_value"): l.get("promotion_link") for l in links or [] if l.get("promotion_link")}


def order_list(start: str, end: str, status: str = "Payment Completed", page: int = 1) -> list[dict]:
    """start/end: 'YYYY-MM-DD HH:MM:SS'. Availability depends on your account permissions."""
    res = call("aliexpress.affiliate.order.list", start_time=start, end_time=end, status=status,
               page_no=page, page_size=50)
    orders = res.get("orders") or {}
    if isinstance(orders, dict):
        orders = orders.get("order", [])
    return orders or []


def is_valid_affiliate_link(link: str) -> bool:
    return bool(re.match(r"^https://(s\.click\.aliexpress\.com|[a-z]+\.aliexpress\.com)/", link or ""))


def probe_permissions() -> dict:
    """Live check of which methods this account can actually use (run via `python -m tsayad check`)."""
    out = {}
    tests = {
        "aliexpress.affiliate.product.query": lambda: product_query("phone holder", page_size=1),
        "aliexpress.affiliate.hotproduct.query": lambda: hot_products("led", page_size=1),
        "aliexpress.affiliate.category.get": categories,
        "aliexpress.affiliate.link.generate": lambda: generate_links(["https://www.aliexpress.com/item/1005006833755847.html"]),
        "aliexpress.affiliate.order.list": lambda: order_list(
            time.strftime("%Y-%m-%d 00:00:00", time.gmtime(time.time() - 86400 * 3)),
            time.strftime("%Y-%m-%d 23:59:59", time.gmtime())),
    }
    for name, fn in tests.items():
        try:
            r = fn()
            out[name] = {"ok": True, "items": len(r) if hasattr(r, "__len__") else None}
        except Exception as e:  # noqa: BLE001
            out[name] = {"ok": False, "error": str(e)[:300]}
    return out
