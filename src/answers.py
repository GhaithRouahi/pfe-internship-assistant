"""Question -> Answer(value, source).

source:
  profile     a fact copied from profile.yaml (name, email, school...)
  rule        a deterministic rule built on profile facts (visa, start date, years of experience...)
  llm_text    open motivation text written by the LLM from your facts only
  llm_choice  the LLM had to judge (screening answer) -> uncertain, not auto-submitted unless allowed in config
Returns None when the truthful answer is not known; the engine then sends the offer to the review list.
"""
import hashlib, json, re, unicodedata
from datetime import date
from typing import NamedTuple, Optional
from . import llm
from .config import CFG, PROFILE, PROJECTS


class Answer(NamedTuple):
    value: str
    source: str


P, ED, IN = PROFILE["personal"], PROFILE["education"], PROFILE["internship"]
WE, EX = PROFILE["work_eligibility"], PROFILE["experience"]
CTX = {"country": "", "site": "", "job_text": "", "job_key": "", "title": "", "company": ""}
_cache = {}

SITE_NAMES = {"linkedin": "LinkedIn", "indeed": "Indeed", "wttj": "Welcome to the Jungle", "generic": "Company website"}
MONTHS = {"en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
          "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
          "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]}
YES = {"yes", "oui", "ja", "si", "y", "true"}
NO = {"no", "non", "nein", "n", "false"}
CEFR = ["A1", "A2", "B1", "B2", "C1", "C2"]
LANG_NAMES = {"Arabic": r"arab", "English": r"english|anglais|englisch|ingles", "French": r"french|francais|franzosisch|frances",
              "German": r"german|allemand|deutsch|aleman"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = s.replace("’", "'").lower()
    return re.sub(r"\s+", " ", s).strip()


FOREIGN_SCRIPT = re.compile(r"[Ͱ-᷿⺀-￯]")   # Greek, Cyrillic, Arabic, Devanagari, CJK... inside a FR/EN/DE text = model glitch


def clean_ai_text(text: str) -> str:
    """'' when an AI text is unusable (foreign-script glitch, placeholders)."""
    if not text or FOREIGN_SCRIPT.search(text) or re.search(r"\[[^\]]*\]|\{[^}]*\}|lorem|XXX|<[a-z]+>", text, re.I):
        return ""
    return text


def set_context(country: str, site: str, title: str, company: str, job_text: str, applied_before: bool = False):
    CTX.update(applied_before=applied_before)
    CTX.update(country=country or "", site=site, title=title or "", company=company or "", job_text=job_text or "",
               job_key=hashlib.sha1(f"{title}|{company}|{job_text[:500]}".encode("utf-8", "ignore")).hexdigest())


def lang_of(text: str) -> str:
    t = " " + norm(text) + " "
    fr = len(re.findall(r" (le|la|les|des|vous|votre|vos|etes|avez|quel|quelle|pourquoi|comment|est-ce|du|une) ", t))
    de = len(re.findall(r" (sie|ihre|haben|sind|der|die|das|und|wie|warum) ", t))
    en = len(re.findall(r" (the|you|your|are|have|what|why|how|do|is|of) ", t))
    fr += len(re.findall(r" (pretentions?|salaire|salariales?|souhaitee?s?|duree|disponibilite|debut|lettre|prenom|ville|pays|annees?|mois|"
                         r"telephone|adresse|niveau|etudes|ecole|diplome|quand|combien|quelle?s?) ", t)) + len(re.findall(r"\w-vous\b", t))
    de += len(re.findall(r" (gehalt|gehaltsvorstellung|eintrittsdatum|vorname|nachname|stadt|dauer|monate|kenntnisse) ", t))
    if fr == de == en == 0 and CTX.get("job_text") and text is not CTX["job_text"]:
        return lang_of(CTX["job_text"][:1500])   # bare label: use the offer's language
    return "fr" if fr > max(de, en) else "de" if de > max(fr, en) else "en"


def is_label_like(q: str) -> bool:
    """A field label ('Email', 'Ville') rather than a question - identity facts are only typed into these."""
    n = norm(q).rstrip(" *:")
    return len(n.split()) <= 6 and "?" not in n


def home() -> bool:
    return norm(CTX["country"]) == norm(WE["home_country"])


# ---------------------------------------------------------------- options

def _yn(flag: bool, options):
    want = YES if flag else NO
    if not options:
        return "Yes" if flag else "No"
    for o in options:
        if norm(o).strip(" .!") in want:
            return o
    for o in options:   # "Yes, I am", "Non, je ne suis pas"
        first = re.split(r"[ ,.(/-]", norm(o))[0]
        if first in want:
            return o
    return None


def _range(text):
    """'1-2 years' -> (1,2), 'Less than 1 year' -> (0,0.99), '5+'/'Plus de 5 ans' -> (5,99), '3' -> (3,3)."""
    t = norm(text)
    nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", t)]
    if not nums:
        if re.search(r"\b(none|aucune?|no experience|pas d.experience|keine)\b", t):
            return (0, 0)
        return None
    if re.search(r"less than|moins d|under|weniger als|<", t):
        return (0, nums[0] - 0.01)
    if re.search(r"\+|more than|plus de|over|mehr als|or more|ou plus|>", t):
        return (nums[0], 99)
    if len(nums) >= 2:
        return (nums[0], nums[1])
    return (nums[0], nums[0])


def _pick_number(n, options):
    best = None
    for o in options:
        r = _range(o)
        if r and r[0] <= n <= r[1]:
            if r[0] == n:
                return o
            best = best or o
    return best


def pick(value, options):
    """Map a desired value onto one of the real options. Strict: exact / yes-no / numeric range / prefix. Never a loose substring."""
    if not options:
        return value
    v = norm(value)
    for o in options:
        if norm(o) == v:
            return o
    if v in YES or v in NO:
        return _yn(v in YES, options)
    if re.fullmatch(r"\d+(\.\d+)?", v):
        return _pick_number(float(v), options)
    starts = [o for o in options if norm(o).startswith(v) or (len(norm(o)) >= 4 and v.startswith(norm(o)))]
    return starts[0] if len(starts) == 1 else None


def _pick_any(candidates, options):
    for c in candidates:
        r = pick(c, options)
        if r:
            return r
    return None


# ---------------------------------------------------------------- formatting

def format_date(iso: str, placeholder: str = "", input_type: str = "", q: str = ""):
    y, m, d = (int(x) for x in iso.split("-"))
    ph = norm(placeholder)
    if input_type == "date":
        return f"{y:04d}-{m:02d}-{d:02d}"
    if input_type == "month":
        return f"{y:04d}-{m:02d}"
    if re.search(r"^(mm|mo)[/.-](yyyy|aaaa|jjjj)$", ph):
        return f"{m:02d}/{y}"
    if re.search(r"^(mm|mo)[/.-](dd|jj|tt)", ph):
        return f"{m:02d}/{d:02d}/{y}"
    if re.search(r"^(dd|jj|tt)[/.-](mm|mo)", ph):
        sep = "." if "." in ph else "/"
        return f"{d:02d}{sep}{m:02d}{sep}{y}"
    if re.search(r"^(yyyy|aaaa)[/.-]", ph):
        return f"{y}-{m:02d}-{d:02d}"
    lang = lang_of(q)
    return f"{MONTHS[lang][m - 1].capitalize() if lang != 'en' else MONTHS['en'][m - 1]} {y}" if not ph else None


def _start_options(options):
    y, m, _ = (int(x) for x in IN["start_date"].split("-"))
    for o in options:
        t = norm(o)
        if str(y) in t and any(norm(MONTHS[l][m - 1])[:3] in t for l in MONTHS):
            return o
    return None


# ---------------------------------------------------------------- language levels

def _lang_answer(q, options, kind):
    n = norm(q)
    for lang, pat in LANG_NAMES.items():
        if re.search(pat, n):
            break
    else:
        return None
    lvl = PROFILE["languages"].get(lang)
    if not lvl:
        v = _yn(False, options) if options else None
        return Answer(v, "profile") if v else None
    rank = CEFR.index(lvl)
    native = lang in PROFILE.get("native_languages", [])
    if re.search(r"native|maternelle|muttersprache|nativ", n) and not re.search(r"level|niveau|proficien", n):
        return Answer(_yn(native, options), "rule") if _yn(native, options) else None
    if options:
        # LinkedIn scale (EN/FR), CEFR codes, or generic words
        scale = [  # (min CEFR rank, patterns)
            (5, r"native|bilingu|maternelle|muttersprach"),
            (4, r"full professional|professionnelle complete|fluent|courant|fliessend|verhandlungssicher|advanced|avance|c1"),
            (3, r"^professional working|^competence professionnelle$|professional working|upper intermediate|b2|good|bon"),
            (2, r"limited working|professionnelle limitee|intermediate|intermediaire|b1"),
            (0, r"elementary|notions|basic|debutant|grundkenntnisse|a1|a2|beginner"),
        ]
        for o in options:
            if norm(o).upper() in CEFR and norm(o).upper() == lvl:
                return Answer(o, "profile")
        if native:
            for o in options:
                if re.search(scale[0][1], norm(o)):
                    return Answer(o, "profile")
        if any(norm(o).strip(" .!") in YES | NO or re.split(r"[ ,.(/-]", norm(o))[0] in YES | NO for o in options):
            return Answer(_yn(rank >= 3, options), "rule") if _yn(rank >= 3, options) else None
        target = 4 if rank == 4 else 3 if rank == 3 else 2 if rank == 2 else 0
        for min_rank, pat in scale:
            if min_rank == target:
                hits = [o for o in options if re.search(pat, norm(o))]
                if len(hits) == 1:
                    return Answer(hits[0], "profile")
        return None
    if kind == "number":
        return None
    return Answer({"en": f"{lvl} (CEFR)", "fr": f"{lvl} (CECRL)", "de": f"{lvl} (GER)"}[lang_of(q)], "profile")


# ---------------------------------------------------------------- skills

def _skills_in(q):
    n = " " + norm(q) + " "
    return [s for s in EX["skills_years"] if re.search(r"(?<![a-z0-9])" + re.escape(norm(s)) + r"(?![a-z0-9])", n)]


STOP = set("""do does you have any experience with using use used worked work working familiar knowledge of in on the a an are is
your hands professional proficient comfortable practical prior previous avez vous de d l une un des avec en le la les du experience
connaissance connaissances maitrisez maitrise travaille utilise utilisez deja haben sie erfahrung mit kenntnisse der die das im
und and et""".split())


def _residual(q, skills):
    """How many content words remain besides known skills - more than a few means the question asks about something else too."""
    t = norm(q)
    for s in skills:
        t = re.sub(r"(?<![a-z0-9])" + re.escape(norm(s)) + r"(?![a-z0-9])", " ", t)
    return len([w for w in re.findall(r"[a-z0-9+#.]+", t) if w not in STOP and len(w) > 1])


def _years_question(q):
    return re.search(r"(how many|combien d|number of|nombre d|wie viele).{0,40}(years?|annees?|ans\b|jahre)|years? of .{0,30}experience|"
                     r"annees? d.experience|ans d.experience|jahre(n)? .{0,20}erfahrung", norm(q))


def _general_experience(q):
    return re.search(r"(professional|work|total|overall|relevant|professionnelle|travail|totale|berufs).{0,15}(experience|erfahrung)|"
                     r"experience (professionnelle|totale|pertinente)", norm(q))


# ---------------------------------------------------------------- main entry

def answer(question: str, options=None, kind: str = "text", placeholder: str = "") -> Optional[Answer]:
    q = (question or "").strip()
    if not q:
        return None
    n = norm(q)
    opts = [o for o in (options or []) if o and o.strip()]

    # 0) user overrides
    for rule in PROFILE.get("answers") or []:
        if rule.get("country") and norm(rule["country"]) != norm(CTX["country"]):
            continue
        if rule.get("not_country") and norm(rule["not_country"]) == norm(CTX["country"]):
            continue
        if re.search(rule["pattern"], n, re.I):
            v = pick(rule["value"], opts)
            return Answer(v, "rule") if v else None

    a = _rules(q, n, opts, kind, placeholder)
    if a is not None:
        return a if a.value not in (None, "") else None

    # LLM fallback
    open_ended = re.search(r"\bwhy\b|pourquoi|warum|tell us|describe|decri|presentez|motivation|cover letter|lettre|"
                           r"additional information|informations? complementaires?|anything else|message|about yourself|"
                           r"parlez-nous|what makes you|qu.est-ce qui|summary|resume yourself", n)
    if kind in ("textarea", "text") and open_ended and not opts:
        if not CFG["submit_policy"].get("allow_llm_free_text", True):
            return None
        v = _llm(q, None, free_text=True)
        return Answer(v, "llm_text") if v else None
    v = _llm(q, opts or None, free_text=False)
    if v is None:
        return None
    if opts:
        v = pick(v, opts)
        return Answer(v, "llm_choice") if v else None
    if kind == "number" and not re.fullmatch(r"\d+(\.\d+)?", v.strip()):
        return None
    return Answer(v, "llm_choice")


def _rules(q, n, opts, kind, placeholder):
    label = is_label_like(q)

    # ---- identity (only into short labels, never inside a sentence)
    if label:
        if re.search(r"country code|code pays|indicatif|phone country|landesvorwahl", n):
            v = _pick_any([f"{P['country_fr']} ({P['phone_country_code']})", f"{P['country']} ({P['phone_country_code']})",
                           P["country_fr"], P["country"], P["phone_country_code"]], opts) if opts else P["phone_country_code"]
            return Answer(v, "profile") if v else Answer("", "profile")
        table = [
            (r"\b(first|given) name\b|^prenom|\bvorname\b|^nombre$", P["first_name"]),
            (r"\b(last|family|sur) ?name\b|nom de famille|^nom$|\bnachname\b|apellido", P["last_name"]),
            (r"^(full )?name$|^nom( complet)?$|nom et prenom|prenom et nom|^your name$|^vollstandiger name$", f"{P['first_name']} {P['last_name']}"),
            (r"e-?mail|courriel", P["email"]),
            (r"phone|telephone|mobile|portable|handy|telefon|^cell", None),   # handled by form (national vs international)
            (r"linkedin", P["linkedin_url"]),
            (r"github", P["github_url"]),
            (r"website|portfolio|site (web|personnel)|personal (site|url)|^url$", P["portfolio_url"]),
            (r"^(?!.*(prefer|desired|souhait|wunsch|willing|target|work location|lieu de travail))"
             r".*(\bcity\b|^ville|stadt|ciudad|location|localisation|lieu de residence)", P["city"]),
            (r"^(country|pays|land|pais)( of residence| de residence)?$|country of residence", None),
            (r"nationalit|citizenship|citoyennete", None),
            (r"school|university|universit|ecole|institution|hochschule|etablissement", ED["school"]),
            (r"^(degree|diplome|diploma|qualification)( type)?$", ED["degree"]),
            (r"field of study|major|discipline|specialit|domaine d.etudes|filiere|studiengang", ED["field"]),
            (r"graduation|date de (fin d.etudes|diplomation|obtention)|annee d.obtention|abschluss", "DATE:" + ED["graduation_date"]),
            (r"\bgpa\b|moyenne|grade point|notendurchschnitt", ED["gpa"]),
        ]
        for pat, val in table:
            if re.search(pat, n):
                if pat.startswith("phone"):
                    return Answer("PHONE", "profile")
                if pat.startswith("^(country"):
                    v = _pick_any([P["country"], P["country_fr"]], opts) if opts else P["country"]
                    return Answer(v, "profile") if v else None
                if pat.startswith("nationalit"):
                    v = _pick_any([P["nationality"], P["country"], P["country_fr"], "Tunisienne", "Tunisien"], opts) if opts else P["nationality"]
                    return Answer(v, "profile") if v else None
                if val and val.startswith("DATE:"):
                    if opts:
                        return None
                    v = format_date(val[5:], placeholder, kind, q)
                    return Answer(v, "profile") if v else None
                if not val:
                    return None
                v = pick(val, opts) if opts else val
                return Answer(v, "profile") if v else None

    # ---- visa / work authorization
    # "Do you NEED a visa / permit / sponsorship?" -> need.  "Are you AUTHORIZED to work (without sponsorship)?" -> authorization.
    auth_words = re.search(r"authori[sz]ed|eligible|legally|right to work|autorise|habilite|berechtigt|erlaubt zu arbeiten", n)
    need_q = re.search(r"(need|require|besoin|benotigen|brauchen|necesita).{0,40}(sponsor|visa|visum|permit|permis|erlaubnis|"
                       r"genehmigung|parrainage|autorisation|titre de sejour)", n)
    if need_q and not auth_words:
        v = _yn(not home() and WE["needs_sponsorship_elsewhere"], opts)
        return Answer(v, "rule") if v else None
    if re.search(r"(authori[sz]ed|eligible|legally|right|permit(ted)?|allowed|autorise|habilite|droit|berechtigt|erlaubt).{0,50}"
                 r"(work|travailler|arbeiten|trabajar)|work (permit|authori[sz]ation|eligibility)|permis de travail|"
                 r"autorisation de travail|arbeitserlaubnis|arbeitsgenehmigung", n):
        v = _yn(home(), opts)
        return Answer(v, "rule") if v else None
    if re.search(r"sponsor|parrainage|\bvisa\b|titre de sejour|aufenthalt", n):
        v = _yn(not home() and WE["needs_sponsorship_elsewhere"], opts)
        return Answer(v, "rule") if v else None
    if re.search(r"\b(eu|eea|ue|european union|union europeenne|eu-burger)\b.{0,30}(citizen|national|citoyen|ressortissant|staatsb)|"
                 r"(citizen|citoyen|ressortissant).{0,30}\b(eu|eea|ue|european union|union europeenne)\b", n):
        v = _yn(WE["eu_citizen"], opts)
        return Answer(v, "rule") if v else None
    if re.search(r"nationalit|citizenship|citoyennete|staatsangehorigkeit", n):
        v = _pick_any([P["nationality"], P["country"], P["country_fr"], "Tunisienne", "Tunisien"], opts) if opts else P["nationality"]
        return Answer(v, "profile") if v else None

    # ---- degree level (a PFE student is preparing a Bac+5 / Master-level engineering degree)
    if re.search(r"niveau (de |d.)(diplome|etudes|formation)|degree level|level of (education|study|degree)|education level|"
                 r"highest (level of )?(education|degree|qualification)|diplome (prepare|en cours)|current degree|"
                 r"hochster abschluss|bildungsabschluss|niveau d.etudes", n):
        if opts:
            for pat in (r"bac\s*\+\s*5", r"\bmaster", r"ingenieur|engineer", r"\bm2\b"):
                hits = [o for o in opts if re.search(pat, norm(o))]
                if len(hits) == 1:
                    return Answer(hits[0], "rule")
            return None
        return Answer({"fr": "Bac+5 (diplôme d'ingénieur, en cours)", "en": "Master's-level engineering degree (in progress)",
                       "de": "Ingenieurdiplom auf Master-Niveau (laufend)"}[lang_of(q)], "rule")

    # ---- "have you applied / interviewed / worked here before?"
    if re.search(r"(already|previously|before|deja|auparavant|bereits|fruher|ever).{0,70}(appl|candidat|postul|recrutement|interview|"
                 r"entretien|bewerb|worked (for|at)|employed|travaille pour)|(appl|postul|candidat|recrutement|interview|entretien|worked (for|at)|"
                 r"employed).{0,70}(before|auparavant|deja|previously|in the past|par le passe)", n):
        company = norm(CTX["company"])
        known = [norm(c) for c in (PROFILE.get("previously_applied_companies") or []) + (PROFILE.get("past_employers") or [])]
        before = CTX.get("applied_before") or any(c and company and (c in company or company in c) for c in known)
        v = _yn(bool(before), opts)
        return Answer(v, "rule") if v else None

    # ---- logistics
    if re.search(r"relocat|demenag|willing to move|mobilite geographique|umzug|umziehen|reubica", n):
        v = _yn(IN["willing_to_relocate"], opts)
        return Answer(v, "rule") if v else None
    if re.search(r"(on-?site|onsite|hybrid|hybride|presentiel|in (the|our) office|au bureau|sur site|vor ort)", n) and \
            re.search(r"willing|able|comfortable|ok |accept|pret|dispos|bereit|can you|pouvez", n):
        v = _yn(IN["willing_onsite_or_hybrid"], opts)
        return Answer(v, "rule") if v else None
    if re.search(r"(18|eighteen|dix-huit).{0,10}(years|ans|jahre)|at least 18|legal age|majeur|volljahrig", n):
        v = _yn(WE["over_18"], opts)
        return Answer(v, "rule") if v else None
    if re.search(r"start date|date de debut|date d.entree|available (to start|from)|availability|disponibilit|quand pouvez|"
                 r"when (can|could) you (start|begin|join)|earliest|fruhest|eintrittsdatum|fecha de inicio|commencer", n):
        if opts:
            v = _start_options(opts)
            return Answer(v, "rule") if v else None
        if kind == "number":
            return None
        v = format_date(IN["start_date"], placeholder, kind, q)
        return Answer(v, "rule") if v else None
    if re.search(r"duration|duree|how long|combien de (mois|temps)|length of (the |your )?internship|dauer|nombre de mois|how many months", n):
        m = IN["duration_months"]
        if opts:
            v = _pick_number(m, opts) or _pick_any([f"{m} months", f"{m} mois", f"{m} Monate", str(m)], opts)
            return Answer(v, "rule") if v else None
        if kind == "number":
            return Answer(str(m), "rule")
        return Answer({"en": f"{m} months", "fr": f"{m} mois", "de": f"{m} Monate"}[lang_of(q)], "rule")
    if re.search(r"(currently|actuellement|derzeit).{0,30}(student|enrolled|etudiant|inscrit|studierend|eingeschrieben)|"
                 r"are you (a )?student|etes-vous etudiant|enrolled in|student status", n):
        v = _yn(True, opts)
        return Answer(v, "rule") if v else None
    if re.search(r"convention de stage|internship agreement|part of your (studies|curriculum|degree|program)|"
                 r"stage (obligatoire|de fin d.etudes|conventionne)|pflichtpraktikum|end.of.studies", n):
        v = _yn(True, opts)
        return Answer(v, "rule") if v else None
    if re.search(r"how did you (hear|find|learn)|comment avez-vous (connu|entendu|trouve|decouvert)|ou avez-vous (vu|trouve)|"
                 r"wie sind sie .{0,20}(aufmerksam|gestossen)|^source|referral source", n):
        site = SITE_NAMES.get(CTX["site"], "LinkedIn")
        v = _pick_any([site, "Job board", "Site d'emploi", "Internet", "Other", "Autre"], opts) if opts else site
        return Answer(v, "rule") if v else None
    if re.search(r"gender|genre|sexe|geschlecht|\brace\b|ethnic|veteran|disabilit|handicap|behinderung|sexual orientation|"
                 r"orientation sexuelle|pronoun", n):
        if not opts:
            return Answer("", "rule")   # optional EEO free text: leave empty
        for o in opts:
            if re.search(r"prefer not|decline|don.?t wish|not to (say|disclose|answer)|ne (souhaite|pas) |keine angabe|prefere ne pas", norm(o)):
                return Answer(o, "rule")
        return None
    if re.search(r"salary|salaire|remuneration|gratification|compensation|pay expectation|pretentions|gehalt|verguetung", n):
        if PROFILE.get("salary_expectation"):
            v = pick(str(PROFILE["salary_expectation"]), opts) if opts else str(PROFILE["salary_expectation"])
            return Answer(v, "profile") if v else None
        if opts or kind == "number":
            return None
        return Answer({"en": "Negotiable", "fr": "À négocier", "de": "Verhandelbar"}[lang_of(q)], "rule")
    if re.search(r"notice period|preavis|kundigungsfrist", n):
        if opts:
            v = _pick_any(["Immediately", "Immédiatement", "None", "Aucun", "0"], opts)
            return Answer(v, "rule") if v else None
        return Answer("0" if kind == "number" else {"en": "None (student)", "fr": "Aucun (étudiant)", "de": "Keine (Student)"}[lang_of(q)], "rule")

    # ---- languages
    if any(re.search(p, n) for p in LANG_NAMES.values()) and \
            re.search(r"level|niveau|proficien|maitrise|fluen|courant|speak|parlez|parler|sprechen|kenntnisse|native|maternelle|comp", n):
        a = _lang_answer(q, opts, kind)
        if a:
            return a

    # ---- experience
    skills = _skills_in(q)
    if _years_question(q):
        obj = re.search(r"\b(with|avec|using|mit|in|en|dans|on|sur|as|comme)\s+(?:the |le |la |les |l'|a |an |un |une |tant que )?"
                        r"([a-z0-9+#./-]{2,})", n)
        if skills:
            yrs = min(EX["skills_years"][s] for s in skills)
        elif obj and obj.group(2) not in STOP and obj.group(2) not in ("total", "totale", "all", "general", "tout", "this", "ce", "cette"):
            return None   # experience with something not in your profile -> review list, never a guess
        else:
            yrs = EX["total_years"]
        if opts:
            v = _pick_number(yrs, opts)
            return Answer(v, "rule") if v else None
        return Answer(str(yrs), "rule")
    if skills and _residual(q, skills) <= 3 and re.search(r"experience|familiar|worked with|used|knowledge|connaissance|maitris|travaille avec|utilise|"
                            r"erfahrung|kenntnisse|comfortable|proficient", n) and (not opts or _yn(True, opts)):
        v = _yn(True, opts)
        return Answer(v, "rule") if v else None
    return None


# ---------------------------------------------------------------- LLM

def _llm(question, options, free_text):
    if not llm.available():
        return None
    key = (CTX["job_key"], question, tuple(options or ()), free_text)   # per job: never reuse another company's answer
    if key in _cache:
        return _cache[key]
    lang = lang_of(question)
    if free_text:
        system = ("You answer an open question on an internship application form for the candidate described in the JSON. "
                  "Use ONLY facts from profile/projects; never invent experience, dates, numbers or skills. "
                  "Mention a technology only if it appears in the candidate facts. Do not claim to know the company's internal stack "
                  "beyond what the job description says. Write in the language of the question (" + lang + "), first person, "
                  "concrete, max 110 words, plain text, no placeholders like [Company]. If you cannot answer truthfully reply UNSURE.")
    else:
        system = ("You answer a screening question on an internship application form for the candidate described in the JSON. "
                  "Use ONLY the facts given. If the facts do not make the answer certain, reply exactly UNSURE. "
                  "If options are given, reply with exactly one option string copied verbatim. Otherwise reply with the shortest correct answer.")
    user = json.dumps({"profile": PROFILE, "projects": PROJECTS, "job_title": CTX["title"], "company": CTX["company"],
                       "offer_country": CTX["country"], "job_description": CTX["job_text"][:3500],
                       "question": question, "options": options}, ensure_ascii=False)
    out = ""
    for _ in range(2):   # one retry if the model output is malformed
        try:
            out = llm.complete(system, user, 500).strip().strip('"')
        except Exception:
            out = ""
        if out.upper().startswith("UNSURE") or clean_ai_text(out):
            break
    res = None if (not out or out.upper().startswith("UNSURE") or not clean_ai_text(out)) else out
    _cache[key] = res
    return res
