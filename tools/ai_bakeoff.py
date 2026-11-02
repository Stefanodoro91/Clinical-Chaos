"""Confronto dei modelli per la revisione incrociata (2/11/2026): quali modelli rispondono davvero con le chiavi del
bot, e come critica ciascun revisore candidato gli stessi post della coda sulla stessa fonte. Nessuna pubblicazione,
nessun commit: tutto nel log del run (e in bakeoff.md come artifact)."""
import json, os, sys, time
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DRY_RUN", "true")
import requests
import content
import bot

out = []
def log(s=""):
    print(s)
    out.append(s)

# ── 1. modelli disponibili ───────────────────────────────────────────────────────────────
log("# Modelli disponibili\n")
try:
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                     headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, timeout=30)
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    log("Gemini: " + ", ".join(n for n in names if any(k in n for k in ("flash", "pro", "gemma"))))
except Exception as e:
    log(f"Gemini: errore {e}")
try:
    r = requests.get("https://api.groq.com/openai/v1/models",
                     headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}, timeout=30)
    groq_ids = sorted(m["id"] for m in r.json().get("data", []) if m.get("active", True))
    log("Groq: " + ", ".join(groq_ids))
except Exception as e:
    groq_ids = []
    log(f"Groq: errore {e}")
try:
    h = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}
    k = requests.get("https://openrouter.ai/api/v1/key", headers=h, timeout=30).json().get("data", {})
    log(f"OpenRouter chiave: free tier={k.get('is_free_tier')}, limite={k.get('limit')}, rate={k.get('rate_limit')}")
    r = requests.get("https://openrouter.ai/api/v1/models", timeout=30)
    free = sorted((m["id"], m.get("context_length")) for m in r.json().get("data", []) if m["id"].endswith(":free"))
    log("OpenRouter free: " + ", ".join(f"{i} ({c})" for i, c in free))
except Exception as e:
    free = []
    log(f"OpenRouter: errore {e}")

# ── 2. revisori candidati sugli stessi post ──────────────────────────────────────────────
want_groq = [m for m in groq_ids if any(k in m for k in ("gpt-oss-120b", "qwen3", "kimi", "deepseek", "llama-4-maverick"))]
want_or = [i for i, _ in free if any(k in i for k in ("nemotron-3-ultra", "inkling:free", "minimax-m3", "gemma-4-31b",
                                                         "deepseek", "qwen", "kimi", "glm"))][:5]
candidates = ([("groq", m) for m in want_groq] + [("openrouter", m) for m in want_or]
              + [("gemini", content.GEMMA), ("gemini", "gemini-flash-lite-latest")])
log("\nCandidati: " + ", ".join(f"{p}:{m}" for p, m in candidates))

drive = bot.drive_service()
queue = json.load(open("queue.json"))
ids = [x for x in (os.environ.get("BAKEOFF_IDS") or "").split(",") if x]
posts = [q for q in queue if q["id"] in ids] if ids else []
for q in queue:                                   # post con fonti diverse
    if len(posts) >= int(os.environ.get("BAKEOFF_N", "2")):
        break
    if q not in posts and q.get("source") not in {p.get("source") for p in posts}:
        posts.append(q)

for post in posts:
    material = bot.source_material(drive, post.get("source", ""))
    log(f"\n\n# Post «{post['title']}» (fonte {post.get('source')}, {len(material)} caratteri)\n")
    log("```\n" + content._post_listing(post) + "\n```")
    if not material:
        log("fonte non disponibile: salto")
        continue
    prompt = content.CRITIC_PROMPT.format(kind="educational carousel", extra_rules="", post=content._post_listing(post),
                                          source_label="teaching material the post was built from",
                                          source=content.relevant_excerpt(material, post, content.REVIEW_CHARS))
    for provider, model in candidates:
        t = time.time()
        try:
            res = content.call_model(provider, model, [{"text": prompt}], content.CRITIC_SCHEMA, 0.1, task="critica")
            log(f"\n## {provider}:{model} — {time.time() - t:.0f}s — verdetto {res.get('verdict')} {res.get('scores')}")
            for x in res.get("issues") or []:
                fix = (f"{x.get('heading', '')} — {x.get('body', '')}" if x.get("heading") or x.get("body") else x.get("text", ""))
                log(f"- **{x.get('where')}** [{x.get('kind')}] «{(x.get('quote') or '')[:160]}» → {x.get('why', '')[:220]}"
                    + (f"\n  fix: {fix[:260]}" if fix else ""))
        except Exception as e:
            log(f"\n## {provider}:{model} — NON DISPONIBILE: {str(e)[:220]}")

# ── 3. catena completa sul primo post (revisore + arbitro + controllo finale) ───────────
if posts and os.environ.get("BAKEOFF_FULL", "1") == "1":
    post = json.loads(json.dumps(posts[0]))
    material = bot.source_material(drive, post.get("source", ""))
    log(f"\n\n# Catena completa su «{post['title']}»\n")
    rep = content.cross_review(post, material)
    log(f"esito: {json.dumps({k: rep[k] for k in ('passed', 'scores', 'critic', 'arbiter', 'fixed', 'removed')}, ensure_ascii=False)}")
    log("```\n" + content._post_listing(post) + "\n```")

open("bakeoff.md", "w").write("\n".join(out))
log("\nConsumo: " + json.dumps(content.USAGE, ensure_ascii=False))
