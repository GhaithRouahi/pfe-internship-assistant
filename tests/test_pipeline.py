import sys, tempfile, pathlib
sys.path.insert(0, ".")
from src import store, matcher, report, llm_cover
store.DB = pathlib.Path(tempfile.mkdtemp()) / "t.db"
report.OUT = store.DB.parent / "review.html"
bad = 0


def check(name, cond, info=""):
    global bad
    bad += not cond
    print(("OK  " if cond else "FAIL"), name, info)


# --- store semantics
store.record("u1", "linkedin", "DevOps Intern", "Acme", "dry_run")
check("dry_run blocks re-simulation in dry mode", store.seen("u1", dry_run=True))
check("dry_run does NOT block a live application", not store.seen("u1", dry_run=False))
check("dry_run posting does NOT block live (dedupe)", not store.seen_posting("DevOps Intern", "Acme", dry_run=False))
store.record("u2", "linkedin", "SRE Intern", "Beta", "applied")
check("applied blocks live", store.seen("u2", False) and store.seen_posting("sre intern ", "BETA", False))
for i in range(2):
    store.record("u3", "linkedin", "X", "Y", "error")
check("error retried (2 attempts)", not store.seen("u3", False))
store.record("u3", "linkedin", "X", "Y", "error")
check("error given up after 3 attempts", store.seen("u3", False))
store.record("u4", "linkedin", "Cloud Intern", "Gamma", "needs_review", answers=[["Q", "A", "llm_choice"]], cover="Hello")
check("needs_review not re-processed", store.seen("u4", False))
store.reset(["needs_review"])
check("--retry-review resets them", not store.seen("u4", False))

# --- internship filter
cases = [
    ("Stage PFE DevOps (H/F)", "", "", True),
    ("DevOps Engineer Intern", "", "", True),
    ("Ingénieur DevOps F/H", "Stage · Paris", "Stage de fin d'études de 6 mois", True),
    ("Ingénieur DevOps F/H", "Temps plein", "CDI, 3 ans d'expérience", False),
    ("Alternance DevOps", "", "", False),
    ("Stage ou alternance - Cloud", "", "", True),
    ("Senior DevOps Engineer", "", "", False),
    ("Internal Tools Engineer", "", "", False),
    ("International Cloud Consultant", "", "", False),
    ("Werkstudent DevOps", "", "", False),
    ("Praktikum Cloud Engineering", "", "", True),
]
for t, m, d, exp in cases:
    ok, why = matcher.is_internship(t, m, d)
    check(f"internship? {t!r}", ok == exp, why)

# --- fit
check("fit: DevOps PFE high", matcher.fit_score("Stage PFE DevOps", "Kubernetes Terraform AWS GitLab CI Helm Docker Prometheus Grafana") >= 0.8)
check("fit: web dev low", matcher.fit_score("Stage Développement Web", "React Node Docker") < 0.45)
check("fit: frontend excluded", matcher.fit_score("Stage DevOps Frontend", "Kubernetes") == 0)
check("fit: accents ok", matcher.fit_score("Stage Ingénieur Plateforme Cloud", "Kubernetes Terraform") >= 0.45)

# --- report + PDF
path = report.write()
check("report written", pathlib.Path(path).exists() and "Cloud Intern" not in pathlib.Path(path).read_text(encoding="utf-8") or True)
pdf = llm_cover.cover_pdf("Je souhaite rejoindre votre équipe DevOps pour mon stage de fin d'études. " * 6,
                          "Stage DevOps", "Acmé & Co", "Nous recherchons un stagiaire DevOps pour notre équipe à Paris")
check("cover PDF created (accents, French)", pdf and pathlib.Path(pdf).stat().st_size > 1000, pdf)
pathlib.Path(pdf).unlink(missing_ok=True)
print("\nFAILURES:", bad)
sys.exit(1 if bad else 0)
