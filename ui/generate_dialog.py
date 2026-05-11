"""Dialog for generating Anki cards from text using AI."""

from typing import Optional

from aqt.qt import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QLabel,
    QHeaderView,
    QSplitter,
    QScrollArea,
    QFrame,
    QLineEdit,
    QThread,
    pyqtSignal,
    QGroupBox,
    QWidget,
    QApplication,
    QImage,
    QColorDialog,
    QShortcut,
    QKeySequence,
    Qt,
)
from aqt import mw
from aqt.utils import showInfo, showWarning, tooltip

def _parse_pdf_text_operators(raw: bytes) -> str:
    """Parse basic PDF text operators (Tj, TJ, ') into a string."""
    import re
    parts: list[str] = []

    for m in re.finditer(rb'\((.*?)\)\s*Tj', raw):
        parts.append(m.group(1).decode("latin-1", errors="replace"))

    for m in re.finditer(rb'\[(.*?)\]\s*TJ', raw):
        arr = m.group(1)
        for sm in re.finditer(rb'\((.*?)\)', arr):
            parts.append(sm.group(1).decode("latin-1", errors="replace"))

    for m in re.finditer(rb'\((.*?)\)\s*\'', raw):
        parts.append(m.group(1).decode("latin-1", errors="replace"))

    return "".join(parts)


from ..features.generate import generate_cards, add_cards_to_deck


class GenerateWorker(QThread):
    finished = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, text: str):
        super().__init__()
        self.text = text

    def run(self) -> None:
        try:
            cards = generate_cards(self.text)
            self.finished.emit(cards)
        except Exception as e:
            self.error_occurred.emit(str(e))


class GenerateDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 生成卡片")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)
        self._cards: list[dict[str, str]] = []
        self._worker: Optional[GenerateWorker] = None
        self._edit_row: int = -1
        self._field_editors: list[tuple[QLabel, QTextEdit]] = []
        self._shown = False
        self._build_ui()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._shown:
            self._shown = True
            self.showMaximized()

    # ═══════════════════════════════════════════════════════════════
    # UI construction
    # ═══════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(4)

        # === LEFT PANEL ===
        self._build_left_panel()

        # === RIGHT PANEL (Anki Add Card style) ===
        self._build_right_panel()

        self.main_splitter.addWidget(self.left_panel)
        self.main_splitter.addWidget(self.right_panel)
        self.main_splitter.setSizes([500, 600])
        layout.addWidget(self.main_splitter)

        self._rebuild_field_editors()

    def _build_left_panel(self) -> None:
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(6)

        # Input group
        input_group = QGroupBox("输入学习材料")
        input_layout = QVBoxLayout()
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(
            "在此粘贴学习材料（课堂笔记、课文摘录、文章段落等）...\n\n"
            "也可以点击下方按钮上传文件或图片，AI 将自动提取文字并填入此框。"
        )
        self.text_edit.setMinimumHeight(150)
        self.text_edit.installEventFilter(self)
        input_layout.addWidget(self.text_edit)

        upload_layout = QHBoxLayout()
        upload_layout.addWidget(QLabel("📎 上传文件（txt/md/pdf/图片）："))
        self.upload_btn = QPushButton("选择文件...")
        self.upload_btn.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 6px 14px; border: 1px solid #D0D5DD; "
            "border-radius: 5px; background: #FFF; color: #555; } "
            "QPushButton:hover { background: #F5F7FA; border-color: #4A90D9; }"
        )
        self.upload_btn.clicked.connect(self._upload_file)
        self.upload_btn.setMinimumHeight(30)
        upload_layout.addWidget(self.upload_btn)
        upload_layout.addStretch()
        input_layout.addLayout(upload_layout)
        input_group.setLayout(input_layout)
        left_layout.addWidget(input_group)

        # Generate button row
        gen_layout = QHBoxLayout()
        self.gen_status = QLabel("")
        self.gen_status.setStyleSheet("color: #888; font-size: 12px;")
        gen_layout.addWidget(self.gen_status)
        gen_layout.addStretch()
        self.generate_btn = QPushButton("生成卡片")
        self.generate_btn.setStyleSheet(
            "QPushButton { font-size: 14px; padding: 8px 24px; border: none; "
            "border-radius: 6px; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #5B9BD5, stop:1 #4A90D9); color: white; font-weight: bold; } "
            "QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #4A90D9, stop:1 #357ABD); } "
            "QPushButton:disabled { background: #CCC; }"
        )
        self.generate_btn.clicked.connect(self._generate)
        self.generate_btn.setMinimumHeight(38)
        gen_layout.addWidget(self.generate_btn)
        left_layout.addLayout(gen_layout)

        # Card preview table
        preview_group = QGroupBox("生成的卡片预览")
        preview_layout = QVBoxLayout()
        self.card_table = QTableWidget(0, 3)
        self.card_table.setHorizontalHeaderLabels(["", "正面（问题）", "背面（答案）"])
        header = self.card_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.card_table.setColumnWidth(0, 36)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.card_table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
        self.card_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.card_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.card_table.itemChanged.connect(lambda item: self._update_sel_count() if item.column() == 0 else None)
        preview_layout.addWidget(self.card_table)

        sel_layout = QHBoxLayout()
        self.sel_count_label = QLabel("")
        self.sel_count_label.setStyleSheet("color: #888; font-size: 11px;")
        sel_layout.addWidget(self.sel_count_label)
        sel_layout.addStretch()
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 3px 10px; border: 1px solid #D0D5DD; "
            "border-radius: 4px; background: #FFF; color: #555; } "
            "QPushButton:hover { background: #F5F7FA; border-color: #4A90D9; }"
        )
        self.select_all_btn.clicked.connect(self._select_all)
        sel_layout.addWidget(self.select_all_btn)
        self.deselect_all_btn = QPushButton("取消全选")
        self.deselect_all_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 3px 10px; border: 1px solid #D0D5DD; "
            "border-radius: 4px; background: #FFF; color: #555; } "
            "QPushButton:hover { background: #F5F7FA; border-color: #4A90D9; }"
        )
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        sel_layout.addWidget(self.deselect_all_btn)
        preview_layout.addLayout(sel_layout)
        preview_group.setLayout(preview_layout)
        left_layout.addWidget(preview_group, stretch=1)

    def _build_right_panel(self) -> None:
        self.right_panel = QWidget()
        self.right_panel.setObjectName("rightPanel")
        self.right_panel.setStyleSheet(
            "QWidget#rightPanel { background-color: #F8F9FA; border: 1px solid #E0E4E8; border-radius: 6px; }"
        )
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(12, 10, 12, 10)
        right_layout.setSpacing(8)

        # Selector row
        selector_row = QHBoxLayout()
        selector_row.setSpacing(8)
        selector_row.addWidget(QLabel("牌组:"))
        self.deck_combo = QComboBox()
        self.deck_combo.setMinimumWidth(180)
        self.deck_combo.setStyleSheet(
            "QComboBox { border: 1px solid #D0D5DD; border-radius: 5px; padding: 4px 8px; background: #FFF; }"
        )
        self._populate_decks()
        selector_row.addWidget(self.deck_combo)

        selector_row.addWidget(QLabel("笔记类型:"))
        self.note_type_combo = QComboBox()
        self.note_type_combo.setMinimumWidth(150)
        self.note_type_combo.setStyleSheet(
            "QComboBox { border: 1px solid #D0D5DD; border-radius: 5px; padding: 4px 8px; background: #FFF; }"
        )
        self._populate_note_types()
        self.note_type_combo.currentIndexChanged.connect(self._on_note_type_changed)
        selector_row.addWidget(self.note_type_combo)
        selector_row.addStretch()
        right_layout.addLayout(selector_row)

        # Format toolbar (Anki-style)
        self._build_format_toolbar()
        right_layout.addWidget(self.format_toolbar)

        # Field editor scroll area
        self.field_scroll_area = QScrollArea()
        self.field_scroll_area.setWidgetResizable(True)
        self.field_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.field_container = QWidget()
        self.field_layout = QVBoxLayout(self.field_container)
        self.field_layout.setSpacing(10)
        self.field_layout.setContentsMargins(4, 4, 4, 4)
        self.field_scroll_area.setWidget(self.field_container)
        right_layout.addWidget(self.field_scroll_area, stretch=1)

        # Tags row
        tags_widget = QWidget()
        tags_widget.setObjectName("tagsWidget")
        tags_widget.setStyleSheet(
            "QWidget#tagsWidget { background: #FFF; border: 1px solid #D0D5DD; "
            "border-radius: 6px; padding: 2px; }"
        )
        tags_layout = QHBoxLayout(tags_widget)
        tags_layout.setContentsMargins(8, 4, 8, 4)
        tags_layout.addWidget(QLabel("# 标签:"))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("添加标签，空格分隔...")
        self.tags_edit.setStyleSheet("border: none; background: transparent; font-size: 13px;")
        tags_layout.addWidget(self.tags_edit)
        right_layout.addWidget(tags_widget)

        # Bottom button row
        btn_row = QHBoxLayout()
        self.copy_btn = QPushButton("复制选中卡片")
        self.copy_btn.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 6px 14px; border: 1px solid #D0D5DD; "
            "border-radius: 5px; background: #FFF; color: #555; } "
            "QPushButton:hover { background: #F5F7FA; border-color: #4A90D9; }"
        )
        self.copy_btn.clicked.connect(self._copy_selected_card)
        self.copy_btn.setEnabled(False)
        self.copy_btn.setMinimumHeight(32)
        btn_row.addWidget(self.copy_btn)
        btn_row.addStretch()
        self.add_btn = QPushButton("添加到牌组")
        self.add_btn.setStyleSheet(
            "QPushButton { font-size: 14px; padding: 8px 24px; border: none; "
            "border-radius: 6px; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #5CB85C, stop:1 #449D44); color: white; font-weight: bold; } "
            "QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #449D44, stop:1 #398439); } "
            "QPushButton:disabled { background: #CCC; }"
        )
        self.add_btn.clicked.connect(self._add_to_deck)
        self.add_btn.setEnabled(False)
        self.add_btn.setMinimumHeight(38)
        btn_row.addWidget(self.add_btn)
        right_layout.addLayout(btn_row)

    # ═══════════════════════════════════════════════════════════════
    # Dynamic field editors
    # ═══════════════════════════════════════════════════════════════

    def _rebuild_field_editors(self) -> None:
        """Rebuild right-side field editors to match the current note type."""
        for _, editor in self._field_editors:
            editor.deleteLater()
        self._field_editors.clear()

        while self.field_layout.count():
            item = self.field_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        note_type_id = self.note_type_combo.currentData()
        if note_type_id is None:
            self.btn_cloze.setVisible(False)
            placeholder = QLabel("请选择一个笔记类型")
            placeholder.setStyleSheet("color: #999; font-size: 13px; padding: 20px;")
            self.field_layout.addWidget(placeholder)
            return

        model = mw.col.models.get(note_type_id)
        if not model:
            self.btn_cloze.setVisible(False)
            return

        is_cloze = model.get("type", 0) == 1
        self.btn_cloze.setVisible(is_cloze)

        for i, field_def in enumerate(model["flds"]):
            field_name = field_def["name"]

            field_widget = QWidget()
            fw_layout = QVBoxLayout(field_widget)
            fw_layout.setContentsMargins(0, 2, 0, 2)
            fw_layout.setSpacing(3)

            label = QLabel(field_name)
            label.setStyleSheet(
                "font-weight: bold; font-size: 13px; color: #2C3E50; padding: 2px 0;"
            )
            fw_layout.addWidget(label)

            editor = QTextEdit()
            editor.setPlaceholderText(f"输入 {field_name}...")
            if i == 1:
                editor.setMinimumHeight(160)
            elif i >= 2:
                editor.setMinimumHeight(60)
            else:
                editor.setMinimumHeight(80)
            editor.setStyleSheet(
                "QTextEdit {"
                "  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;"
                "  font-size: 14px;"
                "  background: #FFFFFF;"
                "  border: 1px solid #D0D5DD;"
                "  border-radius: 6px;"
                "  padding: 8px;"
                "  line-height: 1.5;"
                "}"
                "QTextEdit:focus {"
                "  border-color: #4A90D9;"
                "}"
            )
            editor.textChanged.connect(self._on_field_edited)
            fw_layout.addWidget(editor, stretch=1)

            self.field_layout.addWidget(field_widget)
            self._field_editors.append((label, editor))

        self.field_layout.addStretch(1)
        self._load_current_card_to_fields()

    def _load_current_card_to_fields(self) -> None:
        """Populate field editors from the currently selected card."""
        if self._edit_row < 0 or self._edit_row >= len(self._cards):
            for _, editor in self._field_editors:
                editor.blockSignals(True)
                editor.clear()
                editor.blockSignals(False)
            self.copy_btn.setEnabled(False)
            return

        card = self._cards[self._edit_row]
        for i, (_, editor) in enumerate(self._field_editors):
            editor.blockSignals(True)
            if i == 0:
                editor.setPlainText(card.get("front", ""))
            elif i == 1:
                editor.setPlainText(card.get("back", ""))
            else:
                editor.setPlainText(card.get(f"field_{i}", ""))
            editor.blockSignals(False)
        self.copy_btn.setEnabled(True)

    def _on_field_edited(self) -> None:
        """Auto-sync field editor content back to self._cards and left table."""
        if self._edit_row < 0 or self._edit_row >= len(self._cards):
            return

        sender = self.sender()
        for i, (_, editor) in enumerate(self._field_editors):
            if editor is sender:
                text = editor.toPlainText().strip()
                if i == 0:
                    self._cards[self._edit_row]["front"] = text
                    if self.card_table.item(self._edit_row, 1):
                        self.card_table.item(self._edit_row, 1).setText(text)
                elif i == 1:
                    self._cards[self._edit_row]["back"] = text
                    if self.card_table.item(self._edit_row, 2):
                        self.card_table.item(self._edit_row, 2).setText(text)
                else:
                    self._cards[self._edit_row][f"field_{i}"] = text
                break

    def _on_note_type_changed(self) -> None:
        self._rebuild_field_editors()

    # ═══════════════════════════════════════════════════════════════
    # Format toolbar
    # ═══════════════════════════════════════════════════════════════

    def _build_format_toolbar(self) -> None:
        self.format_toolbar = QWidget()
        self.format_toolbar.setObjectName("formatToolbar")
        self.format_toolbar.setStyleSheet(
            "QWidget#formatToolbar { background: #FFF; border: 1px solid #E0E4E8; "
            "border-radius: 6px; padding: 2px; }"
        )
        tb_layout = QHBoxLayout(self.format_toolbar)
        tb_layout.setContentsMargins(4, 2, 4, 2)
        tb_layout.setSpacing(3)

        btn_style = (
            "QPushButton { font-size: 13px; padding: 4px 8px; border: 1px solid transparent; "
            "border-radius: 4px; background: transparent; color: #333; min-width: 30px; } "
            "QPushButton:hover { background: #E8ECF0; border-color: #D0D5DD; } "
            "QPushButton:pressed { background: #D0D5DD; }"
        )

        btn_bold = QPushButton("B")
        btn_bold.setToolTip("加粗 (Ctrl+B)")
        btn_bold.setStyleSheet(btn_style + "QPushButton { font-weight: bold; }")
        btn_bold.clicked.connect(lambda: self._apply_md_fmt("**", "**"))
        tb_layout.addWidget(btn_bold)

        btn_italic = QPushButton("I")
        btn_italic.setToolTip("斜体 (Ctrl+I)")
        btn_italic.setStyleSheet(btn_style + "QPushButton { font-style: italic; }")
        btn_italic.clicked.connect(lambda: self._apply_md_fmt("*", "*"))
        tb_layout.addWidget(btn_italic)

        btn_underline = QPushButton("U")
        btn_underline.setToolTip("下划线")
        btn_underline.setStyleSheet(btn_style + "QPushButton { text-decoration: underline; }")
        btn_underline.clicked.connect(lambda: self._apply_md_fmt("<u>", "</u>"))
        tb_layout.addWidget(btn_underline)

        tb_layout.addWidget(self._make_tb_sep())

        self.btn_cloze = QPushButton("🔲 Cloze")
        self.btn_cloze.setToolTip("挖空 (Ctrl+Shift+C)")
        self.btn_cloze.setStyleSheet(
            btn_style + "QPushButton { color: #E8961A; font-weight: bold; }"
        )
        self.btn_cloze.clicked.connect(self._format_cloze)
        tb_layout.addWidget(self.btn_cloze)

        tb_layout.addWidget(self._make_tb_sep())

        btn_color = QPushButton("A")
        btn_color.setToolTip("字体颜色")
        btn_color.setStyleSheet(btn_style + "QPushButton { color: #4A90D9; font-weight: bold; }")
        btn_color.clicked.connect(self._format_color)
        tb_layout.addWidget(btn_color)

        btn_code = QPushButton("</>")
        btn_code.setToolTip("行内代码")
        btn_code.setStyleSheet(btn_style + "QPushButton { font-family: monospace; }")
        btn_code.clicked.connect(lambda: self._apply_md_fmt("`", "`"))
        tb_layout.addWidget(btn_code)

        btn_h = QPushButton("H")
        btn_h.setToolTip("小标题")
        btn_h.setStyleSheet(btn_style + "QPushButton { font-weight: bold; }")
        btn_h.clicked.connect(lambda: self._apply_md_fmt("\n## ", ""))
        tb_layout.addWidget(btn_h)

        tb_layout.addStretch()

        # Ctrl+Shift+C shortcut for cloze
        self._cloze_shortcut = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
        self._cloze_shortcut.activated.connect(self._format_cloze)

    @staticmethod
    def _make_tb_sep() -> QWidget:
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background: #D0D5DD; margin: 0 2px;")
        sep.setFixedHeight(22)
        return sep

    def _get_active_editor(self) -> Optional[QTextEdit]:
        """Return the currently focused field editor, or the first one."""
        w = QApplication.focusWidget()
        for _, editor in self._field_editors:
            if editor is w:
                return editor
        return None

    def _apply_md_fmt(self, prefix: str, suffix: str) -> None:
        """Wrap selected text (or cursor position) with Markdown formatting."""
        editor = self._get_active_editor()
        if editor is None:
            editor = self._field_editors[0][1] if self._field_editors else None
        if editor is None:
            return
        cursor = editor.textCursor()
        selected = cursor.selectedText()
        if selected:
            cursor.beginEditBlock()
            cursor.insertText(f"{prefix}{selected}{suffix}")
            cursor.endEditBlock()
        else:
            # Insert markers and place cursor between them
            cursor.beginEditBlock()
            cursor.insertText(f"{prefix}{suffix}")
            cursor.movePosition(cursor.MoveOperation.Left, cursor.MoveMode.MoveAnchor, len(suffix))
            cursor.endEditBlock()
            editor.setTextCursor(cursor)
        editor.setFocus()

    def _format_cloze(self) -> None:
        """Insert cloze deletion {{c1::...}}"""
        editor = self._get_active_editor()
        if editor is None:
            editor = self._field_editors[0][1] if self._field_editors else None
        if editor is None:
            return
        cursor = editor.textCursor()
        selected = cursor.selectedText()
        cursor.beginEditBlock()
        if selected:
            cursor.insertText(f"{{{{c1::{selected}}}}}")
        else:
            cursor.insertText("{{c1::}}")
            cursor.movePosition(cursor.MoveOperation.Left, cursor.MoveMode.MoveAnchor, 2)
            editor.setTextCursor(cursor)
        cursor.endEditBlock()
        editor.setFocus()

    def _format_color(self) -> None:
        """Apply color to selected text using HTML span."""
        color = QColorDialog.getColor(parent=self)
        if not color.isValid():
            return
        hex_color = color.name()
        self._apply_md_fmt(f'<span style="color:{hex_color}">', "</span>")

    # ═══════════════════════════════════════════════════════════════
    # Event filter — clipboard image paste
    # ═══════════════════════════════════════════════════════════════

    def eventFilter(self, obj, event) -> bool:
        from aqt.qt import QEvent
        if obj is self.text_edit and event.type() == QEvent.Type.KeyPress:
            is_paste = (
                event.key() == Qt.Key.Key_V
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier
            )
            if is_paste:
                if self._paste_image_from_clipboard():
                    return True
        return super().eventFilter(obj, event)

    def _paste_image_from_clipboard(self) -> bool:
        from aqt.qt import QImage
        import tempfile
        import os

        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if not mime.hasImage():
            return False

        img = mime.imageData()
        if img.isNull():
            return False

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()
        img.save(tmp_path, "PNG")

        try:
            self._load_image_file(tmp_path)
        finally:
            os.unlink(tmp_path)
        return True

    # ═══════════════════════════════════════════════════════════════
    # File upload
    # ═══════════════════════════════════════════════════════════════

    def _upload_file(self) -> None:
        from aqt.qt import QFileDialog
        import base64
        import os
        import subprocess

        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文件",
            "",
            "所有支持的文件 (*.txt *.md *.py *.json *.csv *.pdf *.png *.jpg *.jpeg *.gif *.bmp);;文本文件 (*.txt *.md);;PDF 文件 (*.pdf);;图片文件 (*.png *.jpg *.jpeg *.gif *.bmp);;所有文件 (*)"
        )
        if not path:
            return

        ext = os.path.splitext(path)[1].lower()
        self.upload_btn.setEnabled(False)
        self.gen_status.setText("读取文件中...")

        try:
            if ext in (".txt", ".md", ".py", ".json", ".csv", ".xml", ".html", ".css", ".js", ".ts"):
                self._load_text_file(path)
            elif ext == ".pdf":
                self._load_pdf_file(path)
            elif ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
                self._load_image_file(path)
            else:
                self._load_text_file(path)
        except Exception as e:
            showWarning(f"读取文件失败：{e}", parent=self)
        finally:
            self.upload_btn.setEnabled(True)
            self.gen_status.setText("")

    def _load_text_file(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        existing = self.text_edit.toPlainText()
        if existing.strip():
            content = existing + "\n\n" + content
        self.text_edit.setPlainText(content)
        tooltip(f"已加载：{len(content)} 字符")

    def _load_pdf_file(self, path: str) -> None:
        import subprocess
        import os
        import shutil

        pdftotext_bin = None
        for candidate in [
            "/opt/homebrew/bin/pdftotext",
            "/usr/local/bin/pdftotext",
        ]:
            if os.path.isfile(candidate):
                pdftotext_bin = candidate
                break
        if pdftotext_bin is None:
            pdftotext_bin = shutil.which("pdftotext")
        if pdftotext_bin is None and os.name == "nt":
            for candidate in [
                r"C:\Program Files\poppler\bin\pdftotext.exe",
                r"C:\poppler\bin\pdftotext.exe",
            ]:
                if os.path.isfile(candidate):
                    pdftotext_bin = candidate
                    break

        if pdftotext_bin is not None:
            result = subprocess.run(
                [pdftotext_bin, "-layout", path, "-"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                text = result.stdout.strip()
                existing = self.text_edit.toPlainText()
                if existing.strip():
                    text = existing + "\n\n" + text
                self.text_edit.setPlainText(text)
                tooltip(f"已提取：{len(text)} 字符")
                return

        text = self._extract_pdf_text_pure(path)
        if text:
            existing = self.text_edit.toPlainText()
            if existing.strip():
                text = existing + "\n\n" + text
            self.text_edit.setPlainText(text)
            tooltip(f"已提取：{len(text)} 字符")
            return

        images = self._extract_pdf_images(path)
        if not images:
            raise RuntimeError("PDF 中未提取到文字，也找不到嵌入图片。请尝试用截图方式。")

        self.gen_status.setText(f"扫描版 PDF，正在识别 {len(images)} 页...")
        tooltip(f"检测到扫描版 PDF，正在逐页识别（共 {len(images)} 页）...")
        all_text: list[str] = []
        for i, img_path in enumerate(images):
            self.gen_status.setText(f"正在识别第 {i + 1}/{len(images)} 页...")
            try:
                page_text = self._run_vision_ocr(img_path)
                if page_text.strip():
                    all_text.append(page_text.strip())
            finally:
                os.unlink(img_path)

        if not all_text:
            raise RuntimeError("AI 未能识别出图片中的文字")

        text = "\n\n".join(all_text)
        existing = self.text_edit.toPlainText()
        if existing.strip():
            text = existing + "\n\n" + text
        self.text_edit.setPlainText(text)
        tooltip(f"已识别 {len(images)} 页，共 {len(text)} 字符")

    def _run_vision_ocr(self, img_path: str) -> str:
        import base64
        import os

        ext = os.path.splitext(img_path)[1].lower()
        mime_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png"}
        mime = mime_map.get(ext, "jpeg")
        with open(img_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("ascii")
        data_url = f"data:image/{mime};base64,{img_b64}"

        from ..config import get_vision_config
        from ..llm.base import LLMMessage
        from ..llm.openai_compat import OpenAICompatProvider

        vc = get_vision_config()
        client = OpenAICompatProvider(base_url=vc["base_url"], api_key=vc["api_key"])
        msg = LLMMessage(
            role="user",
            content="请提取这张图片中的所有文字内容，保持原有格式。如果是表格请用 Markdown 表格格式输出。只输出文字，不要添加额外说明。",
            images=[data_url],
        )
        response = client.chat([msg], model=vc["model"], temperature=0.1, max_tokens=4096)
        return response.content.strip()

    @staticmethod
    def _extract_pdf_images(path: str) -> list[str]:
        import re
        import tempfile
        import os

        images: list[str] = []
        with open(path, "rb") as f:
            data = f.read()

        dct_pattern = re.compile(rb'/Filter\s*/DCTDecode.*?stream\r?\n(.*?)\r?\nendstream', re.DOTALL)
        for match in dct_pattern.finditer(data):
            jpeg_data = match.group(1)
            if jpeg_data[:2] == b'\xff\xd8':
                tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                tmp.write(jpeg_data)
                tmp.close()
                images.append(tmp.name)

        if not images:
            jpx_pattern = re.compile(rb'/Filter\s*/JPXDecode.*?stream\r?\n(.*?)\r?\nendstream', re.DOTALL)
            for match in jpx_pattern.finditer(data):
                jpx_data = match.group(1)
                if jpx_data[:4] == b'\x00\x00\x00\x0c':
                    tmp = tempfile.NamedTemporaryFile(suffix=".jp2", delete=False)
                    tmp.write(jpx_data)
                    tmp.close()
                    images.append(tmp.name)

        return images

    @staticmethod
    def _extract_pdf_text_pure(path: str) -> str:
        import re
        import zlib

        result: list[str] = []
        with open(path, "rb") as f:
            data = f.read()

        text_pattern = re.compile(rb'BT(.*?)ET', re.DOTALL)
        stream_pattern = re.compile(rb'stream\r?\n(.*?)\r?\nendstream', re.DOTALL)

        for match in stream_pattern.finditer(data):
            stream_data = match.group(1)
            try:
                decompressed = zlib.decompress(stream_data)
                for text_match in text_pattern.finditer(decompressed):
                    raw = text_match.group(1)
                    result.append(_parse_pdf_text_operators(raw))
            except (zlib.error, Exception):
                for text_match in text_pattern.finditer(stream_data):
                    raw = text_match.group(1)
                    result.append(_parse_pdf_text_operators(raw))

        if not result:
            for text_match in text_pattern.finditer(data):
                raw = text_match.group(1)
                result.append(_parse_pdf_text_operators(raw))

        return "\n".join(r for r in result if r.strip())

    def _load_image_file(self, path: str) -> None:
        import base64
        import os

        ext = os.path.splitext(path)[1].lower()
        mime_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif", ".bmp": "bmp", ".webp": "webp"}
        mime = mime_map.get(ext, "jpeg")

        with open(path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("ascii")
        data_url = f"data:image/{mime};base64,{img_b64}"

        from ..config import get_vision_config
        from ..llm.base import LLMMessage
        from ..llm.openai_compat import OpenAICompatProvider

        vc = get_vision_config()
        base_url = vc["base_url"]
        api_key = vc["api_key"]
        model = vc["model"]

        if not api_key:
            raise RuntimeError("请在设置中配置视觉模型 API Key")

        provider_name = vc["provider"]
        self.gen_status.setText(f"正在用 {provider_name} 视觉模型识别图片...")
        tooltip("正在用 AI 识别图片中的文字，请稍候...")

        client = OpenAICompatProvider(base_url=base_url, api_key=api_key)
        msg = LLMMessage(
            role="user",
            content="请提取这张图片中的所有文字内容，保持原有格式。如果是表格请用 Markdown 表格格式输出。只输出文字，不要添加额外说明。",
            images=[data_url],
        )
        response = client.chat(
            [msg],
            model=model,
            temperature=0.1,
            max_tokens=4096,
        )

        text = response.content.strip()
        if not text:
            raise RuntimeError("AI 未能识别出图片中的文字，请检查视觉模型是否支持图片识别")

        existing = self.text_edit.toPlainText()
        if existing.strip():
            text = existing + "\n\n" + text
        self.text_edit.setPlainText(text)
        tooltip(f"已识别：{len(text)} 字符")
        self.deck_combo.clear()
        for deck in mw.col.decks.all_names_and_ids():
            self.deck_combo.addItem(deck.name, deck.id)

    # ═══════════════════════════════════════════════════════════════
    # Deck / Note type population
    # ═══════════════════════════════════════════════════════════════

    def _populate_decks(self) -> None:
        self.deck_combo.clear()
        for deck in mw.col.decks.all_names_and_ids():
            self.deck_combo.addItem(deck.name, deck.id)

    def _populate_note_types(self) -> None:
        self.note_type_combo.clear()
        for nt in mw.col.models.all():
            self.note_type_combo.addItem(nt["name"], nt["id"])

    # ═══════════════════════════════════════════════════════════════
    # Generate cards
    # ═══════════════════════════════════════════════════════════════

    def _generate(self) -> None:
        text = self.text_edit.toPlainText().strip()
        if not text:
            showWarning("请先输入学习材料", parent=self)
            return
        if len(text) < 50:
            showWarning("文本太短，请提供更多学习材料（至少50字）", parent=self)
            return

        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("生成中...")
        self.add_btn.setEnabled(False)
        tooltip("AI 正在生成卡片，请稍候...")

        self._worker = GenerateWorker(text)
        self._worker.finished.connect(self._on_cards_generated)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    def _on_cards_generated(self, cards: list[dict[str, str]]) -> None:
        self._cards = cards
        self._edit_row = -1
        self._populate_table()
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("生成卡片")
        self.add_btn.setEnabled(True)
        self._load_current_card_to_fields()
        self._worker = None

    def _on_error(self, error: str) -> None:
        showWarning(f"生成失败：{error}", parent=self)
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("生成卡片")
        self._worker = None

    # ═══════════════════════════════════════════════════════════════
    # Table & selection
    # ═══════════════════════════════════════════════════════════════

    def _populate_table(self) -> None:
        self.card_table.setRowCount(len(self._cards))
        for i, card in enumerate(self._cards):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked)
            self.card_table.setItem(i, 0, chk)
            front_item = QTableWidgetItem(card.get("front", ""))
            back_item = QTableWidgetItem(card.get("back", ""))
            self.card_table.setItem(i, 1, front_item)
            self.card_table.setItem(i, 2, back_item)
        self.card_table.resizeRowsToContents()
        self._update_sel_count()

    def _select_all(self) -> None:
        for i in range(self.card_table.rowCount()):
            item = self.card_table.item(i, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked)
        self._update_sel_count()

    def _deselect_all(self) -> None:
        for i in range(self.card_table.rowCount()):
            item = self.card_table.item(i, 0)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)
        self._update_sel_count()

    def _update_sel_count(self) -> None:
        checked = 0
        for i in range(self.card_table.rowCount()):
            item = self.card_table.item(i, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                checked += 1
        total = self.card_table.rowCount()
        self.sel_count_label.setText(f"已勾选 {checked}/{total}")
        self.add_btn.setEnabled(checked > 0)

    def _on_selection_changed(self) -> None:
        rows: set[int] = set()
        for item in self.card_table.selectedItems():
            rows.add(item.row())
        if len(rows) == 1:
            row = next(iter(rows))
            if row < len(self._cards):
                self._edit_row = row
                self._load_current_card_to_fields()
                return
        self._edit_row = -1
        self._load_current_card_to_fields()

    def _copy_selected_card(self) -> None:
        if self._edit_row < 0 or self._edit_row >= len(self._cards):
            tooltip("请先在左侧表格中选中一张卡片")
            return
        card = self._cards[self._edit_row]
        parts = []
        for i, (label, _) in enumerate(self._field_editors):
            key = "front" if i == 0 else "back" if i == 1 else f"field_{i}"
            parts.append(f"{label.text()}：{card.get(key, '')}")
        text = "\n\n".join(parts)
        QApplication.clipboard().setText(text)
        tooltip("已复制")

    # ═══════════════════════════════════════════════════════════════
    # Add to deck
    # ═══════════════════════════════════════════════════════════════

    def _add_to_deck(self) -> None:
        # Collect checked cards
        checked = set()
        for i in range(self.card_table.rowCount()):
            item = self.card_table.item(i, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                checked.add(i)
        selected = [self._cards[i] for i in sorted(checked) if i < len(self._cards)]
        if not selected:
            showWarning("请先勾选要添加的卡片", parent=self)
            return

        deck_id = self.deck_combo.currentData()
        note_type_id = self.note_type_combo.currentData()

        if deck_id is None or note_type_id is None:
            showWarning("请选择目标牌组和笔记类型", parent=self)
            return

        model = mw.col.models.get(note_type_id)
        if not model:
            showWarning("无效的笔记类型", parent=self)
            return

        if len(model["flds"]) < 2:
            showWarning("笔记类型至少需要 2 个字段（正面 + 背面）", parent=self)
            return

        # Build dynamic field mapping
        field_mapping: dict[int, str] = {}
        for i in range(len(model["flds"])):
            if i == 0:
                field_mapping[i] = "front"
            elif i == 1:
                field_mapping[i] = "back"
            else:
                field_mapping[i] = f"field_{i}"

        tags = self.tags_edit.text().strip()

        try:
            count = add_cards_to_deck(selected, deck_id, note_type_id, field_mapping, tags)
            showInfo(f"已添加 {count} 张卡片到牌组", parent=self)
            self._cards = [c for i, c in enumerate(self._cards) if i not in checked]
            self._edit_row = -1
            self._populate_table()
            self._load_current_card_to_fields()
        except Exception as e:
            showWarning(f"添加失败：{e}", parent=self)
