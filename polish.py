"""Rifinitura deterministica dei post di metodologia e Latest Science prima del rendering: nessuna AI.

- titolo e intestazioni in sentence case (lo stile della pagina), senza toccare nomi propri, acronimi e termini che il
  post stesso scrive con la maiuscola a metà frase;
- reference ripulite (entità HTML come «&amp;», doppioni) e, in testa, l'articolo da cui nasce il post (quello della
  slide «Based on»): la fonte mostrata e le reference non possono più divergere;
- etichetta «Source» delle slide coerente con le reference;
- hashtag adatti al tipo di post (niente #ResearchMethodology su un post clinico);
- punti chiave «Titolo: testo» senza doppia punteggiatura («Is it good?:»);
- link al sito giusto (i post Latest Science stanno su science.html, non su methodology.html)."""
import html
import re

CLINICAL = "Latest Science"
PROPER = {"Bayesian", "Gaussian", "Poisson", "Cox", "Kaplan", "Meier", "Fisher", "Student", "Wilcoxon", "Mann",
          "Whitney", "Pearson", "Spearman", "Likert", "Cohen", "Bonferroni", "Bland", "Altman", "Delphi", "Wald",
          "Markov", "Monte", "Carlo", "Hawthorne", "Berkson", "Simpson", "Neyman", "Rubin", "Bradford", "Hill",
          "Fugl", "Meyer", "Barthel", "Berg", "Rankin", "Glasgow", "Helsinki", "Nuremberg", "Europe", "European",
          "America", "American", "English", "Italian", "Italy", "January", "February", "March", "April", "May",
          "June", "July", "August", "September", "October", "November", "December", "Monday", "Friday"}
RX_CAP = re.compile(r"^([A-Z])([a-z]+)(['’]s)?([^A-Za-z]*)$")
RX_HYPH = re.compile(r"^([A-Z]?[a-z]*|[A-Z])(-[A-Z][a-z]+)+([^A-Za-z]*)$")      # «Sample-Specific», «P-Values»
RX_DOI = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.I)


def _proper_in(context):
    """Parole che il post scrive con la maiuscola a metà frase (quindi nomi propri o termini da tenere così)."""
    out = set()
    for sentence in re.split(r"(?<=[.!?:])\s+|\n+", context or ""):
        words = sentence.split()
        for w in words[1:]:
            m = re.match(r"^[(\"“']?([A-Z][a-z]+)", w)
            if m:
                out.add(m.group(1))
    return out


def sentence_case(text, context=""):
    """«Why Even One Outlier Destroys the Mean» → «Why even one outlier destroys the mean». Lascia stare un testo che
    non è in Title Case, le parole tutte maiuscole (acronimi), quelle con maiuscole interne (McNemar, Fugl-Meyer) e i
    nomi propri noti o usati con la maiuscola a metà frase nel post."""
    if not text:
        return text
    words = text.split(" ")
    long_ = [w for w in words[1:] if re.match(r"^[A-Za-z]{4,}", w)]
    if not long_ or sum(w[0].isupper() for w in long_) / len(long_) < 0.6:
        keep = PROPER | _proper_in(context)               # non è Title Case: sistema solo i composti («Sample-Specific»)
        return " ".join(w if i == 0 or not RX_HYPH.match(w) or any(p in keep for p in re.findall(r"[A-Z][a-z]+", w))
                        else "-".join([w.split("-")[0][:1].lower() + w.split("-")[0][1:] if len(w.split("-")[0]) > 1 else w.split("-")[0]]
                                      + [r[:1].lower() + r[1:] for r in w.split("-")[1:]])
                        for i, w in enumerate(words))
    keep = PROPER | _proper_in(context)
    out = []
    for i, w in enumerate(words):
        prev = out[-1] if out else ""
        m = RX_CAP.match(w)
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if m and (m.group(3) or re.match(r"^[\dIVX]+\b", nxt)):   # «Cronbach's», «Table 1», «Phase II»: restano così
            out.append(w)
            continue
        if i > 0 and not prev.endswith((":", "?", "!", ".")) and RX_HYPH.match(w) \
                and not any(part in keep for part in re.findall(r"[A-Z][a-z]+", w)):
            head, *rest = w.split("-")               # composti in Title Case: «Sample-Specific» → «sample-specific»
            head = head if len(head) == 1 else head[:1].lower() + head[1:]
            out.append("-".join([head] + [r[:1].lower() + r[1:] for r in rest]))
        elif i == 0 or prev.endswith((":", "?", "!", ".")) or not m or m.group(1) + m.group(2) in keep:
            out.append(w)
        else:
            out.append(w[0].lower() + w[1:])
    return " ".join(out)


