"""Ubicación aproximada desde la dirección del aviso, sin pedirle nada a Argenprop.

1) API Georef (datos.gob.ar, gratuita, del Estado): calle + altura + partido.
2) Si no encuentra: Nominatim (OpenStreetMap), máximo 1 pedido por segundo.
Los resultados (también los fallidos) se guardan en data/geocache.json.
"""
import json
import re
import threading
import time

import requests

from .config import DATA

CACHE_PATH = DATA / "geocache.json"
UA = {"User-Agent": "depa-personal/0.1 (uso personal)"}
_lock = threading.Lock()
_cache = None
_last_nominatim = 0.0
_nom_lock = threading.Lock()  # varios sitios descargan a la vez: máximo 1 pedido/s en total

ABBREV = [
    (r"\bav(?:da)?\.?\s+", "Avenida "), (r"\bpres\.?\s+", "Presidente "), (r"\bpte\.?\s+", "Presidente "),
    (r"\bgral\.?\s+", "General "), (r"\bcnel\.?\s+", "Coronel "), (r"\bdr\.?\s+", "Doctor "),
    (r"\bing\.?\s+", "Ingeniero "), (r"\bsta\.?\s+", "Santa "), (r"\bsto\.?\s+", "Santo "),
]


def _load():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save():
    CACHE_PATH.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")


def clean_street(address):
    """'Av. Pte. Peron al 2500 , San Fernando Vías / Centro' -> ('Avenida Presidente Peron', 2500)."""
    first = address.split(",")[0]
    first = re.split(r"\bentre\b|\besq(?:uina)?\.?\b|\by\b(?=\s+[A-ZÁÉÍÓÚ])|\bpiso\b", first,
                     flags=re.I)[0]
    m = re.search(r"^(.*?)\s+(?:al\s+)?(\d{1,5})\b", first.strip(), re.I)
    if not m:
        return first.strip(), None
    street = m.group(1).strip()
    for pat, rep in ABBREV:
        street = re.sub(pat, rep, street + " ", flags=re.I).strip()
    return street, int(m.group(2))


def _georef(street, number, partido, provincia):
    variants = [street]
    plain = re.sub(r"^(Avenida|Presidente|General|Doctor|Coronel|Ingeniero)\s+", "", street)
    plain = re.sub(r"^(Presidente|General)\s+", "", plain)
    if plain != street:
        variants.append(plain)
    for v in variants:
        params = {"direccion": f"{v} {number}", "provincia": provincia, "max": 1}
        if partido:
            params["departamento"] = partido
        r = requests.get("https://apis.datos.gob.ar/georef/api/direcciones",
                         params=params, headers=UA, timeout=8)
        if r.status_code != 200:
            continue
        d = r.json().get("direcciones") or []
        if d and d[0]["ubicacion"]["lat"] is not None:
            u = d[0]["ubicacion"]
            return u["lat"], u["lon"]
    return None


def _nominatim(street, number, partido, provincia):
    global _last_nominatim
    with _nom_lock:
        wait = 1.1 - (time.time() - _last_nominatim)
        if wait > 0:
            time.sleep(wait)
        _last_nominatim = time.time()
    q = f"{street} {number}, {partido + ', ' if partido else ''}{provincia}, Argentina"
    r = requests.get("https://nominatim.openstreetmap.org/search",
                     params={"q": q, "format": "json", "limit": 1, "countrycodes": "ar"},
                     headers=UA, timeout=8)
    if r.status_code == 200 and r.json():
        j = r.json()[0]
        return float(j["lat"]), float(j["lon"])
    return None


def geocode(address, zona, grupo):
    """(lat, lng) o None. zona = nombre del partido/barrio, grupo = CABA/GBA…"""
    street, number = clean_street(address or "")
    if not street or not number:
        return None
    caba = grupo == "CABA"
    provincia = "Ciudad Autónoma de Buenos Aires" if caba else "Buenos Aires"
    partido = None if caba else zona
    key = f"{street}|{number}|{partido}|{provincia}"
    with _lock:
        cache = _load()
        if key in cache:
            return tuple(cache[key]) if cache[key] else None
    res = None
    try:
        res = _georef(street, number, partido, provincia) or _nominatim(street, number, partido, provincia)
    except (requests.RequestException, ValueError, KeyError):
        return None  # sin guardar: se reintenta la próxima vez
    with _lock:
        _cache[key] = list(res) if res else None
        _save()
    return res
