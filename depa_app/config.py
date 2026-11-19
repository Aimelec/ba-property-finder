"""Paths and the user's preferences (data/ajustes.json).

DEPA_DATA_DIR points the whole app at another data folder (e.g. the demo data from scripts/demo_data.py).
"""
import json
import os
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DEPA_DATA_DIR") or ROOT / "data").resolve()
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / "propiedades.db"
STATIONS_PATH = DATA / "estaciones.json"
SETTINGS_PATH = DATA / "ajustes.json"

DEFAULTS = {
    # Search (what is downloaded). Keys are stored in Spanish in ajustes.json and stay that way.
    "tipos": ["departamentos", "casas", "ph"],
    "zonas": [],                 # chosen zone keys; empty = zones.DEFAULT_SELECTED
    "precio_min": 0,
    "precio_max": 200000,
    "sitios": ["ap", "zp", "ml", "tk"],
    "avisos_por_zona": 300,        # listings per zone outside GBA Norte
    "avisos_por_zona_norte": 3000,  # listings per GBA Norte zone (in depth)
    "zona_inicio": "partido-de-san-fernando",  # searched first, then the closest zones
    "detalles_por_corrida": 30,  # detail pages read per run (exact location + features)

    # Filters of the list / map
    "filtro": {
        "precio_min": 0, "precio_max": 200000,
        "amb_min": 0, "m2_min": 0,
        "dist_max": 0,           # meters to a station, 0 = no limit
        "expensas_max": 0,       # ARS, 0 = no limit
        "tipos": ["Departamento", "Casa", "PH"],
        "grupos": ["CABA", "GBA Norte", "GBA Oeste", "GBA Sur", "Otra"],
        "solo_credito": False, "solo_cochera": False, "solo_favoritos": False,
        "ocultar_descartados": True, "solo_con_ubicacion": False, "ocultar_duplicados": True,
        "sitios": ["ap", "zp", "ml", "tk"],
    },

    # Score weights (normalized: they don't need to add up to 100)
    "pesos": {
        "estacion": 40, "precio_m2": 20, "zona": 15,
        "superficie": 10, "expensas": 5, "antiguedad": 5, "extras": 5,
    },
    "estacion_ideal_m": 400,     # at this distance or less: full score
    "estacion_max_m": 2000,      # at this distance or more: zero
    "m2_ideal": 70,
    "prioridad_grupo": {"GBA Norte": 100, "CABA": 60, "GBA Oeste": 40, "GBA Sur": 40, "Otra": 30},
    "idioma": "en",              # interface language: en / es (Preferences)
}


def _merge(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load_settings():
    s = deepcopy(DEFAULTS)
    if SETTINGS_PATH.exists():
        try:
            _merge(s, json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return s


def save_settings(s):
    SETTINGS_PATH.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
