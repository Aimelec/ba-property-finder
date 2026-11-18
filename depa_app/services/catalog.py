"""The listings as the app shows them: loaded from the database, located, scored and filtered.
Qt-free: the window wraps it in ui/app_state.py (which adds the signals)."""
from ..domain import filters, geo, scoring
from ..opendata import stations, subte
from ..repositories import listings_db as db


class Catalog:
    """Settings + all listings with their score; `filtered()` applies the Filters panel."""

    def __init__(self, settings):
        self.settings = settings
        self.rows = []
        self.by_id = {}
        self.text = ""           # free-text search (not saved)
        self.stations = stations.load()
        self.station_pos = {(s["name"], s["line"]): s for s in self.stations}
        self.subte = subte.load()
        if "tk" not in settings["filtro"].get("sitios", []) and not settings.get("_tk_visible"):
            settings["filtro"].setdefault("sitios", []).append("tk")  # new source: make it visible once
            settings["_tk_visible"] = True

    def db_mtime(self):
        try:
            return db.DB_PATH.stat().st_mtime
        except OSError:
            return 0

    def reload(self):
        self.loaded_mtime = self.db_mtime()
        con = db.connect()
        rows = db.all_listings(con)
        changed = False
        for r in rows:  # located listings without a station, or with one that no longer counts (slow branch)
            if r["lat"] is not None and (r["station_m"] is None
                                         or (r["station"], r["station_line"]) not in self.station_pos):
                st, d = geo.nearest(self.stations, r["lat"], r["lng"])
                con.execute("UPDATE listings SET station=?, station_line=?, station_m=? WHERE id=?",
                            (st["name"], st["line"], round(d), r["id"]))
                r.update(station=st["name"], station_line=st["line"], station_m=round(d))
                changed = True
        if changed:
            con.commit()
        con.close()
        self.rows = rows
        self.rescore()

    def rescore(self):
        sub = self.subte.get("stations", [])
        for r in self.rows:
            if r["lat"] is not None and sub and "subte_m" not in r:
                st, d = geo.nearest(sub, r["lat"], r["lng"])
                r["subte"], r["subte_line"], r["subte_m"] = st["name"], st["line"], round(d)
        scoring.score_all(self.rows, self.settings)
        self.rows.sort(key=lambda r: -r["score"])
        self.by_id = {r["id"]: r for r in self.rows}

    def filtered(self):
        f = self.settings["filtro"]
        t = self.text.lower().strip()
        out = []
        for r in self.rows:
            if not filters.passes(r, f):
                continue
            if t and t not in " ".join(str(r.get(k) or "") for k in
                                       ("title", "address", "zona", "station", "agent")).lower():
                continue
            out.append(r)
        return out

    def set_flag(self, lid, field, value):
        con = db.connect()
        db.set_flag(con, lid, field, value)
        con.close()
        if lid in self.by_id:
            self.by_id[lid][field] = value

    def station_of(self, r):
        return self.station_pos.get((r.get("station"), r.get("station_line")))
