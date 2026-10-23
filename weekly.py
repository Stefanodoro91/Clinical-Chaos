"""Ogni lunedì: messaggio pronto per il canale WhatsApp (in inglese) e resoconto per Stefano (in italiano):
bandi e posizioni per regione e area, post della settimana, fonti che rendono e fonti rotte."""

import collections
import json
import re
from datetime import date, timedelta
from pathlib import Path

import requests

import grants
import positions

ROOT = Path(__file__).resolve().parent


def _week(today):
    return today - timedelta(days=7)


def whatsapp_message(grants_list, verified, archive, posted, cfg, today=None):
    """Testo breve da incollare nel canale: i 5 bandi verificati più utili e le 5 posizioni nuove della settimana."""
    today = today or date.today()
    since = _week(today)
    base = cfg.get("links_page_url", "").rstrip("/")
    calls = []
    for g, v, d in grants.page_entries(grants_list, verified, today):
        checked = grants._date((v or {}).get("checked"))
        if v and checked and checked >= since and d:
            ctry = re.sub(r"\s*\(.*\)\s*$", "", v.get("eligible_countries") or "")
            ctry = "" if ctry.lower().startswith(("not stated", "coming soon")) else ctry
            calls.append((g.get("rilevanza") != "Alta", d, v.get("title") or g.get("titolo"), ctry))
    calls.sort()
    jobs = []
    for k, v, d in positions.active(archive, today):
        seen = grants._date(v.get("first_seen"))
        if seen and seen >= since:
            jobs.append((v.get("relevance") != "high", d or date.max, v["title"], v.get("institution", ""), v.get("country", "")))
    jobs.sort()
    methods = [p["title"] for p in posted if (p.get("kind") or "research") == "research"
               and grants._date(p.get("date")) and grants._date(p["date"]) >= since]
    lines = [f"*{cfg['brand_name']}* – week of {today.day} {today.strftime('%b %Y')}", ""]
    if calls:
        lines.append("💶 *New funding calls*")
        lines += [f"• {t} – deadline {grants._fmt_date(d)}" + (f" ({c})" if c else "") for _, d, t, c in calls[:5]]
        lines += [f"All calls: {base}/calls", ""]
    if jobs:
        lines.append("🎓 *New academic positions*")
        lines += [f"• {t} – {i}, {c}" + (f" (deadline {grants._fmt_date(d)})" if d != date.max else "") for _, d, t, i, c in jobs[:5]]
        lines += [f"All positions: {base}/positions", ""]
    if methods:
        lines.append("📚 *This week's methodology*")
        lines += [f"• {t}" for t in methods[:7]]
        lines += [f"Library: {base}/methodology", ""]
    lines.append("Always check eligibility and dates in the official call or advertisement.")
    return "\n".join(lines), len(calls), len(jobs)


def report(grants_list, verified, archive, posted, queue, cfg, today=None):
    """Resoconto in italiano (markdown per la issue di GitHub)."""
    today = today or date.today()
    since = _week(today)
    entries = grants.page_entries(grants_list, verified, today)
    reg = collections.Counter(grants.region(g, v, cfg) if v.get("italy") != "yes" else "Aperti all'Italia" for g, v, d in entries)
    area = collections.Counter(a for g, v, d in entries for a in grants.areas(g))
    pending = sum(1 for g, v, d in entries if not v)
    act = positions.active(archive, today)
    preg = collections.Counter(positions.region_of(v) for k, v, d in act)
    parea = collections.Counter(v.get("area") or "rehabilitation" for k, v, d in act)
    week_posts = collections.Counter((p.get("kind") or "research") for p in posted
                                     if grants._date(p.get("date")) and grants._date(p["date"]) >= since)
    out = [f"## Resoconto settimanale – {grants._fmt_date(today)}", "",
           f"**Bandi in pagina:** {len(entries)} (di cui {pending} ancora da verificare)", ""]
    out += ["| Regione | Bandi |", "| --- | --- |"] + [f"| {k} | {n} |" for k, n in reg.most_common()]
    out += ["", "| Area | Bandi |", "| --- | --- |"] + [f"| {grants.AREA_LABELS.get(k, k)} | {n} |" for k, n in area.most_common()]
    out += ["", f"**Posizioni aperte:** {len(act)}", "", "| Regione | Posizioni |", "| --- | --- |"]
    out += [f"| {k} | {n} |" for k, n in preg.most_common()]
    out += ["", "| Area | Posizioni |", "| --- | --- |"] + [f"| {k} | {n} |" for k, n in parea.most_common()]
    out += ["", "**Post della settimana:** " + (", ".join(f"{k} {n}" for k, n in week_posts.items()) or "nessuno"),
            f"**Post di metodologia in coda:** {len(queue)}", ""]
    # fonti di GrantFinder: quante rendono, quali sono rotte
    try:
        st = requests.get(cfg.get("grantfinder_url") or grants.DEFAULT_URL, timeout=60).json()
        fonti = st.get("fonti", {})
        rotte = [(n, (f.get("note") or "")[:90]) for n, f in fonti.items() if "errore" in (f.get("note") or "").lower()]
        utili = sorted(((len(f.get("pertinenti") or []) if isinstance(f.get("pertinenti"), list) else 0, n)
                        for n, f in fonti.items()), reverse=True)
        out += [f"**Fonti GrantFinder:** {len(fonti)} · con bandi pertinenti: {sum(1 for n, _ in utili if n)} · con errori: {len(rotte)}",
                "", "Le 8 fonti che rendono di più: " + ", ".join(f"{n} ({c})" for c, n in utili[:8]), ""]
        if rotte:
            out += ["<details><summary>Fonti con errori</summary>", ""] + [f"- {n}: {e}" for n, e in rotte] + ["", "</details>", ""]
    except Exception as e:
        out.append(f"Stato delle fonti GrantFinder non disponibile: {e}")
    try:
        ps = json.load(open(ROOT / positions.STATUS_FILE, encoding="utf-8"))
        ok = [n for n, s in ps.items() if not s.get("errore")]
        bad = [(n, s.get("errore", "")[:80]) for n, s in ps.items() if s.get("errore")]
        out += [f"**Fonti posizioni:** {len(ok)} su {len(ps)} rispondono."]
        if bad:
            out += ["<details><summary>Fonti posizioni con errori</summary>", ""] + [f"- {n}: {e}" for n, e in bad] + ["", "</details>"]
    except (OSError, ValueError):
        pass
    return "\n".join(out)
