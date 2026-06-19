"""Browser search panel — embedded web search docked on the right side.

Uses QWebEngineView to load real search engine pages directly in the panel.
Falls back to a local welcome page if WebEngine is unavailable.
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
    QTextBrowser,
    Qt,
    QSize,
    QIcon,
    QUrl,
)
from aqt import mw
from aqt.utils import tooltip

# ── Try to get a working QWebEngineView ───────────────────────────
# Anki 25.09 uses PyQt 6.9.1 — import directly for best compatibility.
_HAS_WEBENGINE = False
_QWebEngineView = None
_QWebEngineProfile = None

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView as _QV  # type: ignore
    from PyQt6.QtWebEngineCore import QWebEngineProfile as _QP  # type: ignore
    _QWebEngineView = _QV
    _QWebEngineProfile = _QP
    _HAS_WEBENGINE = True
except ImportError:
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView as _QV  # type: ignore
        _QWebEngineView = _QV
        _HAS_WEBENGINE = True
    except ImportError:
        try:
            from aqt.qt import QWebEngineView as _QV  # type: ignore
            _QWebEngineView = _QV
            _HAS_WEBENGINE = True
        except ImportError:
            pass

# ── singleton references ──────────────────────────────────────────────
_browser_dock: Optional[QDockWidget] = None
_browser_panel: Optional["BrowserSearchPanel"] = None

_MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "media")

# ── search engine definitions ─────────────────────────────────────────

SEARCH_ENGINES = [
    {
        "name": "百度",
        "url": "https://www.baidu.com/s?wd={query}",
        "home": "https://www.baidu.com",
        "color": "#4E6EF2",
    },
    {
        "name": "Google",
        "url": "https://www.google.com/search?q={query}",
        "home": "https://www.google.com",
        "color": "#4285F4",
    },
    {
        "name": "Bing",
        "url": "https://www.bing.com/search?q={query}",
        "home": "https://www.bing.com",
        "color": "#00809D",
    },
    {
        "name": "B站",
        "url": "https://search.bilibili.com/all?keyword={query}",
        "home": "https://www.bilibili.com",
        "color": "#FB7299",
    },
    {
        "name": "YouTube",
        "url": "https://www.youtube.com/results?search_query={query}",
        "home": "https://www.youtube.com",
        "color": "#FF0000",
    },
]


def _build_welcome_html() -> str:
    """Fallback welcome page when QWebEngineView is unavailable."""
    cards = ""
    for e in SEARCH_ENGINES:
        cards += f"""
        <a href='{e["home"]}' style='text-decoration:none;'>
        <div style='display:flex;align-items:center;gap:10px;
             background:#FFF;border-radius:8px;padding:10px 14px;margin-bottom:8px;
             border-left:3px solid {e["color"]};box-shadow:0 1px 3px rgba(0,0,0,0.06);'>
            <span style='font-size:14px;font-weight:600;color:{e["color"]};'>{e["name"]}</span>
            <span style='flex:1;'></span>
            <span style='color:#CCC;'>→</span>
        </div></a>"""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:-apple-system,"PingFang SC",sans-serif;background:#FAFBFC;padding:24px 20px;}}
h2{{font-size:18px;color:#555;text-align:center;margin-bottom:20px;}}
.hint{{margin-top:20px;padding:12px;background:#FFF8E1;border-radius:8px;font-size:12px;color:#8D6E00;text-align:center;}}
</style></head><body>
<h2>🌐 浏览器搜索</h2>
{cards}
<div class='hint'>💡 <b>提示：</b>点击引擎打开首页，搜索结果在系统浏览器中显示</div>
</body></html>"""


# ═══════════════════════════════════════════════════════════════════════
# BrowserSearchPanel
# ═══════════════════════════════════════════════════════════════════════

