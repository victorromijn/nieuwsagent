"""Haalt de volledige tekst op van vrij leesbare artikelen (geen betaalmuren)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import requests
import trafilatura

from .collect import Item
from .util import USER_AGENT, log

MAX_CHARS = 5000


def _fetch(item: Item) -> None:
    if not item.volledige_tekst_toegestaan or item.volledige_tekst:
        return
    try:
        resp = requests.get(item.link, headers={"User-Agent": USER_AGENT}, timeout=20)
        resp.raise_for_status()
        text = trafilatura.extract(resp.text, include_comments=False, include_tables=False) or ""
        item.volledige_tekst = text.strip()[:MAX_CHARS]
    except Exception as exc:  # noqa: BLE001
        log.info("Volledige tekst niet gelukt voor %s: %s", item.link, exc)


def enrich(items: list[Item]) -> None:
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(_fetch, items))
    n = sum(1 for it in items if it.volledige_tekst)
    log.info("Volledige tekst opgehaald voor %d van %d geselecteerde berichten", n, len(items))
