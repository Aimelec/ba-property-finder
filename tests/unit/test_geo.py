"""Distances and the AMBA area check (domain/geo.py), and where the area check is applied."""
import pytest

from depa_app.domain import geo
from depa_app.services import scrape


def test_haversine_known_distance():
    # Obelisco -> Plaza de Mayo, about 1.1 km
    assert geo.haversine(-34.6037, -58.3816, -34.6083, -58.3712) == pytest.approx(1080, abs=40)


def test_nearest_station():
    stations = [{"name": "A", "lat": -34.50, "lng": -58.50}, {"name": "B", "lat": -34.60, "lng": -58.40}]
    best, d = geo.nearest(stations, -34.59, -58.41)
    assert best["name"] == "B" and d < 1500


def test_walking_minutes():
    assert geo.walk_minutes(400) == 6       # 400 m straight line ≈ 520 m of streets at 80 m/min


@pytest.mark.parametrize("lat, lng, inside", [
    (-34.6037, -58.3816, True),     # CABA
    (-34.42, -58.58, True),         # Tigre
    (7.0, -60.0, False),            # a listing pinned in Venezuela
    (-32.9, -68.8, False),          # Mendoza
    (-34.61, -56.17, False),        # Montevideo
])
def test_in_area(lat, lng, inside):
    assert geo.in_area(lat, lng) is inside


def test_positions_outside_the_area_are_forgotten_in_memory():
    rows = [{"lat": 7.0, "lng": -60.0, "station": "X", "station_line": "Mitre", "station_m": 1.0},
            {"lat": -34.5, "lng": -58.5, "station": "Y", "station_line": "Mitre", "station_m": 300.0},
            {"lat": None, "lng": None}]
    geo.clear_outside_area(rows)
    assert rows[0] == {"lat": None, "lng": None, "station": None, "station_line": None, "station_m": None}
    assert rows[1]["lat"] == -34.5 and rows[1]["station"] == "Y"


def test_geocoding_matches_outside_the_area_are_rejected(monkeypatch):
    answers = {"Calle 1": (-34.5, -58.5), "Calle 2": (7.0, -60.0), "Calle 3": None}
    monkeypatch.setattr(scrape.geocode, "geocode", lambda address, zona, grupo: answers[address])
    assert scrape.ScrapeRun._geocode("Calle 1", "Tigre", "GBA Norte") == (-34.5, -58.5)
    assert scrape.ScrapeRun._geocode("Calle 2", "Tigre", "GBA Norte") is None
    assert scrape.ScrapeRun._geocode("Calle 3", "Tigre", "GBA Norte") is None
