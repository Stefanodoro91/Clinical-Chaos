"""Test DeepSeek V3: genera un post di esempio con hook e lo stampa.
Esegui con: python test_deepseek.py
Richiede DEEPSEEK_API_KEY nell'ambiente.
"""
import json, os, requests, sys

key = os.environ.get("DEEPSEEK_API_KEY")
if not key:
    print("❌ DEEPSEEK_API_KEY non trovata nell'ambiente.")
    sys.exit(1)

PROMPT = """You are the content engine for @clinicalresearchchaos, an Instagram/Facebook page about clinical research methodology.

Generate ONE educational post about the ethical dilemma of randomization in clinical trials — specifically the concept of clinical equipoise (when is it ethical to randomize and when is it not).

Return this exact JSON structure:

{
  "title": "short punchy title (max 8 words)",
  "title_highlight": "1-4 words from the title (most important)",
  "category": "Research methods",
  "hook": "Opening hook using ONE of these formulas: 'Most researchers [wrong assumption]—but [surprising truth].' OR 'You can only randomize when [condition]. Here is why.' OR '[Number] out of [N] clinical trials face this ethical question before they start.'",
  "slides": [
    {
      "heading": "slide heading (max 6 words)",
      "body": "2-3 dense evidence-based sentences. No fluff.",
      "highlight": "exact quote from body (max 8 words)",
      "source": "Author et al., Year"
    }
  ],
  "caption": "Instagram caption (200-280 chars). Start with the hook sentence. End with an open question for researchers. No hashtags.",
  "hashtags": ["#ClinicalResearch", "#RCT", "#ResearchEthics", "#ClinicalTrials", "#Randomization", "#Methodology", "#EvidenceBasedMedicine", "#ClinicalResearcher"],
  "takeaway": "One actionable sentence the reader remembers.",
  "takeaway_highlight": "3-5 words from takeaway"
}

Rules:
- Hook MUST be the first sentence of caption
- 3 slides minimum, 5 maximum
- All claims need a real source (author, year)
- Tone: collegial, precise, never preachy
- Language: English
"""

body = {
    "model": "deepseek-chat",
    "messages": [
        {"role": "system", "content": "You are a clinical research content expert. Respond with valid JSON only, no markdown fences."},
        {"role": "user", "content": PROMPT},
    ],
    "temperature": 0.7,
    "response_format": {"type": "json_object"},
}

print("⏳ Chiamo DeepSeek V3…")
r = requests.post(
    "https://api.deepseek.com/chat/completions",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    json=body, timeout=60,
)
if not r.ok:
    print(f"❌ Errore {r.status_code}: {r.text[:300]}")
    sys.exit(1)

usage = r.json().get("usage", {})
post = json.loads(r.json()["choices"][0]["message"]["content"])

print("\n✅ POST GENERATO DA DEEPSEEK V3\n")
print(f"TITOLO:     {post.get('title')}")
print(f"HIGHLIGHT:  {post.get('title_highlight')}")
print(f"CATEGORIA:  {post.get('category')}")
print(f"\nHOOK:\n{post.get('hook')}")
print(f"\nCAPTION:\n{post.get('caption')}")
print(f"\nTAKEAWAY:\n{post.get('takeaway')}")
print(f"\nSLIDES ({len(post.get('slides', []))}):")
for i, s in enumerate(post.get("slides", []), 1):
    print(f"  {i}. {s.get('heading')} — {s.get('highlight')} [{s.get('source')}]")
print(f"\nHASHTAGS: {' '.join(post.get('hashtags', []))}")
print(f"\nTOKEN USATI: {usage.get('prompt_tokens',0)} in + {usage.get('completion_tokens',0)} out = {usage.get('total_tokens',0)} totali")
print("\nJSON COMPLETO:")
print(json.dumps(post, indent=2, ensure_ascii=False))
