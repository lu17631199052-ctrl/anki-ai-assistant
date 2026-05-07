"""Chat panel for AI study assistance — embeddable in Anki sidebar or floating."""

import re
from typing import Optional

from aqt.qt import (
    QDialog,
    QDockWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextBrowser,
    QTextEdit,
    QPushButton,
    QLabel,
    QThread,
    pyqtSignal,
    QScrollArea,
    QWidget,
    QApplication,
    QFrame,
    QSizePolicy,
    Qt,
    QTimer,
    QComboBox,
    QFormLayout,
    QDialogButtonBox,
)
from aqt import mw
from aqt.utils import showWarning, tooltip, showInfo

from ..features.chat import ChatSession

from .markdown import md_to_html

# ── singleton references ──────────────────────────────────────────
_chat_widget: Optional["ChatWidget"] = None
_dock_widget: Optional[QDockWidget] = None
_float_dialog: Optional[QDialog] = None


class StreamWorker(QThread):
    chunk_received = pyqtSignal(str)
    finished = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, session: ChatSession, message: str):
        super().__init__()
        self.session = session
        self.message = message

    def run(self) -> None:
        try:
            for chunk in self.session.send_stream(self.message):
                self.chunk_received.emit(chunk)
            self.finished.emit()
        except Exception as e:
            self.error_occurred.emit(str(e))


def _find_md_tables(text: str) -> list[str]:
    tables: list[str] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("|") and i + 1 < len(lines):
            next_stripped = lines[i + 1].strip()
            if re.match(r'^\|[\s\-:|]+\|$', next_stripped):
                tbl: list[str] = []
                tbl.append(lines[i])
                i += 1
                tbl.append(lines[i])
                i += 1
                while i < len(lines) and lines[i].strip().startswith("|"):
                    tbl.append(lines[i])
                    i += 1
                tables.append("\n".join(tbl))
                continue
        i += 1
    return tables


def _make_copy_btn(text: str, label: str = "复制") -> QPushButton:
    btn = QPushButton(label)
    btn.setStyleSheet(
        "QPushButton { font-size: 11px; padding: 2px 8px; border: 1px solid #aaa; "
        "border-radius: 3px; background: #fff; } "
        "QPushButton:hover { background: #e0e0e0; }"
    )
    btn.clicked.connect(lambda: _copy(text))
    return btn


def _copy(text: str) -> None:
    from aqt.qt import QMimeData
    mime_data = QMimeData()
    mime_data.setData("text/plain", text.encode("utf-8"))
    QApplication.clipboard().setMimeData(mime_data)
    tooltip("已复制")


def _append_to_card_back(text: str) -> None:
    reviewer = mw.reviewer
    if reviewer is None or reviewer.card is None:
        showWarning("请先在复习界面打开一张卡片", parent=mw)
        return
    note = reviewer.card.note()
    if len(note.fields) < 2:
        showWarning("当前笔记类型至少需要2个字段", parent=mw)
        return
    existing = note.fields[1]
    if existing.strip():
        note.fields[1] = existing + "\n\n" + text.strip()
    else:
        note.fields[1] = text.strip()
    mw.col.update_note(note)
    tooltip("已写入卡片背面")


def _make_write_back_btn(text: str, label: str = "写入背面") -> QPushButton:
    btn = QPushButton(label)
    btn.setStyleSheet(
        "QPushButton { font-size: 11px; padding: 2px 8px; border: 1px solid #f90; "
        "border-radius: 3px; background: #fff3e0; color: #e65100; } "
        "QPushButton:hover { background: #ffe0b2; }"
    )
    btn.clicked.connect(lambda: _append_to_card_back(text))
    return btn


