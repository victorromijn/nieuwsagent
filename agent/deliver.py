"""Bezorgen: Telegram en (optioneel) een privé podcastfeed op je eigen hosting."""
from __future__ import annotations

import posixpath
from datetime import datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

import requests

from .util import env, log


# ---------- Telegram ----------

def _tg(methode: str, **kwargs) -> dict:
    token = env("TELEGRAM_BOT_TOKEN")
    resp = requests.post(f"https://api.telegram.org/bot{token}/{methode}", timeout=120, **kwargs)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {methode} mislukt: {data.get('description')}")
    return data


def telegram_audio(pad: Path, titel: str, bijschrift: str, duur_sec: float) -> None:
    with open(pad, "rb") as f:
        _tg("sendAudio",
            data={"chat_id": env("TELEGRAM_CHAT_ID"), "title": titel, "performer": "Nieuwsagent",
                  "caption": bijschrift[:1024], "duration": int(duur_sec)},
            files={"audio": (pad.name, f, "audio/mpeg")})
    log.info("Verstuurd via Telegram")


def telegram_tekst(tekst: str) -> None:
    try:
        _tg("sendMessage", data={"chat_id": env("TELEGRAM_CHAT_ID"), "text": tekst[:4000]})
    except Exception as exc:  # noqa: BLE001
        log.error("Telegram-bericht niet gelukt: %s", exc)


# ---------- Podcastfeed ----------

def podcast_actief() -> bool:
    return env("PODCAST_PROTOCOL", required=False).lower() in {"ftps", "ftp", "sftp"}


class _Uploader:
    def __init__(self) -> None:
        self.protocol = env("PODCAST_PROTOCOL").lower()
        self.host = env("PODCAST_HOST")
        self.user = env("PODCAST_USER")
        self.password = env("PODCAST_PASSWORD")
        self.map = env("PODCAST_DIR")
        self.conn = None

    def __enter__(self):
        if self.protocol == "sftp":
            import paramiko
            transport = paramiko.Transport((self.host, 22))
            transport.connect(username=self.user, password=self.password)
            self.conn = paramiko.SFTPClient.from_transport(transport)
            self._transport = transport
        else:
            from ftplib import FTP, FTP_TLS
            ftp = FTP_TLS(self.host, timeout=60) if self.protocol == "ftps" else FTP(self.host, timeout=60)
            ftp.login(self.user, self.password)
            if self.protocol == "ftps":
                ftp.prot_p()
            self.conn = ftp
        return self

    def __exit__(self, *exc):
        try:
            if self.protocol == "sftp":
                self.conn.close()
                self._transport.close()
            else:
                self.conn.quit()
        except Exception:  # noqa: BLE001
            pass

    def zet(self, lokaal: Path, naam: str) -> None:
        doel = posixpath.join(self.map, naam)
        if self.protocol == "sftp":
            self.conn.put(str(lokaal), doel)
        else:
            with open(lokaal, "rb") as f:
                self.conn.storbinary(f"STOR {doel}", f)

    def wis(self, naam: str) -> None:
        doel = posixpath.join(self.map, naam)
        try:
            if self.protocol == "sftp":
                self.conn.remove(doel)
            else:
                self.conn.delete(doel)
        except Exception:  # noqa: BLE001
            pass


def feed_xml(cfg: dict, afleveringen: list[dict], basis_url: str) -> str:
    p = cfg["podcast"]
    items = []
    for a in sorted(afleveringen, key=lambda x: x["gemaakt"], reverse=True):
        datum = datetime.fromisoformat(a["gemaakt"])
        minuten, sec = divmod(int(a["duur_sec"]), 60)
        items.append(f"""
    <item>
      <title>{escape(a['titel'])}</title>
      <description>{escape(a.get('omschrijving', ''))}</description>
      <enclosure url="{escape(basis_url.rstrip('/') + '/' + a['bestand'])}" length="{a['bytes']}" type="audio/mpeg"/>
      <guid isPermaLink="false">{escape(a['bestand'])}</guid>
      <pubDate>{format_datetime(datum)}</pubDate>
      <itunes:duration>{minuten}:{sec:02d}</itunes:duration>
    </item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{escape(p['titel'])}</title>
    <description>{escape(p['omschrijving'])}</description>
    <language>nl</language>
    <link>{escape(basis_url)}</link>
    <itunes:block>Yes</itunes:block>
    <itunes:explicit>false</itunes:explicit>{''.join(items)}
  </channel>
</rss>
"""


def podcast_publiceer(cfg: dict, mp3: Path, aflevering: dict, archief: list[dict], werkmap: Path) -> list[dict]:
    """Uploadt de mp3 en een nieuwe feed.xml. Geeft de lijst afleveringen in de feed terug."""
    basis_url = env("PODCAST_BASE_URL")
    bewaar = int(cfg["podcast"].get("bewaar_dagen", 0) or 0)
    in_feed = [a for a in archief if a.get("podcast")] + [aflevering]
    weg = []
    if bewaar > 0:
        grens = datetime.fromisoformat(aflevering["gemaakt"]) - timedelta(days=bewaar)
        weg = [a for a in in_feed if datetime.fromisoformat(a["gemaakt"]) < grens]
        in_feed = [a for a in in_feed if a not in weg]
    xml = werkmap / "feed.xml"
    xml.write_text(feed_xml(cfg, in_feed, basis_url), encoding="utf-8")
    with _Uploader() as up:
        up.zet(mp3, aflevering["bestand"])
        up.zet(xml, "feed.xml")
        for a in weg:
            up.wis(a["bestand"])
            a["podcast"] = False
    log.info("Podcastfeed bijgewerkt (%d afleveringen)", len(in_feed))
    return in_feed
