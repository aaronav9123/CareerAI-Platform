"""
resume_parser.py
-----------------
Extracts raw text from an uploaded PDF/DOCX resume and detects the fields
the Career Prediction form needs (education, specialization, skills,
certification, CGPA/percentage) plus extra context (projects, internships)
used later by the Skill Gap and ATS features.

Pure text/keyword based — no ML model, so it stays fast and dependency-light.
"""

import os
import re

import pdfplumber
from docx import Document

ALLOWED_EXTENSIONS = {"pdf", "docx"}

# ---------------- VOCABULARIES ----------------
# Kept in sync with the option lists in templates/predict.html so that
# whatever the parser finds can be pre-selected directly in the form.

EDUCATION_LEVELS = ["PhD", "Master's", "Masters", "Bachelor's", "Bachelors", "Intermediate", "Matric"]

EDUCATION_NORMALISE = {
    "phd": "PhD",
    "doctorate": "PhD",
    "master's": "Master's",
    "masters": "Master's",
    "m.tech": "Master's",
    "mtech": "Master's",
    "msc": "Master's",
    "m.sc": "Master's",
    "mba": "Master's",
    "bachelor's": "Bachelor's",
    "bachelors": "Bachelor's",
    "b.tech": "Bachelor's",
    "btech": "Bachelor's",
    "bsc": "Bachelor's",
    "b.sc": "Bachelor's",
    "b.e": "Bachelor's",
    "be": "Bachelor's",
    "bca": "Bachelor's",
    "intermediate": "Intermediate",
    "12th": "Intermediate",
    "hsc": "Intermediate",
    "matric": "Matric",
    "10th": "Matric",
    "ssc": "Matric",
}

SPECIALIZATIONS = ["Computer Science", "Science", "Business", "Commerce", "Arts", "Engineering", "Finance", "Psychology"]

SKILLS = [
    "Python", "Java", "C", "C++", "SQL", "HTML", "CSS", "JavaScript", "React",
    "Node.js", "Machine Learning", "Deep Learning", "Artificial Intelligence",
    "Data Analysis", "Cloud Computing", "Cyber Security", "Docker", "Git",
    "Linux", "Communication", "Leadership", "Problem Solving", "Teamwork",
    "MS Office", "Excel", "Accounting", "Financial Analysis", "Marketing",
    "Graphic Design",
]

CERTIFICATIONS = [
    "AWS Certified", "Google Data Analytics", "Tally ERP", "CFA Level 1",
    "Mental Health Basics",
]

SECTION_HEADERS = {
    "projects": ["projects", "academic projects", "personal projects"],
    "internships": ["internship", "internships", "experience", "work experience"],
    "certifications": ["certification", "certifications", "licenses & certifications"],
}


# ---------------- TEXT EXTRACTION ----------------

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text(filepath):
    """Return raw text from a PDF or DOCX file."""

    ext = filepath.rsplit(".", 1)[1].lower()

    if ext == "pdf":
        text_parts = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n".join(text_parts)

    if ext == "docx":
        doc = Document(filepath)
        return "\n".join(p.text for p in doc.paragraphs if p.text)

    return ""


# ---------------- FIELD DETECTION ----------------

def _find_education(text_lower):
    for key, normalised in EDUCATION_NORMALISE.items():
        if re.search(r"\b" + re.escape(key) + r"\b", text_lower):
            return normalised
    return None


def _find_specialization(text_lower):
    for spec in SPECIALIZATIONS:
        if spec.lower() in text_lower:
            return spec
    return None


def _find_skills(text_lower):
    found = []
    for skill in SKILLS:
        # word-boundary match, case-insensitive, handles "C++"/"C" safely
        pattern = r"(?<![a-zA-Z0-9])" + re.escape(skill.lower()) + r"(?![a-zA-Z0-9])"
        if re.search(pattern, text_lower):
            found.append(skill)
    return found


def _find_certifications(text_lower):
    found = []
    for cert in CERTIFICATIONS:
        if cert.lower() in text_lower:
            found.append(cert)
    return found


def _find_cgpa(text):
    # CGPA out of 10/4, or a percentage
    patterns = [
        r"cgpa[:\s]*([0-9]+(?:\.[0-9]+)?)\s*(?:/\s*10)?",
        r"gpa[:\s]*([0-9]+(?:\.[0-9]+)?)\s*(?:/\s*4)?",
        r"percentage[:\s]*([0-9]{1,3}(?:\.[0-9]+)?)\s*%?",
        r"([0-9]{1,3}(?:\.[0-9]+)?)\s*%",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                value = float(match.group(1))
                if 0 <= value <= 100:
                    return value
            except ValueError:
                continue
    return None


def _find_section(lines, header_keywords):
    """Grab short bullet-style lines following a section header."""

    collected = []
    capturing = False

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower().strip(":")

        if not stripped:
            continue

        if lower in header_keywords or any(lower == h for h in header_keywords):
            capturing = True
            continue

        # Stop capturing once we hit another all-caps / title-style header
        if capturing and len(stripped) < 40 and stripped.isupper():
            capturing = False

        if capturing:
            collected.append(stripped)

        if len(collected) >= 8:
            break

    return collected[:8]


def parse_resume(filepath):
    """Extract text + detected fields from an uploaded resume file."""

    text = extract_text(filepath)
    text_lower = text.lower()
    lines = text.splitlines()

    education = _find_education(text_lower)
    specialization = _find_specialization(text_lower)
    skills = _find_skills(text_lower)
    certifications = _find_certifications(text_lower)
    cgpa = _find_cgpa(text)

    projects = _find_section(lines, SECTION_HEADERS["projects"])
    internships = _find_section(lines, SECTION_HEADERS["internships"])

    return {
        "raw_text": text,
        "education": education,
        "specialization": specialization,
        "skills": skills,
        "certification": certifications[0] if certifications else "None",
        "cgpa": cgpa,
        "projects": projects,
        "internships": internships,
    }
