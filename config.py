"""
config.py
---------
Tiny .env loader + settings. No extra dependency (python-dotenv not needed).
Copy `.env.example` to `.env` and fill in whatever you want to enable; every
feature has a working offline fallback when its key is missing.
"""

import os

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load_env(path=_ENV_PATH):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k.strip(), v)


load_env()


def env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default
