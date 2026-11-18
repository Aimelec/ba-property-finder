"""depa: buscador de propiedades en venta (portales e inmobiliarias) con puntaje y mapa."""
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401  (antes de QApplication)
from PySide6.QtWidgets import QApplication
from qfluentwidgets import (FluentIcon as FIF, FluentWindow, NavigationItemPosition, Theme,
                            setTheme, setThemeColor)

from depa_app.config import load_settings
from depa_app.i18n import set_language, tr
from depa_app.ui.app_state import AppState
from depa_app.ui.common import ACCENT, BG, GLOBAL_QSS
from depa_app.ui.home import HomePage
from depa_app.ui.listings import ListingsPage
from depa_app.ui.map_page import MapPage
from depa_app.ui.prefs import PrefsPage
from depa_app.ui.search import SearchPage


class MainWindow(FluentWindow):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.setWindowTitle(tr("depa · properties"))
        self.resize(1500, 900)
        self.setMicaEffectEnabled(False)
        self.setCustomBackgroundColor(QColor(BG), QColor(BG))

        self.home = HomePage(state, self.go_to_listing, self)
        self.listings = ListingsPage(state, self)
        self.map = MapPage(state, self.go_to_listing, self)
        self.search = SearchPage(state, self)
        self.prefs = PrefsPage(state, self)
        self.addSubInterface(self.home, FIF.HOME, tr("Home"))
        self.addSubInterface(self.listings, FIF.TILES, tr("Listings"))
        self.addSubInterface(self.map, FIF.GLOBE, tr("Map"))
        self.addSubInterface(self.search, FIF.SEARCH, tr("Search"))
        self.addSubInterface(self.prefs, FIF.SETTING, tr("Preferences"), NavigationItemPosition.BOTTOM)
        self.navigationInterface.setExpandWidth(190)
        state.map_focus_request.connect(self.go_to_map)
        # si buscar.bat (u otra ventana) agrega avisos, recargar solo
        self._watch = QTimer(self, interval=60_000)
        self._watch.timeout.connect(self._maybe_reload)
        self._watch.start()

    def _maybe_reload(self):
        w = self.search.workers
        if not w and self.state.db_mtime() > getattr(self.state, "loaded_mtime", 0) + 1:
            self.state.reload()

    def go_to_listing(self, lid):
        self.switchTo(self.listings)
        self.state.select_request.emit(lid)

    def go_to_map(self, lid):
        self.switchTo(self.map)
        self.map.focus(lid)

    def closeEvent(self, e):
        for w in self.search.workers.values():
            w.stop()
        for w in self.search.workers.values():
            w.wait(3000)
        super().closeEvent(e)


def _crash_log():
    """Con pythonw no hay consola: los errores fatales y los avisos de Qt van a
    data/logs/errores.log, para saber por qué se cerró la app."""
    import faulthandler
    import traceback
    from datetime import datetime

    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    from depa_app.config import DATA

    path = DATA / "logs" / "errores.log"
    path.parent.mkdir(exist_ok=True)
    f = open(path, "a", encoding="utf-8", buffering=1)
    faulthandler.enable(f)

    def write(text):
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n")

    def qt_message(mode, ctx, msg):
        if mode != QtMsgType.QtDebugMsg:
            write(f"Qt {mode.name}: {msg}")

    sys.excepthook = lambda t, v, tb: write("".join(traceback.format_exception(t, v, tb)))
    qInstallMessageHandler(qt_message)


def main():
    _crash_log()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    setTheme(Theme.DARK)
    setThemeColor(ACCENT)
    app.setStyleSheet(GLOBAL_QSS)
    settings = load_settings()
    set_language(settings.get("idioma", "en"))   # before any widget is built
    state = AppState(settings)
    win = MainWindow(state)
    state.reload()
    win.show()
    if "--buscar" in sys.argv:  # abrir y empezar a buscar con los ajustes guardados
        win.switchTo(win.search)
        QTimer.singleShot(1500, lambda: win.search.start(True, True))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
