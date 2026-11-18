"""MercadoLibre Inmuebles: listados de 48 avisos (sin coordenadas; se ubican por dirección).

La búsqueda general de "venta" trae también locales, oficinas y cocheras: se
filtran por tipo. Los emprendimientos (precios "desde") se saltean.
"""
import json
import re

from .fetch import Client  # noqa: F401

SITE = "ml"
NAME = "MercadoLibre"
PER_PAGE = 48
# una página cada 3-4 s
CLIENT_OPTS = {"pause": (3.0, 4.0), "block_waits": (120, 300, 600)}

BASE = "https://inmuebles.mercadolibre.com.ar"
DOMAINS = {  # domain_id -> (tipo, clave de la búsqueda)
    "MLA-INDIVIDUAL_APARTMENTS_FOR_SALE": ("Departamento", "departamentos"),
    "MLA-HORIZONTAL_PROPERTY_FOR_SALE": ("PH", "ph"),
    "MLA-INDIVIDUAL_HOUSES_FOR_SALE": ("Casa", "casas"),
}


def search_url(tipos, zona, precio_min=0, precio_max=0, page=1):
    url = f"{BASE}/venta/{zona}/"
    frag = ""
    if page > 1:
        frag += f"_Desde_{(page - 1) * PER_PAGE + 1}"
    if precio_max or precio_min:
        frag += f"_PriceRange_{int(precio_min or 0)}USD-{int(precio_max or 999999999)}USD"
    return url + (frag + "_NoIndex_True" if frag else "")


def _attrs(texts, it):
    for t in texts:
        tl = t.lower()
        n = re.search(r"\d+(?:[.,]\d+)?", t)
        if not n or " a " in tl or " - " in tl:  # rangos de emprendimientos
            continue
        v = float(n.group(0).replace(".", "").replace(",", ".")) if "m²" in t else float(n.group(0).replace(",", "."))
        if "amb" in tl:
            it["amb"] = v
        elif "dorm" in tl:
            it["dorm"] = v
        elif "baño" in tl:
            it["banos"] = v
        elif "m²" in t and "cubierto" in tl:
            it["m2_cub"] = v
        elif "m²" in t:
            it["m2_tot"] = v


def parse_list(html, tipos=("departamentos", "casas", "ph")):
    j = html.find('"results":[{"id":"POLYCARD"')
    if j < 0:
        return [], 0, 0
    try:
        res, _ = json.JSONDecoder().raw_decode(html[html.find("[", j):])
    except ValueError:
        return [], 0, 0
    items = []
    for r in res:
        pc = r.get("polycard") or {}
        md = pc.get("metadata") or {}
        dom = DOMAINS.get(md.get("domain_id"))
        if not dom or dom[1] not in tipos:
            continue
        comp = {c.get("type"): c for c in pc.get("components") or []}
        price = ((comp.get("price") or {}).get("price") or {}).get("current_price") or {}
        loc = ((comp.get("location") or {}).get("location") or {}).get("text") or ""
        it = {
            "id": f"ml:{md.get('id')}",
            "url": "https://" + md.get("url", "") if md.get("url") else "",
            "title": ((comp.get("title") or {}).get("title") or {}).get("text", "").strip(),
            "tipo": dom[0],
            "address": loc,
            "loc": loc,
            "price_usd": price.get("value") if price.get("currency") == "USD" else None,
            "price_ars": price.get("value") if price.get("currency") == "ARS" else None,
            "agent": re.sub(r"\{[^}]+\}", "", ((comp.get("seller") or {}).get("seller") or {}).get("text", "")).strip(),
        }
        pics = (pc.get("pictures") or {}).get("pictures") or []
        if pics:
            it["photo"] = f"https://http2.mlstatic.com/D_NQ_NP_{pics[0]['id']}-O.jpg"
        _attrs(((comp.get("attributes_list") or {}).get("attributes_list") or {}).get("texts") or [], it)
        items.append(it)
    m = re.search(r'"event_data":\{[^{]*?"total":(\d+)', html)
    total = int(m.group(1)) if m else len(res)
    pages = -(-total // PER_PAGE) if total else 0
    return items, min(pages, 42), total  # MercadoLibre no muestra más de ~2000 resultados
