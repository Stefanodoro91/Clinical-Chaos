"""Prova dell'estrazione delle figure (visuals.paper_figures) sui PDF delle cartelle «Clinica…» di Drive.
Solo lettura: niente AI, niente pubblicazione. Scrive probe.md e le figure ritagliate in probe_fig/."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bot        # noqa: E402
import sources    # noqa: E402
import visuals    # noqa: E402

out = Path("probe_fig")
out.mkdir(exist_ok=True)
drive = bot.drive_service()
inbox = os.environ["GDRIVE_FOLDER_ID"]
files = [f for f in bot.list_inbox(drive, inbox) if f.get("parent") != inbox and f.get("mimeType") == "application/pdf"]
lines = ["# Figure degli articoli clinici", ""]
for f in files[:14]:
    try:
        data = drive.files().get_media(fileId=f["id"], supportsAllDrives=True).execute()
        text, _ = sources._first_page(data)
        m = sources.RX_DOI.search(text)
        lic = ""
        if m:
            try:
                lic = sources._cc_license(sources._crossref(m.group(1))) or ""
            except Exception as e:
                lic = f"crossref: {str(e)[:60]}"
        figs = visuals.paper_figures(data)
        ok = visuals.figure_license_ok({"license": lic})
        lines.append(f"## {f['name']}\nDOI: {m.group(1) if m else '—'} · licenza: {lic or '—'} · figure usabili: "
                     f"{'sì' if ok else 'no'} · trovate: {len(figs)}")
        stem = "".join(ch if ch.isalnum() else "-" for ch in f["name"][:30])
        for fig in figs:
            im = fig["image"].copy()
            im.thumbnail((800, 800))
            im.save(out / f"{stem}-fig{fig['n']}.jpg", quality=80)
            lines.append(f"- Figure {fig['n']} ({fig['image'].width}×{fig['image'].height}): {fig['caption'][:160]}")
        if figs:
            visuals.figure_panel(figs[0], "Author et al., year · CC BY 4.0", 880, 440).save(out / f"{stem}-panel.jpg", quality=85)
        lines.append("")
    except Exception as e:
        lines.append(f"## {f['name']}\nerrore: {str(e)[:200]}\n")
Path("probe.md").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
