"""Fills ONE form step (a page, an iframe or a modal).

Returns a StepResult:
  missing    required questions with no truthful answer -> the offer goes to the review list
  uncertain  answers that came from an LLM judgement (llm_choice)
  log        every (question, answer, source) written, for the review report
"""
import os, re
from dataclasses import dataclass, field
from .answers import answer, norm, P, CTX
from .browser import pause
from .config import CFG, ROOT, RESUMES

# Site chrome = search bars, nav, page header/footer. Anything inside a dialog (LinkedIn's form has its own
# <header>/<footer> holding the Next / Submit buttons) is never chrome.
CHROME_JS = ("e => !e.closest('dialog, [role=dialog], [aria-modal=true]') && !!e.closest('header, nav, footer, [role=search], "
             "[role=banner], [role=navigation], [role=contentinfo], form[role=search], form[action*=search], form[action*=jobs]')")

LABEL_JS = """e => {
  const t = x => (x && (x.innerText || x.textContent) || '').trim();
  const lb = e.getAttribute('aria-labelledby');
  if (lb) { const s = lb.split(/\\s+/).map(i => t(document.getElementById(i))).join(' ').trim(); if (s) return s; }
  if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); if (t(l)) return t(l); }
  const wrap = e.closest('label'); if (t(wrap)) return t(wrap);
  const a = e.getAttribute('aria-label'); if (a) return a;
  // climb only while the container holds this single field: never borrow a neighbouring field's label
  let c = e.parentElement;
  for (let i = 0; i < 4 && c && c.querySelectorAll('input:not([type=hidden]), select, textarea').length === 1; i++, c = c.parentElement) {
    const l = c.querySelector('legend, label, [class*=label], [class*=Label]');
    if (l && !l.contains(e) && t(l)) return t(l);
  }
  return e.getAttribute('placeholder') || '';
}"""

GROUP_Q_JS = """e => {
  const t = x => (x && (x.innerText || x.textContent) || '').trim();
  const sel = 'input[type=' + e.type + '][name="' + CSS.escape(e.name) + '"]';
  const fs = e.closest('fieldset'); if (fs && fs.querySelector('legend') && t(fs.querySelector('legend'))) return t(fs.querySelector('legend'));
  // LinkedIn (2026 UI): every option carries the question as its aria-label, option text sits in a sibling <p>
  const al = [...document.querySelectorAll(sel)].map(x => (x.getAttribute('aria-label') || '').trim());
  if (al.length > 1 && al[0] && al.every(x => x === al[0])) return al[0];
  const rg = e.closest('[role=radiogroup], [role=group]');
  if (rg) {
    const lb = rg.getAttribute('aria-labelledby');
    if (lb) { const s = lb.split(/\\s+/).map(i => t(document.getElementById(i))).join(' ').trim(); if (s) return s; }
    if (rg.getAttribute('aria-label')) return rg.getAttribute('aria-label');
  }
  let c = e.parentElement;
  while (c && c.querySelectorAll(sel).length < 2) c = c.parentElement;
  for (let k = 0; k < 2 && c; k++, c = c.parentElement) {
    let txt = t(c);
    for (const l of c.querySelectorAll('label')) txt = txt.replace(t(l), '');
    const line = txt.split('\\n').map(x => x.trim()).filter(Boolean)[0];
    if (line) return line;
  }
  return '';
}"""

OPTION_LABEL_JS = """e => {
  const t = x => (x && (x.innerText || x.textContent) || '').trim();
  if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); if (t(l)) return t(l); }
  if (t(e.closest('label'))) return t(e.closest('label'));
  // text of the largest container that holds only this option (LinkedIn: empty <label>, text in a sibling <p>)
  if (e.name) {
    const sel = 'input[type=' + e.type + '][name="' + CSS.escape(e.name) + '"]';
    let c = e.parentElement, best = '';
    while (c && c.querySelectorAll(sel).length === 1) { if (t(c)) best = t(c); c = c.parentElement; }
    if (best) return best;
  }
  if (e.value && e.value !== 'on') return e.value;
  return e.getAttribute('aria-label') || '';
}"""

REQUIRED_JS = """e => {
  const t = x => (x && (x.innerText || x.textContent) || '');
  if (e.required || e.getAttribute('aria-required') === 'true') return true;
  const re = /\\*|\\brequired\\b|obligatoire|pflicht|requis/i;
  if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); if (l && re.test(t(l))) return true; }
  const g = e.closest('fieldset, [role=radiogroup], [role=group]');
  if (g && (g.getAttribute('aria-required') === 'true' || re.test(t(g.querySelector('legend'))))) return true;
  const w = e.closest('label'); if (w && re.test(t(w))) return true;
  return false;
}"""

