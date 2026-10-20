"""Browser tool Claude uses to fill applications itself (look -> think -> act), one command per call.

  python agent.py queue                         selected offers waiting to be handled
  python agent.py prep <url>                    prepared material for an offer (resume, cover letter, fit)
  python agent.py open <url>                    open the offer in Claude's tab (in your Chrome)
  python agent.py look                          screenshot (data/agent/screen.png) + numbered list of fields and buttons
  python agent.py text                          visible text of the form / page
  python agent.py fill <n> <text>               type into field n (replaces its content)
  python agent.py select <n> <option text>      choose an option in a <select>
  python agent.py check <n>                     tick radio / checkbox n
  python agent.py click <n>                     click button / link / element n
  python agent.py pick <n> <text>               typeahead: type text into n, then click the matching suggestion
  python agent.py upload <n> <resume|cover|path>  attach the resume chosen for the offer, its cover letter PDF, or a file
  python agent.py press <Key>                   keyboard key (Escape, Enter, Tab...)
  python agent.py scroll <up|down>              scroll the form
  python agent.py record <url> <applied|needs_review|skipped> <note>
"""
import json, re, sys
from pathlib import Path
from src.browser import launch, shutdown
from src.config import ROOT, RESUMES, PROFILE
from src import store

STATE = ROOT / "data" / "agent"
STATE.mkdir(parents=True, exist_ok=True)
TAB = STATE / "tab.json"

MAP_JS = r"""() => {
  const vis = x => !!(x && (x.offsetWidth || x.offsetHeight || x.getClientRects().length) && getComputedStyle(x).visibility !== 'hidden');
  const t = x => ((x && (x.innerText || x.textContent)) || '').replace(/\s+/g, ' ').trim();
  const dlg = [...document.querySelectorAll('dialog[open], [role=dialog], [aria-modal=true]')].filter(d => vis(d) && d.querySelector('input, select, textarea, button'));
  const root = dlg.length ? dlg[dlg.length - 1] : document.body;
  document.querySelectorAll('[data-agent-id]').forEach(e => e.removeAttribute('data-agent-id'));
  const label = e => {
    const lb = e.getAttribute('aria-labelledby');
    if (lb) { const s = lb.split(/\s+/).map(i => t(document.getElementById(i))).join(' ').trim(); if (s) return s; }
    if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); if (t(l)) return t(l); }
    if (t(e.closest('label'))) return t(e.closest('label'));
    if (e.getAttribute('aria-label')) return e.getAttribute('aria-label');
    let c = e.parentElement;
    for (let i = 0; i < 4 && c && c.querySelectorAll('input:not([type=hidden]), select, textarea').length === 1; i++, c = c.parentElement) {
      const l = c.querySelector('legend, label'); if (l && t(l)) return t(l);
    }
    return e.getAttribute('placeholder') || '';
  };
  const optText = e => {
    if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); if (t(l)) return t(l); }
    // largest container holding only this option -> its text (works with empty <label>s and unnamed checkboxes)
    const sel = e.name ? 'input[type=' + e.type + '][name="' + CSS.escape(e.name) + '"]' : 'input[type=radio], input[type=checkbox]';
    let c = e.parentElement, best = '';
    while (c && c.querySelectorAll(sel).length === 1) { if (t(c)) best = t(c); c = c.parentElement; }
    return best || e.value;
  };
  const groupQ = e => {
    const fs = e.closest('fieldset'); if (fs && t(fs.querySelector('legend'))) return t(fs.querySelector('legend'));
    const sel = 'input[type=' + e.type + '][name="' + CSS.escape(e.name) + '"]';
    const al = [...document.querySelectorAll(sel)].map(x => x.getAttribute('aria-label') || '');
    if (al.length > 1 && al[0] && al.every(x => x === al[0])) return al[0];
    const rg = e.closest('[role=radiogroup], [role=group]'); if (rg && rg.getAttribute('aria-label')) return rg.getAttribute('aria-label');
    return '';
  };
  const out = []; let n = 0;
  const els = root.querySelectorAll('input:not([type=hidden]), select, textarea, button, a[href], [role=button], [role=combobox], [role=option], [role=radio], [role=checkbox]');
  for (const e of els) {
    const shown = vis(e) || (e.labels && [...e.labels].some(vis)) || (['radio', 'checkbox', 'file'].includes(e.type) && vis(e.parentElement));
    if (!shown || e.closest('[data-agent-skip]')) continue;
    if (!dlg.length) {   // whole page: only form controls and apply / navigation-of-the-form buttons, never feed, nav, header, footer
      if (e.closest('header, nav, footer, aside, [role=navigation], [role=search], [role=banner], [role=contentinfo]')) continue;
      const isCtl = ['INPUT', 'SELECT', 'TEXTAREA'].includes(e.tagName) || ['combobox', 'radio', 'checkbox', 'option'].includes(e.getAttribute('role'));
      const words = t(e) + ' ' + (e.getAttribute('aria-label') || '');
      if (!isCtl && !e.closest('form') && !/apply|postuler|candidat|submit|envoyer|soumettre|next|suivant|continu|upload|importer|t.l.charger|accept|ignorer|fermer|close|dismiss|ajouter|add |modifier|edit|enregistrer|save|supprimer|delete|retirer|connect|connexion|sign in|log ?in|anmelden|créer|create|valider|confirm|terminer|finish|review|vérifier/i.test(words)) continue;
      if (isCtl && !e.closest('form') && e.type === 'checkbox' && !t(e.closest('label'))) continue;
    }
    n++; e.setAttribute('data-agent-id', n);
    const req = e.required || e.getAttribute('aria-required') === 'true';
    let d = { n, tag: e.tagName.toLowerCase(), type: e.type || e.getAttribute('role') || '', req };
    if (e.tagName === 'SELECT') { d.label = label(e); d.value = (e.options[e.selectedIndex] || {}).text || ''; d.options = [...e.options].map(o => o.text.trim()).slice(0, 40); }
    else if (e.type === 'radio' || e.type === 'checkbox') { d.label = e.type === 'radio' ? groupQ(e) : ''; d.option = optText(e); d.checked = e.checked; d.name = e.name; }
    else if (e.type === 'file') { d.label = label(e); d.value = e.files && e.files.length ? e.files[0].name : ''; }
    else if (['INPUT', 'TEXTAREA'].includes(e.tagName)) { d.label = label(e); d.value = e.type === 'password' ? (e.value ? '•'.repeat(8) + ' (hidden)' : '') : e.value; d.placeholder = e.placeholder || ''; if (e.maxLength > 0) d.maxlength = e.maxLength; }
    else { d.label = t(e).slice(0, 80) || e.getAttribute('aria-label') || ''; d.aria = e.getAttribute('aria-label') || ''; }
    out.push(d);
  }
  return { scope: dlg.length ? 'dialog' : 'page', title: document.title, url: location.href, heading: t(root.querySelector('h1, h2, h3')).slice(0, 120), items: out };
}"""


