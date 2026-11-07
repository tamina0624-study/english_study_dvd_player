"""Application-local colors and styling for the study player."""
from PySide6.QtGui import QColor, QPalette, QPainter, QIcon, QFont, QFontMetrics, QPen, QPixmap
from PySide6.QtCore import Qt, QRect, QSize, QByteArray
from PySide6.QtWidgets import QStyledItemDelegate, QStyle
from PySide6.QtSvg import QSvgRenderer


def operation_icon(name):
    paths = {
        "字幕を読み込む": '<path d="M3 7V4h6l3 3h9v3M3 8h18l-3 12H3z"/>',
        "DVD字幕を取得": '<path d="M20 8a8 8 0 1 0 0 8M20 3v5h-5"/>',
        "Subtitle EditでOCR": '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M8 8h8m-4 0v9"/>',
        "Subtitle Editで編集": '<path d="m4 20 4-1L20 7l-3-3L5 16zM14 7l3 3M4 20l4-1-3-3"/>',
        "字幕取得を中止": '<rect x="3" y="3" width="18" height="18" rx="5"/><path d="m9 9 6 6m0-6-6 6"/>',
        "言語不明トラックを指定": '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
        "現在の字幕へ追従": '<circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3"/>',
    }
    body = paths.get(name)
    if not body:
        return None
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
           '<g fill="none" stroke="#c3d0e2" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
           + body + '</g></svg>')
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    return QIcon(pixmap)


class SubtitleDelegate(QStyledItemDelegate):
    """Keep large text readable independently of native item padding and elision."""
    def sizeHint(self, option, index):
        body = index.data(Qt.ItemDataRole.UserRole + 2)
        if body is None:
            return super().sizeHint(option, index)
        width = max(240, self.parent().viewport().width())
        font = index.data(Qt.ItemDataRole.FontRole) or option.font
        bounds = QFontMetrics(font).boundingRect(QRect(0, 0, width - 34, 10000),
                                                Qt.TextFlag.TextWordWrap, body)
        return QSize(width - 2, bounds.height() + 54)

    def paint(self, painter, option, index):
        body = index.data(Qt.ItemDataRole.UserRole + 2)
        active = index.data(Qt.ItemDataRole.BackgroundRole)
        active = active is not None and active.color().alpha() > 0
        language = index.data(Qt.ItemDataRole.UserRole)[0]
        rect = option.rect.adjusted(2, 3, -3, -3)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#75cdbb" if active or option.state & QStyle.StateFlag.State_Selected else "#2b3b50")))
        painter.setBrush(QColor("#204c53" if active else "#1b2839" if language == "en" else "#182333"))
        painter.drawRoundedRect(rect, 9, 9)
        if active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#75dcc7"))
            painter.drawRoundedRect(QRect(rect.left() + 2, rect.top() + 8, 4, rect.height() - 16), 2, 2)
        if body is None:
            # Paint image rows here too: stylesheet item painting can hide the
            # BackgroundRole used to mark the current playback position.
            icon = index.data(Qt.ItemDataRole.DecorationRole)
            label_rect = rect.adjusted(13, 6, -12, -6)
            if icon is not None:
                icon_size = icon.actualSize(option.decorationSize)
                icon_rect = QRect(label_rect.left(), rect.center().y() - icon_size.height() // 2,
                                  icon_size.width(), icon_size.height())
                icon.paint(painter, icon_rect)
                label_rect.setLeft(icon_rect.right() + 10)
            painter.setFont(option.font)
            painter.setPen(QColor("#f4fffc" if active else "#c8d6e8"))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                             index.data(Qt.ItemDataRole.DisplayRole))
            painter.restore()
            return
        font = QFont(option.font)
        font.setPointSize(9)
        painter.setFont(font)
        painter.setPen(QColor("#a5e5d9" if active else "#8fa8c3"))
        painter.drawText(rect.adjusted(13, 9, -12, -9), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                         index.data(Qt.ItemDataRole.DisplayRole).split("\n", 1)[0])
        painter.setFont(index.data(Qt.ItemDataRole.FontRole) or option.font)
        painter.setPen(QColor("#f4fffc" if active else "#c8d6e8"))
        painter.drawText(rect.adjusted(13, 30, -13, -10), Qt.TextFlag.TextWordWrap, body)
        painter.restore()


def tint_icon(icon, color="#c3d0e2"):
    pixmap = icon.pixmap(24, 24)
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()
    return QIcon(pixmap)


def apply_theme(window):
    palette = window.palette()
    for role, color in (
        (QPalette.ColorRole.Window, "#101722"),
        (QPalette.ColorRole.WindowText, "#e5edf8"),
        (QPalette.ColorRole.Base, "#151f2d"),
        (QPalette.ColorRole.AlternateBase, "#1b2839"),
        (QPalette.ColorRole.Text, "#e5edf8"),
        (QPalette.ColorRole.Button, "#233247"),
        (QPalette.ColorRole.ButtonText, "#e5edf8"),
        (QPalette.ColorRole.Highlight, "#204c53"),
        (QPalette.ColorRole.HighlightedText, "#f3fffc"),
        (QPalette.ColorRole.ToolTipBase, "#26364b"),
        (QPalette.ColorRole.ToolTipText, "#eef5ff"),
    ):
        palette.setColor(role, QColor(color))
    window.setPalette(palette)
    window.setStyleSheet(STYLE)


