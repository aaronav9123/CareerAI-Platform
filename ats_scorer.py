"""
ats_scorer.py
-------------
Rule-based ATS (Applicant Tracking System) style resume scorer.
No ML model — scores resume text against the same skill_requirements.json
knowledge base used by skill_gap.py, plus generic section/formatting checks
that most real ATS systems look for.
"""

import re

import semantic
from skill_gap import SKILL_REQUIREMENTS, GENERIC_REQUIREMENTS

SECTION_PATTERNS = {
    "Education": r"\beducation\b|\bacademic\b|\bqualification",
    "Skills": r"\bskills\b|\btechnical skills\b|\bcore competenc",
    "Experience / Internships": r"\bexperience\b|\binternship",
    "Projects": r"\bprojects?\b",
    "Contact Details": r"[\w.+-]+@[\w-]+\.[\w.-]+|(\+?\d[\d\s-]{8,}\d)",
}

IDEAL_WORD_RANGE = (150, 1200)


def _keyword_score(resume_lower, requirements):
    core_skills = requirements.get("core_skills", [])
    supporting_skills = requirements.get("supporting_skills", [])

    # Semantic matching: aliases ("ML" -> Machine Learning) and, when the
    # SBERT backend is available, close paraphrases too.
    def matched(skills):
        found = semantic.find_in_text(resume_lower, skills)
        return [s for s in skills if s in found]

    matched_core = matched(core_skills)
    matched_supporting = matched(supporting_skills)

    core_ratio = (len(matched_core) / len(core_skills)) if core_skills else 1.0
    supporting_ratio = (len(matched_supporting) / len(supporting_skills)) if supporting_skills else 1.0

    score = core_ratio * 40 + supporting_ratio * 20

    missing_keywords = [s for s in core_skills if s not in matched_core] + \
                       [s for s in supporting_skills if s not in matched_supporting]

    return round(score), missing_keywords, matched_core + matched_supporting


def _section_score(resume_text):
    found = []
    missing = []

    for section, pattern in SECTION_PATTERNS.items():
        if re.search(pattern, resume_text, re.IGNORECASE):
            found.append(section)
        else:
            missing.append(section)

    score = len(found) * 5  # 5 sections * 5 = 25 max
    return score, found, missing


def _format_score(resume_text, career, requirements):
    word_count = len(resume_text.split())

    if IDEAL_WORD_RANGE[0] <= word_count <= IDEAL_WORD_RANGE[1]:
        length_score = 10
    elif word_count < IDEAL_WORD_RANGE[0]:
        length_score = round(10 * (word_count / IDEAL_WORD_RANGE[0]))
    else:
        # Long resumes lose a couple of points but aren't punished heavily
        length_score = 7

    recommended_certs = requirements.get("certifications", [])
    resume_lower = resume_text.lower()
    has_relevant_cert = any(cert.lower() in resume_lower for cert in recommended_certs)
    cert_score = 5 if (has_relevant_cert or not recommended_certs) else 0

    return length_score + cert_score, word_count, has_relevant_cert


