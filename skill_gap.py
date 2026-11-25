"""
skill_gap.py
------------
Compares a user's skills against the skills required for their predicted
career, using the static knowledge base in data/skill_requirements.json.
No ML model involved — just set comparison + a readiness score.
"""

import json
import os

import semantic

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "skill_requirements.json")

with open(DATA_PATH, "r", encoding="utf-8") as f:
    SKILL_REQUIREMENTS = json.load(f)

GENERIC_REQUIREMENTS = {
    "core_skills": ["Communication", "Problem Solving", "Teamwork", "MS Office"],
    "supporting_skills": [],
    "certifications": [],
    "learning_resources": {},
}


def _readiness(core_skills, supporting_skills, missing_core, missing_supporting):
    if not (core_skills or supporting_skills):
        return 0
    # Core skills weigh more than supporting skills toward readiness.
    core_score = (
        (len(core_skills) - len(missing_core)) / len(core_skills)
        if core_skills else 1.0
    )
    supporting_score = (
        (len(supporting_skills) - len(missing_supporting)) / len(supporting_skills)
        if supporting_skills else 1.0
    )
    return round((core_score * 0.7 + supporting_score * 0.3) * 100)


def compute_skill_gap(user_skills, career, learned=None):
    """
    user_skills: list[str] as selected/detected for the user.
    career: predicted career label.
    learned: list[str] of skills the user has marked "learned" since their
             last prediction (Progress Tracker). They count towards readiness.

    Matching is semantic (see semantic.py), so "ML" satisfies "Machine
    Learning", "MS Excel" satisfies "Excel", etc.

    Returns a dict with possessed/missing core+supporting skills,
    a readiness percentage, and simple next-step suggestions.
    """

    requirements = SKILL_REQUIREMENTS.get(career, GENERIC_REQUIREMENTS)

    core_skills = requirements.get("core_skills", [])
    supporting_skills = requirements.get("supporting_skills", [])
    all_required = core_skills + supporting_skills

    base_skills = [s.strip() for s in user_skills if s and s.strip()]
    learned = [s.strip() for s in (learned or []) if s and s.strip()]

    base_match = semantic.match_skills(base_skills, all_required)
    full_match = semantic.match_skills(base_skills + learned, all_required)

    possessed = [s for s in all_required if full_match[s]]
    missing = [s for s in all_required if not full_match[s]]
    learned_here = [s for s in possessed if not base_match[s]]

    missing_core = [s for s in core_skills if not full_match[s]]
    missing_supporting = [s for s in supporting_skills if not full_match[s]]

    base_missing_core = [s for s in core_skills if not base_match[s]]
    base_missing_supporting = [s for s in supporting_skills if not base_match[s]]

    readiness = _readiness(core_skills, supporting_skills, missing_core, missing_supporting)
    base_readiness = _readiness(core_skills, supporting_skills, base_missing_core, base_missing_supporting)

    resources = requirements.get("learning_resources", {})
    suggestions = []

    # Prioritise missing core skills first, then supporting.
    for skill in (missing_core + missing_supporting)[:5]:
        tip = resources.get(skill)
        if tip:
            suggestions.append(f"Learn {skill} \u2014 try: {tip}")
        else:
            suggestions.append(f"Learn {skill}")

    if not missing:
        suggestions = ["You already cover every skill this role typically needs \u2014 focus on building projects and certifications to stand out."]

    return {
        "career": career,
        "core_skills": core_skills,
        "supporting_skills": supporting_skills,
        "possessed": possessed,
        "missing": missing,
        "missing_core": missing_core,
        "missing_supporting": missing_supporting,
        "learned_here": learned_here,
        "readiness": readiness,
        "base_readiness": base_readiness,
        "suggestions": suggestions,
        "certifications_recommended": requirements.get("certifications", []),
        "matcher": semantic.backend_name(),
    }
