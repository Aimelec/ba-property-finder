"""The Catalog with the Qt signals the pages listen to."""
from PySide6.QtCore import QObject, Signal

from ..services.catalog import Catalog


class AppState(Catalog, QObject):  # Catalog first: QObject.__init__ chains to object, not to Catalog
    data_changed = Signal()       # listings were reloaded / rescored
    filters_changed = Signal()    # a filter changed
    select_request = Signal(str)  # show a listing (id) on the Listings page
    map_focus_request = Signal(str)

    def __init__(self, settings):
        QObject.__init__(self)
        Catalog.__init__(self, settings)

    def rescore(self):
        Catalog.rescore(self)
        self.data_changed.emit()
