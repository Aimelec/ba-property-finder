"""Subte de Buenos Aires (líneas con su color oficial y estaciones) desde OpenStreetMap.

Se baja una vez a data/subte.json; solo se usa para dibujar el mapa.
"""
import json

import requests

from .config import DATA

SUBTE_PATH = DATA / "subte.json"
SERVERS = ["https://overpass-api.de/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter"]
QUERY = """[out:json][timeout:120];
area["name"="Ciudad Autónoma de Buenos Aires"]["boundary"="administrative"]->.caba;
( relation["route"="subway"](area.caba);
  relation["route"="light_rail"]["name"~"Premetro",i](area.caba); );
out geom;
node["railway"="station"]["station"="subway"](-34.75,-58.55,-34.50,-58.33);
out body;"""
# colores oficiales por si OSM no trae 'colour'
COLORS = {"A": "#18cccc", "B": "#eb0909", "C": "#233aa8", "D": "#02db2e", "E": "#c618cc",
          "H": "#ffdd00", "P": "#ffa500"}


def _line_key(tags):
    ref = (tags.get("ref") or "").strip().upper()
    if ref:
        return ref[:1] if ref[:1] in COLORS else ref
    name = tags.get("name", "")
    if "Premetro" in name:
        return "P"
    for k in COLORS:
        if f"Línea {k}" in name or f"Linea {k}" in name:
            return k
    return name


def download():
    last = None
    for url in SERVERS:
        try:
            r = requests.post(url, data={"data": QUERY}, headers={"User-Agent": "depa-personal/0.1"},
                              timeout=180)
            r.raise_for_status()
            els = r.json()["elements"]
            break
        except (requests.RequestException, ValueError) as e:
            last = e
    else:
        raise RuntimeError(f"No se pudo bajar el subte: {last}")
    lines = {}
    for e in els:
        if e["type"] != "relation":
            continue
        key = _line_key(e.get("tags", {}))
        ln = lines.setdefault(key, {"line": key, "name": e["tags"].get("name", key),
                                    "color": e["tags"].get("colour") or COLORS.get(key, "#cccccc"),
                                    "paths": []})
        for m in e.get("members", []):
            if m["type"] == "way" and m.get("geometry"):
                path = [[round(p["lat"], 6), round(p["lon"], 6)] for p in m["geometry"]]
                if path not in ln["paths"]:  # ida y vuelta comparten vías
                    ln["paths"].append(path)
    stations = []
    for e in els:
        if e["type"] == "node" and e.get("tags", {}).get("name"):
            t = e["tags"]
            ref = (t.get("line") or t.get("ref") or "").upper()
            stations.append({"name": t["name"], "line": ref[:1] if ref[:1] in COLORS else ref,
                             "lat": e["lat"], "lng": e["lon"]})
    # OSM no siempre dice de qué línea es cada estación: la más cercana a su recorrido
    from .domain.geo import haversine
    for st in stations:
        if st["line"] in COLORS:
            continue
        best, best_d = "", 400.0
        for ln in lines.values():
            for path in ln["paths"]:
                for la, lo in path[::2]:
                    d = haversine(st["lat"], st["lng"], la, lo)
                    if d < best_d:
                        best, best_d = ln["line"], d
        st["line"] = best
    data = {"lines": list(lines.values()), "stations": stations}
    SUBTE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def load():
    if SUBTE_PATH.exists():
        return json.loads(SUBTE_PATH.read_text(encoding="utf-8"))
    try:
        return download()
    except RuntimeError:
        return {"lines": [], "stations": []}
