"""Browser search panel — embedded web search docked on the right side.

Uses QWebEngineView with a dedicated persistent profile (same approach as
Synapse Pro), so external web pages render correctly in Anki's environment.
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
    QSizePolicy,
    Qt,
    QSize,
    QIcon,
    QUrl,
)
from aqt import mw
from aqt.utils import tooltip

# ── QWebEngine imports (PyQt6 direct, same as Synapse Pro) ───────────
_HAS_WEBENGINE = False
_QWebEngineView = None
_QWebEngineProfile = None
_QWebEnginePage = None
_QWebEngineSettings = None

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView as _QV  # type: ignore
    from PyQt6.QtWebEngineCore import (
        QWebEngineProfile as _QP,
        QWebEnginePage as _QPage,
        QWebEngineSettings as _QSettings,
    )
    _QWebEngineView = _QV
    _QWebEngineProfile = _QP
    _QWebEnginePage = _QPage
    _QWebEngineSettings = _QSettings
    _HAS_WEBENGINE = True
except ImportError:
    pass

# ── singleton references ──────────────────────────────────────────────
_browser_dock: Optional[QDockWidget] = None
_browser_panel: Optional["BrowserSearchPanel"] = None
_web_profile: Optional[object] = None  # QWebEngineProfile

_MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "media")
_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROFILE_DIR = os.path.join(_ADDON_DIR, "web_profile")

# ── search engine definitions ─────────────────────────────────────────

SEARCH_ENGINES = [
    {"name": "Google", "url": "https://www.google.com/search?q={query}",
     "home": "https://www.google.com", "color": "#4285F4"},
    {"name": "百度", "url": "https://www.baidu.com/s?wd={query}",
     "home": "https://www.baidu.com", "color": "#4E6EF2"},
    {"name": "Bing", "url": "https://www.bing.com/search?q={query}",
     "home": "https://www.bing.com", "color": "#00809D"},
    {"name": "B站", "url": "https://search.bilibili.com/all?keyword={query}",
     "home": "https://www.bilibili.com", "color": "#FB7299"},
    {"name": "YouTube", "url": "https://www.youtube.com/results?search_query={query}",
     "home": "https://www.youtube.com", "color": "#FF0000"},
]


def _ensure_web_profile():
    """Create a persistent QWebEngineProfile (same pattern as Synapse Pro)."""
    global _web_profile
    if _web_profile is not None:
        return _web_profile
    if not _HAS_WEBENGINE:
        return None
    try:
        os.makedirs(_PROFILE_DIR, exist_ok=True)
        _web_profile = _QWebEngineProfile("anki_ai_browser", mw)
        _web_profile.setPersistentStoragePath(_PROFILE_DIR)
        _web_profile.setPersistentCookiesPolicy(
            _QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
        )
        _web_profile.setHttpCacheType(
            _QWebEngineProfile.HttpCacheType.DiskHttpCache
        )
    except Exception:
        _web_profile = _QWebEngineProfile.defaultProfile()
    return _web_profile


# ═══════════════════════════════════════════════════════════════════════
# BrowserSearchPanel
# ═══════════════════════════════════════════════════════════════════════

class BrowserSearchPanel(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._default_engine = self._get_default_engine()
        self._current_url = ""
        self._web_view = None
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
        tb_layout = QHBoxLayout(top_bar)
        tb_layout.setContentsMargins(8, 5, 8, 5)
        tb_layout.setSpacing(6)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("输入搜索关键词... (Enter 搜索)")
        self._search_input.setStyleSheet(
            "QLineEdit { font-size: 13px; border: 1px solid #D0D5DD; "
            "border-radius: 6px; padding: 5px 10px; background: #FFF; } "
            "QLineEdit:focus { border-color: #4A90D9; }"
        )
        self._search_input.returnPressed.connect(
            lambda: self._search(self._default_engine)
        )
        tb_layout.addWidget(self._search_input, 1)

        search_btn = QPushButton("搜索")
        search_btn.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 5px 12px; border: none; "
            "border-radius: 6px; background: #4A90D9; color: white; font-weight: bold; } "
            "QPushButton:hover { background: #357ABD; }"
        )
        search_btn.clicked.connect(lambda: self._search(self._default_engine))
        tb_layout.addWidget(search_btn)

        # Engine buttons
        for engine in SEARCH_ENGINES:
            btn = QPushButton(engine["name"])
            btn.setToolTip(f"在 {engine['name']} 搜索")
            btn.setStyleSheet(
                f"QPushButton {{ font-size: 11px; padding: 3px 8px; "
                f"border: 1px solid {engine['color']}; border-radius: 4px; "
                f"background: #FFF; color: {engine['color']}; font-weight: bold; }} "
                f"QPushButton:hover {{ background: {engine['color']}; color: white; }}"
            )
            btn.clicked.connect(self._make_engine_handler(engine))
            tb_layout.addWidget(btn)

        tb_layout.addStretch()

        ext_btn = QPushButton("↗ 外部")
        ext_btn.setToolTip("在系统浏览器打开当前页面")
        ext_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 3px 8px; "
            "border: 1px solid #D0D5DD; border-radius: 4px; "
            "background: #FFF; color: #888; } "
            "QPushButton:hover { background: #F5F7FA; border-color: #4A90D9; }"
        )
        ext_btn.clicked.connect(self._open_external)
        tb_layout.addWidget(ext_btn)

        layout.addWidget(top_bar)

        # ── Web view (Synapse Pro pattern) ─────────────────────────
        if _HAS_WEBENGINE:
            profile = _ensure_web_profile()
            self._web_view = _QWebEngineView()
            self._web_view.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )

            # Create page with the dedicated profile
            page = _QWebEnginePage(profile, self._web_view)
            self._web_view.setPage(page)

            # Enable JavaScript, LocalStorage, etc.
            settings = self._web_view.settings()
            try:
                attrs = _QWebEngineSettings.WebAttribute
                settings.setAttribute(attrs.JavascriptEnabled, True)
                settings.setAttribute(attrs.LocalStorageEnabled, True)
                settings.setAttribute(attrs.ScrollAnimatorEnabled, True)
                settings.setAttribute(attrs.PluginsEnabled, False)
                settings.setAttribute(attrs.FullScreenSupportEnabled, True)
            except AttributeError:
                pass

            # Set zoom after page loads
            self._web_view.loadFinished.connect(self._on_load_finished)

            # Load the default engine's homepage
            home_url = self._get_home_url(self._default_engine)
            self._web_view.setUrl(QUrl.fromUserInput(home_url))
            self._current_url = home_url

            layout.addWidget(self._web_view, 1)
        else:
            # Fallback: simple welcome page
            from aqt.qt import QTextBrowser
            fb = QTextBrowser()
            fb.setOpenExternalLinks(True)
            fb.setStyleSheet("QTextBrowser { border: none; background: #FAFBFC; }")
            fb.setHtml(self._fallback_html())
            layout.addWidget(fb, 1)

    def _fallback_html(self) -> str:
        cards = "".join(
            f"<a href='{e['home']}' style='text-decoration:none;'>"
            f"<div style='padding:10px;margin:4px 0;background:#FFF;border-radius:8px;"
            f"border-left:3px solid {e['color']};color:#333;font-size:14px;'>"
            f"{e['name']} →</div></a>"
            for e in SEARCH_ENGINES
        )
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style='font-family:sans-serif;background:#FAFBFC;padding:20px;'>
<h2>🌐 浏览器搜索</h2><p style='color:#888;'>点击搜索引擎在系统浏览器打开</p>
{cards}</body></html>"""

    def _on_load_finished(self, ok: bool) -> None:
        if ok and self._web_view is not None:
            try:
                self._web_view.setZoomFactor(0.75)
            except Exception:
                pass

    def _make_engine_handler(self, engine: dict):
        def handler():
            self._search(engine["name"])
        return handler

    def _search(self, engine_name: str) -> None:
        query = self._search_input.text().strip()
        if not query:
            tooltip("请输入搜索关键词")
            return
        url = self._get_search_url(engine_name, query)
        if self._web_view is not None:
            self._web_view.setUrl(QUrl.fromUserInput(url))
            self._current_url = url
            tooltip(f"已在 {engine_name} 搜索: {query}")
        else:
            webbrowser.open(url)
            tooltip(f"已在系统浏览器用 {engine_name} 搜索: {query}")

    def _open_external(self) -> None:
        if self._current_url:
            webbrowser.open(self._current_url)
            tooltip("已在系统浏览器打开")
        else:
            home = self._get_home_url(self._default_engine)
            webbrowser.open(home)
            tooltip(f"已在系统浏览器打开 {self._default_engine}")


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
