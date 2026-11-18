"""Puntaje 0-100 de cada propiedad según las preferencias (pestaña Preferencias).

Cada criterio da un valor 0..1; el puntaje es el promedio ponderado por los
pesos. Si a una propiedad le falta un dato (ej. sin coordenadas todavía) ese
criterio cuenta 0.3 para no premiar avisos incompletos.
"""
from statistics import median

MISSING = 0.3
EXTRA_KEYS = {
    "cochera": ("cochera",),
    "exterior": ("balc", "terraza", "patio", "jard", "parque"),
    "credito": ("apto cr",),
}


def clamp(x):
    return max(0.0, min(1.0, x))


def ppm2(r):
    m2 = r.get("m2_cub") or r.get("m2_tot")
    if r.get("price_usd") and m2 and m2 >= 15:
        return r["price_usd"] / m2
    return None


def zone_medians(rows):
    """Mediana de USD/m² por (zona, tipo); si hay pocos datos, por zona."""
    by_zt, by_z = {}, {}
    for r in rows:
        p = ppm2(r)
        if p:
            by_zt.setdefault((r["zona_slug"], r["tipo"]), []).append(p)
            by_z.setdefault(r["zona_slug"], []).append(p)
    out = {k: median(v) for k, v in by_zt.items() if len(v) >= 5}
    out.update({(z, None): median(v) for z, v in by_z.items()})
    return out


def has_extra(r, key):
    text = " ".join([*(k.lower() for k in r.get("features", {})),
                     (r.get("title") or "").lower()])
    if key == "cochera":
        f = r.get("features", {})
        n = f.get("Cant. Cocheras") or f.get("Cocheras")
        if isinstance(n, str) and n.strip() not in ("", "0"):
            return True
    return any(w in text for w in EXTRA_KEYS[key])


def criteria(r, s, medians):
    c = {}
    d = r.get("station_m")
    if d is None:
        c["estacion"] = MISSING
    else:
        ideal, far = s["estacion_ideal_m"], s["estacion_max_m"]
        c["estacion"] = 1.0 if d <= ideal else clamp(1 - (d - ideal) / max(1, far - ideal))

    p = ppm2(r)
    med = medians.get((r["zona_slug"], r["tipo"])) or medians.get((r["zona_slug"], None))
    # 30 % más barato que la mediana de la zona = 1, 30 % más caro = 0
    c["precio_m2"] = clamp((1.3 - p / med) / 0.6) if p and med else MISSING

    c["zona"] = s["prioridad_grupo"].get(r.get("grupo") or "Otra", 30) / 100

    m2 = r.get("m2_cub") or r.get("m2_tot")
    c["superficie"] = clamp(m2 / s["m2_ideal"]) if m2 else MISSING

    exp, price = r.get("expensas"), r.get("price_usd")
    if r.get("tipo") == "Casa" and not exp:
        c["expensas"] = 1.0
    elif exp is None:
        c["expensas"] = MISSING
    else:
        # expensas en ARS por cada 1000 USD de precio: 0 -> 1, 4000 o más -> 0
        c["expensas"] = clamp(1 - (exp / max(price or 100000, 1) * 1000) / 4000)

    a = r.get("antig")
    c["antiguedad"] = MISSING if a is None else clamp(1 - a / 60)

    c["extras"] = sum(has_extra(r, k) for k in EXTRA_KEYS) / len(EXTRA_KEYS)
    return c


SITE_NAMES = {"ap": "Argenprop", "zp": "Zonaprop", "ml": "MercadoLibre", "tk": "Inmobiliaria"}


def _data_rank(r):
    """Cuál aviso de un grupo de duplicados mostrar: el de datos más completos."""
    return ({"ficha": 3, "lista": 3, "direccion": 1}.get(r.get("geo_src"), 0)
            + sum(1 for k in ("m2_cub", "amb", "expensas", "antig") if r.get(k) is not None)
            + (1 if r.get("features") else 0))


