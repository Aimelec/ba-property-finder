"""Optional plugins: extra capabilities installed next to the app as a `depa_private` package.

The public project works without them. A plugin package can provide:
- browser_fetcher(parent): an object with fetch(url, should_stop) -> html, used instead of plain HTTP
  for sources whose pages need a real browser (Argenprop).
- zone_slicer(): read_sliced(worker, client, con, stats, key, slug, max_pages, done, planned), used when a
  zone has more result pages than a site shows (Zonaprop); without it, the pages the site shows are read.
"""
try:
    import depa_private as _private
except ImportError:
    _private = None


def browser_fetcher(parent):
    f = getattr(_private, "browser_fetcher", None)
    return f(parent) if f else None


def zone_slicer():
    f = getattr(_private, "zone_slicer", None)
    return f() if f else None