def score_resume(resume_text, career):
    """
    Returns an ATS-style score breakdown for the given resume text against
    the requirements of `career`.
    """

    requirements = SKILL_REQUIREMENTS.get(career, GENERIC_REQUIREMENTS)
    resume_lower = resume_text.lower()

    keyword_pts, missing_keywords, matched_keywords = _keyword_score(resume_lower, requirements)
    section_pts, found_sections, missing_sections = _section_score(resume_text)
    format_pts, word_count, has_relevant_cert = _format_score(resume_text, career, requirements)

    total_score = min(100, keyword_pts + section_pts + format_pts)

    strengths = []
    weaknesses = []

    if matched_keywords:
        preview = ", ".join(matched_keywords[:5])
        strengths.append(f"Clearly mentions relevant skills for {career}: {preview}.")
    if "Projects" in found_sections:
        strengths.append("Includes a dedicated Projects section, which ATS systems and recruiters value.")
    if "Contact Details" in found_sections:
        strengths.append("Contact details are present and easy to find.")
    if has_relevant_cert:
        strengths.append(f"Lists a certification relevant to {career}.")
    if IDEAL_WORD_RANGE[0] <= word_count <= IDEAL_WORD_RANGE[1]:
        strengths.append("Resume length is in a healthy range — not too short, not overloaded.")

    if missing_keywords:
        preview = ", ".join(missing_keywords[:5])
        weaknesses.append(f"Missing several keywords recruiters search for in {career} resumes: {preview}.")
    if missing_sections:
        weaknesses.append(f"Missing clearly labelled section(s): {', '.join(missing_sections)}.")
    if word_count < IDEAL_WORD_RANGE[0]:
        weaknesses.append("Resume looks quite short — there may not be enough detail for ATS keyword matching.")
    elif word_count > IDEAL_WORD_RANGE[1]:
        weaknesses.append("Resume is quite long — consider trimming to the most relevant experience.")
    if not has_relevant_cert and requirements.get("certifications"):
        weaknesses.append(f"No certification listed that's commonly expected for {career}.")

    suggestions = []

    if missing_keywords:
        suggestions.append(
            f"Naturally work these keywords into your experience/skills bullets: {', '.join(missing_keywords[:6])}."
        )
    if missing_sections:
        suggestions.append(f"Add clearly labelled section headers for: {', '.join(missing_sections)}.")
    if not has_relevant_cert and requirements.get("certifications"):
        suggestions.append(
            f"Consider adding or pursuing: {', '.join(requirements['certifications'])} to strengthen your profile for {career}."
        )
    if word_count < IDEAL_WORD_RANGE[0]:
        suggestions.append("Add more specifics — quantify achievements, list tools used, and describe project outcomes.")

    if not suggestions:
        suggestions.append("Your resume is already well aligned with this role — focus on quantifying achievements with numbers where possible.")

    return {
        "career": career,
        "score": total_score,
        "keyword_points": keyword_pts,
        "section_points": section_pts,
        "format_points": format_pts,
        "missing_keywords": missing_keywords,
        "matched_keywords": matched_keywords,
        "found_sections": found_sections,
        "missing_sections": missing_sections,
        "word_count": word_count,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "suggestions": suggestions,
    }


# =====================================================================
# Job-description (JD) matcher
# =====================================================================
# Instead of the static skill_requirements.json, the keywords are pulled out of
# a job description the user pastes in, then checked against their resume.

import json
import os
from collections import Counter

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _skill_vocabulary():
    vocab = set()
    for req in SKILL_REQUIREMENTS.values():
        vocab.update(req.get("core_skills", []))
        vocab.update(req.get("supporting_skills", []))
    try:
        with open(os.path.join(_DATA_DIR, "job_listings.json"), encoding="utf-8") as f:
            for job in json.load(f):
                vocab.update(job.get("required_skills", []))
    except (OSError, ValueError):
        pass
    try:
        import resume_parser
        vocab.update(resume_parser.SKILLS)
    except Exception:
        pass
    vocab.update(["TypeScript", "Power BI", "Tableau", "Kubernetes", "AWS", "Azure",
                  "Agile", "Scrum", "REST API", "Flask", "Django", "Pandas", "NumPy",
                  "TensorFlow", "PyTorch", "MongoDB", "PostgreSQL", "Jira", "Figma",
                  "SEO", "CRM", "Tally ERP", "GST", "Recruitment", "Negotiation"])
    return sorted(vocab)


SKILL_VOCAB = _skill_vocabulary()

_PREFERRED_CUES = re.compile(
    r"\b(preferred|nice to have|nice-to-have|good to have|bonus|a plus|is a plus|desirable|"
    r"advantage|optional|not required|would be great)\b", re.I)

_STOPWORDS = set("""
a an the and or of to in for on with as at by from is are be this that you your we our will
can able including such etc using use used work working team role job candidate looking
ability strong good great excellent knowledge experience years year skills skill required
requirements responsibilities qualifications preferred plus must have has should also more
other into their they them who what when where which while within across over under about
across per new all any each very well make making build building help helping join company
opportunity position apply applicants applicant benefits salary full time part time based
""".split())


def _stem(w):
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def _other_terms(jd_text, skip_words, limit=12):
    words = re.findall(r"[a-zA-Z][a-zA-Z+#.-]{3,}", jd_text.lower())
    counts = Counter(w.strip(".-") for w in words if w.strip(".-") not in _STOPWORDS)
    out = []
    for w, c in counts.most_common(60):
        if c < 2 or w in skip_words:
            continue
        out.append(w)
        if len(out) >= limit:
            break
    return out


