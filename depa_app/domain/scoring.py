"""0-100 score of each property according to the user's preferences (Preferences page).

Each criterion gives a value in 0..1; the score is their average weighted by the user's weights.
When a listing lacks some data (e.g. not located yet) that criterion counts MISSING, so incomplete
listings are not rewarded. Criterion keys match the stored settings ('pesos'): estacion, precio_m2,
zona, superficie, expensas, antiguedad, extras.
"""
from statistics import median

from .duplicates import mark_duplicates

MISSING = 0.3
EXTRA_KEYS = {
    "cochera": ("cochera",),                                       # parking
    "exterior": ("balc", "terraza", "patio", "jard", "parque"),    # balcony, terrace, patio, garden
    "credito": ("apto cr",),                                        # eligible for a mortgage
}


def clamp(x):
    return max(0.0, min(1.0, x))


def ppm2(r):
    """USD per m² (covered area, else total), or None."""
    m2 = r.get("m2_cub") or r.get("m2_tot")
    if r.get("price_usd") and m2 and m2 >= 15:
        return r["price_usd"] / m2
    return None


def zone_medians(rows):
    """Median USD/m² per (zone, type) when there are at least 5 listings, else per zone."""
    by_zt, by_z = {}, {}
    for r in rows:
        p = ppm2(r)
        if p:
            by_zt.setdefault((r["zona_slug"], r["tipo"]), []).append(p)
            by_z.setdefault(r["zona_slug"], []).append(p)
    out = {k: median(v) for k, v in by_zt.items() if len(v) >= 5}
    out.update({(z, None): median(v) for z, v in by_z.items()})
    return out


def zone_median(r, medians):
    return medians.get((r["zona_slug"], r["tipo"])) or medians.get((r["zona_slug"], None))


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
    med = zone_median(r, medians)
    # 30 % cheaper than the zone's median = 1, 30 % more expensive = 0
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
        # monthly fees (ARS) per 1000 USD of price: 0 -> 1, 4000 or more -> 0
        c["expensas"] = clamp(1 - (exp / max(price or 100000, 1) * 1000) / 4000)

    a = r.get("antig")
    c["antiguedad"] = MISSING if a is None else clamp(1 - a / 60)

    c["extras"] = sum(has_extra(r, k) for k in EXTRA_KEYS) / len(EXTRA_KEYS)
    return c


def score_all(rows, s):
    """Marks duplicates, then adds score, criteria and derived fields to every row (in place)."""
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
        med = zone_median(r, medians)
        r["vs_zona"] = round(100 * (p / med - 1)) if p and med else None
        r["cochera"] = has_extra(r, "cochera")
        r["credito"] = has_extra(r, "credito")
        h = [x[1] for x in r.get("history", []) if x[1]]
        r["bajo_precio"] = len(h) >= 2 and h[-1] < max(h)
    return rows
