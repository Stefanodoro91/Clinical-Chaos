"""Strumenti per disegno di studio, allineati ai livelli della piramide delle evidenze (site_parts/evidence_pyramid.html).

Unica fonte per la tabella ampliata della pagina metodologia (methodology.tools_block) e per la sezione «Tools» delle
schede della piramide (methodology.pyramid_block). Unisce le tabelle «Strumenti design, reporting e critical
appraisal» di Stefano con le varianti della piramide; voci superate aggiornate (CONSORT/SPIRIT 2025, CONSORT-ROUTINE
per i cmRCT, CONSORT-DEFINE per la dose-escalation). Ogni strumento è (nome, url) o (nome, None) quando è un metodo
senza una pagina ufficiale. Link verificati con tools/link_probe.py (GitHub Actions, modalità «links»)."""

# ---- link ufficiali (uno per strumento, riusati nelle righe) ----
SPIRIT25 = ("SPIRIT 2025", "https://doi.org/10.1136/bmj-2024-081477")
CONSORT25 = ("CONSORT 2025", "https://doi.org/10.1136/bmj-2024-081123")
ROB2 = ("RoB 2", "https://www.riskofbias.info/welcome/rob-2-0-tool")
ROBINS_I = ("ROBINS-I", "https://www.riskofbias.info/welcome/home/current-version-of-robins-i")
ROBINS_E = ("ROBINS-E", "https://www.riskofbias.info/welcome/robins-e-tool")
GRADE = ("GRADE", "https://www.gradeworkinggroup.org/")
STROBE = ("STROBE", "https://www.strobe-statement.org/")
TREND = ("TREND", "https://doi.org/10.2105/AJPH.94.3.361")
PRISMA_P = ("PRISMA-P", "https://www.prisma-statement.org/protocols")
PROSPERO = ("PROSPERO", "https://www.crd.york.ac.uk/prospero/")
COCHRANE_HB = ("Cochrane Handbook", "https://training.cochrane.org/handbook")
PRISMA = ("PRISMA 2020", "https://www.prisma-statement.org/")
AMSTAR2 = ("AMSTAR 2", "https://amstar.ca/")
ROBIS = ("ROBIS", "https://www.bristol.ac.uk/population-health-sciences/projects/robis/")
NOS = ("Newcastle-Ottawa Scale", "https://www.ohri.ca/programs/clinical_epidemiology/oxford.asp")
JBI = ("JBI checklist", "https://jbi.global/critical-appraisal-tools")
NIH_PP = ("NIH pre-post tool", "https://www.nhlbi.nih.gov/health-topics/study-quality-assessment-tools")
DAG = ("Causal diagrams (DAGs)", None)

