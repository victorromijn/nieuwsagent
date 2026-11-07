"""Controleert alle feeds en stuurt een overzicht naar Telegram: python -m agent.feedcheck"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from . import deliver
from .collect import fetch_feed
from .util import load_yaml, setup_logging


def main() -> None:
    setup_logging()
    bronnen = load_yaml("feeds.yaml")["bronnen"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        resultaten = list(pool.map(lambda b: fetch_feed(b, 24), bronnen))

    goed, slecht = [], []
    for bron, items, fout in resultaten:
        label = f"{bron['naam']} ({bron.get('rubriek', '')})"
        if fout or not items:
            slecht.append(f"- {label}: {fout or 'geen berichten in 24 uur'}")
        else:
            goed.append(f"- {label}: {len(items)} berichten")

    rapport = (f"Feedcontrole: {len(goed)} werken, {len(slecht)} met problemen.\n\n"
               "Werkt:\n" + "\n".join(goed) + "\n\nProblemen:\n" + ("\n".join(slecht) or "- geen"))
    print(rapport)
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        deliver.telegram_tekst(rapport)


if __name__ == "__main__":
    main()
