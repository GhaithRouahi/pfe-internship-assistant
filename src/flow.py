"""Shared multi-step application engine (LinkedIn Easy Apply modal, company/ATS forms).

Outcome.status:
  applied       submitted and the site confirmed it
  unconfirmed   submit clicked but no confirmation seen -> check manually before re-applying
  dry_run       everything filled, stopped before the final submit (dry_run: true)
  needs_review  good offer the bot could not finish with certainty -> review list with everything prepared
  error         technical failure -> retried on the next run
"""
import re
from dataclasses import dataclass, field
from .browser import pause
from .config import CFG
from .form import fill, trace, in_chrome, unanswered_required

SUBMIT_RE = re.compile(r"^\s*(submit( (my |your )?application)?|send( (my )?application)?|apply( now)?|"
                       r"envoyer( ma| la| votre| mon)?( candidature| dossier)?|soumettre( ma candidature)?|valider (ma|la) candidature|"
                       r"bewerbung (absenden|abschicken|senden)|absenden|enviar( solicitud| candidatura)?|finish|terminer)\s*$", re.I)
NEXT_RE = re.compile(r"^\s*(next|continue|continue to .*|review( your application)?|save and continue|suivant|continuer|"
                     r"v[ée]rifier( votre candidature)?|examiner( votre candidature)?|weiter|siguiente|passe[rz] à l.étape suivante|next step)\s*$", re.I)
DONE_RE = re.compile(r"(application (was |has been )?(sent|submitted|received)|thank you for (applying|your application)|thanks for applying|"
                     r"candidature (a (bien )?été |est )?(envoyée|reçue|transmise|enregistrée)|merci (pour|de) votre candidature|"
                     r"votre candidature a bien|bewerbung (ist |wurde )?(eingegangen|erfolgreich|versendet)|vielen dank für ihre bewerbung|"
                     r"we('ve| have) received your application|your application is (complete|on its way))", re.I)
COOKIE_SEL = ("#onetrust-accept-btn-handler, #didomi-notice-agree-button, #axeptio_btn_acceptAll, .tarteaucitronAllow, "
              "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll, #cookie-accept, button[data-testid*=cookie-accept], "
              "[id*=cookie i] button, [class*=cookie i] button, [id*=consent i] button, [class*=consent i] button")
COOKIE_RE = re.compile(r"^\s*(accept( all)?( cookies)?|accepter( tout| et fermer| les cookies)?|tout accepter|allow all|"
                       r"j.accepte|alle akzeptieren|agree|ok|d.accord)\s*$", re.I)
ERROR_SEL = (".artdeco-inline-feedback--error, [data-test-form-element-error-messages], [role=alert], .error-message, .invalid-feedback, "
             ".field-error, .help-block.error, [id$=-error], [class*=errorMessage], [class*=error-text]")


@dataclass
class Outcome:
    status: str
    reason: str = ""
    log: list = field(default_factory=list)
    uncertain: list = field(default_factory=list)


def cookies(page):
    """Click a cookie-consent accept button, only inside a cookie/consent banner."""
    try:
        for b in page.locator(COOKIE_SEL).all()[:15]:
            try:
                if not b.is_visible():
                    continue
                bid = (b.get_attribute("id") or "").lower()
                if "accept" in bid or "agree" in bid or "allow" in bid or COOKIE_RE.match(b.inner_text() or ""):
                    b.click(timeout=1500)
                    page.wait_for_timeout(600)
                    return
            except Exception:
                continue
    except Exception:
        pass


def visible_challenge(page) -> bool:
    """A captcha that needs a human (invisible reCAPTCHA / hCaptcha badges do NOT count)."""
    sel = ("iframe[src*='recaptcha'][src*='size=normal'], iframe[src*='recaptcha'][src*='size=compact'], "
           "iframe[src*='recaptcha/api2/bframe'], iframe[src*='hcaptcha'][src*='challenge'], #challenge-form, #cf-challenge-running, "
           "iframe[src*='challenges.cloudflare.com']")
    try:
        for f in page.locator(sel).all():
            box = f.bounding_box()
            if f.is_visible() and box and box["height"] > 40:
                return True
        return page.get_by_text(re.compile(r"verify you are human|vérifiez que vous êtes humain|vérification supplémentaire", re.I)).count() > 0
    except Exception:
        return False


