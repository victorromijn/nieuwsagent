"""De redactie: selecteren (Haiku), schrijven (Sonnet) en feitencheck (Haiku)."""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from . import fulltext
from .collect import Item
from .util import log, render_prompt

GELDIGE_BLOKKEN = {"opening", "koppen", "item", "kort", "regionaal", "markt",
                   "weer", "agenda", "licht", "afsluiting"}
WOORDEN_PER_MINUUT = 140


def _tijd(item: Item, tz: str) -> str:
    if not item.gepubliceerd:
        return "tijd onbekend"
    return datetime.fromisoformat(item.gepubliceerd).astimezone(ZoneInfo(tz)).strftime("%d-%m %H:%M")


def _lijst_voor_selectie(items: list[Item], tz: str) -> str:
    regels = []
    for it in items:
        s = it.samenvatting[:280]
        regels.append(f"[{it.id}] {it.bron} | {it.rubriek} | {_tijd(it, tz)} | {it.titel}" + (f" :: {s}" if s else ""))
    return "\n".join(regels)


def selecteer(llm, cfg: dict, editie: dict, items: list[Item], vorige: list[str], context: dict) -> dict:
    system = render_prompt("selectie", {
        "naam": cfg["luisteraar"]["naam"],
        "editie": editie["titel"],
        "datum": context["datum"],
        "focus": "\n".join(f"- {f}" for f in cfg["focus"]),
        "vorige_onderwerpen": "\n".join(f"- {v}" for v in vorige) or "- (geen)",
    })
    user = "BERICHTEN:\n" + _lijst_voor_selectie(items, cfg["luisteraar"]["tijdzone"])
    inst = cfg.get("inspanning", {}).get("selectie", {})
    keuze = llm.json("selectie", cfg["modellen"]["selectie"], system, user, max_tokens=16000,
                     inspanning=inst.get("niveau"), denken=inst.get("nadenken", False))

    bekend = {it.id for it in items}
    for sectie in ("hoofditems", "kort_nieuws", "regionaal", "opmerkelijk", "agenda"):
        schoon = []
        for onderwerp in keuze.get(sectie, []) or []:
            ids = [i for i in onderwerp.get("item_ids", []) if i in bekend]
            if ids:
                onderwerp["item_ids"] = ids[:4]
                schoon.append(onderwerp)
        keuze[sectie] = schoon
    keuze["hoofditems"] = keuze["hoofditems"][:7]
    log.info("Selectie: %d hoofditems, %d kort, %d regionaal",
             len(keuze["hoofditems"]), len(keuze["kort_nieuws"]), len(keuze["regionaal"]))
    return keuze


def bronpakket(keuze: dict, items: list[Item], tz: str) -> tuple[str, list[Item]]:
    """Maakt het bronnenpakket voor de schrijver en haalt volledige teksten op."""
    per_id = {it.id: it for it in items}
    gebruikt: list[Item] = []
    volledige_voor: set[str] = set()
    for sectie in ("hoofditems", "kort_nieuws", "regionaal", "opmerkelijk", "agenda"):
        for onderwerp in keuze.get(sectie, []):
            for n, i in enumerate(onderwerp["item_ids"]):
                if per_id[i] not in gebruikt:
                    gebruikt.append(per_id[i])
                if sectie == "hoofditems" or n == 0:
                    volledige_voor.add(i)
    fulltext.enrich([it for it in gebruikt if it.id in volledige_voor])

    namen = {"hoofditems": "HOOFDITEM", "kort_nieuws": "KORT NIEUWS", "regionaal": "REGIONAAL",
             "opmerkelijk": "OPMERKELIJK", "agenda": "AGENDA"}
    delen = []
    for sectie, label in namen.items():
        for nr, onderwerp in enumerate(keuze.get(sectie, []), 1):
            kop = f"=== {label} {nr}: {onderwerp.get('onderwerp', '')}"
            if onderwerp.get("rubriek"):
                kop += f" ({onderwerp['rubriek']})"
            delen.append(kop + " ===")
            for i in onderwerp["item_ids"]:
                it = per_id[i]
                blok = [f"[{it.id}] Bron: {it.bron} | gepubliceerd: {_tijd(it, tz)}",
                        f"Titel: {it.titel}"]
                if it.samenvatting:
                    blok.append(f"Samenvatting: {it.samenvatting}")
                if it.volledige_tekst:
                    tekst = it.volledige_tekst if sectie == "hoofditems" else it.volledige_tekst[:1500]
                    blok.append(f"Artikeltekst: {tekst}")
                elif not it.volledige_tekst_toegestaan:
                    blok.append("(Alleen kop en intro beschikbaar, betaalmuur of zoekfeed.)")
                delen.append("\n".join(blok))
    return "\n\n".join(delen), gebruikt


