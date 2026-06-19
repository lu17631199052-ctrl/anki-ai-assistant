"""Browser search panel — embedded web search docked on the right side.

Supports: Baidu, Google, Bilibili, YouTube.
Uses QWebEngineView when available, falls back to system browser.
"""

import os
import webbrowser
from typing import Optional
from urllib.parse import quote

from aqt.qt import (
    QDockWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QWidget,
    Qt,
    QSize,
    QIcon,
    QUrl,
)
from aqt import mw
from aqt.utils import tooltip

# ── Try QWebEngineView (available in both PyQt5 and PyQt6 via Anki) ──
try:
    from aqt.qt import QWebEngineView  # type: ignore
    HAS_WEBENGINE = True
except ImportError:
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView  # type: ignore
        HAS_WEBENGINE = True
    except ImportError:
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView  # type: ignore
            HAS_WEBENGINE = True
        except ImportError:
            HAS_WEBENGINE = False

# ── singleton references ──────────────────────────────────────────────
_browser_dock: Optional[QDockWidget] = None
_browser_panel: Optional["BrowserSearchPanel"] = None

_MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "media")

# ── search engine definitions ─────────────────────────────────────────

SEARCH_ENGINES = [
    {
        "name": "百度",
        "url": "https://www.baidu.com/s?wd={query}",
        "color": "#4E6EF2",
        "hover_color": "#3B54D4",
    },
    {
        "name": "Google",
        "url": "https://www.google.com/search?q={query}",
        "color": "#4285F4",
        "hover_color": "#3367D6",
    },
    {
        "name": "Bing",
        "url": "https://www.bing.com/search?q={query}",
        "color": "#00809D",
        "hover_color": "#006B84",
    },
    {
        "name": "B站",
        "url": "https://search.bilibili.com/all?keyword={query}",
        "color": "#FB7299",
        "hover_color": "#E25D80",
    },
    {
        "name": "YouTube",
        "url": "https://www.youtube.com/results?search_query={query}",
        "color": "#FF0000",
        "hover_color": "#CC0000",
    },
]


# ═══════════════════════════════════════════════════════════════════════
# BrowserSearchPanel
# ═══════════════════════════════════════════════════════════════════════

class BrowserSearchPanel(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_url = ""
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Top bar (search row + engine buttons) ──────────────────
        top_bar = QWidget()
        top_bar.setStyleSheet("background: #F5F6F8; border-bottom: 1px solid #E0E0E0;")
        tb_layout = QVBoxLayout(top_bar)
        tb_layout.setContentsMargins(8, 6, 8, 6)
        tb_layout.setSpacing(6)

        # Search input row
        search_row = QHBoxLayout()
        search_row.setSpacing(4)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("输入搜索关键词... (Enter 搜索)")
        self._search_input.setStyleSheet(
            "QLineEdit { font-size: 13px; border: 1px solid #D0D5DD; "
            "border-radius: 6px; padding: 6px 10px; background: #FFF; } "
            "QLineEdit:focus { border-color: #4A90D9; }"
        )
        self._search_input.returnPressed.connect(lambda: self._search("Google"))
        search_row.addWidget(self._search_input, 1)

        search_btn = QPushButton("搜索")
        search_btn.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 6px 14px; border: none; "
            "border-radius: 6px; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #5B9BD5, stop:1 #4A90D9); color: white; font-weight: bold; } "
            "QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #4A90D9, stop:1 #357ABD); }"
        )
        search_btn.clicked.connect(lambda: self._search("Google"))
        search_row.addWidget(search_btn)
        tb_layout.addLayout(search_row)

        # Engine shortcut buttons
        engine_row = QHBoxLayout()
        engine_row.setSpacing(6)

        engine_label = QLabel("搜索引擎:")
        engine_label.setStyleSheet("font-size: 11px; color: #888; background: transparent;")
        engine_row.addWidget(engine_label)

        for engine in SEARCH_ENGINES:
            btn = QPushButton(engine["name"])
            btn.setToolTip(f"在 {engine['name']} 搜索")
            btn.setStyleSheet(
                f"QPushButton {{ font-size: 11px; padding: 3px 10px; "
                f"border: 1px solid {engine['color']}; border-radius: 4px; "
                f"background: #FFF; color: {engine['color']}; font-weight: bold; }} "
                f"QPushButton:hover {{ background: {engine['color']}; color: white; }}"
            )
            btn.clicked.connect(self._make_engine_handler(engine))
            engine_row.addWidget(btn)

        # Open in external browser button
        ext_btn = QPushButton("↗ 外部打开")
        ext_btn.setToolTip("在系统浏览器中打开当前页面")
        ext_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 3px 10px; "
            "border: 1px solid #D0D5DD; border-radius: 4px; "
            "background: #FFF; color: #888; } "
            "QPushButton:hover { background: #F5F7FA; border-color: #4A90D9; color: #4A90D9; }"
        )
        ext_btn.clicked.connect(self._open_external)
        engine_row.addWidget(ext_btn)

        engine_row.addStretch()
        tb_layout.addLayout(engine_row)

        layout.addWidget(top_bar)

        # ── Web view or fallback ───────────────────────────────────
        if HAS_WEBENGINE:
            self._web_view = QWebEngineView()
            self._web_view.setStyleSheet("border: none; background: #FFF;")
            # Load default page immediately so it's not blank
            self._web_view.load(QUrl("https://www.google.com"))
            self._current_url = "https://www.google.com"
            layout.addWidget(self._web_view, 1)
        else:
            # Fallback: label with instructions
            fallback = QLabel(
                "<div style='text-align:center; padding:40px; color:#888;'>"
                "<p style='font-size:16px;'>🔍 浏览器搜索</p>"
                "<p style='font-size:13px;'>输入关键词后点击搜索引擎按钮</p>"
                "<p style='font-size:12px;'>将在系统默认浏览器中打开结果</p>"
                "</div>"
            )
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(fallback, 1)
            self._web_view = None

    def _make_engine_handler(self, engine: dict):
        """Return a click handler for an engine button."""
        def handler():
            self._search(engine["name"])
        return handler

    def _search(self, engine_name: str) -> None:
        """Perform a search with the given engine."""
        query = self._search_input.text().strip()
        if not query:
            tooltip("请输入搜索关键词")
            return

        # Find engine config
        engine = None
        for e in SEARCH_ENGINES:
            if e["name"] == engine_name:
                engine = e
                break
        if engine is None:
            engine = SEARCH_ENGINES[1]  # default to Google

        url = engine["url"].format(query=quote(query))

        if self._web_view is not None:
            self._web_view.load(QUrl(url))
            self._current_url = url
            tooltip(f"已在 {engine_name} 搜索: {query}")
        else:
            webbrowser.open(url)
            tooltip(f"已在系统浏览器打开 {engine_name} 搜索: {query}")

    def _open_external(self) -> None:
        """Open current page in system browser."""
        if self._web_view is not None and self._current_url:
            webbrowser.open(self._current_url)
            tooltip("已在系统浏览器打开")
        elif self._search_input.text().strip():
            query = self._search_input.text().strip()
            webbrowser.open(f"https://www.google.com/search?q={quote(query)}")
            tooltip("已在系统浏览器打开 Google 搜索")


