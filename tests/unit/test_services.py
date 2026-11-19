"""The services with fakes: a download run (ScrapeRun) and the listing catalog (Catalog).
An in-memory SQLite database replaces data/propiedades.db; no network, no real data."""
import sqlite3
from copy import deepcopy

import pytest

from depa_app.config import DEFAULTS
from depa_app.repositories import listings_db
from depa_app.services import catalog as catalog_mod
from depa_app.services import scrape

STATIONS = [{"name": "Tigre", "line": "Mitre", "lat": -34.42, "lng": -58.58},
            {"name": "Retiro", "line": "Mitre", "lat": -34.59, "lng": -58.37}]


def memory_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(listings_db.SCHEMA)
    return con


class NoClose:
    """Wraps a connection so the code under test can close it while the test keeps reading it."""
    def __init__(self, con):
        self.con = con

    def __getattr__(self, name):
        return getattr(self.con, name)

    def close(self):
        pass


@pytest.fixture
def db(monkeypatch):
    con = memory_db()
    monkeypatch.setattr(listings_db, "connect", lambda: NoClose(con))
    return con


class FakeSource:
    SITE, NAME, PER_PAGE = "xx", "Fake", 2
    CLIENT_OPTS = {}

    def __init__(self, pages):
        self.pages = pages                  # page number -> list of listings

    def search_url(self, tipos, zona, lo, hi, page):
        return f"https://fake.example/{zona}/{page}"

    def parse_list(self, html):
        n = int(html)
        return self.pages[n], len(self.pages), sum(len(v) for v in self.pages.values())


class FakeClient:
    def __init__(self, **kw):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return url.rsplit("/", 1)[1]        # the "html" is just the page number

    def sleep(self, s):
        pass


def make_run(monkeypatch, src, settings=None, geocoded=None):
    monkeypatch.setitem(scrape.SOURCES, "xx", src)
    monkeypatch.setattr(scrape, "site_slug", lambda key, site: key)
    monkeypatch.setattr(scrape, "Client", FakeClient)
    monkeypatch.setattr(scrape.stations, "load", lambda: STATIONS)
    monkeypatch.setattr(scrape.geocode, "geocode", lambda address, zona, grupo: (geocoded or {}).get(address))
    s = deepcopy(DEFAULTS) | {"tipos": ["departamentos"], "precio_min": 0, "precio_max": 200000,
                              "avisos_por_zona_norte": 100, "avisos_por_zona": 100}
    s.update(settings or {})
    logs, progress = [], []
    run = scrape.ScrapeRun("xx", s, ["partido-de-tigre"], log=logs.append,
                           progress=lambda *a: progress.append(a))
    return run, logs, progress


def item(i, **kw):
    return {"id": f"xx:{i}", "url": f"https://fake.example/l/{i}", "title": f"Depto {i}", "tipo": "Departamento",
            "address": f"Calle Falsa {i}", "price_usd": 100000, "loc": "Tigre", **kw}


