"""Create a demo data folder with invented listings, to try the app (and take screenshots) without
scraping anything.

    venv\\Scripts\\python.exe scripts\\demo_data.py demo_data
    set DEPA_DATA_DIR=demo_data  &&  venv\\Scripts\\python.exe main.py

Listings are random but reproducible (seeded): generic street names with random numbers, example.com
links, made-up agencies. They are placed around real AMBA train stations (OpenStreetMap, downloaded on
first use if the folder has no estaciones.json) so the map and the station scores look realistic.
Some listings are published on two sites (to show duplicate detection) and some dropped in price.
"""
import argparse
import json
import math
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# zone key (domain/zones.py) -> (name, group, centre lat/lng, typical USD per m²)
ZONES = {
    "partido-de-san-fernando": ("San Fernando", "GBA Norte", -34.444, -58.560, 1500),
    "partido-de-tigre": ("Tigre", "GBA Norte", -34.430, -58.600, 1450),
    "partido-de-san-isidro": ("San Isidro", "GBA Norte", -34.480, -58.530, 2100),
    "partido-de-vicente-lopez": ("Vicente López", "GBA Norte", -34.520, -58.490, 2300),
    "nunez": ("Núñez", "CABA", -34.545, -58.465, 2700),
    "belgrano": ("Belgrano", "CABA", -34.562, -58.458, 2800),
    "villa-urquiza": ("Villa Urquiza", "CABA", -34.573, -58.488, 2400),
    "palermo": ("Palermo", "CABA", -34.582, -58.425, 3000),
    "caballito": ("Caballito", "CABA", -34.618, -58.440, 2200),
    "almagro": ("Almagro", "CABA", -34.608, -58.420, 2100),
}
STREETS = ["Av. del Libertador", "Belgrano", "San Martín", "Rivadavia", "Mitre", "Sarmiento", "Moreno",
           "Alsina", "Pueyrredón", "Las Heras", "Güemes", "Italia", "España", "Uruguay", "Paraná", "Brasil"]
SITES = ["ap", "zp", "ml", "tk"]
AGENCIES = [f"Demo agency {c}" for c in "ABCDEFG"]
TIPOS = [("Departamento", 0.6, (30, 90)), ("PH", 0.2, (50, 120)), ("Casa", 0.2, (80, 220))]


def offset(lat, lng, meters, angle):
    return (lat + meters * math.cos(angle) / 111_320,
            lng + meters * math.sin(angle) / (111_320 * math.cos(math.radians(lat))))


def make_listings(n, stations, rnd):
    from depa_app.domain.geo import haversine
    rows = []
    for i in range(n):
        key = rnd.choice(list(ZONES))
        name, group, clat, clng, ppm2 = ZONES[key]
        near = [s for s in stations if haversine(clat, clng, s["lat"], s["lng"]) < 2500] or stations
        st = rnd.choice(near)
        lat, lng = offset(st["lat"], st["lng"], rnd.uniform(80, 1500), rnd.uniform(0, 2 * math.pi))
        tipo, _, (lo, hi) = rnd.choices(TIPOS, weights=[t[1] for t in TIPOS])[0]
        m2 = rnd.randint(lo, hi)
        price = round(m2 * ppm2 * rnd.uniform(0.7, 1.3), -3)
        amb = max(1, min(6, round(m2 / 22)))
        site = rnd.choice(SITES)
        extras = rnd.sample(["Cochera", "Balcón", "Terraza", "Apto crédito", "Parrilla"], k=rnd.randint(0, 3))
        street = f"{rnd.choice(STREETS)} {rnd.randint(1, 60) * 100}"
        lid = f"{site}:demo{i:04d}" if site != "tk" else f"tk:example.com:demo{i:04d}"
        row = {
            "id": lid, "source": site, "url": f"https://example.com/demo/{i}",
            "title": f"{tipo} {amb} ambientes en venta en {name}" + (" con " + extras[0].lower() if extras else ""),
            "tipo": tipo, "address": f"{street}, {name}", "zona_slug": key, "zona": name, "grupo": group,
            "price_usd": price, "price_ars": None,
            "expensas": None if tipo == "Casa" else round(m2 * rnd.uniform(500, 1400), -3),
            "m2_cub": m2, "m2_tot": m2 + (rnd.randint(0, 60) if tipo != "Departamento" else 0),
            "amb": amb, "dorm": max(1, amb - 1), "banos": 1 + (m2 > 90), "antig": rnd.choice([0, 5, 10, 25, 40, 60]),
            "photo": None, "agent": rnd.choice(AGENCIES),
            "description": "Invented listing for the demo.",
            "features": json.dumps({e: True for e in extras}, ensure_ascii=False),
            "lat": lat, "lng": lng, "geo_src": "lista" if site in ("zp", "ap") else "direccion",
            "first_seen": "2026-10-18T10:00:00", "last_seen": "2026-11-18T10:00:00",
            "favorite": int(rnd.random() < 0.03),
        }
        rows.append(row)
        if rnd.random() < 0.12:     # the same property on another site, a few metres away, ±1 % price
            twin = dict(row, id=f"{rnd.choice([s for s in SITES if s not in ('tk', site)])}:demo{i:04d}b",
                        price_usd=round(price * rnd.uniform(0.99, 1.01), -2), url=f"https://example.com/demo/{i}b")
            twin["lat"], twin["lng"] = offset(lat, lng, rnd.uniform(5, 40), rnd.uniform(0, 6.28))
            rows.append(twin)
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description="Create a demo data folder with invented listings.")
    p.add_argument("folder", type=Path)
    p.add_argument("-n", type=int, default=600, help="number of listings (default 600)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--stations-from", type=Path, default=ROOT / "data",
                   help="copy the public OpenStreetMap files (stations, subte, settlements) from this folder")
    args = p.parse_args(argv)
    folder = args.folder.resolve()
    if (folder / "propiedades.db").exists():
        sys.exit(f"{folder} already has a database: choose an empty folder.")
    folder.mkdir(parents=True, exist_ok=True)
    for f in ("estaciones.json", "subte.json", "barrios_populares.json"):   # public open data only
        if (args.stations_from / f).exists():
            shutil.copyfile(args.stations_from / f, folder / f)

    import os
    os.environ["DEPA_DATA_DIR"] = str(folder)
    sys.path.insert(0, str(ROOT))
    from depa_app.opendata import stations
    from depa_app.repositories import listings_db as db

    rnd = random.Random(args.seed)
    rows = make_listings(args.n, stations.load(), rnd)
    con = db.connect()
    cols = list(rows[0])
    con.executemany(f"INSERT INTO listings ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    [[r[c] for c in cols] for r in rows])
    hist = [(r["id"], "2026-10-18", r["price_usd"] * 1.08) for r in rows if rnd.random() < 0.08]
    con.executemany("INSERT INTO price_history (id, date, price_usd) VALUES (?, ?, ?)",
                    hist + [(i, "2026-11-10", next(r["price_usd"] for r in rows if r["id"] == i)) for i, _, _ in hist])
    con.commit()
    con.close()
    settings = {"zonas": list(ZONES), "precio_max": 400000, "idioma": "en",
                "filtro": {"precio_max": 400000, "solo_con_ubicacion": False}}
    (folder / "ajustes.json").write_text(json.dumps(settings, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} invented listings in {folder}")


if __name__ == "__main__":
    main()