# ---- righe: livello della piramide (0 = vertice) → disegno → (progettazione, reporting, valutazione critica) ----
ROWS = [
    # 1 · Meta-analysis and guidelines
    (0, "Pairwise meta-analysis",
     [PRISMA_P, PROSPERO, COCHRANE_HB], [PRISMA], [AMSTAR2, ROBIS, ("GRADE (certainty)", GRADE[1])]),
    (0, "Network meta-analysis (NMA)",
     [PRISMA_P, PROSPERO], [("PRISMA-NMA", "https://doi.org/10.7326/M14-2385")],
     [("CINeMA", "https://cinema.ispm.unibe.ch/"), AMSTAR2]),
    (0, "Individual patient data (IPD) meta-analysis",
     [PRISMA_P, PROSPERO], [("PRISMA-IPD", "https://doi.org/10.1001/jama.2015.3656")], [AMSTAR2, ROBIS]),
    (0, "Clinical practice guideline",
     [("GRADE Evidence to Decision", GRADE[1])], [("RIGHT", "https://www.right-statement.org/")],
     [("AGREE II", "https://www.agreetrust.org/")]),
    # 2 · Systematic review
    (1, "Systematic review", [PRISMA_P, PROSPERO, COCHRANE_HB], [PRISMA], [AMSTAR2, ROBIS]),
    (1, "Scoping review",
     [("JBI scoping guidance", "https://doi.org/10.11124/JBIES-20-00167")],
     [("PRISMA-ScR", "https://doi.org/10.7326/M18-0850")], [("Not formally appraised", None)]),
    # 3 · RCT (tabella di Stefano + estensioni CONSORT delle varianti della piramide)
    (2, "Parallel-group RCT",
     [SPIRIT25, ("Sample size calculation", None), ("Allocation concealment", None), ("Randomisation software", None)],
     [CONSORT25], [ROB2, ("GRADE (across trials)", GRADE[1])]),
    (2, "Crossover RCT",
     [("Washout planning", None), ("Sequence randomisation", None), ("Carry-over assessment", None)],
     [("CONSORT crossover", "https://doi.org/10.1136/bmj.l4378")],
     [("RoB 2 crossover", "https://www.riskofbias.info/welcome/rob-2-0-tool/rob-2-for-crossover-trials")]),
    (2, "Cluster RCT",
     [("Intracluster correlation in the sample size", None)],
     [("CONSORT cluster", "https://doi.org/10.1136/bmj.e5661")],
     [("RoB 2 cluster", "https://www.riskofbias.info/welcome/rob-2-0-tool/rob-2-for-cluster-randomized-trials")]),
    (2, "Stepped-wedge RCT",
     [("Staggered crossover schedule", None)],
     [("CONSORT stepped-wedge", "https://doi.org/10.1136/bmj.k1614")],
     [("RoB 2 cluster", "https://www.riskofbias.info/welcome/rob-2-0-tool/rob-2-for-cluster-randomized-trials")]),
    (2, "Factorial RCT",
     [("Interaction in the sample size", None)],
     [("CONSORT factorial", "https://pubmed.ncbi.nlm.nih.gov/38051324/")], [ROB2]),
    (2, "Platform / adaptive trial",
     [("Pre-specified adaptation rules", None), ("Simulation of operating characteristics", None)],
     [("CONSORT ACE", "https://doi.org/10.1136/bmj.m115")], [ROB2]),
    (2, "Non-inferiority / equivalence trial",
     [("Justified margin", None)],
     [("CONSORT non-inferiority", "https://doi.org/10.1001/jama.2012.87802")], [ROB2]),
    (2, "Pragmatic RCT",
     [("PRECIS-2", "https://www.precis-2.org/"), ("Real-world eligibility", None), ("Flexible delivery", None)],
     [("CONSORT pragmatic", "https://doi.org/10.1136/bmj.a2390")],
     [ROB2, ("PRECIS-2 (applicability)", "https://doi.org/10.1136/bmj.h2147")]),
    (2, "Zelen design (randomised consent)",
     [("Zelen, 1979", "https://doi.org/10.1056/NEJM197905313002203"), ("Consent pathway mapping", None),
      ("Ethics review of the consent model", None)],
     [("CONSORT 2025, consent pathway stated", CONSORT25[1])],
     [("RoB 2 (selection and consent bias)", ROB2[1])]),
    (2, "cmRCT (trials within cohorts)",
     [("Relton et al., 2010", "https://doi.org/10.1136/bmj.c1066"), ("Cohort and outcome registry", None),
      ("Embedded randomisation", None)],
     [("CONSORT-ROUTINE", "https://doi.org/10.1136/bmj.n857")], [("RoB 2 (selection bias)", ROB2[1])]),
    # 4 · Non-randomised controlled trial
    (3, "Quasi-experimental study",
     [("Interrupted time series design", None), DAG, ("Controlled before-after design", None)],
     [TREND], [ROBINS_I]),
    (3, "Matched controlled study",
     [("Propensity score methods", None), ("Covariate balance diagnostics", None)], [STROBE], [ROBINS_I]),
    (3, "Historically controlled trial",
     [("Historical data harmonisation", None), ("Time-trend bias control", None)], [STROBE], [ROBINS_I]),
    (3, "Geographically controlled study",
     [("Cluster definition", None), ("Spatial analysis", None)], [STROBE],
     [("ROBINS-I (cluster bias)", ROBINS_I[1])]),
    # 5 · Uncontrolled trial
    (4, "Single-arm trial",
     [("Simon two-stage design", "https://doi.org/10.1016/0197-2456(89)90015-9"), ("Feasibility criteria", None)],
     [("Non-randomised pilot guideline", "https://doi.org/10.1186/s40814-019-0499-1"),
      ("CONSORT pilot (randomised pilots)", "https://doi.org/10.1136/bmj.i5239")],
     [NIH_PP, ("ROBINS-I (if comparing)", ROBINS_I[1])]),
    (4, "Pre-post (before-after) study",
     [("Repeated measures planning", None), ("Secular trend control", None)],
     [("TREND (planned intervention)", TREND[1]), ("STROBE (routine data)", STROBE[1])], [NIH_PP]),
    (4, "Dose-escalation trial",
     [("3+3 design", None), ("Continual reassessment method", "https://doi.org/10.2307/2531628"),
      ("SPIRIT-DEFINE", "https://doi.org/10.1136/bmj-2023-076386")],
     [("CONSORT-DEFINE", "https://pubmed.ncbi.nlm.nih.gov/37863501/")],
     [("No dedicated tool: check CONSORT-DEFINE items", None)]),
    # 6 · Cohort
    (5, "Cohort study",
     [DAG, ("Target trial emulation", "https://doi.org/10.1093/aje/kwv254")], [STROBE], [NOS, ROBINS_E]),
    (5, "Registry-based cohort",
     [("Data linkage and validation", None)],
     [("RECORD", "https://doi.org/10.1371/journal.pmed.1001885")], [NOS, ROBINS_E]),
    # 7 · Cross-sectional
    (6, "Analytical cross-sectional study",
     [("Representative sampling frame", None)],
     [STROBE, ("CHERRIES (online surveys)", "https://doi.org/10.2196/jmir.6.3.e34")],
     [("AXIS", "https://doi.org/10.1136/bmjopen-2016-011458"), JBI]),
    (6, "Diagnostic accuracy study",
     [("Reference standard", None), ("Consecutive patient spectrum", None)],
     [("STARD 2015", "https://doi.org/10.1136/bmj.h5527")],
     [("QUADAS-2", "https://doi.org/10.7326/0003-4819-155-8-201110180-00009")]),
    # 8 · Case-control
    (7, "Case-control study",
     [("Control selection", None), ("Matching", None)], [STROBE], [NOS, JBI]),
    # 9 · Case series
    (8, "Case series",
     [("Consecutive inclusion", None), ("Pre-defined outcomes", None)],
     [("PROCESS (surgical)", "https://pubmed.ncbi.nlm.nih.gov/37988417/")], [JBI]),
    # 10 · Case report
    (9, "Case report", [("Patient consent", None)], [("CARE", "https://www.care-statement.org/")], [JBI]),
    # 11 · Editorials, opinions and ideas
    (10, "Narrative review", [("Stated scope", None)],
     [("SANRA", "https://doi.org/10.1186/s41073-019-0064-8")], [("JBI text and opinion", JBI[1])]),
    # 12 · Animal research
    (11, "In vivo efficacy study",
     [("PREPARE", "https://norecopa.no/prepare")], [("ARRIVE 2.0", "https://arriveguidelines.org/")],
     [("SYRCLE risk of bias", "https://doi.org/10.1186/1471-2288-14-43")]),
    # 13 · In vitro research
    (12, "Cell-based assay",
     [("Randomised, blinded plate layout", None), ("Biological replicates", None)],
     [("MDAR checklist", "https://doi.org/10.1073/pnas.2103238118")],
     [("SciRAP (in vitro)", "https://www.scirap.org/")]),
]

