"""Background download threads for the Search page."""
from PySide6.QtCore import QThread, Signal

from .. import plugins
from ..services.scrape import ScrapeRun


class ScrapeWorker(QThread):
    """Runs a ScrapeRun for one site on its own thread and forwards its reports as signals."""
    log = Signal(str)
    progress = Signal(str, int, int, str)   # site, current, total, label
    finished_ok = Signal(str, dict)

    def __init__(self, site, settings, zonas, browser=None, do_list=True, do_details=True):
        super().__init__()
        self.site = site
        self.run_ = ScrapeRun(site, settings, zonas, browser, do_list, do_details,
                              log=self.log.emit, progress=self.progress.emit, slicer=plugins.zone_slicer())

    def stop(self):
        self.run_.stop()

    def run(self):
        self.finished_ok.emit(self.site, self.run_.run())
