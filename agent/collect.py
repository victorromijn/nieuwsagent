"""Verzamelt nieuwsberichten uit RSS-feeds en Google News-zoekfeeds."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import requests

from .util import USER_AGENT, clean_html, log, short_id

MAX_ITEMS = 650


@dataclass
class Item:
    id: str
    bron: str
    rubriek: str
    titel: str
    samenvatting: str
    link: str
    gepubliceerd: str          # ISO-tijd in UTC, of "" als onbekend
    gewicht: int
    volledige_tekst_toegestaan: bool
    volledige_tekst: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def google_news_url(query: str, hours: int, lang: str) -> str:
    q = quote_plus(f"{query} when:{max(1, hours)}h")
    if lang == "en":
        return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    return f"https://news.google.com/rss/search?q={q}&hl=nl&gl=NL&ceid=NL:nl"


def feed_url(bron: dict, hours: int) -> str:
    if bron.get("soort") == "google_news":
        return google_news_url(bron["zoek"], hours, bron.get("taal", "nl"))
    return bron["url"]


def _parse_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def fetch_feed(bron: dict, hours: int) -> tuple[dict, list[Item], str]:
    """Geeft (bron, items, foutmelding) terug. Een kapotte feed stopt de uitzending niet."""
    url = feed_url(bron, hours)
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as exc:  # noqa: BLE001
        return bron, [], f"{type(exc).__name__}: {exc}"

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items: list[Item] = []
    for i, entry in enumerate(parsed.entries):
        title = clean_html(entry.get("title", ""))
        if not title:
            continue
        published = _parse_time(entry)
        if published and published < cutoff:
            continue
        if not published and i >= 15:
            continue
        summary = clean_html(entry.get("summary", ""))
        source_name = bron["naam"]
        if bron.get("soort") == "google_news":
            # Google News zet de bron achter de titel: "Titel - Reuters"
            m = re.match(r"^(.*)\s+-\s+([^-]+)$", title)
            if m:
                title, source_name = m.group(1).strip(), m.group(2).strip()
            summary = ""  # Google News-samenvatting is alleen de titel nog eens
        items.append(Item(
            id=short_id(entry.get("link", "") + title),
            bron=source_name,
            rubriek=bron.get("rubriek", "algemeen"),
            titel=title,
            samenvatting=summary[:600],
            link=entry.get("link", ""),
            gepubliceerd=published.isoformat() if published else "",
            gewicht=int(bron.get("gewicht", 1)),
            volledige_tekst_toegestaan=bool(bron.get("volledige_tekst", False)),
        ))
    return bron, items, ""


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower())[:80]


def collect(bronnen: list[dict], hours: int) -> tuple[list[Item], list[str]]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda b: fetch_feed(b, hours), bronnen))

    problemen, alle = [], []
    for bron, items, fout in results:
        label = bron["naam"] + " (" + bron.get("rubriek", "") + ")"
        if fout:
            problemen.append(f"{label}: {fout}")
        elif not items:
            problemen.append(f"{label}: geen berichten in de afgelopen {hours} uur")
        alle.extend(items)

    # Dubbele berichten eruit (zelfde link of vrijwel dezelfde titel), zwaarste bron wint
    def _ts(it: Item) -> float:
        return datetime.fromisoformat(it.gepubliceerd).timestamp() if it.gepubliceerd else 0.0

    alle.sort(key=lambda it: (-it.gewicht, -_ts(it)))
    gezien_links, gezien_titels, uniek = set(), set(), []
    for it in alle:
        n = _norm(it.titel)
        if it.link in gezien_links or n in gezien_titels:
            continue
        gezien_links.add(it.link)
        gezien_titels.add(n)
        uniek.append(it)

    uniek = uniek[:MAX_ITEMS]
    log.info("Verzameld: %d unieke berichten uit %d feeds (%d met problemen)",
             len(uniek), len(bronnen), len(problemen))
    return uniek, problemen
