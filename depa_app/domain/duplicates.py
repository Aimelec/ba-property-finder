"""The same property published on several sites (or twice on one): find the groups and pick which
listing to show. Pure logic over listing dicts."""
from .geo import haversine

SITE_NAMES = {"ap": "Argenprop", "zp": "Zonaprop", "ml": "MercadoLibre", "tk": "Inmobiliaria"}

MAX_DISTANCE_M = 150     # same property: closer than this...
PRICE_TOLERANCE = 0.03   # ...price within ±3 %...
AREA_TOLERANCE = 0.08    # ...and m² within ±8 %, same type


def data_rank(r):
    """Which listing of a duplicate group to show: the one with the most complete data."""
    return ({"ficha": 3, "lista": 3, "direccion": 1}.get(r.get("geo_src"), 0)
            + sum(1 for k in ("m2_cub", "amb", "expensas", "antig") if r.get(k) is not None)
            + (1 if r.get("features") else 0))


def same_property(a, b):
    if a["tipo"] != b["tipo"]:
        return False
    if abs(a["price_usd"] - b["price_usd"]) > PRICE_TOLERANCE * a["price_usd"]:
        return False
    ma, mb = a.get("m2_cub") or a.get("m2_tot"), b.get("m2_cub") or b.get("m2_tot")
    if ma and mb and abs(ma - mb) > AREA_TOLERANCE * max(ma, mb):
        return False
    if not (ma and mb) and a["price_usd"] != b["price_usd"]:
        return False
    return haversine(a["lat"], a["lng"], b["lat"], b["lng"]) <= MAX_DISTANCE_M


def source_name(r):
    return r["agent"] if r["id"][:2] == "tk" else SITE_NAMES.get(r["id"][:2], "?")


def mark_duplicates(rows):
    """Sets r['dup_of'] (id of the listing shown instead, or None) and r['otros'] (the other copies:
    (site or agency, url, price)). Located listings are bucketed in ~1 km cells, so only neighbours
    are compared."""
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
                if a["id"] < b["id"] and same_property(a, b):
                    parent[find(a["id"])] = find(b["id"])
    groups = {}
    by_id = {r["id"]: r for r in rows}
    for x in list(parent):
        groups.setdefault(find(x), set()).add(x)
    for root, members in groups.items():
        members.add(root)
        # most complete first; ties broken by id so the result never depends on set order
        ms = sorted((by_id[m] for m in members), key=lambda r: (-data_rank(r), r["id"]))
        main = ms[0]
        for o in ms[1:]:
            o["dup_of"] = main["id"]
        for o in ms:
            o["otros"] = [(source_name(x), x["url"], x["price_usd"]) for x in ms if x is not o]
