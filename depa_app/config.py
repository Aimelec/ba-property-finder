"""Rutas y preferencias del usuario (data/ajustes.json)."""
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
DB_PATH = DATA / "propiedades.db"
STATIONS_PATH = DATA / "estaciones.json"
SETTINGS_PATH = DATA / "ajustes.json"

DEFAULTS = {
    # Búsqueda (qué se descarga de Argenprop)
    "tipos": ["departamentos", "casas", "ph"],
    "zonas": [],                 # slugs elegidos; vacío = los predeterminados de zones.py
    "precio_min": 0,
    "precio_max": 200000,
    "sitios": ["ap", "zp", "ml", "tk"],
    "avisos_por_zona": 300,        # resto de las zonas
    "avisos_por_zona_norte": 3000,  # zonas de GBA Norte (cobertura profunda)
    "zona_inicio": "partido-de-san-fernando",  # se busca primero y después las zonas más cercanas
    "detalles_por_corrida": 30,  # fichas de Argenprop por corrida (ubicación exacta + características)

    # Filtros de la lista / mapa
    "filtro": {
        "precio_min": 0, "precio_max": 200000,
        "amb_min": 0, "m2_min": 0,
        "dist_max": 0,           # metros a estación, 0 = sin límite
        "expensas_max": 0,       # ARS, 0 = sin límite
        "tipos": ["Departamento", "Casa", "PH"],
        "grupos": ["CABA", "GBA Norte", "GBA Oeste", "GBA Sur", "Otra"],
        "solo_credito": False, "solo_cochera": False, "solo_favoritos": False,
        "ocultar_descartados": True, "solo_con_ubicacion": False, "ocultar_duplicados": True,
        "sitios": ["ap", "zp", "ml", "tk"],
    },

    # Pesos del puntaje (se normalizan, no hace falta que sumen 100)
    "pesos": {
        "estacion": 40, "precio_m2": 20, "zona": 15,
        "superficie": 10, "expensas": 5, "antiguedad": 5, "extras": 5,
    },
    "estacion_ideal_m": 400,     # a esta distancia o menos: puntaje completo
    "estacion_max_m": 2000,      # a esta distancia o más: cero
    "m2_ideal": 70,
    "prioridad_grupo": {"GBA Norte": 100, "CABA": 60, "GBA Oeste": 40, "GBA Sur": 40, "Otra": 30},
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