class BrowserSearchPanel(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._default_engine = self._get_default_engine()
        self._current_url = ""
        self._web_view = None
        self._fallback_browser = None
        self._build_ui()

    @staticmethod
    def _get_default_engine() -> str:
        try:
            from ..config import get_config
            engine = get_config().get("default_search_engine", "Google")
            for e in SEARCH_ENGINES:
                if e["name"] == engine:
                    return engine
        except Exception:
            pass
        return "Google"

    @staticmethod
    def _get_search_url(engine_name: str, query: str) -> str:
        for e in SEARCH_ENGINES:
            if e["name"] == engine_name:
                return e["url"].format(query=quote(query))
        return f"https://www.google.com/search?q={quote(query)}"

    @staticmethod
    def _get_home_url(engine_name: str) -> str:
        for e in SEARCH_ENGINES:
            if e["name"] == engine_name:
                return e["home"]
        return "https://www.google.com"

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Top bar ────────────────────────────────────────────────
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
        self._search_input.returnPressed.connect(
            lambda: self._search(self._default_engine)
        )
        search_row.addWidget(self._search_input, 1)

        search_btn = QPushButton("搜索")
        search_btn.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 6px 14px; border: none; "
            "border-radius: 6px; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #5B9BD5, stop:1 #4A90D9); color: white; font-weight: bold; } "
            "QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #4A90D9, stop:1 #357ABD); }"
        )
        search_btn.clicked.connect(lambda: self._search(self._default_engine))
        search_row.addWidget(search_btn)
        tb_layout.addLayout(search_row)

        # Engine buttons row
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

        # Home button — loads the default engine's homepage in the panel
        home_btn = QPushButton("🏠 首页")
        home_btn.setToolTip(f"加载 {self._default_engine} 首页")
        home_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 3px 10px; "
            "border: 1px solid #D0D5DD; border-radius: 4px; "
            "background: #FFF; color: #888; } "
            "QPushButton:hover { background: #F5F7FA; border-color: #4A90D9; color: #4A90D9; }"
        )
        home_btn.clicked.connect(self._load_homepage)
        engine_row.addWidget(home_btn)

        # External open button
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
        if _HAS_WEBENGINE:
            self._web_view = _QWebEngineView()
            self._web_view.setStyleSheet("border: none; background: #FFF;")
            # Set zoom after page loads (more reliable)
            self._web_view.loadFinished.connect(self._on_load_finished)
            # Load the default engine's homepage
            home_url = self._get_home_url(self._default_engine)
            self._web_view.load(QUrl(home_url))
            self._current_url = home_url
            layout.addWidget(self._web_view, 1)
        else:
            # Fallback: local welcome page
            self._fallback_browser = QTextBrowser()
            self._fallback_browser.setOpenExternalLinks(True)
            self._fallback_browser.setStyleSheet(
                "QTextBrowser { border: none; background: #FAFBFC; }"
            )
            self._fallback_browser.setHtml(_build_welcome_html())
            layout.addWidget(self._fallback_browser, 1)

    def _on_load_finished(self, ok: bool) -> None:
        """Called when a page finishes loading in the web view."""
        if ok and self._web_view is not None:
            self._web_view.setZoomFactor(0.75)

    def _load_homepage(self) -> None:
        """Load the default engine's homepage in the panel."""
        home_url = self._get_home_url(self._default_engine)
        if self._web_view is not None:
            self._web_view.load(QUrl(home_url))
            self._current_url = home_url
            tooltip(f"已加载 {self._default_engine} 首页")
        else:
            webbrowser.open(home_url)
            tooltip(f"已在系统浏览器打开 {self._default_engine}")

    def _make_engine_handler(self, engine: dict):
        def handler():
            self._search(engine["name"])
        return handler

    def _search(self, engine_name: str) -> None:
        """Search — load results in panel if web view available, else system browser."""
        query = self._search_input.text().strip()
        if not query:
            tooltip("请输入搜索关键词")
            return

        url = self._get_search_url(engine_name, query)

        if self._web_view is not None:
            self._web_view.load(QUrl(url))
            self._current_url = url
            tooltip(f"已在 {engine_name} 搜索: {query}")
        else:
            webbrowser.open(url)
            tooltip(f"已在系统浏览器用 {engine_name} 搜索: {query}")

    def _open_external(self) -> None:
        """Open current page in system browser."""
        if self._current_url:
            webbrowser.open(self._current_url)
            tooltip("已在系统浏览器打开")
        elif self._search_input.text().strip():
            query = self._search_input.text().strip()
            url = self._get_search_url(self._default_engine, query)
            webbrowser.open(url)
            tooltip(f"已在系统浏览器打开 {self._default_engine} 搜索")


# ═══════════════════════════════════════════════════════════════════════
# Dock management
# ═══════════════════════════════════════════════════════════════════════

def _ensure_browser_dock() -> QDockWidget:
    global _browser_dock, _browser_panel

    if _browser_dock is not None:
        return _browser_dock

    _browser_dock = QDockWidget("浏览器搜索", mw)
    _browser_dock.setObjectName("ai_assistant_browser_search")
    _browser_dock.setAllowedAreas(
        Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
    )
    _browser_dock.setMinimumWidth(420)

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

    _browser_dock.visibilityChanged.connect(
        lambda v: _update_launcher_buttons() if v or True else None
    )

    mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, _browser_dock)
    return _browser_dock


def _update_launcher_buttons() -> None:
    try:
        from .left_sidebar import _update_launcher_buttons as _update
        _update()
    except Exception:
        pass


def _toggle_browser_search() -> None:
    dock = _ensure_browser_dock()
    if dock.isVisible():
        dock.hide()
    else:
        dock.show()
        dock.raise_()
        if _browser_panel is not None:
            _browser_panel._search_input.setFocus()
    _update_launcher_buttons()


def _open_browser_search() -> None:
    dock = _ensure_browser_dock()
    dock.show()
    dock.raise_()
    if _browser_panel is not None:
        _browser_panel._search_input.setFocus()
    _update_launcher_buttons()
