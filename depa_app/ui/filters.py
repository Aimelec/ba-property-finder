"""Panel de filtros (se usa en Propiedades y en Mapa, sincronizados)."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CheckBox, SearchLineEdit, SpinBox, StrongBodyLabel,
                            SmoothScrollArea)

from ..config import save_settings
from ..zones import GROUPS

TIPOS = ["Departamento", "Casa", "PH"]
SITIOS = [("ap", "Argenprop"), ("zp", "Zonaprop"), ("ml", "MercadoLibre"), ("tk", "Inmobiliarias")]
NUMS = [  # clave, etiqueta, máximo, paso
    ("precio_min", "Precio mín. (USD)", 5_000_000, 5000),
    ("precio_max", "Precio máx. (USD)", 5_000_000, 5000),
    ("amb_min", "Ambientes mín.", 10, 1),
    ("m2_min", "m² mín.", 2000, 5),
    ("dist_max", "Máx. a estación (m)", 10000, 100),
    ("expensas_max", "Expensas máx. ($)", 5_000_000, 10000),
]
FLAGS = [
    ("solo_credito", "Solo apto crédito"),
    ("solo_cochera", "Solo con cochera"),
    ("solo_favoritos", "Solo favoritos"),
    ("ocultar_descartados", "Ocultar descartados"),
    ("ocultar_duplicados", "Ocultar repetidos (mismo inmueble en otro sitio)"),
    ("solo_con_ubicacion", "Solo con ubicación"),
]


class FilterPanel(SmoothScrollArea):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWidgetResizable(True)
        self.setFixedWidth(250)
        self.setStyleSheet("QScrollArea{background:transparent;border:none}")
        body = QWidget()
        body.setStyleSheet("background:transparent")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(4, 0, 12, 12)
        lay.setSpacing(6)

        self.search = SearchLineEdit(body)
        self.search.setPlaceholderText("Buscar dirección, zona, estación…")
        self.search.textChanged.connect(self._text)
        lay.addWidget(self.search)

        self.nums = {}
        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        for i, (k, label, mx, step) in enumerate(NUMS):
            sb = SpinBox(body)
            sb.setRange(0, mx)
            sb.setSingleStep(step)
            sb.valueChanged.connect(self._changed)
            grid.addWidget(BodyLabel(label, body), 2 * i, 0)
            grid.addWidget(sb, 2 * i + 1, 0)
            self.nums[k] = sb
        lay.addLayout(grid)
        lay.addWidget(BodyLabel("0 = sin límite", body))

        lay.addSpacing(6)
        lay.addWidget(StrongBodyLabel("Tipo", body))
        self.tipos = {}
        for t in TIPOS:
            cb = CheckBox(t, body)
            cb.stateChanged.connect(self._changed)
            lay.addWidget(cb)
            self.tipos[t] = cb

        lay.addSpacing(6)
        lay.addWidget(StrongBodyLabel("Sitios", body))
        self.sitios = {}
        for k, label in SITIOS:
            cb = CheckBox(label, body)
            cb.stateChanged.connect(self._changed)
            lay.addWidget(cb)
            self.sitios[k] = cb

        lay.addSpacing(6)
        lay.addWidget(StrongBodyLabel("Zonas", body))
        self.grupos = {}
        for g in GROUPS:
            cb = CheckBox(g, body)
            cb.stateChanged.connect(self._changed)
            lay.addWidget(cb)
            self.grupos[g] = cb

        lay.addSpacing(6)
        lay.addWidget(StrongBodyLabel("Otros", body))
        self.flags = {}
        for k, label in FLAGS:
            cb = CheckBox(label, body)
            cb.stateChanged.connect(self._changed)
            lay.addWidget(cb)
            self.flags[k] = cb
        lay.addStretch(1)
        self.setWidget(body)

        self._timer = QTimer(self, singleShot=True, interval=250)
        self._timer.timeout.connect(self._apply)
        self._loading = False
        self.load()
        state.filters_changed.connect(self._external)

    def load(self):
        self._loading = True
        f = self.state.settings["filtro"]
        for k, sb in self.nums.items():
            sb.setValue(int(f.get(k) or 0))
        for t, cb in self.tipos.items():
            cb.setChecked(t in f["tipos"])
        for g, cb in self.grupos.items():
            cb.setChecked(g in f["grupos"])
        for k, cb in self.flags.items():
            cb.setChecked(bool(f.get(k)))
        for k, cb in self.sitios.items():
            cb.setChecked(k in f.get("sitios", [k]))
        if self.search.text() != self.state.text:
            self.search.setText(self.state.text)
        self._loading = False

    def _external(self):
        if self.sender_is_me:
            return
        self.load()

    sender_is_me = False

    def _text(self, t):
        if not self._loading:
            self.state.text = t
            self._timer.start()

    def _changed(self, *_):
        if not self._loading:
            self._timer.start()

    def _apply(self):
        f = self.state.settings["filtro"]
        for k, sb in self.nums.items():
            f[k] = sb.value()
        f["tipos"] = [t for t, cb in self.tipos.items() if cb.isChecked()]
        f["grupos"] = [g for g, cb in self.grupos.items() if cb.isChecked()]
        for k, cb in self.flags.items():
            f[k] = cb.isChecked()
        f["sitios"] = [k for k, cb in self.sitios.items() if cb.isChecked()]
        save_settings(self.state.settings)
        self.sender_is_me = True
        self.state.filters_changed.emit()
        self.sender_is_me = False
