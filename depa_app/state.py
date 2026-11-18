"""Estado compartido de la app: ajustes + avisos con puntaje."""
from PySide6.QtCore import QObject, QThread, Signal

import math
from concurrent.futures import ThreadPoolExecutor
import unicodedata

from . import plugins
from .opendata import geocode, stations, subte
from .repositories import listings_db as db
from .domain import filters, geo, scoring
from .sources import SITE_NAMES, SOURCES, tokko  # noqa: F401  (SITE_NAMES is re-exported for the UI)
from .sources.client import Blocked, Client, Stopped
from .domain.zones import site_slug, zone_info

_POOL = ThreadPoolExecutor(6)


class AppState(QObject):
    data_changed = Signal()      # se recargaron/re-puntuaron los avisos
    filters_changed = Signal()   # cambió algún filtro
    select_request = Signal(str)  # mostrar un aviso (id) en Propiedades
    map_focus_request = Signal(str)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.rows = []
        self.by_id = {}
        self.text = ""           # búsqueda libre (no se guarda)
        self.stations = stations.load()
        self.station_pos = {(s["name"], s["line"]): s for s in self.stations}
        self.subte = subte.load()
        if "tk" not in settings["filtro"].get("sitios", []) and not settings.get("_tk_visible"):
            settings["filtro"].setdefault("sitios", []).append("tk")  # fuente nueva: que se vea
            settings["_tk_visible"] = True

    def db_mtime(self):
        try:
            return db.DB_PATH.stat().st_mtime
        except OSError:
            return 0

    def reload(self):
        self.loaded_mtime = self.db_mtime()
        con = db.connect()
        rows = db.all_listings(con)
        changed = False
        for r in rows:  # avisos con coordenadas sin estación, o con una que ya no cuenta (ramal lento)
            if r["lat"] is not None and (r["station_m"] is None
                                         or (r["station"], r["station_line"]) not in self.station_pos):
                st, d = geo.nearest(self.stations, r["lat"], r["lng"])
                con.execute("UPDATE listings SET station=?, station_line=?, station_m=? WHERE id=?",
                            (st["name"], st["line"], round(d), r["id"]))
                r.update(station=st["name"], station_line=st["line"], station_m=round(d))
                changed = True
        if changed:
            con.commit()
        con.close()
        self.rows = rows
        self.rescore()

    def rescore(self):
        sub = self.subte.get("stations", [])
        for r in self.rows:
            if r["lat"] is not None and sub and "subte_m" not in r:
                st, d = geo.nearest(sub, r["lat"], r["lng"])
                r["subte"], r["subte_line"], r["subte_m"] = st["name"], st["line"], round(d)
        scoring.score_all(self.rows, self.settings)
        self.rows.sort(key=lambda r: -r["score"])
        self.by_id = {r["id"]: r for r in self.rows}
        self.data_changed.emit()

    def filtered(self):
        f = self.settings["filtro"]
        t = self.text.lower().strip()
        out = []
        for r in self.rows:
            if not filters.passes(r, f):
                continue
            if t and t not in " ".join(str(r.get(k) or "") for k in
                                       ("title", "address", "zona", "station", "agent")).lower():
                continue
            out.append(r)
        return out

    def set_flag(self, lid, field, value):
        con = db.connect()
        db.set_flag(con, lid, field, value)
        con.close()
        if lid in self.by_id:
            self.by_id[lid][field] = value

    def station_of(self, r):
        return self.station_pos.get((r.get("station"), r.get("station_line")))


