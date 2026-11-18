"""Safety layers for the map (drawn only; they are not part of the score).

- CABA: heat map of violent crime from the city's Mapa del Delito (BA Data):
  https://data.buenosaires.gob.ar/dataset/delitos. The yearly CSVs are downloaded by hand with a
  browser into data/delitos/.
- GBA Norte: RENABAP informal settlements (official polygons from datos.gob.ar). This measures
  housing conditions, not crime.
"""
import csv
import json
from collections import Counter

import requests

from ..config import DATA
from ..domain.zones import ZONES

DELITOS_DIR = DATA / "delitos"
CALOR_PATH = DATA / "delitos_calor.json"
BARRIOS_PATH = DATA / "barrios_populares.json"
RENABAP_URL = "https://archivo.infraestructura.gob.ar/dataset/ssisu/20231205_info_publica.geojson"

# crimes that count for the heat map: violence against a person (no thefts, traffic or threats)
TIPOS_VIOLENTOS = {"Robo", "Homicidios", "Lesiones"}
CELDA = 0.001  # degrees (~110 x 90 m): incidents are summed per cell so the map stays light
# the registry calls "General San Martín" the partido that zones.py calls "San Martín"
_PARTIDO = {"San Martín": "General San Martín"}


def _csv_files():
    return sorted(DELITOS_DIR.glob("*.csv")) if DELITOS_DIR.exists() else []


def build_heat():
    """Sums the violent crimes of every CSV in data/delitos/ into cells -> delitos_calor.json."""
    cells, years, n = Counter(), set(), 0
    for path in _csv_files():
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("tipo") not in TIPOS_VIOLENTOS:
                    continue
                try:
                    lat, lng = float(r["latitud"]), float(r["longitud"])
                    cant = int(float(r.get("cantidad") or 1))
                except (KeyError, TypeError, ValueError):
                    continue
                if not (-34.75 < lat < -34.5 and -58.55 < lng < -58.33):  # outside CABA / no data
                    continue
                cells[(round(lat / CELDA), round(lng / CELDA))] += cant
                years.add(r.get("anio", ""))
                n += cant
    data = {"cells": [[round(a * CELDA, 4), round(b * CELDA, 4), c] for (a, b), c in cells.items()],
            "years": sorted(y for y in years if y), "hechos": n,
            "sources": {p.name: p.stat().st_mtime for p in _csv_files()}}
    CALOR_PATH.write_text(json.dumps(data), encoding="utf-8")
    return data


def load_heat():
    """Heat-map cells; rebuilt when the CSVs changed. Empty when there are no CSVs."""
    files = {p.name: p.stat().st_mtime for p in _csv_files()}
    if not files:
        return {"cells": [], "years": [], "hechos": 0}
    try:
        data = json.loads(CALOR_PATH.read_text(encoding="utf-8"))
        if data.get("sources") == files:
            return data
    except (OSError, ValueError):
        pass
    return build_heat()


def _round(coords):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], 5), round(coords[1], 5)]
    return [_round(c) for c in coords]


def build_barrios(geojson=None):
    """Informal settlements in the GBA Norte partidos -> barrios_populares.json.
    `geojson`: an already downloaded file; otherwise it is downloaded from the official registry (~9 MB)."""
    if geojson:
        src = json.loads(open(geojson, encoding="utf-8").read())
    else:
        r = requests.get(RENABAP_URL, headers={"User-Agent": "depa-personal/0.1"}, timeout=180)
        r.raise_for_status()
        src = r.json()
    partidos = {_PARTIDO.get(name, name) for _, name, _, _ in ZONES["GBA Norte"]}
    feats = []
    for f in src["features"]:
        p = f["properties"]
        if p.get("provincia") != "Buenos Aires" or p.get("departamento") not in partidos:
            continue
        feats.append({"type": "Feature", "geometry": {"type": f["geometry"]["type"],
                                                      "coordinates": _round(f["geometry"]["coordinates"])},
                      "properties": {"nombre": p.get("nombre_barrio"), "partido": p.get("departamento"),
                                     "localidad": p.get("localidad"), "tipo": p.get("clasificacion_barrio"),
                                     "familias": p.get("cantidad_familias_aproximada")}})
    data = {"type": "FeatureCollection", "features": feats, "fuente": RENABAP_URL}
    BARRIOS_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def load_barrios():
    if BARRIOS_PATH.exists():
        return json.loads(BARRIOS_PATH.read_text(encoding="utf-8"))
    try:
        return build_barrios()
    except (requests.RequestException, ValueError, KeyError):
        return {"type": "FeatureCollection", "features": []}