def _state():
    return json.loads(TAB.read_text()) if TAB.exists() else {}


def _page(ctx, create=True):
    tid = _state().get("target")
    for p in ctx.pages:
        try:
            if tid and ctx.new_cdp_session(p).send("Target.getTargetInfo")["targetInfo"]["targetId"] == tid:
                return p
        except Exception:
            continue
    if not create:
        raise SystemExit("No agent tab open. Use: python agent.py open <url>")
    p = ctx.new_page()
    _own(ctx, p)
    return p


def _tid(ctx, p):
    return ctx.new_cdp_session(p).send("Target.getTargetInfo")["targetInfo"]["targetId"]


def _own(ctx, p):
    """Make p Claude's current tab and remember it (so old tabs can be closed later)."""
    tid = _tid(ctx, p)
    st = _state()
    TAB.write_text(json.dumps({**st, "target": tid, "owned": list(dict.fromkeys((st.get("owned") or []) + [tid]))}))


def _cleanup(ctx, keep):
    """Close every tab Claude opened before, except the current one: too many tabs make Chrome's debug port hang."""
    owned, kept = set(_state().get("owned") or []), []
    for p in list(ctx.pages):
        try:
            tid = _tid(ctx, p)
        except Exception:
            continue
        if tid in owned and p is not keep:
            try:
                p.close()
            except Exception:
                kept.append(tid)
        elif p is keep:
            kept.append(tid)
    TAB.write_text(json.dumps({**_state(), "owned": kept}))


def _frames(page):
    """Main frame plus any iframe that holds a form (Greenhouse, Workable... embed the application)."""
    fr = [page.main_frame]
    for f in page.frames[1:]:
        try:
            if "linkedin.com/preload" in f.url:
                continue
            box = f.frame_element().bounding_box()
            big = box and box["width"] > 400 and box["height"] > 300   # an embedded job page / form, not a tracker or widget
            if big or f.locator("form input:not([type=hidden]), textarea, input[type=file]").count() >= 2:
                fr.append(f)
        except Exception:
            pass
    return fr


def _el(page, ref):
    """Element by number from the last `look` ('12', or 'f1:12' inside the first form iframe)."""
    fi, n = (ref.split(":") + [None])[:2] if ":" in ref else ("f0", ref)
    frame = _frames(page)[int(fi[1:])]
    loc = frame.locator(f'[data-agent-id="{n}"]')
    if not loc.count():
        raise SystemExit(f"element {ref} not found - run `look` again (the form changed)")
    return loc.first


