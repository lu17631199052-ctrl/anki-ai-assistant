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
    Qt,
)
from aqt import mw
from aqt.utils import showInfo, showWarning, tooltip

from ..config import get_config, save_config
from ..features.generate import add_cards_to_deck
from ..features.wrong_answer import ensure_mcq_note_type, add_mcq_cards_to_deck, MCQ_NOTE_TYPE_NAME


class AnalyzeWorker(QThread):
    """Background thread for AI analysis of wrong-answer screenshots."""
    finished = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, image_path: str):
        super().__init__()
        self.image_path = image_path

    def run(self) -> None:
        from ..features.wrong_answer import analyze_wrong_answer
        try:
            cards = analyze_wrong_answer(self.image_path)
            self.finished.emit(cards)
        except Exception as e:
            self.error_occurred.emit(str(e))


class WrongAnswerDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 错题整理")
        self.setMinimumSize(900, 650)
        self.resize(1000, 750)
        self._cards: list[dict[str, str]] = []
        self._image_path: Optional[str] = None
        self._cleanup_path: Optional[str] = None
        self._worker: Optional[AnalyzeWorker] = None
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
        # === RIGHT: Result preview + controls ===
        self._build_right_panel()

        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.right_panel)
        splitter.setSizes([400, 600])
        layout.addWidget(splitter)

        self._populate_decks()
        self._populate_note_types()

    def _build_left_panel(self) -> None:
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(8)

        # Image area
        img_group = QGroupBox("错题截图")
        img_layout = QVBoxLayout()

        # Upload buttons
        btn_layout = QHBoxLayout()
        self.upload_btn = QPushButton("📷 选择截图...")
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
        self.img_label.setText("将错题截图拖拽到上方按钮\n或点击选择 / Ctrl+V 粘贴")
        img_layout.addWidget(self.img_label)

        img_group.setLayout(img_layout)
        left_layout.addWidget(img_group)

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

        # Result preview
        preview_group = QGroupBox("卡片预览")
        preview_layout = QVBoxLayout()

        # Front
        preview_layout.addWidget(QLabel("📝 正面（题目 + 选项）："))
        self.front_edit = QTextEdit()
        self.front_edit.setPlaceholderText("AI 分析后，题目和选项将显示在这里...")
        self.front_edit.setMinimumHeight(120)
        self.front_edit.setStyleSheet(
            "QTextEdit { border: 1px solid #E0E4E8; border-radius: 6px; "
            "padding: 8px; font-size: 13px; background: #FFF; }"
        )
        preview_layout.addWidget(self.front_edit)

        # Back
        preview_layout.addWidget(QLabel("✅ 背面（答案 + 解析）："))
        self.back_edit = QTextEdit()
        self.back_edit.setPlaceholderText("AI 分析后，答案和解析将显示在这里...")
        self.back_edit.setMinimumHeight(180)
        self.back_edit.setStyleSheet(
            "QTextEdit { border: 1px solid #E0E4E8; border-radius: 6px; "
            "padding: 8px; font-size: 13px; background: #FFF; }"
        )
        preview_layout.addWidget(self.back_edit)

        preview_layout.addStretch()
        preview_group.setLayout(preview_layout)
        right_layout.addWidget(preview_group)

        # Bottom controls: deck / note type / add
        ctrl_layout = QHBoxLayout()

        ctrl_layout.addWidget(QLabel("牌组："))
        self.deck_combo = QComboBox()
        self.deck_combo.setMinimumWidth(120)
        ctrl_layout.addWidget(self.deck_combo)

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
        self.deck_combo.clear()

        items = []
        for deck in mw.col.decks.all_names_and_ids():
            parts = deck.name.split("::")
            depth = len(parts) - 1
            indent = "    " * depth
            items.append((indent + parts[-1], deck.id, deck.name))

        # Sort by full name — naturally groups children under parents
        items.sort(key=lambda x: x[2])

        last_deck_id = get_config().get("last_deck_id")
        select_index = 0
        for i, (display, deck_id, _) in enumerate(items):
            self.deck_combo.addItem(display, deck_id)
            if deck_id == last_deck_id:
                select_index = i

        self.deck_combo.setCurrentIndex(select_index)

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
    # Image handling
    # ═══════════════════════════════════════════════════════════════

    def _upload_image(self) -> None:
        from aqt.qt import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择错题截图",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;所有文件 (*)"
        )
        if not path:
            return
        self._set_image(path)

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
        self._set_image(tmp_path, cleanup=tmp_path)
        return True

    def _set_image(self, path: str, cleanup: Optional[str] = None) -> None:
        """Load and display image, enable analyze button."""
        from aqt.qt import QPixmap

        self._image_path = path
        self._cleanup_path = cleanup

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
        self.front_edit.clear()
        self.back_edit.clear()
        self.add_btn.setEnabled(False)

    def _clear_image(self) -> None:
        """Clear current screenshot and reset form state."""
        if self._cleanup_path:
            try:
                os.unlink(self._cleanup_path)
            except OSError:
                pass
            self._cleanup_path = None
        self._image_path = None
        self.img_label.clear()
        self.img_label.setText("将错题截图拖拽到上方按钮\n或点击选择 / Ctrl+V 粘贴")
        self.img_label.setStyleSheet(
            "QLabel { border: 1px solid #E0E4E8; border-radius: 6px; "
            "background: #FAFBFC; color: #AAA; font-size: 13px; }"
        )
        self.analyze_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.add_btn.setEnabled(False)
        self._cards = []
        self.front_edit.clear()
        self.back_edit.clear()
        self.status_label.setText("")

    # ═══════════════════════════════════════════════════════════════
    # Analysis
    # ═══════════════════════════════════════════════════════════════

    def _analyze(self) -> None:
        if not self._image_path:
            return

        self.analyze_btn.setEnabled(False)
        self.upload_btn.setEnabled(False)
        self.paste_btn.setEnabled(False)
        self.add_btn.setEnabled(False)
        self.status_label.setText("⏳ AI 正在分析错题，请稍候...")
        tooltip("AI 正在分析错题截图，请稍候...")

        self._worker = AnalyzeWorker(self._image_path)
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.error_occurred.connect(self._on_analysis_error)
        self._worker.start()

    def _on_analysis_done(self, cards: list[dict[str, str]]) -> None:
        self._cards = cards
        self.analyze_btn.setEnabled(True)
        self.upload_btn.setEnabled(True)
        self.paste_btn.setEnabled(True)
        self.add_btn.setEnabled(True)

        if cards:
            first = cards[0]
            self.front_edit.setPlainText(first.get("front", ""))
            self.back_edit.setPlainText(first.get("back", ""))
            self.status_label.setText(f"✅ 分析完成，共生成 {len(cards)} 张卡片")
            tooltip(f"分析完成，共生成 {len(cards)} 张卡片")
        else:
            self.status_label.setText("⚠️ 未生成卡片，请重试")

    def _on_analysis_error(self, error: str) -> None:
        self.analyze_btn.setEnabled(True)
        self.upload_btn.setEnabled(True)
        self.paste_btn.setEnabled(True)
        self.status_label.setText(f"❌ {error}")
        showWarning(f"分析失败：{error}", parent=self)

    # ═══════════════════════════════════════════════════════════════
    # Add to Anki
    # ═══════════════════════════════════════════════════════════════

    def _add_to_anki(self) -> None:
        """Add the current preview card to the selected deck."""
        front = self.front_edit.toPlainText().strip()
        back = self.back_edit.toPlainText().strip()

        if not front or not back:
            showWarning("卡片正面和背面不能为空", parent=self)
            return

        deck_id = self.deck_combo.currentData()
        note_type_id = self.note_type_combo.currentData()

        if not deck_id or not note_type_id:
            showWarning("请选择目标牌组和笔记类型", parent=self)
            return

        # Build cards list from current preview (supports user edits)
        cards = [{"front": front, "back": back}]
        # Also include any additional cards from the AI result (beyond first)
        for extra in self._cards[1:]:
            cards.append(extra)

        try:
            if note_type_id == ensure_mcq_note_type():
                # MCQ note type: preserve raw Markdown
                added = add_mcq_cards_to_deck(
                    cards,
                    deck_id=deck_id,
                    note_type_id=note_type_id,
                    tags="错题",
                )
            else:
                added = add_cards_to_deck(
                    cards,
                    deck_id=deck_id,
                    note_type_id=note_type_id,
                    field_mapping={0: "front", 1: "back"},
                    tags="错题",
                )
            showInfo(f"已添加 {added} 张卡片到牌组！", parent=self)
            tooltip(f"已添加 {added} 张卡片")
        except Exception as e:
            showWarning(f"添加卡片失败：{e}", parent=self)
            return
        self._clear_image()

    # ═══════════════════════════════════════════════════════════════
    # Cleanup
    # ═══════════════════════════════════════════════════════════════

    def closeEvent(self, event) -> None:
        if hasattr(self, '_cleanup_path') and self._cleanup_path:
            try:
                os.unlink(self._cleanup_path)
            except OSError:
                pass
        super().closeEvent(event)
