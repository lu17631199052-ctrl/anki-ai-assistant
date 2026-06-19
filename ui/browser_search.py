"""Browser search panel — shows a search-engine-style homepage, opens results in system browser.

Uses local HTML rendered in QTextBrowser (100% reliable, no WebEngine needed).
The welcome page is styled to look like a real search engine homepage.
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
        "name": "Google",
        "url": "https://www.google.com/search?q={query}",
        "color": "#4285F4",
        "logo_text": "Google",
        "logo_colors": ["#4285F4", "#EA4335", "#FBBC05", "#4285F4", "#34A853", "#EA4335"],
    },
    {
        "name": "百度",
        "url": "https://www.baidu.com/s?wd={query}",
        "color": "#4E6EF2",
        "logo_text": "百度",
        "logo_colors": ["#4E6EF2", "#4E6EF2"],
    },
    {
        "name": "Bing",
        "url": "https://www.bing.com/search?q={query}",
        "color": "#00809D",
        "logo_text": "Bing",
        "logo_colors": ["#00809D", "#00809D"],
    },
    {
        "name": "B站",
        "url": "https://search.bilibili.com/all?keyword={query}",
        "color": "#FB7299",
        "logo_text": "哔哩哔哩",
        "logo_colors": ["#FB7299", "#FB7299"],
    },
    {
        "name": "YouTube",
        "url": "https://www.youtube.com/results?search_query={query}",
        "color": "#FF0000",
        "logo_text": "YouTube",
        "logo_colors": ["#FF0000", "#FF0000"],
    },
]


def _google_colored_logo() -> str:
    """Google-style colored logo as HTML spans."""
    letters = [
        ("G", "#4285F4"), ("o", "#EA4335"), ("o", "#FBBC05"),
        ("g", "#4285F4"), ("l", "#34A853"), ("e", "#EA4335"),
    ]
    return "".join(
        f'<span style="color:{c};font-weight:400;">{l}</span>'
        for l, c in letters
    )


def _build_homepage_html(default_engine: str) -> str:
    """Build a search-engine-style homepage for the given engine."""
    homepages = {
        "Google": "https://www.google.com",
        "百度": "https://www.baidu.com",
        "Bing": "https://www.bing.com",
        "B站": "https://www.bilibili.com",
        "YouTube": "https://www.youtube.com",
    }
    home_url = homepages.get(default_engine, "https://www.google.com")

    # Engine tabs at the top
    tabs_html = ""
    for e in SEARCH_ENGINES:
        active = "active" if e["name"] == default_engine else ""
        tabs_html += (
            f'<button class="engine-tab {active}" '
            f'onclick="switchEngine(\'{e["name"]}\')" '
            f'style="border-color:{e["color"]};">'
            f'{e["name"]}</button>'
        )

    # Shortcut links (like Chrome new tab page)
    shortcuts_html = ""
    shortcuts = [
        ("📖", "Wikipedia", "https://www.wikipedia.org"),
        ("📚", "Z-Library", "https://z-lib.io"),
        ("🧠", "AnkiWeb", "https://ankiweb.net"),
        ("💻", "GitHub", "https://github.com"),
        ("📰", "Hacker News", "https://news.ycombinator.com"),
        ("🎓", "Scholar", "https://scholar.google.com"),
    ]
    for icon, name, url in shortcuts:
        shortcuts_html += (
            f'<a href="{url}" class="shortcut" target="_blank">'
            f'<span class="shortcut-icon">{icon}</span>'
            f'<span class="shortcut-name">{name}</span></a>'
        )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #FAFBFC; color: #333;
    display: flex; flex-direction: column; align-items: center;
    padding: 30px 24px 24px;
    min-height: 100%;
}}
.engine-tabs {{
    display: flex; gap: 6px; margin-bottom: 28px; flex-wrap: wrap; justify-content: center;
}}
.engine-tab {{
    font-size: 12px; padding: 5px 14px; border: 1.5px solid #D0D5DD;
    border-radius: 20px; background: #FFF; color: #666; cursor: pointer;
    font-weight: 500; transition: all 0.15s;
}}
.engine-tab:hover {{ border-color: #4A90D9; color: #4A90D9; }}
.engine-tab.active {{ background: #4A90D9; border-color: #4A90D9; color: white; font-weight: 600; }}
.logo {{
    font-size: 48px; font-weight: 400; letter-spacing: -2px;
    margin-bottom: 24px; user-select: none;
}}
.search-box-wrapper {{
    width: 100%; max-width: 500px; position: relative; margin-bottom: 20px;
}}
.search-box {{
    width: 100%; padding: 12px 48px 12px 20px;
    border: 1px solid #D0D5DD; border-radius: 24px;
    font-size: 15px; outline: none; background: #FFF;
    box-shadow: 0 1px 6px rgba(32,33,36,0.10);
    transition: box-shadow 0.2s;
}}
.search-box:focus {{ box-shadow: 0 1px 8px rgba(32,33,36,0.20); border-color: #4A90D9; }}
.search-icon {{
    position: absolute; right: 16px; top: 50%; transform: translateY(-50%);
    font-size: 18px; color: #999; cursor: pointer; background: none; border: none;
}}
.btn-row {{
    display: flex; gap: 10px; margin-bottom: 28px; justify-content: center;
}}
.search-btn {{
    font-size: 13px; padding: 8px 20px; border: none; border-radius: 6px;
    background: #F0F2F5; color: #555; cursor: pointer; font-weight: 500;
    transition: all 0.15s;
}}
.search-btn:hover {{ background: #E0E4E8; }}
.search-btn.primary {{
    background: #4A90D9; color: white; font-weight: 600;
}}
.search-btn.primary:hover {{ background: #357ABD; }}
.shortcuts {{
    display: flex; gap: 12px; flex-wrap: wrap; justify-content: center;
    max-width: 500px;
}}
.shortcut {{
    display: flex; flex-direction: column; align-items: center; gap: 4px;
    width: 70px; padding: 10px 4px; border-radius: 8px;
    text-decoration: none; color: #555; transition: background 0.15s;
}}
.shortcut:hover {{ background: #E8ECF0; }}
.shortcut-icon {{ font-size: 28px; }}
.shortcut-name {{ font-size: 10px; text-align: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 66px; }}
.hint {{
    margin-top: 24px; font-size: 11px; color: #AAA; text-align: center;
}}
</style></head><body>

<div class="engine-tabs">{tabs_html}</div>

<div class="logo">{_google_colored_logo()}</div>

<div class="search-box-wrapper">
    <input type="text" class="search-box" id="q"
           placeholder="在 Google 中搜索或输入网址" autofocus
           onkeydown="if(event.key==='Enter')doSearch('{default_engine}')">
    <button class="search-icon" onclick="doSearch('{default_engine}')">🔍</button>
</div>

<div class="btn-row">
    <button class="search-btn primary" onclick="doSearch('{default_engine}')">🔍 搜索</button>
    <button class="search-btn" onclick="openUrl('{home_url}')">🏠 打开首页</button>
</div>

<div class="shortcuts">{shortcuts_html}</div>

<div class="hint">💡 搜索将在系统默认浏览器中打开</div>

<script>
var currentEngine = '{default_engine}';
function switchEngine(name) {{
    currentEngine = name;
    var tabs = document.querySelectorAll('.engine-tab');
    tabs.forEach(function(t) {{
        t.classList.remove('active');
        if (t.textContent.trim() === name) t.classList.add('active');
    }});
    var q = document.getElementById('q');
    var logos = {{
        'Google': '{_google_colored_logo()}',
        '百度': '<span style="color:#4E6EF2;">百度</span>',
        'Bing': '<span style="color:#00809D;">Bing</span>',
        'B站': '<span style="color:#FB7299;">哔哩哔哩</span>',
        'YouTube': '<span style="color:#FF0000;">YouTube</span>',
    }};
    document.querySelector('.logo').innerHTML = logos[name] || name;
    q.placeholder = '在 ' + name + ' 中搜索或输入网址';
}}
function doSearch(engine) {{
    var q = document.getElementById('q').value.trim();
    if (!q) return;
    var urls = {{
        'Google': 'https://www.google.com/search?q=',
        '百度': 'https://www.baidu.com/s?wd=',
        'Bing': 'https://www.bing.com/search?q=',
        'B站': 'https://search.bilibili.com/all?keyword=',
        'YouTube': 'https://www.youtube.com/results?search_query=',
    }};
    var url = (urls[engine] || urls['Google']) + encodeURIComponent(q);
    window.open(url, '_blank');
}}
function openUrl(url) {{ window.open(url, '_blank'); }}
</script>
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
    def _get_home_url_static(engine_name: str) -> str:
        homepages = {
            "Google": "https://www.google.com",
            "百度": "https://www.baidu.com",
            "Bing": "https://www.bing.com",
            "B站": "https://www.bilibili.com",
            "YouTube": "https://www.youtube.com",
        }
        return homepages.get(engine_name, "https://www.google.com")

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Top bar (engine buttons + actions) ─────────────────────
        top_bar = QWidget()
        top_bar.setStyleSheet("background: #F5F6F8; border-bottom: 1px solid #E0E0E0;")
        tb_layout = QHBoxLayout(top_bar)
        tb_layout.setContentsMargins(8, 5, 8, 5)
        tb_layout.setSpacing(6)

        engine_label = QLabel("引擎:")
        engine_label.setStyleSheet("font-size: 11px; color: #888; background: transparent;")
        tb_layout.addWidget(engine_label)

        for engine in SEARCH_ENGINES:
            btn = QPushButton(engine["name"])
            btn.setToolTip(f"在 {engine['name']} 搜索")
            active = engine["name"] == self._default_engine
            if active:
                btn.setStyleSheet(
                    f"QPushButton {{ font-size: 11px; padding: 3px 10px; "
                    f"border: 1px solid {engine['color']}; border-radius: 4px; "
                    f"background: {engine['color']}; color: white; font-weight: bold; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ font-size: 11px; padding: 3px 10px; "
                    f"border: 1px solid {engine['color']}; border-radius: 4px; "
                    f"background: #FFF; color: {engine['color']}; font-weight: bold; }} "
                    f"QPushButton:hover {{ background: {engine['color']}; color: white; }}"
                )
            btn.clicked.connect(self._make_engine_handler(engine))
            tb_layout.addWidget(btn)

        tb_layout.addStretch()

        ext_btn = QPushButton("↗ 外部打开")
        ext_btn.setToolTip("在系统浏览器中打开首页")
        ext_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 3px 10px; "
            "border: 1px solid #D0D5DD; border-radius: 4px; "
            "background: #FFF; color: #888; } "
            "QPushButton:hover { background: #F5F7FA; border-color: #4A90D9; color: #4A90D9; }"
        )
        ext_btn.clicked.connect(self._open_homepage)
        tb_layout.addWidget(ext_btn)

        layout.addWidget(top_bar)

        # ── Homepage content (local HTML, Google-style) ────────────
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setStyleSheet(
            "QTextBrowser { border: none; background: #FAFBFC; }"
        )
        self._browser.setHtml(_build_homepage_html(self._default_engine))
        layout.addWidget(self._browser, 1)

    def _make_engine_handler(self, engine: dict):
        def handler():
            self._default_engine = engine["name"]
            # Refresh the homepage with new default engine
            self._browser.setHtml(_build_homepage_html(engine["name"]))
        return handler

    def _open_homepage(self) -> None:
        url = self._get_home_url_static(self._default_engine)
        webbrowser.open(url)
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
    _update_launcher_buttons()


def _open_browser_search() -> None:
    dock = _ensure_browser_dock()
    dock.show()
    dock.raise_()
    _update_launcher_buttons()