def zones_by_distance(keys, start):
    """Zonas ordenadas por distancia a `start` (centro = mediana de las ubicaciones exactas
    guardadas de cada zona). Las zonas sin datos van al final, en su orden original."""
    con = db.connect()
    pts = {}
    for k, lat, lng in con.execute("SELECT zona_slug, lat, lng FROM listings "
                                   "WHERE lat IS NOT NULL AND geo_src IN ('lista', 'ficha')"):
        pts.setdefault(k, []).append((lat, lng))
    con.close()

    def median(v):
        v = sorted(v)
        return v[len(v) // 2]
    center = {k: (median([p[0] for p in v]), median([p[1] for p in v])) for k, v in pts.items() if len(v) >= 5}
    if start not in center:
        return sorted(keys, key=lambda k: k != start)
    c0 = center[start]
    return sorted(keys, key=lambda k: (k not in center, geo.haversine(*c0, *center[k]) if k in center else 0,
                                       keys.index(k)))


def _norm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return " ".join(t.replace(".", " ").split())


class ScrapeWorker(QThread):
    """Descarga de UN sitio en segundo plano (se corre uno por sitio, en paralelo).

    Una zona entera por vez, empezando por 'zona_inicio' (San Fernando) y siguiendo por las
    más cercanas: hasta 'avisos_por_zona_norte' en GBA Norte y 'avisos_por_zona' en el resto.
    Cada página nueva se ubica enseguida (Zonaprop trae coordenadas; el resto
    se ubica por dirección). Al final, Argenprop lee algunas fichas.
    """
    log = Signal(str)
    progress = Signal(str, int, int, str)   # sitio, actual, total, etiqueta
    finished_ok = Signal(str, dict)

    def __init__(self, site, settings, zonas, browser=None, do_list=True, do_details=True):
        super().__init__()
        self.site = site
        self.src = SOURCES[site]
        self.browser = browser
        self.settings = settings
        self.zonas = zonas
        self.do_list = do_list
        self.do_details = do_details and hasattr(self.src, "parse_detail")
        self._stop = False
        self.sts = stations.load()
        # optional plugin: reads zones with more result pages than the site shows (see plugins.py)
        self.slicer = plugins.zone_slicer() if hasattr(self.src, "MAX_PAGES") else None

    def stop(self):
        self._stop = True

    def _log(self, m):
        self.log.emit(f"[{self.src.NAME}] {m}")

    def run(self):
        stats = {"nuevos": 0, "bajas": 0, "vistos": 0, "ubicados": 0, "fichas": 0, "error": ""}
        if getattr(self.src, "NEEDS_BROWSER", False) and self.browser is None:
            stats["error"] = (f"{self.src.NAME} necesita un navegador integrado para descargar "
                              "(plugin opcional, no incluido): se saltea.")
            self._log(stats["error"])
            self.finished_ok.emit(self.site, stats)
            return
        client = Client(log=self._log, should_stop=lambda: self._stop,
                        browser=self.browser if self.site == "ap" else None, **self.src.CLIENT_OPTS)
        con = db.connect()
        try:
            if self.do_list:
                self._lists(client, con, stats)
            self._geocode_pending(con, stats)
            if self.do_details:
                self._details(client, con, stats)
        except Stopped:
            self._log("Detenido.")
        except Blocked:
            stats["error"] = f"{self.src.NAME} sigue bloqueando. Probá de nuevo en un rato."
            self._log(stats["error"])
        except Exception as e:  # que un error raro no mate la app
            stats["error"] = f"{self.src.NAME}: {type(e).__name__}: {e}"
            self._log("Error: " + stats["error"])
        finally:
            con.commit()
            con.close()
        self.finished_ok.emit(self.site, stats)

    # --- listados ---
    def _lists(self, client, con, stats):
        if self.site == "tk":
            return self._agencies(client, con, stats)
        s = self.settings
        per = self.src.PER_PAGE
        zones = [(k, site_slug(k, self.site)) for k in self.zonas]
        zones = [z for z in zones if z[1]]
        # una zona entera por vez, empezando por 'zona_inicio' y siguiendo por las más cercanas
        order = zones_by_distance([k for k, _ in zones], s.get("zona_inicio", "partido-de-san-fernando"))
        zones.sort(key=lambda z: order.index(z[0]))
        self._log("Orden de zonas: " + ", ".join(zone_info(k)[0] for k, _ in zones))
        state = {k: {"next": 1, "pages": None, "done": False} for k, _ in zones}
        first = math.ceil(s["avisos_por_zona"] / per)
        deep = max(first, math.ceil(s["avisos_por_zona_norte"] / per))
        planned = first * len(zones) + (deep - first) * sum(
            1 for k, _ in zones if zone_info(k)[1] == "GBA Norte")
        done = 0
        for key, slug in zones:
            name, group = zone_info(key)
            limit = deep if group == "GBA Norte" else first
            z = state[key]
            maxp = getattr(self.src, "MAX_PAGES", limit)  # Zonaprop: no muestra más de 9 páginas
            while not z["done"] and z["next"] <= min(limit, z["pages"] or limit, maxp):
                self.progress.emit(self.site, done, max(planned, 1), f"{name} · página {z['next']}")
                url = self.src.search_url(s["tipos"], slug, s["precio_min"], s["precio_max"], z["next"])
                html = client.get(url)
                if html is None:
                    self._log(f"{name}: la zona no existe en {self.src.NAME} ({slug}).")
                    z["done"] = True
                    break
                if self.site == "ml":
                    items, pages, total = self.src.parse_list(html, s["tipos"])
                else:
                    items, pages, total = self.src.parse_list(html)
                if z["next"] == 1 and total == 0 and self.site == "ml" and not z.get("retried"):
                    # MercadoLibre a veces frena devolviendo "sin resultados": esperar y reintentar
                    z["retried"] = True
                    self._log(f"{name}: 0 resultados (posible freno del sitio); reintento en 2 min.")
                    client.sleep(120)
                    continue
                if z["next"] == 1:
                    if not self._zone_ok(items, name, slug):
                        z["done"] = True
                        break
                    self._log(f"{name}: {total} avisos en el sitio.")
                z["pages"] = pages
                self._save(con, items, key, name, group, stats)
                con.commit()
                z["next"] += 1
                done += 1
                if not pages or z["next"] > pages:
                    z["done"] = True
                elif pages > maxp and limit > maxp and self.slicer:
                    break  # no entra en las páginas que muestra el sitio: lo lee el plugin
            if not z["done"] and (z["pages"] or 0) > maxp and limit > maxp and self.slicer:
                done = self.slicer(self, client, con, stats, key, slug, limit, done, planned)
                z["done"] = True
        self._log(f"Listados terminados: {stats['vistos']} avisos, {stats['nuevos']} nuevos.")

    def _agencies(self, client, con, stats):
        """Webs de inmobiliarias (Tokko): se recorre cada web entera y se guarda lo que cae
        en las zonas elegidas, dentro del precio y de los tipos buscados."""
        s = self.settings
        agencies = [a for a in s.get("inmobiliarias", tokko.DEFAULT_AGENCIES) if a.get("activa", True)]
        zonas = set(self.zonas)
        for ai, ag in enumerate(agencies):
            page = 0
            before = stats["vistos"]
            more = True
            while more and page < tokko.MAX_PAGES:
                page += 1
                self.progress.emit(self.site, ai, len(agencies), f"{ag['nombre']} · página {page}")
                html = client.get(tokko.search_url(ag["url"], page))
                if html is None:
                    self._log(f"{ag['nombre']}: la web no tiene la plantilla esperada ({ag['url']}/Venta).")
                    break
                items, more = tokko.parse_list(html, ag["url"], ag["nombre"])
                if page > 1 and "--NoMoreProperties--" in html:  # la página 1 trae ese texto en su JS
                    more = False
                by_zone = {}
                for it in items:
                    if it["zona_slug"] in zonas and it["tipo_busqueda"] in s["tipos"]:
                        by_zone.setdefault(it["zona_slug"], []).append(it)
                for key, its in by_zone.items():
                    name, group = zone_info(key)
                    self._save(con, its, key, name, group, stats)
                con.commit()
            self._log(f"{ag['nombre']}: {page} páginas, {stats['vistos'] - before} avisos en tus zonas y precio.")
        self._log(f"Inmobiliarias terminadas: {stats['vistos']} avisos, {stats['nuevos']} nuevos.")

    def _zone_ok(self, items, name, slug):
        """Si el sitio no reconoce la zona a veces devuelve otra búsqueda: lo detecto."""
        if self.site == "ap" or slug == "capital-federal" or not items:
            return True
        want = _norm(name)
        hits = sum(1 for it in items if want in _norm(it.get("loc")))
        if hits / len(items) < 0.3:
            self._log(f"{name}: los resultados no son de esa zona ({slug}); la salteo.")
            return False
        return True

    def _save(self, con, items, key, name, group, stats):
        s = self.settings
        to_locate = []
        for it in items:
            p = it.get("price_usd")
            if p and ((s["precio_min"] and p < s["precio_min"]) or (s["precio_max"] and p > s["precio_max"])):
                continue
            it.update(zona_slug=key, zona=name, grupo=group)
            st = db.upsert_list_item(con, it)
            stats["vistos"] += 1
            if st == "nuevo":
                stats["nuevos"] += 1
            elif st == "baja":
                stats["bajas"] += 1
                self._log(f"Bajó de precio: {it['address']} → USD {p:,.0f}")
            if it.get("lat") is not None:
                station, dist = geo.nearest(self.sts, it["lat"], it["lng"])
                db.save_list_position(con, it["id"], it["lat"], it["lng"], station, dist)
            elif st == "nuevo":
                to_locate.append(it)
        con.commit()  # no tener la base bloqueada mientras se ubica (los otros sitios escriben)
        # ubicar por dirección los nuevos de esta página, 6 a la vez (Georef, no el sitio)
        positions = list(_POOL.map(lambda it: geocode.geocode(it["address"], name, group), to_locate))
        for it, pos in zip(to_locate, positions):
            st = dist = None
            if pos:
                st, dist = geo.nearest(self.sts, *pos)
                stats["ubicados"] += 1
            db.save_geocode(con, it["id"], pos, st, dist)
        if self._stop:
            raise Stopped()

    # --- ubicación ---
    def _geocode_one(self, con, lid, address, zona, grupo, stats):
        pos = geocode.geocode(address, zona, grupo)
        st = dist = None
        if pos:
            st, dist = geo.nearest(self.sts, *pos)
            stats["ubicados"] += 1
        db.save_geocode(con, lid, pos, st, dist)

    def _geocode_pending(self, con, stats):
        pend = db.pending_geocode(con, self.site)
        if not pend:
            return
        self._log(f"Ubicando {len(pend)} avisos por su dirección…")
        for i, row in enumerate(pend):
            if self._stop:
                raise Stopped()
            self.progress.emit(self.site, i, len(pend), f"Ubicando {i + 1} de {len(pend)}")
            self._geocode_one(con, row["id"], row["address"], row["zona"], row["grupo"], stats)
            # confirmar en cada aviso: si no, el bloqueo de escritura queda tomado mientras se
            # ubican los siguientes (minutos) y los otros sitios y la ventana se traban
            con.commit()

    # --- fichas (solo Argenprop) ---
    def _details(self, client, con, stats):
        pend = db.pending_details(con, self.settings["detalles_por_corrida"], self.site)
        if not pend:
            return
        self._log(f"Leyendo {len(pend)} fichas (ubicación exacta y características)…")
        for i, row in enumerate(pend):
            self.progress.emit(self.site, i, len(pend), f"Ficha {i + 1} de {len(pend)}")
            html = client.get(row["url"])
            if html is None:  # aviso dado de baja
                con.execute("UPDATE listings SET detail_at=? WHERE id=?", (db.now(), row["id"]))
                con.commit()  # no retener el bloqueo durante la próxima ficha
                continue
            d = self.src.parse_detail(html)
            st = dist = None
            if d.get("lat") is not None:
                st, dist = geo.nearest(self.sts, d["lat"], d["lng"])
            db.save_detail(con, row["id"], d, st, dist)
            con.commit()
            stats["fichas"] += 1
