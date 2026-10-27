"""Confronto A/B giornaliero (27/10 → 2/11): A = Flash, impostazione attuale; B = Flash-Lite con annunci di 15.000
caratteri. Ogni giorno un campione nuovo (mai voci già confrontate); stessi testi per A e B; si confrontano i campi
che contano. Risultati in ab/ab-<data>.md e riepilogo cumulativo in ab/summary.md."""
import functools, glob, json, os, random, re, sys, time
from datetime import date
sys.path.insert(0, os.getcwd())
import content, grants, positions

N = int(os.environ.get("AB_N", "3"))
TRANSIENT = ("timed out", "RemoteDisconnected", "Connection aborted", "Connection reset", "403 Client Error",
             "404 Client Error", "troppo breve", " 503", " 500")
DONE = set()
for f in glob.glob("ab/ab-*.json"):
    try:
        d = json.load(open(f, encoding="utf-8"))
        DONE |= {r["id"] for r in d.get("grants", []) + d.get("positions", []) if "same" in r}
    except (OSError, ValueError, KeyError):
        pass
RND = random.Random(date.today().toordinal())
START, BUDGET = time.time(), 28 * 60       # si ferma prima del timeout del job e scrive comunque i risultati
STOP = []
FLASH, LITE = "gemini-flash-latest", "gemini-flash-lite-latest"
B_MODEL = os.environ.get("AB_B_MODEL", LITE)          # variante B: modello leggero (quota separata e più ampia)
B_THINK = os.environ.get("AB_B_THINKING") or None
B_CHARS = int(os.environ.get("AB_B_CHARS", "15000"))
cfg = json.load(open("config.json"))
out = {"date": date.today().isoformat(), "grants": [], "positions": [], "models": set()}

_orig = content.gemini_json
def tagged(variant, thinking, model=FLASH):
    def f(parts, schema, temperature=0.5, task="altro", thinking_=None, **kw):
        content.GEMINI_MODEL = content.GEMINI_FALLBACK = model      # nessun ripiego: ogni variante usa il suo modello
        return _orig(parts, schema, temperature, task=f"{task} [{variant}]", thinking=thinking)
    return f

# il testo ufficiale si scarica una volta sola per bando
grants.official_text = functools.lru_cache(maxsize=None)(lambda g, _f=grants.official_text: _f(g)) if False else grants.official_text
_texts = {}
_ot = grants.official_text
def cached_text(g):
    if g["id"] not in _texts:
        _texts[g["id"]] = _ot(g)
    return _texts[g["id"]]
grants.official_text = cached_text

def norm(s): return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(s or "").lower()).split())

gl = {g["id"]: g for g in grants.fetch(cfg)}
ver = grants.load_verified()
sample = [k for k, v in ver.items() if v.get("status") == "ok" and v.get("version", 0) >= 3 and k in gl and k not in DONE]
RND.shuffle(sample)
for gid in sample:
    if STOP or time.time() - START > BUDGET or sum("same" in r for r in out["grants"]) >= N:
        break
    g = gl[gid]
    try:
        content.gemini_json = tagged("A", None); a = grants.verify(g, cfg)
        content.gemini_json = tagged("B", B_THINK, B_MODEL); b = grants.verify(g, cfg)
    except Exception as e:
        out["grants"].append({"id": gid, "error": str(e)[:200]})
        if "Gemini non disponibile" in str(e) and " 429" in str(e):
            STOP.append("quota")
        elif any(t in str(e) for t in TRANSIENT):
            time.sleep(30)            # errore di rete o sovraccarico momentaneo: si passa alla voce successiva
        continue
    fields = {
        "due_dates": a.get("due_dates") == b.get("due_dates"),
        "deadline_source": a.get("deadline_source") == b.get("deadline_source"),
        "italy": a.get("italy") == b.get("italy"),
        "is_open_call": a.get("is_open_call") == b.get("is_open_call"),
        "countries": norm(a.get("eligible_countries")) == norm(b.get("eligible_countries")),
        "lead_present": bool(a.get("lead")) == bool(b.get("lead")),
        "loi": a.get("loi_deadline") == b.get("loi_deadline"),
    }
    out["grants"].append({"id": gid, "same": fields, "A": {k: a.get(k) for k in ("due_dates", "italy", "eligible_countries", "lead", "is_open_call")},
                          "B": {k: b.get(k) for k in ("due_dates", "italy", "eligible_countries", "lead", "is_open_call")}})
    time.sleep(9)

arch = positions.load_archive()
psample = [(k, v) for k, v in arch.items() if v.get("status") == "ok" and v.get("url") and k not in DONE
           and not v.get("url", "").startswith("https://www.inpa")]
