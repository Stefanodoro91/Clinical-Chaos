"""Prova di diagnosi di Threads: crea contenitori VIDEO con varianti e legge lo stato. NON pubblica niente
(threads_publish non viene mai chiamato)."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests
import social

USER = os.environ["THREADS_USER_ID"]
URLS = {
    "A nostro video convertito, senza testo": (os.environ["OUR_URL"], None),
    "B nostro video convertito, con testo": (os.environ["OUR_URL"], "Academic positions for clinical researchers"),
    "C nostro video originale, senza testo": (os.environ["OUR_URL"].replace("-threads", ""), None),
    "D video di esempio pubblico (MDN), senza testo": ("https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4", None),
}


def probe(label, url, text):
    params = {"media_type": "VIDEO", "video_url": url}
    if text:
        params["text"] = text
    try:
        cid = social._threads("POST", f"{USER}/threads", **params)["id"]
    except Exception as e:
        print(f"[{label}] creazione rifiutata: {str(e)[:300]}", flush=True)
        return
    for i in range(40):
        st = social._threads("GET", cid, fields="status,error_message")
        if st.get("status") in ("FINISHED", "ERROR", "EXPIRED"):
            print(f"[{label}] → {st} (dopo {i * 8} s)", flush=True)
            return
        time.sleep(8)
    print(f"[{label}] ancora in elaborazione dopo 320 s: {st}", flush=True)


try:
    lim = social._threads("GET", f"{USER}/threads_publishing_limit", fields="quota_usage,config")
    print("limite di pubblicazione:", json.dumps(lim), flush=True)
except Exception as e:
    print("limite:", str(e)[:200])
try:
    r = requests.get(f"https://graph.threads.net/v1.0/me", params={"fields": "id,username,threads_profile_picture_url",
                     "access_token": os.environ["THREADS_ACCESS_TOKEN"]}, timeout=30)
    print("profilo:", r.status_code, r.text[:200], flush=True)
except Exception as e:
    print("profilo:", str(e)[:200])
for label, (url, text) in URLS.items():
    probe(label, url, text)
