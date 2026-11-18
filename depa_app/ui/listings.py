"""Listings page: filters | table | detail panel."""
from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, QUrl)
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, FluentIcon as FIF, ImageLabel, LineEdit,
                            PrimaryPushButton, ProgressBar, PushButton, SmoothScrollArea,
                            StrongBodyLabel, SubtitleLabel, TableView, TitleLabel,
                            TogglePushButton)

from ..domain import geo
from ..i18n import tr
from .common import ACCENT, TEXT_DIM, dim_label, fade_in, meters, miles, score_color, usd
from .labels import group_label, tipo_label
from .filters import FilterPanel

# title, shown value, value used for sorting
COLUMNS = [
    ("Score", lambda r: r["score"], lambda r: r["score"]),
    ("Site", lambda r: SITE_SHORT[r["id"][:2]] + (f" +{len(r['otros'])}" if r["otros"] else ""),
     lambda r: r["id"][:2]),
    ("Type", lambda r: tr("Apt.") if r["tipo"] == "Departamento" else tipo_label(r["tipo"]), lambda r: r["tipo"]),
    ("Zone", lambda r: r["zona"], lambda r: r["zona"] or ""),
    ("Address", lambda r: r["address"], lambda r: r["address"] or ""),
    ("Price", lambda r: usd(r["price_usd"]), lambda r: r["price_usd"] or 1e12),
    ("USD/m²", lambda r: miles(r["ppm2"]), lambda r: r["ppm2"] or 1e12),
    ("vs zone", lambda r: "—" if r["vs_zona"] is None else f"{r['vs_zona']:+d} %",
     lambda r: r["vs_zona"] if r["vs_zona"] is not None else 1e9),
    ("m²", lambda r: miles(r["m2_cub"] or r["m2_tot"]), lambda r: r["m2_cub"] or r["m2_tot"] or 0),
    ("Rooms", lambda r: miles(r["amb"]), lambda r: r["amb"] or 0),
    ("Station", lambda r: r["station"] or tr("not located"), lambda r: r["station"] or "~"),
    ("Distance", lambda r: meters(r["station_m"]), lambda r: r["station_m"] if r["station_m"] is not None else 1e9),
    ("Fees", lambda r: miles(r["expensas"], "$ "), lambda r: r["expensas"] or 0),
    ("Age", lambda r: "—" if r["antig"] is None else tr("{n} yrs", n=f"{r['antig']:.0f}"), lambda r: r["antig"] if r["antig"] is not None else 999),
]
SITE_SHORT = {"ap": "Argenprop", "zp": "Zonaprop", "ml": "MeLi", "tk": "Agency"}
NUMERIC = {0, 5, 6, 7, 8, 9, 11, 12, 13}
CRIT_NAMES = {"estacion": "Close to a station", "precio_m2": "Price per m²", "zona": "Zone",
              "superficie": "Area", "expensas": "Monthly fees", "antiguedad": "Age",
              "extras": "Parking / outdoor / mortgage"}


class Model(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.rows = []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orient, role=Qt.DisplayRole):
        if orient == Qt.Horizontal and role == Qt.DisplayRole:
            return tr(COLUMNS[section][0])
        return None

    def data(self, idx, role=Qt.DisplayRole):
        r = self.rows[idx.row()]
        c = idx.column()
        if role == Qt.DisplayRole:
            v = COLUMNS[c][1](r)
            if c == 4 and r.get("favorite"):
                v = "★ " + (v or "")
            return v
        if role == Qt.UserRole:
            return COLUMNS[c][2](r)
        if role == Qt.UserRole + 1:
            return r["id"]
        if role == Qt.ForegroundRole:
            color = None
            if c == 0:
                color = score_color(r["score"])
            elif c == 7 and r["vs_zona"] is not None and abs(r["vs_zona"]) > 5:
                color = QColor(ACCENT) if r["vs_zona"] < 0 else QColor("#e5484d")
            elif c == 11 and r["station_m"] is not None and r["station_m"] <= 600:
                color = QColor(ACCENT)
            elif r.get("discarded"):
                color = QColor("#5b626b")
            return QBrush(color) if color else None
        if role == Qt.TextAlignmentRole and c in NUMERIC:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ToolTipRole and c == 4:
            return r["title"]
        if role == Qt.ToolTipRole and c == 1 and r["otros"]:
            return tr("Also on: ") + ", ".join(f"{tr(s)} ({usd(p)})" for s, _, p in r["otros"])
        return None


