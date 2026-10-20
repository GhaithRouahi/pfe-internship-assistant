"""Find DevOps/Cloud PFE offers, apply with the right resume, and send everything uncertain to the review list.

  python main.py                  dry run (fills forms, never submits)
  python main.py --live           real applications
  python main.py --retry-review   re-try offers from the review list (after you added answers to profile.yaml)
  python report.py                open the review report (data/review.html)
"""
import argparse, re
from src.config import CFG
from src import store, matcher, llm_cover, answers, report
from src.browser import launch, pause, shutdown
from src.sites import linkedin, generic


def build_searches():
    out = []
    for c in CFG["countries"]:
        for k in CFG["keywords"] + CFG.get("local_keywords", {}).get(c, []):
            out.append({"keywords": k, "location": c})
    return out


def process(ctx, job, site, country, dry):
    """Returns the final status recorded for this job."""
    def rec(status, reason="", **kw):
        store.record(job.url, site, job.title, job.company, status, reason, country=country, **kw)
        return status

    if job.title and not matcher.title_could_fit(job.title):
        return rec("skipped", "low match (title)")   # decided from the search card, page not opened
    pause("page")
    if site == "linkedin":
        linkedin.hydrate(ctx, job)
    else:
        generic.hydrate(ctx, job)
    if not job.title:
        return rec("error", "could not read the offer page")
    if store.seen_posting(job.title, job.company, dry):
        return rec("skipped", "duplicate posting (same company + title already handled)")
    ok, why = matcher.is_internship(job.title, job.meta, job.text)
    if not ok:
        return rec("skipped", why)
    if country.lower() != "tunisia" and any(re.search(b, job.text, re.I) for b in CFG["visa_blockers"]):
        return rec("skipped", "offer excludes candidates needing a visa")
    blocker = next((b for b in CFG.get("requirement_blockers", []) if re.search(b, job.text, re.I)), None)
    if blocker:
        return rec("skipped", "offer requires something you don't have: " + re.search(blocker, job.text, re.I).group(0)[:60])
    score = matcher.fit_score(job.title, job.text)
    if score < CFG["min_match_score"]:
        return rec("skipped", f"low match {score:.2f}", score=score)
    fit = matcher.llm_fit(job.title, job.company, job.text)
    if fit is not None and fit < CFG["llm_fit_min"]:
        return rec("skipped", f"AI fit {fit}/100", score=score)

    best = matcher.rank_projects(job.text)
    resume = matcher.pick_resume(job.title, job.text, best)
    answers.set_context(country, site, job.title, job.company, job.text, store.applied_to_company(job.company))
    cover = llm_cover.cover_text(job.title, job.company, job.text, best)
    cover_pdf = llm_cover.cover_pdf(cover, job.title, job.company, job.text) if cover else ""
    if CFG.get("apply_mode", "claude") == "claude":   # Claude fills the form itself (agent.py), nothing automated here
        rec("selected", "ready - Claude applies", resume=resume, projects=";".join(p["name"] for _, p in best), score=score,
            cover=cover, cover_pdf=cover_pdf)
        print(f"[selected] {job.title} @ {job.company} ({site}, {country or 'remote'}) resume={resume} fit={score:.2f}"
              f"{'' if fit is None else f'/{fit}'}")
        return "selected"
    mod = linkedin if site == "linkedin" else generic
    out = mod.apply(ctx, job, resume, cover, cover_pdf)
    rec(out.status, out.reason, resume=resume, projects=";".join(p["name"] for _, p in best), score=score,
        answers=[list(x) for x in out.log], cover=cover, cover_pdf=cover_pdf)
    unc = f" | {len(out.uncertain)} AI-judged answer(s)" if out.uncertain else ""
    print(f"[{out.status}] {job.title} @ {job.company} ({site}, {country or 'remote'}) resume={resume} fit={score:.2f}"
          f"{'' if fit is None else f'/{fit}'} {out.reason}{unc}")
    return out.status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="really submit applications (otherwise dry run)")
    ap.add_argument("--retry-review", action="store_true", help="re-process offers currently in the review list")
    ap.add_argument("--sites", help="comma list overriding config sites, e.g. wttj or linkedin,wttj")
    a = ap.parse_args()
    if a.live:
        CFG["dry_run"] = False
    dry = CFG["dry_run"]
    if a.sites:
        CFG["sites"] = [x.strip() for x in a.sites.split(",") if x.strip()]
    if a.retry_review:
        store.reset(["needs_review"])
    print(f"Mode: {'DRY RUN (nothing is submitted)' if dry else 'LIVE (applications are submitted)'}")

    pw, ctx = launch()
    try:
        if "linkedin" in CFG["sites"] and not linkedin.logged_in(ctx):
            raise SystemExit("LinkedIn is not logged in inside the bot's Chrome. Log in there (start_chrome.bat) and re-run.")
        n, blocked, done_queries = 0, set(), set()
        for s in build_searches():
            if n >= CFG["max_applications_per_run"]:
                break
            country = "" if s["location"].lower() == "remote" else s["location"]
            for site in CFG["sites"]:
                if n >= CFG["max_applications_per_run"] or site in blocked:
                    continue
                if site in ("wttj", "generic"):   # these searches ignore the country: run each keyword once
                    key = (site, "")   # WTTJ matches / urls.txt do not depend on the keyword
                    if key in done_queries:
                        continue
                    done_queries.add(key)
                try:
                    jobs = linkedin.search(ctx, s["keywords"], s["location"]) if site == "linkedin" else \
                        generic.search(ctx, site, s["keywords"], s["location"])
                except generic.Blocked:
                    print(f"!! {site} shows a bot check - skipping it for this run (nothing recorded)")
                    blocked.add(site)
                    continue
                except Exception as e:
                    print(f"!! search failed on {site} '{s['keywords']}' {s['location']}: {e!r}"[:200])
                    continue
                for job in jobs:
                    if n >= CFG["max_applications_per_run"]:
                        break
                    if store.seen(job.url, dry):
                        continue
                    try:
                        status = process(ctx, job, site, country, dry)
                    except generic.Blocked:
                        print(f"!! {site} shows a bot check - skipping it for this run (nothing recorded)")
                        blocked.add(site)
                        break
                    except Exception as e:
                        store.record(job.url, site, job.title, job.company, "error", repr(e)[:300], country=country)
                        print(f"[error] {job.title or job.url}: {e!r}"[:250])
                        continue
                    if status in ("applied", "dry_run", "unconfirmed", "selected"):
                        n += 1
                    if status not in ("skipped",):
                        pause("job")
    finally:
        shutdown(pw)
        path = report.write()
        print(f"\nReview report: {path}")


if __name__ == "__main__":
    main()
