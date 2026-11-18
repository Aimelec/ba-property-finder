"""Base SQLite: avisos + historial de precios."""
import json
import sqlite3
from datetime import datetime

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY, source TEXT, url TEXT, title TEXT, tipo TEXT, address TEXT,
    zona_slug TEXT, zona TEXT, grupo TEXT,
    price_usd REAL, price_ars REAL, expensas REAL,
    m2_cub REAL, m2_tot REAL, amb REAL, dorm REAL, banos REAL, antig REAL,
    photo TEXT, agent TEXT, description TEXT, features TEXT,
    lat REAL, lng REAL, station TEXT, station_line TEXT, station_m REAL,
    first_seen TEXT, last_seen TEXT, detail_at TEXT,
    favorite INTEGER DEFAULT 0, discarded INTEGER DEFAULT 0, notes TEXT DEFAULT '',
    geo_src TEXT, geo_tried INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS price_history (
    id TEXT, date TEXT, price_usd REAL, PRIMARY KEY (id, date)
);
"""

LIST_FIELDS = ["url", "title", "tipo", "address", "zona_slug", "zona", "grupo", "price_usd",
               "price_ars", "expensas", "m2_cub", "m2_tot", "amb", "dorm", "banos", "antig",
               "photo", "agent", "description", "features"]
DETAIL_FIELDS = ["m2_cub", "m2_tot", "amb", "dorm", "banos", "antig", "expensas", "description"]


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect():
    con = sqlite3.connect(DB_PATH, timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")  # varios sitios escriben a la vez y la app lee
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(listings)")}
    for col, decl in (("geo_src", "TEXT"), ("geo_tried", "INTEGER DEFAULT 0")):
        if col not in cols:
            con.execute(f"ALTER TABLE listings ADD COLUMN {col} {decl}")
    # solo escribir si hace falta: un UPDATE pide el bloqueo de escritura aunque no cambie nada,
    # y la ventana (que solo quiere leer) se quedaba esperando a que un sitio terminara de escribir
    if con.execute("SELECT 1 FROM listings WHERE lat IS NOT NULL AND geo_src IS NULL LIMIT 1").fetchone():
        con.execute("UPDATE listings SET geo_src='ficha' WHERE lat IS NOT NULL AND geo_src IS NULL")
    con.commit()  # si no, esta conexión retiene el bloqueo de escritura y traba a las demás
    return con


def upsert_list_item(con, it):
    """Guarda un aviso del listado. Devuelve 'nuevo', 'baja' (bajó el precio) o ''."""
    t = now()
    if isinstance(it.get("features"), dict):
        it = dict(it, features=json.dumps(it["features"], ensure_ascii=False))
    row = con.execute("SELECT price_usd FROM listings WHERE id=?", (it["id"],)).fetchone()
    status = ""
    if row is None:
        cols = ["id", "source", "first_seen", "last_seen"] + LIST_FIELDS
        vals = [it["id"], it["id"].split(":")[0], t, t] + [it.get(f) for f in LIST_FIELDS]
        con.execute(f"INSERT INTO listings ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
        status = "nuevo"
    else:
        # no pisar con vacío lo que ya completó la ficha de detalle
        sets = {f: it.get(f) for f in LIST_FIELDS if it.get(f) is not None}
        sets["last_seen"] = t
        con.execute(f"UPDATE listings SET {', '.join(k + '=?' for k in sets)} WHERE id=?",
                    [*sets.values(), it["id"]])
        old = row["price_usd"]
        if old and it.get("price_usd") and it["price_usd"] < old:
            status = "baja"
    if it.get("price_usd"):
        con.execute("INSERT OR REPLACE INTO price_history VALUES (?,?,?)",
                    (it["id"], t[:10], it["price_usd"]))
    return status


def save_detail(con, lid, d, station=None, station_m=None):
    sets = {f: d[f] for f in DETAIL_FIELDS if d.get(f) is not None}
    sets["features"] = json.dumps(d.get("features", {}), ensure_ascii=False)
    sets["detail_at"] = now()
    if d.get("lat") is not None:
        sets.update(lat=d["lat"], lng=d["lng"], geo_src="ficha")
    if station:
        sets.update(station=station["name"], station_line=station["line"], station_m=round(station_m))
    con.execute(f"UPDATE listings SET {', '.join(k + '=?' for k in sets)} WHERE id=?",
                [*sets.values(), lid])


def pending_details(con, limit, site="ap"):
    """Fichas sin leer: primero favoritos, después los que no se pudieron ubicar."""
    return con.execute(
        f"SELECT id, url FROM listings WHERE id LIKE '{site}:%' AND detail_at IS NULL AND discarded=0 "
        "ORDER BY favorite DESC, (lat IS NULL) DESC, "
        "CASE grupo WHEN 'GBA Norte' THEN 0 WHEN 'CABA' THEN 1 ELSE 2 END, "
        "first_seen DESC LIMIT ?", (limit,)).fetchall()


def pending_geocode(con, site):
    return con.execute("SELECT id, address, zona, grupo FROM listings "
                       "WHERE id LIKE ? AND lat IS NULL AND geo_tried=0", (f"{site}:%",)).fetchall()


def save_list_position(con, lid, lat, lng, station, station_m):
    """Coordenadas exactas que ya vienen en el listado (Zonaprop)."""
    con.execute("UPDATE listings SET lat=?, lng=?, geo_src='lista', geo_tried=1, station=?, "
                "station_line=?, station_m=? WHERE id=?",
                (lat, lng, station["name"], station["line"], round(station_m), lid))


def save_geocode(con, lid, pos, station=None, station_m=None):
    if pos is None:
        con.execute("UPDATE listings SET geo_tried=1 WHERE id=?", (lid,))
        return
    con.execute("UPDATE listings SET lat=?, lng=?, geo_src='direccion', geo_tried=1, station=?, "
                "station_line=?, station_m=? WHERE id=?",
                (pos[0], pos[1], station["name"], station["line"], round(station_m), lid))


def all_listings(con):
    rows = [dict(r) for r in con.execute("SELECT * FROM listings")]
    hist = {}
    for h in con.execute("SELECT id, date, price_usd FROM price_history ORDER BY date"):
        hist.setdefault(h["id"], []).append((h["date"], h["price_usd"]))
    for r in rows:
        r["history"] = hist.get(r["id"], [])
        try:
            r["features"] = json.loads(r["features"]) if r["features"] else {}
        except ValueError:
            r["features"] = {}
    return rows


def set_flag(con, lid, field, value):
    assert field in ("favorite", "discarded", "notes")
    con.execute(f"UPDATE listings SET {field}=? WHERE id=?", (value, lid))
    con.commit()
