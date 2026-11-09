# How this repo works: the PFE application machine

This file explains everything this repo does to find a 6-month **PFE (end-of-studies internship) starting February 2027** in DevOps / Cloud / SRE / DevSecOps / MLOps: the bots, the scripts, the mail campaign, the data, and the house rules.
It is written for the owner and for any agent (Claude) picking up the work in a new session.

Personal facts (contact details, school, dates, languages, eligibility) are **not** written here. They live in `profile.yaml`, `projects.yaml` and `resumes.yaml`, which are git-ignored. Passwords are never stored anywhere in the repo.

---

## 1. The big picture

There are three ways applications go out, and they all record into the same database:

```
              discovery (scanners)                          applying                          tracking
 LinkedIn / WTTJ / Workday / ATS feeds  ──►  main.py selects + prepares  ──►  Claude fills forms with agent.py ──┐
 Hellowork / Eightfold / SmartRecruiters                                       (portal-specific helper scripts) ├─► data/applications.db
 LinkedIn "companies hiring DevOps"     ──►  outreach sheet (.xlsx)      ──►  send_batch.py → Gmail             │   + outreach .xlsx
 Gmail inbox (replies, rejections,      ──►  read by Claude ───────────────────────────────────────────────────┘
 screening invitations)
```

1. **Portal applications.** Offers are found on job sites and company career portals. `main.py` scores them and prepares a resume and cover letter. Claude then fills each form itself, step by step, in the bot Chrome (`agent.py`).
2. **Spontaneous email campaign.** Companies that currently advertise DevOps/Cloud jobs (any level) are collected, the emails they publish on their own website are found, and a short application email with the resume is sent from Gmail in batches.
3. **Inbox follow-up.** Claude reads Gmail (in the same bot Chrome) for acknowledgements, rejections, screening questionnaires and interview requests, and updates the database and the sheet.

---

## 2. The bot Chrome (everything runs through it)

All browser work happens in **one dedicated Chrome**, driven over the DevTools protocol (CDP). No headless browser is used, so logins persist and sites see a normal browser.

- Start it with `start_chrome.bat`, or:
  ```powershell
  Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222','--remote-debugging-address=127.0.0.1','"--user-data-dir=D:\RT5\Postulation pfe\data\chrome_profile"'
  ```
- Profile: `data/chrome_profile`. It holds the logins to LinkedIn, Gmail, WTTJ, Workday tenants and so on. Log in once by hand and the session is kept.
- Scripts connect with Playwright: `p.chromium.connect_over_cdp("http://127.0.0.1:9222")`.

**Pitfalls:**
- **Never close all tabs.** Chrome exits and every script fails.
- If CDP freezes (LinkedIn anti-bot iframes, heavy Gmail or Workday tabs), close only the heavy tabs via `http://127.0.0.1:9222/json/close/<id>`.
- To restart Chrome cleanly, kill only the `chrome.exe` processes whose command line contains this profile path, not the user's own Chrome.
- Don't close tabs that a running LinkedIn sweep opened.

---

## 3. Portal applications

### 3.1 Discovery and selection: `main.py`

```
python main.py                  # dry run: search, score, prepare (never submits)
python main.py --live           # real mode
python main.py --retry-review   # re-try the review list after adding answers to profile.yaml
python report.py                # data/review.html: what was sent / what needs you
```

The pipeline:
- Every keyword × country in `config.yaml` (`keywords`, `local_keywords`, `countries`, `sites`) is searched.
- Offers pass through the filters in `src/matcher.py`:
  - internship words
  - title exclusions (alternance, working student…)
  - seniority words
  - role keywords
  - the heuristic `min_match_score`, then an LLM second opinion `llm_fit_min`
  - `visa_blockers` (no sponsorship / EU-only), which skip the offer
  - `requirement_blockers` (fluent German/Dutch…), which skip the offer
  - `visa_friendly` mentions, which raise the score
- A resume is picked (`pick_resume`) and a tailored cover letter is written (`src/llm_cover.py`, which uses only facts from profile and projects). The PDF goes to `data/covers/`.
- `apply_mode: claude` (the current setting) means `main.py` **only selects and prepares**. Claude fills the forms. `apply_mode: auto` is the old scripted engine (`src/flow.py`, `src/form.py`), kept as a fallback.

