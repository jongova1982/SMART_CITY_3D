"""Small rolling demand chart implemented with Qt painting only."""
from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class DemandTrend(QWidget):
    COLORS = (QColor("#38bdf8"), QColor("#a78bfa"), QColor("#34d399"), QColor("#fbbf24"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(170)
        self.samples = {zone: deque(maxlen=120) for zone in "ABCD"}

    def add_sample(self, zone_values):
        for zone in "ABCD":
            self.samples[zone].append(float(zone_values.get(zone, {}).get("power_kw", 0.0)))
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#0f1929"))
        area = self.rect().adjusted(48, 18, -18, -26)
        painter.setPen(QPen(QColor("#26364d"), 1))
        for level in range(5):
            y = area.top() + area.height() * level / 4
            painter.drawLine(area.left(), int(y), area.right(), int(y))
        painter.setPen(QColor("#94a3b8"))
        painter.drawText(8, area.top() + 5, "kW")
        painter.drawText(6, area.bottom() + 4, "0")
        painter.drawText(4, area.top() + 4, "200")
        for index, zone in enumerate("ABCD"):
            x = area.left() + index * 76
            painter.setPen(self.COLORS[index])
            painter.drawText(x, self.height() - 5, f"● Zona {zone}")
            values = list(self.samples[zone])
            if len(values) < 2:
                continue
            pen = QPen(self.COLORS[index], 2)
            painter.setPen(pen)
            points = []
            for i, value in enumerate(values):
                x_point = area.left() + i * area.width() / max(1, len(values)-1)
                y_point = area.bottom() - min(200.0, max(0.0, value)) / 200.0 * area.height()
                points.append((int(x_point), int(y_point)))
            for first, second in zip(points, points[1:]):
                painter.drawLine(first[0], first[1], second[0], second[1])
        painter.end()
