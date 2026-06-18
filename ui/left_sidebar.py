"""Left launcher + content panels — Synapse Pro style icon strip + right-side panels.

A fixed-width icon bar always visible on the left. Click an icon to toggle
its corresponding content panel on the right side of the Anki window.
"""

import json
import os
from datetime import datetime
from typing import Optional, Callable

from aqt.qt import (
    QDockWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPushButton,
    QLabel,
    QWidget,
    QTabWidget,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
    QFrame,
    QTimer,
    Qt,
    QSize,
    QIcon,
    QEvent,
    QFileDialog,
)
from aqt import mw
from aqt.utils import tooltip

# ── data file path (same directory as config backup) ────────────────
_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_PATH = os.path.join(os.path.dirname(_ADDON_DIR), "anki_ai_assistant_sidebar.json")
_MEDIA_DIR = os.path.join(_ADDON_DIR, "media")

# ── singleton references ────────────────────────────────────────────
_launcher_dock: Optional[QDockWidget] = None
_notebook_dock: Optional[QDockWidget] = None
_notebook_panel: Optional["NotebookPanel"] = None
_launcher: Optional["LauncherWidget"] = None

# ── style constants ─────────────────────────────────────────────────
_LAUNCHER_WIDTH = 52
_ICON_SIZE = 40


# ═══════════════════════════════════════════════════════════════════════
# Todo item widget (used inside NotebookPanel's todo tab)
# ═══════════════════════════════════════════════════════════════════════

