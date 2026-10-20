"""SQLite log of every offer seen. Decides what is never retried (final) vs retried (errors, dry runs once live)."""
import json, re, sqlite3, time
from .config import ROOT
from .answers import norm

DB = ROOT / "data" / "applications.db"
COLS = ["url", "site", "title", "company", "status", "reason", "resume", "projects", "score", "ts",
        "country", "answers", "cover", "cover_pdf", "attempts"]
FINAL_LIVE = ("applied", "unconfirmed", "skipped", "needs_review", "selected")          # never re-processed in live mode
FINAL_DRY = FINAL_LIVE + ("dry_run",)                                      # in dry-run mode, already-simulated offers are skipped too
MAX_ATTEMPTS = 3


def _conn():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS applications(
        url TEXT PRIMARY KEY, site TEXT, title TEXT, company TEXT,
        status TEXT, reason TEXT, resume TEXT, projects TEXT, score REAL, ts REAL)""")
    have = {r[1] for r in c.execute("PRAGMA table_info(applications)")}
    for col, typ in (("country", "TEXT"), ("answers", "TEXT"), ("cover", "TEXT"), ("cover_pdf", "TEXT"), ("attempts", "INTEGER DEFAULT 0")):
        if col not in have:
            c.execute(f"ALTER TABLE applications ADD COLUMN {col} {typ}")
    return c


def _final(dry_run):
    return FINAL_DRY if dry_run else FINAL_LIVE


def seen(url: str, dry_run: bool) -> bool:
    with _conn() as c:
        r = c.execute("SELECT status, attempts FROM applications WHERE url=?", (url,)).fetchone()
    if not r:
        return False
    status, attempts = r
    return status in _final(dry_run) or (status == "error" and (attempts or 0) >= MAX_ATTEMPTS)


SUFFIX = re.compile(r"\b(deutschland|germany|france|tunisie|tunisia|uk|usa|us|nederland|netherlands|belgium|belgique|schweiz|suisse|"
                    r"switzerland|espana|spain|italia|italy|canada|emea|europe|gmbh|ag|sas|sasu|sarl|sa|se|ltd|limited|inc|llc|bv|b\.v\.|"
                    r"group|groupe|holding|technologies|technology)\b\.?", re.I)


def _company_key(company):
    return re.sub(r"[^a-z0-9]+", " ", SUFFIX.sub(" ", norm(company))).strip()


WTTJ_SUFFIX = re.compile(r"\s+-\s+[^-]+\s+-\s+(stage|cdi|cdd|alternance|freelance|vie)\b.*$", re.I)   # "<title> - CGI - Stage à Montpellier"


def _title_key(title):
    return norm(WTTJ_SUFFIX.sub("", title or "")).strip()


def seen_posting(title: str, company: str, dry_run: bool) -> bool:
    """Same company + title already handled (reposts, same offer in several cities / sites / country pages of one company)."""
    if not title or not company:
        return False
    t, ck = _title_key(title), _company_key(company)
    q = f"SELECT title, company FROM applications WHERE status IN ({','.join('?' * len(_final(dry_run)))})"
    with _conn() as c:
        return any(_title_key(rt) == t and _company_key(rc or "") == ck for rt, rc in c.execute(q, _final(dry_run)))


def applied_to_company(company: str) -> bool:
    ck = _company_key(company or "")
    with _conn() as c:
        return bool(ck) and any(_company_key(rc or "") == ck for (rc,) in c.execute("SELECT company FROM applications WHERE status IN ('applied','unconfirmed')"))


def record(url, site, title, company, status, reason="", resume="", projects="", score=0.0, country="", answers=None, cover="", cover_pdf=""):
    with _conn() as c:
        prev = c.execute("SELECT attempts FROM applications WHERE url=?", (url,)).fetchone()
        attempts = ((prev[0] or 0) if prev else 0) + (1 if status == "error" else 0)
        c.execute(f"INSERT OR REPLACE INTO applications ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})",
                  (url, site, title, company, status, reason, resume, projects, score, time.time(), country,
                   json.dumps(answers or [], ensure_ascii=False), cover, cover_pdf, attempts))


def reset(statuses):
    with _conn() as c:
        c.execute(f"DELETE FROM applications WHERE status IN ({','.join('?' * len(statuses))})", tuple(statuses))


def rows(statuses=None):
    with _conn() as c:
        c.row_factory = sqlite3.Row
        if statuses:
            return [dict(r) for r in c.execute(f"SELECT * FROM applications WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY ts DESC", tuple(statuses))]
        return [dict(r) for r in c.execute("SELECT * FROM applications ORDER BY ts DESC")]
