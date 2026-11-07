"""Maakt eenvoudige, eigen jingles (geen auteursrecht van derden).

Wil je eigen jingles? Zet dan intro.mp3, overgang.mp3 en outro.mp3 in de map assets.
Die worden dan automatisch gebruikt in plaats van deze.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100


def _toon(freq: float, duur: float, volume: float = 0.25) -> np.ndarray:
    t = np.linspace(0, duur, int(SR * duur), endpoint=False)
    golf = (np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(2 * np.pi * freq * 2 * t)
            + 0.12 * np.sin(2 * np.pi * freq * 3 * t))
    aanzet = np.minimum(1.0, t / 0.02)
    uitsterf = np.exp(-3.2 * t / duur)
    return volume * golf * aanzet * uitsterf


def _mix(noten: list[tuple[float, float, float]], totaal: float) -> np.ndarray:
    """noten: (starttijd, frequentie, duur)."""
    buf = np.zeros(int(SR * totaal))
    for start, freq, duur in noten:
        s = int(SR * start)
        toon = _toon(freq, duur)
        buf[s:s + len(toon)] += toon[: len(buf) - s]
    piek = np.max(np.abs(buf)) or 1.0
    return buf / piek * 0.6


def _schrijf(pad: Path, data: np.ndarray) -> None:
    pcm = (data * 32767).astype(np.int16)
    with wave.open(str(pad), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def zorg_voor_jingles(map_: Path) -> dict[str, Path]:
    map_.mkdir(parents=True, exist_ok=True)
    C5, E5, G5, C6, D5 = 523.25, 659.25, 783.99, 1046.5, 587.33
    ontwerpen = {
        "intro": ([(0.0, C5, 1.2), (0.18, E5, 1.2), (0.36, G5, 1.4), (0.6, C6, 1.8)], 2.6),
        "overgang": ([(0.0, G5, 0.6), (0.14, D5, 0.8)], 1.0),
        "outro": ([(0.0, C6, 1.2), (0.2, G5, 1.2), (0.4, E5, 1.4), (0.65, C5, 2.0)], 2.8),
    }
    paden = {}
    for naam, (noten, duur) in ontwerpen.items():
        eigen = map_ / f"{naam}.mp3"
        if eigen.exists():
            paden[naam] = eigen
            continue
        pad = map_ / f"{naam}.wav"
        if not pad.exists():
            _schrijf(pad, _mix(noten, duur))
        paden[naam] = pad
    return paden