Site adapters live in `src/sites/`: `linkedin.py` (Easy Apply), `generic.py` (WTTJ / Indeed / urls.txt) and `external.py` (company ATS: Greenhouse, Lever, Workable, SmartRecruiters, Teamtailor, Recruitee, Ashby…).

### 3.2 Filling forms: `agent.py` (look → think → act)

Claude works one command at a time in its own tab of the bot Chrome:

| Command | What it does |
|---|---|
| `queue` / `prep <url>` | offers waiting, and their prepared resume / letter / fit |
| `open <url>` | open a page in Claude's tab |
| `look` | numbered list of fields and buttons, plus a screenshot `data/agent/screen.png` |
| `text` | visible page text |
| `fill <n> <text>`, `select <n> <opt>`, `check <n>`, `click <n>`, `pick <n> <text>` | act on element n |
| `upload <n> resume\|cover\|<path>` | attach a file |
| `press <Key>`, `scroll up\|down` | keyboard and scroll |
| `secret <n> <ENV_VAR>` | type a password taken from an environment variable (never printed) |
| `record <url> <status> <note>` | write the outcome to the DB |

The rule: **look, think, fill**. Nothing is scripted blindly. Claude submits only when every answer is a true fact; otherwise it asks the user.

### 3.3 Portal-specific helpers (`data/agent/`)

Some big portals have repeatable flows, so they have scripts. All of them print what they did, and most only submit with `--submit`. Unknown questions are printed and **not** submitted.

| Portal | Scripts | Notes |
|---|---|---|
| **Thales** (Phenom guest form) | `thales_flow.sh <R-number> <cv.pdf> [--submit]`, `thales_apply.py`, `thales_finish.sh` | CV file names must be **short** (long names are silently ignored). Some offers add a "Questions relatives à l'application" step, which is filled by hand. New Workday postings take about a day to appear on careers.thalesgroup.com. |
| **Thales screenings** | `thales_screen.py <link> [--submit]` | Each Thales application triggers an emailed 8-question screening with a 3–5 day deadline. Links come from the Gmail invitations (`from:recruiting@jobalerts.thalesgroup.com invité`). |
| **Workday** (Renault, Intel, Naval Group, BPCE…) | `intel_apply.py`, `wd_scan.py` | Custom dropdowns are `button[aria-haspopup=listbox]`, then `[role=option]`. Drafts resume via "Continuer la candidature". |
| **SuccessFactors** (Capgemini, Ericsson) | `cap_apply.sh`, `ericsson_sf.py`, `sf_combo.py`, `sf_cover.py` | Combo boxes need the arrow button. |
| **SmartRecruiters** | `sr_scan.py`, `sr_apply.py` | page 1 only, never submits |
| **Crédit Agricole** | `ca_apply.py` | 5-step wizard |
| **Viveris / Siemens** | `viveris_apply.py`, `siemens_apply.py` | invisible reCAPTCHA: if a challenge shows, the user solves it |

### 3.4 Discovery scanners (no applying)

These need no browser except `ef_*`:
- `li_guest.py`, `li_search.py`, `li_countries.py`: LinkedIn guest search
- `wttj_search.py`: Welcome to the Jungle
- `wd_scan.py`: Workday CXS across many tenants
- `ats_scan.py`, `fr_scan.py`: Greenhouse / Lever / Ashby / Workable / SmartRecruiters / Recruitee feeds
- `ef_scan.py`, `ef_detail.py`: Eightfold, fetched inside Chrome
- `hw_scan.py`: Hellowork, discovery only
- `ie_nl.py`: Ireland and the Netherlands

Each writes a `*_hits.json` of offers not already in the DB.

---

## 4. Spontaneous email campaign (`data/outreach/`)

The goal is to email companies that **are hiring DevOps/Cloud right now** (any level), offering a 6-month PFE, even when they have posted no internship.

| Step | Script | Output |
|---|---|---|
| 1. Collect hiring companies (LinkedIn public search, recent DevOps/Cloud/SRE jobs) | `collect_devops_companies.py` | `devops_companies_raw.json` (snapshot of batch 1: `devops_companies_raw_3010.json`) |
| 2. Find each company's website (LinkedIn company page; Clearbit fallback, shown in red) and the emails it publishes on its own domain (home / contact / careers / legal pages) | `find_company_emails.py` | `devops_companies_emails.json` |
| 3. Build the tracking sheet | `build_sheet.py` | `Spontaneous_DevOps_Applications.xlsx` |
| 4. Send in batches | `send_batch.py FR:<#> EN:<#> …` | Gmail sends, sheet updated, DB rows |
| 5. Look for internships at the emailed companies | `find_company_internships.py` | `company_internships.json` |

