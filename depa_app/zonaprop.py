"""Zonaprop: listados de 30 avisos con todos los datos y coordenadas exactas.

Los datos vienen en window.__PRELOADED_STATE__ de cada página de resultados,
así que no hace falta abrir cada aviso. El sitio muestra como mucho 9 páginas de
resultados por búsqueda (270 avisos).
"""
import json
import re

from .fetch import Client  # noqa: F401

SITE = "zp"
NAME = "Zonaprop"
PER_PAGE = 30
MAX_PAGES = 9  # páginas de resultados que muestra el sitio por búsqueda
CLIENT_OPTS = {"pause": (5.0, 9.0), "block_waits": (60, 300, 600)}

BASE = "https://www.zonaprop.com.ar"
TIPO_SLUG = {"casas": "casas", "departamentos": "departamentos", "ph": "ph"}
TIPO_NAME = {"Departamentos": "Departamento", "Casas": "Casa", "PH": "PH"}
FEATURES = {  # id de Zonaprop -> campo
    "CFT100": "m2_tot", "CFT101": "m2_cub", "CFT1": "amb", "CFT2": "dorm", "CFT3": "banos",
    "CFT5": "antig",
}


def search_url(tipos, zona, precio_min=0, precio_max=0, page=1):
    kinds = "-".join(TIPO_SLUG[t] for t in ("casas", "departamentos", "ph") if t in tipos)
    url = f"{BASE}/{kinds}-venta-{zona}"
    if precio_min and precio_max:
        url += f"-{int(precio_min)}-{int(precio_max)}-dolar"  # rango, ej. -100000-160000-dolar
    elif precio_max:
        url += f"-menos-{int(precio_max)}-dolar"
    if page > 1:
        url += f"-pagina-{page}"
    return url + ".html"


def _state(html):
    i = html.find("window.__PRELOADED_STATE__")
    if i < 0:
        return None
    i = html.find("{", i)
    try:
        st, _ = json.JSONDecoder().raw_decode(html[i:])
    except ValueError:
        return None
    return st


def _num(v):
    if v in (None, ""):
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", str(v))
    return float(m.group(0).replace(",", ".")) if m else None


def _location_names(loc):
    names = []
    while loc:
        names.append(loc.get("name") or "")
        loc = loc.get("parent")
    return names


def parse_list(html):
    """(avisos, total_páginas, total_resultados)."""
    st = _state(html)
    if not st:
        return [], 0, 0
    ls = st.get("listStore", {})
    items = []
    for p in ls.get("listPostings") or []:
        if p.get("postingType") != "PROPERTY":
            continue  # emprendimientos (precios "desde")
        price_usd = price_ars = None
        for op in p.get("priceOperationTypes") or []:
            if (op.get("operationType") or {}).get("name") != "Venta":
                continue
            for pr in op.get("prices") or []:
                if pr.get("currency") == "USD":
                    price_usd = pr.get("amount")
                elif pr.get("currency") in ("$", "ARS"):
                    price_ars = pr.get("amount")
        loc = p.get("postingLocation") or {}
        names = _location_names(loc.get("location"))
        address = ((loc.get("address") or {}).get("name") or "").strip()
        geo = ((loc.get("postingGeolocation") or {}).get("geolocation") or {})
        feats = {}
        it = {
            "id": f"zp:{p['postingId']}",
            "url": BASE + (p.get("url") or ""),
            "title": (p.get("title") or p.get("generatedTitle") or "").strip(),
            "tipo": TIPO_NAME.get((p.get("realEstateType") or {}).get("name"), "Otro"),
            "address": ", ".join(x for x in [address] + names[:2] if x),
            "loc": " ".join(names),
            "price_usd": price_usd,
            "price_ars": price_ars,
            "expensas": (p.get("expenses") or {}).get("amount") or None,
            "description": re.sub(r"<[^>]+>", " ", p.get("descriptionNormalized") or "")[:1500],
            "agent": (p.get("publisher") or {}).get("name") or "",
        }
        if geo.get("latitude") and geo.get("longitude"):
            it["lat"], it["lng"] = geo["latitude"], geo["longitude"]
        for fid, f in (p.get("mainFeatures") or {}).items():
            label = f.get("label") or fid
            if fid in FEATURES:
                val = _num(f.get("value"))
                if val is not None:
                    it[FEATURES[fid]] = val
            feats[label] = f.get("value") if f.get("value") not in (None, "") else True
        for group in (p.get("generalFeatures") or {}).values():
            for f in (group or {}).values():
                if isinstance(f, dict) and f.get("label"):
                    feats[f["label"]] = f.get("value") if f.get("value") not in (None, "") else True
        if "Cochera" in feats and "Cocheras" not in feats:
            feats["Cocheras"] = str(feats["Cochera"])
        it["features"] = feats
        pics = p.get("visiblePictures") or {}
        plist = pics.get("pictures") if isinstance(pics, dict) else None
        if plist:
            first = plist[0]
            it["photo"] = first.get("url730x532") or first.get("url360x266") or first.get("resizeUrl1200x1200")
        items.append(it)
    paging = ls.get("paging") or {}
    return items, int(paging.get("totalPages") or 0), int(paging.get("total") or 0)
