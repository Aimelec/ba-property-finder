"""A download run for ONE site (the window runs one per site, in parallel threads). Qt-free: it reports
through the log/progress callbacks; ui/workers.py runs it on a QThread."""
import math
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from ..domain import geo
from ..domain.zones import site_slug, zone_info
from ..i18n import number, tr
from ..opendata import geocode, stations
from ..repositories import listings_db as db
from ..sources import SOURCES, tokko
from ..sources.client import Blocked, Client, Stopped

_POOL = ThreadPoolExecutor(6)


def zones_by_distance(keys, start):
    """Zones sorted by distance to `start` (zone centre = median of its exact stored positions).
    Zones without data go last, in their original order."""
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


class ScrapeRun:
    """Downloads ONE site (one run per site, in parallel).

    One whole zone at a time, starting with 'zona_inicio' and continuing with the closest zones: up to
    'avisos_por_zona_norte' listings in GBA Norte and 'avisos_por_zona' elsewhere. Every new page is
    located right away (Zonaprop has coordinates; the rest are located by address). At the end,
    sources with detail pages read some of them.
    """
    def __init__(self, site, settings, zonas, browser=None, do_list=True, do_details=True,
                 log=print, progress=lambda site, current, total, label: None, slicer=None):
        """log(text) and progress(site, current, total, label) report to the caller (the window).
        slicer: optional plugin for zones with more pages than the site shows (see plugins.py)."""
        self.on_log = log
        self.on_progress = progress
        self.site = site
        self.src = SOURCES[site]
        self.browser = browser
        self.settings = settings
        self.zonas = zonas
        self.do_list = do_list
        self.do_details = do_details and hasattr(self.src, "parse_detail")
        self._stop = False
        self.sts = stations.load()
        self.slicer = slicer if hasattr(self.src, "MAX_PAGES") else None

    def stop(self):
        self._stop = True

    def _log(self, m):
        self.on_log(f"[{self.src.NAME}] {m}")

    def run(self):
        stats = {"nuevos": 0, "bajas": 0, "vistos": 0, "ubicados": 0, "fichas": 0, "error": ""}
        if getattr(self.src, "NEEDS_BROWSER", False) and self.browser is None:
            stats["error"] = tr("{site} needs a built-in browser to download (optional plugin, not included): "
                                "skipped.", site=self.src.NAME)
            self._log(stats["error"])
            return stats
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
            self._log(tr("Stopped."))
        except Blocked:
            stats["error"] = tr("{site} keeps refusing. Try again in a while.", site=self.src.NAME)
            self._log(stats["error"])
        except Exception as e:  # an unexpected error must not kill the app
            stats["error"] = f"{self.src.NAME}: {type(e).__name__}: {e}"
            self._log(tr("Error: ") + stats["error"])
        finally:
            con.commit()
            con.close()
        return stats

    # --- result lists ---
    def _lists(self, client, con, stats):
        if self.site == "tk":
            return self._agencies(client, con, stats)
        s = self.settings
        per = self.src.PER_PAGE
        zones = [(k, site_slug(k, self.site)) for k in self.zonas]
        zones = [z for z in zones if z[1]]
        # one whole zone at a time, starting with 'zona_inicio' and then the closest ones
        order = zones_by_distance([k for k, _ in zones], s.get("zona_inicio", "partido-de-san-fernando"))
        zones.sort(key=lambda z: order.index(z[0]))
        self._log(tr("Zone order: ") + ", ".join(zone_info(k)[0] for k, _ in zones))
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
            maxp = getattr(self.src, "MAX_PAGES", limit)  # Zonaprop shows at most 9 pages
            while not z["done"] and z["next"] <= min(limit, z["pages"] or limit, maxp):
                self.on_progress(self.site, done, max(planned, 1), tr("{zone} · page {page}", zone=name, page=z["next"]))
                url = self.src.search_url(s["tipos"], slug, s["precio_min"], s["precio_max"], z["next"])
                html = client.get(url)
                if html is None:
                    self._log(tr("{zone}: the zone does not exist on {site} ({slug}).", zone=name, site=self.src.NAME, slug=slug))
                    z["done"] = True
                    break
                if self.site == "ml":
                    items, pages, total = self.src.parse_list(html, s["tipos"])
                else:
                    items, pages, total = self.src.parse_list(html)
                if z["next"] == 1 and total == 0 and self.site == "ml" and not z.get("retried"):
                    # MercadoLibre sometimes slows down by answering "no results": wait and retry
                    z["retried"] = True
                    self._log(tr("{zone}: 0 results (the site may be slowing down); retrying in 2 min.", zone=name))
                    client.sleep(120)
                    continue
                if z["next"] == 1:
                    if not self._zone_ok(items, name, slug):
                        z["done"] = True
                        break
                    self._log(tr("{zone}: {n} listings on the site.", zone=name, n=total))
                z["pages"] = pages
                self._save(con, items, key, name, group, stats)
                con.commit()
                z["next"] += 1
                done += 1
                if not pages or z["next"] > pages:
                    z["done"] = True
                elif pages > maxp and limit > maxp and self.slicer:
                    break  # doesn't fit in the pages the site shows: the plugin reads it
            if not z["done"] and (z["pages"] or 0) > maxp and limit > maxp and self.slicer:
                done = self.slicer(self, client, con, stats, key, slug, limit, done, planned)
                z["done"] = True
        self._log(tr("Result lists finished: {seen} listings, {new} new.", seen=stats["vistos"], new=stats["nuevos"]))

    def _agencies(self, client, con, stats):
        """Agency websites (Tokko): each site is read entirely; listings in the chosen zones, price
        range and property types are saved."""
        s = self.settings
        agencies = [a for a in s.get("inmobiliarias", tokko.DEFAULT_AGENCIES) if a.get("activa", True)]
        zonas = set(self.zonas)
        for ai, ag in enumerate(agencies):
            page = 0
            before = stats["vistos"]
            more = True
            while more and page < tokko.MAX_PAGES:
                page += 1
                self.on_progress(self.site, ai, len(agencies), tr("{zone} · page {page}", zone=ag["nombre"], page=page))
                html = client.get(tokko.search_url(ag["url"], page))
                if html is None:
                    self._log(tr("{agency}: the website doesn't have the expected template ({url}/Venta).",
                                 agency=ag["nombre"], url=ag["url"]))
                    break
                items, more = tokko.parse_list(html, ag["url"], ag["nombre"])
                if page > 1 and "--NoMoreProperties--" in html:  # page 1 contains that text in its JavaScript
                    more = False
                by_zone = {}
                for it in items:
                    if it["zona_slug"] in zonas and it["tipo_busqueda"] in s["tipos"]:
                        by_zone.setdefault(it["zona_slug"], []).append(it)
                for key, its in by_zone.items():
                    name, group = zone_info(key)
                    self._save(con, its, key, name, group, stats)
                con.commit()
            self._log(tr("{agency}: {pages} pages, {n} listings in your zones and price range.", agency=ag["nombre"],
                         pages=page, n=stats["vistos"] - before))
        self._log(tr("Agencies finished: {seen} listings, {new} new.", seen=stats["vistos"], new=stats["nuevos"]))

    def _zone_ok(self, items, name, slug):
        """When a site doesn't know a zone it sometimes returns another search: detect that."""
        if self.site == "ap" or slug == "capital-federal" or not items:
            return True
        want = _norm(name)
        hits = sum(1 for it in items if want in _norm(it.get("loc")))
        if hits / len(items) < 0.3:
            self._log(tr("{zone}: the results are not from that zone ({slug}); skipping it.", zone=name, slug=slug))
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
                self._log(tr("Price dropped: {address} → USD {price}", address=it["address"], price=number(p)))
            if it.get("lat") is not None:
                station, dist = geo.nearest(self.sts, it["lat"], it["lng"])
                db.save_list_position(con, it["id"], it["lat"], it["lng"], station, dist)
            elif st == "nuevo":
                to_locate.append(it)
        con.commit()  # don't keep the database locked while locating (other sources write)
        # locate this page's new listings by address, 6 at a time (Georef, not the site)
        positions = list(_POOL.map(lambda it: geocode.geocode(it["address"], name, group), to_locate))
        for it, pos in zip(to_locate, positions):
            st = dist = None
            if pos:
                st, dist = geo.nearest(self.sts, *pos)
                stats["ubicados"] += 1
            db.save_geocode(con, it["id"], pos, st, dist)
        if self._stop:
            raise Stopped()

    # --- locating ---
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
        self._log(tr("Locating {n} listings by their address…", n=len(pend)))
        for i, row in enumerate(pend):
            if self._stop:
                raise Stopped()
            self.on_progress(self.site, i, len(pend), tr("Locating {i} of {n}", i=i + 1, n=len(pend)))
            self._geocode_one(con, row["id"], row["address"], row["zona"], row["grupo"], stats)
            # commit after every listing: otherwise the write lock stays taken while the next ones are
            # located (minutes) and the other sources and the window freeze
            con.commit()

    # --- detail pages ---
    def _details(self, client, con, stats):
        pend = db.pending_details(con, self.settings["detalles_por_corrida"], self.site)
        if not pend:
            return
        self._log(tr("Reading {n} detail pages (exact location and features)…", n=len(pend)))
        for i, row in enumerate(pend):
            self.on_progress(self.site, i, len(pend), tr("Detail page {i} of {n}", i=i + 1, n=len(pend)))
            html = client.get(row["url"])
            if html is None:  # listing was removed
                con.execute("UPDATE listings SET detail_at=? WHERE id=?", (db.now(), row["id"]))
                con.commit()  # don't hold the lock during the next page
                continue
            d = self.src.parse_detail(html)
            st = dist = None
            if d.get("lat") is not None:
                st, dist = geo.nearest(self.sts, d["lat"], d["lng"])
            db.save_detail(con, row["id"], d, st, dist)
            con.commit()
            stats["fichas"] += 1
