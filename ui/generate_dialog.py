"""Dialog for generating Anki cards from text using AI."""

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
    QThread,
    pyqtSignal,
    QGroupBox,
    QFormLayout,
    QMessageBox,
    QApplication,
    Qt,
)
from aqt import mw
from aqt.utils import showInfo, showWarning, tooltip

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
        self.setMinimumSize(700, 750)
        self.resize(700, 800)
        self._cards: list[dict[str, str]] = []
        self._worker: GenerateWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Top: input area
        input_group = QGroupBox("输入学习材料")
        input_layout = QVBoxLayout()
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(
            "在此粘贴学习材料（课堂笔记、课文摘录、文章段落等）...\n\n"
            "AI 将自动提取关键知识点并生成问答卡片。"
        )
        self.text_edit.setMinimumHeight(200)
        input_layout.addWidget(self.text_edit)
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        # Generate button
        gen_layout = QHBoxLayout()
        self.generate_btn = QPushButton("生成卡片")
        self.generate_btn.clicked.connect(self._generate)
        self.generate_btn.setMinimumHeight(36)
        gen_layout.addStretch()
        gen_layout.addWidget(self.generate_btn)
        layout.addLayout(gen_layout)

        # Card preview table
        preview_group = QGroupBox("生成的卡片预览")
        preview_layout = QVBoxLayout()
        self.card_table = QTableWidget(0, 2)
        self.card_table.setHorizontalHeaderLabels(["正面（问题）", "背面（答案）"])
        self.card_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.card_table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
        self.card_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.card_table.itemSelectionChanged.connect(self._on_selection_changed)
        preview_layout.addWidget(self.card_table)

        # Detail view for selected card
        detail_group = QGroupBox("选中卡片详情（点击上方表格行查看，可直接复制原始内容）")
        detail_layout = QVBoxLayout()

        self.front_detail = QTextEdit()
        self.front_detail.setReadOnly(True)
        self.front_detail.setMaximumHeight(60)
        self.front_detail.setPlaceholderText("正面（问题）...")
        self.front_detail.setStyleSheet(
            "QTextEdit { font-family: 'PingFang SC', sans-serif; font-size: 13px; "
            "background: #fff; border: 1px solid #ddd; border-radius: 4px; padding: 6px; }"
        )
        detail_layout.addWidget(QLabel("正面（问题）："))
        detail_layout.addWidget(self.front_detail)

        self.back_detail = QTextEdit()
        self.back_detail.setReadOnly(True)
        self.back_detail.setMaximumHeight(120)
        self.back_detail.setPlaceholderText("背面（答案）...")
        self.back_detail.setStyleSheet(
            "QTextEdit { font-family: 'PingFang SC', sans-serif; font-size: 13px; "
            "background: #fff; border: 1px solid #ddd; border-radius: 4px; padding: 6px; }"
        )
        detail_layout.addWidget(QLabel("背面（答案）："))
        detail_layout.addWidget(self.back_detail)

        copy_btn_layout = QHBoxLayout()
        copy_btn_layout.addStretch()
        self.detail_copy_btn = QPushButton("复制选中卡片")
        self.detail_copy_btn.clicked.connect(self._copy_selected_card)
        self.detail_copy_btn.setEnabled(False)
        self.detail_copy_btn.setMinimumHeight(32)
        copy_btn_layout.addWidget(self.detail_copy_btn)
        detail_layout.addLayout(copy_btn_layout)

        detail_group.setLayout(detail_layout)
        preview_layout.addWidget(detail_group)
        preview_group.setLayout(preview_layout)
        layout.addWidget(preview_group)

        # Bottom: deck selection + add button
        bottom_layout = QHBoxLayout()

        bottom_layout.addWidget(QLabel("目标牌组:"))

        self.deck_combo = QComboBox()
        self.deck_combo.setMinimumWidth(200)
        self._populate_decks()
        bottom_layout.addWidget(self.deck_combo)

        bottom_layout.addWidget(QLabel("笔记类型:"))

        self.note_type_combo = QComboBox()
        self.note_type_combo.setMinimumWidth(150)
        self._populate_note_types()
        bottom_layout.addWidget(self.note_type_combo)

        bottom_layout.addStretch()

        self.add_btn = QPushButton("添加到牌组")
        self.add_btn.clicked.connect(self._add_to_deck)
        self.add_btn.setEnabled(False)
        self.add_btn.setMinimumHeight(36)
        bottom_layout.addWidget(self.add_btn)

        layout.addLayout(bottom_layout)

    def _populate_decks(self) -> None:
        self.deck_combo.clear()
        for deck in mw.col.decks.all_names_and_ids():
            self.deck_combo.addItem(deck.name, deck.id)

    def _populate_note_types(self) -> None:
        self.note_type_combo.clear()
        for nt in mw.col.models.all():
            self.note_type_combo.addItem(nt["name"], nt["id"])

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
        self._populate_table()
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("生成卡片")
        self.add_btn.setEnabled(True)
        self._worker = None

    def _on_error(self, error: str) -> None:
        showWarning(f"生成失败：{error}", parent=self)
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("生成卡片")
        self._worker = None

    def _populate_table(self) -> None:
        self.card_table.setRowCount(len(self._cards))
        for i, card in enumerate(self._cards):
            front_item = QTableWidgetItem(card.get("front", ""))
            back_item = QTableWidgetItem(card.get("back", ""))
            self.card_table.setItem(i, 0, front_item)
            self.card_table.setItem(i, 1, back_item)
        self.card_table.resizeRowsToContents()

    def _on_selection_changed(self) -> None:
        rows: set[int] = set()
        for item in self.card_table.selectedItems():
            rows.add(item.row())
        if len(rows) == 1:
            row = next(iter(rows))
            if row < len(self._cards):
                card = self._cards[row]
                self.front_detail.setPlainText(card.get("front", ""))
                self.back_detail.setPlainText(card.get("back", ""))
                self.detail_copy_btn.setEnabled(True)
                return
        self.front_detail.clear()
        self.back_detail.clear()
        self.detail_copy_btn.setEnabled(False)

    def _copy_selected_card(self) -> None:
        front = self.front_detail.toPlainText().strip()
        back = self.back_detail.toPlainText().strip()
        if not front and not back:
            tooltip("没有可复制的内容")
            return
        text = f"正面：{front}\n\n背面：{back}"
        QApplication.clipboard().setText(text)
        tooltip("已复制")

    def _add_to_deck(self) -> None:
        if not self._cards:
            showWarning("没有卡片可以添加", parent=self)
            return

        deck_id = self.deck_combo.currentData()
        note_type_id = self.note_type_combo.currentData()

        if deck_id is None or note_type_id is None:
            showWarning("请选择目标牌组和笔记类型", parent=self)
            return

        # Get the note type fields to map front/back
        model = mw.col.models.get(note_type_id)
        if not model:
            showWarning("无效的笔记类型", parent=self)
            return

        field_names = [f["name"] for f in model["flds"]]
        num_fields = len(field_names)

        if num_fields < 2:
            showWarning("笔记类型至少需要 2 个字段（正面 + 背面）", parent=self)
            return

        # Auto-map: first field = front, second field = back
        field_mapping = {0: "front", 1: "back"}

        try:
            count = add_cards_to_deck(self._cards, deck_id, note_type_id, field_mapping)
            showInfo(f"已添加 {count} 张卡片到牌组", parent=self)
            self._cards = []
            self.card_table.setRowCount(0)
            self.add_btn.setEnabled(False)
        except Exception as e:
            showWarning(f"添加失败：{e}", parent=self)
