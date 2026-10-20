"""Offline checks of the answer engine (no LLM: questions that need it must return None or be flagged)."""
import sys
sys.path.insert(0, ".")
from src.config import CFG
CFG["llm"]["enabled"] = False
from src import answers as A

YN = ["Yes", "No"]; ON = ["Oui", "Non"]; JN = ["Ja", "Nein"]
LI_FR = ["Aucune", "Notions", "Compétence professionnelle limitée", "Compétence professionnelle", "Compétence professionnelle complète", "Bilingue ou langue maternelle"]
LI_EN = ["None", "Elementary", "Limited working", "Professional working", "Full professional", "Native or bilingual"]
CASES = [
 # (country, question, options, kind, placeholder, expected)
 ("France", "First name", None, "text", "", "Jane"),
 ("France", "Prénom*", None, "text", "", "Jane"),
 ("France", "Nom de famille", None, "text", "", "Doe"),
 ("France", "Email address", None, "email", "", "jane.doe@example.com"),
 ("France", "Mobile phone number", None, "tel", "", "PHONE"),
 ("France", "Location (city)", None, "text", "", "Tunis"),
 ("France", "Preferred work location", None, "text", "", None),
 ("France", "LinkedIn Profile", None, "url", "", "https://www.linkedin.com/in/jane-doe-example/"),
 ("France", "Are you legally authorized to work in France?", YN, "radio", "", "No"),
 ("France", "Are you authorized to work in France without sponsorship?", YN, "radio", "", "No"),
 ("France", "Will you now or in the future require visa sponsorship?", YN, "radio", "", "Yes"),
 ("France", "Êtes-vous autorisé(e) à travailler en France ?", ON, "radio", "", "Non"),
 ("France", "Avez-vous besoin d'un visa pour travailler en France ?", ON, "radio", "", "Oui"),
 ("Tunisia", "Are you legally authorized to work in Tunisia?", YN, "radio", "", "Yes"),
 ("Tunisia", "Do you require sponsorship?", YN, "radio", "", "No"),
 ("Germany", "Benötigen Sie ein Visum oder eine Arbeitserlaubnis?", JN, "radio", "", "Ja"),
 ("France", "Are you an EU citizen?", YN, "radio", "", "No"),
 ("France", "Nationality", ["France", "Tunisia", "Morocco"], "select", "", "Tunisia"),
 ("France", "Are you willing to relocate?", YN, "radio", "", "Yes"),
 ("France", "Êtes-vous disposé(e) à travailler en présentiel ?", ON, "radio", "", "Oui"),
 ("France", "When can you start?", None, "text", "", "February 2027"),
 ("France", "Date de début souhaitée", None, "text", "jj/mm/aaaa", "01/02/2027"),
 ("France", "Start date", None, "date", "", "2027-02-01"),
 ("France", "Availability", None, "text", "MM/DD/YYYY", "02/01/2027"),
 ("France", "Quelle est votre disponibilité ?", ["Janvier 2027", "Février 2027", "Mars 2027"], "select", "", "Février 2027"),
 ("France", "Durée du stage souhaitée", ["3 mois", "4 mois", "6 mois"], "select", "", "6 mois"),
 ("France", "How many months is your internship?", None, "number", "", "6"),
 ("France", "Combien d'années d'expérience avez-vous en Kubernetes ?", None, "text", "", "1"),
 ("France", "How many years of experience do you have with Terraform?", None, "number", "", "1"),
 ("France", "How many years of work experience do you have with Salesforce?", None, "number", "", None),
 ("France", "Combien d'années d'expérience professionnelle avez-vous ?", None, "text", "", "1"),
 ("France", "Years of experience with AWS", ["0-1 years", "1-2 years", "3-5 years", "5+ years"], "select", "", "1-2 years"),
 ("France", "Do you have experience with Docker?", YN, "radio", "", "Yes"),
 ("France", "Avez-vous de l'expérience avec Kubernetes ?", ON, "radio", "", "Oui"),
 ("France", "Do you have experience with Kubernetes and SAP HANA migrations at enterprise scale?", YN, "radio", "", None),
 ("France", "Do you have experience with Salesforce?", YN, "radio", "", None),
 ("France", "Quel est votre niveau de maîtrise de la langue Anglais ?", LI_FR, "select", "", "Compétence professionnelle complète"),
 ("France", "Quel est votre niveau de maîtrise de la langue Français ?", LI_FR, "select", "", "Compétence professionnelle"),
 ("France", "What is your level of proficiency in German?", LI_EN, "select", "", "Elementary"),
 ("France", "What is your level of proficiency in Arabic?", LI_EN, "select", "", "Native or bilingual"),
 ("France", "Do you speak fluent French?", YN, "radio", "", "Yes"),
 ("France", "English level", ["A1", "A2", "B1", "B2", "C1", "C2"], "select", "", "C1"),
 ("France", "Are you currently enrolled as a student?", YN, "radio", "", "Yes"),
 ("France", "Ce stage s'inscrit-il dans le cadre de votre fin d'études (convention de stage) ?", ON, "radio", "", "Oui"),
 ("France", "Are you at least 18 years old?", YN, "radio", "", "Yes"),
 ("France", "How did you hear about us?", ["LinkedIn", "Indeed", "Friend", "Other"], "select", "", "LinkedIn"),
 ("France", "Gender", ["Male", "Female", "Prefer not to say"], "select", "", "Prefer not to say"),
 ("France", "Salary expectations", None, "text", "", "Negotiable"),
 ("France", "Prétentions salariales", None, "text", "", "À négocier"),
 ("France", "Expected monthly salary (EUR)", None, "number", "", None),
 ("France", "School", None, "text", "", "National Institute of Applied Sciences and Technology (INSAT)"),
 ("France", "Graduation date", None, "text", "MM/YYYY", "06/2027"),
 ("France", "GPA", None, "text", "", "14.00/20"),
 ("France", "Country code", ["France (+33)", "Tunisie (+216)"], "select", "", "Tunisie (+216)"),
 ("France", "Mobile app development experience?", YN, "radio", "", None),
 ("France", "Do you have a driving licence?", YN, "radio", "", None),
 ("France", "Why do you want to join us?", None, "textarea", "", None),
]
bad = 0
for country, q, opts, kind, ph, exp in CASES:
    A.set_context(country, "linkedin", "Stage DevOps", "Acme", "")
    a = A.answer(q, opts, kind, ph)
    got = a.value if a else None
    ok = got == exp
    bad += not ok
    print(("OK  " if ok else "FAIL"), f"{q[:70]:70s} -> {got!r}" + ("" if ok else f"   (expected {exp!r})"))
print(f"\n{len(CASES) - bad}/{len(CASES)} passed")
sys.exit(1 if bad else 0)
