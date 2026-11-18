"""Página Buscar: qué sitios y zonas descargar, y el progreso (un hilo por sitio)."""
import re
from datetime import datetime

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, CheckBox, FluentIcon as FIF, InfoBar,
                            InfoBarPosition, LineEdit, PlainTextEdit, PrimaryPushButton,
                            ProgressBar, PushButton, SimpleCardWidget, SmoothScrollArea, SpinBox,
                            StrongBodyLabel, TitleLabel)

from ..config import DATA, save_settings
from .. import plugins
from ..sources import tokko
from ..state import SITE_NAMES, SOURCES, ScrapeWorker
from ..zones import DEFAULT_SELECTED, ZONES, zone_info
from .common import dim_label

LOG_DIR = DATA / "logs"
TIPOS = [("departamentos", "Departamentos"), ("casas", "Casas"), ("ph", "PH")]
SITE_NOTES = {
    "ap": "20 avisos/página · una cada ~16 s · necesita el navegador integrado (plugin opcional)",
    "zp": "30 avisos/página con ubicación exacta · una cada ~7 s",
    "ml": "48 avisos/página · una cada ~8 s · se ubica por dirección",
    "tk": "webs propias de inmobiliarias (Tokko) · sin límites · avisos que a veces no están en los portales",
}
# segundos promedio por página (incluye pausas de lote y ubicar por dirección)
SECS_PER_PAGE = {"ap": 23, "zp": 29, "ml": 20, "tk": 6}