RND.shuffle(psample)
for k, v in psample:
    if STOP or time.time() - START > BUDGET or sum("same" in r for r in out["positions"]) >= N:
        break
    item = {"url": v["url"], "title": v.get("title", ""), "source": v.get("source", "")}
    try:
        positions.TEXT_CHARS = 40000; content.gemini_json = tagged("A", None); a = positions.verify(item)
        positions.TEXT_CHARS = B_CHARS; content.gemini_json = tagged("B", B_THINK, B_MODEL); b = positions.verify(item)
    except Exception as e:
        out["positions"].append({"id": k, "error": str(e)[:200]})
        if "Gemini non disponibile" in str(e) and " 429" in str(e):
            STOP.append("quota")
        elif any(t in str(e) for t in TRANSIENT):
            time.sleep(30)
        continue
    fields = {f: a.get(f) == b.get(f) for f in ("is_open", "type", "relevance", "deadline", "area")}
    fields["country"] = norm(a.get("country")) == norm(b.get("country"))
    out["positions"].append({"id": k, "same": fields, "A": {f: a.get(f) for f in ("is_open", "type", "relevance", "deadline", "country")},
                             "B": {f: b.get(f) for f in ("is_open", "type", "relevance", "deadline", "country")}})
    time.sleep(9)

content.gemini_json = _orig
def rate(rows, f):
    ok = [r for r in rows if "same" in r]
    return f"{sum(r['same'][f] for r in ok)}/{len(ok)}" if ok else "-"
lines = [f"# Confronto A/B – {out['date']}", "", f"A = {FLASH}, impostazione attuale; B = {B_MODEL}, ragionamento {B_THINK or 'predefinito'}, "
         f"annunci di {B_CHARS} caratteri", "", f"Interrotto: {', '.join(STOP)}" if STOP else "Completato", "", "## Bandi"]
gf = ["due_dates", "deadline_source", "italy", "is_open_call", "countries", "lead_present", "loi"]
lines += [f"- {f}: {rate(out['grants'], f)}" for f in gf]
lines += ["", "## Posizioni"]
pf = ["is_open", "type", "relevance", "deadline", "area", "country"]
lines += [f"- {f}: {rate(out['positions'], f)}" for f in pf]
lines += ["", "## Consumo (token)", "", "| Attività | Richieste | Ingresso | Uscita | Ragionamento |", "| --- | --- | --- | --- | --- |"]
for key, c in sorted(content.USAGE.items()):
    lines.append(f"| {key} ({c.get('versione', '')}) | {c['richieste']} | {c['ingresso']} | {c['uscita']} | {c['ragionamento']} |")
lines += ["", "## Differenze"]
for r in out["grants"] + out["positions"]:
    if "error" in r:
        lines.append(f"- {r['id']}: errore {r['error']}")
    elif not all(r["same"].values()):
        diff = [f for f, s in r["same"].items() if not s]
        lines.append(f"- {r['id']}: {', '.join(diff)} | A={json.dumps({f: r['A'].get(f) for f in r['A']}, ensure_ascii=False)[:300]} | B={json.dumps({f: r['B'].get(f) for f in r['B']}, ensure_ascii=False)[:300]}")
os.makedirs("ab", exist_ok=True)
open(f"ab/ab-{out['date']}.md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
out.pop("models")
json.dump(out, open(f"ab/ab-{out['date']}.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=str)
print("\n".join(lines))

# riepilogo cumulativo di tutti i giorni
allg, allp = [], []
for f in sorted(glob.glob("ab/ab-*.json")):
    try:
        d = json.load(open(f, encoding="utf-8"))
    except (OSError, ValueError):
        continue
    allg += [r for r in d.get("grants", []) if "same" in r]
    allp += [r for r in d.get("positions", []) if "same" in r]
tot = sum(sum(r["same"].values()) for r in allg + allp)
cnt = sum(len(r["same"]) for r in allg + allp)
crit = [r["id"] for r in allg if not (r["same"]["due_dates"] and r["same"]["italy"])]
summ = ["# Confronto A/B – riepilogo cumulativo", "", f"Bandi confrontati: {len(allg)} · posizioni: {len(allp)}",
        f"Campi uguali: {tot}/{cnt} ({100 * tot / cnt:.1f}%)" if cnt else "Campi uguali: -",
        f"Bandi con scadenze o Italia diverse: {', '.join(crit) or 'nessuno'}", "",
        "Regola: Flash-Lite per le verifiche solo con almeno 10 bandi e 10 posizioni, ≥ 95% di campi uguali e nessuna "
        "differenza su scadenze o Italia.", "", "## Bandi"]
summ += [f"- {f}: {rate(allg, f)}" for f in gf] + ["", "## Posizioni"] + [f"- {f}: {rate(allp, f)}" for f in pf]
open("ab/summary.md", "w", encoding="utf-8").write("\n".join(summ) + "\n")
print("\n".join(summ))
content.save_usage("usage")   # conta nella quota del giorno: le verifiche lasciano spazio ai post
