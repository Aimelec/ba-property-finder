"""Página Inicio: resumen y mejores opciones."""
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, CardWidget, FlowLayout, SmoothScrollArea,
                            StrongBodyLabel, SubtitleLabel, TitleLabel)

from ..domain import geo
from .common import ACCENT, StatCard, TEXT_DIM, dim_label, fade_in, meters, score_color, usd


class ListingCard(CardWidget):
    """Fila clickeable con un aviso."""
    opened = Signal(str)

    def __init__(self, r, parent=None):
        super().__init__(parent)
        self.lid = r["id"]
        self.setFixedHeight(66)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 8)
        sc = SubtitleLabel(str(r["score"]), self)
        sc.setFixedWidth(44)
        sc.setTextColor(score_color(r["score"]), score_color(r["score"]))
        lay.addWidget(sc)
        mid = QVBoxLayout()
        mid.setSpacing(0)
        star = "★ " if r.get("favorite") else ""
        mid.addWidget(StrongBodyLabel(f"{star}{r['address']}", self))
        bits = [r["tipo"], r["zona"]]
        if r["amb"]:
            bits.append(f"{r['amb']:.0f} amb.")
        m2 = r["m2_cub"] or r["m2_tot"]
        if m2:
            bits.append(f"{m2:.0f} m²")
        if r["station_m"] is not None:
            bits.append(f"estación {r['station']} {meters(r['station_m'])} "
                        f"(~{geo.walk_minutes(r['station_m'])} min)")
        cap = CaptionLabel(" · ".join(bits), self)
        cap.setTextColor(QColor(TEXT_DIM), QColor(TEXT_DIM))
        mid.addWidget(cap)
        lay.addLayout(mid, 1)
        price = StrongBodyLabel(usd(r["price_usd"]), self)
        lay.addWidget(price)
        self.clicked.connect(lambda: self.opened.emit(self.lid))


class HomePage(SmoothScrollArea):
    def __init__(self, state, go_to_listing, parent=None):
        super().__init__(parent)
        self.setObjectName("inicio")
        self.state = state
        self.go_to_listing = go_to_listing
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea{background:transparent;border:none}")
        body = QWidget()
        body.setStyleSheet("background:transparent")
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(24, 16, 24, 24)
        self.lay.setSpacing(12)
        self.lay.addWidget(TitleLabel("depa", body))
        self.lay.addWidget(dim_label(
            "Avisos de venta de portales e inmobiliarias con puntaje según tus preferencias. Lo más "
            "importante por defecto: cercanía a una estación de tren y zona norte.", body))

        stats_w = QWidget(body)
        self.flow = FlowLayout(stats_w, needAni=True)
        self.flow.setHorizontalSpacing(12)
        self.cards = {}
        for k, t in [("total", "Avisos guardados"), ("ubicados", "Con ubicación"),
                     ("filtrados", "Pasan tus filtros"), ("nuevos", "Nuevos hoy"),
                     ("bajas", "Bajaron de precio"), ("cerca", "A ≤ 600 m de estación")]:
            self.cards[k] = StatCard(t, stats_w)
            self.flow.addWidget(self.cards[k])
        self.lay.addWidget(stats_w)

        self.lay.addWidget(SubtitleLabel("Mejores según tus preferencias", body))
        self.top_box = QVBoxLayout()
        self.top_box.setSpacing(6)
        self.lay.addLayout(self.top_box)
        self.lay.addWidget(SubtitleLabel("Bajaron de precio", body))
        self.drop_box = QVBoxLayout()
        self.drop_box.setSpacing(6)
        self.lay.addLayout(self.drop_box)
        self.lay.addStretch(1)
        self.setWidget(body)
        state.data_changed.connect(self.refresh)
        state.filters_changed.connect(self.refresh)

    def _fill(self, box, rows, empty):
        while box.count():
            w = box.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not rows:
            box.addWidget(dim_label(empty, self))
        for r in rows:
            c = ListingCard(r, self)
            c.opened.connect(self.go_to_listing)
            box.addWidget(c)
            fade_in(c, 350)

    def refresh(self):
        rows = self.state.rows
        filt = self.state.filtered()
        today = date.today().isoformat()
        self.cards["total"].set(len(rows))
        self.cards["ubicados"].set(sum(1 for r in rows if r["lat"] is not None))
        self.cards["filtrados"].set(len(filt), ACCENT)
        self.cards["nuevos"].set(sum(1 for r in rows if (r["first_seen"] or "").startswith(today)))
        self.cards["bajas"].set(sum(1 for r in rows if r["bajo_precio"]))
        self.cards["cerca"].set(sum(1 for r in filt if r["station_m"] is not None and r["station_m"] <= 600))
        self._fill(self.top_box, filt[:10],
                   "Todavía no hay avisos. Andá a Buscar para descargar los primeros.")
        self._fill(self.drop_box, [r for r in filt if r["bajo_precio"]][:10],
                   "Ninguno por ahora (se detecta al volver a buscar otro día).")
