"""Tekst naar spraak via Google Cloud Text-to-Speech (Chirp 3 HD-stemmen)."""
from __future__ import annotations

import base64
import re
import subprocess
from pathlib import Path

import requests

from .util import env, log

API = "https://texttospeech.googleapis.com/v1/text:synthesize"
MAX_CHUNK = 1200


def _chunks(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK:
        return [text]
    zinnen = re.split(r"(?<=[.!?])\s+", text)
    delen, huidig = [], ""
    for z in zinnen:
        if huidig and len(huidig) + len(z) + 1 > MAX_CHUNK:
            delen.append(huidig)
            huidig = z
        else:
            huidig = f"{huidig} {z}".strip()
    if huidig:
        delen.append(huidig)
    return delen


class GoogleTTS:
    def __init__(self, snelheid: float = 1.0) -> None:
        self.key = env("GOOGLE_TTS_API_KEY")
        self.snelheid = snelheid
        self.tekens = 0

    def _call(self, text: str, stem: str, met_snelheid: bool) -> bytes:
        body = {
            "input": {"text": text},
            "voice": {"languageCode": stem[:5], "name": stem},
            "audioConfig": {"audioEncoding": "MP3", "sampleRateHertz": 24000},
        }
        if met_snelheid and self.snelheid != 1.0:
            body["audioConfig"]["speakingRate"] = self.snelheid
        resp = requests.post(API, params={"key": self.key}, json=body, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"Google TTS fout {resp.status_code}: {resp.text[:300]}")
        return base64.b64decode(resp.json()["audioContent"])

    def spreek(self, text: str, stem: str, uit: Path) -> list[Path]:
        paden = []
        for n, deel in enumerate(_chunks(text)):
            self.tekens += len(deel)
            try:
                audio = self._call(deel, stem, met_snelheid=True)
            except RuntimeError as exc:
                if "speakingRate" in str(exc) or "speaking_rate" in str(exc):
                    log.warning("Spreeksnelheid niet ondersteund, opnieuw zonder")
                    audio = self._call(deel, stem, met_snelheid=False)
                else:
                    raise
            pad = uit.with_name(f"{uit.stem}_{n}.mp3")
            pad.write_bytes(audio)
            paden.append(pad)
        return paden


class NepTTS:
    """Proefrun: een zachte toon in plaats van spraak, lengte naar aantal woorden."""

    def __init__(self, snelheid: float = 1.0) -> None:
        self.tekens = 0

    def spreek(self, text: str, stem: str, uit: Path) -> list[Path]:
        self.tekens += len(text)
        duur = max(1.0, len(text.split()) / 2.4)
        freq = 330 if "Aoede" in stem else 220
        pad = uit.with_name(f"{uit.stem}_0.mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
             f"sine=frequency={freq}:duration={duur:.2f}", "-af", "volume=0.05",
             "-ar", "24000", "-ac", "1", str(pad)],
            check=True,
        )
        return [pad]
