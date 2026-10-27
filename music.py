"""Basi strumentali originali per storie e reel (nessun diritto d'autore): lo-fi/chill con batteria, basso, accordi e
piano elettrico, sintetizzati in Python con numpy. Ogni seme sceglie tonalità, giro di accordi e tempo diversi."""
import wave
from pathlib import Path

import numpy as np

RATE = 44100
# giri di accordi (gradi in semitoni dalla tonica, accordi a 4 voci): pop/lo-fi classici
PROGRESSIONS = [
    [[9, 12, 16, 19], [5, 9, 12, 16], [0, 4, 7, 11], [7, 11, 14, 17]],    # vi–IV–I–V   (Am7 Fmaj7 Cmaj7 G7)
    [[2, 5, 9, 12], [7, 11, 14, 17], [0, 4, 7, 11], [9, 12, 16, 19]],     # ii–V–I–vi   (Dm7 G7 Cmaj7 Am7)
    [[0, 4, 7, 11], [9, 12, 16, 19], [5, 9, 12, 16], [7, 11, 14, 17]],    # I–vi–IV–V
    [[5, 9, 12, 16], [7, 11, 14, 17], [4, 7, 11, 14], [9, 12, 16, 19]],   # IV–V–iii–vi
]
KEYS = [0, 2, 3, 5, 7, 8]          # do, re, mib, fa, sol, lab (tonica sotto il do centrale + offset)


def _hz(semi, base=130.81):        # 130.81 Hz = do3
    return base * 2 ** (semi / 12)


def _lowpass(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / RATE)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):        # filtro a un polo: suono più caldo (accordi e basso)
        acc = (1 - a) * x[i] + a * acc
        y[i] = acc
    return y


def _env(n, attack, release, total=None):
    total = total or n
    e = np.ones(n)
    a, r = int(attack * RATE), int(release * RATE)
    if a:
        e[:a] = np.linspace(0, 1, a)
    if r:
        e[max(0, total - r):] *= np.linspace(1, 0, len(e[max(0, total - r):]))
    return e


def _saw(freq, t, harmonics=10):
    out = np.zeros_like(t)
    for k in range(1, harmonics + 1):
        out += np.sin(2 * np.pi * freq * k * t) / k
    return out


def _add(buf, start, sig):
    s = int(start * RATE)
    if s >= len(buf):
        return
    end = min(len(buf), s + len(sig))
    buf[s:end] += sig[:end - s]


PENTA = [0, 2, 4, 7, 9]             # pentatonica maggiore: suona bene su tutti i giri


def _pluck(freq, dur):
    """Nota pizzicata brillante (armoniche che si spengono prima della fondamentale)."""
    tt = np.arange(int(dur * RATE)) / RATE
    out = np.zeros_like(tt)
    for k, amp in ((1, 1.0), (2, 0.6), (3, 0.42), (4, 0.3), (5, 0.22), (6, 0.15), (7, 0.1), (8, 0.07)):
        out += amp * np.sin(2 * np.pi * freq * k * tt) * np.exp(-tt * (4 + 1.5 * k))
    return out * np.minimum(1, tt / 0.004)


def _motif(rng):
    """Due battute di melodia: (posizione in battiti, grado della pentatonica, intensità)."""
    rhythms = [[0, 0.75, 1.5, 2.5, 3], [0.5, 1, 2, 2.75, 3.5], [0, 1, 1.5, 2.5, 3.25]]
    out = []
    deg = int(rng.integers(2, 6))
    for bar in range(2):
        notes = []
        for pos in rhythms[int(rng.integers(len(rhythms)))]:
            deg = int(np.clip(deg + rng.choice([-2, -1, 1, 1, 2]), 0, 8))
            notes.append((pos, deg, 0.22 + 0.08 * rng.random()))
        out.append(notes)
    out[1][-1] = (out[1][-1][0], 5, 0.26)                          # chiude sulla tonica all'ottava
    return out