class DetailPanel(SmoothScrollArea):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.r = None
        self.setWidgetResizable(True)
        self.setFixedWidth(380)
        self.setStyleSheet("QScrollArea{background:transparent;border:none}")
        self.body = QWidget()
        self.body.setStyleSheet("background:transparent")
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(12, 0, 12, 12)
        lay.setSpacing(8)

        self.photo = ImageLabel(self.body)
        self.photo.setBorderRadius(10, 10, 10, 10)
        self.photo.setFixedHeight(220)
        self.price = TitleLabel(tr("Pick a property"), self.body)
        self.title = StrongBodyLabel("", self.body)
        self.title.setWordWrap(True)
        self.addr = dim_label("", self.body)
        self.also = BodyLabel("", self.body)
        self.also.setWordWrap(True)
        self.also.setOpenExternalLinks(True)
        self.also.setTextFormat(Qt.RichText)
        self.facts = BodyLabel("", self.body)
        self.facts.setWordWrap(True)
        self.station = BodyLabel("", self.body)
        self.station.setWordWrap(True)

        btns = QHBoxLayout()
        self.open_btn = PrimaryPushButton(FIF.LINK, tr("Open listing"), self.body)
        self.open_btn.clicked.connect(lambda: self.r and QDesktopServices.openUrl(QUrl(self.r["url"])))
        self.map_btn = PushButton(FIF.GLOBE, tr("Map"), self.body)
        self.map_btn.clicked.connect(lambda: self.r and self.state.map_focus_request.emit(self.r["id"]))
        btns.addWidget(self.open_btn)
        btns.addWidget(self.map_btn)
        btns2 = QHBoxLayout()
        self.fav = TogglePushButton(FIF.HEART, tr("Favourite"), self.body)
        self.fav.clicked.connect(self._fav)
        self.disc = TogglePushButton(FIF.DELETE, tr("Discard"), self.body)
        self.disc.clicked.connect(self._disc)
        btns2.addWidget(self.fav)
        btns2.addWidget(self.disc)

        self.notes = LineEdit(self.body)
        self.notes.setPlaceholderText(tr("Your notes (saved automatically)"))
        self.notes.editingFinished.connect(self._notes)

        self.score_lbl = SubtitleLabel("", self.body)
        self.bars = {}
        crit_box = QVBoxLayout()
        crit_box.setSpacing(2)
        for k, name in CRIT_NAMES.items():
            cap = CaptionLabel(name, self.body)
            bar = ProgressBar(self.body)
            bar.setRange(0, 100)
            crit_box.addWidget(cap)
            crit_box.addWidget(bar)
            self.bars[k] = (cap, bar)

        self.history = dim_label("", self.body)
        self.features = dim_label("", self.body)
        self.desc = dim_label("", self.body)
        self.desc.setTextInteractionFlags(Qt.TextSelectableByMouse)

        for w in (self.photo, self.price, self.title, self.addr, self.also, self.facts, self.station):
            lay.addWidget(w)
        lay.addLayout(btns)
        lay.addLayout(btns2)
        lay.addWidget(self.notes)
        lay.addSpacing(6)
        lay.addWidget(self.score_lbl)
        lay.addLayout(crit_box)
        lay.addSpacing(6)
        lay.addWidget(self.history)
        lay.addWidget(StrongBodyLabel(tr("Features"), self.body))
        lay.addWidget(self.features)
        lay.addWidget(StrongBodyLabel(tr("Description"), self.body))
        lay.addWidget(self.desc)
        lay.addStretch(1)
        self.setWidget(self.body)

        self.net = QNetworkAccessManager(self)
        self.net.finished.connect(self._photo_loaded)
        self.show_listing(None)

    def show_listing(self, r):
        self.r = r
        for w in self.body.findChildren(QWidget):
            if w is not self.price:
                w.setVisible(r is not None)
        if r is None:
            return
        self.price.setText(usd(r["price_usd"]) if r["price_usd"] else miles(r["price_ars"], "$ "))
        self.title.setText(r["title"] or "")
        self.addr.setText(f"{r['address']} · {r['zona']} ({group_label(r['grupo'])}) · {tr(SITE_SHORT[r['id'][:2]])}")
        self.also.setText(tr("Also on: ") + " · ".join(
            f'<a style="color:{ACCENT}" href="{u}">{tr(s)} {usd(p)}</a>' for s, u, p in r["otros"])
            if r["otros"] else "")
        self.also.setVisible(bool(r["otros"]))
        bits = [tipo_label(r["tipo"])]
        if r["amb"]:
            bits.append(tr("{n} rooms", n=f"{r['amb']:.0f}"))
        if r["dorm"]:
            bits.append(tr("{n} bedr.", n=f"{r['dorm']:.0f}"))
        if r["banos"]:
            bits.append(tr("{n} bath(s)", n=f"{r['banos']:.0f}"))
        if r["m2_cub"]:
            bits.append(tr("{n} m² covered", n=f"{r['m2_cub']:.0f}"))
        if r["m2_tot"] and r["m2_tot"] != r["m2_cub"]:
            bits.append(tr("{n} m² total", n=f"{r['m2_tot']:.0f}"))
        if r["ppm2"]:
            vs = "" if r["vs_zona"] is None else tr(" ({pct:+d} % vs zone)", pct=r["vs_zona"])
            bits.append(f"USD {miles(r['ppm2'])}/m²{vs}")
        if r["expensas"]:
            bits.append(tr("fees {amount}", amount=miles(r["expensas"], "$ ")))
        if r["antig"] is not None:
            bits.append(tr("brand new") if r["antig"] == 0 else tr("{n} years old", n=f"{r['antig']:.0f}"))
        self.facts.setText(" · ".join(bits))
        if r["station_m"] is not None:
            line = f" ({r['station_line']})" if r["station_line"] else ""
            approx = tr(" (approximate location from the address)") if r.get("geo_src") == "direccion" else ""
            self.station.setText(tr("{station} station{line}: {distance} in a straight line, ~{minutes} min walk",
                                    station=r["station"], line=line, distance=meters(r["station_m"]),
                                    minutes=geo.walk_minutes(r["station_m"])) + approx)
            if r.get("subte_m") is not None and r["subte_m"] <= 2000:
                self.station.setText(self.station.text() + "\n" + tr(
                    "Subte {line} {station}: {distance} (~{minutes} min)", line=r["subte_line"], station=r["subte"],
                    distance=meters(r["subte_m"]), minutes=geo.walk_minutes(r["subte_m"])))
        else:
            self.station.setText(tr("Station: not located (the address was not found; filled in when the detail page is read)."))
        self.fav.setChecked(bool(r.get("favorite")))
        self.disc.setChecked(bool(r.get("discarded")))
        self.notes.setText(r.get("notes") or "")

        self.score_lbl.setText(tr("Score {score}/100", score=r["score"]))
        self.score_lbl.setTextColor(score_color(r["score"]), score_color(r["score"]))
        for k, (cap, bar) in self.bars.items():
            v = round(100 * r["criterios"].get(k, 0))
            w = self.state.settings["pesos"].get(k, 0)
            cap.setText(tr("{criterion} · {value}/100 · weight {weight}", criterion=tr(CRIT_NAMES[k]), value=v, weight=w))
            bar.setValue(v)

        h = r.get("history", [])
        hist = " → ".join(f"{d[5:]}: {usd(p)}" for d, p in h[-6:]) if len(h) > 1 else ""
        self.history.setText((tr("Price history: ") + hist) if hist else
                             tr("First seen: {date}", date=(r["first_seen"] or "")[:10]))
        feats = [k if v is True else f"{k}: {v}" for k, v in r["features"].items()
                 if k not in ("Tipo de operación", "Precio")]
        self.features.setText(" · ".join(feats) if feats else tr("Filled in when the detail page is read."))
        self.desc.setText(r["description"] or "")

        self.photo.setFixedHeight(220)
        self.photo.setImage(QPixmap())
        if r.get("photo"):
            req = QNetworkRequest(QUrl(r["photo"].replace("_u_small", "_u_medium")))
            req.setAttribute(QNetworkRequest.User, r["id"])
            self.net.get(req)
        fade_in(self.body)

    def _photo_loaded(self, reply):
        rid = reply.request().attribute(QNetworkRequest.User)
        data = reply.readAll()
        reply.deleteLater()
        if not self.r or rid != self.r["id"]:
            return
        pm = QPixmap()
        if not pm.loadFromData(data) and "_u_medium" in reply.url().toString():
            req = QNetworkRequest(QUrl(self.r["photo"]))  # sin versión mediana: usar la chica
            req.setAttribute(QNetworkRequest.User, rid)
            self.net.get(req)
            return
        self.photo.setImage(pm)
        self.photo.scaledToWidth(self.width() - 40)
        fade_in(self.photo)

    def _fav(self):
        if self.r:
            self.state.set_flag(self.r["id"], "favorite", int(self.fav.isChecked()))
            self.state.filters_changed.emit()

    def _disc(self):
        if self.r:
            self.state.set_flag(self.r["id"], "discarded", int(self.disc.isChecked()))
            self.state.filters_changed.emit()

    def _notes(self):
        if self.r and self.notes.text() != (self.r.get("notes") or ""):
            self.state.set_flag(self.r["id"], "notes", self.notes.text())


