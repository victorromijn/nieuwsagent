# Nieuwsagent

Persoonlijke Nederlandstalige nieuwsuitzending, elke ochtend en avond op je telefoon via Telegram en een privé podcastfeed.

## Hoe het werkt

1. Verzamelen: RSS- en Google News-feeds uit `feeds.yaml`, plus weer (Open-Meteo), euro-dollar (ECB) en vandaag in de geschiedenis (Wikipedia).
2. Selectie: Claude Haiku kiest 5 tot 7 hoofditems, kort nieuws, regionaal en opmerkelijk nieuws (`prompts/selectie.md`).
3. Script: Claude Sonnet schrijft een script voor twee stemmen, lezer en duider (`prompts/script.md`).
4. Feitencheck: Claude Haiku legt elke bewering naast de bronnen en schrapt of verbetert wat niet klopt (`prompts/feitencheck.md`).
5. Audio: Google Chirp 3 HD-stemmen met eigen jingles, samengevoegd tot één mp3 van maximaal 15 minuten.
6. Bezorgen: Telegram, en als je hem hebt ingesteld ook de podcastfeed op je eigen hosting.
7. Archief: elk script met bronnen staat in `archive/scripts`, de lijst met uitzendingen in `archive/afleveringen.json`.

## Aanpassen

- Persoonlijke instellingen, stemmen en modellen: `config.yaml`
- Nieuwsbronnen: `feeds.yaml`
- Redactieregels: de bestanden in `prompts/`
- Eigen jingles: zet `intro.mp3`, `overgang.mp3` en `outro.mp3` in `assets/`

## Handmatig starten

GitHub > Actions > Nieuwsuitzending > Run workflow.

## Testen zonder sleutels

```
pip install -r requirements.txt pytest
python -m pytest tests
python -m agent.main --proef
```
