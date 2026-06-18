"""Left sidebar panel — notepad + todo list, toggleable from a thin edge strip.

Provides a collapsible left dock that students can use to jot down ideas
or manage a quick todo list without leaving the Anki review screen.
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
)
from aqt import mw
from aqt.utils import tooltip

# ── data file path (same directory as config backup) ────────────────
_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_PATH = os.path.join(os.path.dirname(_ADDON_DIR), "anki_ai_assistant_sidebar.json")

# ── singleton references ────────────────────────────────────────────
_left_sidebar: Optional["LeftSidebar"] = None
_left_dock: Optional[QDockWidget] = None


# ═══════════════════════════════════════════════════════════════════════
# Todo item widget
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
            self._on_changed(self._index, False)  # False = toggle, not delete

    def _on_remove(self) -> None:
        if self._on_changed:
            self._on_changed(self._index, True)  # True = delete


# ═══════════════════════════════════════════════════════════════════════
# LeftSidebar — the core widget
# ═══════════════════════════════════════════════════════════════════════

class LeftSidebar(QWidget):
    """Collapsible left sidebar with notepad and todo list tabs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._collapsed = True
        self._data: dict = {"notepad": "", "todos": []}
        self._dock: Optional[QDockWidget] = None  # set by external code
        self._load_data()

        # debounce save timer
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_data)

        self._build_ui()
        self._set_collapsed(True)

    # ── build UI ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── collapsed strip ─────────────────────────────────────────
        self._strip_widget = QWidget()
        self._strip_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        # Hover effect via stylesheet
        self._strip_widget.setStyleSheet(
            "QWidget { background: #F8F9FA; border-right: 1px solid #E0E0E0; } "
            "QWidget:hover { background: #E8F0FE; border-right: 2px solid #4A90D9; }"
        )
        strip_layout = QVBoxLayout(self._strip_widget)
        strip_layout.setContentsMargins(2, 8, 2, 8)
        strip_layout.setSpacing(2)

        # thin vertical label acting as the clickable strip
        self._strip_label = QLabel("学\n习\n工\n具")
        self._strip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._strip_label.setStyleSheet(
            "QLabel { font-size: 11px; color: #888; background: transparent; "
            "padding: 4px 0px; } "
            "QWidget:hover QLabel { color: #4A90D9; }"
        )
        self._strip_label.setCursor(Qt.CursorShape.PointingHandCursor)
        strip_layout.addWidget(self._strip_label)
        strip_layout.addStretch()

        # Click on the strip to expand
        self._strip_widget.mousePressEvent = lambda e: self.toggle()
        self._strip_label.mousePressEvent = lambda e: self.toggle()

        main_layout.addWidget(self._strip_widget)

        # ── expanded panel ──────────────────────────────────────────
        self._panel_widget = QWidget()
        panel_layout = QVBoxLayout(self._panel_widget)
        panel_layout.setContentsMargins(4, 4, 4, 4)
        panel_layout.setSpacing(4)

        # top bar with collapse button
        top_bar = QHBoxLayout()
        self._collapse_btn = QPushButton("◀")
        self._collapse_btn.setFixedSize(24, 24)
        self._collapse_btn.setStyleSheet(
            "QPushButton { font-size: 12px; border: 1px solid #D0D5DD; "
            "border-radius: 4px; background: #FFF; color: #666; } "
            "QPushButton:hover { background: #F5F7FA; border-color: #4A90D9; }"
        )
        self._collapse_btn.clicked.connect(self.toggle)
        top_bar.addWidget(self._collapse_btn)

        title_label = QLabel("学习工具")
        title_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #333;")
        top_bar.addWidget(title_label)
        top_bar.addStretch()
        panel_layout.addLayout(top_bar)

        # separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #E0E0E0;")
        panel_layout.addWidget(sep)

        # tab widget
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #E0E0E0; border-radius: 4px; } "
            "QTabBar::tab { padding: 6px 12px; font-size: 12px; } "
            "QTabBar::tab:selected { background: #FFF; border-bottom: 2px solid #4A90D9; }"
        )
        self._tabs.addTab(self._build_notepad_tab(), "📝 记事本")
        self._tabs.addTab(self._build_todo_tab(), "✅ 待办")
        panel_layout.addWidget(self._tabs, 1)

        main_layout.addWidget(self._panel_widget)

    def _build_notepad_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._notepad = QTextEdit()
        self._notepad.setPlaceholderText("随时记录想法...")
        self._notepad.setStyleSheet(
            "QTextEdit { border: none; font-size: 12px; background: #FAFAFA; "
            "border-radius: 4px; padding: 6px; }"
        )
        self._notepad.textChanged.connect(self._schedule_save)
        layout.addWidget(self._notepad)

        # load saved content
        if self._data.get("notepad"):
            self._notepad.setPlainText(self._data["notepad"])

        return tab

    def _build_todo_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)
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

        # todo list
        self._todo_list = QListWidget()
        self._todo_list.setStyleSheet(
            "QListWidget { border: none; background: transparent; } "
            "QListWidget::item { border-bottom: 1px solid #F0F0F0; padding: 2px 0; }"
        )
        self._todo_list.setSpacing(1)
        layout.addWidget(self._todo_list, 1)

        # load saved todos
        self._rebuild_todo_list()

        return tab

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
        """Rebuild todo list from data, keeping undone items first."""
        self._todo_list.clear()
        todos = self._data.get("todos", [])
        # Build index mapping: (original_index, todo_dict) for display ordering
        indexed = list(enumerate(todos))
        # Sort: undone first, then done; within each group preserve original order
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
        """Handle checkbox toggle or delete for a todo item by its original index."""
        todos = self._data.get("todos", [])
        if index < 0 or index >= len(todos):
            return
        if delete:
            del todos[index]
        else:
            todos[index]["done"] = not todos[index].get("done", False)
        self._rebuild_todo_list()
        self._save_data()

    # ── collapse / expand ───────────────────────────────────────────

    def toggle(self) -> None:
        """Toggle between collapsed strip and expanded panel."""
        self._set_collapsed(not self._collapsed)
        self._schedule_save()

    def _set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._strip_widget.setVisible(collapsed)
        self._panel_widget.setVisible(not collapsed)

        if self._dock is not None:
            if collapsed:
                self._dock.setMinimumWidth(0)
                self._dock.setMaximumWidth(32)
                self._dock.resize(28, self._dock.height())
            else:
                self._dock.setMinimumWidth(260)
                self._dock.setMaximumWidth(600)
                self._dock.resize(280, self._dock.height())

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_dock(self, dock: QDockWidget) -> None:
        self._dock = dock

    # ── data persistence ────────────────────────────────────────────

    def _schedule_save(self) -> None:
        """Debounce save — collect notepad text and schedule write."""
        if hasattr(self, '_notepad') and self._notepad is not None:
            self._data["notepad"] = self._notepad.toPlainText()
        self._save_timer.start(1000)  # 1s debounce

    def _save_data(self) -> None:
        """Write current data to JSON file."""
        # Ensure latest notepad content is captured
        if hasattr(self, '_notepad') and self._notepad is not None:
            self._data["notepad"] = self._notepad.toPlainText()
        try:
            with open(_DATA_PATH, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass  # Don't crash on save failure

    def _load_data(self) -> None:
        """Load data from JSON file."""
        try:
            with open(_DATA_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._data = {"notepad": "", "todos": []}
                self._data.update(loaded)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._data = {"notepad": "", "todos": []}


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════

def toggle_left_sidebar() -> None:
    """Create or toggle the left sidebar dock widget."""
    global _left_sidebar, _left_dock

    if _left_sidebar is None:
        _left_sidebar = LeftSidebar()

    if _left_dock is None:
        _left_dock = QDockWidget("学习工具", mw)
        _left_dock.setObjectName("ai_assistant_left_sidebar")
        _left_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        # Hide the default title bar — we use our own
        _left_dock.setTitleBarWidget(QWidget())
        _left_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        _left_dock.destroyed.connect(lambda: _cleanup())
        _left_sidebar.set_dock(_left_dock)

    _left_dock.setWidget(_left_sidebar)
    mw.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, _left_dock)
    _left_dock.show()
    _left_dock.raise_()

    # Always start collapsed (thin strip visible, click to expand)
    _left_sidebar._set_collapsed(True)

    tooltip("左侧工具栏已打开（点击左侧边缘展开）")


def _cleanup() -> None:
    """Reset singleton state when dock is destroyed."""
    global _left_sidebar, _left_dock
    if _left_sidebar is not None:
        _left_sidebar._save_data()
    _left_sidebar = None
    _left_dock = None