class TodoItemWidget(QWidget):
    """Single todo row: checkbox + label + delete button."""

    def __init__(
        self,
        index: int,
        text: str,
        done: bool = False,
        on_changed: Optional[Callable[[int, bool], None]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._index = index
        self._on_changed = on_changed
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(4)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(done)
        self.checkbox.stateChanged.connect(self._on_toggle)
        layout.addWidget(self.checkbox)

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self._update_label_style(done)
        layout.addWidget(self.label, 1)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(20, 20)
        del_btn.setStyleSheet(
            "QPushButton { font-size: 10px; border: none; color: #BBB; "
            "background: transparent; border-radius: 10px; } "
            "QPushButton:hover { color: #E55; background: #FEE; }"
        )
        del_btn.clicked.connect(self._on_remove)
        layout.addWidget(del_btn)

    def _update_label_style(self, done: bool) -> None:
        if done:
            self.label.setStyleSheet(
                "font-size: 12px; text-decoration: line-through; color: #999;"
            )
        else:
            self.label.setStyleSheet("font-size: 12px;")

    def _on_toggle(self, state: int) -> None:
        done = self.checkbox.isChecked()
        self._update_label_style(done)
        if self._on_changed:
            self._on_changed(self._index, False)

    def _on_remove(self) -> None:
        if self._on_changed:
            self._on_changed(self._index, True)


# ═══════════════════════════════════════════════════════════════════════
# LauncherWidget — fixed left icon strip with SVG icons
# ═══════════════════════════════════════════════════════════════════════

class LauncherWidget(QWidget):
    """Fixed-width icon bar docked on the left, always visible.

    Layout (top to bottom):
      - Logo (brain SVG icon)
      - Separator
      - Tool icons with labels
      - Separator
      - Settings gear
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LauncherContent")
        self.setFixedWidth(_LAUNCHER_WIDTH)
        self._buttons: dict[str, QPushButton] = {}
        self._build_ui()
        self.installEventFilter(self)

    # ── icon helpers ───────────────────────────────────────────────

    @staticmethod
    def _load_icon(name: str) -> QIcon:
        """Load an SVG icon, returns empty QIcon if file missing."""
        path = os.path.join(_MEDIA_DIR, f"{name}.svg")
        if os.path.exists(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon
        return QIcon()

    @staticmethod
    def _load_icon_pair(name: str) -> tuple[QIcon, QIcon]:
        """Return (normal_gray_icon, white_icon) for a tool."""
        normal = LauncherWidget._load_icon(name)
        white = LauncherWidget._load_icon(f"{name}_white")
        if white.isNull():
            white = normal
        return normal, white

    def _set_btn_icons(self, btn: QPushButton, name: str) -> None:
        """Load and store both icon variants on a button via properties."""
        normal, white = self._load_icon_pair(name)
        btn.setProperty("normalIcon", normal)
        btn.setProperty("whiteIcon", white)
        btn.setIcon(normal)
        btn.setIconSize(QSize(24, 24))

    # ── UI construction ────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 10)
        layout.setSpacing(2)

        # ── Logo ──────────────────────────────────────────────────
        logo = QPushButton()
        logo.setFixedSize(_ICON_SIZE + 4, _ICON_SIZE + 4)
        logo.setToolTip("AI Study Assistant")
        logo.setFlat(True)
        logo.setCursor(Qt.CursorShape.PointingHandCursor)
        logo.clicked.connect(lambda: toggle_notebook("notepad"))
        self._set_btn_icons(logo, "logo")
        logo.setIconSize(QSize(28, 28))
        logo.installEventFilter(self)
        logo_layout = QHBoxLayout()
        logo_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.addWidget(logo)
        layout.addLayout(logo_layout)
        layout.addSpacing(4)

        # ── Separator after logo ──────────────────────────────────
        self._sep1 = QFrame()
        self._sep1.setFrameShape(QFrame.Shape.HLine)
        self._sep1.setFixedWidth(_LAUNCHER_WIDTH - 16)
        layout.addWidget(self._sep1, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(6)

        layout.addStretch(1)

        # ── Tool icons ────────────────────────────────────────────
        tool_icons = [
            ("notebook",    "notebook",    "记事本", "记事本 — 随时记录想法"),
            ("todo",        "todo",        "待办",   "待办清单"),
            ("wrong_answer","wrong_answer","错题",   "AI 错题整理 — 截图识别"),
            ("chat",        "chat",        "AI对话", "AI 学习助手对话"),
        ]

        for key, icon_name, label, tooltip_text in tool_icons:
            item_widget = self._create_icon_with_label(icon_name, label, tooltip_text)
            btn = item_widget.findChild(QPushButton)
            if btn:
                btn.clicked.connect(self._make_handler(key))
                btn.installEventFilter(self)
                # wrong_answer is a one-shot action, not a toggle
                if key == "wrong_answer":
                    btn.setCheckable(False)
                self._buttons[key] = btn
            layout.addWidget(item_widget)
            layout.addSpacing(2)

        layout.addStretch(1)

        # ── Bottom separator ──────────────────────────────────────
        self._sep2 = QFrame()
        self._sep2.setFrameShape(QFrame.Shape.HLine)
        self._sep2.setFixedWidth(_LAUNCHER_WIDTH - 16)
        layout.addWidget(self._sep2, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(4)

        # ── Settings gear ─────────────────────────────────────────
        settings_item = self._create_icon_with_label("settings", "设置", "插件设置")
        sbtn = settings_item.findChild(QPushButton)
        if sbtn:
            sbtn.clicked.connect(self._open_settings)
            sbtn.installEventFilter(self)
            self._buttons["settings"] = sbtn
        layout.addWidget(settings_item)

    def _create_icon_with_label(self, icon_name: str, label: str, tooltip: str) -> QWidget:
        """Create a vertical SVG icon + label combo."""
        container = QWidget()
        container.setFixedSize(_LAUNCHER_WIDTH, 56)
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(1)
        vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn = QPushButton()
        btn.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        btn.setToolTip(tooltip)
        btn.setFlat(True)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setObjectName(f"launcher_btn_{label}")
        self._set_btn_icons(btn, icon_name)

        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size: 9px; color: #888; background: transparent;")
        lbl.setCursor(Qt.CursorShape.PointingHandCursor)

        vbox.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
        vbox.addWidget(lbl, 0, Qt.AlignmentFlag.AlignCenter)
        return container

    # ── event filter: hover icon swap ──────────────────────────────

    def eventFilter(self, watched, event) -> bool:
        """Swap normal ↔ white icon on hover, and handle checked state."""
        if isinstance(watched, QPushButton) and watched.property("normalIcon") is not None:
            normal = watched.property("normalIcon")
            white = watched.property("whiteIcon")
            if isinstance(normal, QIcon) and isinstance(white, QIcon):
                if event.type() == QEvent.Type.Enter:
                    watched.setIcon(white)
                elif event.type() == QEvent.Type.Leave:
                    if watched.isChecked():
                        watched.setIcon(white)
                    else:
                        watched.setIcon(normal)
        return super().eventFilter(watched, event)

    # ── handlers ───────────────────────────────────────────────────

    def _make_handler(self, key: str) -> Callable:
        def handler():
            if key == "notebook":
                toggle_notebook(tab="notepad")
            elif key == "todo":
                toggle_notebook(tab="todo")
            elif key == "wrong_answer":
                _toggle_wrong_answer()
            elif key == "chat":
                _toggle_chat()
        return handler

    def _open_settings(self) -> None:
        from .settings import SettingsDialog
        dialog = SettingsDialog(mw)
        dialog.show()

    def set_active(self, key: str, active: bool) -> None:
        """Set the checked state of an icon button and swap icon."""
        btn = self._buttons.get(key)
        if btn and btn.isCheckable():
            btn.setChecked(active)
            # Swap icon to white when active
            normal = btn.property("normalIcon")
            white = btn.property("whiteIcon")
            if active and isinstance(white, QIcon):
                btn.setIcon(white)
            elif not active and isinstance(normal, QIcon):
                btn.setIcon(normal)
        # Update label color for active state
        if btn and btn.parent():
            lbl = btn.parent().findChild(QLabel)
            if lbl:
                if active:
                    lbl.setStyleSheet(
                        "font-size: 9px; color: #4A90D9; background: transparent; font-weight: bold;"
                    )
                else:
                    lbl.setStyleSheet("font-size: 9px; color: #888; background: transparent;")

    def apply_theme(self) -> None:
        """Re-apply stylesheet (for night mode support)."""
        night = mw.pm.night_mode() if mw and hasattr(mw, 'pm') else False
        if night:
            bg = "#1E1E1E"
            hover_bg = "#333"
            active_bg = "#3A5070"
            sep_color = "#444"
            label_color = "#AAA"
        else:
            bg = "#F0F2F5"
            hover_bg = "#DCE8F5"
            active_bg = "#CCDBF0"
            sep_color = "#D8DADC"
            label_color = "#777"

        self.setStyleSheet(
            f"QWidget#LauncherContent {{ "
            f"background: {bg}; "
            f"border-right: 1px solid {sep_color}; "
            f"}}"
        )

        icon_style = (
            f"QPushButton {{ border: none; border-radius: 10px; "
            f"background: transparent; }} "
            f"QPushButton:hover {{ background: {hover_bg}; }} "
            f"QPushButton:checked {{ background: {active_bg}; }}"
        )
        for btn in self._buttons.values():
            if btn is not None:
                btn.setStyleSheet(icon_style)

        sep_style = f"border: none; border-top: 1px solid {sep_color};"
        for sep in [self._sep1, self._sep2]:
            if sep:
                sep.setStyleSheet(sep_style)

        # Update label colors
        for container in self.findChildren(QWidget):
            lbl = container.findChild(QLabel)
            if lbl and lbl.text() in ("记事本", "待办", "AI对话", "设置"):
                btn = container.findChild(QPushButton)
                if btn and btn.isChecked():
                    lbl.setStyleSheet(
                        "font-size: 9px; color: #4A90D9; background: transparent; font-weight: bold;"
                    )
                else:
                    lbl.setStyleSheet(
                        f"font-size: 9px; color: {label_color}; background: transparent;"
                    )


# ═══════════════════════════════════════════════════════════════════════
# NotebookPanel — multi-page notepad + todo tabs (Apple Notes style)
# ═══════════════════════════════════════════════════════════════════════

class NotebookPanel(QWidget):
    """Right-side panel with multi-page Notepad and Todo tabs."""

    # Default page template when creating a new page
    _DEFAULT_PAGE = {"title": "", "content": "", "created_at": "", "updated_at": ""}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: dict = {"pages": [], "todos": []}
        self._current_page_index: int = -1
        self._load_data()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_data)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #E0E0E0; border-radius: 0; } "
            "QTabBar::tab { padding: 8px 16px; font-size: 12px; } "
            "QTabBar::tab:selected { background: #FFF; border-bottom: 2px solid #4A90D9; }"
        )
        self._tabs.addTab(self._build_notepad_tab(), "📝 记事本")
        self._tabs.addTab(self._build_todo_tab(), "✅ 待办")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs, 1)

    # ── Notepad tab (multi-page, Apple Notes style) ─────────────────

    def _build_notepad_tab(self) -> QWidget:
        tab = QWidget()
        self._notepad_hbox = QHBoxLayout(tab)
        self._notepad_hbox.setContentsMargins(0, 0, 0, 0)
        self._notepad_hbox.setSpacing(0)

        # ── Left: page list sidebar (collapsible) ─────────────────
        self._nb_sidebar = QWidget()
        self._nb_sidebar.setFixedWidth(150)
        self._nb_sidebar.setStyleSheet(
            "background: #F7F7F5; border-right: 1px solid #E8E8E8;"
        )
        sv = QVBoxLayout(self._nb_sidebar)
        sv.setContentsMargins(8, 4, 8, 8)
        sv.setSpacing(4)

        # Collapse button (top-right of sidebar)
        collapse_btn = QPushButton("◀")
        collapse_btn.setFixedSize(26, 26)
        collapse_btn.setToolTip("隐藏页面列表")
        collapse_btn.setStyleSheet(
            "QPushButton { font-size: 12px; border: none; border-radius: 13px; "
            "background: #E8E8E8; color: #666; } "
            "QPushButton:hover { background: #D0D0D0; color: #333; }"
        )
        collapse_btn.clicked.connect(self._collapse_nb_sidebar)
        collapse_row = QHBoxLayout()
        collapse_row.addStretch()
        collapse_row.addWidget(collapse_btn)
        sv.addLayout(collapse_row)

        # New page button
        new_btn = QPushButton("+ 新建页面")
        new_btn.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 6px 10px; border: none; "
            "border-radius: 6px; background: transparent; color: #666; text-align: left; } "
            "QPushButton:hover { background: #EBEBE9; }"
        )
        new_btn.clicked.connect(self._new_page)
        sv.addWidget(new_btn)

        # Page list
        self._page_list = QListWidget()
        self._page_list.setStyleSheet(
            "QListWidget { border: none; background: transparent; font-size: 13px; } "
            "QListWidget::item { padding: 8px 10px; border-radius: 6px; color: #37352F; } "
            "QListWidget::item:hover { background: #EBEBE9; } "
            "QListWidget::item:selected { background: #E2E2E0; font-weight: bold; }"
        )
        self._page_list.currentRowChanged.connect(self._on_page_selected)
        sv.addWidget(self._page_list, 1)

        # Export button
        export_btn = QPushButton("📤 导出当前页面")
        export_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 5px 10px; border: none; "
            "border-radius: 6px; background: transparent; color: #999; text-align: left; } "
            "QPushButton:hover { background: #E8F0FE; color: #4A90D9; }"
        )
        export_btn.clicked.connect(self._export_current_page)
        sv.addWidget(export_btn)

        # Delete page button (always visible at bottom)
        del_btn = QPushButton("🗑 删除当前页面")
        del_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 5px 10px; border: none; "
            "border-radius: 6px; background: transparent; color: #999; text-align: left; } "
            "QPushButton:hover { background: #FEE; color: #E55; }"
        )
        del_btn.clicked.connect(self._delete_page)
        sv.addWidget(del_btn)

        self._notepad_hbox.addWidget(self._nb_sidebar)

        # ── Collapsed strip (shown when sidebar hidden) ───────────
        self._nb_collapsed_strip = QWidget()
        self._nb_collapsed_strip.setFixedWidth(26)
        self._nb_collapsed_strip.setStyleSheet(
            "background: #F7F7F5; border-right: 1px solid #E8E8E8;"
        )
        self._nb_collapsed_strip.setCursor(Qt.CursorShape.PointingHandCursor)
        cs_layout = QVBoxLayout(self._nb_collapsed_strip)
        cs_layout.setContentsMargins(3, 6, 3, 8)
        cs_layout.setSpacing(0)
        expand_btn = QPushButton("▶")
        expand_btn.setFixedSize(20, 24)
        expand_btn.setToolTip("显示页面列表")
        expand_btn.setStyleSheet(
            "QPushButton { font-size: 10px; border: none; border-radius: 4px; "
            "background: #E0E0E0; color: #666; } "
            "QPushButton:hover { background: #D0D0D0; color: #333; }"
        )
        expand_btn.clicked.connect(self._expand_nb_sidebar)
        cs_layout.addWidget(expand_btn)
        cs_layout.addStretch()
        self._nb_collapsed_strip.hide()
        self._notepad_hbox.addWidget(self._nb_collapsed_strip)

        # ── Right: editor area ───────────────────────────────────
        editor = QWidget()
        editor.setStyleSheet("background: #FFF;")
        ev = QVBoxLayout(editor)
        ev.setContentsMargins(20, 16, 20, 16)
        ev.setSpacing(8)

        # Title field (large, bold, Apple Notes style)
        self._page_title = QLineEdit()
        self._page_title.setPlaceholderText("标题")
        self._page_title.setStyleSheet(
            "QLineEdit { font-size: 22px; font-weight: bold; border: none; "
            "background: transparent; color: #1D1D1F; padding: 0; }"
        )
        self._page_title.textChanged.connect(self._on_title_changed)
        ev.addWidget(self._page_title)

        # Timestamp label
        self._page_time = QLabel("")
        self._page_time.setStyleSheet("font-size: 11px; color: #AAA; padding: 0 0 8px 0;")
        ev.addWidget(self._page_time)

        # Content editor
        self._page_content = QTextEdit()
        self._page_content.setPlaceholderText("开始写点什么...")
        self._page_content.setStyleSheet(
            "QTextEdit { font-size: 15px; border: none; background: transparent; "
            "color: #333; line-height: 1.6; }"
        )
        self._page_content.textChanged.connect(self._schedule_save)
        ev.addWidget(self._page_content, 1)

        self._notepad_hbox.addWidget(editor, 1)

        # Populate page list and select first page
        self._rebuild_page_list()
        return tab

    def _collapse_nb_sidebar(self) -> None:
        """Hide page list sidebar, show thin strip."""
        self._nb_sidebar.hide()
        self._nb_collapsed_strip.show()

    def _expand_nb_sidebar(self) -> None:
        """Show page list sidebar, hide thin strip."""
        self._nb_collapsed_strip.hide()
        self._nb_sidebar.show()

    # ── page management ────────────────────────────────────────────

    def _new_page(self) -> None:
        """Create a new blank page and switch to it."""
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        page = {
            "title": "",
            "content": "",
            "created_at": now,
            "updated_at": now,
        }
        self._data.setdefault("pages", []).append(page)
        self._rebuild_page_list()
        # Select the new page (last item)
        self._page_list.setCurrentRow(len(self._data["pages"]) - 1)
        self._page_title.setFocus()

    def _delete_page(self) -> None:
        """Delete the currently selected page."""
        if self._current_page_index < 0:
            return
        pages = self._data.get("pages", [])
        if 0 <= self._current_page_index < len(pages):
            del pages[self._current_page_index]
        self._rebuild_page_list()
        self._save_data()

    def _export_current_page(self) -> None:
        """Export the current page as a Markdown file."""
        pages = self._data.get("pages", [])
        if not (0 <= self._current_page_index < len(pages)):
            tooltip("没有可导出的页面")
            return
        page = pages[self._current_page_index]
        title = page.get("title", "").strip() or "无标题"
        content = page.get("content", "")

        # Build Markdown
        md = f"# {title}\n\n{content}"

        # Suggest filename from title
        safe_title = title.replace("/", "-").replace("\\", "-")[:40]
        default_name = f"{safe_title}.md"

        path, _ = QFileDialog.getSaveFileName(
            mw, "导出页面", default_name, "Markdown (*.md);;Text (*.txt)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(md)
            tooltip(f"已导出: {os.path.basename(path)}")
        except OSError as e:
            tooltip(f"导出失败: {e}")

    def _rebuild_page_list(self) -> None:
        """Refresh the page list from data."""
        self._page_list.blockSignals(True)
        self._page_list.clear()
        for page in self._data.get("pages", []):
            title = page.get("title", "").strip()
            display = title if title else "无标题"
            # Truncate long titles in list
            if len(display) > 15:
                display = display[:14] + "…"
            self._page_list.addItem(display)
        if self._data.get("pages"):
            if self._current_page_index >= len(self._data["pages"]):
                self._current_page_index = 0
            if self._current_page_index < 0:
                self._current_page_index = 0
            self._page_list.setCurrentRow(self._current_page_index)
        else:
            self._current_page_index = -1
        self._page_list.blockSignals(False)
        self._load_page_into_editor()

    def _on_page_selected(self, index: int) -> None:
        """Save current page, then load the selected one."""
        if index < 0:
            return
        self._save_current_page()
        self._current_page_index = index
        self._load_page_into_editor()

    def _save_current_page(self) -> None:
        """Flush editor state back into the current page dict."""
        pages = self._data.get("pages", [])
        if 0 <= self._current_page_index < len(pages):
            page = pages[self._current_page_index]
            page["title"] = self._page_title.text().strip()
            page["content"] = self._page_content.toPlainText()
            from datetime import datetime
            page["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    def _load_page_into_editor(self) -> None:
        """Display the current page in the editor."""
        pages = self._data.get("pages", [])
        if 0 <= self._current_page_index < len(pages):
            page = pages[self._current_page_index]
            self._page_title.blockSignals(True)
            self._page_title.setText(page.get("title", ""))
            self._page_title.blockSignals(False)
            self._page_content.blockSignals(True)
            self._page_content.setPlainText(page.get("content", ""))
            self._page_content.blockSignals(False)
            updated = page.get("updated_at") or page.get("created_at", "")
            self._page_time.setText(f"上次编辑: {updated}" if updated else "")
        else:
            self._page_title.clear()
            self._page_content.clear()
            self._page_time.setText("")

    def _on_title_changed(self, text: str) -> None:
        """Update page title in data and refresh list display."""
        pages = self._data.get("pages", [])
        if 0 <= self._current_page_index < len(pages):
            pages[self._current_page_index]["title"] = text.strip()
            # Update list item text
            display = text.strip() if text.strip() else "无标题"
            if len(display) > 15:
                display = display[:14] + "…"
            item = self._page_list.item(self._current_page_index)
            if item:
                item.setText(display)
        self._schedule_save()

    def _build_todo_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # input row
        input_row = QHBoxLayout()
        self._todo_input = QLineEdit()
        self._todo_input.setPlaceholderText("添加待办事项...")
        self._todo_input.setStyleSheet(
            "QLineEdit { font-size: 12px; border: 1px solid #D0D5DD; "
            "border-radius: 4px; padding: 6px 8px; background: #FFF; } "
            "QLineEdit:focus { border-color: #4A90D9; }"
        )
        self._todo_input.returnPressed.connect(self._add_todo)
        input_row.addWidget(self._todo_input, 1)

        add_btn = QPushButton("+")
        add_btn.setFixedSize(28, 28)
        add_btn.setStyleSheet(
            "QPushButton { font-size: 16px; font-weight: bold; border: none; "
            "border-radius: 14px; background: #4A90D9; color: white; } "
            "QPushButton:hover { background: #357ABD; }"
        )
        add_btn.clicked.connect(self._add_todo)
        input_row.addWidget(add_btn)
        layout.addLayout(input_row)

        self._todo_list = QListWidget()
        self._todo_list.setStyleSheet(
            "QListWidget { border: none; background: transparent; } "
            "QListWidget::item { border-bottom: 1px solid #F0F0F0; padding: 2px 0; }"
        )
        self._todo_list.setSpacing(1)
        layout.addWidget(self._todo_list, 1)

        self._rebuild_todo_list()
        return tab

    # ── tab switching ───────────────────────────────────────────────

    def switch_to(self, tab: str) -> None:
        """Switch to notepad or todo tab."""
        if tab == "notepad":
            self._tabs.setCurrentIndex(0)
        elif tab == "todo":
            self._tabs.setCurrentIndex(1)

    def current_tab(self) -> str:
        idx = self._tabs.currentIndex()
        return "notepad" if idx == 0 else "todo"

    def _on_tab_changed(self, index: int) -> None:
        _update_launcher_buttons()

    # ── todo operations ─────────────────────────────────────────────

    def _add_todo(self) -> None:
        text = self._todo_input.text().strip()
        if not text:
            return
        todo = {"text": text, "done": False, "created_at": datetime.now().isoformat()}
        self._data.setdefault("todos", []).append(todo)
        self._rebuild_todo_list()
        self._todo_input.clear()
        self._todo_input.setFocus()
        self._save_data()

    def _rebuild_todo_list(self) -> None:
        self._todo_list.clear()
        todos = self._data.get("todos", [])
        indexed = list(enumerate(todos))
        undone = [(i, t) for i, t in indexed if not t.get("done")]
        done = [(i, t) for i, t in indexed if t.get("done")]
        for orig_idx, todo in undone + done:
            item_widget = TodoItemWidget(
                index=orig_idx,
                text=todo["text"],
                done=todo.get("done", False),
                on_changed=self._on_todo_changed,
            )
            list_item = QListWidgetItem(self._todo_list)
            list_item.setSizeHint(item_widget.sizeHint())
            self._todo_list.setItemWidget(list_item, item_widget)

    def _on_todo_changed(self, index: int, delete: bool) -> None:
        todos = self._data.get("todos", [])
        if index < 0 or index >= len(todos):
            return
        if delete:
            del todos[index]
        else:
            todos[index]["done"] = not todos[index].get("done", False)
        self._rebuild_todo_list()
        self._save_data()

    # ── data persistence ────────────────────────────────────────────

    def _schedule_save(self) -> None:
        # Flush current page editor state before saving
        self._save_current_page()
        self._save_timer.start(1000)

    def _save_data(self) -> None:
        self._save_current_page()
        try:
            with open(_DATA_PATH, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _load_data(self) -> None:
        try:
            with open(_DATA_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("invalid format")
            # Migrate old format: {"notepad": "...", "todos": [...]}
            if "pages" not in loaded:
                old_notepad = loaded.pop("notepad", "")
                from datetime import datetime
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                loaded["pages"] = [{
                    "title": "",
                    "content": old_notepad,
                    "created_at": now,
                    "updated_at": now,
                }] if old_notepad.strip() else []
            self._data = {"pages": [], "todos": []}
            self._data.update(loaded)
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            self._data = {"pages": [], "todos": []}


# ═══════════════════════════════════════════════════════════════════════
# Dock management functions
# ═══════════════════════════════════════════════════════════════════════

def _ensure_launcher() -> QDockWidget:
    """Create (or return existing) left launcher dock."""
    global _launcher_dock, _launcher

    if _launcher_dock is not None:
        return _launcher_dock

    _launcher_dock = QDockWidget("", mw)
    _launcher_dock.setObjectName("ai_assistant_launcher")
    _launcher_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
    _launcher_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
    _launcher_dock.setTitleBarWidget(QWidget())

    _launcher = LauncherWidget()
    _launcher_dock.setWidget(_launcher)

    mw.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, _launcher_dock)
    _launcher_dock.show()

    # Apply night/day theme
    try:
        from aqt import gui_hooks
        gui_hooks.theme_did_change.append(lambda: _launcher.apply_theme() if _launcher else None)
    except Exception:
        pass
    _launcher.apply_theme()

    return _launcher_dock


def _ensure_notebook_dock() -> QDockWidget:
    """Create (or return existing) notebook content dock on the right."""
    global _notebook_dock, _notebook_panel

    if _notebook_dock is not None:
        return _notebook_dock

    _notebook_dock = QDockWidget("学习工具", mw)
    _notebook_dock.setObjectName("ai_assistant_notebook")
    _notebook_dock.setAllowedAreas(
        Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
    )
    _notebook_dock.setMinimumWidth(280)

    # Custom title bar with styled close button
    title_bar = QWidget()
    title_bar.setStyleSheet("background: #F5F6F8;")
    tb_layout = QHBoxLayout(title_bar)
    tb_layout.setContentsMargins(12, 4, 8, 4)
    tb_layout.setSpacing(4)
    title_label = QLabel("学习工具")
    title_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #555; background: transparent;")
    tb_layout.addWidget(title_label)
    tb_layout.addStretch()
    close_btn = QPushButton("✕")
    close_btn.setFixedSize(26, 26)
    close_btn.setToolTip("关闭面板")
    close_btn.setStyleSheet(
        "QPushButton { font-size: 14px; border: none; border-radius: 13px; "
        "background: transparent; color: #999; } "
        "QPushButton:hover { background: #E8E8E8; color: #555; }"
    )
    close_btn.clicked.connect(lambda: _notebook_dock.hide() if _notebook_dock else None)
    tb_layout.addWidget(close_btn)
    _notebook_dock.setTitleBarWidget(title_bar)

    _notebook_panel = NotebookPanel()
    _notebook_dock.setWidget(_notebook_panel)

    # Track visibility → update launcher button states
    _notebook_dock.visibilityChanged.connect(lambda v: _update_launcher_buttons())

    mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, _notebook_dock)
    return _notebook_dock


def _update_launcher_buttons() -> None:
    """Sync launcher button active states with dock visibility."""
    if _launcher is None:
        return
    if _notebook_dock is not None and _notebook_panel is not None:
        visible = _notebook_dock.isVisible()
        tab = _notebook_panel.current_tab()
        _launcher.set_active("notebook", visible and tab == "notepad")
        _launcher.set_active("todo", visible and tab == "todo")
    # Chat dock check
    try:
        from .chat_dialog import _dock_widget as chat_dock
        if chat_dock is not None:
            _launcher.set_active("chat", chat_dock.isVisible())
    except Exception:
        pass


def _toggle_chat() -> None:
    """Toggle the existing AI chat dock."""
    try:
        from .chat_dialog import _open_chat, _dock_widget as chat_dock
        if chat_dock is not None and chat_dock.isVisible():
            chat_dock.hide()
        else:
            _open_chat()
    except Exception:
        from .chat_dialog import _open_chat
        _open_chat()
    _update_launcher_buttons()


_wrong_answer_dialog_ref = None

def _toggle_wrong_answer() -> None:
    """Open the wrong answer dialog (screenshot → MCQ cards)."""
    global _wrong_answer_dialog_ref
    from .wrong_answer_dialog import WrongAnswerDialog
    _wrong_answer_dialog_ref = WrongAnswerDialog(mw)
    _wrong_answer_dialog_ref.show()


# ── Public API ───────────────────────────────────────────────────────

def init_launcher() -> None:
    """Initialize the left launcher. Call once on profile open."""
    _ensure_launcher()
    # Connect to existing chat dock visibility if it exists later
    QTimer.singleShot(1000, _update_launcher_buttons)


def toggle_notebook(tab: str = "notepad") -> None:
    """Toggle the notebook dock. If opening, switch to the given tab."""
    dock = _ensure_notebook_dock()
    if dock.isVisible():
        if _notebook_panel is not None:
            # If already visible with the same tab, hide; otherwise switch tab
            if _notebook_panel.current_tab() == tab:
                dock.hide()
            else:
                _notebook_panel.switch_to(tab)
        else:
            dock.hide()
    else:
        if _notebook_panel is not None:
            _notebook_panel.switch_to(tab)
        dock.show()
        dock.raise_()
    _update_launcher_buttons()


def cleanup_sidebar() -> None:
    """Save data and clean up singletons."""
    global _launcher_dock, _notebook_dock, _notebook_panel, _launcher
    if _notebook_panel is not None:
        _notebook_panel._save_data()
    _notebook_panel = None
    _notebook_dock = None
    _launcher = None
    _launcher_dock = None
