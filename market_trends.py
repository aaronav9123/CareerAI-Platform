"""
market_trends.py
----------------
Demand / salary / growth insights per career, from data/market_trends.json.
The figures are indicative estimates (see the _meta note in the JSON) - the
page says so. If Adzuna is configured, the live opening count is added.
"""

import json
import os

import live_jobs

_PATH = os.path.join(os.path.dirname(__file__), "data", "market_trends.json")
with open(_PATH, encoding="utf-8") as f:
    _DATA = json.load(f)

YEARS = _DATA["_meta"]["years"]
NOTE = _DATA["_meta"]["note"]
CAREERS = _DATA["careers"]


def get_trend(career):
    t = CAREERS.get(career)
    if not t:
        return None
    return {**t, "career": career}


def compare_all(highlight=None):
    rows = []
    for name, t in CAREERS.items():
        rows.append({"career": name, "demand_index": t["demand_index"],
                     "growth": t["yoy_growth_pct"], "mid": t["salary_lpa"]["mid"],
                     "highlight": name == highlight})
    rows.sort(key=lambda r: -r["demand_index"])
    return rows


def live_openings(career):
    return live_jobs.live_opening_count(career)
