"""Display names of values stored in Spanish in the database and settings (they stay unchanged)."""
from ..i18n import tr

TIPOS = {"Departamento": "Apartment", "Casa": "House", "PH": "PH", "Otro": "Other type"}
GROUPS = {"Otra": "Other zone"}   # CABA, GBA Norte, GBA Oeste, GBA Sur are proper names


def tipo_label(value):
    return tr(TIPOS.get(value, value)) if value else ""


def group_label(value):
    return tr(GROUPS[value]) if value in GROUPS else value