PLACEHOLDER_OPT = re.compile(r"^(select|selectionnez|choisissez|choose|please|veuillez|bitte|--|—|-$|$)", re.I)
CONSENT = re.compile(r"agree|consent|accept|j.accepte|conditions|privacy|confidentialit|terms|rgpd|gdpr|datenschutz|einverstanden|"
                     r"certif|attest|declare|i have read|j.ai lu|politique", re.I)
MARKETING = re.compile(r"newsletter|marketing|promotion|offres? (commerciales|similaires)|job alert|alerte|talent (community|pool)|"
                       r"vivier|keep me informed|tenez-moi|future (opportunities|openings)|follow|suivre", re.I)
COVER_FILE = re.compile(r"cover|lettre|motivation|anschreiben|carta", re.I)
OTHER_FILE = re.compile(r"transcript|releve|diplom|photo|picture|portrait|certificat|passport|passeport|id card|identite|"
                        r"zeugnis|portfolio|writing sample|other|autre", re.I)
COVER_TEXT = re.compile(r"cover letter|lettre de motivation|motivation letter|anschreiben|message (to|for|au|pour) (the )?(hiring|recruit|responsable)|"
                        r"message au recruteur|why (do )?you want|pourquoi (souhaitez|voulez)", re.I)


@dataclass
class StepResult:
    missing: list = field(default_factory=list)
    uncertain: list = field(default_factory=list)
    log: list = field(default_factory=list)


def in_chrome(el):
    """True for site chrome (search bars, nav, footer) that must never be filled."""
    try:
        return bool(el.evaluate(CHROME_JS))
    except Exception:
        return False


def trace(*a):
    if os.environ.get("AUTOAPPLY_DEBUG"):
        print("   [trace]", *a)


def _ev(el, js, default=""):
    try:
        return el.evaluate(js)
    except Exception:
        return default


def _clean(s):
    return " ".join(str(s or "").split())


def _required(el):
    return bool(_ev(el, REQUIRED_JS, True))


def _record(res, q, a, src):
    res.log.append((q, a, src))
    if src == "llm_choice":
        res.uncertain.append((q, a))
    trace(f"{src:10s} {q[:70]!r} -> {str(a)[:80]!r}")


def _phone_value(scope):
    """National number when the form has its own country-code selector, else international."""
    has_cc = scope.locator("select, [role=combobox]").filter(has_text=re.compile(r"\+\d{1,3}")).count() > 0 or \
        scope.get_by_text(re.compile(r"country code|code pays|indicatif", re.I)).count() > 0
    return P["phone_national"] if has_cc else f'{P["phone_country_code"]}{P["phone_national"]}'


def _same_phone(a, b):
    da, db = re.sub(r"\D", "", a or ""), re.sub(r"\D", "", b or "")
    return bool(da) and (da.endswith(P["phone_national"]) and db.endswith(P["phone_national"]))


# ------------------------------------------------------------------ files

SHOWN_JS = """e => {
  const vis = x => !!(x && (x.offsetWidth || x.offsetHeight || x.getClientRects().length) && getComputedStyle(x).visibility !== 'hidden');
  if (vis(e)) return true;
  if (e.labels && [...e.labels].some(vis)) return true;
  return vis(e.parentElement);
}"""


def _shown(el):
    """Visible, or a hidden native input whose label / wrapper is on screen (custom-styled radios, file pickers).
    Fields on hidden steps of a multi-step form are NOT shown."""
    return bool(_ev(el, SHOWN_JS, False))


