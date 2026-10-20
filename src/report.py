"""data/review.html: what was sent, what needs you (with everything prepared), what to double-check."""
import html, json
from collections import Counter
from .config import ROOT, RESUMES
from . import store

OUT = ROOT / "data" / "review.html"
SECTIONS = [
    ("selected", "Selected - Claude is applying", "Good matches selected and prepared; Claude fills these forms itself."),
    ("needs_review", "Needs you", "Good matches the bot could not finish with certainty. Everything is prepared: open the link, use the resume and letter below."),
    ("unconfirmed", "Check these", "Submit was clicked but no confirmation appeared. Check the site (or your email) before re-applying."),
    ("applied", "Applied", "Submitted and confirmed by the site."),
    ("dry_run", "Dry run - ready to submit", "Fully filled; would be submitted in live mode."),
    ("error", "Errors (retried automatically)", "Technical failures; the next run retries them up to 3 times."),
]
SRC = {"profile": "from your profile", "rule": "rule", "llm_text": "AI-written", "llm_choice": "AI-judged - please verify"}


def _e(s):
    return html.escape(str(s or ""))


def write() -> str:
    rows = store.rows()
    counts = Counter(r["status"] for r in rows)
    parts = ["<!doctype html><meta charset=utf-8><title>Applications review</title><style>",
             "body{font:14px/1.45 system-ui,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#1d1d1f;background:#fff}",
             "h2{margin-top:32px;border-bottom:2px solid #ddd}.card{border:1px solid #ddd;border-radius:8px;padding:12px 14px;margin:12px 0}",
             ".why{color:#a33}.muted{color:#666}table{border-collapse:collapse;width:100%;margin-top:6px}td{border-top:1px solid #eee;padding:4px 6px;vertical-align:top}",
             ".unc td{background:#fff4e5}details{margin-top:6px}pre{white-space:pre-wrap;background:#f6f6f6;padding:8px;border-radius:6px}",
             "</style><h1>Applications review</h1><p class=muted>" + " · ".join(f"{k}: {v}" for k, v in counts.most_common()) + "</p>"]
    for status, title, help_ in SECTIONS:
        items = [r for r in rows if r["status"] == status]
        if not items:
            continue
        parts.append(f"<h2>{_e(title)} ({len(items)})</h2><p class=muted>{_e(help_)}</p>")
        for r in items:
            resume = RESUMES.get(r.get("resume") or "", {}).get("file", "")
            parts.append(f"<div class=card><b><a href='{_e(r['url'])}' target=_blank>{_e(r['title'])}</a></b> · {_e(r['company'])} "
                         f"<span class=muted>({_e(r['site'])}, {_e(r.get('country') or 'remote')}, fit {r.get('score') or 0:.2f})</span>")
            if r.get("reason"):
                parts.append(f"<div class=why>{_e(r['reason'])}</div>")
            if resume:
                parts.append(f"<div>Resume: <code>{_e(resume)}</code></div>")
            if r.get("cover_pdf"):
                parts.append(f"<div>Cover letter PDF: <code>{_e(r['cover_pdf'])}</code></div>")
            ans = json.loads(r.get("answers") or "[]")
            if ans:
                trs = "".join(f"<tr class={'unc' if s == 'llm_choice' else ''}><td>{_e(q)}</td><td>{_e(a)}</td><td class=muted>{_e(SRC.get(s, s))}</td></tr>"
                              for q, a, s in ans)
                parts.append(f"<details><summary>Answers filled ({len(ans)})</summary><table>{trs}</table></details>")
            if r.get("cover"):
                parts.append(f"<details><summary>Motivation text</summary><pre>{_e(r['cover'])}</pre></details>")
            parts.append("</div>")
    skipped = [r for r in rows if r["status"] == "skipped"]
    if skipped:
        parts.append(f"<h2>Skipped ({len(skipped)})</h2><table>" + "".join(
            f"<tr><td><a href='{_e(r['url'])}' target=_blank>{_e(r['title'] or r['url'])}</a></td><td>{_e(r['company'])}</td><td class=muted>{_e(r['reason'])}</td></tr>"
            for r in skipped[:300]) + "</table>")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(parts), encoding="utf-8")
    return str(OUT)
