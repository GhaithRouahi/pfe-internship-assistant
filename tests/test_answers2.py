import sys
sys.path.insert(0, ".")
from src.config import CFG
CFG["llm"]["enabled"] = False
from src import answers as A
YN = ["Yes", "No"]; ON = ["Oui", "Non"]
CASES = [
 ("France", "Do you have experience in a similar role?", YN, "radio", "", None),
 ("France", "Are you willing to work weekends?", YN, "radio", "", None),
 ("France", "How many years of experience do you have in total?", None, "number", "", "1"),
 ("France", "Number of years of experience as a DevOps engineer", None, "number", "", "1"),
 ("France", "Do you own a mobile phone?", YN, "radio", "", None),
 ("France", "Website", None, "url", "", "https://github.com/janedoe-example"),
 ("France", "Address", None, "text", "", None),
 ("France", "Postal code", None, "text", "", None),
 ("France", "Country", ["France", "Tunisia"], "select", "", "Tunisia"),
 ("France", "Pays de résidence", ["France", "Tunisie"], "select", "", "Tunisie"),
 ("France", "Pourrez-vous fournir une convention de stage ?", ON, "radio", "", "Oui"),
 ("United Kingdom", "Do you have the right to work in the UK?", YN, "radio", "", "No"),
 ("Germany", "Are you eligible to work in Germany without a visa?", YN, "radio", "", "No"),
 ("Canada", "Do you currently hold a valid work permit for Canada?", YN, "radio", "", "No"),
 ("Canada", "Will you require a work permit to work in Canada?", YN, "radio", "", "Yes"),
 ("France", "Disponibilité", None, "text", "", "Février 2027"),
 ("France", "Quand pouvez-vous commencer ?", None, "text", "", "Février 2027"),
 ("France", "Do you have experience with Kubernetes?", ["Yes", "No"], "select", "", "Yes"),
 ("France", "Do you have hands-on experience with Terraform and Ansible?", YN, "radio", "", "Yes"),
 ("France", "Notice period", None, "text", "", "None (student)"),
 ("France", "Full name", None, "text", "", "Jane Doe"),
 ("France", "Nom", None, "text", "", "Doe"),
 ("France", "Are you a veteran?", ["I am not a protected veteran", "I identify as a veteran", "I don't wish to answer"], "select", "", "I don't wish to answer"),
 ("France", "Years of experience with Python", ["Less than 1 year", "1-3 years", "3+ years"], "select", "", "1-3 years"),
]
bad = 0
for country, q, opts, kind, ph, exp in CASES:
    A.set_context(country, "linkedin", "Stage DevOps", "Acme", "Nous recherchons un stagiaire DevOps pour notre équipe")
    a = A.answer(q, opts, kind, ph)
    got = a.value if a else None
    bad += got != exp
    if got != exp:
        print("FAIL", f"{q[:70]:70s} -> {got!r} (expected {exp!r})")
print(f"{len(CASES) - bad}/{len(CASES)} passed")