EMPTY_REQUIRED_JS = """root => {
  const vis = x => !!(x && (x.offsetWidth || x.offsetHeight || x.getClientRects().length) && getComputedStyle(x).visibility !== 'hidden');
  const shown = e => vis(e) || (e.labels && [...e.labels].some(vis)) || vis(e.parentElement);
  const inChrome = e => !!e.closest('header, nav, footer, [role=search], [role=banner], [role=navigation]');
  const req = e => e.required || e.getAttribute('aria-required') === 'true';
  const name = e => ((e.id && document.querySelector('label[for="' + CSS.escape(e.id) + '"]')) || {}).innerText || e.getAttribute('aria-label') || e.name || e.id || e.type;
  const out = [];
  const els = root.querySelectorAll ? root.querySelectorAll('input, select, textarea') : [];
  const radios = {};
  for (const e of els) {
    if (!shown(e) || inChrome(e) || e.disabled || e.type === 'hidden' || e.type === 'submit' || e.type === 'button') continue;
    if (e.type === 'radio') { if (req(e)) radios[e.name] = radios[e.name] || e; continue; }
    if (!req(e)) continue;
    if (e.type === 'checkbox') { if (!e.checked) out.push(name(e)); continue; }
    if (e.type === 'file') { if (!e.files || !e.files.length) out.push(name(e)); continue; }
    if (e.tagName === 'SELECT') { const o = e.options[e.selectedIndex]; if (!e.value || !o || /^(select|s.lectionnez|choisissez|choose|please|--)/i.test(o.text.trim())) out.push(name(e)); continue; }
    if (!String(e.value || '').trim()) out.push(name(e));
  }
  for (const [n, e] of Object.entries(radios)) if (![...root.querySelectorAll('input[type=radio][name="' + CSS.escape(n) + '"]')].some(r => r.checked)) out.push(name(e));
  return out.map(s => String(s).trim().replace(/\\s+/g, ' ').slice(0, 80));
}"""


def _check(scope, target) -> bool:
    """Select a radio/checkbox whatever its styling: the input, its label, its option text, then a raw click event."""
    tid = target.get_attribute("id")
    attempts = [lambda: target.check(timeout=3000)]
    if tid:
        attempts.append(lambda: scope.locator(f'label[for="{tid}"]').first.click(timeout=3000))
    attempts.append(lambda: target.evaluate("e => { let c = e.parentElement; const sel = 'input[type=' + e.type + '][name=\"' + CSS.escape(e.name) + '\"]';"
                                            " while (c.parentElement && c.parentElement.querySelectorAll(sel).length === 1) c = c.parentElement;"
                                            " (c.querySelector('p, span, div:not(:has(input))') || c).click(); }"))
    attempts.append(lambda: target.evaluate("e => e.click()"))
    for attempt in attempts:
        try:
            attempt()
        except Exception:
            pass
        try:
            if target.is_checked():
                return True
        except Exception:
            pass
    return False


def unanswered_required(scope):
    """Safety net run before every Next / Submit: required fields that are still empty, whatever the reason."""
    try:
        root = scope if hasattr(scope, "evaluate") and not hasattr(scope, "goto") and not hasattr(scope, "child_frames") else None
        if root is not None:
            return root.evaluate(EMPTY_REQUIRED_JS)
        return scope.evaluate(f"() => ({EMPTY_REQUIRED_JS})(document)")
    except Exception:
        return []


def _files(scope, res, resume_key, cover_pdf):
    for el in scope.locator("input[type=file]").all():
        if in_chrome(el) or not _shown(el):
            continue
        lab = _clean(_ev(el, LABEL_JS)) + " " + (el.get_attribute("name") or "") + " " + (el.get_attribute("id") or "")
        current = _ev(el, "e => e.files && e.files.length ? e.files[0].name : ''")
        if COVER_FILE.search(lab):
            if not cover_pdf:
                if _required(el):
                    res.missing.append("cover letter file")
                continue
            if not _required(el) and not CFG.get("attach_cover_letter_when_optional", True):
                continue
            if current != os.path.basename(cover_pdf):
                el.set_input_files(cover_pdf)
                _record(res, "cover letter file", os.path.basename(cover_pdf), "llm_text")
            continue
        if OTHER_FILE.search(lab) and not re.search(r"resume|cv\b|curriculum|lebenslauf", lab, re.I):
            if _required(el):
                res.missing.append(f"document upload: {_clean(lab)[:60]}")
            continue
        path = str(ROOT / RESUMES[resume_key]["file"])
        if current != os.path.basename(path):
            el.set_input_files(path)
            _record(res, "resume file", os.path.basename(path), "profile")
            el.page.wait_for_timeout(2500)


# ------------------------------------------------------------------ comboboxes (custom dropdowns / typeaheads)

def _visible_options(page):
    try:
        return [o for o in page.locator("[role=option]:visible, [role=listbox] li:visible").all()[:60]]
    except Exception:
        return []


