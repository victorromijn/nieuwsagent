"""Zet spraak en jingles achter elkaar tot één mp3."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .jingles import zorg_voor_jingles
from .util import ROOT, log

GROEP = {"opening": "A", "koppen": "A", "item": "B", "kort": "C", "regionaal": "C",
         "markt": "D", "weer": "D", "agenda": "D", "licht": "E", "afsluiting": "E"}
SR = 44100


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def duur(pad: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(pad)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def _naar_wav(bron: Path, doel: Path) -> Path:
    _ff("-i", str(bron), "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(doel))
    return doel


def _stilte(sec: float, doel: Path) -> Path:
    if not doel.exists():
        _ff("-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono", "-t", f"{sec}", "-c:a", "pcm_s16le", str(doel))
    return doel


def maak_uitzending(script: dict, stemmen: dict, tts, werkmap: Path, uit: Path,
                    max_minuten: float, meta: dict) -> float:
    werkmap.mkdir(parents=True, exist_ok=True)
    jingles = zorg_voor_jingles(ROOT / "assets")
    kort, mid, lang = (_stilte(s, werkmap / f"stilte_{s}.wav") for s in (0.15, 0.4, 0.7))

    reeks: list[Path] = [_naar_wav(jingles["intro"], werkmap / "j_intro.wav"), mid]
    overgang = _naar_wav(jingles["overgang"], werkmap / "j_overgang.wav")
    vorige_groep = "A"
    for i, seg in enumerate(script["segmenten"]):
        groep = GROEP.get(seg["blok"], "B")
        if groep != vorige_groep:
            reeks += [lang, overgang, mid]
            vorige_groep = groep
        stem = stemmen["duider"] if seg["spreker"] == "duider" else stemmen["lezer"]
        delen = tts.spreek(seg["tekst"], stem, werkmap / f"seg_{i:03d}.mp3")
        for n, deel in enumerate(delen):
            reeks.append(_naar_wav(deel, werkmap / f"seg_{i:03d}_{n}.wav"))
            reeks.append(kort if n < len(delen) - 1 else mid)
    reeks += [lang, _naar_wav(jingles["outro"], werkmap / "j_outro.wav")]

    lijst = werkmap / "lijst.txt"
    lijst.write_text("".join(f"file '{p.resolve()}'\n" for p in reeks), encoding="utf-8")
    ruw = werkmap / "ruw.wav"
    _ff("-f", "concat", "-safe", "0", "-i", str(lijst), "-c", "copy", str(ruw))

    lengte = duur(ruw)
    filters = ["loudnorm=I=-16:TP=-1.5:LRA=11"]
    max_sec = max_minuten * 60
    if lengte > max_sec:
        factor = min(1.10, lengte / max_sec)
        filters.insert(0, f"atempo={factor:.3f}")
        log.warning("Uitzending %.0f s, versneld met factor %.3f", lengte, factor)

    tags = []
    for k, v in meta.items():
        tags += ["-metadata", f"{k}={v}"]
    _ff("-i", str(ruw), "-af", ",".join(filters), "-ar", str(SR), "-ac", "1",
        "-c:a", "libmp3lame", "-b:a", "64k", *tags, str(uit))
    eind = duur(uit)
    log.info("Uitzending klaar: %s (%.1f minuten, %.1f MB)", uit.name, eind / 60, uit.stat().st_size / 1e6)
    return eind
