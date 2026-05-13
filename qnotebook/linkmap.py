"""Link map dock: 1-hop graph of pages around the current page.

Uses QGraphicsScene with circle items for pages and line items for links.
Forward links + backlinks (backlinks rendered with a dashed pen).
"""

from __future__ import annotations

import math
from typing import Callable

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QBrush, QColor, QFont, QPen
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QVBoxLayout,
    QWidget,
)


NODE_RADIUS = 24


class _PageNode(QGraphicsEllipseItem):
    def __init__(self, page: str, x: float, y: float, is_center: bool, on_click: Callable[[str], None]) -> None:
        super().__init__(x - NODE_RADIUS, y - NODE_RADIUS, NODE_RADIUS * 2, NODE_RADIUS * 2)
        self.page = page
        self._on_click = on_click
        color = QColor("#2e86de") if is_center else QColor("#95a5a6")
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor("#2c3e50"), 1))
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click(self.page)
            event.accept()
            return
        super().mousePressEvent(event)


class LinkMapDock(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene, self)
        self.view.setRenderHints(self.view.renderHints())
        v.addWidget(self.view, 1)
        self._on_navigate: Callable[[str], None] = lambda _p: None
        self._nodes: dict[str, _PageNode] = {}

    def set_on_navigate(self, cb: Callable[[str], None]) -> None:
        self._on_navigate = cb

    def build(self, current_page: str | None, forward: list[str], backward: list[str]) -> None:
        self.scene.clear()
        self._nodes = {}
        if current_page is None:
            return
        center = QPointF(0.0, 0.0)
        self._add_node(current_page, center, is_center=True)
        # Place forward links on right half; back on left half of circle.
        all_peers: list[tuple[str, str]] = []
        for p in forward:
            if p != current_page:
                all_peers.append(("fwd", p))
        for p in backward:
            if p != current_page and all(p != q for _, q in all_peers):
                all_peers.append(("back", p))
        count = len(all_peers)
        radius = 130
        for i, (kind, page) in enumerate(all_peers):
            if count == 1:
                angle = 0.0
            else:
                angle = 2 * math.pi * i / count
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            self._add_node(page, QPointF(x, y), is_center=False)
            pen = QPen(QColor("#34495e"), 1.5)
            if kind == "back":
                pen.setStyle(Qt.PenStyle.DashLine)
            line = QGraphicsLineItem(center.x(), center.y(), x, y)
            line.setPen(pen)
            line.setZValue(-1)
            self.scene.addItem(line)
        rect = self.scene.itemsBoundingRect().adjusted(-30, -30, 30, 30)
        self.scene.setSceneRect(rect)
        self.view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _add_node(self, page: str, pos: QPointF, is_center: bool) -> None:
        node = _PageNode(page, pos.x(), pos.y(), is_center, self._on_navigate)
        self.scene.addItem(node)
        self._nodes[page] = node
        label = QGraphicsSimpleTextItem(page.rsplit(":", 1)[-1])
        f = QFont()
        f.setPointSize(9)
        label.setFont(f)
        br = label.boundingRect()
        label.setPos(pos.x() - br.width() / 2, pos.y() + NODE_RADIUS + 2)
        self.scene.addItem(label)
