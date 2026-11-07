"""Tests zonder internet: python -m pytest tests"""
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest import mock

from agent import collect, editor, extras, tts
from agent.deliver import feed_xml
from agent.llm import parse_json

NU = datetime.now(timezone.utc)


def _rss(titels, uren_geleden=1):
    t = format_datetime(NU - timedelta(hours=uren_geleden))
    items = "".join(f"<item><title>{x}</title><link>https://ex.org/{i}</link><pubDate>{t}</pubDate>"
                    f"<description>&lt;p&gt;Samenvatting {i}&lt;/p&gt;</description></item>" for i, x in enumerate(titels))
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>x</title>{items}</channel></rss>".encode()


def _resp(body):
    r = mock.Mock()
    r.content = body
    r.raise_for_status = lambda: None
    return r


def test_rss_en_google_news_titel():
    with mock.patch("agent.collect.requests.get", return_value=_resp(_rss(["Kabinet valt - Reuters"]))):
        _, items, fout = collect.fetch_feed({"naam": "Reuters", "soort": "google_news", "zoek": "site:reuters.com", "taal": "en"}, 24)
    assert not fout and items[0].titel == "Kabinet valt" and items[0].bron == "Reuters"
    assert items[0].samenvatting == ""


def test_oude_berichten_eruit():
    with mock.patch("agent.collect.requests.get", return_value=_resp(_rss(["Oud nieuws"], uren_geleden=30))):
        _, items, _ = collect.fetch_feed({"naam": "NOS", "url": "https://x"}, 24)
    assert items == []


def test_dubbelen_zwaarste_bron_wint():
    def fake_get(url, **kw):
        return _resp(_rss(["Zelfde titel hier"]))
    bronnen = [{"naam": "AD", "url": "https://a", "gewicht": 1}, {"naam": "NOS", "url": "https://b", "gewicht": 3}]
    with mock.patch("agent.collect.requests.get", side_effect=fake_get):
        items, problemen = collect.collect(bronnen, 24)
    assert len(items) == 1 and items[0].bron == "NOS"


def test_kapotte_feed_stopt_niets():
    with mock.patch("agent.collect.requests.get", side_effect=ConnectionError("weg")):
        items, problemen = collect.collect([{"naam": "X", "url": "https://x"}], 24)
    assert items == [] and "ConnectionError" in problemen[0]


def test_selectie_onbekende_ids_weg():
    it = collect.Item("abc1234", "NOS", "tech", "T", "S", "l", "", 3, True)
    llm = mock.Mock()
    llm.json.return_value = {"hoofditems": [{"onderwerp": "a", "item_ids": ["abc1234", "verzonnen"]},
                                            {"onderwerp": "b", "item_ids": ["nee"]}]}
    cfg = {"luisteraar": {"naam": "Victor", "tijdzone": "Europe/Amsterdam"}, "focus": ["x"],
           "modellen": {"selectie": "m"}}
    keuze = editor.selecteer(llm, cfg, {"titel": "Ochtendjournaal"}, [it], [], {"datum": "vandaag"})
    assert keuze["hoofditems"] == [{"onderwerp": "a", "item_ids": ["abc1234"]}]
    assert keuze["kort_nieuws"] == []


def test_feitencheck_past_aan_en_schrapt():
    script = {"segmenten": [{"blok": "item", "spreker": "lezer", "tekst": "Fout", "bron_ids": []},
                            {"blok": "item", "spreker": "duider", "tekst": "Verzonnen", "bron_ids": []},
                            {"blok": "kort", "spreker": "lezer", "tekst": "Goed", "bron_ids": []}]}
    llm = mock.Mock()
    llm.json.return_value = {"wijzigingen": [{"index": 0, "probleem": "p", "nieuwe_tekst": "Juist"},
                                             {"index": 1, "probleem": "p", "nieuwe_tekst": ""},
                                             {"index": 99, "nieuwe_tekst": "x"}]}
    cfg = {"luisteraar": {"naam": "Victor"}, "modellen": {"feitencheck": "m"}}
    uit, w = editor.feitencheck(llm, cfg, script, "", {}, {"datum": "vandaag"})
    assert [s["tekst"] for s in uit["segmenten"]] == ["Juist", "Goed"] and len(w) == 2


def test_lange_tekst_wordt_gesplitst():
    tekst = "Dit is een zin. " * 200
    delen = tts._chunks(tekst)
    assert len(delen) > 1 and all(len(d) <= tts.MAX_CHUNK for d in delen)


def test_beaufort_en_richting():
    assert extras.beaufort(0) == 0 and extras.beaufort(25) == 4 and extras.beaufort(130) == 12
    assert extras.richting(225) == "zuidwest" and extras.richting(355) == "noord"


def test_json_met_codeblok():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Hier is het: {"a": 2} klaar') == {"a": 2}


def test_podcastfeed_is_geldige_xml():
    cfg = {"podcast": {"titel": "Nieuws & meer", "omschrijving": "Privé"}}
    afl = [{"titel": "Ochtendjournaal", "omschrijving": "AI <test>", "bestand": "2026-11-07-ochtend.mp3",
            "bytes": 123, "gemaakt": "2026-11-07T06:40:00+01:00", "duur_sec": 754}]
    root = ET.fromstring(feed_xml(cfg, afl, "https://voorbeeld.nl/geheim"))
    enc = root.find("channel/item/enclosure")
    assert enc.get("url") == "https://voorbeeld.nl/geheim/2026-11-07-ochtend.mp3"