def _combobox(el, q, res, kind_hint):
    page = el.page
    el.click()
    page.wait_for_timeout(700)
    opts = _visible_options(page)
    texts = [_clean(o.inner_text()) for o in opts]
    if texts and len(texts) >= 2:   # a real choice list
        a = answer(q, texts, "select")
        if a is None:
            page.keyboard.press("Escape")
            return False
        for o, t in zip(opts, texts):
            if t == a.value:
                o.click()
                page.wait_for_timeout(500)
                shown = norm(el.input_value() or "") or norm(_ev(el, "e => (e.closest('[role=combobox]') || e.parentElement).innerText", ""))
                if norm(t) not in shown:
                    return False   # the widget did not take the value
                _record(res, q, a.value, a.source)
                return True
        page.keyboard.press("Escape")
        return False
    if not el.is_editable():   # read-only dropdown whose list did not open: cannot answer safely
        page.keyboard.press("Escape")
        return False
    a = answer(q, None, kind_hint)   # typeahead: type, then choose the matching suggestion
    if a is None:
        page.keyboard.press("Escape")
        return False
    typed = P["city"] if norm(a.value).startswith(norm(P["city"])) else a.value
    el.fill(typed)
    page.wait_for_timeout(1800)
    opts = _visible_options(page)
    for o in opts:
        shown = _clean(o.inner_text())   # read before clicking: the list closes afterwards
        t = norm(shown)
        if t.startswith(norm(typed)) and (norm(typed) != norm(P["city"]) or norm(P["country"]) in t or norm(P["country_fr"]) in t):
            o.click()
            page.wait_for_timeout(500)
            got = el.input_value()
            if got and norm(got) != t and not norm(got).startswith(norm(typed)):
                el.fill("")
                return False
            _record(res, q, shown, a.source)
            return True
    el.fill("")
    page.keyboard.press("Escape")
    return False


# ------------------------------------------------------------------ main