def visible_button(scope, regex):
    """First visible, enabled button / link whose accessible name matches, outside site header/nav."""
    for role in ("button", "link"):
        try:
            for b in scope.get_by_role(role, name=regex).all():
                try:
                    if b.is_visible() and b.is_enabled() and not in_chrome(b):
                        return b
                except Exception:
                    continue
        except Exception:
            continue
    return None


def has_form(scope) -> bool:
    """A real application form: a file input, a textarea, or >=2 text inputs outside header/nav/search."""
    try:
        if scope.locator("input[type=file]").count() or scope.locator("textarea:visible").count():
            return True
        els = scope.locator("input:not([type=hidden]):not([type=search]):not([type=checkbox]):not([type=radio]):not([type=submit]):visible").all()
        return len([e for e in els if not in_chrome(e)]) >= 2
    except Exception:
        return False


def find_form_scope(page):
    """The page, or the iframe holding the application form (Greenhouse, Workable, SmartRecruiters... embed it)."""
    if has_form(page):
        return page
    for fr in page.frames[1:]:
        if has_form(fr):
            return fr
    return page


def _errors(scope):
    out = []
    try:
        for e in scope.locator(ERROR_SEL).all()[:8]:
            try:
                t = " ".join(e.inner_text().split())
                if e.is_visible() and t and t not in out:
                    out.append(t)
            except Exception:
                continue
        for e in scope.locator("[aria-invalid=true]:visible").all()[:4]:
            lab = e.evaluate("e => (e.id && document.querySelector('label[for=\"'+CSS.escape(e.id)+'\"]') || {}).innerText || e.name || ''")
            if lab:
                out.append("invalid: " + " ".join(lab.split()))
    except Exception:
        pass
    return out[:5]


def _signature(scope):
    try:
        return " ".join(scope.locator("body").inner_text().split())[:600] if hasattr(scope, "goto") or hasattr(scope, "child_frames") \
            else " ".join(scope.inner_text().split())[:600]
    except Exception:
        return ""


def _confirmed(page, wait_ms=12000):
    for _ in range(wait_ms // 1000):
        try:
            if any(DONE_RE.search(f.locator("body").inner_text()) for f in [page.main_frame, *page.frames[1:3]]):
                return True
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def run_steps(page, get_scope, resume_key, cover_text, cover_pdf, max_steps=15) -> Outcome:
    log, uncertain, stuck = [], [], 0
    for step in range(max_steps):
        page.wait_for_timeout(1200)
        scope = get_scope()
        if visible_challenge(page):
            return Outcome("needs_review", "captcha must be solved by a human", log, uncertain)
        r = fill(scope, resume_key, cover_text, cover_pdf)
        log += r.log
        uncertain += r.uncertain
        page.wait_for_timeout(500)
        r.missing += [f"{m} (still empty)" for m in unanswered_required(get_scope()) if m and not any(m[:25] in x for x in r.missing)]
        if r.missing:
            return Outcome("needs_review", "needs your answer: " + " | ".join(dict.fromkeys(m for m in r.missing if m))[:400], log, uncertain)
        sub = visible_button(scope, SUBMIT_RE)
        nxt = visible_button(scope, NEXT_RE)
        trace(f"step {step + 1}: submit={bool(sub)} next={bool(nxt)}")
        if sub and not nxt:
            if uncertain and not CFG["submit_policy"].get("allow_llm_choices", False):
                return Outcome("needs_review", f"{len(uncertain)} answer(s) were judged by the AI, please confirm", log, uncertain)
            if CFG["dry_run"]:
                return Outcome("dry_run", "everything filled, stopped before submit", log, uncertain)
            sub.click()
            if _confirmed(page):
                return Outcome("applied", "", log, uncertain)
            errs = _errors(get_scope())
            if errs:
                return Outcome("needs_review", "site rejected the submission: " + " | ".join(errs)[:300], log, uncertain)
            return Outcome("unconfirmed", "submit clicked but no confirmation message seen - check before re-applying", log, uncertain)
        if not nxt:
            return Outcome("needs_review", f"no Next/Submit button recognised on step {step + 1}", log, uncertain)
        before = _signature(scope)
        nxt.click()
        pause()
        page.wait_for_timeout(1500)
        after = _signature(get_scope())
        if after == before:
            errs = _errors(get_scope())
            stuck += 1
            if errs or stuck >= 2:
                return Outcome("needs_review", "form did not accept the step: " + (" | ".join(errs) or "no visible error")[:300], log, uncertain)
        else:
            stuck = 0
    return Outcome("needs_review", "more steps than expected", log, uncertain)
