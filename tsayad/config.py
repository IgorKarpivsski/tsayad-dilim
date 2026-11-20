"""Central configuration. Secrets come ONLY from environment variables (.env locally,
GitHub Secrets in CI). Non-secret tunables live in config/settings.json."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TSAYAD_DATA_DIR", ROOT / "data"))
OUT_DIR = Path(os.environ.get("TSAYAD_OUT_DIR", ROOT / "build"))
ASSETS = ROOT / "assets"
FONT_PATH = ASSETS / "fonts" / "Heebo.ttf"
SETTINGS_FILE = ROOT / "config" / "settings.json"


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _settings() -> dict:
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    return {}


@dataclass
class Settings:
    raw: dict = field(default_factory=_settings)

    def get(self, key: str, default=None):
        cur = self.raw
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur


S = Settings()

# ---- Brand -------------------------------------------------------------------
BRAND = {
    "name_he": S.get("brand.name_he", "צייד הדילים"),
    "name_en": S.get("brand.name_en", "Tsayad HaDilim"),
    "slogan": S.get("brand.slogan", "צדים בשבילכם את הדילים ששווה להכיר – מסוננים, בדוקים, בעברית"),
    "telegram_username": env("TELEGRAM_CHANNEL_USERNAME", S.get("brand.telegram_username", "tsayad_dilim")),
    "site_url": env("SITE_URL", S.get("brand.site_url", "https://tsayad-dilim.pages.dev")).rstrip("/"),
    "colors": S.get("brand.colors", {
        "primary": "#FF5A36", "dark": "#14213D", "accent": "#FFC93C", "bg": "#FFF8F0", "text": "#1B1B1B"}),
}

# ---- Secrets / connections ---------------------------------------------------
AE_APP_KEY = env("AE_APP_KEY")
AE_APP_SECRET = env("AE_APP_SECRET")
AE_TRACKING_ID = env("AE_TRACKING_ID")
AE_GATEWAY = env("AE_GATEWAY", "https://api-sg.aliexpress.com/sync")

TG_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TG_CHANNEL_ID = env("TELEGRAM_CHANNEL_ID")          # @tsayad_dilim or -100...
TG_ADMIN_CHAT_ID = env("TELEGRAM_ADMIN_CHAT_ID")    # your private chat id for alerts

FB_PAGE_ID = env("FB_PAGE_ID")
FB_PAGE_TOKEN = env("FB_PAGE_TOKEN")
IG_USER_ID = env("IG_USER_ID")
GRAPH_VERSION = env("GRAPH_API_VERSION", "v26.0")

TIKTOK_CLIENT_KEY = env("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = env("TIKTOK_CLIENT_SECRET")
TIKTOK_REFRESH_TOKEN = env("TIKTOK_REFRESH_TOKEN")

GEMINI_API_KEY = env("GEMINI_API_KEY")
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-flash-lite-latest")

TRACKER_URL = env("TRACKER_URL").rstrip("/")         # Cloudflare Worker, optional
TRACKER_SECRET = env("TRACKER_SECRET")

DASHBOARD_PASSWORD = env("DASHBOARD_PASSWORD")
DATA_KEY = env("DATA_KEY")                           # base64 32 bytes – encrypts the DB at rest

# ---- Tunables ----------------------------------------------------------------
POST_INTERVAL_MIN = int(S.get("publishing.interval_minutes", 120))
QUIET_HOURS = S.get("publishing.quiet_hours", [])   # e.g. [2,3,4,5] Israel time; empty = 24/7
REPOST_COOLDOWN_DAYS = int(S.get("publishing.repost_cooldown_days", 45))
MIN_SCORE = float(S.get("scoring.min_score", 55))
MIN_FEEDBACK = float(S.get("scoring.min_feedback_pct", 90))
MIN_ORDERS = int(S.get("scoring.min_orders", 50))
SCAN_EVERY_HOURS = int(S.get("discovery.scan_every_hours", 24))
TIMEZONE = "Asia/Jerusalem"


def status_of_connections() -> dict:
    """Honest connection status: 'configured' only means keys exist; live checks set 'active'."""
    def st(ok: bool) -> str:
        return "configured" if ok else "pending"
    return {
        "aliexpress": st(bool(AE_APP_KEY and AE_APP_SECRET and AE_TRACKING_ID)),
        "telegram": st(bool(TG_BOT_TOKEN and TG_CHANNEL_ID)),
        "telegram_alerts": st(bool(TG_BOT_TOKEN and TG_ADMIN_CHAT_ID)),
        "facebook": st(bool(FB_PAGE_ID and FB_PAGE_TOKEN)),
        "instagram": st(bool(IG_USER_ID and FB_PAGE_TOKEN)),
        "tiktok": st(bool(TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET and TIKTOK_REFRESH_TOKEN)),
        "ai_writer": st(bool(GEMINI_API_KEY)),
        "click_tracker": st(bool(TRACKER_URL and TRACKER_SECRET)),
        "dashboard": st(bool(DASHBOARD_PASSWORD)),
        "data_encryption": st(bool(DATA_KEY)),
    }
