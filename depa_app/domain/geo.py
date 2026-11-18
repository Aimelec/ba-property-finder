"""Distances on the map. Pure functions, no I/O."""
import math

EARTH_RADIUS_M = 6371000.0


def haversine(lat1, lng1, lat2, lng2):
    """Straight-line distance in meters between two points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def nearest(points, lat, lng):
    """(closest point, meters in a straight line). Points are dicts with 'lat' and 'lng'."""
    best, best_d = None, float("inf")
    for p in points:
        d = haversine(lat, lng, p["lat"], p["lng"])
        if d < best_d:
            best, best_d = p, d
    return best, best_d


def walk_minutes(meters):
    """Estimate: streets make the straight line ~30 % longer; walking at 80 m/min."""
    return round(meters * 1.3 / 80)


# Greater Buenos Aires (AMBA) with a margin. Positions outside it are wrong pins or wrong geocoding
# matches (e.g. a listing placed in Venezuela) and count as "not located".
AREA_LAT = (-35.2, -34.2)
AREA_LNG = (-59.3, -57.9)


def in_area(lat, lng):
    return AREA_LAT[0] <= lat <= AREA_LAT[1] and AREA_LNG[0] <= lng <= AREA_LNG[1]


def clear_outside_area(rows):
    """Forget (in memory) positions outside the area: the listing shows as not located."""
    for r in rows:
        if r.get("lat") is not None and not in_area(r["lat"], r["lng"]):
            r.update(lat=None, lng=None, station=None, station_line=None, station_m=None)
    return rows
