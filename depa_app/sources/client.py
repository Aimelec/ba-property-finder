"""Slow, polite HTTP client shared by all sources.

- random pause between requests ('pause'), optional long pause every N pages ('batch') and a
  longer rest every N pages ('rest')
- when a site pushes back, it waits ('block_waits') and retries, then gives up with Blocked
- every request is logged to data/logs/pedidos.csv (time, host, result, status, seconds, url)
- pages can come from plain HTTP (requests) or from an alternative fetcher (plugin, see plugins.py)
"""
import random
import threading
import time
from datetime import datetime
from urllib.parse import urlparse

import requests

from ..config import DATA

# one line per request, to tune each site's pace: data/logs/pedidos.csv
REQ_LOG = DATA / "logs" / "pedidos.csv"
_req_lock = threading.Lock()


def log_request(url, result, status, secs, session_n):
    """result: ok / bloqueado (refused) / no_existe (404). session_n: requests made by this client so far."""
    try:
        REQ_LOG.parent.mkdir(exist_ok=True)
        new = not REQ_LOG.exists()
        with _req_lock, open(REQ_LOG, "a", encoding="utf-8") as f:
            if new:
                f.write("hora,sitio,resultado,http,segundos,n_sesion,url\n")
            f.write(f"{datetime.now().isoformat(timespec='seconds')},{urlparse(url).netloc},"
                    f"{result},{status},{secs:.1f},{session_n},{url}\n")
    except OSError:
        pass

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9",
}
BLOCK_SIGNS = ("Just a moment", "Un momento", "cf-chl", "captcha", "account-verification",
               "suspicious-traffic")


class Blocked(Exception):
    """The site still refuses after all the retries."""


class Stopped(Exception):
    """The user pressed Stop."""


class Client:
    def __init__(self, pause=(10.0, 15.0), log=print, should_stop=lambda: False, browser=None,
                 batch=None, rest=None, block_waits=(60, 180, 420)):
        """pause: (min, max) seconds between requests. batch / rest: (pages, seconds) long pauses.
        browser: object with fetch(url, should_stop) (see plugins.py), or None to use requests."""
        self.browser = browser
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.pause = pause
        self.log = log
        self.should_stop = should_stop
        self.batch = batch
        self.rest = rest  # (pages, seconds): a longer rest every that many pages
        self._total = 0
        self.block_waits = block_waits
        self._last = 0.0
        self._count = 0

    def sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self.should_stop():
                raise Stopped()
            time.sleep(0.2)

    def _wait_turn(self):
        if self.rest and self._total and self._total % self.rest[0] == 0:
            self.log(f"Descanso de {self.rest[1] // 60} min ({self._total} páginas leídas)…")
            self.sleep(self.rest[1])
            self._count = 0
        if self.batch and self._count and self._count % self.batch[0] == 0:
            self.log(f"Pausa de {self.batch[1] // 60} min para no ser bloqueado…")
            self.sleep(self.batch[1])
        gap = random.uniform(*self.pause) - (time.time() - self._last)
        if gap > 0:
            self.sleep(gap)
        if self.should_stop():
            raise Stopped()
        self._last = time.time()
        self._count += 1
        self._total += 1

    def get(self, url):
        """HTML of the page, or None when it does not exist (404 / empty)."""
        waits = self.block_waits
        for attempt in range(len(waits) + 1):
            self._wait_turn()
            t0 = time.time()
            html, blocked, why = self._fetch(url)
            log_request(url, "bloqueado" if blocked else ("ok" if html else "no_existe"),
                        self._status, time.time() - t0, self._total)
            if not blocked:
                return html
            if attempt == len(waits):
                break
            self.log(f"{why}: espero {waits[attempt] // 60} min y reintento…")
            self.sleep(waits[attempt])
            self._count = 0  # after waiting, the batch starts over
        raise Blocked(url)

    def _fetch(self, url):
        """(html, refused, reason)."""
        self._status = ""
        if self.browser is not None:
            html = self.browser.fetch(url, self.should_stop)
            if self.should_stop():
                raise Stopped()
            if html is None:
                return None, True, "La página no cargó"
            return html or None, False, ""
        try:
            r = self.s.get(url, timeout=30)
        except requests.RequestException as e:
            self._status = type(e).__name__
            return None, True, f"Error de red ({type(e).__name__})"
        self._status = r.status_code
        if r.status_code == 404:
            return None, False, ""
        if r.status_code == 200 and not any(s in r.text[:5000] for s in BLOCK_SIGNS):
            return r.text, False, ""
        return None, True, f"Bloqueo del sitio (HTTP {r.status_code})"