def mark_duplicates(rows):
    """El mismo inmueble publicado en varios sitios (o dos veces): misma zona, a menos
    de 150 m, precio a ±3 % y m² a ±8 %. Marca r['dup_of'] y r['otros']."""
    from .stations import haversine
    cells = {}
    for r in rows:
        r["dup_of"] = None
        r["otros"] = []
        if r.get("lat") is not None and r.get("price_usd"):
            cells.setdefault((round(r["lat"], 2), round(r["lng"], 2)), []).append(r)
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    for (la, lo), group in cells.items():
        near = [o for dla in (-0.01, 0, 0.01) for dlo in (-0.01, 0, 0.01)
                for o in cells.get((round(la + dla, 2), round(lo + dlo, 2)), [])]
        for a in group:
            for b in near:
                if a["id"] >= b["id"] or a["tipo"] != b["tipo"]:
                    continue
                if abs(a["price_usd"] - b["price_usd"]) > 0.03 * a["price_usd"]:
                    continue
                ma, mb = a.get("m2_cub") or a.get("m2_tot"), b.get("m2_cub") or b.get("m2_tot")
                if ma and mb and abs(ma - mb) > 0.08 * max(ma, mb):
                    continue
                if not (ma and mb) and a["price_usd"] != b["price_usd"]:
                    continue
                if haversine(a["lat"], a["lng"], b["lat"], b["lng"]) > 150:
                    continue
                parent[find(a["id"])] = find(b["id"])
    groups = {}
    by_id = {r["id"]: r for r in rows}
    for x in list(parent):
        groups.setdefault(find(x), set()).add(x)
    for root, members in groups.items():
        members.add(root)
        ms = sorted((by_id[m] for m in members), key=_data_rank, reverse=True)
        main = ms[0]
        for o in ms[1:]:
            o["dup_of"] = main["id"]
        for o in ms:
            o["otros"] = [(x["agent"] if x["id"][:2] == "tk" else SITE_NAMES.get(x["id"][:2], "?"),
                           x["url"], x["price_usd"])
                          for x in ms if x is not o]


def score_all(rows, s):
    mark_duplicates(rows)
    medians = zone_medians(rows)
    w = s["pesos"]
    total_w = sum(w.values()) or 1
    for r in rows:
        c = criteria(r, s, medians)
        r["criterios"] = c
        r["score"] = round(100 * sum(c[k] * w.get(k, 0) for k in c) / total_w)
        p = ppm2(r)
        r["ppm2"] = round(p) if p else None
        med = medians.get((r["zona_slug"], r["tipo"])) or medians.get((r["zona_slug"], None))
        r["vs_zona"] = round(100 * (p / med - 1)) if p and med else None
        r["cochera"] = has_extra(r, "cochera")
        r["credito"] = has_extra(r, "credito")
        h = [x[1] for x in r.get("history", []) if x[1]]
        r["bajo_precio"] = len(h) >= 2 and h[-1] < max(h)
    return rows


def passes(r, f):
    """Filtros duros de la lista/mapa."""
    p = r.get("price_usd")
    if f["precio_max"] and (p is None or p > f["precio_max"]):
        return False
    if f["precio_min"] and (p or 0) < f["precio_min"]:
        return False
    if f["amb_min"] and (r.get("amb") or 0) < f["amb_min"]:
        return False
    if f["m2_min"] and (r.get("m2_cub") or r.get("m2_tot") or 0) < f["m2_min"]:
        return False
    if f["dist_max"] and (r.get("station_m") is None or r["station_m"] > f["dist_max"]):
        return False
    if f["expensas_max"] and (r.get("expensas") or 0) > f["expensas_max"]:
        return False
    if r.get("tipo") not in f["tipos"] and not (r.get("tipo") == "Otro"):
        return False
    if (r.get("grupo") or "Otra") not in f["grupos"]:
        return False
    if f["solo_credito"] and not r.get("credito"):
        return False
    if f["solo_cochera"] and not r.get("cochera"):
        return False
    if f["solo_favoritos"] and not r.get("favorite"):
        return False
    if f.get("ocultar_duplicados", True) and r.get("dup_of"):
        return False
    if f.get("sitios") is not None and r["id"][:2] not in f["sitios"]:
        return False
    if f["ocultar_descartados"] and r.get("discarded"):
        return False
    if f["solo_con_ubicacion"] and r.get("lat") is None:
        return False
    return True
