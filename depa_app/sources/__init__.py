"""Listing sources: one module per site, all with the same shape (a ListingSource).

A source module provides:
    SITE          two-letter id prefix stored with each listing ('ap', 'zp', 'ml', 'tk')
    NAME          display name
    PER_PAGE      listings per result page
    CLIENT_OPTS   pacing for the polite Client (pause, block_waits, ...)
    search_url(tipos, zona, precio_min, precio_max, page) -> str
    parse_list(html) -> (listings, total pages, total results)
optionally:
    MAX_PAGES      result pages the site shows per search
    NEEDS_BROWSER  True when pages must come from a browser fetcher (plugin)
    parse_detail(html) -> dict   extra data from a listing's own page

Adding a site = adding a module with this shape and registering it in SOURCES.
"""
from . import argenprop, mercadolibre, tokko, zonaprop

SOURCES = {"ap": argenprop, "zp": zonaprop, "ml": mercadolibre, "tk": tokko}
SITE_NAMES = {k: m.NAME for k, m in SOURCES.items()}