def tidy_reference(ref):
    ref = html.unescape(html.unescape(ref or "")).strip()
    return re.sub(r"\s+", " ", ref)


def _doi(ref):
    m = RX_DOI.search(ref or "")
    return m.group(0).rstrip(".,;)").lower() if m else ""


def _key(ref):
    return _doi(ref) or re.sub(r"\W+", "", ref.lower())[:80]


def lead_reference(post, apa):
    """L'articolo della slide «Based on» diventa la prima reference (se non c'è già); niente doppioni."""
    refs = [tidy_reference(r) for r in post.get("references") or [] if r]
    if apa:
        apa = tidy_reference(apa)
        refs = [apa] + [r for r in refs if _key(r) != _key(apa)]
    seen, out = set(), []
    for r in refs:
        if _key(r) not in seen:
            seen.add(_key(r))
            out.append(r)
    post["references"] = out
    return out


def _cite_of(ref):
    """«Surname et al., Year» / «Surname, Year» da una reference APA."""
    m = re.match(r"\s*([^,(]+?),", ref or "")
    y = re.search(r"\((\d{4})", ref or "")
    if not (m and y):
        return ""
    many = ref.count("., ") >= 2 or "&" in ref.split("(")[0]
    return f"{m.group(1).strip()}{' et al.' if many else ''}, {y.group(1)}"


def align_sources(post, lead_cite=""):
    """L'etichetta «Source» di una slide deve rimandare a una reference del post: se cita un lavoro che non è tra le
    reference, diventa la fonte principale (o sparisce se non c'è)."""
    refs = post.get("references") or []
    surnames = {(_cite_of(r).split(",")[0].replace(" et al.", "").strip().lower()) for r in refs}
    for s in post.get("slides") or []:
        src = (s.get("source") or "").strip()
        if src and src.split(",")[0].replace(" et al.", "").strip().lower() not in surnames:
            s["source"] = lead_cite


def point(heading, body):
    """«Titolo: testo», senza «?:» o «.:» quando il titolo finisce già con un segno di punteggiatura."""
    heading, body = (heading or "").strip(), (body or "").strip()
    if not heading:
        return body
    return f"{heading} {body}" if heading[-1] in "?!.:" else f"{heading}: {body}"


def hashtags(post, fixed):
    """Hashtag del post: per Latest Science solo #ClinicalResearch fisso, mai #ResearchMethodology."""
    own = [t for t in post.get("hashtags") or [] if t]
    if post.get("category") == CLINICAL:
        pool = ["#ClinicalResearch"] + [t for t in own if t.lower() != "#researchmethodology"]
    else:
        pool = list(fixed) + own
    seen, out = set(), []
    for t in pool:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def page_anchor(post):
    """Pagina del sito che ospita il post."""
    pid = post.get("id", "")
    return f"science#s-{pid}" if post.get("category") == CLINICAL else f"methodology#m-{pid}"


def polish_post(post, apa=""):
    """Rifinitura completa di un post di metodologia o Latest Science (sul posto). `apa`: reference APA dell'articolo
    della slide «Based on», se c'è."""
    slides = post.get("slides") or []
    context = " ".join([post.get("caption") or "", post.get("takeaway") or ""] +
                       [s.get("body") or "" for s in slides])
    post["title"] = sentence_case(post.get("title", ""), context)
    th = post.get("title_highlight") or ""
    i = post["title"].lower().find(th.lower()) if th else -1
    if i >= 0:                                    # l'evidenziato deve restare identico al titolo, maiuscole comprese
        post["title_highlight"] = post["title"][i:i + len(th)]
    for s in slides:
        s["heading"] = sentence_case(s.get("heading", ""), context)
    lead_reference(post, apa)
    align_sources(post, _cite_of(apa) if apa else "")
    return post