def fill(scope, resume_key: str, cover_text: str = "", cover_pdf: str = "") -> StepResult:
    res = StepResult()
    _files(scope, res, resume_key, cover_pdf)
    enforce = CFG.get("enforce_contact_fields", True)

    # ---- text-like inputs and textareas
    sel = ("input:not([type]):visible, input[type=text]:visible, input[type=email]:visible, input[type=tel]:visible, "
           "input[type=url]:visible, input[type=number]:visible, input[type=date]:visible, input[type=month]:visible, textarea:visible")
    for el in scope.locator(sel).all():
        is_combo = el.get_attribute("role") == "combobox" or el.get_attribute("aria-autocomplete") in ("list", "both")
        if in_chrome(el) or (not is_combo and not el.is_editable()) or el.is_disabled():
            continue
        q = _clean(_ev(el, LABEL_JS))
        typ = (el.get_attribute("type") or "text").lower()
        kind = "textarea" if _ev(el, "e => e.tagName") == "TEXTAREA" else typ
        cur = el.input_value().strip()
        nq = norm(q)
        if cur:
            if enforce and q:   # prefilled contact data must match your profile
                if re.search(r"e-?mail|courriel", nq) and "@" in cur and cur.lower() != P["email"].lower():
                    el.fill(P["email"]); _record(res, q, P["email"], "profile")
                elif re.search(r"phone|telephone|mobile|portable|telefon", nq) and not _same_phone(cur, P["phone_national"]):
                    v = _phone_value(scope); el.fill(v); _record(res, q, v, "profile")
            continue
        if not q:
            if _required(el):
                res.missing.append("(unlabelled field)")
            continue
        if is_combo:
            if not _combobox(el, q, res, kind) and _required(el):
                res.missing.append(q)
            pause()
            continue
        if cover_text and COVER_TEXT.search(q) and kind in ("textarea", "text"):
            a_val, src = cover_text, "llm_text"
        else:
            a = answer(q, None, kind, el.get_attribute("placeholder") or "")
            if a is None:
                if _required(el):
                    res.missing.append(q)
                continue
            a_val, src = a.value, a.source
            if a_val == "PHONE":
                a_val = _phone_value(scope)
        a_val = str(a_val)
        if kind == "number" and not re.fullmatch(r"\d+(\.\d+)?", a_val):
            if _required(el):
                res.missing.append(q)
            continue
        if kind == "email" and "@" not in a_val:
            res.missing.append(q)
            continue
        maxlen = el.get_attribute("maxlength")
        if maxlen and maxlen.isdigit() and len(a_val) > int(maxlen):
            if src != "llm_text":
                res.missing.append(f"{q} (answer longer than {maxlen} chars)")
                continue
            cut = a_val[: int(maxlen)]
            a_val = cut[: max(cut.rfind(". ") + 1, cut.rfind("\n"))] or cut.rsplit(" ", 1)[0]
        el.fill(a_val)
        got = el.input_value()
        if got.strip() != a_val.strip() and not (_same_phone(got, a_val)):
            res.missing.append(f"{q} (field rejected value)")
            continue
        _record(res, q, a_val, src)
        pause()

    # ---- native selects
    for el in scope.locator("select:visible").all():
        if in_chrome(el):
            continue
        q = _clean(_ev(el, LABEL_JS))
        options = _ev(el, "e => [...e.options].map(o => [o.value, (o.text || '').trim(), o.disabled])", [])
        real = [(v, t) for v, t, dis in options if not dis and v != "" and not PLACEHOLDER_OPT.match(norm(t))]
        cur_text = _ev(el, "e => e.selectedIndex >= 0 ? (e.options[e.selectedIndex].text || '').trim() : ''")
        cur_val = _ev(el, "e => e.value")
        answered = cur_val != "" and not PLACEHOLDER_OPT.match(norm(cur_text or ""))
        if answered:
            if enforce and re.search(r"e-?mail|courriel", norm(q)) and "@" in cur_text and cur_text.lower() != P["email"].lower():
                match = [v for v, t in real if t.lower() == P["email"].lower()]
                if match:
                    el.select_option(value=match[0]); _record(res, q, P["email"], "profile")
                else:
                    _record(res, q + " (your profile email is not in this site's list; kept)", cur_text, "profile")
            continue
        a = answer(q, [t for _, t in real], "select")
        if a is None:
            if _required(el):
                res.missing.append(q)
            continue
        val = [v for v, t in real if t == a.value]
        if not val:
            res.missing.append(q)
            continue
        el.select_option(value=val[0])
        _record(res, q, a.value, a.source)
        pause()

    # ---- radio groups
    done = set()
    for el in scope.locator("input[type=radio]").all():
        name = el.get_attribute("name") or ""
        if not name or name in done or in_chrome(el):
            continue
        done.add(name)
        group = scope.locator(f'input[type=radio][name="{name}"]')
        if group.evaluate_all("els => els.some(e => e.checked)"):
            continue
        if not any(_shown(group.nth(i)) for i in range(group.count())):
            continue
        q = _clean(_ev(el, GROUP_Q_JS))
        labels = [_clean(group.nth(i).evaluate(OPTION_LABEL_JS)) for i in range(group.count())]
        a = answer(q, labels, "radio") if q else None
        if a is None or a.value not in labels:
            res.missing.append(q or "(unlabelled choice)")   # an unanswered radio question is treated as mandatory
            trace("unanswered radio", repr(q), labels, _ev(el, "e => { let c = e; for (let i = 0; i < 5 && c.parentElement; i++) c = c.parentElement; return c.outerHTML.slice(0, 1500); }"))
            continue
        target = group.nth(labels.index(a.value))
        if not _check(scope, target):
            res.missing.append(q + " (could not select)")
            continue
        _record(res, q, a.value, a.source)
        pause()

    # ---- checkboxes: consent only; groups of checkboxes = multi-select questions
    seen_groups = set()
    for el in scope.locator("input[type=checkbox]").all():
        if in_chrome(el) or not _shown(el):
            continue
        name = el.get_attribute("name") or el.get_attribute("id") or ""
        siblings = scope.locator(f'input[type=checkbox][name="{name}"]').count() if el.get_attribute("name") else 1
        lab = _clean(_ev(el, OPTION_LABEL_JS))
        if siblings > 1:
            if name in seen_groups:
                continue
            seen_groups.add(name)
            group = scope.locator(f'input[type=checkbox][name="{name}"]')
            if group.evaluate_all("els => els.some(e => e.checked)"):
                continue
            if any(_required(group.nth(i)) for i in range(group.count())):
                res.missing.append(_clean(_ev(el, GROUP_Q_JS)) or "(multi-select question)")
            continue
        if el.is_checked():
            continue
        if MARKETING.search(lab) and not _required(el):
            continue   # never opt into newsletters / talent pools / follow-company
        if CONSENT.search(lab):
            if _required(el) or re.search(r"privacy|confidentialit|rgpd|gdpr|datenschutz|data|donnees|traitement", lab, re.I):
                el.check(force=True)
                _record(res, lab[:80], "checked", "rule")
            continue
        if _required(el):
            res.missing.append(lab or "(required checkbox)")
            trace("unanswered checkbox", repr(lab), _ev(el, "e => { let c = e; for (let i = 0; i < 5 && c.parentElement; i++) c = c.parentElement; return c.outerHTML.slice(0, 1500); }"))
    return res
