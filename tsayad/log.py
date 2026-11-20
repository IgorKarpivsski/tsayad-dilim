import logging
import sys

from . import config

config.DATA_DIR.mkdir(parents=True, exist_ok=True)

_fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("tsayad")
if not log.handlers:
    log.setLevel(logging.INFO)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(_fmt)
    log.addHandler(h)
    fh = logging.FileHandler(config.DATA_DIR / "tsayad.log", encoding="utf-8")
    fh.setFormatter(_fmt)
    log.addHandler(fh)


def get(name: str) -> logging.Logger:
    return log.getChild(name)
