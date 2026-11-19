"""Interface language (depa_app/i18n.py): every text shown in the app has a Spanish version."""
import ast
import string
from pathlib import Path

import pytest

from depa_app import i18n
from depa_app.translations.es import TEXTS

ROOT = Path(__file__).parents[2]
NOT_TRANSLATED = {"Argenprop", "Zonaprop", "MercadoLibre", "MeLi", "PH", "Subte", "USD/m²", "m²"}   # names / symbols


def tr_literals():
    """English texts passed to tr() as literals, anywhere in the app."""
    out = {}
    for f in [*ROOT.joinpath("depa_app").rglob("*.py"), ROOT / "main.py"]:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "tr" and node.args \
                    and isinstance(node.args[0], ast.Constant):
                out.setdefault(node.args[0].value, f"{f.relative_to(ROOT)}:{node.lineno}")
    return out


def label_tables():
    """Texts translated through variables: the label tables of the pages."""
    from depa_app.sources import SITE_NAMES
    from depa_app.ui import filters, labels, listings, prefs, search
    texts = [*(t for _, t, *_ in filters.NUMS), *(t for _, t in filters.FLAGS), *(t for _, t in filters.SITIOS),
             *(c[0] for c in listings.COLUMNS), *listings.CRIT_NAMES.values(), *listings.SITE_SHORT.values(),
             *(t for _, t in prefs.WEIGHTS), *search.SITE_NOTES.values(), *(t for _, t in search.TIPOS),
             *labels.TIPOS.values(), *labels.GROUPS.values(), *SITE_NAMES.values()]
    return [t for t in texts if t not in NOT_TRANSLATED]


@pytest.fixture(autouse=True)
def english_after():
    yield
    i18n.set_language("en")


def test_every_tr_literal_has_a_spanish_version():
    missing = {t: where for t, where in tr_literals().items() if t not in TEXTS and t not in NOT_TRANSLATED}
    assert not missing, missing


def test_every_label_table_text_has_a_spanish_version():
    assert [t for t in label_tables() if t not in TEXTS] == []


def test_placeholders_match_between_languages():
    fields = lambda s: sorted(x[1] for x in string.Formatter().parse(s) if x[1])
    assert [t for t in TEXTS if fields(t) != fields(TEXTS[t])] == []


def test_switching_language():
    assert i18n.tr("{n} rooms", n=3) == "3 rooms" and i18n.number(12345.6) == "12,346"
    i18n.set_language("es")
    assert i18n.tr("{n} rooms", n=3) == "3 amb." and i18n.number(12345.6) == "12.346"
    assert i18n.number(1.5, 1) == "1,5"
    i18n.set_language("xx")                      # unknown -> English
    assert i18n.language() == "en" and i18n.tr("Search") == "Search"


def test_untranslated_text_falls_back_to_english():
    i18n.set_language("es")
    assert i18n.tr("A text nobody translated") == "A text nobody translated"
