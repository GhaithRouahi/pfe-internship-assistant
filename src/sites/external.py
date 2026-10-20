"""Company career pages and ATS forms (Greenhouse, Lever, Workable, SmartRecruiters, Teamtailor, Recruitee, Ashby, WTTJ...)."""
import re
from ..flow import Outcome, run_steps, cookies, find_form_scope, has_form, visible_button, visible_challenge

APPLY_LINK_RE = re.compile(r"^\s*(apply( now| here| online)?( for this (job|position|role|offer))?|apply to this (job|position)|"
                           r"postuler( à cette offre| à ce poste| maintenant| en ligne)?|je postule|candidater|"
                           r"i.m interested|je suis intéressé\(?e?\)?|jetzt bewerben|bewerben|submit your application|start (your )?application|"
                           r"apply manually|postuler manuellement)\s*$", re.I)
ACCOUNT_RE = re.compile(r"create (an |your )?account|sign (in|up) to apply|log ?in to apply|créer (un|votre) compte|se connecter|"
                        r"connectez-vous|register to apply|konto erstellen|anmelden", re.I)
ACCOUNT_HOSTS = re.compile(r"myworkdayjobs|workday|taleo|successfactors|icims|brassring|oraclecloud|phenom|jobs\.sap|kenexa", re.I)


def apply_on_page(page, job, resume_key, cover, cover_pdf) -> Outcome:
    """`page` is on the job / application URL. Clicks through to the form, then runs the step engine."""
    _settle(page)
    cookies(page)
    if visible_challenge(page):
        return Outcome("needs_review", f"captcha / bot check on {_host(page)}")
    for _ in range(2):   # landing page -> 'Apply' -> (sometimes) 'Apply manually'
        if has_form(page) or any(has_form(f) for f in page.frames[1:]):
            break
        btn = visible_button(page, APPLY_LINK_RE)
        if not btn:
            break
        ctx, before = page.context, set(page.context.pages)
        btn.click()
        page.wait_for_timeout(3500)
        new = [p for p in ctx.pages if p not in before]
        if new:
            page = new[-1]
            page.bring_to_front()
        _settle(page)
        cookies(page)
    if page.locator("input[type=password]:visible").count() or ACCOUNT_HOSTS.search(page.url):
        if not (has_form(page) and not page.locator("input[type=password]:visible").count()):
            return Outcome("needs_review", f"account required on {_host(page)} (apply manually with the prepared material)")
    if not has_form(page) and not any(has_form(f) for f in page.frames[1:]):
        body = page.locator("body").inner_text()[:4000]
        why = "account required" if ACCOUNT_RE.search(body) else "application form not recognised"
        return Outcome("needs_review", f"{why} on {_host(page)}")
    return run_steps(page, lambda: find_form_scope(page), resume_key, cover, cover_pdf)


def _settle(page):
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(2000)


def _host(page):
    try:
        return page.url.split("/")[2]
    except Exception:
        return page.url


def apply(ctx, job, resume_key, cover, cover_pdf) -> Outcome:
    before = set(ctx.pages)
    page = ctx.new_page()
    try:
        page.bring_to_front()
        page.goto(job.url, wait_until="domcontentloaded")
        return apply_on_page(page, job, resume_key, cover, cover_pdf)
    except Exception as e:
        return Outcome("error", repr(e)[:300])
    finally:
        for pg in [p for p in ctx.pages if p not in before]:   # close only tabs this application opened
            try:
                pg.close()
            except Exception:
                pass
