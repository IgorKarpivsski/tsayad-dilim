"""SQLite storage. One file, easy to back up, encrypted at rest when stored in git."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY,
  title TEXT, title_he TEXT, category TEXT, keyword TEXT, source TEXT,
  image_url TEXT, images TEXT,
  price REAL, original_price REAL, currency TEXT, discount REAL,
  feedback REAL, orders INTEGER, commission REAL,
  shop_id TEXT, shop_url TEXT, detail_url TEXT,
  affiliate_link TEXT, link_ok INTEGER DEFAULT 0, link_checked_at TEXT,
  score REAL DEFAULT 0, score_breakdown TEXT,
  status TEXT DEFAULT 'new',            -- new | queued | rejected | published
  reject_reason TEXT,
  first_seen TEXT, last_seen TEXT, price_checked_at TEXT, published_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_products_status ON products(status, score);

CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id TEXT, platform TEXT, style TEXT,
  status TEXT,                           -- published | failed | draft | pending | skipped
  external_id TEXT, caption TEXT, error TEXT, attempts INTEGER DEFAULT 0,
  hour INTEGER, created_at TEXT, published_at TEXT, clicks INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_posts_product ON posts(product_id, platform);

CREATE TABLE IF NOT EXISTS price_history (product_id TEXT, price REAL, ts TEXT);

CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT PRIMARY KEY, product_id TEXT, status TEXT,
  paid_amount REAL, commission_est REAL, commission_final REAL, currency TEXT,
  created_at TEXT, paid_at TEXT, settled INTEGER DEFAULT 0, raw TEXT, updated_at TEXT
);

CREATE TABLE IF NOT EXISTS clicks (
  day TEXT, post_id INTEGER, product_id TEXT, source TEXT, variant TEXT, count INTEGER,
  PRIMARY KEY (day, post_id, source)
);

CREATE TABLE IF NOT EXISTS metrics (day TEXT, key TEXT, value REAL, PRIMARY KEY(day, key));
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT, started TEXT, finished TEXT, status TEXT, info TEXT);
CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, level TEXT, message TEXT, sent INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS recommendations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE, title TEXT, problem TEXT, benefit TEXT,
  cost TEXT, complexity TEXT, time_to_implement TEXT, impact TEXT, automatable TEXT,
  score REAL, status TEXT DEFAULT 'open', source TEXT, created_at TEXT, updated_at TEXT);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db_path() -> Path:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return config.DATA_DIR / "tsayad.db"


_conn: sqlite3.Connection | None = None


def connect(path: Path | None = None) -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(path or db_path()), timeout=30)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=DELETE")  # single file -> safe to copy/encrypt
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn


def close() -> None:
    global _conn
    if _conn is not None:
        _conn.commit()
        _conn.close()
        _conn = None


@contextmanager
def tx():
    c = connect()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise


def q(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    return connect().execute(sql, args).fetchall()


def one(sql: str, args: tuple = ()):
    return connect().execute(sql, args).fetchone()


def kv_get(key: str, default=None):
    r = one("SELECT value FROM kv WHERE key=?", (key,))
    return json.loads(r["value"]) if r else default


def kv_set(key: str, value) -> None:
    with tx() as c:
        c.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, json.dumps(value, ensure_ascii=False)))


def metric_set(day: str, key: str, value: float) -> None:
    with tx() as c:
        c.execute("INSERT INTO metrics(day,key,value) VALUES(?,?,?) "
                  "ON CONFLICT(day,key) DO UPDATE SET value=excluded.value", (day, key, value))


def alert(level: str, message: str) -> None:
    with tx() as c:
        c.execute("INSERT INTO alerts(ts,level,message) VALUES(?,?,?)", (now_iso(), level, message))
