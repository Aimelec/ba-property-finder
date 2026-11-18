"""Preferences page: score weights and criteria, zone priorities, stations, interface language."""
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QGridLayout, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, ComboBox, FluentIcon as FIF, InfoBar, InfoBarPosition, PushButton,
                            SimpleCardWidget, Slider, SmoothScrollArea, SpinBox, StrongBodyLabel,
                            TitleLabel)

from ..opendata import stations
from ..config import save_settings
from ..i18n import LANGUAGES, language, tr
from .labels import group_label
from .common import dim_label

WEIGHTS = [
    ("estacion", "Close to a train station"),
    ("precio_m2", "Price per m² (compared with the zone)"),
    ("zona", "Zone priority"),
    ("superficie", "Area"),
    ("expensas", "Low monthly fees"),
    ("antiguedad", "Newer building"),
    ("extras", "Parking / balcony-patio / mortgage-eligible"),
]


class StationsDownload(QThread):
    done = Signal(object)

    def run(self):
        try:
            self.done.emit(stations.download())
        except Exception as e:
            self.done.emit(e)


class PrefsPage(SmoothScrollArea):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.setObjectName("preferencias")
        self.state = state
        s = state.settings
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea{background:transparent;border:none}")
        body = QWidget()
        body.setStyleSheet("background:transparent")
        root = QVBoxLayout(body)
        root.setContentsMargins(24, 16, 24, 24)
        root.setSpacing(12)
        root.addWidget(TitleLabel(tr("Preferences"), body))
        root.addWidget(dim_label(
            tr("The score (0-100) is a weighted average. Move the weights according to what matters most "
               "to you; the list and the map update instantly."), body))

        self.timer = QTimer(self, singleShot=True, interval=300)
        self.timer.timeout.connect(self._apply)

        card = SimpleCardWidget(body)
        g = QGridLayout(card)
        g.setContentsMargins(18, 14, 18, 14)
        g.addWidget(StrongBodyLabel(tr("Weights"), card), 0, 0)
        self.sliders = {}
        for i, (k, label) in enumerate(WEIGHTS, start=1):
            sl = Slider(Qt.Horizontal, card)
            sl.setRange(0, 100)
            sl.setValue(int(s["pesos"].get(k, 0)))
            sl.setMinimumWidth(320)
            val = BodyLabel(str(sl.value()), card)
            val.setFixedWidth(30)
            sl.valueChanged.connect(lambda v, lab=val: (lab.setText(str(v)), self.timer.start()))
            g.addWidget(BodyLabel(tr(label), card), i, 0)
            g.addWidget(sl, i, 1)
            g.addWidget(val, i, 2)
            self.sliders[k] = sl
        root.addWidget(card)

        card2 = SimpleCardWidget(body)
        g2 = QGridLayout(card2)
        g2.setContentsMargins(18, 14, 18, 14)
        g2.addWidget(StrongBodyLabel(tr("Criteria"), card2), 0, 0)
        self.spins = {}
        for i, (k, label, mx, step) in enumerate([
                ("estacion_ideal_m", "Ideal distance to a station (m): full score", 5000, 50),
                ("estacion_max_m", "Distance to a station that scores zero (m)", 20000, 100),
                ("m2_ideal", "m² that give the full area score", 1000, 5)], start=1):
            sb = SpinBox(card2)
            sb.setRange(0, mx)
            sb.setSingleStep(step)
            sb.setValue(int(s[k]))
            sb.valueChanged.connect(lambda *_: self.timer.start())
            g2.addWidget(BodyLabel(tr(label), card2), i, 0)
            g2.addWidget(sb, i, 1)
            self.spins[k] = sb
        root.addWidget(card2)

        card3 = SimpleCardWidget(body)
        g3 = QGridLayout(card3)
        g3.setContentsMargins(18, 14, 18, 14)
        g3.addWidget(StrongBodyLabel(tr("Priority of each zone (0-100)"), card3), 0, 0)
        self.prio = {}
        for i, (grp, v) in enumerate(s["prioridad_grupo"].items(), start=1):
            sl = Slider(Qt.Horizontal, card3)
            sl.setRange(0, 100)
            sl.setValue(int(v))
            sl.setMinimumWidth(320)
            val = BodyLabel(str(v), card3)
            val.setFixedWidth(30)
            sl.valueChanged.connect(lambda x, lab=val: (lab.setText(str(x)), self.timer.start()))
            g3.addWidget(BodyLabel(group_label(grp), card3), i, 0)
            g3.addWidget(sl, i, 1)
            g3.addWidget(val, i, 2)
            self.prio[grp] = sl
        root.addWidget(card3)

        card4 = SimpleCardWidget(body)
        l4 = QVBoxLayout(card4)
        l4.setContentsMargins(18, 14, 18, 14)
        l4.addWidget(StrongBodyLabel(tr("Train stations"), card4))
        self.st_info = dim_label(tr("{n} AMBA stations (OpenStreetMap). The Mitre diesel branches and the Tren de "
                                    "la Costa don't count. Subte not included.", n=len(state.stations)), card4)
        l4.addWidget(self.st_info)
        self.st_btn = PushButton(FIF.SYNC, tr("Update stations"), card4)
        self.st_btn.clicked.connect(self._update_stations)
        l4.addWidget(self.st_btn, 0, Qt.AlignLeft)
        root.addWidget(card4)

        card5 = SimpleCardWidget(body)
        l5 = QVBoxLayout(card5)
        l5.setContentsMargins(18, 14, 18, 14)
        l5.addWidget(StrongBodyLabel(tr("Language"), card5))
        self.lang = ComboBox(card5)
        for code, name in LANGUAGES.items():
            self.lang.addItem(name, userData=code)
        self.lang.setCurrentIndex(list(LANGUAGES).index(language()))
        self.lang.currentIndexChanged.connect(self._language)
        l5.addWidget(self.lang, 0, Qt.AlignLeft)
        root.addWidget(card5)
        root.addStretch(1)
        self.setWidget(body)

    def _apply(self):
        s = self.state.settings
        for k, sl in self.sliders.items():
            s["pesos"][k] = sl.value()
        for k, sb in self.spins.items():
            s[k] = sb.value()
        for g, sl in self.prio.items():
            s["prioridad_grupo"][g] = sl.value()
        save_settings(s)
        self.state.rescore()

    def _language(self, _index):
        self.state.settings["idioma"] = self.lang.currentData()
        save_settings(self.state.settings)
        InfoBar.success(tr("Language saved"), tr("It applies the next time you open the app."),
                        parent=self.window(), position=InfoBarPosition.TOP_RIGHT)

    def _update_stations(self):
        self.st_btn.setEnabled(False)
        self.dl = StationsDownload()
        self.dl.done.connect(self._stations_done)
        self.dl.start()

    def _stations_done(self, res):
        self.st_btn.setEnabled(True)
        if isinstance(res, Exception):
            InfoBar.error(tr("Could not update"), str(res), parent=self.window(),
                          position=InfoBarPosition.TOP_RIGHT)
            return
        st = self.state
        st.stations = res
        st.station_pos = {(x["name"], x["line"]): x for x in res}
        from ..repositories import listings_db as db
        con = db.connect()
        con.execute("UPDATE listings SET station=NULL, station_line=NULL, station_m=NULL")
        con.commit()
        con.close()
        st.reload()  # recalcula la estación más cercana de cada aviso
        self.st_info.setText(tr("{n} AMBA stations (OpenStreetMap), without the Mitre diesel branches or the "
                                "Tren de la Costa.", n=len(res)))
        InfoBar.success(tr("Stations updated"), tr("{n} stations.", n=len(res)), parent=self.window(),
                        position=InfoBarPosition.TOP_RIGHT)
