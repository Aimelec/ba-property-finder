"""Cliente de descarga lento y educado, compartido por todos los sitios.

- pausa aleatoria entre pedidos
- 'lote': después de N páginas, una pausa larga
- si el sitio bloquea, espera y reintenta (los tiempos dependen del sitio)
- puede usar un navegador integrado (plugin opcional, ver plugins.py) o requests
"""
import random
import threading
import time
from datetime import datetime
from urllib.parse import urlparse

import requests

from .config import DATA

# registro de cada pedido (para ajustar el ritmo de cada sitio): data/logs/pedidos.csv
REQ_LOG = DATA / "logs" / "pedidos.csv"
_req_lock = threading.Lock()


def log_request(url, result, status, secs, session_n):
    """result: ok / bloqueado / no_existe. session_n: pedidos de este cliente hasta ahora."""
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
    """El sitio sigue bloqueando después de los reintentos."""


class Stopped(Exception):
    """El usuario apretó Detener."""


class Client:
    def __init__(self, pause=(10.0, 15.0), log=print, should_stop=lambda: False, browser=None,
                 batch=None, rest=None, block_waits=(60, 180, 420)):
        """batch: (páginas, segundos) = pausa larga cada tantas páginas.
        browser: objeto con fetch(url, should_stop) (ver plugins.py) o None para usar requests."""
        self.browser = browser
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.pause = pause
        self.log = log
        self.should_stop = should_stop
        self.batch = batch
        self.rest = rest  # (páginas, segundos): descanso largo cada tantas páginas
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
        """HTML de la página, o None si no existe (404 / sin contenido)."""
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
            self._count = 0  # después de esperar, el lote empieza de nuevo
        raise Blocked(url)

    def _fetch(self, url):
        """(html, bloqueado, motivo)."""
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