**The sheet** (`Targets` tab):
- Columns: `#`, Company, Country, open roles, job link, website, contact email, email type (Recruiting / General / Personal), source, other emails, language.
- The columns the user edits are **L Status**, **M Date sent** and **N Notes**. Rebuilding the sheet keeps them.
- Status flow: `To review → Approved → Sent → Replied / Interview / Rejected`, or `Skip`.
- Extra tabs: `Summary` (COUNTIF formulas, reply rate), `How to use`, `Email template`.
- Rows for companies already applied to via a portal are flagged "Already applied via a portal – check before emailing".

**Sending** (`send_batch.py`):
- Uses the FR template for Tunisia / France / Belgium / Luxembourg / Switzerland and EN for the rest. The language can be overridden per row (`EN:<#>`); English is used for German-speaking Swiss and Flemish companies.
- Attaches `resumes/Resume_Ghaith_Rouahi_DevOps_AI.pdf`.
- Each mail goes through `data/agent/gmail_send.sh <to> <subject> <body.txt> <files…>`, which opens Gmail's compose URL, attaches, clicks *Envoyer* and checks "Message envoyé". It runs under Git Bash: `"C:/Program Files/Git/bin/bash.exe"`.
- The script waits **45 s between mails**, and batches are capped at **40–50 per run** so Gmail doesn't flag the account as spam.
- Each sent row becomes `Sent` plus the date in the sheet and a `mailto:<address>` row with status `applied` in the DB.
- After a batch, check that nothing is stuck in **Drafts** and that the count in **Sent** matches. "NOT CONFIRMED" sometimes means it was in fact sent.

**Choosing rows:**
- Prefer Recruiting addresses (jobs@, careers@, rh@), then General (contact@, info@).
- Skip addresses that cannot reach HR: press, DPO/privacy, trademark, impressum, complaints, customer service, investor relations.
- Skip a second company on a domain that was already emailed.

**Other outreach:**
- `data/agent/contacts.py` collects recruiter / engineering-lead / INSAT-alumni contacts. It is read-only.
- `outreach.py` sends LinkedIn invitations with a note, and `dm.py` sends recruiter messages with an InMail cap.
- Protocol: the user reviews 3 drafts before anything is sent.

---

## 5. Inbox follow-up

Claude reads Gmail in the bot Chrome with Playwright:
- Search URL: `https://mail.google.com/mail/u/0/#search/<query>`, opened with `wait_until="domcontentloaded"`.
- Rows are `div[role=main] tr.zA`. Open a thread by clicking `span.bog`. Message bodies are in `div.a3s`. Pressing `;` expands every message in a thread.
- Use `in:anywhere` for password resets (they sometimes land in Trash), and `newer_than:1d -from:me` for new mail.

For each mail, it is matched to a DB row (by company / `mailto:` address / job reference) and recorded:

| Mail | DB status | Sheet status |
|---|---|---|
| acknowledgement ("we received your application") | unchanged (`applied`) | note added |
| rejection / "no internships at the moment" | `rejected` | `Rejected` |
| "apply via our portal" / "send more info" | unchanged, note added | `Replied` |
| interview / call request | `interview` | `Interview` |
| screening questionnaire (Thales, …) | answer it before the deadline | n/a |
| "confirm your application" link (BPCE TalentLink) | click within 24 h or it is deleted | n/a |

---

## 6. Data

| Path | Content |
|---|---|
| `data/applications.db` | SQLite, table `applications`. Columns: `url` (PK), `site`, `title`, `company`, `status`, `reason`, `resume`, `projects`, `score`, `ts`, `country`, `answers`, `cover`, `cover_pdf`, `attempts` |
| `data/outreach/Spontaneous_DevOps_Applications.xlsx` | email campaign tracker |
| `data/covers/` | generated cover letters (txt + PDF) |
| `data/review.html` | review report (`python report.py`) |
| `data/agent/*_hits.json` | scanner results |
| `resumes/` | resume variants: DevOps-AI (default), DevSecOps (security offers only), plus certificates (CKA, AWS SAA) and transcripts |

