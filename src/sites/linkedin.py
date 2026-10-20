import re
from urllib.parse import quote
from .base import Job
from . import external
from ..config import CFG
from ..flow import run_steps, Outcome

NAME = "linkedin"
EASY_RE = re.compile(r"Easy Apply|Candidature simplifi", re.I)
EXT_RE = re.compile(r"^(Apply|Postuler)\b|Apply on company|Postuler sur|Candidater", re.I)
APPLIED_RE = re.compile(r"Candidature envoyée|Vous avez postulé|Postulé il y a|Applied \d|Application submitted|Applied on", re.I)
# LinkedIn's form is a native <dialog open> (hashed class names); older UI used div.jobs-easy-apply-modal
MODAL = "dialog[open]:has(input, select, textarea, button), div.jobs-easy-apply-modal"


def logged_in(ctx) -> bool:
    page = ctx.new_page()
    try:
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        return not re.search(r"/login|authwall|checkpoint|/signup", page.url)
    finally:
        page.close()


def search(ctx, kw, loc):
    page = ctx.new_page()
    page.bring_to_front()
    easy = "" if CFG.get("include_external_apply", True) else "&f_AL=true"
    try:
        page.goto(f"https://www.linkedin.com/jobs/search/?keywords={quote(kw)}&location={quote(loc)}{easy}&f_E=1&sortBy=DD",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(4500)
        jobs, ids = [], set()
        cards = page.locator("li[data-occludable-job-id]")
        for i in range(min(cards.count(), 25)):
            card = cards.nth(i)
            jid = card.get_attribute("data-occludable-job-id")
            if not jid or jid in ids:
                continue
            ids.add(jid)
            try:
                card.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(250)
                lines = [l.strip() for l in card.inner_text(timeout=3000).splitlines() if l.strip()]
            except Exception:
                lines = []
            # card title (first line, LinkedIn sometimes repeats it "with verification"); empty -> decided on the job page
            jobs.append(Job(NAME, f"https://www.linkedin.com/jobs/view/{jid}/", lines[0] if lines else "", lines[1] if len(lines) > 1 else ""))
        return jobs
    finally:
        page.close()


def hydrate(ctx, job: Job):
    """Title / company / description from the job page itself (robust to LinkedIn's hashed class names)."""
    page = ctx.new_page()
    try:
        page.bring_to_front()
        page.goto(job.url, wait_until="domcontentloaded")
        page.wait_for_load_state("load")
        page.wait_for_timeout(2500)
        parts = [p.strip() for p in page.title().split(" | ")]
        job.title = parts[0] if parts else ""
        job.company = parts[1] if len(parts) > 2 else ""
        main = page.locator("main").first
        main_txt = main.inner_text() if main.count() else page.locator("body").inner_text()
        about = page.get_by_text(re.compile(r"^(À propos de l.offre d.emploi|About the job)$")).first
        txt = ""
        if about.count():
            txt = about.evaluate("e => { let c = e; for (let i = 0; i < 4 && c; i++) { c = c.parentElement; "
                                 "if (c && c.innerText.length > 400) return c.innerText; } return ''; }")
        job.text = (txt or main_txt)[:8000]
        job.meta = main_txt[:1500]   # header: location, 'Stage', 'Stagiaire / Alternant', applicants...
    finally:
        page.close()


def apply(ctx, job: Job, resume_key: str, cover: str, cover_pdf: str) -> Outcome:
    page = ctx.new_page()
    try:
        page.bring_to_front()   # background tabs are throttled and render late
        page.goto(job.url, wait_until="domcontentloaded")
        page.wait_for_load_state("load")
        page.wait_for_timeout(2500)
        if re.search(r"/login|authwall|checkpoint", page.url):
            return Outcome("error", "LinkedIn is logged out in this Chrome")
        easy = _first_visible(page, EASY_RE, "button")
        if easy:
            easy.click()
            try:
                page.locator(MODAL).first.wait_for(state="visible", timeout=15000)
            except Exception:
                return Outcome("error", "Easy Apply form did not open after click")
            out = run_steps(page, lambda: page.locator(MODAL).first, resume_key, cover, cover_pdf)
            if out.status in ("applied", "unconfirmed"):
                _dismiss_done(page)
            else:
                _close(page, save=(out.status == "needs_review" and not CFG["dry_run"]))
            return out
        ext = _first_visible(page, EXT_RE, "button") or _first_visible(page, EXT_RE, "link")
        if ext:
            return _external(ctx, ext, job, resume_key, cover, cover_pdf)
        main_txt = page.locator("main").first.inner_text() if page.locator("main").count() else ""
        if APPLIED_RE.search(main_txt[:3000]):
            return Outcome("skipped", "you already applied to this offer")
        if re.search(r"n.accepte plus de candidatures|no longer accepting applications", main_txt, re.I):
            return Outcome("skipped", "offer closed")
        return Outcome("error", "no apply button found on the job page")
    except Exception as e:
        return Outcome("error", repr(e)[:300])
    finally:
        try:
            page.close()
        except Exception:
            pass


def _first_visible(page, regex, role):
    """Real apply control only: visible and not inside a job card / list item (cards also say 'Candidature simplifiée')."""
    for b in page.get_by_role(role, name=regex).all():
        try:
            if b.is_visible() and not b.evaluate("e => !!e.closest('li, [data-occludable-job-id], [data-job-id], aside')"):
                return b
        except Exception:
            continue
    return None


def _external(ctx, btn, job, resume_key, cover, cover_pdf) -> Outcome:
    """Offer applies on the company site: follow the link and run the generic engine there."""
    before = set(ctx.pages)
    ext = None
    try:
        with ctx.expect_page(timeout=12000) as np:
            btn.click()
        ext = np.value
    except Exception:
        new = [p for p in ctx.pages if p not in before]
        ext = new[0] if new else None
    if ext is None:
        return Outcome("error", "external apply link did not open")
    try:
        ext.bring_to_front()
        ext.wait_for_load_state("domcontentloaded")
        return external.apply_on_page(ext, job, resume_key, cover, cover_pdf)
    finally:
        for p in [p for p in ctx.pages if p not in before]:   # close only tabs this application opened
            try:
                p.close()
            except Exception:
                pass


def _close(page, save=False):
    """Close the Easy Apply form. save=True keeps LinkedIn's draft so you can finish it in one click."""
    choice = re.compile(r"^\s*(Enregistrer|Save)\s*$", re.I) if save else re.compile(r"^\s*(Supprimer|Abandonner|Discard|Delete)\s*$", re.I)
    try:
        page.locator(MODAL).first.locator("button[aria-label*='Ignorer'], button[aria-label*='Dismiss'], button[aria-label*='Fermer'], "
                                          "button[aria-label*='Close']").first.click(timeout=3000)
    except Exception:
        page.keyboard.press("Escape")
    page.wait_for_timeout(1200)
    try:
        page.get_by_role("button", name=choice).first.click(timeout=3000)
    except Exception:
        pass
    page.wait_for_timeout(800)


def _dismiss_done(page):
    try:
        page.get_by_role("button", name=re.compile(r"^\s*(Terminé|Done|OK)\s*$", re.I)).first.click(timeout=3000)
    except Exception:
        pass