def score_against_jd(resume_text, jd_text):
    """
    Score `resume_text` against a pasted job description.

    Returns a dict shaped like score_resume() (score, strengths, weaknesses,
    suggestions) plus required/preferred keyword breakdowns taken from the JD.
    """

    jd_text = (jd_text or "").strip()
    resume_lower = resume_text.lower()

    jd_found = semantic.find_in_text(jd_text, SKILL_VOCAB, literal_only=True)
    jd_skills = list(jd_found.keys())

    # --- classify each JD skill as required or preferred (by the line it's in)
    lines = [l for l in re.split(r"[\n\r]+|(?<=[.;])\s", jd_text) if l.strip()]
    preferred, required = [], []
    for skill in jd_skills:
        in_lines = [l for l in lines if semantic.find_in_text(l, [skill], literal_only=True)]
        if in_lines and all(_PREFERRED_CUES.search(l) for l in in_lines):
            preferred.append(skill)
        else:
            required.append(skill)

    # --- check each against the resume (semantic)
    res_found = semantic.find_in_text(resume_lower, jd_skills)
    matched_req = [s for s in required if s in res_found]
    missing_req = [s for s in required if s not in res_found]
    matched_pref = [s for s in preferred if s in res_found]
    missing_pref = [s for s in preferred if s not in res_found]

    # --- other recurring JD terms (domain words that aren't in the vocabulary)
    skip = {w for s in jd_skills for w in s.lower().split()}
    terms = _other_terms(jd_text, skip)
    resume_stems = {_stem(w) for w in re.findall(r"[a-zA-Z][a-zA-Z+#.-]{2,}", resume_lower)}
    matched_terms = [t for t in terms if _stem(t) in resume_stems]
    missing_terms = [t for t in terms if _stem(t) not in resume_stems]

    section_pts, found_sections, missing_sections = _section_score(resume_text)
    word_count = len(resume_text.split())
    length_ok = IDEAL_WORD_RANGE[0] <= word_count <= IDEAL_WORD_RANGE[1]

    # --- weighted score, re-normalised over the components that exist
    components = []  # (ratio, weight)
    if required:
        components.append((len(matched_req) / len(required), 50))
    if preferred:
        components.append((len(matched_pref) / len(preferred), 15))
    if terms:
        components.append((len(matched_terms) / len(terms), 15))
    components.append((section_pts / 25, 12))
    components.append((1.0 if length_ok else 0.4, 8))
    total_w = sum(w for _, w in components)
    score = round(sum(r * w for r, w in components) / total_w * 100)

    # --- years of experience asked for in the JD
    yrs = [int(y) for y in re.findall(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?years?", jd_text, re.I)]
    years_required = max(yrs) if yrs else None

    strengths, weaknesses, suggestions = [], [], []
    if matched_req:
        strengths.append(f"Your resume covers {len(matched_req)} of {len(required)} required skills: {', '.join(matched_req[:6])}.")
    if matched_pref:
        strengths.append(f"You also match preferred skills: {', '.join(matched_pref[:5])}.")
    if "Projects" in found_sections:
        strengths.append("Has a Projects section that can be tailored to this role.")
    if missing_req:
        weaknesses.append(f"Required skills not found in your resume: {', '.join(missing_req[:8])}.")
        suggestions.append(
            "If you genuinely have these skills, add them to your Skills section AND show them in a project or "
            f"experience bullet: {', '.join(missing_req[:6])}. If you don't, they're your learning priorities.")
    if missing_pref:
        weaknesses.append(f"Preferred (bonus) skills missing: {', '.join(missing_pref[:6])}.")
    if missing_terms:
        suggestions.append(f"Mirror the job's own wording where truthful. Recurring JD terms missing from your resume: {', '.join(missing_terms[:8])}.")
    if missing_sections:
        weaknesses.append(f"Missing section(s): {', '.join(missing_sections)}.")
        suggestions.append(f"Add clearly labelled section headers for: {', '.join(missing_sections)}.")
    if years_required:
        suggestions.append(f"The JD mentions {years_required}+ years of experience \u2014 make sure internships, projects and "
                           "freelance work are described with durations so recruiters can see relevant experience.")
    if not jd_skills:
        weaknesses.append("We couldn't recognise specific skills in that job description \u2014 try pasting the full text including the Requirements section.")
    if not suggestions:
        suggestions.append("Strong match. Tailor your summary line to this job title and quantify your achievements.")

    first_line = next((l.strip() for l in jd_text.splitlines() if l.strip()), "")

    return {
        "score": score,
        "job_title": first_line[:90],
        "required": required, "preferred": preferred,
        "matched_required": matched_req, "missing_required": missing_req,
        "matched_preferred": matched_pref, "missing_preferred": missing_pref,
        "matched_terms": matched_terms, "missing_terms": missing_terms,
        "found_sections": found_sections, "missing_sections": missing_sections,
        "word_count": word_count,
        "years_required": years_required,
        "via_alias": {s: p for s, p in res_found.items() if p.lower() != s.lower()},
        "strengths": strengths, "weaknesses": weaknesses, "suggestions": suggestions,
        "matcher": semantic.backend_name(),
    }