def look(page):
    page.bring_to_front()
    page.wait_for_timeout(800)
    shot = STATE / "screen.png"
    page.screenshot(path=str(shot))
    for i, f in enumerate(_frames(page)):
        try:
            m = f.evaluate(MAP_JS)
        except Exception as e:
            print(f"(frame {i} unreadable: {e!r})"[:120]); continue
        pre = "" if i == 0 else f"f{i}:"
        print(f"== frame f{i} | {m['scope']} | {m['title'][:70]} | {m['url'][:90]}\n   heading: {m['heading']}")
        for d in m["items"]:
            req = "*" if d.get("req") else " "
            if d["tag"] == "select":
                print(f" [{pre}{d['n']}]{req}select   {d['label'][:90]!r} = {d['value']!r}  options={d['options']}")
            elif d["type"] in ("radio", "checkbox"):
                print(f" [{pre}{d['n']}]{req}{d['type']:8s} {d['label'][:70]!r} option={(d.get('option') or '')[:60]!r} {'[x]' if d.get('checked') else '[ ]'}")
            elif d["tag"] in ("input", "textarea"):
                extra = f" placeholder={d['placeholder']!r}" if d.get("placeholder") else ""
                extra += f" maxlength={d['maxlength']}" if d.get("maxlength") else ""
                print(f" [{pre}{d['n']}]{req}{d['type'] or d['tag']:8s} {d['label'][:90]!r} = {str(d.get('value', ''))[:80]!r}{extra}")
            else:
                print(f" [{pre}{d['n']}] {d['tag']:8s} {d['label'][:70]!r}" + (f" aria={d['aria'][:60]!r}" if d.get("aria") and d["aria"] != d["label"] else ""))
    print(f"\nscreenshot: {shot}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__); return
    cmd, args = sys.argv[1], sys.argv[2:]

    if cmd == "queue":
        for r in store.rows(["selected"]):
            print(f"{r['url']}  | {r['title'][:60]} @ {r['company']} | {r.get('country') or 'remote'} | fit {r.get('score') or 0:.2f} | resume={r['resume']}")
        return
    if cmd == "prep":
        r = next((x for x in store.rows() if x["url"] == args[0]), None)
        if not r:
            raise SystemExit("unknown offer")
        print(json.dumps({k: r[k] for k in ("title", "company", "country", "status", "reason", "score", "resume", "projects", "cover_pdf")},
                         ensure_ascii=False, indent=1))
        print("resume file:", RESUMES.get(r["resume"] or "devops", {}).get("file"))
        print("\nCOVER LETTER TEXT:\n" + (r.get("cover") or "(none)"))
        return
    if cmd == "record":
        url, status, note = args[0], args[1], " ".join(args[2:])
        r = next((x for x in store.rows() if x["url"] == url), {})
        store.record(url, r.get("site", "linkedin"), r.get("title", ""), r.get("company", ""), status, note, r.get("resume", ""),
                     r.get("projects", ""), r.get("score") or 0, r.get("country", ""), json.loads(r.get("answers") or "[]"),
                     r.get("cover", ""), r.get("cover_pdf", ""))
        print("recorded", status)
        return

    pw, ctx = launch()
    try:
        if cmd == "cover":   # (re)write the tailored letter for an offer from its current page
            from src import matcher, llm_cover
            from src.sites import linkedin, generic
            from src.sites.base import Job
            r = next((x for x in store.rows() if x["url"] == args[0]), None) or {}
            job = Job(r.get("site", "linkedin"), args[0], "", "")
            (linkedin if job.site == "linkedin" else generic).hydrate(ctx, job)
            best = matcher.rank_projects(job.text)
            text = llm_cover.cover_text(job.title, job.company, job.text, best)
            pdf = llm_cover.cover_pdf(text, job.title, job.company, job.text) if text else ""
            store.record(args[0], job.site, job.title or r.get("title", ""), job.company or r.get("company", ""), r.get("status", "selected"),
                         r.get("reason", ""), r.get("resume", "devops"), ";".join(p["name"] for _, p in best), r.get("score") or 0,
                         r.get("country", ""), json.loads(r.get("answers") or "[]"), text, pdf)
            print("COVER LETTER:\n" + (text or "(generation failed - none saved)") + f"\n\nPDF: {pdf}")
            return
        page = _page(ctx, create=(cmd == "open"))
        if cmd == "open":
            TAB.write_text(json.dumps({**_state(), "offer": args[0]}))   # the offer being applied to (for `upload resume|cover`)
            _cleanup(ctx, page)
            page.bring_to_front()
            page.goto(args[0], wait_until="domcontentloaded")
            page.wait_for_timeout(3500)
            look(page)
        elif cmd == "look":
            look(page)
        elif cmd == "text":
            m = page.locator("dialog[open], [role=dialog]").last
            print((m.inner_text() if m.count() and m.is_visible() else page.locator("body").inner_text())[:6000])
        elif cmd == "fill":
            e = _el(page, args[0]); e.fill(" ".join(args[1:])); print("value now:", repr(e.input_value()))
        elif cmd == "select":
            e = _el(page, args[0]); e.select_option(label=" ".join(args[1:]))
            print("selected:", e.evaluate("e => e.options[e.selectedIndex].text"))
        elif cmd == "check":
            e = _el(page, args[0])
            state = None
            for how in (lambda: e.check(timeout=3000), lambda: e.evaluate("e => e.click()")):
                try:
                    how()
                except Exception:
                    pass
                try:
                    state = e.is_checked(timeout=2000)
                except Exception:
                    state = "form redrew - run `look` to verify"
                    break
                if state:
                    break
            print("checked:", state)
        elif cmd == "click":
            popups = []
            page.on("popup", lambda p: popups.append(p))   # only tabs opened BY this tab (other scripts may open tabs too)
            _el(page, args[0]).click(timeout=8000)
            page.wait_for_timeout(3500)
            new = [p for p in popups if p.url != "about:blank" or p.wait_for_load_state("domcontentloaded") is None]
            if new:   # the click opened a new tab (company career site): Claude's tab follows it
                np_ = new[-1]
                np_.wait_for_load_state("domcontentloaded")
                _own(ctx, np_)
                print("clicked -> new tab followed:", np_.url[:120])
            else:
                print("clicked")
        elif cmd == "pick":
            e = _el(page, args[0]); e.click(); e.fill(""); e.type(" ".join(args[1:]), delay=70); page.wait_for_timeout(1800)   # real keystrokes: React dropdowns ignore pasted text
            fi = args[0].split(":")[0] if ":" in args[0] else "f0"
            opts = _frames(page)[int(fi[1:])].locator("[role=option]:visible").all()[:12]   # suggestions live in the field's frame
            texts = [o.inner_text().strip() for o in opts]
            print("suggestions:", texts)
            if opts:
                opts[0].click(); page.wait_for_timeout(600); print("picked:", texts[0], "| value now:", repr(e.input_value()))
        elif cmd == "upload":
            e, what = _el(page, args[0]), " ".join(args[1:])
            if what in ("resume", "cover"):
                offer = _state().get("offer", "")
                r = next((x for x in store.rows() if x["url"] == offer), None) or {}
                path = (ROOT / RESUMES[r.get("resume") or "devops"]["file"]) if what == "resume" else Path(r.get("cover_pdf") or "")
            else:
                path = Path(what)
            if not path or not Path(path).is_file():
                raise SystemExit(f"file not found: {path}")
            if e.evaluate("e => e.tagName === 'INPUT' && e.type === 'file'"):
                e.set_input_files(str(path))
            else:   # an 'Upload' button that opens the OS file picker
                with page.expect_file_chooser(timeout=10000) as fc:
                    e.click()
                fc.value.set_files(str(path))
            page.wait_for_timeout(3000); print("uploaded:", Path(path).name)
        elif cmd == "secret":   # secret <n> <ENV_VAR>: type a value read from an environment variable, never printed or stored
            import os
            v = os.environ.get(args[1], "")
            if not v:
                raise SystemExit(f"environment variable {args[1]} is empty")
            e = _el(page, args[0]); e.fill(v)
            print("filled", args[0], "with", len(v), "characters (not shown)")
        elif cmd == "show":   # scroll field n into view, screenshot, and print the text of the block around it
            e = _el(page, args[0])
            e.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(600)
            page.screenshot(path=str(STATE / "screen.png"))
            ctx_txt = e.evaluate("e => { let c = e; for (let i = 0; i < 6 && c.parentElement; i++) { c = c.parentElement;"
                                 " const t = (c.innerText || '').trim(); if (t.length > 25) return t; } return ''; }")
            print(" | ".join(l.strip() for l in ctx_txt.splitlines() if l.strip())[:400])
            print("screenshot:", STATE / "screen.png")
        elif cmd == "press":
            page.keyboard.press(args[0]); page.wait_for_timeout(800); print("pressed", args[0])
        elif cmd == "scroll":
            page.mouse.wheel(0, -700 if args and args[0] == "up" else 700); page.wait_for_timeout(600); print("scrolled")
        else:
            print(__doc__)
    finally:
        shutdown(pw)


if __name__ == "__main__":
    main()
