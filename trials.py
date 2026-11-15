"""Pagina «Find your trial»: per i pazienti che cercano uno studio clinico in corso a cui partecipare.

Il sito non ospita né seleziona studi: la pagina costruisce le ricerche sui registri pubblici ufficiali
(ClinicalTrials.gov, registro UE CTIS, ISRCTN, portale OMS ICTRP) e spiega cosa chiedere prima di contattare uno studio.
Nessun dato lascia il browser: la ricerca è solo un link al registro.

Formati di ricerca (verificati sul pacchetto R «ctrdata», che genera le query dei registri):
  ClinicalTrials.gov  https://clinicaltrials.gov/search?cond=…&country=…&aggFilters=status:not rec
                      (status: «not» = non ancora in reclutamento, «rec» = in reclutamento)
  CTIS (UE)           https://euclinicaltrials.eu/ctis-public/search#searchCriteria={"containAll":"…","status":[2,3,4,6,7]}
                      (status 2,3,4,6,7 = studi in corso)
  ISRCTN              https://www.isrctn.com/search?q=…
  WHO ICTRP           https://trialsearch.who.int/  (nessun link di ricerca diretto: si apre il modulo)
"""

from html import escape

import grants

TRIALS_ACCENT = "#F2698E"     # colore della funzione «Find your trial» (rosa corallo)

COUNTRIES = ["Italy", "France", "Germany", "Spain", "Switzerland", "United Kingdom", "Austria", "Belgium",
             "Netherlands", "Portugal", "Greece", "Poland", "Sweden", "Denmark", "Ireland", "United States", "Canada",
             "Australia"]

