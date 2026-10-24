"""Diagnostica quota Gemini: modello dietro gli alias, chiamata semplice e con Google Search (non stampa la chiave)."""
import json, os, re, requests
K = os.environ["GEMINI_API_KEY"]
B = "https://generativelanguage.googleapis.com/v1beta/models/"
H = {"x-goog-api-key": K}
def note(t, m): print(f"::notice title={t}::{m[:900]}")
for m in ["gemini-flash-latest", "gemini-flash-lite-latest"]:
    r = requests.get(B + m, headers=H, timeout=30)
    j = r.json() if r.ok else {}
    note(f"MODEL {m}", f"{r.status_code} | {j.get('version','')} | {j.get('displayName','')} | in {j.get('inputTokenLimit','')} out {j.get('outputTokenLimit','')}")
    for label, extra in [("plain", {}), ("search", {"tools": [{"google_search": {}}]})]:
        body = {"contents": [{"parts": [{"text": "Reply with the single word OK."}]}], **extra}
        r = requests.post(B + m + ":generateContent", headers=H, json=body, timeout=60)
        if r.ok:
            u = r.json().get("usageMetadata", {})
            note(f"{m} {label} 200", f"modelVersion {r.json().get('modelVersion','')} | tokens {json.dumps(u)}")
        else:
            try:
                e = r.json().get("error", {})
                det = [v for d in e.get("details", []) for v in d.get("violations", [])]
                note(f"{m} {label} {r.status_code}", f"{e.get('message','')[:300]} | {json.dumps(det)[:500]}")
            except ValueError:
                note(f"{m} {label} {r.status_code}", r.text[:300])
