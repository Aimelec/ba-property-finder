"""Search zones and how each site names them.

key (= the Argenprop slug, stored in the database) -> name, Zonaprop slug, MercadoLibre path.
Argenprop-only zones can be added from the Search page (by pasting a URL).
"""


def _gba(region, items):
    return [(f"partido-de-{s}" if not s.startswith("partido-de-") else s, name, zp or s,
             f"bsas-gba-{region}/{ml or zp or s}")
            for s, name, zp, ml in items]


def _caba(items):
    return [(s, name, s, f"capital-federal/{s}") for s, name in items]


ZONES = {
    "GBA Norte": _gba("norte", [
        ("san-fernando", "San Fernando", None, None),
        ("tigre", "Tigre", None, None),
        ("san-isidro", "San Isidro", None, None),
        ("vicente-lopez", "Vicente López", None, None),
        ("escobar", "Escobar", None, None),
        ("pilar", "Pilar", None, None),
        ("general-san-martin", "San Martín", "general-san-martin", None),
        ("san-miguel", "San Miguel", None, None),
        ("malvinas-argentinas", "Malvinas Argentinas", None, None),
        ("jose-c-paz", "José C. Paz", None, None),
    ]),
    "CABA": _caba([
        ("nunez", "Núñez"), ("belgrano", "Belgrano"), ("saavedra", "Saavedra"),
        ("coghlan", "Coghlan"), ("villa-urquiza", "Villa Urquiza"), ("colegiales", "Colegiales"),
        ("palermo", "Palermo"), ("villa-devoto", "Villa Devoto"),
        ("villa-pueyrredon", "Villa Pueyrredón"), ("caballito", "Caballito"),
        ("almagro", "Almagro"), ("recoleta", "Recoleta"),
    ]) + [("capital-federal", "CABA (toda)", "capital-federal", "capital-federal")],
    "GBA Oeste": _gba("oeste", [
        ("tres-de-febrero", "Tres de Febrero", None, None),
        ("hurlingham", "Hurlingham", None, None),
        ("moron", "Morón", None, None),
        ("ituzaingo", "Ituzaingó", None, None),
        ("la-matanza", "La Matanza", None, None),
        ("merlo", "Merlo", None, None),
        ("moreno", "Moreno", None, None),
    ]),
    "GBA Sur": _gba("sur", [
        ("avellaneda", "Avellaneda", None, None),
        ("lanus", "Lanús", None, None),
        ("lomas-de-zamora", "Lomas de Zamora", None, None),
        ("quilmes", "Quilmes", None, None),
        ("almirante-brown", "Almirante Brown", None, None),
        ("berazategui", "Berazategui", None, None),
    ]),
}

DEFAULT_SELECTED = [z[0] for z in ZONES["GBA Norte"][:5]]
GROUPS = list(ZONES) + ["Otra"]
_BY_KEY = {z[0]: (z, g) for g, items in ZONES.items() for z in items}


def zone_info(key):
    """(name, group); zones added by hand go to 'Otra' (other)."""
    if key in _BY_KEY:
        z, g = _BY_KEY[key]
        return z[1], g
    return key.replace("partido-de-", "").replace("-", " ").title(), "Otra"


def site_slug(key, site):
    """Slug of the zone on a site ('ap', 'zp', 'ml'); None when the site does not have it."""
    if site == "ap":
        return key
    if key not in _BY_KEY:
        return None
    z, _ = _BY_KEY[key]
    return z[2] if site == "zp" else z[3]
