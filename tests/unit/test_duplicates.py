"""Cross-site duplicate detection (domain/duplicates.py)."""
import random

from depa_app.domain.duplicates import data_rank, mark_duplicates, same_property


def listing(id_, lat=-34.45, lng=-58.55, price=100000, m2=60, tipo="Departamento", **extra):
    return {"id": id_, "lat": lat, "lng": lng, "price_usd": price, "m2_cub": m2, "tipo": tipo,
            "url": f"https://example.com/{id_}", "agent": "Agency X", **extra}


class TestSameProperty:
    def test_same_place_price_and_area(self):
        assert same_property(listing("ap:1"), listing("zp:1", lat=-34.4501, price=102000, m2=63))

    def test_different_type(self):
        assert not same_property(listing("ap:1"), listing("zp:1", tipo="Casa"))

    def test_price_more_than_3_percent_apart(self):
        assert not same_property(listing("ap:1"), listing("zp:1", price=104000))

    def test_area_more_than_8_percent_apart(self):
        assert not same_property(listing("ap:1"), listing("zp:1", m2=66))

    def test_more_than_150_m_apart(self):
        assert not same_property(listing("ap:1"), listing("zp:1", lat=-34.452))     # ~220 m north

    def test_without_area_the_price_must_match_exactly(self):
        assert same_property(listing("ap:1", m2=None), listing("zp:1", m2=None))
        assert not same_property(listing("ap:1", m2=None), listing("zp:1", m2=None, price=100500))


class TestMarkDuplicates:
    def test_groups_copies_and_keeps_the_most_complete(self):
        rows = [listing("ml:1"), listing("zp:1", geo_src="lista", amb=3, expensas=50000), listing("ap:9", lat=-34.6)]
        mark_duplicates(rows)
        by = {r["id"]: r for r in rows}
        assert by["zp:1"]["dup_of"] is None and by["ml:1"]["dup_of"] == "zp:1"
        assert [o[0] for o in by["zp:1"]["otros"]] == ["MercadoLibre"]
        assert by["ap:9"]["dup_of"] is None and by["ap:9"]["otros"] == []

    def test_chains_of_matches_form_one_group(self):
        # a~b and b~c (but a and c are 2.9 % + 2.9 % apart): one property published three times
        rows = [listing("ap:1", price=100000), listing("ml:1", price=102900), listing("zp:1", price=105800)]
        mark_duplicates(rows)
        assert sum(1 for r in rows if r["dup_of"] is None) == 1

    def test_agency_copies_are_named_by_agency(self):
        rows = [listing("ap:1", geo_src="ficha"), listing("tk:example.com:7", agent="Leo Propiedades")]
        mark_duplicates(rows)
        assert rows[0]["otros"][0][0] == "Leo Propiedades"

    def test_result_does_not_depend_on_input_order(self):
        """Regression: among equally complete copies the main listing used to depend on set iteration
        order (string hashing is randomized per run), so it could change every time the app opened."""
        base = [listing(f"{site}:{i}") for i, site in enumerate(["ap", "zp", "ml", "tk", "ap", "zp"])]
        results = set()
        for seed in range(20):
            rows = [dict(r) for r in base]
            random.Random(seed).shuffle(rows)
            mark_duplicates(rows)
            results.add(tuple(sorted((r["id"], r["dup_of"], tuple(o[1] for o in r["otros"])) for r in rows)))
        assert len(results) == 1
        main = [r for r in base if all(r["id"] <= o["id"] for o in base)][0]["id"]
        assert ("ap:0", None) == next((i, d) for i, d, _ in results.pop() if i == main)

    def test_rank_counts_location_source_and_data(self):
        assert data_rank({"geo_src": "ficha", "m2_cub": 50, "amb": 2, "features": {"x": 1}}) == 3 + 2 + 1
        assert data_rank({"geo_src": "direccion"}) == 1
