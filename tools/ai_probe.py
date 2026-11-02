"""Quali modelli rispondono davvero con le chiavi del bot e quanto valgono per ciascuna operazione (2/11/2026).
1) sonda: una richiesta minima a ogni modello (Gemini dall'elenco della chiave, Groq, OpenRouter gratuiti);
2) verifica bandi: gli stessi bandi, ogni modello, confronto con i dati già verificati (scadenze, Italia, paesi);
3) scrittura del post di un bando: ogni modello scrive, un giudice indipendente (Groq/Qwen) dà i voti.
Nessuna pubblicazione e nessun commit: tutto nel log (e in probe.md come artifact)."""
import json, os, random, re, sys, time
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DRY_RUN", "true")
from datetime import date
import requests
import content, grants

out = []
def log(s=""):
    print(s, flush=True)
    out.append(s)

cfg = json.load(open("config.json"))
OK = {"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"}}, "required": ["ok"]}
SKIP = ("tts", "image", "live", "embedding", "audio", "transcribe", "vision", "robotics", "computer", "customtools", "native")

# ── 1. sonda ─────────────────────────────────────────────────────────────────────────────
log("# 1. Sonda dei modelli\n")
cands = []
try:
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                     headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, timeout=30)
    for m in r.json().get("models", []):
        n = m["name"].split("/")[-1]
        if "generateContent" in m.get("supportedGenerationMethods", []) and any(k in n for k in ("flash", "pro", "gemma")) \
                and not any(k in n for k in SKIP):
            cands.append(("gemini", n))
except Exception as e:
    log(f"Gemini elenco: {e}")
try:
    r = requests.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}, timeout=30)
    for m in r.json().get("data", []):
        if any(k in m["id"] for k in ("gpt-oss-120b", "gpt-oss-20b", "qwen", "llama", "kimi", "deepseek")) and "guard" not in m["id"] \
                and "safeguard" not in m["id"]:
            cands.append(("groq", m["id"]))
except Exception as e:
    log(f"Groq elenco: {e}")
cands.append(("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"))     # una sola richiesta: 50 al giorno, condivise col bot

ok_models, status = [], {}
for prov, model in cands:
    t = time.time()
    try:
        r = content.call_model(prov, model, [{"text": 'Reply with the JSON {"ok": true}'}], OK, 0.0, task="sonda")
        status[(prov, model)] = f"OK {time.time() - t:.0f}s"
        ok_models.append((prov, model))
    except Exception as e:
        status[(prov, model)] = f"NO: {str(e)[:150]}"
    log(f"- {prov}:{model} → {status[(prov, model)]}")

SLOW = lambda p, m: "gemma" in m or p == "openrouter" or "pro" in m
cmp_models = [pm for pm in ok_models if pm[0] != "openrouter"]               # OpenRouter già confrontato (bakeoff)
log(f"\nUtilizzabili: {', '.join(f'{p}:{m}' for p, m in cmp_models)}")

# ── 2. verifica bandi ───────────────────────────────────────────────────────────────────
log("\n\n# 2. Verifica bandi (confronto con i dati già verificati)\n")
today = date.today()
gl = grants.fetch(cfg)
ver = grants.load_verified()
pool = [g for g in gl if ver.get(g.get("id"), {}).get("status") == "ok" and grants.checked(ver[g["id"]])
        and grants.next_due(g, ver[g["id"]], today) and not grants.is_nih(g) and g.get("url")]
rnd = random.Random(11)
rnd.shuffle(pool)
picked, fams = [], set()
for g in pool:
    fam = ver[g["id"]].get("programme_family") or grants.programme_family(g)
    if fam not in fams:
        fams.add(fam); picked.append(g)
    if len(picked) == 3:
        break
log("Bandi: " + "; ".join(f"{g['id']} ({(ver[g['id']].get('programme') or '')[:40]})" for g in picked))
norm = lambda x: re.sub(r"\W+", " ", str(x or "").lower()).strip()
fields = [("due_dates", lambda v: sorted(v.get("due_dates") or [])), ("is_open_call", lambda v: v.get("is_open_call")),
          ("italy", lambda v: v.get("italy")), ("countries", lambda v: norm(v.get("eligible_countries"))[:60]),
          ("lead", lambda v: bool(v.get("lead")))]
score = {}
for prov, model in cmp_models:
    n_g = 1 if SLOW(prov, model) else 3
    content.ROUTE_OVERRIDES["verifica bandi"] = [f"{prov}:{model}"]
    res = []
    for g in picked[:n_g]:
        ref = ver[g["id"]]
        t = time.time()
        try:
            v = grants.verify(g, cfg)
            res.append({k: f(v) == f(ref) for k, f in fields} | {"s": round(time.time() - t)})
        except Exception as e:
            res.append({"err": str(e)[:120]})
    score[(prov, model)] = res
    log(f"- {prov}:{model}: " + " | ".join(
        (r["err"] if "err" in r else f"{sum(v for k, v in r.items() if k != 's')}/{len(fields)} campi uguali, {r['s']}s"
         + ("" if all(r[k] for k, _ in fields) else " (diversi: " + ", ".join(k for k, _ in fields if not r[k]) + ")")) for r in res))
content.ROUTE_OVERRIDES.pop("verifica bandi", None)

# ── 3. scrittura del post di un bando + giudice ─────────────────────────────────────────
log("\n\n# 3. Scrittura del post di un bando (giudice: Groq Qwen, stessa fonte)\n")
judge = next((pm for pm in ok_models if pm[0] == "groq" and "qwen" in pm[1]), None)
g = picked[0] if picked else None
if g and judge:
    v = ver[g["id"]]
    text, source, _ = grants.official_text(g)
    log(f"Bando: {g['id']} — {v.get('title', '')[:90]}")
    for prov, model in cmp_models:
        content.ROUTE_OVERRIDES["post bando"] = [f"{prov}:{model}"]
        t = time.time()
        try:
            post = grants.build_post(g, v, {**cfg, "cross_review": False}, ())
        except Exception as e:
            log(f"\n## {prov}:{model} — NON RIUSCITO: {str(e)[:160]}")
            continue
        el = time.time() - t
        draft = {"title": post["title"], "slides": post["slides"], "takeaway": post["takeaway"],
                 "hook": (post["caption"].split("\n")[0]), "caption": ""}
        try:
            prompt = content.CRITIC_PROMPT.format(kind="funding-call carousel", extra_rules=content.GRANT_RULES,
                                                  post=content._post_listing(draft), source_label="official text of the call",
                                                  source=content.relevant_excerpt(text, draft, content.REVIEW_CHARS))
            j = content.call_model(*judge, [{"text": prompt}], content.CRITIC_SCHEMA, 0.1, task="critica")
            sc = f"voti {j.get('scores')}, {len(j.get('issues') or [])} problemi, verdetto {j.get('verdict')}"
        except Exception as e:
            sc = f"giudice non disponibile: {str(e)[:80]}"
        log(f"\n## {prov}:{model} — {el:.0f}s — {sc}")
        log(f"Titolo: {post['title']}\n" + "\n".join(f"- {s['heading']}: {s['body']}" for s in post["slides"]) + f"\nTakeaway: {post['takeaway']}")
    content.ROUTE_OVERRIDES.pop("post bando", None)

open("probe.md", "w").write("\n".join(out))
log("\nConsumo: " + json.dumps(content.USAGE, ensure_ascii=False)[:1500])
