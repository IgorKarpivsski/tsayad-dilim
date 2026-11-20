"""Telegram Bot API (official). The bot must be an admin of the channel with 'Post messages'."""
from __future__ import annotations

import json
from pathlib import Path

from . import config, http, log

L = log.get("telegram")


class TelegramError(Exception):
    pass


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/{method}"


def _call(method: str, data: dict | None = None, files: dict | None = None) -> dict:
    if not config.TG_BOT_TOKEN:
        raise TelegramError("TELEGRAM_BOT_TOKEN missing")
    r = http.request("POST", _api(method), data=data, files=files, retries=4, timeout=60)
    try:
        js = r.json()
    except ValueError as e:
        raise TelegramError(f"{method}: HTTP {r.status_code}") from e
    if not js.get("ok"):
        raise TelegramError(f"{method}: {js.get('error_code')} {js.get('description')}")
    return js["result"]


def get_me() -> dict:
    return _call("getMe")


def channel_check() -> dict:
    """Verifies the bot can see the channel and is an administrator who can post."""
    me = get_me()
    chat = _call("getChat", {"chat_id": config.TG_CHANNEL_ID})
    member = _call("getChatMember", {"chat_id": config.TG_CHANNEL_ID, "user_id": me["id"]})
    can_post = member.get("status") == "creator" or member.get("can_post_messages", False)
    return {"bot": me.get("username"), "channel": chat.get("title"), "username": chat.get("username"),
            "status": member.get("status"), "can_post": bool(can_post)}


def member_count() -> int | None:
    try:
        return int(_call("getChatMemberCount", {"chat_id": config.TG_CHANNEL_ID}))
    except Exception as e:  # noqa: BLE001
        L.warning("member count failed: %s", e)
        return None


def send_product(photo: Path, caption_html: str, buy_url: str) -> int:
    """Posts photo + caption + a 'buy' button. Returns message_id (proof of publication)."""
    markup = {"inline_keyboard": [[{"text": "🛒 לצפייה ורכישה", "url": buy_url}],
                                  [{"text": "📢 שתפו את הערוץ", "url": f"https://t.me/share/url?url=https://t.me/{config.BRAND['telegram_username']}"}]]}
    with open(photo, "rb") as fh:
        res = _call("sendPhoto", {"chat_id": config.TG_CHANNEL_ID, "caption": caption_html, "parse_mode": "HTML",
                                  "reply_markup": json.dumps(markup)}, files={"photo": fh})
    mid = res.get("message_id")
    if not mid:
        raise TelegramError("sendPhoto returned no message_id")
    return int(mid)


def send_text(chat_id: str, text: str, html: bool = True) -> int | None:
    data = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": "true"}
    if html:
        data["parse_mode"] = "HTML"
    return _call("sendMessage", data).get("message_id")


def notify_admin(text: str) -> bool:
    if not (config.TG_BOT_TOKEN and config.TG_ADMIN_CHAT_ID):
        return False
    try:
        send_text(config.TG_ADMIN_CHAT_ID, text)
        return True
    except Exception as e:  # noqa: BLE001
        L.error("admin notify failed: %s", e)
        return False


def flush_alerts() -> int:
    from . import db
    rows = db.q("SELECT id, level, message FROM alerts WHERE sent=0 ORDER BY id LIMIT 20")
    if not rows or not (config.TG_BOT_TOKEN and config.TG_ADMIN_CHAT_ID):
        return 0
    icon = {"error": "🚨", "warning": "⚠️", "info": "ℹ️", "action": "🛠️", "opportunity": "💡", "sale": "💰"}
    text = "\n\n".join(f"{icon.get(r['level'], '•')} {r['message']}" for r in rows)
    if notify_admin(f"<b>צייד הדילים – התראות מערכת</b>\n\n{text}"):
        with db.tx() as c:
            c.executemany("UPDATE alerts SET sent=1 WHERE id=?", [(r["id"],) for r in rows])
        return len(rows)
    return 0
