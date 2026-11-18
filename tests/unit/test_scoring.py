"""The weighted score (domain/scoring.py) and the hard filters (domain/filters.py)."""
from copy import deepcopy

import pytest

from depa_app.config import DEFAULTS
from depa_app.domain import scoring
from depa_app.domain.filters import passes

S = deepcopy(DEFAULTS)


def row(**kw):
    r = {"id": "ap:1", "zona_slug": "z", "tipo": "Departamento", "grupo": "GBA Norte", "price_usd": 100000,
         "m2_cub": 50, "m2_tot": None, "station_m": 300, "expensas": 40000, "antig": 10, "features": {},
         "title": "", "history": [], "lat": None, "lng": None, "url": "", "agent": ""}
    r.update(kw)
    return r


class TestCriteria:
    def test_station_full_score_up_to_the_ideal_distance_then_linear_to_zero(self):
        med = {}
        assert scoring.criteria(row(station_m=400), S, med)["estacion"] == 1.0
        assert scoring.criteria(row(station_m=1200), S, med)["estacion"] == pytest.approx(0.5)   # halfway 400..2000
        assert scoring.criteria(row(station_m=5000), S, med)["estacion"] == 0.0
        assert scoring.criteria(row(station_m=None), S, med)["estacion"] == scoring.MISSING

    def test_price_per_m2_compared_with_the_zone_median(self):
        med = {("z", "Departamento"): 2000}
        assert scoring.criteria(row(price_usd=70000, m2_cub=50), S, med)["precio_m2"] == pytest.approx(1.0)  # 30 % cheaper
        assert scoring.criteria(row(price_usd=100000, m2_cub=50), S, med)["precio_m2"] == pytest.approx(0.5)  # at median
        assert scoring.criteria(row(price_usd=130000, m2_cub=50), S, med)["precio_m2"] == pytest.approx(0.0)  # 30 % dearer

    def test_houses_without_monthly_fees_get_the_full_fees_score(self):
        assert scoring.criteria(row(tipo="Casa", expensas=None), S, {})["expensas"] == 1.0
        assert scoring.criteria(row(expensas=None), S, {})["expensas"] == scoring.MISSING

    def test_extras_from_features_and_title(self):
        r = row(features={"Cocheras": "1"}, title="Depto con balcón apto crédito")
        assert scoring.criteria(r, S, {})["extras"] == 1.0
        assert scoring.criteria(row(), S, {})["extras"] == 0.0


class TestScoreAll:
    def test_score_is_the_weighted_average_of_the_criteria(self):
        rows = scoring.score_all([row()], S)
        c, w = rows[0]["criterios"], S["pesos"]
        assert rows[0]["score"] == round(100 * sum(c[k] * w[k] for k in c) / sum(w.values()))

    def test_weights_change_the_ranking(self):
        near_dear = row(id="ap:1", station_m=200, price_usd=140000)
        far_cheap = row(id="ap:2", station_m=1900, price_usd=60000)
        default = {r["id"]: r["score"] for r in scoring.score_all([dict(near_dear), dict(far_cheap)], S)}
        price_first = deepcopy(S)
        price_first["pesos"] = {k: 0 for k in S["pesos"]} | {"precio_m2": 100}
        priced = {r["id"]: r["score"] for r in scoring.score_all([dict(near_dear), dict(far_cheap)], price_first)}
        assert default["ap:1"] > default["ap:2"] and priced["ap:2"] > priced["ap:1"]

    def test_zone_median_needs_five_listings_per_type(self):
        rows = [row(id=f"ap:{i}", price_usd=100000 + i * 1000) for i in range(4)]
        med = scoring.zone_medians(rows)
        assert ("z", "Departamento") not in med and ("z", None) in med

    def test_price_drop_is_detected_from_history(self):
        r = scoring.score_all([row(history=[("2026-10-01", 120000), ("2026-10-10", 110000)])], S)[0]
        assert r["bajo_precio"] is True and r["ppm2"] == 2000


class TestFilters:
    F = deepcopy(DEFAULTS["filtro"])

    def test_defaults_let_a_normal_listing_through(self):
        assert passes(row(), self.F)

    @pytest.mark.parametrize("change, rule", [
        ({"price_usd": 250000}, {}), ({"amb": 1}, {"amb_min": 2}), ({"station_m": 900}, {"dist_max": 600}),
        ({"tipo": "Casa"}, {"tipos": ["Departamento"]}), ({"grupo": "CABA"}, {"grupos": ["GBA Norte"]}),
        ({"dup_of": "zp:9"}, {}), ({"discarded": 1}, {}), ({"lat": None}, {"solo_con_ubicacion": True}),
        ({"id": "ml:1"}, {"sitios": ["ap"]})])
    def test_each_rule_excludes(self, change, rule):
        assert not passes(row(**change), self.F | rule)
