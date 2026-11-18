"""Argenprop: result lists (20 listings per page) and detail pages (exact location, features).

Its pages are loaded with a built-in browser (optional plugin, see plugins.py), slowly.
"""
import re

from selectolax.lexbor import LexborHTMLParser


SITE = "ap"
NAME = "Argenprop"
PER_PAGE = 20
NEEDS_BROWSER = True
# one page every 15-16 s; long waits before retrying if the site pushes back
CLIENT_OPTS = {"pause": (15.0, 16.0), "block_waits": (660, 900, 1200)}

BASE = "https://www.argenprop.com"

# icon class on the result card -> field
CARD_ICONS = {
    "superficie_cubierta": "m2_cub",
    "superficie_total": "m2_tot",
    "cantidad_dormitorios": "dorm",
    "antiguedad": "antig",
    "cantidad_banos": "banos",
    "cantidad_ambientes": "amb",
}


def number(text):
    """'USD 99.000' -> 99000.0, '45,5 m²' -> 45.5, 'A estrenar' (brand new) -> 0."""
    if not text:
        return None
    if "estrenar" in text.lower():
        return 0.0
    m = re.search(r"\d[\d.]*(?:,\d+)?", text)
    if not m:
        return None
    return float(m.group(0).replace(".", "").replace(",", "."))


def search_url(tipos, zona, precio_min=0, precio_max=0, page=1):
    """tipos: ['departamentos', 'casas', 'ph'] -> URL of the for-sale result list."""
    # Argenprop redirects to its own order (casas, departamentos, ph): asking that way avoids a second load
    url = f"{BASE}/{'-o-'.join(sorted(tipos))}/venta/{zona}"
    if precio_min and precio_max:
        url += f"/dolares-{int(precio_min)}-{int(precio_max)}"
    elif precio_max:
        url += f"/dolares-hasta-{int(precio_max)}"
    elif precio_min:
        url += f"/dolares-desde-{int(precio_min)}"
    if page > 1:
        url += f"?pagina-{page}"
    return url


def _text(node):
    return " ".join(node.text(separator=" ").split()) if node else ""


def parse_list(html):
    """(listings, total pages, total results)."""
    tree = LexborHTMLParser(html)
    items = []
    for card in tree.css("div.listing__item a.card"):
        aid = card.attributes.get("idaviso") or card.attributes.get("data-item-card")
        href = card.attributes.get("href") or ""
        if not aid or not href:
            continue
        cur = _text(card.css_first(".card__currency"))
        price = number(_text(card.css_first(".card__price")))
        title = _text(card.css_first(".card__title"))
        it = {
            "id": f"ap:{aid}",
            "url": BASE + href if href.startswith("/") else href,
            "title": title.capitalize(),
            "tipo": _tipo(title, href),
            "address": _text(card.css_first(".card__address")),
            "price_usd": price if cur == "USD" else None,
            "price_ars": price if cur == "$" else None,
            "expensas": number(_text(card.css_first(".card__expenses"))),
            "description": _text(card.css_first(".card__info"))[:1500],
            "agent": _text(card.css_first(".card__agent-name")),
        }
        img = card.css_first(".card__photos img")
        if img:
            it["photo"] = img.attributes.get("src") or img.attributes.get("data-src")
        for li in card.css(".card__main-features li"):
            icon = li.css_first("i")
            cls = (icon.attributes.get("class") or "") if icon else ""
            for key, field in CARD_ICONS.items():
                if key in cls:
                    it[field] = number(_text(li))
        items.append(it)

    pages = 1
    for span in tree.css(".pagination__page span[data-link-href]"):
        n = number(_text(span))
        if n:
            pages = max(pages, int(n))
    total = number(_text(tree.css_first("h1.listing-header__title")))
    return items, pages, int(total or 0)


def _tipo(title, href):
    t = (title + " " + href).lower()
    if t.startswith("ph") or "ph-en-venta" in t or " ph " in f" {t} ":
        return "PH"
    if "casa" in t:
        return "Casa"
    if "departamento" in t or "monoambiente" in t:
        return "Departamento"
    return "Otro"


def parse_detail(html):
    """Coordinates and the full feature list of a detail page."""
    tree = LexborHTMLParser(html)
    out = {"features": {}}
    m = tree.css_first("[data-latitude]")
    if m:
        try:
            out["lat"] = float(m.attributes["data-latitude"].replace(",", "."))
            out["lng"] = float(m.attributes["data-longitude"].replace(",", "."))
        except (KeyError, ValueError, AttributeError):
            pass
    for li in tree.css('ul[id^="section-"] li'):
        txt = _text(li)
        if not txt:
            continue
        if ":" in txt:
            k, v = txt.split(":", 1)
            out["features"][k.strip()] = v.strip()
        else:
            out["features"][txt] = True
    desc = tree.css_first(".section-description--content") or tree.css_first(".property-description p")
    if desc:
        out["description"] = _text(desc)[:4000]
    f = out["features"]
    for key, field in (("Sup. Cubierta", "m2_cub"), ("Sup. Total", "m2_tot"),
                       ("Cant. Ambientes", "amb"), ("Cant. Dormitorios", "dorm"),
                       ("Cant. Baños", "banos"), ("Antiguedad", "antig"),
                       ("Expensas", "expensas")):
        if key in f and isinstance(f[key], str):
            val = number(f[key])
            if val is not None:
                out[field] = val
    return out
