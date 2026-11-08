"""Anteprima dei reel dei due post di lancio (Funding calls, Academic positions): le slide pubblicate, musica Funky
dalla libreria su Drive, colore della rubrica. Niente pubblicazione: i video vanno sul ramo di prova probe-figures."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import reels  # noqa: E402

cfg = json.loads((ROOT / "config.json").read_text())
out = ROOT / "probe_fig"
out.mkdir(exist_ok=True)
report = ["# Reel dei post di lancio\n"]
for seed, (folder, accent, ann) in enumerate([
        ("2026-11-08-kickoff-funding-calls", cfg.get("grant_accent", "#FFB547"), "kickoff-funding-calls"),
        ("2026-11-08-kickoff-academic-positions", cfg.get("positions_accent", "#8B5CF6"), "kickoff-academic-positions")]):
    d = ROOT / "published_images" / folder
    slides = sorted(d.glob("slide-*.jpg"), key=lambda p: int(p.stem.split("-")[1]))
    log = json.loads((ROOT / "posted_log.json").read_text())
    post = next((p for p in log if p.get("id") == ann), {})
    words = [len((s.get("heading", "") + " " + s.get("body", "")).split()) for s in post.get("slides", [])] or [25]
    lengths = reels.reading_lengths(len(slides), words, cap=40.0)
    rcfg = {**cfg, "colors": {**cfg["colors"], "accent": accent}}
    video = out / f"{ann}.mp4"
    import os
    from datetime import date, timedelta
    os.environ["PREVIEW_DATE"] = (date.today() + timedelta(days=seed)).isoformat()   # un brano diverso per reel
    secs = reels.build_reel(slides, video, rcfg, accent=accent, mood="Funky", per_slide=lengths)
    import music
    report.append(f"- {ann}: {secs} s, {len(slides)} slide, musica {music.LAST_TRACK.get('name')}")
    print(report[-1], flush=True)
(ROOT / "probe.md").write_text("\n".join(report) + "\n")
