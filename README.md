# PFE / internship application assistant

A browser-driven helper that finds internship offers (LinkedIn, Welcome to the Jungle, Indeed, company career pages),
chooses the right resume and writes a cover letter for each offer, then fills application forms **inside your own Chrome**
(through the DevTools port). Anything the bot is not sure about is sent to a review list instead of being guessed.

## Setup
1. `pip install -r requirements.txt` then `playwright install chromium`
2. Copy the templates and fill in **your own facts** (these files are git-ignored and never leave your machine):
   - `profile.example.yaml` -> `profile.yaml` (contact, education, languages, work eligibility, skills)
   - `projects.example.yaml` -> `projects.yaml` (the projects the bot is allowed to mention)
   - `resumes.example.yaml` -> `resumes.yaml`, and put your resume PDFs in `resumes/`
   - `.env.example` -> `.env` (LLM API key; used for the fit score and cover letters)
3. Run `start_chrome.bat`, log in to the job sites once in that window (the session is kept in `data/chrome_profile`).
4. Review `config.yaml` (keywords, countries, filters such as visa blockers).

## Usage
- `python main.py` dry run (fills forms, never submits); `python main.py --live` real applications; `python report.py` review report
- `python agent.py ...` step-by-step browser commands (see the docstring at the top of `agent.py`)
- Tests (offline, use fictional data): `python tests/run_all.py`

## Safety rules built in
- Never invents experience: only facts from `profile.yaml`, `projects.yaml` and your resumes are used.
- Never solves captchas; stops and asks you.
- Never stores passwords in files: pass them through environment variables.

## Never commit
`.env`, `profile.yaml`, `projects.yaml`, `resumes.yaml`, `resumes/`, `data/` (browser profile, database, cover letters). They are in `.gitignore`.
