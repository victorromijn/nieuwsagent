"""Hulpfuncties: configuratie, datums in het Nederlands, prompts en logging."""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("nieuwsagent")

DAGEN = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli",
           "augustus", "september", "oktober", "november", "december"]

USER_AGENT = "Mozilla/5.0 (compatible; Nieuwsagent/1.0; persoonlijk gebruik)"


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_yaml(name: str) -> dict:
    with open(ROOT / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def now_local(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def datum_nl(d: datetime) -> str:
    """Bijvoorbeeld: vrijdag 7 november 2026."""
    return f"{DAGEN[d.weekday()]} {d.day} {MAANDEN[d.month - 1]} {d.year}"


def short_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:7]


def clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def render_prompt(name: str, values: dict) -> str:
    """Laadt prompts/<name>.md en vult {{sleutel}} in."""
    text = (ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")
    for key, val in values.items():
        text = text.replace("{{" + key + "}}", str(val))
    missing = re.findall(r"\{\{(\w+)\}\}", text)
    if missing:
        raise ValueError(f"Prompt {name}: geen waarde voor {missing}")
    return text


def env(name: str, required: bool = True) -> str:
    val = os.environ.get(name, "").strip()
    if required and not val:
        raise RuntimeError(f"Geheime sleutel {name} ontbreekt. Zie de handleiding, stap 'Sleutels in GitHub'.")
    return val