PAGE = """<!doctype html>
<html lang="en">
<head>
<!-- Google Analytics 4 -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-6ZCXVHNT2"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-6ZCXVHNT2');
</script>
<!-- End Google Analytics 4 -->
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Find your trial · {brand}</title>
<meta name="description" content="Looking for a clinical trial to take part in? Search the official public registries of ongoing studies and learn what to ask before you contact a study team.">
{og}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  :root {{ --bg: {bg}; --card: #15304A; --text: #FFFFFF; --muted: {muted}; --soft: {soft}; --accent: {accent}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); font-family: Inter, system-ui, sans-serif; line-height: 1.5; }}
  .bar {{ height: 6px; background: var(--accent); }}
  main {{ max-width: 680px; margin: 0 auto; padding: 28px 16px 48px; }}
  .switch {{ display: inline-block; color: var(--text); text-decoration: none; font-size: 14px; font-weight: 600;
            border: 1px solid var(--muted); border-radius: 999px; padding: 7px 14px; margin: 0 6px 18px 0; }}
  .switch:hover {{ border-color: var(--soft); }}
  .badge {{ display: inline-block; background: var(--accent); color: #0A0A0A; font-weight: 800; font-size: 13px;
           letter-spacing: .06em; padding: 6px 14px; border-radius: 999px; }}
  h1 {{ font-size: clamp(26px, 6vw, 32px); font-weight: 800; margin: 14px 0 8px; line-height: 1.15; text-wrap: balance; }}
  h2 {{ font-size: 20px; font-weight: 800; margin: 34px 0 12px; line-height: 1.25; }}
  .intro {{ color: var(--soft); margin: 0 0 22px; font-size: 16px; max-width: 62ch; }}
  .card {{ background: var(--card); border-radius: 18px; padding: 20px; }}
  form {{ display: grid; gap: 14px; }}
  label {{ display: grid; gap: 6px; font-size: 12px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
          color: var(--muted); }}
  label small {{ text-transform: none; letter-spacing: 0; font-weight: 500; color: var(--soft); font-size: 13px; }}
  input[type=text], select {{ font: 500 16px Inter, system-ui, sans-serif; color: var(--text); background: var(--bg);
                             border: 1px solid var(--muted); border-radius: 10px; padding: 11px 12px; width: 100%; }}
  input:focus, select:focus {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
  .row2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
  @media (max-width: 520px) {{ .row2 {{ grid-template-columns: 1fr; }} }}
  .check {{ display: flex; align-items: flex-start; gap: 10px; text-transform: none; letter-spacing: 0; font-size: 15px;
           font-weight: 500; color: var(--soft); }}
  .check input {{ width: 18px; height: 18px; margin-top: 3px; accent-color: var(--accent); flex: none; }}
  .go {{ background: var(--accent); color: #0A0A0A; border: 0; border-radius: 999px; padding: 13px 20px;
        font: 800 16px Inter, system-ui, sans-serif; cursor: pointer; justify-self: start; }}
  .results {{ margin-top: 18px; display: grid; gap: 10px; }}
  .results[hidden] {{ display: none; }}
  .results p {{ margin: 0; color: var(--soft); font-size: 14px; }}
  .res {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; text-decoration: none;
         color: var(--text); border: 1px solid var(--accent); border-radius: 12px; padding: 12px 14px; font-weight: 700; }}
  .res span {{ color: var(--soft); font-weight: 500; font-size: 13px; }}
  .res:hover {{ background: rgba(242, 105, 142, .12); }}
  .regs {{ display: grid; gap: 12px; }}
  .reg {{ background: var(--card); border-radius: 14px; padding: 16px 18px; border-left: 4px solid var(--accent); }}
  .reg h3 {{ margin: 0 0 4px; font-size: 16px; }}
  .reg h3 a {{ color: var(--text); }}
  .reg p {{ margin: 0; color: var(--soft); font-size: 14px; }}
  .reg .id {{ color: var(--muted); font-size: 13px; margin-top: 6px; }}
  ol.steps {{ margin: 0; padding: 0; list-style: none; counter-reset: s; display: grid; gap: 12px; }}
  ol.steps li {{ counter-increment: s; position: relative; padding-left: 42px; color: var(--soft); font-size: 15px; }}
  ol.steps li::before {{ content: counter(s); position: absolute; left: 0; top: -1px; width: 28px; height: 28px;
                        border-radius: 50%; background: var(--accent); color: #0A0A0A; font-weight: 800; font-size: 14px;
                        display: grid; place-items: center; }}
  ol.steps b {{ color: var(--text); }}
  dl.words {{ margin: 0; display: grid; gap: 10px; }}
  dl.words div {{ background: var(--card); border-radius: 12px; padding: 12px 16px; }}
  dl.words dt {{ font-weight: 800; font-size: 15px; }}
  dl.words dd {{ margin: 2px 0 0; color: var(--soft); font-size: 14px; }}
  .note {{ border: 1px solid var(--muted); border-radius: 14px; padding: 14px 16px; color: var(--soft); font-size: 14px;
          margin-top: 30px; }}
  .note b {{ color: var(--text); }}
  footer {{ color: var(--muted); font-size: 13px; margin-top: 30px; }}
  footer a {{ color: var(--accent); }}
</style>
</head>
<body>
<div class="bar"></div>
<main>
  <a class="switch" href="index.html">&larr; Home</a><a class="switch" href="calls.html">Funding calls &rarr;</a><a class="switch" href="positions.html">Academic positions &rarr;</a><a class="switch" href="methodology.html">Design, Reporting &amp; Appraisal &rarr;</a><a class="switch" href="science.html">Latest Science &rarr;</a><a class="switch" href="rss.html">RSS &rarr;</a><br>
  <span class="badge">FIND YOUR TRIAL</span>
  <h1>Find a clinical trial that is looking for volunteers</h1>
  <p class="intro">Clinical trials test new treatments, devices and rehabilitation programmes, and many of them are
  looking for patients and healthy volunteers. Search the official public registries of ongoing studies, then talk
  about what you find with your doctor.</p>

  <section class="card" aria-labelledby="search-title">
    <form id="tf" action="https://clinicaltrials.gov/search" method="get" target="_blank" rel="noopener">
      <label id="search-title">Condition or disease
        <input type="text" name="cond" required maxlength="120" autocomplete="off"
               placeholder="e.g. stroke, multiple sclerosis, knee osteoarthritis">
      </label>
      <div class="row2">
        <label>Country <small>(where you could take part)</small>
          <select name="country"><option value="">Any country</option>{countries}</select>
        </label>
        <label>Keyword <small>(optional: a treatment, e.g. rehabilitation)</small>
          <input type="text" name="term" maxlength="120" autocomplete="off">
        </label>
      </div>
      <label class="check"><input type="checkbox" name="soon" checked>
        Show only studies that are recruiting or will start recruiting soon</label>
      <input type="hidden" name="aggFilters" value="status:not rec">
      <button class="go" type="submit">Search ongoing trials</button>
    </form>
    <div class="results" id="results" hidden aria-live="polite">
      <p>Open your search in each registry (new tab). The same study can appear in more than one.</p>
      <a class="res" id="r-ctg" target="_blank" rel="noopener" href="https://clinicaltrials.gov/">ClinicalTrials.gov <span>worldwide &rarr;</span></a>
      <a class="res" id="r-ctis" target="_blank" rel="noopener" href="https://euclinicaltrials.eu/ctis-public/search">EU Clinical Trials (CTIS) <span>medicines, EU/EEA &rarr;</span></a>
      <a class="res" id="r-isrctn" target="_blank" rel="noopener" href="https://www.isrctn.com/">ISRCTN <span>all study types &rarr;</span></a>
      <a class="res" target="_blank" rel="noopener" href="https://trialsearch.who.int/">WHO trial search <span>type your condition there &rarr;</span></a>
    </div>
  </section>

  <h2>Where the studies are listed</h2>
  <div class="regs">
    <div class="reg"><h3><a href="https://clinicaltrials.gov/" target="_blank" rel="noopener">ClinicalTrials.gov</a></h3>
      <p>The largest public registry, run by the US National Library of Medicine. It lists studies from many countries,
      not only the United States, including trials of medicines, devices, surgery and rehabilitation.</p>
      <p class="id">Study code looks like: NCT01234567</p></div>
    <div class="reg"><h3><a href="https://euclinicaltrials.eu/ctis-public/search" target="_blank" rel="noopener">EU Clinical Trials Information System (CTIS)</a></h3>
      <p>The official European Union register, run by the European Medicines Agency. It covers clinical trials of
      medicines in the EU and EEA. Studies of devices, surgery or rehabilitation are usually not here.</p>
      <p class="id">Study code looks like: 2024-512345-12-00</p></div>
    <div class="reg"><h3><a href="https://www.isrctn.com/" target="_blank" rel="noopener">ISRCTN registry</a></h3>
      <p>A primary registry recognised by the World Health Organization, based in the United Kingdom. It accepts
      studies of any type from any country.</p>
      <p class="id">Study code looks like: ISRCTN12345678</p></div>
    <div class="reg"><h3><a href="https://trialsearch.who.int/" target="_blank" rel="noopener">WHO International Clinical Trials Registry Platform</a></h3>
      <p>One search across many national registries at once, including registries in countries not covered above.
      Useful to double-check that you have not missed a study.</p></div>
  </div>

  <h2>Before you contact a study</h2>
  <ol class="steps">
    <li><b>Talk to your doctor first.</b> Bring the study code: your doctor can tell you whether the study fits your
      situation and your current treatment.</li>
    <li><b>Read who can take part.</b> Each study lists its eligibility criteria: who can join (inclusion) and who
      cannot (exclusion), such as age, diagnosis or other treatments.</li>
    <li><b>Check where and how often.</b> Look at the study sites and how many visits are needed, and whether travel
      costs are covered.</li>
    <li><b>Ask the study team.</b> What is being tested and compared? What would you have to do? What are the possible
      risks and benefits? What happens when the study ends?</li>
    <li><b>Take your time with the consent.</b> Before joining you receive written information and sign an informed
      consent form. You can ask questions and talk with your family before you decide.</li>
    <li><b>You can always stop.</b> Taking part is voluntary: you can withdraw at any time without giving a reason,
      and without losing your usual care.</li>
  </ol>

  <h2>Words you will meet</h2>
  <dl class="words">
    <div><dt>Recruiting</dt><dd>The study is looking for participants now.</dd></div>
    <div><dt>Not yet recruiting</dt><dd>The study is approved but has not started enrolling yet.</dd></div>
    <div><dt>Randomised</dt><dd>Participants are assigned by chance to one of the groups being compared, so the groups
      are similar and the comparison is fair.</dd></div>
    <div><dt>Placebo</dt><dd>A treatment that looks like the real one but has no active effect. Not every trial uses one:
      the information sheet tells you.</dd></div>
    <div><dt>Phase 1, 2, 3, 4</dt><dd>Trials of medicines go through phases: first safety in a few people, then
      effect and dose, then comparison with the usual treatment in many patients, then follow-up after approval.</dd></div>
    <div><dt>Informed consent</dt><dd>Your written agreement to take part, after you have received and understood all
      the information about the study.</dd></div>
  </dl>

  <p class="note"><b>Please note.</b> {brand} does not run, recommend or select clinical trials and does not give
  medical advice. This page only opens searches on public registries: nothing you type is sent to us. Registry
  listings are written by the study teams; always confirm details with the study contact and your doctor. Be wary of
  any study that asks you to pay to take part.</p>

  <footer>Updated {updated} · <a href="feedback.html">Something wrong on this page? Write to us</a></footer>
</main>
<script>
(function () {{
  var f = document.getElementById("tf"), box = document.getElementById("results");
  if (!f) return;
  function enc(v) {{ return encodeURIComponent(v); }}
  f.addEventListener("submit", function (ev) {{
    ev.preventDefault();
    var cond = f.cond.value.trim(), term = f.term.value.trim(), country = f.country.value, soon = f.soon.checked;
    if (!cond) {{ f.cond.focus(); return; }}
    var q = "cond=" + enc(cond) + (term ? "&term=" + enc(term) : "") + (country ? "&country=" + enc(country) : "")
            + (soon ? "&aggFilters=" + enc("status:not rec") : "");
    document.getElementById("r-ctg").href = "https://clinicaltrials.gov/search?" + q;
    var crit = {{ containAll: (cond + " " + term).trim() }};
    if (soon) crit.status = [2, 3, 4, 6, 7];          /* studi in corso */
    document.getElementById("r-ctis").href = "https://euclinicaltrials.eu/ctis-public/search#searchCriteria="
                                            + enc(JSON.stringify(crit));
    document.getElementById("r-isrctn").href = "https://www.isrctn.com/search?q=" + enc((cond + " " + term).trim());
    box.hidden = false;
    box.scrollIntoView({{ behavior: "smooth", block: "nearest" }});
  }});
}})();
</script>
</body>
</html>
"""


def build_page(cfg, today=None):
    from datetime import date
    c = grants.site_palette(cfg)
    countries = "".join(f'<option value="{escape(n, quote=True)}">{escape(n)}</option>' for n in COUNTRIES)
    return PAGE.format(brand=escape(cfg["brand_name"]), bg=c["background"], muted=c["muted"], soft=c["muted_text"],
                       accent=TRIALS_ACCENT, countries=countries, updated=grants._fmt_date(today or date.today()),
                       og=grants.og_tags(cfg, f"Find your trial · {cfg['brand_name']}",
                                         "Search the official public registries of ongoing clinical trials and learn "
                                         "what to ask before you contact a study team.", "trials"))
