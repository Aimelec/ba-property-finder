"""Hard filters of the list and the map (the Filters panel)."""


def passes(r, f):
    """True when listing `r` matches filter settings `f` (0 / empty = no limit)."""
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
