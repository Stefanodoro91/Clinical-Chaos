"""Token di Pagina Facebook ricavato al volo dal token utente (IG_ACCESS_TOKEN).

Facebook (storie, reel, post della Pagina) e il caricamento diretto dei reel Instagram vogliono un
Page Access Token. Se il secret FB_PAGE_TOKEN è vuoto, lo si chiede a Graph API con il token utente:
un token di Pagina ottenuto da un token utente di lunga durata non scade. Il valore viene mascherato nei
log di GitHub Actions e messo in os.environ["FB_PAGE_TOKEN"], così tutto il codice esistente lo usa.
"""
import os

import requests

GRAPH_VERSION = os.environ.get("GRAPH_API_VERSION") or "v23.0"


def ensure_page_token():
    """Restituisce il token di Pagina (o, se non ricavabile, il token utente come prima)."""
    if os.environ.get("FB_PAGE_TOKEN"):
        return os.environ["FB_PAGE_TOKEN"]
    user, page = os.environ.get("IG_ACCESS_TOKEN"), os.environ.get("FB_PAGE_ID")
    if not user or not page:
        return user
    try:
        r = requests.get(f"https://graph.facebook.com/{GRAPH_VERSION}/{page}",
                         params={"fields": "access_token", "access_token": user}, timeout=30)
        token = r.json().get("access_token") if r.ok else None
    except (requests.RequestException, ValueError):
        token = None
    if not token:
        print("::warning title=Token di Pagina::non ricavabile dal token utente: Facebook potrebbe rifiutare le pubblicazioni")
        return user
    print(f"::add-mask::{token}")
    os.environ["FB_PAGE_TOKEN"] = token
    print("::notice title=Token di Pagina::ricavato dal token utente")
    return token
