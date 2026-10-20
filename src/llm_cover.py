"""Tailored motivation text (+ PDF for 'cover letter' upload fields). Returns ("", "") when it cannot be produced safely."""
import json, re
from datetime import date
from . import llm
from .answers import lang_of, norm, MONTHS, clean_ai_text
from .config import PROFILE, ROOT

COVER_DIR = ROOT / "data" / "covers"


def cover_text(title: str, company: str, job_text: str, best_projects) -> str:
    if not llm.available():
        return ""
    lang = lang_of(job_text[:2000])
    y, m, _ = (int(x) for x in PROFILE["internship"]["start_date"].split("-"))
    start = f"{MONTHS[lang][m - 1]} {y}"
    facts = {"profile": PROFILE, "most_relevant_projects": [p for _, p in best_projects]}
    system = (
        "Write the body of a short motivation letter (130-170 words) for an end-of-studies internship (PFE) application. "
        f"Language: {'French' if lang == 'fr' else 'German' if lang == 'de' else 'English'}. "
        "Rules: use ONLY facts from the candidate JSON; never invent experience, numbers, dates or skills. "
        "Name the employer exactly as written in the job description. Mention a technology only if it appears in BOTH the job "
        "description and the candidate facts. Never claim to know the company's stack beyond the description. "
        f"State availability: {PROFILE['internship']['duration_months']} months from {start}. "
        "Never claim outside recognition or reputation (no 'recognised for', 'known for', 'reconnu pour'): describe personal qualities "
        "plainly as what the candidate brings. "
        "Always mention the two certifications: Certified Kubernetes Administrator (CKA) and AWS Certified Solutions Architect - "
        "Associate (SAA). "
        "No greeting line, no signature, no placeholders, no markdown. Plain paragraphs.")
    user = json.dumps({"job_title": title, "company_hint": company, "job_description": job_text[:4000], "candidate": facts},
                      ensure_ascii=False)
    cert_line = {"fr": "Je suis titulaire des certifications CKA (Certified Kubernetes Administrator) et AWS Solutions Architect - Associate (SAA).",
                 "de": "Ich besitze die Zertifizierungen CKA (Certified Kubernetes Administrator) und AWS Solutions Architect - Associate (SAA).",
                 "en": "I hold the CKA (Certified Kubernetes Administrator) and AWS Solutions Architect - Associate (SAA) certifications."}[lang]
    best = ""
    for _ in range(2):   # one retry when the output is malformed (foreign-script glitch, placeholders, too short)
        try:
            text = llm.complete(system, user, 900).strip()
        except Exception:
            return ""
        if clean_ai_text(text) and len(text.split()) >= 60 and not re.search(r"\bplaceholder\b", text, re.I):
            if re.search(r"\bCKA\b|Certified Kubernetes Administrator", text) and re.search(r"\bSAA\b|Solutions Architect", text):
                return text
            best = best or text
    if best:   # both certifications are required in every letter: append them when the model left one out
        return best.rstrip() + "\n\n" + cert_line
    return ""


def cover_pdf(text: str, title: str, company: str, job_text: str) -> str:
    """Render the letter to data/covers/<company>_<title>.pdf (for upload fields). Returns the path or ''."""
    if not text:
        return ""
    from fpdf import FPDF
    lang = lang_of(job_text[:2000])
    P = PROFILE["personal"]
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", norm(f"{company}_{title}"))[:40].strip("_")   # short names: some portals silently reject long file names or "cover"
    path = COVER_DIR / f"Cover_Letter_{P['first_name']}_{P['last_name']}_{slug}.pdf"
    today = date.today()
    head = {"fr": ("Objet : candidature au stage de fin d'études", "Madame, Monsieur,", "Je vous prie d'agréer mes salutations distinguées."),
            "de": ("Betreff: Bewerbung für das Praktikum", "Sehr geehrte Damen und Herren,", "Mit freundlichen Grüßen"),
            "en": ("Subject: application for the internship", "Dear Hiring Team,", "Kind regards,")}[lang]
    pdf = FPDF(format="A4")
    pdf.set_margins(22, 20, 22)
    pdf.add_page()
    pdf.add_font("Arial", "", r"C:\Windows\Fonts\arial.ttf")
    pdf.add_font("Arial", "B", r"C:\Windows\Fonts\arialbd.ttf")
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 7, f"{P['first_name']} {P['last_name']}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 5, f"{P['city']}, {P['country']}  |  {P['phone_country_code']} {P['phone_national']}  |  {P['email']}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"{P['linkedin_url']}  |  {P['github_url']}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.cell(0, 5, today.strftime("%d/%m/%Y") if lang != "en" else today.strftime("%B %d, %Y"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Arial", "B", 11)
    pdf.multi_cell(0, 6, f"{head[0]} - {title}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Arial", "", 11)
    pdf.multi_cell(0, 6, head[1], new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    for para in [p.strip() for p in text.split("\n") if p.strip()]:
        pdf.multi_cell(0, 6, para, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    pdf.ln(2)
    pdf.multi_cell(0, 6, head[2], new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 6, f"{P['first_name']} {P['last_name']}", new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))
    return str(path)