def track(seconds, seed=0):
    """Restituisce l'audio (stereo, float -1..1) di una base di `seconds` secondi."""
    rng = np.random.default_rng(seed)
    prog = PROGRESSIONS[seed % len(PROGRESSIONS)]
    key = KEYS[(seed // len(PROGRESSIONS)) % len(KEYS)]
    bpm = [86, 90, 94, 98][seed % 4]
    beat = 60 / bpm
    bar = 4 * beat
    n = int(seconds * RATE)
    pads, keys_, bass, drums, lead = (np.zeros(n) for _ in range(5))
    motif = _motif(rng)
    t_bar = np.arange(int(bar * RATE)) / RATE

    bars = int(np.ceil(seconds / bar))
    for b in range(bars):
        chord = [c + key for c in prog[b % len(prog)]]
        start = b * bar
        # accordi: saw morbide leggermente stonate tra loro, filtrate (pad caldo)
        pad = sum(_saw(_hz(c), t_bar) + _saw(_hz(c) * 1.004, t_bar) for c in chord)
        pad = _lowpass(pad / (2 * len(chord)), 2400) * _env(len(t_bar), 0.25, 0.35)
        _add(pads, start, pad * 0.6)
        # piano elettrico: note dell'accordo in levare, con decadimento
        for k, pos in enumerate([0.5, 1.5, 2.5, 3.25]):
            note = chord[(k + b) % len(chord)] + 12
            tt = np.arange(int(0.9 * RATE)) / RATE
            ep = (np.sin(2 * np.pi * _hz(note) * tt) + 0.35 * np.sin(2 * np.pi * _hz(note) * 2 * tt)
                  + 0.12 * np.sin(2 * np.pi * _hz(note) * 3 * tt) + 0.2 * np.sin(2 * np.pi * _hz(note) * 7 * tt) * np.exp(-tt * 14)) * np.exp(-tt * 4.0)
            _add(keys_, start + pos * beat, ep * (0.55 + 0.1 * rng.random()))
        # melodia: pluck brillante su scala pentatonica (motivo di 2 battute, ripetuto con variazioni)
        if b >= 1:
            for pos, deg, vel in motif[b % 2]:
                semi = key + 24 + PENTA[deg % 5] + 12 * (deg // 5)
                _add(lead, start + pos * beat, _pluck(_hz(semi), 0.55) * vel)
        # basso: tonica sui tempi 1 e 3, quinta di passaggio
        root = chord[0] - 12
        while root > 0:
            root -= 12
        for pos, semi, dur in ((0, root, 1.4), (2, root, 1.0), (3.5, root + 7, 0.45)):
            tt = np.arange(int(dur * beat * RATE)) / RATE
            bs = np.tanh(1.6 * np.sin(2 * np.pi * _hz(semi) * tt)) * _env(len(tt), 0.01, 0.12)
            _add(bass, start + pos * beat, bs * 0.28)
        # batteria
        for pos in (0, 2, 2.5):                                   # cassa
            tt = np.arange(int(0.35 * RATE)) / RATE
            f = 45 + 75 * np.exp(-tt * 30)
            kick = np.sin(2 * np.pi * np.cumsum(f) / RATE) * np.exp(-tt * 9)
            _add(drums, start + pos * beat, kick * (0.55 if pos != 2.5 else 0.35))
        for pos in (1, 3):                                        # rullante morbido
            tt = np.arange(int(0.22 * RATE)) / RATE
            noise = rng.standard_normal(len(tt))
            sn = (0.9 * np.diff(noise, 1, prepend=0)) * np.exp(-tt * 16) + 0.3 * np.sin(2 * np.pi * 185 * tt) * np.exp(-tt * 25)
            _add(drums, start + pos * beat, sn * 0.45)
        for i in range(8):                                        # charleston in ottavi, con swing
            pos = i * 0.5 + (0.08 if i % 2 else 0)
            tt = np.arange(int(0.05 * RATE)) / RATE
            noise = rng.standard_normal(len(tt))
            hat = np.diff(noise, 2, prepend=[0, 0]) * np.exp(-tt * 60)                # passa-alto: più «aria»
            _add(drums, start + pos * beat, hat * (0.16 if i % 2 else 0.22) * (0.8 + 0.4 * rng.random()))
        if b % 2:                                                 # charleston aperto a fine giro
            tt = np.arange(int(0.3 * RATE)) / RATE
            noise = rng.standard_normal(len(tt))
            _add(drums, start + 3.5 * beat, np.diff(noise, 2, prepend=[0, 0]) * np.exp(-tt * 9) * 0.08)

    # «pompaggio» degli accordi sulla cassa (sidechain) e piccolo eco sul piano
    t = np.arange(n) / RATE
    phase = (t % (2 * beat)) / (2 * beat)
    pads *= 0.55 + 0.45 * np.minimum(1, phase * 6)
    delay = int(beat * 0.75 * RATE)
    echo = np.zeros(n)
    echo[delay:] = keys_[:-delay] * 0.35
    lecho = np.zeros(n)
    lecho[delay:] = lead[:-delay] * 0.4
    crackle = np.zeros(n)                                          # fruscio da vinile, appena udibile
    pops = rng.random(n) < 0.0004
    crackle[pops] = rng.standard_normal(pops.sum()) * 0.12
    crackle += np.diff(rng.standard_normal(n), prepend=0) * 0.004
    left = pads * 0.9 + keys_ * 0.8 + echo * 0.6 + bass + drums + lead * 1.0 + lecho * 0.4 + crackle
    right = pads * 1.0 + keys_ * 0.6 + echo * 0.9 + bass + drums + lead * 0.8 + lecho * 0.6 + crackle
    mix = np.stack([left, right], axis=1)
    mix = np.tanh(mix * 0.9)                                       # compressione dolce
    mix /= max(1e-9, np.abs(mix).max()) / 0.85
    fade_in, fade_out = int(0.6 * RATE), int(1.2 * RATE)
    mix[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    mix[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    return mix


def write(path, seconds, seed=0):
    data = (track(seconds, seed) * 32767).astype("<i2")
    with wave.open(str(Path(path)), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data.tobytes())
    return path


# ---------------------------------------------------------------- brani da libreria (Pixabay Music) su Google Drive
# I file stanno nella cartella «Musica» dentro la cartella Drive del materiale (GDRIVE_FOLDER_ID), mai nel repository
# pubblico: la licenza Pixabay vieta di ridistribuire i brani così come sono. Il bot li usa solo dentro i video.
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
LAST_TRACK = {}


def _drive():
    import json
    import os
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(os.environ["GDRIVE_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _folder(drive, parent, name):
    q = (f"'{parent}' in parents and name = '{name}' and trashed = false "
         "and mimeType = 'application/vnd.google-apps.folder'")
    found = drive.files().list(q=q, fields="files(id)", supportsAllDrives=True,
                               includeItemsFromAllDrives=True).execute().get("files", [])
    return found[0]["id"] if found else None


def library_files(drive, mood=None):
    """Brani della cartella «Musica». `mood` = sottocartella per genere, anche più d'una in ordine di preferenza
    («Speciale|Funky»): si usa la prima che contiene brani, altrimenti i brani direttamente in «Musica».
    Generi: Classica = contenuti scientifici, Funky = posizioni accademiche, Rock = bandi."""
    import os
    root = _folder(drive, os.environ["GDRIVE_FOLDER_ID"], "Musica")
    if not root:
        return []
    for name in [*(mood.split("|") if mood else []), None]:
        folder = _folder(drive, root, name) if name else root
        if not folder:
            continue
        files = drive.files().list(q=f"'{folder}' in parents and trashed = false", pageSize=200,
                                   fields="files(id, name, mimeType)", supportsAllDrives=True,
                                   includeItemsFromAllDrives=True).execute().get("files", [])
        files = [f for f in files if f["name"].lower().endswith(AUDIO_EXT) or f["mimeType"].startswith("audio/")]
        if files:
            return sorted(files, key=lambda f: f["name"].lower())
    return []


def _download(drive, f, folder):
    import io
    from googleapiclient.http import MediaIoBaseDownload
    path = Path(folder) / f"{f['id']}{Path(f['name']).suffix or '.mp3'}"
    if not path.exists():
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, drive.files().get_media(fileId=f["id"], supportsAllDrives=True))
        done = False
        while not done:
            _, done = dl.next_chunk()
        path.write_bytes(buf.getvalue())
    return path


def best_start(path, seconds):
    """Inizio del tratto più pieno (di solito il ritornello), saltando l'intro e il finale."""
    import subprocess
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    total = len(x) / 8000
    if total <= seconds + 2:
        return 0.0
    env = np.sqrt(np.convolve(x ** 2, np.ones(8000) / 8000, mode="valid")[::8000])       # energia per secondo
    w = int(seconds)
    lo, hi = int(total * 0.12), int(min(total * 0.7, total - seconds - 1))
    if hi <= lo:
        return max(0.0, (total - seconds) / 2)
    scores = [env[s:s + w].mean() for s in range(lo, hi)]
    return float(lo + int(np.argmax(scores)))


def from_library(path, seconds, seed=0, cache=None, mood=None, track=None):
    """Scrive in `path` un estratto di un brano della cartella Drive «Musica» (diverso ogni giorno con il seme).
    Restituisce il nome del brano, oppure None se la cartella non è raggiungibile o è vuota."""
    import os
    import subprocess
    import tempfile
    if not (os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON") and os.environ.get("GDRIVE_FOLDER_ID")):
        return None
    drive = _drive()
    files = library_files(drive, mood)
    if not files:
        return None
    chosen = [f for f in files if track and f["name"] == track]      # brano scelto a mano (reel speciali)
    f = chosen[0] if chosen else files[seed % len(files)]
    src = _download(drive, f, cache or tempfile.gettempdir())
    start = best_start(src, seconds)
    fade_out = 1.2
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-ss", f"{start:.2f}", "-i", str(src),
                    "-t", f"{seconds:.2f}",
                    "-af", f"afade=t=in:d=0.4,afade=t=out:st={seconds - fade_out:.2f}:d={fade_out},"
                           "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", str(RATE), "-ac", "2", str(path)], check=True)
    return f["name"]


def for_video(path, seconds, seed=0, mood=None, track=None):
    """Musica per storie e reel: un brano della libreria su Drive; se non disponibile, la base generata qui."""
    LAST_TRACK.clear()
    try:
        name = from_library(path, seconds, seed, mood=mood, track=track)
        if name:
            LAST_TRACK["name"] = name
            print(f"::notice title=Musica::{name}")
            return path
    except Exception as e:
        print(f"::warning title=Musica dalla libreria non disponibile::{str(e)[:200]} (uso la base generata)")
    LAST_TRACK["name"] = f"generata (seme {seed})"
    return write(path, seconds, seed)
