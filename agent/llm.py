"""Aanroepen van Claude met JSON-antwoorden, plus een nep-versie voor de proefrun."""
from __future__ import annotations

import json
import re

from .util import env, log


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


class Claude:
    """Stuurt de sleutel als Bearer-token (aanbevolen), met x-api-key als reserve."""

    def __init__(self) -> None:
        import os
        import anthropic
        self._anthropic = anthropic
        self.key = re.sub(r"\s+", "", env("ANTHROPIC_API_KEY"))
        os.environ.pop("ANTHROPIC_API_KEY", None)  # anders stuurt de SDK hem ook als x-api-key mee
        headers = {}
        workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
        if workspace:
            headers["anthropic-workspace-id"] = workspace
        self.headers = headers
        self.client = anthropic.Anthropic(auth_token=self.key, default_headers=headers)
        self.reserve_gebruikt = False
        self.verbruik: list[dict] = []
        log.info("Claude-sleutel: %s...%s (%d tekens)", self.key[:14], self.key[-4:], len(self.key))

    def _create(self, **kwargs):
        try:
            return self.client.messages.create(**kwargs)
        except self._anthropic.AuthenticationError:
            if self.reserve_gebruikt:
                raise
            log.warning("Bearer-token geweigerd, opnieuw met x-api-key")
            self.reserve_gebruikt = True
            self.client = self._anthropic.Anthropic(api_key=self.key, default_headers=self.headers)
            return self.client.messages.create(**kwargs)

    def json(self, taak: str, model: str, system: str, user: str, max_tokens: int = 8000,
             inspanning: str | None = None, denken: bool = True) -> dict:
        """inspanning: low/medium/high. denken=False zet het nadenken uit (alleen Haiku 5.5)."""
        laatste_fout = None
        extra: dict = {}
        if inspanning:
            extra["output_config"] = {"effort": inspanning}
        if not denken:
            extra["thinking"] = {"type": "disabled"}
        for poging in range(3):
            try:
                resp = self._create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    extra_body=extra or None,
                )
            except self._anthropic.BadRequestError as exc:
                if extra:
                    log.warning("%s: instellingen geweigerd (%s), opnieuw zonder", taak, exc)
                    extra = {}
                    continue
                raise
            log.info("%s: stop=%s, uitvoer %d tokens", taak, resp.stop_reason, resp.usage.output_tokens)
            if resp.stop_reason == "max_tokens":
                self.verbruik.append({"taak": taak, "model": model,
                                      "invoer_tokens": resp.usage.input_tokens,
                                      "uitvoer_tokens": resp.usage.output_tokens})
                max_tokens = min(max_tokens * 2, 64000)
                log.warning("%s: antwoord afgekapt, opnieuw met max_tokens=%d", taak, max_tokens)
                continue
            self.verbruik.append({
                "taak": taak, "model": model,
                "invoer_tokens": resp.usage.input_tokens,
                "uitvoer_tokens": resp.usage.output_tokens,
            })
            tekst = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            if not tekst.strip():
                soorten = [getattr(b, "type", "?") for b in resp.content]
                log.warning("%s: leeg antwoord (blokken: %s, stop=%s)", taak, soorten, resp.stop_reason)
            try:
                return parse_json(tekst)
            except json.JSONDecodeError as exc:
                laatste_fout = exc
                log.warning("%s: antwoord was geen geldige JSON (poging %d)", taak, poging + 1)
        raise RuntimeError(f"{taak}: geen geldige JSON na 3 pogingen ({laatste_fout})")


class NepClaude:
    """Voor de proefrun zonder API-sleutel: geeft voorspelbare antwoorden terug."""

    def __init__(self) -> None:
        self.verbruik: list[dict] = []
        self.items: list[dict] = []

    def json(self, taak: str, model: str, system: str, user: str, max_tokens: int = 8000,
             inspanning: str | None = None, denken: bool = True) -> dict:
        self.verbruik.append({"taak": taak, "model": "nep", "invoer_tokens": len(user) // 4, "uitvoer_tokens": 0})
        ids = re.findall(r"^\[(\w{7})\]", user, flags=re.M)
        if taak == "selectie":
            return {
                "hoofditems": [{"onderwerp": f"Onderwerp {i + 1}", "rubriek": "binnenland",
                                "item_ids": [ids[i]], "waarom": "test"} for i in range(min(5, len(ids)))],
                "kort_nieuws": [{"onderwerp": "Kort", "item_ids": ids[5:7]}],
                "regionaal": [{"onderwerp": "Houten", "item_ids": ids[7:8]}],
                "opmerkelijk": [{"onderwerp": "Opmerkelijk", "item_ids": ids[8:9]}],
                "agenda": [],
            }
        if taak == "script":
            seg = [
                {"blok": "opening", "spreker": "lezer", "tekst": "Goedemorgen Victor. Dit is een proefuitzending.", "bron_ids": []},
                {"blok": "koppen", "spreker": "lezer", "tekst": "De koppen van vandaag in deze test.", "bron_ids": []},
            ]
            for i, item_id in enumerate(ids[:5]):
                seg.append({"blok": "item", "spreker": "lezer", "tekst": f"Testbericht nummer {i + 1}, volgens de NOS.", "bron_ids": [item_id]})
                seg.append({"blok": "item", "spreker": "duider", "tekst": "Wat betekent dit? Dit is de duiding bij het testbericht.", "bron_ids": [item_id]})
            seg += [
                {"blok": "kort", "spreker": "lezer", "tekst": "Dan het korte nieuws.", "bron_ids": []},
                {"blok": "weer", "spreker": "duider", "tekst": "Het weer: droog en zeven graden.", "bron_ids": []},
                {"blok": "afsluiting", "spreker": "lezer", "tekst": "Het citaat van de dag. Tot vanavond, Victor.", "bron_ids": []},
            ]
            return {"titel": "Proefuitzending", "segmenten": seg, "onderwerpen": ["test"]}
        if taak == "feitencheck":
            return {"wijzigingen": []}
        return {}
