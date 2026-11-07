"""Testo del post LinkedIn, pronto da copiare e caricare a mano: nessuna pubblicazione automatica.
Stesso stile del testo lungo di Facebook (didascalia per esteso, punti chiave, takeaway, fonti, link cliccabile),
salvato come file .txt in linkedin_drafts/ a ogni post reale o simulato, cosi' da poterlo incollare su LinkedIn."""
import re

import polish


def draft(post, caption, kind, link):
    tags = re.findall(r"#\w+", caption)
    body = re.sub(r"(\s*#\w+)+\s*$", "", caption).strip()
    body = body.replace("link in bio", link or "")
    body = re.sub(r"\n*References:\n(?:[•-] .*(?:\n|$))+", "\n", body).strip()   # le reference vanno una volta sola, in fondo
    points = "\n".join(f"{i}. {polish.point(s['heading'], s['body'])}" for i, s in enumerate(post.get("slides", []), 1))
    refs = "\n".join(f"- {r}" for r in (post.get("references") or [])[:3])
    parts = [body,
             f"Key points:\n{points}" if points else "",
             f"Takeaway: {post['takeaway']}" if post.get("takeaway") else "",
             f"References:\n{refs}" if refs else "",
             f"Full details: {link}" if link and "link in bio" not in caption and link not in body else "",
             " ".join(tags[:5])]
    return "\n\n".join(x for x in parts if x)[:3000]


def filename(post, kind, today):
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in post["id"])
    return f"{today}-{kind or 'research'}-{safe}.txt"
