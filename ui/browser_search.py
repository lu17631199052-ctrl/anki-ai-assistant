"""Browser search panel — search-engine homepage look, opens results in system browser.

Uses QTextBrowser with local HTML (100% reliable, no WebEngine dependency).
"""

import json
import os
import webbrowser
from typing import Optional
from urllib.parse import quote

from aqt.qt import (
    QDockWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QLabel, QWidget, QTextBrowser,
    Qt, QSize, QIcon, QUrl,
)
from aqt import mw
from aqt.utils import tooltip

_browser_dock: Optional[QDockWidget] = None
_browser_panel: Optional["BrowserSearchPanel"] = None
_MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "media")

ENGINES = [
    {"name": "Google", "search": "https://www.google.com/search?q={q}",
     "home": "https://www.google.com", "color": "#4285F4"},
    {"name": "百度", "search": "https://www.baidu.com/s?wd={q}",
     "home": "https://www.baidu.com", "color": "#4E6EF2"},
    {"name": "Bing", "search": "https://www.bing.com/search?q={q}",
     "home": "https://www.bing.com", "color": "#00809D"},
    {"name": "B站", "search": "https://search.bilibili.com/all?keyword={q}",
     "home": "https://www.bilibili.com", "color": "#FB7299"},
    {"name": "YouTube", "search": "https://www.youtube.com/results?search_query={q}",
     "home": "https://www.youtube.com", "color": "#FF0000"},
]

SHORTCUTS = [
    ("📖", "Wikipedia", "https://www.wikipedia.org"),
    ("📚", "Z-Library", "https://z-lib.io"),
    ("🧠", "AnkiWeb", "https://ankiweb.net"),
    ("💻", "GitHub", "https://github.com"),
    ("🎓", "Scholar", "https://scholar.google.com"),
    ("📰", "HN", "https://news.ycombinator.com"),
]

LOGOS = {
    "Google": ('<span style="color:#4285F4;">G</span>'
               '<span style="color:#EA4335;">o</span>'
               '<span style="color:#FBBC05;">o</span>'
               '<span style="color:#4285F4;">g</span>'
               '<span style="color:#34A853;">l</span>'
               '<span style="color:#EA4335;">e</span>'),
    "百度": '<span style="color:#4E6EF2;font-weight:700;">百度</span>',
    "Bing": '<span style="color:#00809D;font-weight:700;">Bing</span>',
    "B站": '<span style="color:#FB7299;font-weight:700;">哔哩哔哩</span>',
    "YouTube": '<span style="color:#FF0000;font-weight:700;">YouTube</span>',
}