# Fuori dalla piramide: studi sugli strumenti di misura (il «mondo COSMIN»).
COSMIN = {
    "design": [("COSMIN Study Design checklist", "https://www.cosmin.nl/")],
    "report": [("COSMIN reporting guideline (PROMs)", "https://pubmed.ncbi.nlm.nih.gov/33818733/"),
               ("PRISMA-COSMIN for OMIs (reviews)", "https://pubmed.ncbi.nlm.nih.gov/38977535/")],
    "appraise": [("COSMIN Risk of Bias checklist", "https://doi.org/10.1007/s11136-017-1765-4"),
                 ("COSMIN guideline for reviews of PROMs", "https://doi.org/10.1007/s11136-018-1798-3")],
    "taxonomy": ("Mokkink et al., 2010", "https://doi.org/10.1016/j.jclinepi.2010.02.006"),
    # tassonomia COSMIN: 3 domini, 9 proprietà di misura
    "domains": [("Reliability", ["Internal consistency", "Reliability", "Measurement error"]),
                ("Validity", ["Content validity", "Structural validity", "Hypotheses testing",
                              "Cross-cultural validity", "Criterion validity"]),
                ("Responsiveness", ["Responsiveness"])],
}

# Per ogni disegno: strumenti generali.
EVERY = [("EQUATOR library", "https://www.equator-network.org/library/"),
         ("CASP checklists", "https://casp-uk.net/casp-tools-checklists/"), JBI]


def all_links():
    """Ogni (nome, url) usato: per la verifica dei link."""
    out = []
    for _, _, *cols in ROWS:
        for col in cols:
            out += [t for t in col if t[1]]
    for k in ("design", "report", "appraise"):
        out += COSMIN[k]
    out += [COSMIN["taxonomy"]] + EVERY
    seen, uniq = set(), []
    for name, url in out:
        if url not in seen:
            seen.add(url)
            uniq.append((name, url))
    return uniq
