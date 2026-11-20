import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="tsayad_test_")
os.environ["TSAYAD_DATA_DIR"] = str(Path(_tmp) / "data")
os.environ["TSAYAD_OUT_DIR"] = str(Path(_tmp) / "build")
# test-only credentials – never real
os.environ.update({"AE_APP_KEY": "123456", "AE_APP_SECRET": "testsecret", "AE_TRACKING_ID": "tsayad_test",
                   "TELEGRAM_BOT_TOKEN": "1:TEST", "TELEGRAM_CHANNEL_ID": "@tsayad_dilim", "TELEGRAM_ADMIN_CHAT_ID": "42",
                   "DASHBOARD_PASSWORD": "pw-test", "TRACKER_URL": "https://t.example.workers.dev", "TRACKER_SECRET": "s3cr3t"})


@pytest.fixture(autouse=True)
def fresh_db():
    from tsayad import db
    db.close()
    p = db.db_path()
    if p.exists():
        p.unlink()
    db.connect()
    yield
    db.close()
