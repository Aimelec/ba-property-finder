"""Estaciones de tren del AMBA (OpenStreetMap) y distancia a la más cercana."""
import json
import math

import requests

from .config import STATIONS_PATH

BBOX = "-35.10,-59.20,-34.25,-58.05"  # sur, oeste, norte, este
QUERY = f"""[out:json][timeout:90];
(node["railway"="station"]["station"!="subway"]({BBOX});
 node["railway"="halt"]({BBOX}););
out body;"""

LINES = ["Mitre", "Sarmiento", "Roca", "San Martín", "Belgrano Norte", "Belgrano Sur",
         "Urquiza", "Tren de la Costa", "Belgrano"]

# servicios con trenes muy espaciados: no cuentan para el puntaje ni se muestran (pedido del usuario).
# Ramales diésel del Mitre (Victoria–Capilla del Señor y Villa Ballester–Zárate) sin las cabeceras
# Victoria y Villa Ballester, que también son del Mitre eléctrico; y el Tren de la Costa entero.
SLOW_LINES = {"Tren de la Costa"}
SLOW_STATIONS = {("Mitre", n) for n in (
    "Doctor Albert Schweitzer", "Bancalari R", "General Pacheco", "El Talar", "López Camelo",
    "Garín", "Maquinista Savio", "Matheu", "Zelaya", "Los Cardales", "Capilla del Señor",
    "Benavídez", "Ingeniero Maschwitz", "Escobar", "Río Luján")}


def frequent(stations):
    """Sin las estaciones de servicios lentos (SLOW_LINES / SLOW_STATIONS)."""
    return [s for s in stations
            if s["line"] not in SLOW_LINES and (s["line"], s["name"]) not in SLOW_STATIONS]


def _line(tags):
    blob = " ".join(tags.get(k, "") for k in ("line", "network", "operator", "name", "route_ref"))
    if tags.get("station") == "light_rail" or "Costa" in blob:
        return "Tren de la Costa"
    for ln in LINES:
        if ln in blob:
            return ln
    return ""


def download():
    r = requests.post("https://overpass-api.de/api/interpreter", data={"data": QUERY},
                      headers={"User-Agent": "depa-personal/0.1"}, timeout=120)
    r.raise_for_status()
    out = []
    for e in r.json()["elements"]:
        t = e.get("tags", {})
        if not t.get("name") or "disused" in t.get("railway", "") or t.get("disused") == "yes":
            continue
        out.append({"name": t["name"], "line": _line(t), "lat": e["lat"], "lng": e["lon"]})
    STATIONS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return frequent(out)


def load():
    """Estaciones que cuentan (el archivo guarda todas, sin filtrar)."""
    if STATIONS_PATH.exists():
        return frequent(json.loads(STATIONS_PATH.read_text(encoding="utf-8")))
    return download()


def haversine(lat1, lng1, lat2, lng2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def nearest(stations, lat, lng):
    """(estación, metros en línea recta)."""
    best, best_d = None, float("inf")
    for st in stations:
        d = haversine(lat, lng, st["lat"], st["lng"])
        if d < best_d:
            best, best_d = st, d
    return best, best_d


def walk_minutes(meters):
    """Estimación: las calles alargan ~30 % la línea recta, 80 m/min caminando."""
    return round(meters * 1.3 / 80)
