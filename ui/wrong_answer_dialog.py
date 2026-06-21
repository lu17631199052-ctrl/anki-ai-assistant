"""Dialog for analyzing wrong multiple-choice questions from screenshots."""

import os
import tempfile
from typing import Optional

from aqt.qt import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPushButton,
    QComboBox,
    QLabel,
    QSplitter,
    QFrame,
    QThread,
    pyqtSignal,
    QGroupBox,
    QWidget,
    QApplication,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QGraphicsDropShadowEffect,
    QColor,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    Qt,
)
from aqt import mw
from aqt.utils import showInfo, showWarning, tooltip

from ..config import get_config, save_config
from ..features.generate import add_cards_to_deck
from ..features.wrong_answer import ensure_mcq_note_type, add_mcq_cards_to_deck, MCQ_NOTE_TYPE_NAME


class AnalyzeWorker(QThread):
    """Background thread for AI analysis of wrong-answer screenshots (single or batch)."""
    finished = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # current, total

    def __init__(self, image_paths: list[str], user_instruction: str = ""):
        super().__init__()
        self.image_paths = image_paths
        self.user_instruction = user_instruction

    def run(self) -> None:
        from ..features.wrong_answer import analyze_wrong_answer

        all_cards: list[dict[str, str]] = []
        total = len(self.image_paths)
        for i, path in enumerate(self.image_paths):
            try:
                cards = analyze_wrong_answer(path, user_instruction=self.user_instruction)
                all_cards.extend(cards)
            except Exception as e:
                # Continue with remaining pages on per-page error
                all_cards.append({
                    "front": f"第 {i + 1} 页分析失败",
                    "back": f"错误：{e}",
                })
            self.progress.emit(i + 1, total)
        self.finished.emit(all_cards)


class WrongAnswerDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 错题整理")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)
        self._cards: list[dict[str, str]] = []
        self._image_path: Optional[str] = None
        self._cleanup_paths: list[str] = []  # Multiple temp files to clean up
        self._worker: Optional[AnalyzeWorker] = None
        self._selected_deck_id = None
        self._edit_row: int = -1
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
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)

        # === LEFT: Image upload + preview ===
        self._build_left_panel()
        # === RIGHT: Result table + controls ===
        self._build_right_panel()

        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.right_panel)
        splitter.setSizes([380, 620])
        layout.addWidget(splitter)

        self._populate_decks()
        self._populate_note_types()

    def _build_left_panel(self) -> None:
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(8)

        # Image area
        img_group = QGroupBox("错题截图 / PDF")
        img_layout = QVBoxLayout()

        # Upload buttons
        btn_layout = QHBoxLayout()
        self.upload_btn = QPushButton("📷 选择截图/PDF...")
        self.upload_btn.setMinimumHeight(36)
        self.upload_btn.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 6px 16px; border: 2px dashed #C0C8D0; "
            "border-radius: 8px; background: #F8FAFB; color: #555; } "
            "QPushButton:hover { background: #EEF2F7; border-color: #4A90D9; }"
        )
        self.upload_btn.clicked.connect(self._upload_image)
        btn_layout.addWidget(self.upload_btn)

        self.paste_btn = QPushButton("📋 粘贴剪贴板图片")
        self.paste_btn.setMinimumHeight(36)
        self.paste_btn.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 6px 16px; border: 2px dashed #C0C8D0; "
            "border-radius: 8px; background: #F8FAFB; color: #555; } "
            "QPushButton:hover { background: #EEF2F7; border-color: #4A90D9; }"
        )
        self.paste_btn.clicked.connect(self._paste_image)
        btn_layout.addWidget(self.paste_btn)

        self.clear_btn = QPushButton("🗑 清除")
        self.clear_btn.setMinimumHeight(36)
        self.clear_btn.setEnabled(False)
        self.clear_btn.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 6px 14px; border: 2px dashed #E0D0D0; "
            "border-radius: 8px; background: #FDF8F8; color: #999; } "
            "QPushButton:hover { background: #FDF0F0; border-color: #E74C3C; color: #E74C3C; }"
        )
        self.clear_btn.clicked.connect(self._clear_image)
        btn_layout.addWidget(self.clear_btn)
        img_layout.addLayout(btn_layout)

        # Image preview label
        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setMinimumHeight(200)
        self.img_label.setStyleSheet(
            "QLabel { border: 1px solid #E0E4E8; border-radius: 6px; "
            "background: #FAFBFC; color: #AAA; font-size: 13px; }"
        )
        self.img_label.setText("将错题截图拖拽到上方按钮\n或点击选择 / Ctrl+V 粘贴\n\n支持单张图片或 PDF 文件")
        img_layout.addWidget(self.img_label)

        img_group.setLayout(img_layout)
        left_layout.addWidget(img_group)

        # User instruction
        instr_group = QGroupBox("💡 分析指令（可选）")
        instr_layout = QVBoxLayout()
        self.instruction_edit = QTextEdit()
        self.instruction_edit.setPlaceholderText(
            "在此输入对 AI 的额外要求，例如：\n"
            "• \"请重点分析辨证论治的思路\"\n"
            "• \"答案请用表格形式对比各选项\"\n"
            "• \"请补充相关的方剂出处和组成\"\n"
            "• \"这是一道X科目的题，请针对该科目特点分析\""
        )
        self.instruction_edit.setMinimumHeight(80)
        self.instruction_edit.setMaximumHeight(140)
        self.instruction_edit.setStyleSheet(
            "QTextEdit { border: 1px solid #E0E4E8; border-radius: 6px; "
            "padding: 8px; font-size: 12px; background: #FFF; color: #555; }"
        )
        instr_layout.addWidget(self.instruction_edit)
        instr_group.setLayout(instr_layout)
        left_layout.addWidget(instr_group)

        # Status
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")
        left_layout.addWidget(self.status_label)
        left_layout.addStretch()

    def _build_right_panel(self) -> None:
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(8)

        # Analyze button
        analyze_layout = QHBoxLayout()
        self.analyze_btn = QPushButton("🔍 AI 分析错题")
        self.analyze_btn.setMinimumHeight(40)
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; padding: 8px 24px; "
            "border: none; border-radius: 8px; background: #4A90D9; color: #FFF; } "
            "QPushButton:hover { background: #357ABD; } "
            "QPushButton:disabled { background: #C0C8D0; color: #FFF; }"
        )
        self.analyze_btn.clicked.connect(self._analyze)
        analyze_layout.addWidget(self.analyze_btn)
        analyze_layout.addStretch()
        right_layout.addLayout(analyze_layout)

        # Card preview table
        preview_group = QGroupBox("卡片预览")
        preview_layout = QVBoxLayout()

        self.card_table = QTableWidget(0, 3)
        self.card_table.setHorizontalHeaderLabels(["", "正面（问题）", "背面（答案）"])
        header = self.card_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.card_table.setColumnWidth(0, 36)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.card_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.card_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.card_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.card_table.itemChanged.connect(lambda item: self._update_sel_count() if item.column() == 0 else None)
        preview_layout.addWidget(self.card_table)

        # Selection controls
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
        right_layout.addWidget(preview_group, stretch=1)

        # Field editors for selected card
        edit_group = QGroupBox("编辑选中卡片")
        edit_layout = QVBoxLayout()

        edit_layout.addWidget(QLabel("📝 正面（题目 + 选项）："))
        self.front_edit = QTextEdit()
        self.front_edit.setPlaceholderText("在表格中选中一张卡片进行编辑...")
        self.front_edit.setMinimumHeight(100)
        self.front_edit.setStyleSheet(
            "QTextEdit { border: 1px solid #E0E4E8; border-radius: 6px; "
            "padding: 8px; font-size: 13px; background: #FFF; }"
        )
        self.front_edit.textChanged.connect(self._on_field_edited)
        edit_layout.addWidget(self.front_edit)

        edit_layout.addWidget(QLabel("✅ 背面（答案 + 解析）："))
        self.back_edit = QTextEdit()
        self.back_edit.setPlaceholderText("在表格中选中一张卡片进行编辑...")
        self.back_edit.setMinimumHeight(120)
        self.back_edit.setStyleSheet(
            "QTextEdit { border: 1px solid #E0E4E8; border-radius: 6px; "
            "padding: 8px; font-size: 13px; background: #FFF; }"
        )
        self.back_edit.textChanged.connect(self._on_field_edited)
        edit_layout.addWidget(self.back_edit)

        edit_group.setLayout(edit_layout)
        right_layout.addWidget(edit_group)

        # Bottom controls: deck / note type / add
        ctrl_layout = QHBoxLayout()

        ctrl_layout.addWidget(QLabel("牌组："))
        self.deck_btn = QPushButton("选择牌组...")
        self.deck_btn.setMinimumWidth(140)
        self.deck_btn.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 6px 12px; border: 1px solid #C0C8D0; "
            "border-radius: 6px; background: #FFF; text-align: left; } "
            "QPushButton:hover { border-color: #4A90D9; }"
        )
        self.deck_btn.clicked.connect(self._show_deck_popup)
        ctrl_layout.addWidget(self.deck_btn)

        # Deck tree popup — frameless for custom rounded styling
        self._deck_popup = QDialog(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._deck_popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        popup_layout = QVBoxLayout(self._deck_popup)
        popup_layout.setContentsMargins(0, 0, 0, 0)

        # Container frame with rounded border + shadow
        self._popup_frame = QFrame()
        self._popup_frame.setObjectName("deckPopupFrame")
        self._popup_frame.setStyleSheet(
            "#deckPopupFrame {"
            "  border: 1px solid #D0D5DD;"
            "  border-radius: 10px;"
            "  background: #FFF;"
            "}"
        )
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 60))
        self._popup_frame.setGraphicsEffect(shadow)

        frame_layout = QVBoxLayout(self._popup_frame)
        frame_layout.setContentsMargins(6, 6, 6, 6)

        self._deck_tree = QTreeWidget()
        self._deck_tree.setHeaderHidden(True)
        self._deck_tree.setIndentation(16)
        self._deck_tree.setRootIsDecorated(True)
        self._deck_tree.setAnimated(True)
        self._deck_tree.setStyleSheet(
            "QTreeWidget { border: none; background: transparent; font-size: 13px; } "
            "QTreeWidget::item { padding: 5px 8px; border-radius: 5px; } "
            "QTreeWidget::item:hover { background: #F0F4FF; } "
            "QTreeWidget::item:selected { background: #E8EDF9; color: #000; } "
        )
        self._deck_tree.itemClicked.connect(self._on_deck_item_clicked)
        self._deck_tree.itemDoubleClicked.connect(self._on_deck_item_double_clicked)
        frame_layout.addWidget(self._deck_tree)
        popup_layout.addWidget(self._popup_frame)

        ctrl_layout.addWidget(QLabel("笔记类型："))
        self.note_type_combo = QComboBox()
        self.note_type_combo.setMinimumWidth(120)
        ctrl_layout.addWidget(self.note_type_combo)

        ctrl_layout.addStretch()

        self.add_btn = QPushButton("➕ 添加到 Anki")
        self.add_btn.setMinimumHeight(38)
        self.add_btn.setEnabled(False)
        self.add_btn.setStyleSheet(
            "QPushButton { font-size: 13px; font-weight: bold; padding: 8px 20px; "
            "border: none; border-radius: 8px; background: #27AE60; color: #FFF; } "
            "QPushButton:hover { background: #1E8449; } "
            "QPushButton:disabled { background: #C0C8D0; color: #FFF; }"
        )
        self.add_btn.clicked.connect(self._add_to_anki)
        ctrl_layout.addWidget(self.add_btn)

        right_layout.addLayout(ctrl_layout)

    # ═══════════════════════════════════════════════════════════════
    # Deck / Note type
    # ═══════════════════════════════════════════════════════════════

    def _populate_decks(self) -> None:
        self._deck_tree.clear()

        item_map: dict[str, QTreeWidgetItem] = {}
        last_deck_id = get_config().get("last_deck_id")
        target_item = None

        for deck in mw.col.decks.all_names_and_ids():
            parts = deck.name.split("::")
            item = QTreeWidgetItem([parts[-1]])
            item.setData(0, Qt.ItemDataRole.UserRole, deck.id)
            item_map[deck.name] = item

            if deck.id == last_deck_id:
                target_item = item

            if "::" in deck.name:
                parent_name = deck.name.rsplit("::", 1)[0]
                parent = item_map.get(parent_name)
                if parent:
                    parent.addChild(item)
                    continue
            self._deck_tree.addTopLevelItem(item)

        self._deck_tree.sortItems(0, Qt.SortOrder.AscendingOrder)

        if target_item is not None:
            self._select_deck_item(target_item)
        else:
            self._selected_deck_id = None
            self.deck_btn.setText("选择牌组...")

    def _show_deck_popup(self) -> None:
        btn_rect = self.deck_btn.rect()

        screen = QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen is not None else None

        popup_w = max(self.deck_btn.width(), 260)
        self._deck_popup.setFixedWidth(popup_w)

        row_h = self._deck_tree.sizeHintForRow(0)
        if row_h <= 0:
            row_h = self._deck_tree.fontMetrics().height() + 10
        count = self._count_tree_items(self._deck_tree.invisibleRootItem())
        tree_h = max(min(row_h * max(count, 1) + 16, 420), 120)
        self._deck_tree.setMinimumHeight(tree_h)
        self._deck_tree.setMaximumHeight(tree_h)

        # Account for frame padding (6+6) + popup_layout margins (0)
        popup_h = tree_h + 12

        # Position above the button, fall back to below if no room
        top_pos = self.deck_btn.mapToGlobal(btn_rect.topLeft())
        above_y = top_pos.y() - popup_h
        if above_y >= 0:
            pos = top_pos
            pos.setY(above_y)
        else:
            pos = self.deck_btn.mapToGlobal(btn_rect.bottomLeft())

        # Adjust if popup would go off screen
        if screen_geo is not None:
            if pos.y() + popup_h > screen_geo.bottom():
                pos.setY(max(0, screen_geo.bottom() - popup_h))
            if pos.x() + popup_w > screen_geo.right():
                pos.setX(max(0, screen_geo.right() - popup_w))

        self._deck_popup.move(pos)
        self._deck_popup.show()

    def _count_tree_items(self, parent: QTreeWidgetItem) -> int:
        count = 0
        for i in range(parent.childCount()):
            child = parent.child(i)
            count += 1
            if child.isExpanded():
                count += self._count_tree_items(child)
        return count

    def _on_deck_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item.childCount() > 0:
            item.setExpanded(not item.isExpanded())
            return
        self._select_deck_item(item)
        self._deck_popup.hide()

    def _on_deck_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        self._select_deck_item(item)
        self._deck_popup.hide()

    def _select_deck_item(self, item: QTreeWidgetItem) -> None:
        deck_id = item.data(0, Qt.ItemDataRole.UserRole)
        if deck_id is None:
            return
        self._selected_deck_id = deck_id
        self.deck_btn.setText(item.text(0))
        self._deck_tree.setCurrentItem(item)

    def _populate_note_types(self) -> None:
        self.note_type_combo.clear()
        # Ensure MCQ note type exists
        mcq_id = ensure_mcq_note_type()
        mcq_index = 0
        for i, nt in enumerate(mw.col.models.all()):
            self.note_type_combo.addItem(nt["name"], nt["id"])
            if nt["id"] == mcq_id:
                mcq_index = i
        self.note_type_combo.setCurrentIndex(mcq_index)

    # ═══════════════════════════════════════════════════════════════
    # Keyboard shortcut for paste
    # ═══════════════════════════════════════════════════════════════

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_V and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if self._paste_image():
                return
        super().keyPressEvent(event)

    # ═══════════════════════════════════════════════════════════════
    # Image / PDF handling
    # ═══════════════════════════════════════════════════════════════

    def _upload_image(self) -> None:
        from aqt.qt import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择错题截图或 PDF",
            "",
            "图片和 PDF (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.pdf);;图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;PDF 文件 (*.pdf);;所有文件 (*)"
        )
        if not path:
            return

        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            self._load_pdf(path)
        else:
            self._set_image(path)

    def _load_pdf(self, path: str) -> None:
        """Extract images from a scanned PDF and prepare for batch analysis."""
        from ..utils.file_parser import _extract_pdf_images

        self._clear_results()

        # Clean up old temp files before loading new PDF
        for p in self._cleanup_paths:
            try:
                os.unlink(p)
            except OSError:
                pass
        self._cleanup_paths = []

        try:
            images = _extract_pdf_images(path)
        except Exception as e:
            showWarning(f"PDF 解析失败：{e}", parent=self)
            return

        if not images:
            showWarning(
                "PDF 中未找到嵌入图片。\n\n"
                "此功能适用于扫描版 PDF（每页为截图）。\n"
                "如果是文字版 PDF，请使用「AI 生成卡片」功能。",
                parent=self,
            )
            return

        # Show PDF info in preview area
        self._image_path = path
        self._cleanup_paths = images  # Track temp files for cleanup
        self.img_label.setText(f"📄 PDF 文件\n{os.path.basename(path)}\n\n共提取 {len(images)} 页图片")
        self.img_label.setStyleSheet(
            "QLabel { border: 2px solid #4A90D9; border-radius: 6px; "
            "background: #F0F4FF; color: #333; font-size: 14px; }"
        )
        self.analyze_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.status_label.setText(f"已加载 PDF：{os.path.basename(path)}，共 {len(images)} 页")
        self._cards = []
        self._edit_row = -1
        self._populate_table()
        self._load_current_card_to_fields()

    def _paste_image(self) -> bool:
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if not mime.hasImage():
            if self.sender() is self.paste_btn:
                showWarning("剪贴板中没有图片，请先截图后再粘贴", parent=self)
            return False

        img = mime.imageData()
        if img.isNull():
            if self.sender() is self.paste_btn:
                showWarning("剪贴板图片无效", parent=self)
            return False

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()
        img.save(tmp_path, "PNG")
        self._set_image(tmp_path, cleanup=[tmp_path])
        return True

    def _set_image(self, path: str, cleanup: Optional[list[str]] = None) -> None:
        """Load and display a single image, enable analyze button."""
        from aqt.qt import QPixmap

        self._clear_results()

        # Clean up old temp files when switching from PDF mode to single image
        if not cleanup:
            for p in self._cleanup_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass
            self._cleanup_paths = []

        self._image_path = path
        if cleanup:
            self._cleanup_paths = cleanup

        pixmap = QPixmap(path)
        if pixmap.isNull():
            showWarning("无法加载图片", parent=self)
            return

        # Scale to fit the label while maintaining aspect ratio
        scaled = pixmap.scaled(
            self.img_label.width() - 20,
            self.img_label.height() - 20,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.img_label.setPixmap(scaled)
        self.img_label.setStyleSheet(
            "QLabel { border: 2px solid #4A90D9; border-radius: 6px; background: #FFF; }"
        )

        self.analyze_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.status_label.setText(f"已加载：{os.path.basename(path)}")
        self._cards = []
        self._edit_row = -1
        self._populate_table()
        self._load_current_card_to_fields()

    def _clear_results(self) -> None:
        """Clear card table and editors without resetting image/file state."""
        self._cards = []
        self._edit_row = -1
        self._populate_table()
        self._load_current_card_to_fields()
        self.add_btn.setEnabled(False)

    def _clear_image(self) -> None:
        """Clear current screenshot/file and reset form state."""
        for p in self._cleanup_paths:
            try:
                os.unlink(p)
            except OSError:
                pass
        self._cleanup_paths = []
        self._image_path = None
        self._selected_deck_id = None
        self.deck_btn.setText("选择牌组...")
        self.img_label.clear()
        self.img_label.setText("将错题截图拖拽到上方按钮\n或点击选择 / Ctrl+V 粘贴\n\n支持单张图片或 PDF 文件")
        self.img_label.setStyleSheet(
            "QLabel { border: 1px solid #E0E4E8; border-radius: 6px; "
            "background: #FAFBFC; color: #AAA; font-size: 13px; }"
        )
        self.analyze_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.add_btn.setEnabled(False)
        self._cards = []
        self._edit_row = -1
        self._populate_table()
        self._load_current_card_to_fields()
        self.status_label.setText("")

    # ═══════════════════════════════════════════════════════════════
    # Analysis
    # ═══════════════════════════════════════════════════════════════

    def _analyze(self) -> None:
        # Determine image paths to analyze
        if self._cleanup_paths:
            # PDF mode: analyze all extracted images
            image_paths = list(self._cleanup_paths)
        elif self._image_path:
            # Single image mode
            image_paths = [self._image_path]
        else:
            return

        self.analyze_btn.setEnabled(False)
        self.upload_btn.setEnabled(False)
        self.paste_btn.setEnabled(False)
        self.add_btn.setEnabled(False)

        total = len(image_paths)
        if total > 1:
            self.status_label.setText(f"⏳ AI 正在分析 {total} 页错题，请稍候...")
        else:
            self.status_label.setText("⏳ AI 正在分析错题，请稍候...")
        tooltip("AI 正在分析错题，请稍候...")

        self._worker = AnalyzeWorker(image_paths, user_instruction=self.instruction_edit.toPlainText().strip())
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.error_occurred.connect(self._on_analysis_error)
        self._worker.progress.connect(self._on_analysis_progress)
        self._worker.start()

    def _on_analysis_progress(self, current: int, total: int) -> None:
        if total > 1:
            self.status_label.setText(f"⏳ AI 正在分析第 {current}/{total} 页...")

    def _on_analysis_done(self, cards: list[dict[str, str]]) -> None:
        self._cards = cards
        self._edit_row = -1
        self.analyze_btn.setEnabled(True)
        self.upload_btn.setEnabled(True)
        self.paste_btn.setEnabled(True)
        self.add_btn.setEnabled(len(cards) > 0)

        if cards:
            self._populate_table()
            self._load_current_card_to_fields()
            # Auto-select first card
            if self.card_table.rowCount() > 0:
                self.card_table.selectRow(0)
            self.status_label.setText(f"✅ 分析完成，共生成 {len(cards)} 张卡片")
            tooltip(f"分析完成，共生成 {len(cards)} 张卡片")
        else:
            self._populate_table()
            self._load_current_card_to_fields()
            self.status_label.setText("⚠️ 未生成卡片，请重试")

    def _on_analysis_error(self, error: str) -> None:
        self.analyze_btn.setEnabled(True)
        self.upload_btn.setEnabled(True)
        self.paste_btn.setEnabled(True)
        self.status_label.setText(f"❌ {error}")
        showWarning(f"分析失败：{error}", parent=self)

    # ═══════════════════════════════════════════════════════════════
    # Card table & selection
    # ═══════════════════════════════════════════════════════════════

    def _populate_table(self) -> None:
        self.card_table.setRowCount(len(self._cards))
        for i, card in enumerate(self._cards):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked)
            self.card_table.setItem(i, 0, chk)
            front_text = card.get("front", "")
            back_text = card.get("back", "")
            # Truncate for table display
            front_display = front_text.split("\n")[0][:80]
            back_display = back_text.split("\n")[0][:80]
            self.card_table.setItem(i, 1, QTableWidgetItem(front_display))
            self.card_table.setItem(i, 2, QTableWidgetItem(back_display))
        self.card_table.resizeRowsToContents()
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

    # ═══════════════════════════════════════════════════════════════
    # Card field editing
    # ═══════════════════════════════════════════════════════════════

    def _load_current_card_to_fields(self) -> None:
        """Populate field editors from the currently selected card."""
        if self._edit_row < 0 or self._edit_row >= len(self._cards):
            self.front_edit.blockSignals(True)
            self.front_edit.clear()
            self.front_edit.setPlaceholderText("在表格中选中一张卡片进行编辑...")
            self.front_edit.blockSignals(False)
            self.back_edit.blockSignals(True)
            self.back_edit.clear()
            self.back_edit.setPlaceholderText("在表格中选中一张卡片进行编辑...")
            self.back_edit.blockSignals(False)
            return

        card = self._cards[self._edit_row]
        self.front_edit.blockSignals(True)
        self.front_edit.setPlainText(card.get("front", ""))
        self.front_edit.blockSignals(False)
        self.back_edit.blockSignals(True)
        self.back_edit.setPlainText(card.get("back", ""))
        self.back_edit.blockSignals(False)

    def _on_field_edited(self) -> None:
        """Auto-sync field editor content back to self._cards and table."""
        if self._edit_row < 0 or self._edit_row >= len(self._cards):
            return

        sender = self.sender()
        card = self._cards[self._edit_row]
        if sender is self.front_edit:
            text = self.front_edit.toPlainText().strip()
            card["front"] = text
            if self.card_table.item(self._edit_row, 1):
                self.card_table.item(self._edit_row, 1).setText(text.split("\n")[0][:80])
        elif sender is self.back_edit:
            text = self.back_edit.toPlainText().strip()
            card["back"] = text
            if self.card_table.item(self._edit_row, 2):
                self.card_table.item(self._edit_row, 2).setText(text.split("\n")[0][:80])

    # ═══════════════════════════════════════════════════════════════
    # Add to Anki
    # ═══════════════════════════════════════════════════════════════

    def _add_to_anki(self) -> None:
        """Add checked cards to the selected deck."""
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

        deck_id = self._selected_deck_id
        note_type_id = self.note_type_combo.currentData()

        if not deck_id or not note_type_id:
            showWarning("请选择目标牌组和笔记类型", parent=self)
            return

        try:
            if note_type_id == ensure_mcq_note_type():
                # MCQ note type: preserve raw Markdown
                added = add_mcq_cards_to_deck(
                    selected,
                    deck_id=deck_id,
                    note_type_id=note_type_id,
                    tags="错题",
                )
            else:
                added = add_cards_to_deck(
                    selected,
                    deck_id=deck_id,
                    note_type_id=note_type_id,
                    field_mapping={0: "front", 1: "back"},
                    tags="错题",
                )
            showInfo(f"已添加 {added} 张卡片到牌组！", parent=self)
            tooltip(f"已添加 {added} 张卡片")

            cfg = get_config()
            cfg["last_deck_id"] = deck_id
            save_config(cfg)

            # Remove added cards from list
            self._cards = [c for i, c in enumerate(self._cards) if i not in checked]
            self._edit_row = -1
            self._populate_table()
            self._load_current_card_to_fields()

            # Clear everything if all cards were added
            if not self._cards:
                self._clear_image()
        except Exception as e:
            showWarning(f"添加卡片失败：{e}", parent=self)
            return

    # ═══════════════════════════════════════════════════════════════
    # Cleanup
    # ═══════════════════════════════════════════════════════════════

    def closeEvent(self, event) -> None:
        for p in self._cleanup_paths:
            try:
                os.unlink(p)
            except OSError:
                pass
        self._cleanup_paths.clear()
        super().closeEvent(event)
