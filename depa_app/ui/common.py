"""Formatting helpers, colours and animations shared by the pages."""
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsOpacityEffect, QVBoxLayout
from qfluentwidgets import BodyLabel, CaptionLabel, SimpleCardWidget, TitleLabel

from ..i18n import number, tr

ACCENT = "#2bd4a4"
BG = "#16181d"
PANEL = "#1e2128"
TEXT_DIM = "#9aa3ad"


def miles(x, prefix=""):
    """12345.6 -> '12,346' (English) / '12.346' (Spanish)."""
    if x is None:
        return "—"
    return prefix + number(x)


def usd(x):
    return miles(x, "USD ")


def meters(m):
    if m is None:
        return "—"
    return f"{number(m / 1000, 1)} km" if m >= 1000 else f"{m:.0f} m"


def score_color(score):
    """0 red -> 50 amber -> 100 green."""
    s = max(0, min(100, score or 0)) / 100
    if s < 0.5:
        a, b, t = QColor("#e5484d"), QColor("#f5a524"), s / 0.5
    else:
        a, b, t = QColor("#f5a524"), QColor(ACCENT), (s - 0.5) / 0.5
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def fade_in(widget, ms=260):
    """Smooth appearance (opacity 0 -> 1)."""
    eff = widget.graphicsEffect()
    if not isinstance(eff, QGraphicsOpacityEffect):
        eff = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(eff)
    anim = QPropertyAnimation(eff, b"opacity", widget)
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start(QPropertyAnimation.DeleteWhenStopped)


class StatCard(SimpleCardWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setFixedSize(190, 96)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 12)
        self.value = TitleLabel("—", self)
        self.caption = CaptionLabel(tr(title), self)
        self.caption.setTextColor(QColor(TEXT_DIM), QColor(TEXT_DIM))
        lay.addWidget(self.value)
        lay.addWidget(self.caption)

    def set(self, value, color=None):
        self.value.setText(str(value))
        if color:
            self.value.setTextColor(QColor(color), QColor(color))
        fade_in(self.value, 400)


def dim_label(text, parent=None):
    """Wrapped, dimmed text (already translated by the caller)."""
    lab = BodyLabel(text, parent)
    lab.setTextColor(QColor(TEXT_DIM), QColor(TEXT_DIM))
    lab.setWordWrap(True)
    return lab


GLOBAL_QSS = f"""
QWidget#page {{ background: transparent; }}
QToolTip {{ background: {PANEL}; color: #e6e6e6; border: 1px solid #333; }}
"""
ALIGN_RIGHT = Qt.AlignRight | Qt.AlignVCenter