# ═══════════════════════════════════════════════════════════════════════
# Dock management
# ═══════════════════════════════════════════════════════════════════════

def _ensure_browser_dock() -> QDockWidget:
    """Create (or return existing) browser search dock on the right."""
    global _browser_dock, _browser_panel

    if _browser_dock is not None:
        return _browser_dock

    _browser_dock = QDockWidget("浏览器搜索", mw)
    _browser_dock.setObjectName("ai_assistant_browser_search")
    _browser_dock.setAllowedAreas(
        Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
    )
    _browser_dock.setMinimumWidth(300)

    # Custom title bar
    title_bar = QWidget()
    title_bar.setStyleSheet("background: #F5F6F8;")
    tb_layout = QHBoxLayout(title_bar)
    tb_layout.setContentsMargins(12, 4, 8, 4)
    tb_layout.setSpacing(4)

    title_label = QLabel("🌐 浏览器搜索")
    title_label.setStyleSheet(
        "font-size: 12px; font-weight: bold; color: #555; background: transparent;"
    )
    tb_layout.addWidget(title_label)
    tb_layout.addStretch()

    close_icon = QIcon(os.path.join(_MEDIA_DIR, "close.svg"))
    close_btn = QPushButton()
    close_btn.setIcon(close_icon)
    close_btn.setIconSize(QSize(16, 16))
    close_btn.setFixedSize(26, 26)
    close_btn.setToolTip("关闭面板")
    close_btn.setStyleSheet(
        "QPushButton { border: none; border-radius: 13px; "
        "background: #E0E0E0; } "
        "QPushButton:hover { background: #C0C0C0; }"
    )
    close_btn.clicked.connect(lambda: _browser_dock.hide() if _browser_dock else None)
    tb_layout.addWidget(close_btn)
    _browser_dock.setTitleBarWidget(title_bar)

    _browser_panel = BrowserSearchPanel()
    _browser_dock.setWidget(_browser_panel)

    # Track visibility → update launcher buttons
    _browser_dock.visibilityChanged.connect(
        lambda v: _update_launcher_buttons() if v or True else None
    )

    mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, _browser_dock)
    return _browser_dock


def _update_launcher_buttons() -> None:
    """Notify left_sidebar to refresh button states."""
    try:
        from .left_sidebar import _update_launcher_buttons as _update
        _update()
    except Exception:
        pass


def _toggle_browser_search() -> None:
    """Toggle the browser search dock."""
    dock = _ensure_browser_dock()
    if dock.isVisible():
        dock.hide()
    else:
        dock.show()
        dock.raise_()
        # Focus search input
        if _browser_panel is not None:
            _browser_panel._search_input.setFocus()
    _update_launcher_buttons()


def _open_browser_search() -> None:
    """Open the browser search dock (non-toggle)."""
    dock = _ensure_browser_dock()
    dock.show()
    dock.raise_()
    if _browser_panel is not None:
        _browser_panel._search_input.setFocus()
    _update_launcher_buttons()