class QuickCardDialog(QDialog):
    """Compact dialog to quickly create a card from chat content."""

    def __init__(self, raw_content: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("快速创建卡片")
        self.setMinimumWidth(450)
        self.raw_content = raw_content
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.front_edit = QTextEdit()
        self.front_edit.setMaximumHeight(80)
        self.front_edit.setPlaceholderText("输入卡片的问题...")
        first_line = self.raw_content.strip().split("\n")[0]
        if len(first_line) > 60:
            first_line = first_line[:60] + "..."
        self.front_edit.setPlainText(first_line)
        form.addRow("正面（问题）:", self.front_edit)
        self.back_edit = QTextEdit()
        self.back_edit.setPlainText(self.raw_content.strip())
        form.addRow("背面（答案）:", self.back_edit)
        from ..config import get_config
        cfg = get_config()
        self.deck_combo = QComboBox()
        for deck in mw.col.decks.all_names_and_ids():
            self.deck_combo.addItem(deck.name, deck.id)
        default_deck = cfg.get("default_deck", "")
        if default_deck:
            idx = self.deck_combo.findData(default_deck)
        else:
            idx = -1
        if idx < 0 and mw.reviewer and mw.reviewer.card:
            idx = self.deck_combo.findData(mw.reviewer.card.current_deck_id())
        if idx >= 0:
            self.deck_combo.setCurrentIndex(idx)
        form.addRow("牌组:", self.deck_combo)
        self.note_type_combo = QComboBox()
        for nt in mw.col.models.all():
            self.note_type_combo.addItem(nt["name"], nt["id"])
        default_nt = cfg.get("default_note_type", "")
        if default_nt:
            idx = self.note_type_combo.findData(default_nt)
            if idx >= 0:
                self.note_type_combo.setCurrentIndex(idx)
        form.addRow("笔记类型:", self.note_type_combo)
        layout.addLayout(form)
        buttons = QDialogButtonBox()
        add_btn = buttons.addButton("添加", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._add_card)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_card(self) -> None:
        front = self.front_edit.toPlainText().strip()
        back = self.back_edit.toPlainText().strip()
        if not front or not back:
            showWarning("正面和背面都不能为空", parent=self)
            return
        from ..config import get_config
        if get_config().get("md_to_html", False):
            front = md_to_html(front)
            back = md_to_html(back)
        else:
            front = front.replace("\n", "<br>")
            back = back.replace("\n", "<br>")
        deck_id = self.deck_combo.currentData()
        note_type_id = self.note_type_combo.currentData()
        model = mw.col.models.get(note_type_id)
        if not model:
            showWarning("无效的笔记类型", parent=self)
            return
        from anki.notes import Note
        note = Note(mw.col, model)
        note.fields[0] = front
        if len(note.fields) > 1:
            note.fields[1] = back
        try:
            mw.col.add_note(note, deck_id)
            showInfo("卡片已添加", parent=self)
            self.accept()
        except Exception as e:
            showWarning(f"添加失败: {e}", parent=self)


def _make_card_btn(raw_text: str) -> QPushButton:
    btn = QPushButton("创建卡片")
    btn.setStyleSheet(
        "QPushButton { font-size: 11px; padding: 2px 8px; border: 1px solid #4a9; "
        "border-radius: 3px; background: #e8f5e9; color: #2e7d32; } "
        "QPushButton:hover { background: #c8e6c9; }"
    )
    btn.clicked.connect(lambda: QuickCardDialog(raw_text, mw).exec())
    return btn


# ═══════════════════════════════════════════════════════════════════
# ChatWidget — the core chat UI (QWidget, not QDialog)
# ═══════════════════════════════════════════════════════════════════

class ChatWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = ChatSession()
        self._worker: Optional[StreamWorker] = None
        self._current_ai_raw = ""
        self._message_widgets: list[QWidget] = []
        self._pending_message: str = ""
        self._is_sidebar = True
        self._build_ui()
        self._attach_card_context()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Top bar
        top_bar = QHBoxLayout()
        self.context_label = QLabel("")
        self.context_label.setWordWrap(True)
        self.context_label.setStyleSheet("color: #666; font-size: 11px; padding: 2px;")
        top_bar.addWidget(self.context_label, 1)
        self.dock_btn = QPushButton("⬆ 弹出窗口")
        self.dock_btn.setStyleSheet(
            "QPushButton { font-size: 10px; padding: 2px 4px; border: 1px solid #aaa; "
            "border-radius: 3px; background: #fff; } "
            "QPushButton:hover { background: #e0e0e0; }"
        )
        self.dock_btn.clicked.connect(self._toggle_mode)
        top_bar.addWidget(self.dock_btn)
        layout.addLayout(top_bar)

        # Scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.msg_container = QWidget()
        self.msg_layout = QVBoxLayout(self.msg_container)
        self.msg_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.msg_layout.addStretch()
        self.scroll_area.setWidget(self.msg_container)
        layout.addWidget(self.scroll_area, 1)

        # Input area
        input_layout = QHBoxLayout()
        self.input_edit = QTextEdit()
        self.input_edit.setMaximumHeight(80)
        self.input_edit.setPlaceholderText("输入问题... (Ctrl+Enter 发送)")
        self.input_edit.installEventFilter(self)
        input_layout.addWidget(self.input_edit)

        btn_layout = QVBoxLayout()
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self._send)
        self.send_btn.setMinimumHeight(36)
        btn_layout.addWidget(self.send_btn)

        self.copy_btn = QPushButton("复制全文")
        self.copy_btn.clicked.connect(self._copy_full)
        self.copy_btn.setMinimumHeight(26)
        btn_layout.addWidget(self.copy_btn)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self._clear)
        btn_layout.addWidget(self.clear_btn)
        input_layout.addLayout(btn_layout)
        layout.addLayout(input_layout)

    def eventFilter(self, obj, event) -> bool:
        from aqt.qt import QEvent
        if obj is self.input_edit and event.type() == QEvent.Type.KeyPress:
            if (
                event.key() == Qt.Key.Key_Return
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier
            ):
                self._send()
                return True
        return super().eventFilter(obj, event)

    def _copy_full(self) -> None:
        text = self._current_ai_raw.strip()
        if not text:
            tooltip("没有可复制的内容")
            return
        QApplication.clipboard().setText(text)
        tooltip("已复制全文")

    def _attach_card_context(self) -> None:
        reviewer = mw.reviewer
        if reviewer is None or reviewer.card is None:
            self.context_label.setText("（当前没有打开的卡片）")
            return
        card = reviewer.card
        note = card.note()
        fields = list(note.items())
        front = fields[0][1].strip() if fields else ""
        back = fields[1][1].strip() if len(fields) > 1 else front
        self.session.set_card_context(front, back)
        self.context_label.setText(f"当前卡片：{front[:60]}{'...' if len(front) > 60 else ''}")

    def _send(self) -> None:
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        if self._worker and self._worker.isRunning():
            self._pending_message = text
            self.input_edit.clear()
            self.input_edit.setPlaceholderText("上一条生成中，消息已排队...")
            return
        self.send_btn.setEnabled(False)
        self._add_user_message(text)
        self.input_edit.clear()
        self.input_edit.setPlaceholderText("AI 生成中... (可继续输入排队)")
        self._current_ai_raw = ""
        self._add_ai_message_placeholder()
        self._worker = StreamWorker(self.session, text)
        self._worker.chunk_received.connect(self._on_chunk)
        self._worker.finished.connect(self._on_finished)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    def _on_chunk(self, chunk: str) -> None:
        self._current_ai_raw += chunk
        self._update_last_ai_message()

    def _on_finished(self) -> None:
        self._update_last_ai_message()
        self.send_btn.setEnabled(True)
        self.input_edit.setFocus()
        self.input_edit.setPlaceholderText("输入问题... (Ctrl+Enter 发送)")
        self._worker = None
        pending = self._pending_message
        self._pending_message = ""
        if pending:
            self._send()

    def _on_error(self, error: str) -> None:
        self._current_ai_raw += f'\n\n❌ 错误: {error}'
        self._update_last_ai_message()
        self.send_btn.setEnabled(True)
        self.input_edit.setPlaceholderText("输入问题... (Ctrl+Enter 发送)")
        self._worker = None
        pending = self._pending_message
        self._pending_message = ""
        if pending:
            self._send()

    # ── Message widgets ──────────────────────────────────────────

    def _add_user_message(self, content: str) -> None:
        label = QLabel(
            f'<div style="font-size:13px;"><b style="color:#1a73e8;">🧑 你</b></div>'
            f'<div style="margin:4px 0 0 12px; font-size:13px;">{content}</div>'
        )
        label.setWordWrap(True)
        label.setStyleSheet("background: #f5f5f5; border-radius: 8px; padding: 8px; margin: 2px 20px 2px 0;")
        self._insert_before_stretch(label)
        self._message_widgets.append(label)

    def _add_ai_message_placeholder(self) -> QWidget:
        container = QWidget()
        container.setStyleSheet("background: #f0f7ff; border-radius: 8px; padding: 8px; margin: 2px 0 2px 10px;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        header = QLabel('<b style="color:#34a853;">🤖 AI</b>')
        layout.addWidget(header)
        content_area = QWidget()
        cl = QVBoxLayout(content_area)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        layout.addWidget(content_area)
        container._content_layout = cl  # type: ignore
        self._insert_before_stretch(container)
        self._message_widgets.append(container)
        return container

    def _update_last_ai_message(self) -> None:
        if not self._message_widgets:
            return
        last = self._message_widgets[-1]
        cl = getattr(last, '_content_layout', None)
        if cl is None:
            self._add_ai_message_placeholder()
            return
        while cl.count():
            item = cl.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._current_ai_raw.strip():
            return
        raw_text = self._current_ai_raw.strip()

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setReadOnly(True)
        browser.setFrameShape(QFrame.Shape.NoFrame)
        browser.setStyleSheet("border: none; background: transparent;")
        browser.setHtml(md_to_html(raw_text))
        browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        browser.document().setDocumentMargin(4)
        cl.addWidget(browser)

        tables = _find_md_tables(raw_text)
        if tables:
            sep = QLabel('<hr style="border:none; border-top:1px dashed #ccc; margin:6px 0;">')
            cl.addWidget(sep)
            for idx, tbl in enumerate(tables):
                tbl_widget = QWidget()
                tbl_layout = QHBoxLayout(tbl_widget)
                tbl_layout.setContentsMargins(0, 2, 0, 2)
                tbl_layout.setSpacing(4)
                tbl_label = QLabel(f"<b style='color:#888;'>原始 Markdown 表格 {idx + 1}:</b>")
                tbl_layout.addWidget(tbl_label)
                tbl_layout.addStretch()
                tbl_layout.addWidget(_make_write_back_btn(tbl, f"写入背面 {idx + 1}"))
                tbl_layout.addWidget(_make_copy_btn(tbl, f"复制表格 {idx + 1}"))
                cl.addWidget(tbl_widget)
                raw_edit = QTextEdit()
                raw_edit.setPlainText(tbl)
                raw_edit.setReadOnly(True)
                raw_edit.setMaximumHeight(100)
                raw_edit.setStyleSheet(
                    "QTextEdit { font-family: monospace; font-size: 11px; "
                    "background: #fafafa; border: 1px solid #ddd; border-radius: 4px; padding: 4px; }"
                )
                cl.addWidget(raw_edit)

        btn_row = QWidget()
        btn_row_layout = QHBoxLayout(btn_row)
        btn_row_layout.setContentsMargins(0, 4, 0, 0)
        btn_row_layout.addStretch()
        btn_row_layout.addWidget(_make_write_back_btn(raw_text, "写入全文到背面"))
        btn_row_layout.addWidget(_make_card_btn(raw_text))
        cl.addWidget(btn_row)
        self._scroll_to_bottom()

    def _insert_before_stretch(self, widget: QWidget) -> None:
        count = self.msg_layout.count()
        if count > 0:
            self.msg_layout.takeAt(count - 1)
        self.msg_layout.addWidget(widget)
        self.msg_layout.addStretch()

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(50, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))

    def _clear(self) -> None:
        self.session = ChatSession()
        self.session.set_card_context("", "")
        self._current_ai_raw = ""
        self._pending_message = ""
        while self.msg_layout.count() > 1:
            item = self.msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._message_widgets.clear()
        self._attach_card_context()
        self.input_edit.setPlaceholderText("输入问题... (Ctrl+Enter 发送)")

    # ── Sidebar / Float toggle ────────────────────────────────────

    def _toggle_mode(self) -> None:
        """Switch between sidebar and floating window."""
        if self._is_sidebar:
            self._undock_to_window()
        else:
            self._dock_to_sidebar()

    def _dock_to_sidebar(self) -> None:
        global _float_dialog, _dock_widget
        self._is_sidebar = True
        self.dock_btn.setText("⬆ 弹出窗口")
        # Close floating dialog
        if _float_dialog is not None:
            _float_dialog.hide()
            _float_dialog = None
        # Show dock widget
        if _dock_widget is not None:
            _dock_widget.setWidget(self)
            _dock_widget.show()
            _dock_widget.raise_()

    def _undock_to_window(self) -> None:
        global _float_dialog, _dock_widget
        self._is_sidebar = False
        self.dock_btn.setText("📌 固定到右侧")
        # Remove from dock
        if _dock_widget is not None:
            self.setParent(None)
            _dock_widget.hide()
        # Create floating dialog
        _float_dialog = QDialog(mw)
        _float_dialog.setWindowTitle("AI 学习助手")
        _float_dialog.setMinimumSize(380, 500)
        _float_dialog.resize(420, 700)
        layout = QVBoxLayout(_float_dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self)
        _float_dialog.show()


# ═══════════════════════════════════════════════════════════════════
# Public API — create / toggle chat panel
# ═══════════════════════════════════════════════════════════════════

def _open_chat() -> None:
    """Open the chat panel — either as sidebar or floating window."""
    global _chat_widget, _dock_widget

    if _chat_widget is None:
        _chat_widget = ChatWidget()

    # Default: show as sidebar docked to Anki's right side
    if _dock_widget is None:
        _dock_widget = QDockWidget("AI 学习助手", mw)
        _dock_widget.setObjectName("ai_assistant_chat_dock")
        _dock_widget.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        _dock_widget.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        # When dock is closed by the X button, clean up
        _dock_widget.destroyed.connect(lambda: _cleanup())

    _dock_widget.setWidget(_chat_widget)
    mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, _dock_widget)
    _chat_widget._is_sidebar = True
    _chat_widget.dock_btn.setText("⬆ 弹出窗口")
    _dock_widget.show()
    _dock_widget.raise_()


def _cleanup() -> None:
    """Reset singleton state when dock is destroyed."""
    global _chat_widget, _dock_widget, _float_dialog
    if _float_dialog is not None:
        _float_dialog.close()
        _float_dialog = None
    _chat_widget = None
    _dock_widget = None
