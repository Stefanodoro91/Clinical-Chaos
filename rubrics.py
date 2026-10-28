"""Rubriche fisse, trasversali ai tipi di post. Tutte senza AI: contenuti scritti qui, accurati e riformulati
(mai copiati dalle linee guida), così escono anche a quota Gemini finita.

  Checklist         giovedì (slot metodologia): una voce di CONSORT, PRISMA, STROBE, SPIRIT o COSMIN per volta
  Clinical Insights sabato (slot metodologia): il post viene dalla coda normale, ma si preferisce un articolo
                    con DOI così la slide «Based on» mostra la fonte (etichetta in copertina, vedi bot.pick_next)
  Before you apply  venerdì ogni due settimane (slot bandi): 3 consigli pratici di candidatura in una slide in più
  Career Path       primo lunedì del mese (slot posizioni): come leggere gli annunci, glossario dei ruoli
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------- Checklist (giovedì)
REFS = {
    "CONSORT": "Schulz, K. F., Altman, D. G., & Moher, D. (2010). CONSORT 2010 statement: Updated guidelines "
               "for reporting parallel group randomised trials. BMJ, 340, c332. https://doi.org/10.1136/bmj.c332",
    "PRISMA": "Page, M. J., McKenzie, J. E., Bossuyt, P. M., Boutron, I., Hoffmann, T. C., Mulrow, C. D., et al. "
              "(2021). The PRISMA 2020 statement: An updated guideline for reporting systematic reviews. BMJ, "
              "372, n71. https://doi.org/10.1136/bmj.n71",
    "STROBE": "von Elm, E., Altman, D. G., Egger, M., Pocock, S. J., Gøtzsche, P. C., & Vandenbroucke, J. P. "
              "(2007). The Strengthening the Reporting of Observational Studies in Epidemiology (STROBE) "
              "statement: Guidelines for reporting observational studies. The Lancet, 370(9596), 1453–1457. "
              "https://doi.org/10.1016/S0140-6736(07)61602-X",
    "SPIRIT": "Chan, A.-W., Tetzlaff, J. M., Altman, D. G., Laupacis, A., Gøtzsche, P. C., Krleža-Jerić, K., "
              "et al. (2013). SPIRIT 2013 statement: Defining standard protocol items for clinical trials. "
              "Annals of Internal Medicine, 158(3), 200–207. https://doi.org/10.7326/0003-4819-158-3-201302050-00583",
    "COSMIN": "Prinsen, C. A. C., Mokkink, L. B., Bouter, L. M., Alonso, J., Patrick, D. L., de Vet, H. C. W., & "
              "Terwee, C. B. (2018). COSMIN guideline for systematic reviews of patient-reported outcome "
              "measures. Quality of Life Research, 27(5), 1147–1157. https://doi.org/10.1007/s11136-018-1798-3",
}

CITE = {"CONSORT": "Schulz et al., 2010", "PRISMA": "Page et al., 2021", "STROBE": "von Elm et al., 2007",
        "SPIRIT": "Chan et al., 2013", "COSMIN": "Prinsen et al., 2018"}

# Una voce a settimana: (slug, linea guida, voce, titolo ≤70, hook ≤120, gancio didascalia,
# 3 slide [cosa chiede / perché conta / come si fa], takeaway ≤130, evidenziato, hashtag, categoria)
ITEMS = [
    dict(slug="consort-flow", guide="CONSORT", item="Item 13 – Participant flow",
         title="Can readers trace every patient in your trial?",
         title_highlight="every patient",
         hook="CONSORT item 13: if readers cannot trace every randomised patient, your results are hard to trust.",
         slides=[("What the item asks", "Report how many people were assessed, randomised, treated, lost and "
                  "analysed, in each group: a flow diagram is strongly recommended."),
                 ("Why it matters", "Losses after randomisation can bias results. A trial that randomised 120 "
                  "but analysed 80 has a story the reader must see."),
                 ("How to comply", "Build the flow diagram from your screening log before writing: numbers at "
                  "every stage, with reasons for every exclusion.")],
         takeaway="Report the flow of all participants, stage by stage, with reasons for every exclusion.",
         takeaway_highlight="stage by stage",
         hashtags=["#CONSORT", "#ClinicalTrials", "#ReportingGuidelines"], category="Reporting & publication"),
    dict(slug="consort-outcomes", guide="CONSORT", item="Item 6a – Outcomes",
         title="Primary outcome: defined before, not after",
         title_highlight="before",
         hook="CONSORT item 6a: your primary outcome must be fully pre-specified: measure, metric and time point.",
         slides=[("What the item asks", "Define every pre-specified primary and secondary outcome: the measure, "
                  "how it was assessed, and exactly when."),
                 ("Why it matters", "Vague outcomes invite switching after the data are in, one of the "
                  "best-documented sources of reporting bias."),
                 ("How to comply", "Write each outcome as: instrument + metric + aggregation + time point. "
                  "Example: pain on a 0–10 scale, mean change at 12 weeks.")],
         takeaway="An outcome is pre-specified only if measure, metric and time point are written down first.",
         takeaway_highlight="written down first",
         hashtags=["#CONSORT", "#ClinicalTrials", "#Endpoints"], category="Endpoints & outcomes"),
    dict(slug="prisma-search", guide="PRISMA", item="Item 7 – Search strategy",
         title="Could a colleague rerun your literature search?",
         title_highlight="rerun your literature search",
         hook="PRISMA item 7: a systematic review search must be reported so fully that anyone can repeat it.",
         slides=[("What the item asks", "Present the full search strategy for every database and register, "
                  "including filters and limits, exactly as run."),
                 ("Why it matters", "The search defines the evidence base. If it cannot be repeated, the review "
                  "cannot be checked or updated."),
                 ("How to comply", "Export each database's full query string into an appendix, with the date of "
                  "the search and any language or date limits.")],
         takeaway="Report every search string, database, filter and date: reproducible or it is not systematic.",
         takeaway_highlight="reproducible",
         hashtags=["#PRISMA", "#SystematicReview", "#EvidenceSynthesis"], category="Reporting & publication"),
    dict(slug="strobe-bias", guide="STROBE", item="Item 9 – Bias",
         title="Observational study? Name your biases in print",
         title_highlight="Name your biases",
         hook="STROBE item 9 asks observational studies to state what was done about bias, not to pretend there is none.",
         slides=[("What the item asks", "Describe any efforts to address potential sources of bias: selection, "
                  "information and confounding."),
                 ("Why it matters", "Every observational design has bias. Readers judge your results by how "
                  "openly you handled it, not by silence."),
                 ("How to comply", "List your 3 most likely biases, then state the design or analysis step "
                  "taken for each: restriction, matching, adjustment, sensitivity analysis.")],
         takeaway="State each likely source of bias and what you did about it: silence reads as blindness.",
         takeaway_highlight="what you did about it",
         hashtags=["#STROBE", "#Epidemiology", "#BiasInResearch"], category="Bias & confounding"),
    dict(slug="spirit-protocol", guide="SPIRIT", item="Item 20a – Statistical methods",
         title="Your analysis plan belongs in the protocol",
         title_highlight="in the protocol",
         hook="SPIRIT item 20a: the statistical methods for primary and secondary outcomes go in the protocol, before data exist.",
         slides=[("What the item asks", "The trial protocol must state the statistical methods for analysing "
                  "primary and secondary outcomes, in advance."),
                 ("Why it matters", "An analysis chosen after seeing the data can always be chosen to please. "
                  "Pre-specification is the only antidote."),
                 ("How to comply", "Write the model, the comparison, the population (e.g. intention-to-treat) "
                  "and how missing data are handled, in the protocol and the registry.")],
         takeaway="Pre-specify model, population and missing-data handling in the protocol, not in the paper.",
         takeaway_highlight="Pre-specify",
         hashtags=["#SPIRIT", "#ClinicalTrials", "#StudyProtocol"], category="Study design"),
    dict(slug="prisma-rob", guide="PRISMA", item="Item 11 – Risk of bias",
         title="A review is only as strong as its worst study",
         title_highlight="worst study",
         hook="PRISMA item 11: say how you assessed risk of bias in every included study, with which tool and how many reviewers.",
         slides=[("What the item asks", "Specify the methods used to assess risk of bias in the included "
                  "studies: the tool, the process, the number of reviewers."),
                 ("Why it matters", "Pooling biased studies gives a precise answer to the wrong question. "
                  "Readers need to see which results rest on weak evidence."),
                 ("How to comply", "Use a recognised tool (e.g. RoB 2 for trials, ROBINS-I for non-randomised "
                  "studies), with 2 independent reviewers and a tie-breaking rule.")],
         takeaway="Assess risk of bias with a named tool and two reviewers, and report it per study.",
         takeaway_highlight="named tool",
         hashtags=["#PRISMA", "#RiskOfBias", "#SystematicReview"], category="Critical appraisal"),
    dict(slug="consort-sample", guide="CONSORT", item="Item 7a – Sample size",
         title="Show the maths behind your sample size",
         title_highlight="sample size",
         hook="CONSORT item 7a: report how the sample size was determined, with every assumption on the table.",
         slides=[("What the item asks", "Explain how the sample size was determined: expected effect, "
                  "variability, alpha, power and allowance for drop-out."),
                 ("Why it matters", "Without the assumptions, readers cannot tell an honest estimate from a "
                  "number reverse-engineered to fit the budget."),
                 ("How to comply", "Report all inputs so the calculation can be redone, e.g.: 80% power, "
                  "alpha 0.05, expected difference 5 points (SD 12), 15% drop-out.")],
         takeaway="A sample size is reported only when someone else can redo the calculation.",
         takeaway_highlight="redo the calculation",
         hashtags=["#CONSORT", "#SampleSize", "#Biostatistics"], category="Sample size & power"),
    dict(slug="strobe-numbers", guide="STROBE", item="Item 13 – Participants",
         title="From eligible to analysed: show the drop at each step",
         title_highlight="each step",
         hook="STROBE item 13: report the numbers at each stage of your observational study, from eligible to analysed.",
         slides=[("What the item asks", "Report numbers at each stage: potentially eligible, examined, "
                  "confirmed eligible, included, followed up, analysed."),
                 ("Why it matters", "If 1,000 were eligible and 150 analysed, selection may drive the result. "
                  "The reader can only judge if the numbers are visible."),
                 ("How to comply", "Add a flow diagram with reasons for non-participation at each stage; "
                  "STROBE explicitly recommends it.")],
         takeaway="Report participant numbers and losses at every stage, with reasons: a diagram helps.",
         takeaway_highlight="every stage",
         hashtags=["#STROBE", "#Epidemiology", "#CohortStudy"], category="Reporting & publication"),
    dict(slug="consort-random", guide="CONSORT", item="Items 8–9 – Randomisation",
         title="“Randomised” is a method, not a magic word",
         title_highlight="not a magic word",
         hook="CONSORT items 8–9: report who generated the random sequence, how, and how allocation was concealed.",
         slides=[("What the item asks", "Describe the method used to generate the random sequence and the "
                  "mechanism used to conceal it until assignment."),
                 ("Why it matters", "Trials with unclear concealment tend to overestimate effects: foreseeable "
                  "allocation lets selection back in."),
                 ("How to comply", "Name the generator (e.g. computer-generated blocks) and the concealment "
                  "mechanism (e.g. central web-based assignment), and who did what.")],
         takeaway="Report sequence generation and allocation concealment separately: both, by name.",
         takeaway_highlight="both, by name",
         hashtags=["#CONSORT", "#Randomization", "#ClinicalTrials"], category="Randomization & blinding"),
    dict(slug="prisma-protocol", guide="PRISMA", item="Item 24a – Registration",
         title="Register the review before you run it",
         title_highlight="before",
         hook="PRISMA item 24a: report where your systematic review was registered, or state that it was not.",
         slides=[("What the item asks", "Provide registration information for the review, including the "
                  "register name and number, or state that it was not registered."),
                 ("Why it matters", "Registration lets readers compare what was planned with what was "
                  "reported, and protects against silent changes of question."),
                 ("How to comply", "Register on PROSPERO or OSF before screening starts, and cite the "
                  "registration number in the abstract and methods.")],
         takeaway="Register the protocol before screening and cite the number: unregistered means unverifiable.",
         takeaway_highlight="before screening",
         hashtags=["#PRISMA", "#OpenScience", "#SystematicReview"], category="Research ethics"),
    dict(slug="strobe-confounding", guide="STROBE", item="Item 16 – Main results",
         title="Crude and adjusted: report both numbers",
         title_highlight="both numbers",
         hook="STROBE item 16: give unadjusted and confounder-adjusted estimates, and say which confounders you adjusted for and why.",
         slides=[("What the item asks", "Report unadjusted estimates and, if used, confounder-adjusted "
                  "estimates with their precision, and which confounders were included."),
                 ("Why it matters", "The gap between crude and adjusted results tells readers how much "
                  "confounding was at play, and whether adjustment is plausible."),
                 ("How to comply", "Present both estimates with 95% confidence intervals side by side, and "
                  "justify each confounder, ideally from a causal diagram.")],
         takeaway="Show crude and adjusted estimates with confidence intervals, and justify every confounder.",
         takeaway_highlight="crude and adjusted",
         hashtags=["#STROBE", "#Confounding", "#Epidemiology"], category="Statistics"),
    dict(slug="cosmin-choice", guide="COSMIN", item="Instrument selection",
         title="Picking a questionnaire? Check it was tested for your use",
         title_highlight="tested for your use",
         hook="COSMIN: an outcome measure is only as good as the evidence for it in your population and purpose.",
         slides=[("What the item asks", "Select patient-reported outcome measures on evidence of their "
                  "measurement properties in a population like yours."),
                 ("Why it matters", "A questionnaire validated in chronic pain may measure something else in "
                  "post-surgical patients: scores move, meaning does not follow."),
                 ("How to comply", "Before adopting an instrument, check a COSMIN-based review for evidence on "
                  "content validity and reliability in your target population.")],
         takeaway="Choose outcome measures on evidence in your population, not on how often they are cited.",
         takeaway_highlight="in your population",
         hashtags=["#COSMIN", "#PROMs", "#OutcomeMeasures"], category="Endpoints & outcomes"),
]


def checklist_post(posted):
    """Il prossimo appuntamento della rubrica Checklist (una voce mai uscita), oppure None se sono finite.
    Post completo e deterministico: niente AI, niente quota."""
    done = {p.get("id") for p in posted}
    item = next((i for i in ITEMS if f"checklist-{i['slug']}" not in done), None)
    if not item:
        return None
    cite = CITE[item["guide"]]
    slides = [{"heading": h, "body": b, "image_prompt": "", "photo_query": "", "highlight": "",
               "source": cite} for h, b in item["slides"]]
    caption = (f"{item['hook']}\n\nOne reporting-checklist item at a time, every Thursday: what it asks, why it "
               f"matters, and how to comply in practice.\nThis week: {item['guide']}, {item['item']}.\n"
               "Which checklist item do you see ignored most often?")
    return {"id": f"checklist-{item['slug']}", "kind": None, "rubric": "Checklist",
            "title": item["title"], "title_highlight": item["title_highlight"],
            "category": item["category"], "slides": slides,
            "takeaway": item["takeaway"], "takeaway_highlight": item["takeaway_highlight"],
            "references": [REFS[item["guide"]]], "caption": caption, "hashtags": item["hashtags"],
            "source": "Rubrica Checklist", "source_hint": f"{item['guide']} {item['item']}", "no_images": True}


# ---------------------------------------------------------------- Before you apply (venerdì, ogni due settimane)
TIPS = [
    ("Read the full call", "Eligibility details hide in annexes and footnotes, not in the summary page."),
    ("Start the budget early", "Finance offices usually need 2–3 weeks before the submission deadline."),
    ("Mirror the criteria", "Match every aim to an evaluation criterion: reviewers score against the grid."),
    ("Ask the programme officer", "Specific questions get specific answers, and they are often decisive."),
    ("Test your abstract", "Have a colleague outside your field read it: reviewers rarely share your niche."),
    ("Check the formatting rules", "Page limits, fonts and attachments disqualify more proposals than science does."),
    ("Line up support letters now", "Partners and co-applicants are slowest exactly when deadlines cluster."),
    ("Register on the portal early", "Submission-system credentials can take days: a week before is the minimum."),
    ("Reuse your data plan", "Funders ask for the same core data-management sections: keep a living template."),
]


def apply_tips(post):
    """Tre consigli di candidatura (scelti in modo stabile dall'id del bando) come slide extra «Before you apply»."""
    seed = sum(ord(c) for c in post.get("id", ""))
    picked = [TIPS[(seed + k * 3) % len(TIPS)] for k in range(3)]
    seen, rows = set(), []
    for t, b in picked:
        if t not in seen:
            seen.add(t)
            rows.append((t, b))
    for t, b in TIPS:                      # se il seed ha pescato doppioni, completa con i successivi
        if len(rows) == 3:
            break
        if t not in seen:
            seen.add(t)
            rows.append((t, b))
    post["rubric"] = "Before you apply"
    post["extra_facts"] = {"label": "BEFORE YOU APPLY", "rows": rows}
    post["caption"] += "\n\nBefore you apply: three practical tips in the last slide."
    return post


# ---------------------------------------------------------------- Career Path (primo lunedì del mese)
GLOSSARY = {
    "Post-doc": "Fixed-term research role after the PhD, usually 1–3 years, tied to a funded project and a PI.",
    "Research assistant / associate": "Project staff role, from bachelor's to PhD level: data collection and "
                                      "analysis for a funded study, with little independent agenda.",
    "Research fellow": "Researcher on a fellowship or project, often with an own funding line and growing independence.",
    "Faculty": "Professor-track role mixing research and teaching: tenure-track in the US, lecturer to professor "
               "in the UK, RTD then associate in Italy.",
    "Clinical academic & fellowship": "Combines clinical duties with protected research time; usually requires a "
                                      "health-professional qualification in that country.",
    "PhD position": "Funded doctoral post: a salary or stipend to train by doing research, typically 3–4 years.",
}


def career_path(post):
    """Etichetta Career Path e slide-glossario dei ruoli presenti nella raccolta della settimana."""
    types = []
    for j in post.get("jobs", []):
        if j.get("type") in GLOSSARY and j["type"] not in types:
            types.append(j["type"])
    rows = [(t, GLOSSARY[t]) for t in types[:5]] or list(GLOSSARY.items())[:4]
    post["rubric"] = "Career Path"
    post["facts_label"] = "HOW TO READ THE ADS"
    post["facts"] = rows
    post["caption"] += "\n\nCareer Path: what each role actually means, in the last slide."
    return post


def log_state():
    """Per il resoconto: voci Checklist già uscite."""
    try:
        posted = json.loads((ROOT / "posted_log.json").read_text(encoding="utf-8"))
    except OSError:
        posted = []
    return [p["id"] for p in posted if str(p.get("id", "")).startswith("checklist-")]
