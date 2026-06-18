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
)
from aqt import mw
from aqt.utils import tooltip

# ── data file path (same directory as config backup) ────────────────
_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_PATH = os.path.join(os.path.dirname(_ADDON_DIR), "anki_ai_assistant_sidebar.json")

# ── singleton references ────────────────────────────────────────────
_launcher_dock: Optional[QDockWidget] = None
_notebook_dock: Optional[QDockWidget] = None
_notebook_panel: Optional["NotebookPanel"] = None
_launcher: Optional["LauncherWidget"] = None

# ── style constants ─────────────────────────────────────────────────
_LAUNCHER_WIDTH = 44
_ICON_SIZE = 32


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
        done = state == Qt.CheckState.Checked.value
        self._update_label_style(done)
        if self._on_changed:
            self._on_changed(self._index, False)

    def _on_remove(self) -> None:
        if self._on_changed:
            self._on_changed(self._index, True)


# ═══════════════════════════════════════════════════════════════════════
# LauncherWidget — fixed left icon strip
# ═══════════════════════════════════════════════════════════════════════

class LauncherWidget(QWidget):
    """Fixed-width icon bar docked on the left, always visible."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LauncherContent")
        self.setFixedWidth(_LAUNCHER_WIDTH)
        self._buttons: dict[str, QPushButton] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 10, 4, 10)
        layout.setSpacing(6)

        layout.addStretch(1)

        # ── icon definitions: (key, emoji, tooltip) ────────────────
        icons = [
            ("notebook", "📝", "记事本"),
            ("todo",     "✅", "待办清单"),
            ("chat",     "💬", "AI 对话"),
        ]

        for key, emoji, tooltip_text in icons:
            btn = self._create_icon_button(emoji, tooltip_text)
            btn.clicked.connect(self._make_handler(key))
            layout.addWidget(btn)
            self._buttons[key] = btn

        layout.addStretch(1)

        # bottom separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #DDD; margin: 4px 2px;")
        layout.addWidget(sep)

        # settings gear at bottom
        settings_btn = self._create_icon_button("⚙", "设置")
        settings_btn.clicked.connect(self._open_settings)
        layout.addWidget(settings_btn)
        self._buttons["settings"] = settings_btn

    def _create_icon_button(self, emoji: str, tooltip_text: str) -> QPushButton:
        btn = QPushButton(emoji)
        btn.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        btn.setToolTip(tooltip_text)
        btn.setFlat(True)
        btn.setCheckable(True)
        btn.setStyleSheet(
            "QPushButton { font-size: 18px; border: none; border-radius: 6px; "
            "background: transparent; } "
            "QPushButton:hover { background: #E8F0FE; } "
            "QPushButton:checked { background: #D3E3FD; }"
        )
        return btn

    def _make_handler(self, key: str) -> Callable:
        def handler():
            if key == "notebook":
                toggle_notebook(tab="notepad")
            elif key == "todo":
                toggle_notebook(tab="todo")
            elif key == "chat":
                _toggle_chat()
        return handler

    def _open_settings(self) -> None:
        from .settings import SettingsDialog
        dialog = SettingsDialog(mw)
        dialog.show()

    def set_active(self, key: str, active: bool) -> None:
        """Set the checked state of an icon button."""
        btn = self._buttons.get(key)
        if btn and btn.isCheckable():
            btn.setChecked(active)

    def apply_theme(self) -> None:
        """Re-apply stylesheet (for night mode support)."""
        night = mw.pm.night_mode() if mw and hasattr(mw, 'pm') else False
        if night:
            bg = "#2C2C2C"
            hover = "#3A3A3A"
            active = "#4A4A4A"
            sep = "#444"
        else:
            bg = "#F5F6F8"
            hover = "#E8F0FE"
            active = "#D3E3FD"
            sep = "#DDD"
        self.setStyleSheet(f"QWidget#LauncherContent {{ background: {bg}; }}")
        for key, btn in self._buttons.items():
            btn.setStyleSheet(
                f"QPushButton {{ font-size: 18px; border: none; border-radius: 6px; "
                f"background: transparent; }} "
                f"QPushButton:hover {{ background: {hover}; }} "
                f"QPushButton:checked {{ background: {active}; }}"
            )
        # Update separator colour
        for child in self.findChildren(QFrame):
            child.setStyleSheet(
                f"border: none; border-top: 1px solid {sep}; margin: 4px 2px;"
            )


# ═══════════════════════════════════════════════════════════════════════
# NotebookPanel — the content panel (notepad + todo tabs)
# ═══════════════════════════════════════════════════════════════════════

class NotebookPanel(QWidget):
    """Right-side panel with Notepad and Todo tabs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: dict = {"notepad": "", "todos": []}
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
            "QTabBar::tab { padding: 6px 14px; font-size: 12px; } "
            "QTabBar::tab:selected { background: #FFF; border-bottom: 2px solid #4A90D9; }"
        )
        self._tabs.addTab(self._build_notepad_tab(), "📝 记事本")
        self._tabs.addTab(self._build_todo_tab(), "✅ 待办")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs, 1)

    def _build_notepad_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._notepad = QTextEdit()
        self._notepad.setPlaceholderText("随时记录想法...")
        self._notepad.setStyleSheet(
            "QTextEdit { border: none; font-size: 13px; background: #FAFAFA; "
            "border-radius: 4px; padding: 8px; }"
        )
        self._notepad.textChanged.connect(self._schedule_save)
        layout.addWidget(self._notepad)

        if self._data.get("notepad"):
            self._notepad.setPlainText(self._data["notepad"])

        return tab

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
        if hasattr(self, '_notepad') and self._notepad is not None:
            self._data["notepad"] = self._notepad.toPlainText()
        self._save_timer.start(1000)

    def _save_data(self) -> None:
        if hasattr(self, '_notepad') and self._notepad is not None:
            self._data["notepad"] = self._notepad.toPlainText()
        try:
            with open(_DATA_PATH, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _load_data(self) -> None:
        try:
            with open(_DATA_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._data = {"notepad": "", "todos": []}
                self._data.update(loaded)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._data = {"notepad": "", "todos": []}


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
