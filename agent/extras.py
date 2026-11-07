"""Vaste rubrieken met harde cijfers: weer, euro-dollar en vandaag in de geschiedenis.

Alle cijfers worden hier in code berekend, zodat het taalmodel ze alleen hoeft voor te lezen.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

from .util import USER_AGENT, log

WMO = {
    0: "onbewolkt", 1: "overwegend zonnig", 2: "half bewolkt", 3: "bewolkt",
    45: "mist", 48: "mist met rijp", 51: "lichte motregen", 53: "motregen",
    55: "dichte motregen", 56: "lichte ijzel", 57: "ijzel", 61: "lichte regen",
    63: "regen", 65: "zware regen", 66: "lichte ijzelregen", 67: "ijzelregen",
    71: "lichte sneeuw", 73: "sneeuw", 75: "zware sneeuw", 77: "korrelsneeuw",
    80: "lichte regenbuien", 81: "regenbuien", 82: "zware regenbuien",
    85: "lichte sneeuwbuien", 86: "zware sneeuwbuien", 95: "onweer",
    96: "onweer met hagel", 99: "zwaar onweer met hagel",
}
BEAUFORT_KMH = [1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118]
RICHTINGEN = ["noord", "noordoost", "oost", "zuidoost", "zuid", "zuidwest", "west", "noordwest"]


def beaufort(kmh: float) -> int:
    for bft, grens in enumerate(BEAUFORT_KMH):
        if kmh < grens:
            return bft
    return 12


def richting(graden: float) -> str:
    return RICHTINGEN[int(((graden % 360) + 22.5) // 45) % 8]


def _get(url: str) -> requests.Response:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    return resp


def weer(plaatsen: list[dict], dag: datetime) -> list[dict]:
    """Verwachting per plaats voor de gegeven dag (lokale datum)."""
    datum = dag.strftime("%Y-%m-%d")
    uit = []
    for p in plaatsen:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={p['lat']}&longitude={p['lon']}"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
            "precipitation_probability_max,wind_speed_10m_max,wind_direction_10m_dominant"
            "&hourly=precipitation_probability,precipitation,wind_speed_10m,wind_direction_10m,temperature_2m"
            "&timezone=Europe%2FAmsterdam&forecast_days=3"
        )
        try:
            data = _get(url).json()
        except Exception as exc:  # noqa: BLE001
            log.warning("Weer voor %s niet gelukt: %s", p["naam"], exc)
            continue
        d = data["daily"]
        if datum not in d["time"]:
            continue
        i = d["time"].index(datum)
        info = {
            "plaats": p["naam"],
            "landelijk_beeld": bool(p.get("landelijk")),
            "datum": datum,
            "omschrijving": WMO.get(d["weather_code"][i], "wisselend"),
            "max_temp_c": round(d["temperature_2m_max"][i]),
            "min_temp_c": round(d["temperature_2m_min"][i]),
            "neerslag_mm": round(d["precipitation_sum"][i], 1),
            "kans_op_neerslag_pct": d["precipitation_probability_max"][i],
            "wind_bft": beaufort(d["wind_speed_10m_max"][i]),
            "windrichting": richting(d["wind_direction_10m_dominant"][i]),
        }
        if p.get("fietsweer"):
            h = data["hourly"]
            blokken = {"ochtendspits 7 tot 9 uur": (7, 9), "middagspits 16 tot 18 uur": (16, 18)}
            fiets = {}
            for naam, (van, tot) in blokken.items():
                idx = [k for k, t in enumerate(h["time"])
                       if t.startswith(datum) and van <= int(t[11:13]) <= tot]
                if not idx:
                    continue
                fiets[naam] = {
                    "kans_op_neerslag_pct": max(h["precipitation_probability"][k] or 0 for k in idx),
                    "neerslag_mm": round(sum(h["precipitation"][k] or 0 for k in idx), 1),
                    "wind_bft": beaufort(max(h["wind_speed_10m"][k] for k in idx)),
                    "windrichting": richting(h["wind_direction_10m"][idx[0]]),
                    "temp_c": round(sum(h["temperature_2m"][k] for k in idx) / len(idx)),
                }
            info["fietsweer"] = fiets
        uit.append(info)
    return uit


def euro_dollar() -> dict | None:
    """ECB-referentiekoers (vastgesteld rond 16:00 op werkdagen)."""
    try:
        root = ET.fromstring(_get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml").content)
    except Exception as exc:  # noqa: BLE001
        log.warning("Euro-dollarkoers niet gelukt: %s", exc)
        return None
    koersen = []
    for cube in root.iter():
        if cube.get("time"):
            for c in cube:
                if c.get("currency") == "USD":
                    koersen.append((cube.get("time"), float(c.get("rate"))))
    koersen.sort(reverse=True)
    if len(koersen) < 2:
        return None
    (d1, k1), (d0, k0) = koersen[0], koersen[1]
    verschil = (k1 - k0) / k0 * 100
    return {
        "datum_koers": d1,
        "een_euro_in_dollar": f"{k1:.4f}".replace(".", ","),
        "vorige_koers": f"{k0:.4f}".replace(".", ","),
        "verandering_pct": f"{verschil:+.2f}".replace(".", ","),
        "bron": "Europese Centrale Bank, referentiekoers",
    }


def vandaag_in_de_geschiedenis(dag: datetime) -> list[dict]:
    mm, dd = f"{dag.month:02d}", f"{dag.day:02d}"
    for taal in ("nl", "en"):
        url = f"https://api.wikimedia.org/feed/v1/wikipedia/{taal}/onthisday/selected/{mm}/{dd}"
        try:
            data = _get(url).json()
        except Exception:  # noqa: BLE001
            continue
        events = [{"jaar": e.get("year"), "gebeurtenis": e.get("text", ""), "taal": taal}
                  for e in data.get("selected", []) if e.get("text")]
        if events:
            return events[:8]
    log.warning("Vandaag in de geschiedenis niet gelukt")
    return []


def verzamel(cfg: dict, editie: dict, nu: datetime) -> dict:
    weer_dag = nu if editie["weer_voor"] == "vandaag" else nu + timedelta(days=1)
    return {
        "weer": weer(cfg["weer"], weer_dag),
        "euro_dollar": euro_dollar(),
        "vandaag_in_de_geschiedenis": vandaag_in_de_geschiedenis(nu),
    }