STYLE = """
QMainWindow, QWidget#appRoot { background: #101722; color: #e5edf8; }
QWidget { color: #e5edf8; font-family: 'Yu Gothic UI', 'Segoe UI', sans-serif; font-size: 13px; }
QLabel { color: #e5edf8; background: transparent; }
QLabel#brandTitle { font-size: 23px; font-weight: 700; letter-spacing: 2px; }
QLabel#brandSubtitle { color: #8fa2ba; font-size: 12px; }
QLabel#brandMark { background: #75dcc7; color: #10252a; border-radius: 12px;
                  font-size: 21px; font-weight: 700; padding: 9px 14px; }
QLabel#languageBadge { color: #8fe5d3; background: #1b3339; border: 1px solid #2b5359;
                      padding: 5px 12px; border-radius: 12px; font-size: 11px; font-weight: 600; }
QLabel#sectionTitle { color: #c9d6e8; font-weight: 600; font-size: 14px; }
QLabel#sectionHint { color: #7e91aa; font-size: 11px; }
QLabel#subtitleStatus { color: #91a5bf; font-size: 11px; padding: 7px 3px; }
QLabel#coverageStatus { color: #efc181; font-size: 11px; }
QLabel#timeDisplay { font-family: 'Consolas', monospace; color: #adc0d8; font-size: 12px; }
QFrame#sourceBar, QFrame#transportBar { background: #182332; border: 1px solid #27364a;
                                      border-radius: 12px; }
QFrame#videoCard, QFrame#subtitleCard { background: #151f2d; border: 1px solid #27364a;
                                      border-radius: 14px; }
QFrame#videoSurface { background: #070c12; border: none; border-radius: 6px; }
QPushButton { background: #243348; color: #d7e3f2; border: 1px solid #32445c;
              border-radius: 8px; padding: 8px 13px; min-height: 18px; }
QPushButton:hover { background: #30435c; border-color: #4e6989; }
QPushButton:pressed { background: #1c2c40; }
QPushButton:focus { border: 1px solid #8fe5d3; }
QPushButton:disabled { background: #1b2635; color: #53667f; border-color: #263548; }
QPushButton[role="primary"] { background: #75dcc7; color: #10252a; border-color: #75dcc7; font-weight: 700; }
QPushButton[role="primary"]:hover { background: #95ead9; border-color: #95ead9; }
QPushButton[role="primary"]:pressed { background: #50bfa9; }
QPushButton[role="primary"]:disabled { background: #284944; color: #678b84; border-color: #34534d; }
QPushButton[role="icon"] { padding: 5px; border-color: transparent; background: transparent; }
QPushButton[role="icon"]:hover { background: #2d4159; border-color: #49637e; }
QPushButton[role="icon"]:focus { border-color: #8fe5d3; }
QPushButton[role="icon"]:checked { background: #204c53; border-color: #75dcc7; }
QComboBox { color: #d7e3f2; background: #101b2a; border: 1px solid #32445c;
            border-radius: 7px; padding: 7px 10px; min-height: 18px; }
QComboBox:hover, QComboBox:focus { border-color: #75bfb8; }
QComboBox:disabled { color: #53667f; border-color: #27364a; }
QComboBox::drop-down { width: 24px; border: none; }
QComboBox QAbstractItemView { color: #e5edf8; background: #1d2b3e;
                             selection-background-color: #28545b; border: 1px solid #3d526d; padding: 5px; }
QListWidget { background: transparent; border: none; outline: none; padding: 2px; }
QListWidget::item { border: 1px solid #2b3b50; border-radius: 9px; margin: 3px 1px;
                    padding: 8px 10px; }
QListWidget::item:hover { border-color: #52758a; }
QListWidget::item:selected { border: 1px solid #79cfc0; }
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 14px; }
QSlider::groove:horizontal { height: 5px; background: #34465e; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #75dcc7; border-radius: 2px; }
QSlider::handle:horizontal { width: 13px; height: 13px; margin: -5px 0;
                            background: #d4fff4; border: 2px solid #75dcc7; border-radius: 8px; }
QSlider::handle:horizontal:hover { background: white; border-color: #a4ffea; }
QSlider::groove:horizontal:disabled { background: #27364a; }
QSlider::sub-page:horizontal:disabled { background: #365852; }
QSlider::handle:horizontal:disabled { background: #4b6470; border-color: #365852; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 3px 0; }
QScrollBar::handle:vertical { background: #3d536d; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #5d7a96; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QMenuBar { background: #101722; color: #8fa2ba; padding: 2px 12px; }
QMenuBar::item:selected { background: #243348; border-radius: 4px; }
QMenu { background: #1b293b; color: #e5edf8; border: 1px solid #3a4f69; padding: 5px; }
QMenu::item { padding: 7px 25px; border-radius: 4px; }
QMenu::item:selected { background: #30545b; }
QMenu::item:disabled { color: #60758f; }
QStatusBar { background: #101722; color: #8298b3; font-size: 11px; padding: 2px 10px; }
QStatusBar::item { border: none; }
QToolTip { background: #26364b; color: #eef5ff; border: 1px solid #4b647f; padding: 7px; }
"""