def _build_page(engine_name: str) -> str:
    """Build a search-engine-style homepage."""
    search_urls = json.dumps({e["name"]: e["search"].replace("{q}","") for e in ENGINES})
    homes = json.dumps({e["name"]: e["home"] for e in ENGINES})

    tabs = ""
    for e in ENGINES:
        cls = "active" if e["name"] == engine_name else ""
        tabs += (
            f'<a class="tab {cls}" href="switch:{e["name"]}" '
            f'style="--c:{e["color"]};">{e["name"]}</a>'
        )

    shortcuts = ""
    for icon, name, url in SHORTCUTS:
        shortcuts += (
            f'<a class="sc" href="{url}">'
            f'<span class="sci">{icon}</span><span class="scn">{name}</span></a>'
        )

    logo = LOGOS.get(engine_name, LOGOS["Google"])

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
background:#FAFBFC;color:#333;display:flex;flex-direction:column;
align-items:center;padding:24px 20px 20px;min-height:100%;}}
.tabs{{display:flex;gap:6px;margin-bottom:22px;flex-wrap:wrap;justify-content:center;}}
.tab{{font-size:12px;padding:5px 16px;border:1.5px solid #D0D5DD;border-radius:20px;
background:#FFF;color:#666;text-decoration:none;font-weight:500;transition:all .15s;}}
.tab:hover{{border-color:var(--c);color:var(--c);}}
.tab.active{{background:var(--c);border-color:var(--c);color:#FFF;font-weight:600;}}
.logo{{font-size:48px;letter-spacing:-2px;margin-bottom:20px;user-select:none;}}
.sbox{{
width:100%;max-width:460px;padding:12px 20px;border:1px solid #D0D5DD;
border-radius:24px;font-size:15px;outline:none;background:#FFF;
box-shadow:0 1px 6px rgba(32,33,36,.10);margin-bottom:18px;}}
.sbox:focus{{box-shadow:0 1px 8px rgba(32,33,36,.20);border-color:#4A90D9;}}
.btns{{display:flex;gap:10px;margin-bottom:26px;justify-content:center;}}
.btn{{font-size:13px;padding:8px 22px;border:none;border-radius:6px;
background:#F0F2F5;color:#555;cursor:pointer;font-weight:500;
text-decoration:none;transition:all .15s;}}
.btn:hover{{background:#E0E4E8;}}
.btn.go{{background:#4A90D9;color:#FFF;font-weight:600;}}
.btn.go:hover{{background:#357ABD;}}
.scwrap{{display:flex;gap:6px;flex-wrap:wrap;justify-content:center;max-width:480px;}}
.sc{{display:flex;flex-direction:column;align-items:center;gap:4px;width:72px;
padding:8px 2px;border-radius:8px;text-decoration:none;color:#555;transition:background .15s;}}
.sc:hover{{background:#E8ECF0;}}
.sci{{font-size:26px;}}
.scn{{font-size:10px;text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:68px;}}
.hint{{margin-top:18px;font-size:11px;color:#AAA;text-align:center;}}
</style></head><body>

<div class="tabs">{tabs}</div>
<div class="logo">{logo}</div>

<input type="text" class="sbox" id="q"
       placeholder="在 {engine_name} 中搜索..."
       onkeydown="if(event.key==='Enter')go()" autofocus>

<div class="btns">
    <a class="btn go" href="action:go">🔍 搜索</a>
    <a class="btn" href="action:home">🏠 打开首页</a>
</div>

<div class="scwrap">{shortcuts}</div>
<div class="hint">💡 在上方搜索框输入关键词，搜索结果在系统浏览器中打开</div>

<script>
var E={engine_name};
var SU={search_urls};
var HM={homes};
function go(){{
    var q=document.getElementById('q').value.trim();
    if(!q)return;
    window.open((SU[E]||SU['Google'])+encodeURIComponent(q),'_blank');
}}
</script>
</body></html>"""


class BrowserSearchPanel(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = self._get_default()
        self._build_ui()

    @staticmethod
    def _get_default() -> str:
        try:
            from ..config import get_config
            e = get_config().get("default_search_engine", "Google")
            for eng in ENGINES:
                if eng["name"] == e:
                    return e
        except Exception:
            pass
        return "Google"

    @staticmethod
    def _search_url(engine: str, query: str) -> str:
        for e in ENGINES:
            if e["name"] == engine:
                return e["search"].format(q=quote(query))
        return f"https://www.google.com/search?q={quote(query)}"

    @staticmethod
    def _home_url(engine: str) -> str:
        for e in ENGINES:
            if e["name"] == engine:
                return e["home"]
        return "https://www.google.com"

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Top bar: engine buttons + external ─────────────────────
        top = QWidget()
        top.setStyleSheet("background:#F5F6F8;border-bottom:1px solid #E0E0E0;")
        tb = QHBoxLayout(top)
        tb.setContentsMargins(8, 5, 8, 5)
        tb.setSpacing(5)

        for e in ENGINES:
            btn = QPushButton(e["name"])
            btn.setToolTip(f"切换到 {e['name']}")
            self._style_engine_btn(btn, e, e["name"] == self._engine)
            btn.clicked.connect(self._on_engine_btn(e["name"]))
            tb.addWidget(btn)

        tb.addStretch()

        ext = QPushButton("↗ 外部打开")
        ext.setToolTip("在系统浏览器打开当前引擎首页")
        ext.setStyleSheet(
            "QPushButton{font-size:11px;padding:3px 8px;border:1px solid #D0D5DD;"
            "border-radius:4px;background:#FFF;color:#888;}"
            "QPushButton:hover{background:#F5F7FA;border-color:#4A90D9;}"
        )
        ext.clicked.connect(lambda: self._open(self._home_url(self._engine)))
        tb.addWidget(ext)

        layout.addWidget(top)

        # ── Homepage ───────────────────────────────────────────────
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setStyleSheet("QTextBrowser{border:none;background:#FAFBFC;}")
        self._browser.setHtml(_build_page(self._engine))
        self._browser.anchorClicked.connect(self._on_link)
        layout.addWidget(self._browser, 1)

    def _style_engine_btn(self, btn: QPushButton, engine: dict, active: bool) -> None:
        c = engine["color"]
        if active:
            btn.setStyleSheet(
                f"QPushButton{{font-size:11px;padding:3px 10px;"
                f"border:1px solid {c};border-radius:4px;"
                f"background:{c};color:white;font-weight:bold;}}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton{{font-size:11px;padding:3px 10px;"
                f"border:1px solid {c};border-radius:4px;"
                f"background:#FFF;color:{c};font-weight:bold;}}"
                f"QPushButton:hover{{background:{c};color:white;}}"
            )

    def _on_engine_btn(self, name: str):
        def handler():
            self._switch_to(name)
        return handler

    def _switch_to(self, name: str) -> None:
        self._engine = name
        self._browser.setHtml(_build_page(name))
        # Refresh top bar button styles
        top = self.layout().itemAt(0).widget()
        tb = top.layout()
        for i in range(tb.count()):
            w = tb.itemAt(i).widget()
            if isinstance(w, QPushButton):
                for e in ENGINES:
                    if w.text() == e["name"]:
                        self._style_engine_btn(w, e, e["name"] == name)
                        break

    def _on_link(self, url: QUrl) -> None:
        s = url.toString()
        if s.startswith("switch:"):
            self._switch_to(s.split(":", 1)[-1])
        elif s.startswith("action:go"):
            # Can't read JS input from QTextBrowser, open engine homepage
            self._open(self._home_url(self._engine))
        elif s.startswith("action:home"):
            self._open(self._home_url(self._engine))
        else:
            self._open(s)

    def _open(self, url: str) -> None:
        webbrowser.open(url)
        tooltip("已在系统浏览器打开")


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

    bar = QWidget()
    bar.setStyleSheet("background:#F5F6F8;")
    bl = QHBoxLayout(bar)
    bl.setContentsMargins(12, 4, 8, 4)
    bl.setSpacing(4)
    tl = QLabel("🌐 浏览器搜索")
    tl.setStyleSheet("font-size:12px;font-weight:bold;color:#555;background:transparent;")
    bl.addWidget(tl)
    bl.addStretch()
    cb = QPushButton()
    cb.setIcon(QIcon(os.path.join(_MEDIA_DIR, "close.svg")))
    cb.setIconSize(QSize(16, 16))
    cb.setFixedSize(26, 26)
    cb.setToolTip("关闭面板")
    cb.setStyleSheet(
        "QPushButton{border:none;border-radius:13px;background:#E0E0E0;}"
        "QPushButton:hover{background:#C0C0C0;}"
    )
    cb.clicked.connect(lambda: _browser_dock.hide() if _browser_dock else None)
    bl.addWidget(cb)
    _browser_dock.setTitleBarWidget(bar)

    _browser_panel = BrowserSearchPanel()
    _browser_dock.setWidget(_browser_panel)
    _browser_dock.visibilityChanged.connect(lambda v: _update_launcher())
    mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, _browser_dock)
    return _browser_dock


def _update_launcher() -> None:
    try:
        from .left_sidebar import _update_launcher_buttons as fn
        fn()
    except Exception:
        pass


def _toggle_browser_search() -> None:
    d = _ensure_browser_dock()
    d.hide() if d.isVisible() else (d.show(), d.raise_())
    _update_launcher()


def _open_browser_search() -> None:
    d = _ensure_browser_dock()
    d.show()
    d.raise_()
    _update_launcher()
