"""Runs the real engine on local copies of a LinkedIn-style and an ATS-style form (separate headless browser, dry run)."""
import sys, pathlib
sys.path.insert(0, ".")
from src.config import CFG
CFG["llm"]["enabled"] = False
CFG["dry_run"] = True
CFG["delay_between_actions_sec"] = [0, 0]
CFG["submit_policy"]["allow_llm_choices"] = False
from playwright.sync_api import sync_playwright
from src import answers
from src.flow import run_steps, find_form_scope

F = pathlib.Path("tests/fixtures").resolve()
bad = 0


def check(name, cond, info=""):
    global bad
    bad += not cond
    print(("OK  " if cond else "FAIL"), name, info)


with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page()

    answers.set_context("France", "linkedin", "Stage DevOps", "Acme", "Stage de fin d'études DevOps, Kubernetes, Terraform")
    pg.goto((F / "linkedin_like.html").as_uri())
    out = run_steps(pg, lambda: pg.locator("dialog[open]").first, "devops", "", "")
    print("   ->", out.status, out.reason)
    for q, a, s in out.log:
        print("     ", s, "|", q[:60], "->", a)
    check("status dry_run", out.status == "dry_run")
    check("phone replaced with profile number (national)", pg.input_value("#ph") == "20123456", pg.input_value("#ph"))
    check("resume uploaded", pg.inner_text("#cvname") == "Resume_Jane_Doe.pdf", pg.inner_text("#cvname"))
    check("years Kubernetes = 1", pg.input_value("#y1") == "1")
    check("authorized in France = Non", pg.is_checked("#a2"))
    check("needs sponsorship = Oui", pg.is_checked("#b1"))
    check("English level", pg.eval_on_selector("#lv", "e=>e.options[e.selectedIndex].text") == "Compétence professionnelle complète")
    check("header search box untouched", pg.input_value("header input") == "")
    check("not submitted", "envoyée" not in pg.inner_text("body"))
    check("page-footer newsletter untouched", pg.input_value("#nl") == "")

    answers.set_context("France", "linkedin", "Stage DevOps", "ACME", "Stage DevOps")
    pg.goto((F / "linkedin_2026_radios.html").as_uri())
    from src.form import fill
    r = fill(pg.locator("dialog[open]").first, "devops", "", "")
    for q, a, s in r.log:
        print("     ", s, "|", q[:60], "->", a)
    check("2026 radios: nothing missing", not r.missing, r.missing)
    check("2026 radios: 'applied before?' = Non", pg.is_checked("#r2"))
    check("2026 radios: authorized in region (France) = Non", pg.is_checked("#r4"))
    check("degree level = BAC + 5 (rule, not AI)", pg.eval_on_selector("#dl", "e=>e.options[e.selectedIndex].text") == "BAC + 5"
          and all(s != "llm_choice" for _, _, s in r.log))

    answers.set_context("Germany", "generic", "DevOps Intern", "Acme", "We are hiring a DevOps intern (Kubernetes, AWS)")
    pg.goto((F / "ats_like.html").as_uri())
    out = run_steps(pg, lambda: find_form_scope(pg), "devops", "", "")
    print("   ->", out.status, out.reason)
    for q, a, s in out.log:
        print("     ", s, "|", q[:60], "->", a)
    check("ATS status dry_run (all required answered)", out.status == "dry_run", out.reason)
    check("first/last/email", (pg.input_value("#first"), pg.input_value("#last"), pg.input_value("#email")) == ("Jane", "Doe", "jane.doe@example.com"))
    check("phone international", pg.input_value("#phone") == "+21620123456", pg.input_value("#phone"))
    check("resume in resume field", pg.eval_on_selector("#res", "e=>e.files.length && e.files[0].name") == "Resume_Jane_Doe.pdf")
    check("transcript NOT filled with resume", pg.eval_on_selector("#tr", "e=>e.files.length") == 0)
    check("authorized (combobox) = No", pg.input_value("#cbi") == "No", pg.input_value("#cbi"))
    check("city typeahead picked the Tunisia option", pg.input_value("#city") == "Tunis, Tunis, Tunisia", pg.input_value("#city"))
    check("start date", pg.input_value("#start") == "2027-02-01")
    check("salary number left empty", pg.input_value("#sal") == "")
    check("how did you hear", pg.eval_on_selector("#hear", "e=>e.value") == "Other", pg.eval_on_selector("#hear", "e=>e.value"))
    check("GDPR consent checked", pg.is_checked("#gdpr"))
    check("marketing NOT checked", not pg.is_checked("#news"))
    check("nav inputs untouched", pg.input_value("nav input >> nth=0") == "" and pg.input_value("nav input >> nth=1") == "")
    check("not submitted", "Thank you" not in pg.inner_text("body"))
    b.close()
print("\nFAILURES:", bad)
sys.exit(1 if bad else 0)
