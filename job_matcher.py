"""
job_matcher.py
--------------
Matches a user's predicted career + skills against a local sample job
dataset (data/job_listings.json). No external/paid job-search APIs.
"""

import json
import os

import semantic

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "job_listings.json")

with open(DATA_PATH, "r", encoding="utf-8") as f:
    JOB_LISTINGS = json.load(f)


def match_jobs(user_skills, career=None, top_n=8):
    """
    user_skills: list[str] the user selected/has.
    career: predicted career label, used to prioritise same-career listings.

    Returns job dicts enriched with match_percentage and matched_skills,
    sorted with same-career listings first, then by skill match %.
    """

    user_skills_set = {s.strip() for s in user_skills if s and s.strip()}

    enriched = []

    for job in JOB_LISTINGS:
        required = job.get("required_skills", [])
        hits = semantic.match_skills(list(user_skills_set), required)
        matched = [s for s in required if hits[s]]
        match_pct = round((len(matched) / len(required)) * 100) if required else 0
        same_career = career is not None and job.get("career") == career

        enriched.append({
            **job,
            "matched_skills": matched,
            "match_percentage": match_pct,
            "same_career": same_career,
        })

    enriched.sort(key=lambda j: (not j["same_career"], -j["match_percentage"]))

    return enriched[:top_n]