class ListingsPage(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.setObjectName("propiedades")
        self.state = state
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 12, 12)
        head = QHBoxLayout()
        head.addWidget(TitleLabel(tr("Listings"), self))
        self.count = dim_label("", self)
        head.addSpacing(16)
        head.addWidget(self.count, 1)
        root.addLayout(head)

        body = QHBoxLayout()
        self.filters = FilterPanel(state, self)
        body.addWidget(self.filters)

        self.model = Model()
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.UserRole)
        self.table = TableView(self)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.DescendingOrder)
        self.table.setSelectionBehavior(TableView.SelectRows)
        self.table.setSelectionMode(TableView.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.setWordWrap(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(False)
        for c, w in enumerate([100, 92, 84, 120, 240, 118, 82, 80, 58, 58, 150, 88, 112, 82]):
            self.table.setColumnWidth(c, w)
        self.table.selectionModel().currentRowChanged.connect(self._row)
        body.addWidget(self.table, 1)

        self.detail = DetailPanel(state, self)
        body.addWidget(self.detail)
        root.addLayout(body, 1)

        state.data_changed.connect(self.refresh)
        state.filters_changed.connect(self.refresh)
        state.select_request.connect(self.select)

    def refresh(self):
        keep = self.detail.r["id"] if self.detail.r else None
        rows = self.state.filtered()
        self.model.set_rows(rows)
        total = len(self.state.rows)
        located = sum(1 for r in rows if r["lat"] is not None)
        self.count.setText(tr("{shown} of {total} listings · {located} located", shown=len(rows), total=total, located=located))
        if keep:
            self.select(keep, scroll=False)

    def select(self, lid, scroll=True):
        for i, r in enumerate(self.model.rows):
            if r["id"] == lid:
                idx = self.proxy.mapFromSource(self.model.index(i, 0))
                self.table.selectRow(idx.row())
                if scroll:
                    self.table.scrollTo(idx, TableView.PositionAtCenter)
                return
        r = self.state.by_id.get(lid)  # oculto por los filtros: mostrar igual la ficha
        if r:
            self.detail.show_listing(r)

    def _row(self, cur, _prev):
        if not cur.isValid():
            return
        lid = self.proxy.data(cur.siblingAtColumn(0), Qt.UserRole + 1)
        r = self.state.by_id.get(lid)
        if r:
            self.detail.show_listing(r)
