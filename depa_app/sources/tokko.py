"""Agency websites built with Tokko Broker (classic template).

Each site lists its listings for sale at /Venta (20 per page) and the next pages at
/Venta?o=2,2&p=N until "--NoMoreProperties--". There are no coordinates in the list: listings are
located by address. The agency list is in the settings ("inmobiliarias") and editable in Search.
"""
import re
import unicodedata
from urllib.parse import urlparse

from selectolax.lexbor import LexborHTMLParser


SITE = "tk"
NAME = "Agencies"  # shown through tr(): "Inmobiliarias" in Spanish
PER_PAGE = 20
CLIENT_OPTS = {"pause": (3.0, 5.0), "block_waits": (60, 180, 600)}
MAX_PAGES = 80

DEFAULT_AGENCIES = [
    {"nombre": "Leo Resia", "url": "https://www.leoresia.com", "activa": True},
    {"nombre": "Guallini Peifer", "url": "https://www.guallinipeifer.com", "activa": True},
    {"nombre": "Di Paolo", "url": "https://www.dipaolopropiedades.com", "activa": True},
    {"nombre": "Rollan", "url": "https://www.rollan.com.ar", "activa": True},
    {"nombre": "Ruiz Propiedades", "url": "https://www.ruizpropiedades.com", "activa": True},
    {"nombre": "Basilio", "url": "https://www.basilioinmobiliaria.com", "activa": True},
    {"nombre": "Solimano Dal Pos", "url": "https://www.solimanodalposrealestate.com", "activa": True},
]
TIPOS = {"departamento": ("Departamento", "departamentos"), "casa": ("Casa", "casas"), "ph": ("PH", "ph")}

# locality -> zone key (zones.py). Localities of a partido go to that partido.
_PARTIDOS = {
    "partido-de-san-fernando": ["san fernando", "victoria", "virreyes", "punta chica"],
    "partido-de-tigre": ["tigre", "don torcuato", "pacheco", "el talar", "benavidez", "rincon de milberg",
                         "nordelta", "troncos del talar", "villa la nata", "dique lujan"],
    "partido-de-san-isidro": ["san isidro", "martinez", "beccar", "acassuso", "boulogne", "las lomas"],
    "partido-de-vicente-lopez": ["vicente lopez", "v lopez", "olivos", "florida", "munro", "la lucila",
                                 "villa martelli", "carapachay"],
    "partido-de-escobar": ["escobar", "garin", "maschwitz", "matheu"],
    "partido-de-pilar": ["pilar", "del viso", "manzanares", "derqui"],
    "partido-de-general-san-martin": ["san martin", "villa ballester", "jose leon suarez", "billinghurst"],
    "partido-de-san-miguel": ["san miguel", "bella vista", "muniz"],
    "partido-de-malvinas-argentinas": ["malvinas argentinas", "los polvorines", "grand bourg"],
    "partido-de-jose-c-paz": ["jose c paz"],
}
_CABA = ["nunez", "belgrano", "saavedra", "coghlan", "villa urquiza", "colegiales", "palermo",
         "villa devoto", "villa pueyrredon", "caballito", "almagro", "recoleta"]


def norm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", t).split())


def zone_of(ubicacion):
    """'Virreyes, San Fernando' -> 'partido-de-san-fernando'; 'Almagro, Capital Federal' -> 'almagro'."""
    parts = [norm(p) for p in (ubicacion or "").split(",")]
    whole = " ".join(parts)
    if "capital federal" in whole or "caba" in whole.split():
        for b in _CABA:
            if b in whole:
                return b.replace(" ", "-")
        return None
    for part in reversed(parts):  # the partido usually comes last
        for key, locs in _PARTIDOS.items():
            if any(part == l or part.startswith(l + " ") or f" {l}" in f" {part}" for l in locs):
                return key
    return None


def search_url(base, page):
    return f"{base.rstrip('/')}/Venta" + (f"?o=2,2&p={page}" if page > 1 else "")


def _num(t):
    m = re.search(r"\d+(?:[.,]\d+)?", t or "")
    return float(m.group(0).replace(",", ".")) if m else None


def parse_list(html, base, agency):
    """(listings, more pages). Each listing gets 'zona_slug' from its locality."""
    host = urlparse(base).netloc.replace("www.", "")
    tree = LexborHTMLParser(html)
    items = []
    for li in tree.css("li[prop-id]"):
        a = li.css_first("a")
        tu = " ".join((li.css_first(".prop-desc-tipo-ub").text() if li.css_first(".prop-desc-tipo-ub") else "").split())
        street = " ".join((li.css_first(".prop-desc-dir").text() if li.css_first(".prop-desc-dir") else "").split())
        ptxt = " ".join((li.css_first(".prop-valor-nro").text() if li.css_first(".prop-valor-nro") else "").split())
        kind = next((v for k, v in TIPOS.items() if tu.lower().startswith(k)), None)
        if not kind or " en venta " not in f" {tu.lower()} ":
            continue
        loc = tu.split(" en ")[-1].strip() if " en " in tu else ""
        m = re.search(r"(USD|U\$S|\$)\s*([\d.]+)", ptxt)
        price = float(m.group(2).replace(".", "")) if m else None
        usd = m and m.group(1) in ("USD", "U$S")
        it = {
            "id": f"tk:{host}:{li.attributes.get('prop-id')}",
            "url": base.rstrip("/") + (a.attributes.get("href", "") if a else ""),
            "title": f"{tu} · {street}",
            "tipo": kind[0],
            "tipo_busqueda": kind[1],
            "address": f"{street}, {loc}",
            "loc": loc,
            "zona_slug": zone_of(loc),
            "price_usd": price if usd and price and price > 1000 else None,  # "1" = price on request
            "price_ars": price if m and not usd else None,
            "agent": agency,
        }
        img = li.css_first("img.dest-img")
        if img:
            it["photo"] = img.attributes.get("src")
        for box in li.css(".prop-data, .prop-data2"):
            icon = (box.css_first("img").attributes.get("src", "") if box.css_first("img") else "")
            val = _num(box.text())
            if not val:
                continue
            if "suptotal" in icon or "superficie" in icon:
                it["m2_tot"] = val
            elif "ambientes" in icon:
                it["amb"] = val
            elif "dormitorios" in icon:
                it["dorm"] = val
            elif "banos" in icon:
                it["banos"] = val
        items.append(it)
    return items, bool(tree.css("li[prop-id]"))
