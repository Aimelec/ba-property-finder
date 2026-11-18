"""Interface language. The code writes every user-facing text in English, wrapped in tr(); each other
language is a dict {English text: translation} in depa_app/translations/<code>.py.

    tr("{n} listings", n=3)   -> "3 listings" / "3 avisos"
    number(12345.6)            -> "12,346" in English, "12.346" in Spanish

Adding a language = adding translations/<code>.py with a TEXTS dict and listing it in LANGUAGES.
tests/unit/test_i18n.py checks that every tr() text in the code has a translation.
"""
import importlib

LANGUAGES = {"en": "English", "es": "Español"}
DEFAULT = "en"
THOUSANDS = {"en": ",", "es": "."}
DECIMAL = {"en": ".", "es": ","}

_lang = DEFAULT
_texts = {}


def set_language(code):
    """Switch the interface language ('en', 'es'); unknown codes fall back to English."""
    global _lang, _texts
    _lang = code if code in LANGUAGES else DEFAULT
    _texts = {} if _lang == DEFAULT else importlib.import_module(f"depa_app.translations.{_lang}").TEXTS


def language():
    return _lang


def tr(text, **values):
    """`text` (English) in the current language, with {placeholders} filled from `values`."""
    out = _texts.get(text, text)
    return out.format(**values) if values else out


def number(x, decimals=0):
    """Number with the current language's separators: 12345.6 -> '12,346' / '12.346'."""
    s = f"{x:,.{decimals}f}"
    return s.translate(str.maketrans({",": THOUSANDS[_lang], ".": DECIMAL[_lang]}))
