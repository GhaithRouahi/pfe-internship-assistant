"""Welcome to the Jungle / Indeed / urls.txt: collect job links, read the offer, hand off to the external engine."""
import re
from urllib.parse import quote
from .base import Job
from . import external
from ..config import ROOT
from ..flow import Outcome, visible_challenge

SEARCH = {
    "indeed": ("https://fr.indeed.com/jobs?q={kw}&l={loc}&sort=date", r"/(rc/clk|viewjob|pagead/clk)\?", "https://fr.indeed.com"),
    "wttj": ("https://www.welcometothejungle.com/fr/jobs?query={kw}&refinementList%5Bcontract_type%5D%5B%5D=internship",
             r"^/fr/companies/[^/]+/jobs/[^/?#]+", "https://www.welcometothejungle.com"),
}


class Blocked(Exception):
    """The site shows a bot check: stop using it for this run instead of recording wrong data."""


def search(ctx, site, kw, loc):
    if site == "generic":
        f = ROOT / "urls.txt"
        return [Job(site, u.strip(), "", "") for u in f.read_text(encoding="utf-8").splitlines() if u.strip()
                and not u.startswith("#")] if f.exists() else []
    if site == "wttj":
        return _wttj_matches(ctx)
    tmpl, pat, base = SEARCH[site]
    page = ctx.new_page()
    try:
        page.bring_to_front()
        page.goto(tmpl.format(kw=quote(kw), loc=quote(loc)), wait_until="domcontentloaded")
        page.wait_for_timeout(4500)
        if visible_challenge(page):
            raise Blocked(site)
        links = []
        for h in page.locator("a[href]").evaluate_all("els => els.map(a => a.getAttribute('href'))"):
            path = h.replace(base, "") if h else ""
            if path and re.search(pat, path) and path not in links:
                links.append(path)
        return [Job(site, base + l, "", "") for l in links[:20]]
    finally:
        page.close()


def _wttj_matches(ctx, limit=120):
    """WTTJ (2026) no longer lists search results: offers come from the account's 'jobs-matches' page, driven by the
    search preferences saved on the account (role, countries, contract = Stage)."""
    base = "https://www.welcometothejungle.com"
    page = ctx.new_page()
    try:
        page.bring_to_front()
        page.goto(base + "/fr/jobs-matches", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        if visible_challenge(page):
            raise Blocked("wttj")
        for b in page.get_by_role("button", name=re.compile(r"^(Fermer|Dismiss popup)$")).all():
            try:
                if b.is_visible():
                    b.click(); page.wait_for_timeout(800)
            except Exception:
                pass
        links = []
        for _ in range(15):   # numbered pages of 10 matches, "Next Page" button
            hrefs = page.locator("a[href]").evaluate_all("els => els.map(a => a.getAttribute('href'))")
            before = len(links)
            for h in (x.split("?")[0] for x in hrefs if x and re.search(r"/companies/[^/]+/jobs/[^/?#]+", x)):
                if h not in links:
                    links.append(h)
            nxt = page.get_by_role("button", name="Next Page")
            if len(links) >= limit or len(links) == before or not nxt.count() or not nxt.first.is_enabled():
                break
            nxt.first.scroll_into_view_if_needed(); nxt.first.click(); page.wait_for_timeout(3500)
        return [Job("wttj", (h if h.startswith("http") else base + h), "", "") for h in links[:limit]]
    finally:
        page.close()


def hydrate(ctx, job: Job):
    page = ctx.new_page()
    try:
        page.bring_to_front()
        page.goto(job.url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        if visible_challenge(page):
            raise Blocked(job.site)
        job.title = (page.locator("h1").first.inner_text().strip() if page.locator("h1").count() else "") or page.title()
        job.text = page.locator("main").first.inner_text()[:8000] if page.locator("main").count() else page.locator("body").inner_text()[:8000]
        job.meta = job.text[:1500]
        m = re.search(r"/companies/([^/]+)/jobs/", page.url)
        og = page.locator("meta[property='og:site_name']").first.get_attribute("content") if page.locator("meta[property='og:site_name']").count() else ""
        if m:
            job.company = m.group(1).replace("-", " ").title()
        elif job.site == "indeed":
            c = page.locator("[data-testid=inlineHeader-companyName], [data-company-name]").first
            job.company = c.inner_text().strip() if c.count() else ""
        else:
            job.company = og or page.url.split("/")[2].replace("www.", "").replace("careers.", "").replace("jobs.", "")
    finally:
        page.close()


def apply(ctx, job: Job, resume_key: str, cover: str, cover_pdf: str) -> Outcome:
    return external.apply(ctx, job, resume_key, cover, cover_pdf)
