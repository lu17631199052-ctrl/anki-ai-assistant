"""Browser search panel — search bar + engine shortcuts, opens results in system browser."""

import os
import webbrowser
from typing import Optional
from urllib.parse import quote

from aqt.qt import (
    QDockWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QLabel, QWidget, QTextBrowser,
    Qt, QSize, QIcon,
)
from aqt import mw
from aqt.utils import tooltip

_browser_dock: Optional[QDockWidget] = None
_browser_panel: Optional["BrowserSearchPanel"] = None
_MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "media")

ENGINES = [
    {"name": "百度", "search": "https://www.baidu.com/s?wd={q}", "color": "#4E6EF2"},
    {"name": "Google", "search": "https://www.google.com/search?q={q}", "color": "#4285F4"},
    {"name": "Bing", "search": "https://www.bing.com/search?q={q}", "color": "#00809D"},
    {"name": "B站", "search": "https://search.bilibili.com/all?keyword={q}", "color": "#FB7299"},
    {"name": "YouTube", "search": "https://www.youtube.com/results?search_query={q}", "color": "#FF0000"},
]


def _welcome_html() -> str:
    """Simple instruction page shown below the search bar."""
    cards = ""
    for e in ENGINES:
        cards += (
            f'<div style="display:flex;align-items:center;gap:8px;'
            f'background:#FFF;border-radius:8px;padding:10px 14px;margin-bottom:6px;'
            f'border-left:3px solid {e["color"]};box-shadow:0 1px 3px rgba(0,0,0,0.05);">'
            f'<span style="font-size:14px;font-weight:600;color:{e["color"]};">{e["name"]}</span>'
            f'<span style="flex:1;"></span>'
            f'<span style="font-size:11px;color:#AAA;">点击上方按钮搜索</span>'
            f'</div>'
        )
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
background:#FAFBFC;color:#333;padding:20px 18px;}}
h2{{font-size:17px;color:#555;text-align:center;margin-bottom:6px;}}
.sub{{font-size:12px;color:#999;text-align:center;margin-bottom:18px;}}
.hint{{margin-top:16px;padding:10px;background:#FFF8E1;border-radius:8px;
font-size:12px;color:#8D6E00;text-align:center;line-height:1.6;}}
</style></head><body>
<h2>🌐 浏览器搜索</h2>
<p class="sub">输入关键词 → 选择搜索引擎 → 在系统浏览器中打开结果</p>
{cards}
<div class="hint">
💡 <b>提示：</b>在顶部搜索框输入关键词，按 <b>Enter</b> 或用按钮搜索<br>
可在「设置 → 快捷提示词」中修改默认搜索引擎
</div>
</body></html>"""


class BrowserSearchPanel(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._default_engine = self._get_default()
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

    def _search_url(self, engine: str, query: str) -> str:
        for e in ENGINES:
            if e["name"] == engine:
                return e["search"].format(q=quote(query))
        return f"https://www.google.com/search?q={quote(query)}"

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Top bar: search input + engine buttons ─────────────────
        top = QWidget()
        top.setStyleSheet("background:#F5F6F8;border-bottom:1px solid #E0E0E0;")
        tb = QVBoxLayout(top)
        tb.setContentsMargins(8, 6, 8, 6)
        tb.setSpacing(5)

        # Row 1: search input + search button
        sr = QHBoxLayout()
        sr.setSpacing(4)

        self._input = QLineEdit()
        self._input.setPlaceholderText("输入搜索关键词... (Enter 搜索)")
        self._input.setStyleSheet(
            "QLineEdit{font-size:13px;border:1px solid #D0D5DD;"
            "border-radius:6px;padding:6px 10px;background:#FFF;}"
            "QLineEdit:focus{border-color:#4A90D9;}"
        )
        self._input.returnPressed.connect(lambda: self._search(self._default_engine))
        sr.addWidget(self._input, 1)

        sbtn = QPushButton("搜索")
        sbtn.setStyleSheet(
            "QPushButton{font-size:12px;padding:6px 14px;border:none;"
            "border-radius:6px;background:#4A90D9;color:white;font-weight:bold;}"
            "QPushButton:hover{background:#357ABD;}"
        )
        sbtn.clicked.connect(lambda: self._search(self._default_engine))
        sr.addWidget(sbtn)
        tb.addLayout(sr)

        # Row 2: engine buttons
        er = QHBoxLayout()
        er.setSpacing(6)
        el = QLabel("搜索引擎:")
        el.setStyleSheet("font-size:11px;color:#888;background:transparent;")
        er.addWidget(el)

        for e in ENGINES:
            btn = QPushButton(e["name"])
            btn.setToolTip(f"在 {e['name']} 搜索")
            btn.setStyleSheet(
                f"QPushButton{{font-size:11px;padding:3px 10px;"
                f"border:1px solid {e['color']};border-radius:4px;"
                f"background:#FFF;color:{e['color']};font-weight:bold;}}"
                f"QPushButton:hover{{background:{e['color']};color:white;}}"
            )
            btn.clicked.connect(self._on_engine(e["name"]))
            er.addWidget(btn)

        er.addStretch()
        tb.addLayout(er)
        layout.addWidget(top)

        # ── Welcome page ───────────────────────────────────────────
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet("QTextBrowser{border:none;background:#FAFBFC;}")
        browser.setHtml(_welcome_html())
        layout.addWidget(browser, 1)

    def _on_engine(self, name: str):
        def handler():
            self._search(name)
        return handler

    def _search(self, engine: str) -> None:
        q = self._input.text().strip()
        if not q:
            tooltip("请输入搜索关键词")
            return
        url = self._search_url(engine, q)
        webbrowser.open(url)
        tooltip(f"已在系统浏览器用 {engine} 搜索: {q}")


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
    _browser_dock.setMinimumWidth(380)

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
    if d.isVisible():
        d.hide()
    else:
        d.show()
        d.raise_()
        if _browser_panel:
            _browser_panel._input.setFocus()
    _update_launcher()


def _open_browser_search() -> None:
    d = _ensure_browser_dock()
    d.show()
    d.raise_()
    if _browser_panel:
        _browser_panel._input.setFocus()
    _update_launcher()
