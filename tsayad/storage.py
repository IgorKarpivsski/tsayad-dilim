"""State persistence for stateless CI runners.

The DB lives on an orphan git branch `data` as `state.db.enc` (AES-GCM encrypted) and is
force-pushed as a single commit, so history never grows. Daily snapshots (last 14) are kept
in `backups/` on the same branch for disaster recovery."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import config, crypto, db, log

L = log.get("storage")
BRANCH = "data"


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd or config.ROOT, check=check, capture_output=True, text=True)


def _has_remote() -> bool:
    r = _git("remote", check=False)
    return r.returncode == 0 and "origin" in r.stdout


def restore() -> str:
    """Fetch and decrypt the DB. Returns a short status string."""
    target = db.db_path()
    if target.exists():
        return "local-db"
    if not (_has_remote() and config.DATA_KEY):
        return "fresh-db"
    r = _git("fetch", "--depth=1", "origin", BRANCH, check=False)
    if r.returncode != 0:
        L.info("no data branch yet – starting fresh")
        return "fresh-db"
    blob = subprocess.run(["git", "show", f"origin/{BRANCH}:state.db.enc"], cwd=config.ROOT, capture_output=True)
    if blob.returncode != 0:
        return "fresh-db"
    target.write_bytes(crypto.decrypt_bytes(blob.stdout, config.DATA_KEY))
    return "restored"


def save(message: str = "state update") -> str:
    db.close()
    src = db.db_path()
    if not src.exists():
        return "nothing"
    if not (_has_remote() and config.DATA_KEY):
        return "local-only"
    enc = crypto.encrypt_bytes(src.read_bytes(), config.DATA_KEY)
    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / "wt"
        prev_backups = Path(tmp) / "prev"
        # keep existing backups
        if _git("fetch", "--depth=1", "origin", BRANCH, check=False).returncode == 0:
            _git("worktree", "add", "--detach", str(prev_backups), f"origin/{BRANCH}", check=False)
        wt.mkdir()
        _git("init", "-q", "-b", BRANCH, cwd=wt)
        (wt / "state.db.enc").write_bytes(enc)
        bdir = wt / "backups"
        bdir.mkdir()
        if (prev_backups / "backups").exists():
            for f in sorted((prev_backups / "backups").glob("*.enc"))[-13:]:
                shutil.copy(f, bdir / f.name)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        (bdir / f"{today}.db.enc").write_bytes(enc)
        (wt / "README.md").write_text("Encrypted Tsayad HaDilim state. Decrypt with DATA_KEY (see BACKUP_RESTORE.md).\n")
        url = _git("remote", "get-url", "origin").stdout.strip()
        _git("add", "-A", cwd=wt)
        _git("-c", "user.name=tsayad-bot", "-c", "user.email=bot@tsayad.local", "commit", "-qm", message, cwd=wt)
        extra = []
        header = subprocess.run(["git", "config", "--get-regexp", r"http\..*\.extraheader"], cwd=config.ROOT,
                                capture_output=True, text=True).stdout.strip()
        if header:  # actions/checkout stores the token as an extraheader
            k, v = header.split(" ", 1)
            extra = ["-c", f"{k}={v}"]
        r = subprocess.run(["git", *extra, "push", "-f", url, f"{BRANCH}:{BRANCH}"], cwd=wt, capture_output=True, text=True)
        _git("worktree", "remove", "--force", str(prev_backups), check=False)
        if r.returncode != 0:
            L.error("push failed: %s", r.stderr[-400:])
            return "push-failed"
    return "saved"


def export_backup(path: Path) -> Path:
    """Manual encrypted backup file (download from the Actions artifact or run locally)."""
    db.close()
    path.write_bytes(crypto.encrypt_bytes(db.db_path().read_bytes(), config.DATA_KEY))
    return path


def import_backup(path: Path) -> None:
    db.close()
    db.db_path().write_bytes(crypto.decrypt_bytes(path.read_bytes(), config.DATA_KEY))
