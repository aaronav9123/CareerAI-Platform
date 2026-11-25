"""
semantic.py
-----------
Semantic skill matching used by Skill Gap, ATS scoring, JD matching and Job
matching, so "ML" matches "Machine Learning", "reactjs" matches "React",
"MS Excel" matches "Excel" and so on.

Two backends, picked automatically:

  * "sbert" - sentence-transformers (all-MiniLM-L6-v2) sentence embeddings.
              Used when `pip install sentence-transformers` has been done and
              the model can be loaded (needs internet on first run to download
              ~90 MB). Force with SEMANTIC_BACKEND=sbert.
  * "lite"  - no extra dependencies. Alias dictionary + character n-gram
              similarity. Used as the automatic fallback, or force with
              SEMANTIC_BACKEND=lite.

Both backends share the same alias table and the same "conflict" guard, so
clearly different skills (Java vs JavaScript, C vs C++) are never merged.
"""

import math
import os
import re
from collections import Counter
from functools import lru_cache

# ---------------------------------------------------------------- aliases
# canonical -> (tight aliases, loose aliases)
#   tight = abbreviations / spelling variants of the SAME skill ("ml").
#   loose = more specific tools that imply the skill ("pytorch" -> deep learning).
# Tight aliases are used everywhere. Loose aliases only count when a *resume*
# is checked against a general requirement (a resume that says "PostgreSQL"
# satisfies "SQL", but a job asking for "PostgreSQL" is not found in "SQL").
_ALIAS_GROUPS = {
    "machine learning": (["ml", "machine-learning"], ["scikit-learn", "sklearn"]),
    "deep learning": (["dl", "deep-learning", "neural networks", "neural network"], ["tensorflow", "pytorch", "keras"]),
    "artificial intelligence": (["ai", "a.i.", "artificial-intelligence"], []),
    "javascript": (["js", "java script", "ecmascript", "es6"], []),
    "typescript": (["ts"], []),
    "python": (["py", "python3", "python 3"], []),
    "c++": (["cpp", "c plus plus", "cplusplus"], []),
    "c#": (["c sharp", "csharp"], []),
    "react": (["reactjs", "react.js", "react js"], []),
    "node.js": (["nodejs", "node js", "node"], ["express.js", "expressjs"]),
    "html": (["html5"], []),
    "css": (["css3"], []),
    "sql": (["structured query language"], ["mysql", "postgresql", "postgres", "sqlite", "sql server", "mssql", "pl/sql", "t-sql"]),
    "git": ([], ["github", "gitlab", "version control", "bitbucket"]),
    "docker": (["containerization"], ["containers", "kubernetes", "k8s"]),
    "linux": ([], ["ubuntu", "unix", "bash", "shell scripting"]),
    "cloud computing": (["cloud"], ["aws", "amazon web services", "azure", "gcp", "google cloud"]),
    "cyber security": (["cybersecurity", "cyber-security", "infosec"], ["information security", "network security"]),
    "data analysis": (["data analytics", "data analyst", "data analyzing", "data analysing"], ["analytics", "pandas", "numpy"]),
    "excel": (["ms excel", "microsoft excel", "advanced excel"], ["spreadsheets", "spreadsheet", "google sheets"]),
    "ms office": (["microsoft office", "office 365", "m.s. office"], ["ms word", "ms powerpoint", "microsoft word"]),
    "power bi": (["powerbi", "power-bi"], []),
    "tally erp": (["tally", "tally prime", "tallyerp", "tally erp 9"], []),
    "problem solving": (["problem-solving", "problem solver"], ["analytical thinking", "troubleshooting"]),
    "teamwork": (["team work", "team player"], ["collaboration", "collaborative"]),
    "communication": (["communication skills", "verbal communication", "written communication"], ["public speaking"]),
    "leadership": (["leadership skills", "team leadership"], ["team lead"]),
    "accounting": ([], ["bookkeeping", "book keeping", "accounts payable", "accounts receivable"]),
    "financial analysis": (["financial analytics"], ["financial modelling", "financial modeling", "financial statements"]),
    "marketing": ([], ["digital marketing", "social media marketing", "seo", "content marketing"]),
    "graphic design": (["graphic designing"], ["photoshop", "illustrator", "canva", "adobe photoshop", "figma"]),
}

ALIASES = {}               # any alias (tight or loose) -> canonical
ALIAS_TIGHT = {}           # canonical -> [tight aliases]
ALIAS_LOOSE = {}           # canonical -> [loose aliases]
for _canon, (_tight, _loose) in _ALIAS_GROUPS.items():
    ALIASES[_canon] = _canon
    ALIAS_TIGHT[_canon] = list(_tight)
    ALIAS_LOOSE[_canon] = list(_loose)
    for _a in _tight + _loose:
        ALIASES[_a] = _canon

# Skills that look similar but are NOT interchangeable.
_CONFLICT_GROUPS = [
    {"java", "javascript", "typescript"},
    {"c", "c++", "c#"},
    {"python", "java", "javascript", "c", "c++", "c#"},
    {"accounting", "marketing", "graphic design", "financial analysis"},
]


def _clean(s):
    s = (s or "").strip().lower()
    s = re.sub(r"[‘’]", "'", s)
    s = re.sub(r"\s+", " ", s)
    return s


def canon(skill):
    """Canonical form of a skill name (alias-resolved, lower-case)."""
    s = _clean(skill)
    return ALIASES.get(s, s)


