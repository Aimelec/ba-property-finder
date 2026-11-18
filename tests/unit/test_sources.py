"""Site parsers and URL builders, on small synthetic pages (tests/fixtures/, invented data)."""
from pathlib import Path

import pytest

from depa_app.sources import SITE_NAMES, SOURCES, argenprop, mercadolibre, tokko, zonaprop

FIX = Path(__file__).parents[1] / "fixtures"


def page(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_every_source_has_the_listing_source_shape():
    for key, src in SOURCES.items():
        assert src.SITE == key and src.NAME and src.PER_PAGE > 0 and isinstance(src.CLIENT_OPTS, dict)
        assert callable(src.search_url) and callable(src.parse_list)
    assert SITE_NAMES == {"ap": "Argenprop", "zp": "Zonaprop", "ml": "MercadoLibre", "tk": "Agencies"}


class TestArgenprop:
    def test_list(self):
        items, pages, total = argenprop.parse_list(page("argenprop_list.html"))
        assert (len(items), pages, total) == (2, 8, 152)
        a, b = items
        assert a["id"] == "ap:111" and a["url"].startswith("https://www.argenprop.com/departamento-en-venta")
        assert (a["tipo"], a["price_usd"], a["price_ars"], a["expensas"]) == ("Departamento", 98500.0, None, 45000.0)
        assert (a["m2_cub"], a["amb"], a["dorm"], a["antig"]) == (62.0, 3.0, 2.0, 0.0)   # "A estrenar" -> 0
        assert a["address"] == "Calle Falsa 123, Tigre" and a["photo"] == "https://img.example/111.jpg"
        assert (b["id"], b["tipo"], b["price_usd"], b["price_ars"]) == ("ap:222", "PH", None, 95000000.0)

    def test_detail(self):
        d = argenprop.parse_detail(page("argenprop_detail.html"))
        assert (d["lat"], d["lng"]) == (-34.4251, -58.5797)
        assert (d["m2_cub"], d["m2_tot"], d["amb"], d["banos"], d["antig"], d["expensas"]) == (62, 70, 3, 1, 10, 45000)
        assert d["features"]["Apto Crédito"] is True and "tres ambientes" in d["description"]

    @pytest.mark.parametrize("text, value", [("USD 99.000", 99000.0), ("45,5 m²", 45.5), ("A estrenar", 0.0), ("", None)])
    def test_number(self, text, value):
        assert argenprop.number(text) == value

    def test_search_url_uses_the_sites_own_type_order(self):
        url = argenprop.search_url(["ph", "departamentos", "casas"], "partido-de-tigre", 0, 160000, 3)
        assert url == "https://www.argenprop.com/casas-o-departamentos-o-ph/venta/partido-de-tigre/dolares-hasta-160000?pagina-3"


class TestZonaprop:
    def test_list(self):
        items, pages, total = zonaprop.parse_list(page("zonaprop_list.html"))
        assert (len(items), pages, total) == (1, 12, 345)       # the development is skipped
        it = items[0]
        assert it["id"] == "zp:501" and it["tipo"] == "Departamento" and it["price_usd"] == 120000
        assert (it["lat"], it["lng"]) == (-34.45, -58.55) and it["address"] == "Calle Falsa 456, Victoria, San Fernando"
        assert (it["m2_tot"], it["m2_cub"], it["amb"]) == (55.0, 50.0, 2.0) and it["expensas"] == 60000
        assert it["features"]["Cocheras"] == "1" and it["description"].strip() == "Muy lindo"

    def test_page_without_data(self):
        assert zonaprop.parse_list("<html></html>") == ([], 0, 0)

    def test_search_url(self):
        assert zonaprop.search_url(["casas", "ph"], "tigre", 100000, 160000, 2) == \
            "https://www.zonaprop.com.ar/casas-ph-venta-tigre-100000-160000-dolar-pagina-2.html"


class TestMercadoLibre:
    def test_list(self):
        items, pages, total = mercadolibre.parse_list(page("mercadolibre_list.html"))
        assert (len(items), pages, total) == (1, 4, 150)        # the office is filtered out by type
        it = items[0]
        assert it["id"] == "ml:MLA900" and it["tipo"] == "Casa" and it["price_usd"] == 150000
        assert (it["amb"], it["dorm"], it["banos"], it["m2_tot"], it["m2_cub"]) == (4, 3, 2, 180, 120)
        assert it["agent"] == "Inmobiliaria Ejemplo" and it["photo"].endswith("abc123-O.jpg")

    def test_types_not_searched_are_skipped(self):
        items, _, _ = mercadolibre.parse_list(page("mercadolibre_list.html"), tipos=("departamentos",))
        assert items == []


class TestTokko:
    def test_list(self):
        items, more = tokko.parse_list(page("tokko_list.html"), "https://www.example-agency.com", "Agency X")
        assert more and len(items) == 2                         # the rental is skipped
        casa, depto = items
        assert casa["id"] == "tk:example-agency.com:7001" and casa["zona_slug"] == "partido-de-san-fernando"
        assert (casa["price_usd"], casa["m2_tot"], casa["amb"], casa["dorm"]) == (135000, 200, 4, 3)
        assert depto["zona_slug"] == "almagro" and depto["price_usd"] is None   # "USD 1" = price on request

    @pytest.mark.parametrize("place, zone", [
        ("Virreyes, San Fernando", "partido-de-san-fernando"), ("Nordelta, Tigre", "partido-de-tigre"),
        ("Martínez, San Isidro", "partido-de-san-isidro"), ("Palermo, Capital Federal", "palermo"),
        ("Mataderos, Capital Federal", None), ("Rosario, Santa Fe", None)])
    def test_zone_of(self, place, zone):
        assert tokko.zone_of(place) == zone

    def test_search_url(self):
        assert tokko.search_url("https://www.example-agency.com/", 1) == "https://www.example-agency.com/Venta"
        assert tokko.search_url("https://www.example-agency.com", 3) == "https://www.example-agency.com/Venta?o=2,2&p=3"
