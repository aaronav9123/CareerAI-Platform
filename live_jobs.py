"""
live_jobs.py
------------
Live job listings with graceful fallback.

Order of preference:
  1. Adzuna API   (free key: https://developer.adzuna.com)  ADZUNA_APP_ID / ADZUNA_APP_KEY
  2. Static sample data in data/job_listings.json  (always available, offline)

Every returned job has the same shape the Jobs page already used
(title, required_skills, salary_range, experience_level, ...) plus company,
location, url and `source`, so the template works for both.
Results are cached in memory for 30 minutes to stay inside API rate limits.
"""

import re
import time

import requests

import ats_scorer
import job_matcher
import semantic
from config import env

CACHE_TTL = 30 * 60
_cache = {}

# Search phrases that work better on a job board than our internal career labels.
CAREER_QUERY = {
    "Software Engineer": "software engineer",
    "ML Engineer": "machine learning engineer",
    "Data Entry Operator": "data entry operator",
    "Business Analyst": "business analyst",
    "Financial Analyst": "financial analyst",
    "Junior Accountant": "junior accountant",
    "Marketing Executive": "marketing executive",
    "Sales Assistant": "sales assistant",
    "Clerk": "office clerk",
    "School Counselor": "school counselor",
    "Professor": "assistant professor",
    "Research Scientist": "research scientist",
}


def adzuna_configured():
    return bool(env("ADZUNA_APP_ID") and env("ADZUNA_APP_KEY"))


def _format_salary(lo, hi, country):
    def fmt(v):
        if country == "in":
            return f"₹{v / 100000:.1f} LPA".replace(".0 ", " ")
        sym = {"gb": "£", "us": "$", "au": "A$", "ca": "C$"}.get(country, "")
        return f"{sym}{int(v):,}"
    if lo and hi and abs(hi - lo) > 1:
        return f"{fmt(lo)} - {fmt(hi)}"
    v = lo or hi
    return fmt(v) if v else "Not disclosed"


def _level(title, desc):
    t = f"{title} {desc}".lower()
    if re.search(r"\b(senior|sr\.?|lead|principal|head|manager)\b", t):
        return "Senior Level"
    if re.search(r"\b(junior|jr\.?|intern|trainee|fresher|entry|graduate|associate)\b", t):
        return "Entry Level"
    return "Mid Level"


def _fetch_adzuna(career, location, page=1):
    country = env("ADZUNA_COUNTRY", "in").lower()
    params = {
        "app_id": env("ADZUNA_APP_ID"),
        "app_key": env("ADZUNA_APP_KEY"),
        "results_per_page": 20,
        "what": CAREER_QUERY.get(career, career),
        "content-type": "application/json",
    }
    if location:
        params["where"] = location
    r = requests.get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}", params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    jobs = []
    for j in data.get("results", []):
        desc = j.get("description", "") or ""
        title = j.get("title", "").replace("<strong>", "").replace("</strong>", "")
        found = semantic.find_in_text(f"{title} {desc}", ats_scorer.SKILL_VOCAB, literal_only=True)
        jobs.append({
            "title": title,
            "career": career,
            "company": (j.get("company") or {}).get("display_name", "Company not listed"),
            "location": (j.get("location") or {}).get("display_name", ""),
            "required_skills": list(found.keys())[:8],
            "salary_range": _format_salary(j.get("salary_min"), j.get("salary_max"), country)
                            if (j.get("salary_min") or j.get("salary_max")) else "Not disclosed",
            "experience_level": _level(title, desc),
            "url": j.get("redirect_url"),
            "posted": (j.get("created") or "")[:10],
            "snippet": re.sub(r"\s+", " ", desc)[:220],
            "source": "Adzuna",
        })
    return jobs, data.get("count")


def get_jobs(user_skills, career, location="", top_n=12):
    """
    Returns (jobs, meta). `meta` = {source, live, total_openings, error}.
    Jobs are ranked: same-career + skill-match for static data; skill-match for live data.
    """
    key = (career, (location or "").strip().lower())
    meta = {"source": "Sample data", "live": False, "total_openings": None, "error": None}

    if adzuna_configured():
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            jobs, total = hit[1], hit[2]
        else:
            try:
                jobs, total = _fetch_adzuna(career, location)
                _cache[key] = (time.time(), jobs, total)
            except Exception as e:
                print("[live_jobs] Adzuna failed:", e)
                meta["error"] = "Live job service is unavailable right now - showing sample listings."
                jobs = None
        if jobs is not None:
            meta.update(source="Adzuna", live=True, total_openings=total)
            user_set = [s for s in user_skills if s]
            enriched = []
            for job in jobs:
                req = job["required_skills"]
                hits = semantic.match_skills(user_set, req) if req else {}
                matched = [s for s in req if hits.get(s)]
                pct = round(len(matched) / len(req) * 100) if req else 0
                enriched.append({**job, "matched_skills": matched, "match_percentage": pct, "same_career": True})
            enriched.sort(key=lambda j: -j["match_percentage"])
            return enriched[:top_n], meta
    elif not meta["error"]:
        meta["error"] = None

    return job_matcher.match_jobs(user_skills, career, top_n), meta


def live_opening_count(career):
    """Number of live openings for the career (None when unavailable)."""
    if not adzuna_configured():
        return None
    key = (career, "")
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[2]
    try:
        jobs, total = _fetch_adzuna(career, "")
        _cache[key] = (time.time(), jobs, total)
        return total
    except Exception as e:
        print("[live_jobs] count failed:", e)
        return None