def _conflict(a, b):
    if a == b:
        return False
    return any(a in g and b in g for g in _CONFLICT_GROUPS)


# ---------------------------------------------------------------- backends

def _ngrams(s, n=3):
    s = f" {s} "
    return Counter(s[i:i + n] for i in range(max(1, len(s) - n + 1)))


def _cosine(c1, c2):
    if not c1 or not c2:
        return 0.0
    dot = sum(v * c2.get(k, 0) for k, v in c1.items())
    n1 = math.sqrt(sum(v * v for v in c1.values()))
    n2 = math.sqrt(sum(v * v for v in c2.values()))
    return dot / (n1 * n2) if n1 and n2 else 0.0


class _LiteBackend:
    name = "lite"
    threshold = 0.74

    @lru_cache(maxsize=4096)
    def _grams(self, s):
        return _ngrams(s)

    def similarity(self, a, b):
        return _cosine(self._grams(a), self._grams(b))


class _SbertBackend:
    name = "sbert"
    threshold = 0.80

    def __init__(self):
        from sentence_transformers import SentenceTransformer  # noqa
        self.model = SentenceTransformer(os.environ.get("SBERT_MODEL", "all-MiniLM-L6-v2"))
        self._cache = {}

    def embed(self, texts):
        missing = [t for t in texts if t not in self._cache]
        if missing:
            vecs = self.model.encode(missing, normalize_embeddings=True, show_progress_bar=False)
            for t, v in zip(missing, vecs):
                self._cache[t] = v
        return [self._cache[t] for t in texts]

    def similarity(self, a, b):
        va, vb = self.embed([a, b])
        return float(sum(x * y for x, y in zip(va, vb)))


_backend = None


def get_backend():
    global _backend
    if _backend is not None:
        return _backend
    choice = os.environ.get("SEMANTIC_BACKEND", "auto").lower()
    if choice in ("auto", "sbert"):
        try:
            _backend = _SbertBackend()
            return _backend
        except Exception as e:  # not installed / no internet / model missing
            if choice == "sbert":
                print("[semantic] SBERT requested but unavailable:", e)
    _backend = _LiteBackend()
    return _backend


def backend_name():
    return get_backend().name


# ---------------------------------------------------------------- API

def similarity(a, b):
    """0..1 similarity between two skill names."""
    ca, cb = canon(a), canon(b)
    if ca == cb:
        return 1.0
    if _conflict(ca, cb):
        return 0.0
    be = get_backend()
    score = be.similarity(ca, cb)
    if be.name == "sbert":
        # embeddings of short tokens can be noisy - never let them go below
        # what the cheap lexical measure says
        score = max(score, _LiteBackend().similarity(ca, cb))
    return score


def is_match(a, b):
    ca, cb = canon(a), canon(b)
    if ca == cb:
        return True
    if _conflict(ca, cb):
        return False
    return similarity(a, b) >= get_backend().threshold


def match_skills(user_skills, required):
    """
    For each skill in `required`, find the user skill (if any) that matches it.
    Returns {required_skill: matched_user_skill_or_None}, order preserved.
    """
    user = [s.strip() for s in user_skills if s and s.strip()]
    result = {}
    for req in required:
        hit = None
        for u in user:
            if is_match(u, req):
                hit = u
                break
        result[req] = hit
    return result


def _skill_pattern(term):
    t = re.escape(term.lower())
    return re.compile(r"(?<![a-zA-Z0-9])" + t + r"(?![a-zA-Z0-9+#])", re.I)


@lru_cache(maxsize=4096)
def _patterns_for(skill, loose):
    own = _clean(skill)
    c = canon(skill)
    terms = {own}
    # a skill that IS an alias ("PostgreSQL") only matches itself; a canonical
    # skill ("SQL") also matches its aliases.
    if own == c:
        terms.update(ALIAS_TIGHT.get(c, []))
        if loose:
            terms.update(ALIAS_LOOSE.get(c, []))
    else:
        terms.update(t for t in ALIAS_TIGHT.get(c, []) if t == own)
    return [(t, _skill_pattern(t)) for t in terms if t]


def find_in_text(text, skills, literal_only=False):
    """
    Which of `skills` does `text` mention - literally, via an alias, or (with
    the SBERT backend) via a semantically close phrase?
    Returns {skill: phrase_that_matched}.
    """
    text_l = _clean(text)
    found = {}
    for skill in skills:
        for term, pat in _patterns_for(skill, not literal_only):
            if pat.search(text_l):
                found[skill] = term
                break

    if literal_only:
        return found

    be = get_backend()
    if be.name == "sbert":
        remaining = [s for s in skills if s not in found]
        if remaining:
            phrases = _candidate_phrases(text_l)
            for skill in remaining:
                c = canon(skill)
                best, best_p = 0.0, None
                for p in phrases:
                    if _conflict(c, canon(p)):
                        continue
                    sc = be.similarity(c, p)
                    if sc > best:
                        best, best_p = sc, p
                if best >= max(be.threshold, 0.82):
                    found[skill] = best_p
    return found


def _candidate_phrases(text_l, limit=800):
    words = re.findall(r"[a-z0-9+#.]+", text_l)
    seen, out = set(), []
    for n in (1, 2, 3):
        for i in range(len(words) - n + 1):
            p = " ".join(words[i:i + n])
            if len(p) < 3 or p in seen:
                continue
            seen.add(p)
            out.append(p)
            if len(out) >= limit:
                return out
    return out
