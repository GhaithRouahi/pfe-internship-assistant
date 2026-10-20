"""The engine must never report success when something is wrong. Local pages only, separate headless browser."""
import sys
sys.path.insert(0, ".")
from src.config import CFG
CFG["llm"]["enabled"] = False
CFG["delay_between_actions_sec"] = [0, 0]
from playwright.sync_api import sync_playwright
from src import answers
from src.flow import run_steps, find_form_scope

BASE = """<!doctype html><meta charset=utf-8><form onsubmit="event.preventDefault(); {on_submit}">
<label for=fn>First name *</label><input id=fn required>
<label for=em>Email *</label><input id=em type=email required>
{extra}
<button type=submit>Submit application</button></form>"""
OK_SUBMIT = "document.body.insertAdjacentHTML('beforeend','<h2>Thank you for applying!</h2>')"
NO_CONFIRM = "void 0"
REJECT = "document.body.insertAdjacentHTML('beforeend','<div role=alert>Phone number is invalid</div>')"
bad = 0


def run(pg, extra="", on_submit=OK_SUBMIT, dry=True, allow_choices=False):
    CFG["dry_run"] = dry
    CFG["submit_policy"]["allow_llm_choices"] = allow_choices
    answers.set_context("France", "generic", "DevOps Intern", "Acme", "DevOps internship")
    pg.set_content(BASE.format(extra=extra, on_submit=on_submit))
    return run_steps(pg, lambda: find_form_scope(pg), "devops", "", "")


def expect(name, out, status):
    global bad
    ok = out.status == status
    bad += not ok
    print(("OK  " if ok else "FAIL"), f"{name}: {out.status} ({out.reason[:90]})")


with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page()
    expect("plain form, dry run", run(pg), "dry_run")
    expect("unanswerable required radio -> review",
           run(pg, "<fieldset><legend>Do you have a driving licence? *</legend><input type=radio name=d id=d1 required><label for=d1>Yes</label>"
                   "<input type=radio name=d id=d2><label for=d2>No</label></fieldset>"), "needs_review")
    expect("unanswerable required text -> review", run(pg, "<label for=x>Your favourite Kubernetes operator and why? *</label><input id=x required>"), "needs_review")
    expect("required document (transcript) -> review", run(pg, "<label for=t>Transcript *</label><input type=file id=t required>"), "needs_review")
    expect("required field with no label -> review", run(pg, "<input id=z required>"), "needs_review")
    expect("optional unknown field is left empty, still ok", run(pg, "<label for=o>Hobbies</label><input id=o>"), "dry_run")
    expect("live + confirmation -> applied", run(pg, dry=False), "applied")
    expect("live + no confirmation -> unconfirmed (never counted as applied)", run(pg, on_submit=NO_CONFIRM, dry=False), "unconfirmed")
    expect("live + site rejects -> review", run(pg, on_submit=REJECT, dry=False), "needs_review")

    # an AI-judged answer must block auto-submit unless allowed
    orig = answers._llm
    answers.llm.available = lambda: True
    answers._llm = lambda q, o, free_text: (o[0] if o else "Yes")
    extra = "<label for=s>Which cloud do you prefer? *</label><select id=s required><option value=''>Select</option><option>AWS</option><option>GCP</option></select>"
    expect("AI-judged answer, live, policy off -> review", run(pg, extra, dry=False, allow_choices=False), "needs_review")
    expect("AI-judged answer, live, policy on -> applied", run(pg, extra, dry=False, allow_choices=True), "applied")
    answers._llm = orig
    b.close()
print("\nFAILURES:", bad)
sys.exit(1 if bad else 0)