class SearchPage(SmoothScrollArea):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.setObjectName("buscar")
        self.state = state
        self.workers = {}
        self.totals = {}
        self._pages = 0
        self.browser = plugins.browser_fetcher(self)  # None without the optional plugin
        s = state.settings
        if not s["zonas"]:
            s["zonas"] = list(DEFAULT_SELECTED)
        s.setdefault("zonas_extra", [])
        s.setdefault("inmobiliarias", [dict(a) for a in tokko.DEFAULT_AGENCIES])
        if "tk" not in s["sitios"] and not s.get("_tk_sitio"):  # fuente nueva: activarla una vez
            s["sitios"].append("tk")
            s["_tk_sitio"] = True

        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea{background:transparent;border:none}")
        body = QWidget()
        body.setStyleSheet("background:transparent")
        root = QVBoxLayout(body)
        root.setContentsMargins(24, 16, 24, 24)
        root.setSpacing(12)
        root.addWidget(TitleLabel("Buscar", body))
        root.addWidget(dim_label(
            "Descarga avisos de los sitios y zonas marcados, todos los sitios a la vez, cada uno a "
            "su ritmo seguro. Empieza por San Fernando y sigue zona por zona, de la más cercana a la "
            "más lejana (a fondo en GBA Norte), así que podés detenerlo cuando quieras: lo leído ya queda guardado y "
            "aparece en el mapa. Cada aviso se ubica enseguida (Zonaprop trae la ubicación exacta; "
            "los demás se ubican por dirección con Georef, del Estado).", body))

        # --- sitios ---
        sites_card = SimpleCardWidget(body)
        sl = QGridLayout(sites_card)
        sl.setContentsMargins(18, 14, 18, 14)
        sl.addWidget(StrongBodyLabel("Sitios", sites_card), 0, 0)
        self.site_boxes, self.site_bars, self.site_status = {}, {}, {}
        for i, key in enumerate(("zp", "ml", "ap", "tk"), start=1):
            cb = CheckBox(SITE_NAMES[key], sites_card)
            cb.setChecked(key in s["sitios"])
            cb.stateChanged.connect(self._save)
            note = CaptionLabel(SITE_NOTES[key], sites_card)
            bar = ProgressBar(sites_card)
            bar.setRange(0, 100)
            bar.setValue(0)
            status = CaptionLabel("", sites_card)
            sl.addWidget(cb, i, 0)
            sl.addWidget(note, i, 1)
            sl.addWidget(bar, i, 2)
            sl.addWidget(status, i, 3)
            self.site_boxes[key], self.site_bars[key], self.site_status[key] = cb, bar, status
        sl.setColumnStretch(2, 1)
        sl.setColumnMinimumWidth(3, 230)
        root.addWidget(sites_card)

        # --- inmobiliarias (webs Tokko) ---
        ag_card = SimpleCardWidget(body)
        al = QVBoxLayout(ag_card)
        al.setContentsMargins(18, 14, 18, 14)
        al.addWidget(StrongBodyLabel("Inmobiliarias (webs propias con Tokko Broker)", ag_card))
        al.addWidget(dim_label("Se lee la web entera de cada una y se guardan los avisos de tus zonas. "
                               "Para sumar otra, pegá su dirección (tiene que tener la página /Venta de Tokko).",
                               ag_card))
        self.ag_grid = QGridLayout()
        al.addLayout(self.ag_grid)
        self.ag_boxes = []
        for ag in s["inmobiliarias"]:
            self._agency_box(ag)
        ag_row = QHBoxLayout()
        self.ag_edit = LineEdit(ag_card)
        self.ag_edit.setPlaceholderText("ej. https://www.leoresia.com")
        ag_btn = PushButton(FIF.ADD, "Agregar inmobiliaria", ag_card)
        ag_btn.clicked.connect(self._add_agency)
        self.ag_edit.returnPressed.connect(self._add_agency)
        ag_row.addWidget(self.ag_edit, 1)
        ag_row.addWidget(ag_btn)
        al.addLayout(ag_row)
        root.addWidget(ag_card)

        # --- zonas ---
        self.zone_boxes = {}
        zones_card = SimpleCardWidget(body)
        zl = QVBoxLayout(zones_card)
        zl.setContentsMargins(18, 14, 18, 14)
        for group, items in ZONES.items():
            head = QHBoxLayout()
            head.addWidget(StrongBodyLabel(group, zones_card))
            all_btn = PushButton("Todas", zones_card)
            none_btn = PushButton("Ninguna", zones_card)
            all_btn.setFixedHeight(26)
            none_btn.setFixedHeight(26)
            keys = [z[0] for z in items]
            all_btn.clicked.connect(lambda _=False, k=keys: self._set_zones(k, True))
            none_btn.clicked.connect(lambda _=False, k=keys: self._set_zones(k, False))
            head.addWidget(all_btn)
            head.addWidget(none_btn)
            head.addStretch(1)
            zl.addLayout(head)
            grid = QGridLayout()
            for i, z in enumerate(items):
                cb = CheckBox(z[1], zones_card)
                cb.setChecked(z[0] in s["zonas"])
                cb.stateChanged.connect(self._save)
                grid.addWidget(cb, i // 5, i % 5)
                self.zone_boxes[z[0]] = cb
            zl.addLayout(grid)
            zl.addSpacing(6)
        zl.addWidget(StrongBodyLabel("Otras zonas, solo Argenprop (pegá una URL de Argenprop o el nombre)", zones_card))
        self.extra_grid = QGridLayout()
        zl.addLayout(self.extra_grid)
        add_row = QHBoxLayout()
        self.extra_edit = LineEdit(zones_card)
        self.extra_edit.setPlaceholderText("ej. https://www.argenprop.com/departamentos/venta/victoria  o  victoria")
        add_btn = PushButton(FIF.ADD, "Agregar", zones_card)
        add_btn.clicked.connect(self._add_extra)
        self.extra_edit.returnPressed.connect(self._add_extra)
        add_row.addWidget(self.extra_edit, 1)
        add_row.addWidget(add_btn)
        zl.addLayout(add_row)
        for slug in s["zonas_extra"]:
            self._extra_box(slug)
        root.addWidget(zones_card)

        # --- opciones ---
        opt = SimpleCardWidget(body)
        ol = QGridLayout(opt)
        ol.setContentsMargins(18, 14, 18, 14)
        ol.setHorizontalSpacing(18)
        self.tipo_boxes = {}
        tl = QHBoxLayout()
        tl.setSpacing(24)
        for key, label in TIPOS:
            cb = CheckBox(label, opt)
            cb.setChecked(key in s["tipos"])
            cb.stateChanged.connect(self._save)
            tl.addWidget(cb)
            self.tipo_boxes[key] = cb
        tl.addStretch(1)
        ol.addWidget(StrongBodyLabel("Tipos", opt), 0, 0)
        ol.addLayout(tl, 1, 0, 1, 3)
        self.spins = {}
        for col, (key, label, mx, step) in enumerate([
                ("precio_min", "Precio desde (USD)", 5_000_000, 5000),
                ("precio_max", "Precio hasta (USD)", 5_000_000, 5000),
                ("avisos_por_zona", "Avisos por zona (CABA y resto)", 20000, 50),
                ("avisos_por_zona_norte", "Avisos por zona GBA Norte (a fondo)", 50000, 100),
                ("detalles_por_corrida", "Fichas Argenprop al final", 5000, 10)]):
            sb = SpinBox(opt)
            sb.setRange(0, mx)
            sb.setSingleStep(step)
            sb.setValue(int(s[key]))
            sb.valueChanged.connect(self._save)
            ol.addWidget(BodyLabel(label, opt), 2, col)
            ol.addWidget(sb, 3, col)
            self.spins[key] = sb
        self.estimate = dim_label("", opt)
        ol.addWidget(self.estimate, 4, 0, 1, 5)
        root.addWidget(opt)

        # --- acciones ---
        actions = QHBoxLayout()
        self.run_btn = PrimaryPushButton(FIF.PLAY, "Buscar", body)
        self.run_btn.clicked.connect(lambda: self.start(True, True))
        self.det_btn = PushButton(FIF.PIN, "Solo ubicar / fichas pendientes", body)
        self.det_btn.clicked.connect(lambda: self.start(False, True))
        self.stop_btn = PushButton(FIF.PAUSE, "Detener", body)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        for b in (self.run_btn, self.det_btn, self.stop_btn):
            actions.addWidget(b)
        actions.addStretch(1)
        root.addLayout(actions)

        self.log = PlainTextEdit(body)
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(260)
        root.addWidget(self.log, 1)
        self.setWidget(body)
        self._update_estimate()

    # --- inmobiliarias ---
    def _agency_box(self, ag):
        cb = CheckBox(f"{ag['nombre']}  ·  {ag['url'].replace('https://', '').replace('www.', '')}", self)
        cb.setChecked(ag.get("activa", True))
        cb.stateChanged.connect(lambda _=0, a=ag, c=cb: (a.__setitem__("activa", c.isChecked()), self._save()))
        n = len(self.ag_boxes)
        self.ag_grid.addWidget(cb, n // 3, n % 3)
        self.ag_boxes.append(cb)

    def _add_agency(self):
        t = self.ag_edit.text().strip()
        if not t:
            return
        url = t if t.startswith("http") else "https://" + t
        url = re.sub(r"(https?://[^/]+).*", r"\1", url)
        if any(a["url"] == url for a in self.state.settings["inmobiliarias"]):
            return
        name = re.sub(r"^www\.", "", url.split("://")[1]).split(".")[0].replace("-", " ").title()
        ag = {"nombre": name, "url": url, "activa": True}
        self.state.settings["inmobiliarias"].append(ag)
        self._agency_box(ag)
        self.ag_edit.clear()
        self._save()

    # --- zonas ---
    def _set_zones(self, keys, on):
        for k in keys:
            self.zone_boxes[k].setChecked(on)

    def _extra_box(self, slug):
        name, _ = zone_info(slug)
        cb = CheckBox(f"{name}  ({slug})", self)
        cb.setChecked(slug in self.state.settings["zonas"])
        cb.stateChanged.connect(self._save)
        n = len([k for k in self.zone_boxes if k in self.state.settings["zonas_extra"]])
        self.extra_grid.addWidget(cb, n // 3, n % 3)
        self.zone_boxes[slug] = cb

    def _add_extra(self):
        t = self.extra_edit.text().strip().lower()
        m = re.search(r"/venta/([a-z0-9-]+)", t)
        slug = m.group(1) if m else re.sub(r"[^a-z0-9]+", "-", t).strip("-")
        if not slug or slug in self.zone_boxes:
            return
        self.state.settings["zonas_extra"].append(slug)
        self._extra_box(slug)
        self.zone_boxes[slug].setChecked(True)
        self.extra_edit.clear()

    # --- ajustes ---
    def _save(self, *_):
        s = self.state.settings
        s["zonas"] = [k for k, cb in self.zone_boxes.items() if cb.isChecked()]
        s["tipos"] = [k for k, cb in self.tipo_boxes.items() if cb.isChecked()]
        s["sitios"] = [k for k, cb in self.site_boxes.items() if cb.isChecked()]
        for k, sb in self.spins.items():
            s[k] = sb.value()
        save_settings(s)
        self._update_estimate()

    def _update_estimate(self):
        s = self.state.settings
        zonas = s["zonas"]
        norte = sum(1 for z in zonas if zone_info(z)[1] == "GBA Norte")
        parts, worst = [], 0
        for site in s["sitios"]:
            if site == "tk":
                n_ag = sum(1 for a in s.get("inmobiliarias", []) if a.get("activa", True))
                parts.append(f"Inmobiliarias: {n_ag} webs (~{n_ag * 10 * SECS_PER_PAGE['tk'] / 60:.0f} min)")
                continue
            per = SOURCES[site].PER_PAGE
            first = -(-s["avisos_por_zona"] // per)
            deep = max(first, -(-s["avisos_por_zona_norte"] // per))
            pages = first * len(zonas) + (deep - first) * norte
            secs = pages * SECS_PER_PAGE[site]
            worst = max(worst, secs)
            parts.append(f"{SITE_NAMES[site]} hasta {pages} páginas (~{secs / 3600:.1f} h)")
        self.estimate.setText(
            f"{len(zonas)} zonas ({norte} de GBA Norte). " + " · ".join(parts)
            + f". Como máximo ~{worst / 3600:.1f} h (los sitios corren en paralelo; muchas zonas "
              "tienen menos avisos que el máximo y terminan antes).")

    # --- descarga ---
    def start(self, do_list, do_details):
        s = self.state.settings
        if do_list and (not s["zonas"] or not s["tipos"] or not s["sitios"]):
            InfoBar.warning("Falta elegir", "Marcá al menos un sitio, una zona y un tipo.",
                            parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
            return
        self.totals = {}
        self._log("── Inicio: " + ", ".join(SITE_NAMES[x] for x in s["sitios"]))
        for site in s["sitios"]:
            w = ScrapeWorker(site, dict(s), list(s["zonas"]), self.browser, do_list, do_details)
            w.log.connect(self._log)
            w.progress.connect(self._progress)
            w.finished_ok.connect(self._done)
            self.workers[site] = w
            self.site_status[site].setText("empezando…")
            w.start()
        self._busy(True)

    def stop(self):
        for w in self.workers.values():
            w.stop()
        for site in self.workers:
            self.site_status[site].setText("deteniendo…")

    def _busy(self, busy):
        self.run_btn.setEnabled(not busy)
        self.det_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)

    def _log(self, text):
        line = f"{datetime.now():%H:%M:%S}  {text}"
        self.log.appendPlainText(line)
        try:  # copia en data/logs/ para revisar después
            LOG_DIR.mkdir(exist_ok=True)
            with open(LOG_DIR / f"busqueda_{datetime.now():%Y-%m-%d}.log", "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def _progress(self, site, cur, total, label):
        self.site_bars[site].setValue(int(100 * cur / max(1, total)))
        self.site_status[site].setText(label)
        self._pages += 1
        if self._pages % 10 == 0:  # ir mostrando lo nuevo sin esperar al final
            self.state.reload()

    def _done(self, site, st):
        w = self.workers.pop(site, None)
        if w is not None:
            # finished_ok sale desde adentro de run(): esperar a que el hilo termine de verdad.
            # Si se suelta la última referencia antes, Qt destruye un QThread en marcha y
            # cierra la app de golpe (pasaba al terminar el primer sitio, ej. Inmobiliarias).
            w.wait()
        self.totals[site] = st
        if not st["error"]:
            self.site_bars[site].setValue(100)
        self.site_status[site].setText("con error" if st["error"] else "terminado")
        self._log(f"── {SITE_NAMES[site]} terminó: {st['vistos']} avisos, {st['nuevos']} nuevos, "
                  f"{st['bajas']} bajaron de precio, {st['ubicados']} ubicados por dirección"
                  + (f", {st['fichas']} fichas" if st["fichas"] else ""))
        self.state.reload()
        if self.workers:
            return
        self._busy(False)
        nuevos = sum(t["nuevos"] for t in self.totals.values())
        errors = [t["error"] for t in self.totals.values() if t["error"]]
        if errors:
            InfoBar.warning("Búsqueda terminada con avisos", " ".join(errors), duration=8000,
                            parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
        else:
            InfoBar.success("Búsqueda terminada", f"{nuevos} avisos nuevos en total.",
                            duration=6000, parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