**Statuses:**
- `applied`: submitted and confirmed, or email sent
- `unconfirmed`: submitted but no confirmation seen; check before re-applying
- `needs_review`: blocked on a decision or fact from the user
- `skipped`: filtered out (visa, language, not a fit…)
- `rejected`, `interview`
- `selected`: prepared, waiting to be filled
- `dry_run`, `error`: retried later

All of these except `dry_run` and `error` are final in live mode, so the offer is never processed again (`src/store.py`).

To record from code:
```python
from src import store
store.record(url, site, title, company, status, reason, resume, country="...")
```
Email applications use `mailto:<address>` as the URL.

Quick count:
```bash
python -c "import sqlite3;print(dict(sqlite3.connect('data/applications.db').execute('select status,count(*) from applications group by status').fetchall()))"
```

---

## 7. Configuration and secrets

| File | Purpose | In git? |
|---|---|---|
| `config.yaml` | keywords, countries, filters, submit policy, pacing, LLM model | yes |
| `profile.yaml` | every personal fact the bots may use: contact, education, languages, work eligibility, availability, standard answers | **no** |
| `projects.yaml` | projects the bot is allowed to mention | **no** |
| `resumes.yaml` | which resume for which kind of offer | **no** |
| `.env` | LLM endpoint + key (Azure, `OPENAI_BASE_URL`) | **no** |
| `data/` | browser profile, DB, letters, logs | **no** |

**Passwords:**
- Never typed into files, logs, memory or chat output.
- They go through an environment variable and `python agent.py secret <n> PORTAL_PW`.
- Portal accounts are created with the user's Gmail address and usual password. Verification codes are asked from the user.

---

## 8. House rules (non-negotiable)

1. **Truth only.**
   - Every answer comes from `profile.yaml`, `projects.yaml` or the resumes.
   - Work authorisation in France/EU is answered **No**; the internship visa comes through the INSAT internship agreement (convention de stage).
   - Never claim residence in another country (e.g. Hellowork gates Tunisia: use the inline quick-apply form, never a fake country).
   - Don't present a past job as current.
2. **Consent / certification checkboxes** (GDPR consent, "I certify…") are ticked by the user personally.
3. **Captchas** are never solved by the bot; the user does them.
4. **Unknown question → stop and ask**, don't guess. The helper scripts refuse to submit when a question is unknown.
5. **Cover letters and motivation answers always cite the CKA and AWS Solutions Architect – Associate certifications.**
6. **Default resume = DevOps-AI**; use the DevSecOps resume only for security offers.
7. **Email pacing:** at most about 40–50 mails per batch, 45 s apart.
8. **Known knockouts:**
   - Ericsson Sweden theses auto-reject non-Swedish-university students.
   - Some companies (e.g. Atos) only take candidates already in France.
   - Prefer companies that sponsor or relocate.

---

## 9. Typical session recipes

**Check the inbox and update statuses**
1. Make sure the bot Chrome is up (port 9222).
2. Read new threads (`newer_than:1d -from:me`) and classify them per section 5.
3. Update `applications.db` (by rowid or `mailto:` URL) and the sheet's L/N columns.
4. Answer any screening questionnaires before their deadline.

**Apply to new portal offers**
1. Run the scanners (or `main.py`), then shortlist by fit, visa and language.
2. For each offer: `agent.py open` → `look` → fill → `upload resume/cover` → review → submit only if every answer is a known fact → `record`.
3. Watch for follow-up emails: confirmation links, screening questionnaires.

**Send a batch of spontaneous emails**
1. Pick about 50 `To review` rows (rules in section 4).
2. Run `python -X utf8 data/outreach/send_batch.py FR:<#> … EN:<#> …` (it takes about 45 minutes; run it in the background).
3. Check Gmail Sent and Drafts. The sheet and DB are updated by the script.

**Find more targets for the campaign**
- `collect_devops_companies.py` → `find_company_emails.py` → `build_sheet.py`. New rows are marked "New – batch N".

---

## 10. Tests

`python tests/run_all.py` runs offline tests with fictional data and HTML fixtures (`tests/fixtures/`). They cover:
- answer rules
- form filling on LinkedIn-like and ATS-like pages
- the pipeline
- safety (no invented facts, no submit on uncertainty)
