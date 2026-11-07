"""Start de nieuwsagent: python -m agent.main --editie ochtend|avond|auto [--proef] [--forceer]"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
from pathlib import Path

from . import deliver, editor, extras
from .audio import maak_uitzending
from .collect import Item, collect
from .llm import Claude, NepClaude
from .tts import GoogleTTS, NepTTS
from .util import ROOT, datum_nl, load_yaml, log, now_local, setup_logging

ARCHIEF = ROOT / "archive" / "afleveringen.json"
PRIJZEN_USD = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0)}  # per miljoen tokens


def laad_archief() -> list[dict]:
    if ARCHIEF.exists():
        return json.loads(ARCHIEF.read_text(encoding="utf-8"))
    return []


def bewaar_archief(archief: list[dict]) -> None:
    ARCHIEF.parent.mkdir(parents=True, exist_ok=True)
    ARCHIEF.write_text(json.dumps(archief, ensure_ascii=False, indent=1), encoding="utf-8")


def kosten_usd(verbruik: list[dict]) -> float:
    totaal = 0.0
    for v in verbruik:
        pin, pout = PRIJZEN_USD.get(v["model"], (0.0, 0.0))
        totaal += v["invoer_tokens"] / 1e6 * pin + v["uitvoer_tokens"] / 1e6 * pout
    return round(totaal, 4)


def bewaar_script(pad: Path, script: dict, gebruikt: list[Item], wijzigingen: list[dict], kop: str) -> None:
    regels = [f"# {kop}", "", f"**{script.get('titel', '')}**", ""]
    for s in script["segmenten"]:
        regels.append(f"**{s['spreker'].capitalize()}** ({s['blok']}): {s['tekst']}")
        regels.append("")
    regels += ["## Bronnen", ""]
    regels += [f"- [{it.id}] {it.bron}: {it.titel} {it.link}" for it in gebruikt]
    if wijzigingen:
        regels += ["", "## Aanpassingen door de feitencheck", ""]
        regels += [f"- #{w['index']}: {w['probleem']}" for w in wijzigingen]
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text("\n".join(regels), encoding="utf-8")


def laad_proefitems() -> list[Item]:
    data = json.loads((ROOT / "tests" / "fixtures" / "items.json").read_text(encoding="utf-8"))
    return [Item(**d) for d in data]


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--editie", default="auto", choices=["auto", "ochtend", "avond"])
    ap.add_argument("--proef", action="store_true", help="zonder sleutels en internet, met testdata")
    ap.add_argument("--forceer", action="store_true", help="ook maken als deze editie vandaag al verstuurd is")
    ap.add_argument("--geen-levering", action="store_true", help="niet versturen, alleen maken")
    args = ap.parse_args(argv)

    cfg = load_yaml("config.yaml")
    tz = cfg["luisteraar"]["tijdzone"]
    nu = now_local(tz)
    naam = args.editie if args.editie != "auto" else ("ochtend" if nu.hour < 13 else "avond")
    ed = cfg["edities"][naam]
    vandaag = nu.strftime("%Y-%m-%d")
    context = {"datum": datum_nl(nu)}

    archief = laad_archief()
    if not args.forceer and not args.proef and any(
            a["datum"] == vandaag and a["editie"] == naam and a.get("telegram") for a in archief):
        log.info("De %s van %s is al verstuurd. Niets te doen.", naam, vandaag)
        return 0

    levering = not (args.proef or args.geen_levering)
    try:
        llm = NepClaude() if args.proef else Claude()
        tts = (NepTTS if args.proef else GoogleTTS)(cfg["stemmen"].get("spreeksnelheid", 1.0))

        if args.proef:
            items, problemen = laad_proefitems(), []
            extra = json.loads((ROOT / "tests" / "fixtures" / "extras.json").read_text(encoding="utf-8"))
        else:
            bronnen = load_yaml("feeds.yaml")["bronnen"]
            items, problemen = collect(bronnen, ed["terugkijken_uren"])
            if len(items) < 15:
                raise RuntimeError(f"Te weinig nieuws binnengekomen ({len(items)} berichten). Problemen: {problemen[:5]}")
            extra = extras.verzamel(cfg, ed, nu)

        vorige = archief[-1].get("onderwerpen", []) if archief else []
        keuze = editor.selecteer(llm, cfg, ed, items, vorige, context)
        pakket, gebruikt = editor.bronpakket(keuze, items, tz)
        script = editor.schrijf(llm, cfg, ed, pakket, extra, context)
        script, wijzigingen = editor.feitencheck(llm, cfg, script, pakket, extra, context)
        if len(script["segmenten"]) < 5:
            raise RuntimeError("Het script is te kort geworden na de feitencheck.")

        uitmap = ROOT / "output"
        uitmap.mkdir(exist_ok=True)
        bestand = f"{vandaag}-{naam}.mp3"
        mp3 = uitmap / bestand
        werkmap = uitmap / "werk"
        shutil.rmtree(werkmap, ignore_errors=True)
        titel = f"{ed['titel']} {datum_nl(nu)}"
        duur_sec = maak_uitzending(
            script, cfg["stemmen"], tts, werkmap, mp3, ed["max_minuten"],
            {"title": titel, "artist": "Nieuwsagent", "album": cfg["podcast"]["titel"], "date": vandaag},
        )

        aflevering = {
            "datum": vandaag, "editie": naam, "titel": titel, "bestand": bestand,
            "gemaakt": nu.isoformat(), "duur_sec": round(duur_sec), "bytes": mp3.stat().st_size,
            "omschrijving": script.get("titel", ""),
            "onderwerpen": script.get("onderwerpen", []), "woorden": script["woorden"],
            "tts_tekens": tts.tekens, "claude_kosten_usd": kosten_usd(llm.verbruik),
            "feitencheck_aanpassingen": len(wijzigingen), "feeds_met_problemen": problemen,
            "telegram": False, "podcast": False,
        }
        scriptmap = uitmap if args.proef else ROOT / "archive" / "scripts"
        bewaar_script(scriptmap / f"{vandaag}-{naam}.md", script, gebruikt, wijzigingen, titel)
        log.info("Kosten Claude: $%.4f, tekens spraak: %d", aflevering["claude_kosten_usd"], tts.tekens)

        if levering:
            minuten = round(duur_sec / 60)
            deliver.telegram_audio(mp3, titel, f"{ed['titel']}, {datum_nl(nu)}, {minuten} minuten", duur_sec)
            aflevering["telegram"] = True
            if deliver.podcast_actief():
                try:
                    deliver.podcast_publiceer(cfg, mp3, aflevering, archief, werkmap)
                    aflevering["podcast"] = True
                except Exception as exc:  # noqa: BLE001
                    log.error("Podcastfeed niet gelukt: %s", exc)
                    deliver.telegram_tekst(f"Let op: de uitzending staat in Telegram, maar de podcastfeed kon niet worden bijgewerkt ({exc}).")

        archief.append(aflevering)
        if not args.proef:
            bewaar_archief(archief)
        shutil.rmtree(werkmap, ignore_errors=True)
        log.info("Klaar: %s", mp3)
        return 0

    except Exception as exc:  # noqa: BLE001
        log.error("Uitzending mislukt: %s\n%s", exc, traceback.format_exc())
        if levering:
            deliver.telegram_tekst(
                f"De {naam}editie van {datum_nl(nu)} is niet gelukt.\nFout: {exc}\n"
                "Kijk op GitHub bij Actions voor details, of start hem daar opnieuw.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
