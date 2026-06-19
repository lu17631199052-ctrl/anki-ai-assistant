"""Browser search panel — search bar + engine shortcuts, opens in system browser.

Shows a styled local welcome page in the panel.  Searches always open in
the system default web browser for maximum reliability and full browser UI.
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
        "icon": "🔵",
        "desc": "中文搜索",
    },
    {
        "name": "Google",
        "url": "https://www.google.com/search?q={query}",
        "home": "https://www.google.com",
        "color": "#4285F4",
        "icon": "🌐",
        "desc": "全球搜索",
    },
    {
        "name": "Bing",
        "url": "https://www.bing.com/search?q={query}",
        "home": "https://www.bing.com",
        "color": "#00809D",
        "icon": "🔍",
        "desc": "微软搜索",
    },
    {
        "name": "B站",
        "url": "https://search.bilibili.com/all?keyword={query}",
        "home": "https://www.bilibili.com",
        "color": "#FB7299",
        "icon": "📺",
        "desc": "视频搜索",
    },
    {
        "name": "YouTube",
        "url": "https://www.youtube.com/results?search_query={query}",
        "home": "https://www.youtube.com",
        "color": "#FF0000",
        "icon": "▶️",
        "desc": "视频搜索",
    },
]


def _build_welcome_html() -> str:
    """Build a styled welcome page showing all search engines."""
    cards = ""
    for e in SEARCH_ENGINES:
        cards += f"""
        <div class='engine-card' onclick='openUrl("{e["home"]}")'
             style='border-left: 3px solid {e["color"]};'>
            <span class='engine-icon'>{e["icon"]}</span>
            <div class='engine-info'>
                <span class='engine-name' style='color:{e["color"]};'>{e["name"]}</span>
                <span class='engine-desc'>{e["desc"]}</span>
            </div>
            <span class='engine-arrow'>→</span>
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    font-family: -apple-system, "Segoe UI", "PingFang SC", sans-serif;
    background: #FAFBFC; color: #333;
    padding: 24px 20px;
}}
h2 {{
    font-size: 18px; color: #555; margin-bottom: 6px;
    text-align: center; font-weight: 600;
}}
.subtitle {{
    font-size: 12px; color: #999; text-align: center;
    margin-bottom: 20px;
}}
.engine-card {{
    display: flex; align-items: center; gap: 10px;
    background: #FFF; border-radius: 8px;
    padding: 10px 14px; margin-bottom: 8px;
    cursor: pointer; transition: all 0.15s;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}}
.engine-card:hover {{
    background: #F0F4FF; box-shadow: 0 2px 8px rgba(0,0,0,0.10);
    transform: translateX(2px);
}}
.engine-icon {{ font-size: 24px; }}
.engine-info {{ display: flex; flex-direction: column; flex: 1; }}
.engine-name {{ font-size: 14px; font-weight: 600; }}
.engine-desc {{ font-size: 11px; color: #999; }}
.engine-arrow {{ font-size: 16px; color: #CCC; }}
.hint {{
    margin-top: 20px; padding: 12px; background: #FFF8E1;
    border-radius: 8px; font-size: 12px; color: #8D6E00;
    text-align: center; line-height: 1.6;
}}
</style></head><body>
<h2>🌐 浏览器搜索</h2>
<p class='subtitle'>输入关键词后按 Enter 或点击下方引擎</p>
{cards}
<div class='hint'>
💡 <b>提示：</b>搜索结果将在<b>系统默认浏览器</b>中打开<br>
在设置中可以修改默认搜索引擎
</div>
</body></html>"""


# ═══════════════════════════════════════════════════════════════════════
# BrowserSearchPanel
# ═══════════════════════════════════════════════════════════════════════

class BrowserSearchPanel(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._default_engine = self._get_default_engine()
        self._build_ui()

    @staticmethod
    def _get_default_engine() -> str:
        """Read the user's preferred default search engine from config."""
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
        """Get search URL for an engine and query."""
        for e in SEARCH_ENGINES:
            if e["name"] == engine_name:
                return e["url"].format(query=quote(query))
        # Fallback
        return f"https://www.google.com/search?q={quote(query)}"

    @staticmethod
    def _get_home_url(engine_name: str) -> str:
        """Get homepage URL for an engine."""
        for e in SEARCH_ENGINES:
            if e["name"] == engine_name:
                return e["home"]
        return "https://www.google.com"

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

        # Engine shortcut buttons
        engine_row = QHBoxLayout()
        engine_row.setSpacing(6)

        engine_label = QLabel("搜索引擎:")
        engine_label.setStyleSheet("font-size: 11px; color: #888; background: transparent;")
        engine_row.addWidget(engine_label)

        for engine in SEARCH_ENGINES:
            btn = QPushButton(engine["name"])
            btn.setToolTip(f"在 {engine['name']} 搜索（系统浏览器打开）")
            btn.setStyleSheet(
                f"QPushButton {{ font-size: 11px; padding: 3px 10px; "
                f"border: 1px solid {engine['color']}; border-radius: 4px; "
                f"background: #FFF; color: {engine['color']}; font-weight: bold; }} "
                f"QPushButton:hover {{ background: {engine['color']}; color: white; }}"
            )
            btn.clicked.connect(self._make_engine_handler(engine))
            engine_row.addWidget(btn)

        engine_row.addStretch()
        tb_layout.addLayout(engine_row)

        layout.addWidget(top_bar)

        # ── Welcome page (local HTML, no external loading needed) ───
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)  # We handle links ourselves
        self._browser.setStyleSheet(
            "QTextBrowser { border: none; background: #FAFBFC; }"
        )
        self._browser.setHtml(_build_welcome_html())
        # Intercept link clicks → open in system browser
        self._browser.anchorClicked.connect(self._on_welcome_link)
        layout.addWidget(self._browser, 1)

    def _on_welcome_link(self, url: QUrl) -> None:
        """Open links from the welcome page in system browser."""
        webbrowser.open(url.toString())
        tooltip("已在系统浏览器打开")

    def _make_engine_handler(self, engine: dict):
        """Return a click handler for an engine button."""
        def handler():
            self._search(engine["name"])
        return handler

    def _search(self, engine_name: str) -> None:
        """Search with the given engine — always opens system browser."""
        query = self._search_input.text().strip()
        if not query:
            tooltip("请输入搜索关键词")
            return

        url = self._get_search_url(engine_name, query)
        webbrowser.open(url)
        tooltip(f"已在系统浏览器用 {engine_name} 搜索: {query}")


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
    _browser_dock.setMinimumWidth(380)

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
