"""Scores an offer against your target role (DevOps/Cloud) and picks projects/resume to present."""
from . import llm
import json, os, re
from .config import CFG, PROJECTS, PROFILE, RESUMES


from .answers import norm


def _has(text: str, term: str) -> bool:
    """Whole-word match, accent- and case-insensitive (text must already be norm()-ed)."""
    return re.search(r"(?<![a-z0-9])" + re.escape(norm(term)) + r"(?![a-z0-9])", text) is not None


def _words_re(words):
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(norm(w)) for w in words) + r")(?![a-z0-9])")


def is_internship(title: str, meta: str, text: str):
    """(ok, reason). Internship / PFE offers only; LinkedIn's 'Stage' header counts when the description confirms it."""
    t, m, d = norm(title), norm(meta), norm(text)
    intern = _words_re(CFG["internship_words"])
    if _words_re(CFG["title_must_exclude_any"]).search(t) and not intern.search(t):
        return False, "not an internship (title)"
    if _words_re(CFG["seniority_exclude"]).search(t):
        return False, "senior / lead role"
    if intern.search(t):
        return True, ""
    if intern.search(m) and intern.search(d):
        return True, ""
    return False, "not an internship"


def rank_projects(job_text: str, top=3):
    t = norm(job_text)
    scored = []
    for p in PROJECTS["projects"]:
        tags = p.get("tags", [])
        if tags:
            scored.append((sum(_has(t, x) for x in tags) / len(tags), p))
    scored.sort(key=lambda x: -x[0])
    return [(s, p) for s, p in scored[:top] if s > 0]


def title_could_fit(title: str) -> bool:
    """Same title rule fit_score applies (a DevOps/cloud word in the title, no excluded role): lets us skip an offer
    from its search card without opening it, with exactly the verdict opening it would give."""
    t = norm(title)
    return not any(_has(t, x) for x in CFG["exclude_roles"]) and any(_has(t, x) for x in CFG["role_keywords"])


def fit_score(title: str, job_text: str) -> float:
    """0..1 heuristic: role keywords in the title weigh most, then role keywords + your skills in the body."""
    title_l, text = norm(title), norm(job_text)
    if any(_has(title_l, x) for x in CFG["exclude_roles"]):
        return 0.0
    role = CFG["role_keywords"]
    title_hit = 1.0 if any(_has(title_l, x) for x in role) else 0.0
    core = min(sum(_has(text, x) for x in role) / 4, 1.0)
    skills = min(sum(_has(text, x) for x in set(PROJECTS["skills"])) / 8, 1.0)
    if not title_hit:
        return round(min(0.4, 0.3 * core + 0.3 * skills), 3)   # no DevOps/cloud word in the title -> never a "perfect fit"
    bonus = 0.1 if any(re.search(norm(x), text) for x in CFG.get("visa_friendly", [])) else 0.0
    return round(min(1.0, 0.4 * title_hit + 0.3 * core + 0.3 * skills + bonus), 3)


def llm_fit(title: str, company: str, job_text: str):
    """Optional second opinion from the LLM: 0-100 fit for a DevOps/Cloud end-of-studies internship. None if unavailable."""
    if not llm.available():
        return None
    try:
        out = llm.complete(
        "Rate how well this internship offer fits a student seeking an end-of-studies (PFE) internship in "
        "DevOps / Cloud / SRE / platform / DevSecOps, given their profile. Reply with only an integer 0-100. "
        "Give 0 if it is not an internship/PFE or is a different specialty.",
        json.dumps({"profile_skills": PROJECTS["skills"], "certs": PROFILE.get("certifications"),
                    "title": title, "company": company, "description": job_text[:3500]}), 10)
    except Exception:
        return None
    m = re.search(r"\d+", out)
    return int(m.group()) if m else None


def pick_resume(title: str, job_text: str, best_projects) -> str:
    t = f"{title}\n{job_text}".lower()
    best, best_s = next(iter(RESUMES)), -1
    for key, r in RESUMES.items():
        s = sum(_has(t, f) for f in r.get("focus", []))
        s += sum(2 * sc for sc, p in best_projects if p.get("resume") == key)
        if _has(norm(title), key):
            s += 3
        if s > best_s:
            best, best_s = key, s
    return best