class TestScrapeRun:
    def test_reads_every_page_saves_locates_and_reports(self, db, monkeypatch):
        src = FakeSource({1: [item(1, lat=-34.43, lng=-58.57), item(2)], 2: [item(3, price_usd=900000)]})
        run, logs, progress = make_run(monkeypatch, src, geocoded={"Calle Falsa 2": (-34.44, -58.58)})
        stats = run.run()
        assert (stats["vistos"], stats["nuevos"], stats["ubicados"], stats["error"]) == (2, 2, 1, "")
        rows = {r["id"]: dict(r) for r in db.execute("SELECT * FROM listings")}
        assert set(rows) == {"xx:1", "xx:2"}                         # xx:3 is above the price range
        assert rows["xx:1"]["geo_src"] == "lista" and rows["xx:1"]["station"] == "Tigre"
        assert rows["xx:2"]["geo_src"] == "direccion" and rows["xx:2"]["zona"] == "Tigre"
        assert len(progress) == 2 and any("Result lists finished" in m for m in logs)

    def test_positions_outside_the_area_fall_back_to_the_address(self, db, monkeypatch):
        src = FakeSource({1: [item(1, lat=7.0, lng=-60.0)]})
        run, _, _ = make_run(monkeypatch, src, geocoded={"Calle Falsa 1": (-34.43, -58.57)})
        run.run()
        r = dict(db.execute("SELECT lat, geo_src FROM listings").fetchone())
        assert r == {"lat": -34.43, "geo_src": "direccion"}

    def test_a_second_run_counts_price_drops(self, db, monkeypatch):
        run, logs, _ = make_run(monkeypatch, FakeSource({1: [item(1, lat=-34.43, lng=-58.57)]}))
        run.run()
        run, logs, _ = make_run(monkeypatch, FakeSource({1: [item(1, lat=-34.43, lng=-58.57, price_usd=95000)]}))
        stats = run.run()
        assert (stats["nuevos"], stats["bajas"]) == (0, 1) and any("Price dropped" in m for m in logs)

    def test_stop_ends_the_run_cleanly(self, db, monkeypatch):
        run, logs, _ = make_run(monkeypatch, FakeSource({1: [item(1)], 2: [item(2)]}))
        run.stop()
        stats = run.run()
        assert stats["error"] == "" and any("Stopped" in m for m in logs)

    def test_a_source_that_needs_a_browser_is_skipped_without_one(self, db, monkeypatch):
        src = FakeSource({1: [item(1)]})
        src.NEEDS_BROWSER = True
        run, _, _ = make_run(monkeypatch, src)
        stats = run.run()
        assert "needs a built-in browser" in stats["error"]
        assert db.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0

    def test_an_unexpected_error_is_reported_not_raised(self, db, monkeypatch):
        src = FakeSource({1: [item(1)]})
        src.parse_list = lambda html: 1 / 0
        run, _, _ = make_run(monkeypatch, src)
        assert "ZeroDivisionError" in run.run()["error"]


class TestCatalog:
    @pytest.fixture
    def catalog(self, db, monkeypatch):
        monkeypatch.setattr(catalog_mod.stations, "load", lambda: STATIONS)
        monkeypatch.setattr(catalog_mod.subte, "load", lambda: {"stations": []})
        for i, (lat, lng, price) in enumerate([(-34.43, -58.57, 100000), (-34.58, -58.38, 150000),
                                               (7.0, -60.0, 90000), (None, None, 120000)]):
            listings_db.upsert_list_item(db, item(i, price_usd=price, zona_slug="partido-de-tigre", zona="Tigre",
                                                  grupo="GBA Norte"))
            if lat is not None:
                db.execute("UPDATE listings SET lat=?, lng=?, geo_src='lista' WHERE id=?", (lat, lng, f"xx:{i}"))
        db.commit()
        c = catalog_mod.Catalog(deepcopy(DEFAULTS))
        c.reload()
        return c

    def test_loads_scores_and_sorts(self, catalog):
        assert len(catalog.rows) == 4 and [r["score"] for r in catalog.rows] == sorted(
            (r["score"] for r in catalog.rows), reverse=True)

    def test_stations_are_filled_in_and_outside_positions_dropped(self, catalog):
        by = catalog.by_id
        assert by["xx:0"]["station"] == "Tigre" and by["xx:1"]["station"] == "Retiro"
        assert by["xx:2"]["lat"] is None and by["xx:2"]["station"] is None     # the pin in Venezuela

    def test_filtered_applies_filters_and_free_text(self, catalog):
        catalog.settings["filtro"]["sitios"] = ["xx"]          # the fake test source
        catalog.settings["filtro"]["solo_con_ubicacion"] = True
        assert {r["id"] for r in catalog.filtered()} == {"xx:0", "xx:1"}
        catalog.text = "falsa 1"
        assert [r["id"] for r in catalog.filtered()] == ["xx:1"]

    def test_flags_are_saved(self, catalog, db):
        catalog.set_flag("xx:0", "favorite", 1)
        assert db.execute("SELECT favorite FROM listings WHERE id='xx:0'").fetchone()[0] == 1
        assert catalog.by_id["xx:0"]["favorite"] == 1