def schrijf(llm, cfg: dict, editie: dict, pakket: str, extras: dict, context: dict) -> dict:
    max_woorden = int(editie["max_minuten"] * WOORDEN_PER_MINUUT) - 60
    system = render_prompt("script", {
        "naam": cfg["luisteraar"]["naam"],
        "begroeting": editie["begroeting"],
        "editie": editie["titel"],
        "datum": context["datum"],
        "vooruitblik": editie["vooruitblik"],
        "weer_voor": editie["weer_voor"],
        "max_woorden": max_woorden,
        "focus": "\n".join(f"- {f}" for f in cfg["focus"]),
    })
    user = ("BRONNEN:\n\n" + pakket +
            "\n\nVASTE GEGEVENS (weer, koers, geschiedenis):\n" +
            json.dumps(extras, ensure_ascii=False, indent=1))
    inst = cfg.get("inspanning", {}).get("script", {})
    script = llm.json("script", cfg["modellen"]["script"], system, user, max_tokens=40000,
                      inspanning=inst.get("niveau", "medium"), denken=inst.get("nadenken", True))
    return _schoon_script(script)


def _schoon_script(script: dict) -> dict:
    segs = []
    for s in script.get("segmenten", []):
        tekst = (s.get("tekst") or "").strip()
        if not tekst:
            continue
        segs.append({
            "blok": s.get("blok") if s.get("blok") in GELDIGE_BLOKKEN else "item",
            "spreker": "duider" if s.get("spreker") == "duider" else "lezer",
            "tekst": tekst,
            "bron_ids": s.get("bron_ids", []) or [],
        })
    script["segmenten"] = segs
    script["woorden"] = sum(len(s["tekst"].split()) for s in segs)
    log.info("Script: %d segmenten, %d woorden", len(segs), script["woorden"])
    return script


def feitencheck(llm, cfg: dict, script: dict, pakket: str, extras: dict, context: dict) -> tuple[dict, list[dict]]:
    system = render_prompt("feitencheck", {"datum": context["datum"], "naam": cfg["luisteraar"]["naam"]})
    genummerd = "\n".join(f"#{i} [{s['blok']}|{s['spreker']}] {s['tekst']}"
                          for i, s in enumerate(script["segmenten"]))
    user = ("SCRIPT:\n" + genummerd + "\n\nBRONNEN:\n\n" + pakket +
            "\n\nVASTE GEGEVENS:\n" + json.dumps(extras, ensure_ascii=False, indent=1))
    inst = cfg.get("inspanning", {}).get("feitencheck", {})
    oordeel = llm.json("feitencheck", cfg["modellen"]["feitencheck"], system, user, max_tokens=32000,
                       inspanning=inst.get("niveau", "medium"), denken=inst.get("nadenken", True))

    wijzigingen = []
    segs = script["segmenten"]
    for w in oordeel.get("wijzigingen", []) or []:
        i = w.get("index")
        if not isinstance(i, int) or not 0 <= i < len(segs):
            continue
        nieuw = (w.get("nieuwe_tekst") or "").strip()
        wijzigingen.append({"index": i, "oud": segs[i]["tekst"], "nieuw": nieuw, "probleem": w.get("probleem", "")})
        segs[i]["tekst"] = nieuw
    script["segmenten"] = [s for s in segs if s["tekst"]]
    script["woorden"] = sum(len(s["tekst"].split()) for s in script["segmenten"])
    log.info("Feitencheck: %d aanpassingen", len(wijzigingen))
    return script, wijzigingen
