"""Quiz player dialog — AI-generated practice questions from deck content."""

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
    QTreeWidget,
    QTreeWidgetItem,
    QGraphicsDropShadowEffect,
    QColor,
    QSpinBox,
    QScrollArea,
    QApplication,
    Qt,
)
from aqt import mw
from aqt.utils import showInfo, showWarning, tooltip

from ..config import get_config, save_config
from ..features.quiz_generator import generate_quizzes, read_deck_group_notes, count_notes_in_deck


# ═══════════════════════════════════════════════════════════════════
# Background worker for AI generation
# ═══════════════════════════════════════════════════════════════════

class QuizWorker(QThread):
    """Background thread for AI quiz generation."""
    finished = pyqtSignal(list)          # list[dict] questions
    error_occurred = pyqtSignal(str)     # error message
    progress = pyqtSignal(str)           # status message

    def __init__(
        self,
        deck_prefix: str,
        num_questions: int,
        question_type: str,
        custom_instruction: str,
    ):
        super().__init__()
        self.deck_prefix = deck_prefix
        self.num_questions = num_questions
        self.question_type = question_type
        self.custom_instruction = custom_instruction

    def run(self) -> None:
        try:
            questions = generate_quizzes(
                deck_prefix=self.deck_prefix,
                num_questions=self.num_questions,
                question_type=self.question_type,
                custom_instruction=self.custom_instruction,
                progress_callback=lambda msg: self.progress.emit(msg),
            )
            self.finished.emit(questions)
        except Exception as e:
            self.error_occurred.emit(str(e))


# ═══════════════════════════════════════════════════════════════════
# Main Dialog
# ═══════════════════════════════════════════════════════════════════

class QuizGeneratorDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(None)  # Independent window
        self.setWindowTitle("AI 出题")
        self.setMinimumSize(800, 600)
        self.resize(1000, 750)

        # State
        self._questions: list[dict[str, str]] = []
        self._current_index: int = 0
        self._answers: dict[int, str] = {}         # question_index -> selected_option
        self._worker: Optional[QuizWorker] = None
        self._selected_deck_prefix: str = ""
        self._shown = False

        self._build_ui()
        self._populate_decks()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._shown:
            self._shown = True
            self.showMaximized()

    # ═══════════════════════════════════════════════════════════════
    # UI construction
    # ═══════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        """Build the complete dialog UI with stacked layout for setup/quiz/results."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # --- Title ---
        title = QLabel("🧠 AI 出题 — 从牌组生成练习题目")
        title.setStyleSheet(
            "QLabel { font-size: 18px; font-weight: bold; color: #1a1a2e; padding: 4px 0; }"
        )
        outer.addWidget(title)

        # --- Stacked content ---
        self._stack = QVBoxLayout()
        outer.addLayout(self._stack)

        # Build each "page"
        self._build_setup_page()
        self._build_quiz_page()
        self._build_results_page()

        # Show setup by default
        self._show_setup_page()

    # ── Setup page ────────────────────────────────────────────────

    def _build_setup_page(self) -> None:
        self._setup_widget = QWidget()
        layout = QVBoxLayout(self._setup_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Deck picker
        deck_group = QGroupBox("📚 选择牌组组")
        deck_layout = QVBoxLayout()

        deck_row = QHBoxLayout()
        deck_row.addWidget(QLabel("牌组："))
        self.deck_btn = QPushButton("选择牌组组...")
        self.deck_btn.setMinimumWidth(280)
        self.deck_btn.setMinimumHeight(34)
        self.deck_btn.setStyleSheet(
            "QPushButton { font-size: 14px; padding: 6px 14px; border: 1px solid #C0C8D0; "
            "border-radius: 6px; background: #FFF; text-align: left; } "
            "QPushButton:hover { border-color: #4A90D9; }"
        )
        self.deck_btn.clicked.connect(self._show_deck_popup)
        deck_row.addWidget(self.deck_btn)
        deck_row.addStretch()
        deck_layout.addLayout(deck_row)

        # Deck tree popup
        self._deck_popup = QDialog(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._deck_popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        popup_layout = QVBoxLayout(self._deck_popup)
        popup_layout.setContentsMargins(0, 0, 0, 0)
        self._popup_frame = QFrame()
        self._popup_frame.setObjectName("deckPopupFrame")
        self._popup_frame.setStyleSheet(
            "#deckPopupFrame { border: 1px solid #D0D5DD; border-radius: 10px; background: #FFF; }"
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

        deck_group.setLayout(deck_layout)
        layout.addWidget(deck_group)

        # Settings
        settings_group = QGroupBox("⚙️ 出题设置")
        settings_layout = QHBoxLayout()

        settings_layout.addWidget(QLabel("题目数量："))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(5, 50)
        self.count_spin.setValue(get_config().get("quiz_default_count", 10))
        self.count_spin.setMinimumWidth(70)
        settings_layout.addWidget(self.count_spin)

        settings_layout.addSpacing(20)
        settings_layout.addWidget(QLabel("题目类型："))
        self.type_combo = QComboBox()
        self.type_combo.addItem("鉴别型（重点区分相似疾病）", "differentiating")
        self.type_combo.addItem("单一疾病型（考察单个疾病知识）", "single_disease")
        self.type_combo.addItem("混合型", "mixed")
        default_type = get_config().get("quiz_question_type", "differentiating")
        for i in range(self.type_combo.count()):
            if self.type_combo.itemData(i) == default_type:
                self.type_combo.setCurrentIndex(i)
                break
        settings_layout.addWidget(self.type_combo)
        settings_layout.addStretch()

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # Custom instruction
        instr_group = QGroupBox("💡 额外要求（可选）")
        instr_layout = QVBoxLayout()
        self.instruction_edit = QTextEdit()
        self.instruction_edit.setPlaceholderText(
            "在此输入对 AI 的额外要求，例如：\n"
            "• \"请重点出病机和治则方面的题目\"\n"
            "• \"请多出一些涉及方剂的题目\"\n"
            "• \"请生成表格对比类的题目\""
        )
        self.instruction_edit.setMaximumHeight(80)
        self.instruction_edit.setStyleSheet(
            "QTextEdit { border: 1px solid #E0E4E8; border-radius: 6px; "
            "padding: 8px; font-size: 13px; background: #FFF; }"
        )
        instr_layout.addWidget(self.instruction_edit)
        instr_group.setLayout(instr_layout)
        layout.addWidget(instr_group)

        # Buttons
        btn_row = QHBoxLayout()
        self.read_btn = QPushButton("📖 读取牌组内容")
        self.read_btn.setMinimumHeight(42)
        self.read_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; padding: 8px 20px; "
            "border: none; border-radius: 8px; background: #4A90D9; color: #FFF; } "
            "QPushButton:hover { background: #357ABD; } "
            "QPushButton:disabled { background: #C0C8D0; color: #FFF; }"
        )
        self.read_btn.clicked.connect(self._on_read_deck)
        btn_row.addWidget(self.read_btn)

        self.generate_btn = QPushButton("🤖 AI 生成题目")
        self.generate_btn.setMinimumHeight(42)
        self.generate_btn.setEnabled(False)
        self.generate_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; padding: 8px 20px; "
            "border: none; border-radius: 8px; background: #27AE60; color: #FFF; } "
            "QPushButton:hover { background: #1E8449; } "
            "QPushButton:disabled { background: #C0C8D0; color: #FFF; }"
        )
        self.generate_btn.clicked.connect(self._on_generate)
        btn_row.addWidget(self.generate_btn)
        btn_row.addStretch()

        layout.addLayout(btn_row)

        # Status
        self.status_label = QLabel("请先选择一个牌组组，然后点击「读取牌组内容」")
        self.status_label.setStyleSheet("color: #888; font-size: 13px; padding: 4px 0;")
        layout.addWidget(self.status_label)

        # Preview area (shows deck content summary after reading)
        self.preview_group = QGroupBox("📋 牌组内容预览")
        self.preview_group.hide()
        preview_layout = QVBoxLayout()
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(120)
        self.preview_text.setStyleSheet(
            "QTextEdit { border: 1px solid #E0E4E8; border-radius: 6px; "
            "padding: 8px; font-size: 13px; background: #FAFBFC; color: #333; }"
        )
        preview_layout.addWidget(self.preview_text)
        self.preview_group.setLayout(preview_layout)
        layout.addWidget(self.preview_group)

        layout.addStretch()

    # ── Quiz page ─────────────────────────────────────────────────

    def _build_quiz_page(self) -> None:
        self._quiz_widget = QWidget()
        layout = QVBoxLayout(self._quiz_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Progress bar
        progress_row = QHBoxLayout()
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(
            "QLabel { font-size: 14px; color: #4A90D9; font-weight: bold; }"
        )
        progress_row.addWidget(self.progress_label)
        progress_row.addStretch()
        layout.addLayout(progress_row)

        # Question area
        q_group = QGroupBox("📝 题目")
        q_layout = QVBoxLayout()
        self.question_label = QLabel("")
        self.question_label.setWordWrap(True)
        self.question_label.setStyleSheet(
            "QLabel { font-size: 17px; line-height: 1.8; color: #1a1a2e; "
            "padding: 16px; background: #FFF; border: 1px solid #E4E8EE; "
            "border-radius: 8px; }"
        )
        q_layout.addWidget(self.question_label)
        q_group.setLayout(q_layout)
        layout.addWidget(q_group)

        # Options area
        opt_group = QGroupBox("选项")
        opt_layout = QVBoxLayout()
        opt_layout.setSpacing(8)

        self._option_buttons: list[QPushButton] = []
        option_labels = ["A", "B", "C", "D"]
        option_colors = ["#4A90D9", "#27AE60", "#E67E22", "#9B59B6"]

        for i, (label, color) in enumerate(zip(option_labels, option_colors)):
            btn = QPushButton()
            btn.setMinimumHeight(50)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._option_style(color))
            btn.clicked.connect(lambda checked, idx=i: self._on_select_option(idx))
            self._option_buttons.append(btn)
            opt_layout.addWidget(btn)

        opt_group.setLayout(opt_layout)
        layout.addWidget(opt_group)

        # Explanation area (shown after answering)
        self.explanation_group = QGroupBox("💡 解析")
        self.explanation_group.hide()
        expl_layout = QVBoxLayout()
        self.explanation_label = QLabel("")
        self.explanation_label.setWordWrap(True)
        self.explanation_label.setStyleSheet(
            "QLabel { font-size: 14px; line-height: 1.7; color: #333; "
            "padding: 12px; background: #FFFBF0; border: 1px solid #F0E0C0; "
            "border-radius: 6px; }"
        )
        expl_layout.addWidget(self.explanation_label)
        self.explanation_group.setLayout(expl_layout)
        layout.addWidget(self.explanation_group)

        # Navigation
        nav_row = QHBoxLayout()
        nav_row.addStretch()
        self.next_btn = QPushButton("下一题 →")
        self.next_btn.setMinimumHeight(42)
        self.next_btn.setMinimumWidth(140)
        self.next_btn.setEnabled(False)
        self.next_btn.setStyleSheet(
            "QPushButton { font-size: 15px; font-weight: bold; padding: 8px 24px; "
            "border: none; border-radius: 8px; background: #4A90D9; color: #FFF; } "
            "QPushButton:hover { background: #357ABD; } "
            "QPushButton:disabled { background: #C0C8D0; color: #FFF; }"
        )
        self.next_btn.clicked.connect(self._on_next_question)
        nav_row.addWidget(self.next_btn)
        layout.addLayout(nav_row)

        # Back to setup button
        back_row = QHBoxLayout()
        self.back_setup_btn = QPushButton("← 返回设置，重新出题")
        self.back_setup_btn.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 6px 14px; border: 1px solid #D0D5DD; "
            "border-radius: 6px; background: #FFF; color: #555; } "
            "QPushButton:hover { background: #F5F7FA; border-color: #4A90D9; }"
        )
        self.back_setup_btn.clicked.connect(self._show_setup_page)
        back_row.addWidget(self.back_setup_btn)
        back_row.addStretch()
        layout.addLayout(back_row)

    # ── Results page ──────────────────────────────────────────────

    def _build_results_page(self) -> None:
        self._results_widget = QWidget()
        layout = QVBoxLayout(self._results_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Score banner
        self.score_label = QLabel("")
        self.score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.score_label.setWordWrap(True)
        self.score_label.setMinimumHeight(60)
        self.score_label.setStyleSheet(
            "QLabel { font-size: 20px; font-weight: bold; padding: 16px; "
            "border-radius: 10px; }"
        )
        layout.addWidget(self.score_label)

        # Review list
        review_group = QGroupBox("📋 题目回顾")
        review_layout = QVBoxLayout()
        self.review_area = QScrollArea()
        self.review_area.setWidgetResizable(True)
        self.review_content = QWidget()
        self.review_content_layout = QVBoxLayout(self.review_content)
        self.review_content_layout.setContentsMargins(0, 0, 0, 0)
        self.review_content_layout.setSpacing(8)
        self.review_area.setWidget(self.review_content)
        self.review_area.setStyleSheet(
            "QScrollArea { border: 1px solid #E0E4E8; border-radius: 6px; background: #FFF; }"
        )
        review_layout.addWidget(self.review_area)
        review_group.setLayout(review_layout)
        layout.addWidget(review_group, stretch=1)

        # Actions
        action_row = QHBoxLayout()
        self.retry_wrong_btn = QPushButton("🔄 重做错题")
        self.retry_wrong_btn.setMinimumHeight(40)
        self.retry_wrong_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; padding: 8px 20px; "
            "border: none; border-radius: 8px; background: #E67E22; color: #FFF; } "
            "QPushButton:hover { background: #D35400; } "
            "QPushButton:disabled { background: #C0C8D0; color: #FFF; }"
        )
        self.retry_wrong_btn.clicked.connect(self._on_retry_wrong)
        action_row.addWidget(self.retry_wrong_btn)

        self.regenerate_btn = QPushButton("🆕 重新出题")
        self.regenerate_btn.setMinimumHeight(40)
        self.regenerate_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; padding: 8px 20px; "
            "border: none; border-radius: 8px; background: #27AE60; color: #FFF; } "
            "QPushButton:hover { background: #1E8449; }"
        )
        self.regenerate_btn.clicked.connect(self._show_setup_page)
        action_row.addWidget(self.regenerate_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

    # ═══════════════════════════════════════════════════════════════
    # Page switching
    # ═══════════════════════════════════════════════════════════════

    def _clear_stack(self) -> None:
        """Remove all widgets from the stack."""
        for i in reversed(range(self._stack.count())):
            item = self._stack.itemAt(i)
            if item and item.widget():
                item.widget().hide()
                self._stack.removeWidget(item.widget())

    def _show_setup_page(self) -> None:
        self._clear_stack()
        self._stack.addWidget(self._setup_widget)
        self._setup_widget.show()

    def _show_quiz_page(self) -> None:
        self._clear_stack()
        self._stack.addWidget(self._quiz_widget)
        self._quiz_widget.show()
        self._current_index = 0
        self._answers = {}
        self._display_question()

    def _show_results_page(self) -> None:
        self._clear_stack()
        self._stack.addWidget(self._results_widget)
        self._results_widget.show()
        self._display_results()

    # ═══════════════════════════════════════════════════════════════
    # Deck selection
    # ═══════════════════════════════════════════════════════════════

    def _populate_decks(self) -> None:
        self._deck_tree.clear()
        item_map: dict[str, QTreeWidgetItem] = {}

        last_deck = get_config().get("last_quiz_deck", "")
        target_item = None

        for deck in mw.col.decks.all_names_and_ids():
            parts = deck.name.split("::")
            item = QTreeWidgetItem([parts[-1]])
            item.setData(0, Qt.ItemDataRole.UserRole, deck.name)
            item_map[deck.name] = item

            if deck.name == last_deck:
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
            self._selected_deck_prefix = ""
            self.deck_btn.setText("选择牌组组...")
            self.generate_btn.setEnabled(False)

    def _show_deck_popup(self) -> None:
        btn_rect = self.deck_btn.rect()
        screen = QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen is not None else None

        popup_w = max(self.deck_btn.width(), 280)
        self._deck_popup.setFixedWidth(popup_w)

        row_h = self._deck_tree.sizeHintForRow(0)
        if row_h <= 0:
            row_h = self._deck_tree.fontMetrics().height() + 10
        count = self._count_tree_items(self._deck_tree.invisibleRootItem())
        tree_h = max(min(row_h * max(count, 1) + 16, 500), 120)
        self._deck_tree.setMinimumHeight(tree_h)
        self._deck_tree.setMaximumHeight(tree_h)
        popup_h = tree_h + 12

        top_pos = self.deck_btn.mapToGlobal(btn_rect.topLeft())
        # Try above, fall back to below
        above_y = top_pos.y() - popup_h
        if above_y >= 0:
            pos = top_pos
            pos.setY(above_y)
        else:
            pos = self.deck_btn.mapToGlobal(btn_rect.bottomLeft())

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
        # Allow selecting non-leaf nodes (deck groups with children)
        self._select_deck_item(item)
        self._deck_popup.hide()

    def _on_deck_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        self._select_deck_item(item)
        self._deck_popup.hide()

    def _select_deck_item(self, item: QTreeWidgetItem) -> None:
        deck_name = item.data(0, Qt.ItemDataRole.UserRole)
        if deck_name is None:
            return
        self._selected_deck_prefix = deck_name
        self.deck_btn.setText(deck_name)
        self._deck_tree.setCurrentItem(item)
        self.generate_btn.setEnabled(True)

        cfg = get_config()
        cfg["last_quiz_deck"] = deck_name
        save_config(cfg)

    # ═══════════════════════════════════════════════════════════════
    # Read deck content
    # ═══════════════════════════════════════════════════════════════

    def _on_read_deck(self) -> None:
        if not self._selected_deck_prefix:
            showWarning("请先选择一个牌组组", parent=self)
            return

        try:
            disease_count, note_count = count_notes_in_deck(self._selected_deck_prefix)
            if disease_count == 0:
                showWarning(
                    f'在牌组组 "{self._selected_deck_prefix}" 中没有找到任何笔记。',
                    parent=self,
                )
                return

            # Show summary
            grouped = read_deck_group_notes(self._selected_deck_prefix)
            preview_lines = [f"共读取 {disease_count} 个疾病，{note_count} 条笔记\n"]
            for disease, fields in grouped.items():
                field_list = "、".join(fields.keys())
                preview_lines.append(f"📌 {disease}（{field_list}）")

            self.preview_text.setPlainText("\n".join(preview_lines))
            self.preview_group.show()
            self.status_label.setText(
                f"✅ 已读取 {disease_count} 个疾病，共 {note_count} 条笔记。现在可以点击「AI 生成题目」"
            )
            self.generate_btn.setEnabled(True)
        except Exception as e:
            showWarning(f"读取牌组失败：{e}", parent=self)

    # ═══════════════════════════════════════════════════════════════
    # Generate questions
    # ═══════════════════════════════════════════════════════════════

    def _on_generate(self) -> None:
        if not self._selected_deck_prefix:
            showWarning("请先选择一个牌组组", parent=self)
            return

        self.read_btn.setEnabled(False)
        self.generate_btn.setEnabled(False)
        self.status_label.setText("⏳ AI 正在生成题目，请稍候...")
        tooltip("AI 正在生成题目，请稍候...")

        self._worker = QuizWorker(
            deck_prefix=self._selected_deck_prefix,
            num_questions=self.count_spin.value(),
            question_type=self.type_combo.currentData(),
            custom_instruction=self.instruction_edit.toPlainText().strip(),
        )
        self._worker.progress.connect(self._on_gen_progress)
        self._worker.finished.connect(self._on_gen_done)
        self._worker.error_occurred.connect(self._on_gen_error)
        self._worker.start()

    def _on_gen_progress(self, msg: str) -> None:
        self.status_label.setText(msg)

    def _on_gen_done(self, questions: list[dict[str, str]]) -> None:
        self.read_btn.setEnabled(True)
        self.generate_btn.setEnabled(True)

        self._questions = questions
        if not questions:
            self.status_label.setText("⚠️ 未生成任何题目，请重试")
            return

        self.status_label.setText(f"✅ 成功生成 {len(questions)} 道题目，开始答题吧！")
        tooltip(f"已生成 {len(questions)} 道题目")

        # Save config
        cfg = get_config()
        cfg["quiz_default_count"] = self.count_spin.value()
        cfg["quiz_question_type"] = self.type_combo.currentData()
        save_config(cfg)

        # Switch to quiz page
        self._show_quiz_page()

    def _on_gen_error(self, error: str) -> None:
        self.read_btn.setEnabled(True)
        self.generate_btn.setEnabled(True)
        self.status_label.setText(f"❌ {error}")
        showWarning(f"生成失败：{error}", parent=self)

    # ═══════════════════════════════════════════════════════════════
    # Quiz interaction
    # ═══════════════════════════════════════════════════════════════

    def _display_question(self) -> None:
        """Display the current question and its options."""
        if self._current_index >= len(self._questions):
            self._show_results_page()
            return

        q = self._questions[self._current_index]

        # Progress
        self.progress_label.setText(
            f"第 {self._current_index + 1}/{len(self._questions)} 题"
        )

        # Question text
        self.question_label.setText(q.get("题干", ""))

        # Options
        for i, label in enumerate(["A", "B", "C", "D"]):
            btn = self._option_buttons[i]
            text = q.get(f"选项{label}", "")
            btn.setText(f"  {label}. {text}")
            btn.setEnabled(True)
            # Reset style to default
            colors = ["#4A90D9", "#27AE60", "#E67E22", "#9B59B6"]
            btn.setStyleSheet(self._option_style(colors[i]))

        # Hide explanation
        self.explanation_group.hide()
        self.next_btn.setEnabled(False)

        # If already answered (coming back from retry), show previous answer
        if self._current_index in self._answers:
            self._restore_answer_state()

    def _restore_answer_state(self) -> None:
        """Restore the answered state for the current question."""
        q = self._questions[self._current_index]
        correct = q.get("正确答案", "").strip().upper()
        selected = self._answers.get(self._current_index, "")

        for i, label in enumerate(["A", "B", "C", "D"]):
            btn = self._option_buttons[i]
            btn.setEnabled(False)
            if label == correct:
                btn.setStyleSheet(self._option_style("#27AE60", "correct"))
            elif label == selected and label != correct:
                btn.setStyleSheet(self._option_style("#E74C3C", "wrong"))
            else:
                btn.setStyleSheet(self._option_style("#C0C8D0", "disabled"))

        self.explanation_label.setText(q.get("解析", ""))
        self.explanation_group.show()
        self.next_btn.setEnabled(True)
        if self._current_index >= len(self._questions) - 1:
            self.next_btn.setText("🏁 查看成绩")
        else:
            self.next_btn.setText("下一题 →")

    def _on_select_option(self, idx: int) -> None:
        """Handle option selection."""
        if self._current_index in self._answers:
            return  # Already answered

        q = self._questions[self._current_index]
        correct = q.get("正确答案", "").strip().upper()
        selected_label = ["A", "B", "C", "D"][idx]

        # Record answer
        self._answers[self._current_index] = selected_label

        # Highlight correct (green) and selected (red if wrong)
        for i, label in enumerate(["A", "B", "C", "D"]):
            btn = self._option_buttons[i]
            btn.setEnabled(False)
            if label == correct:
                btn.setStyleSheet(self._option_style("#27AE60", "correct"))
            elif label == selected_label and label != correct:
                btn.setStyleSheet(self._option_style("#E74C3C", "wrong"))
            else:
                btn.setStyleSheet(self._option_style("#C0C8D0", "disabled"))

        # Show explanation
        self.explanation_label.setText(q.get("解析", ""))
        self.explanation_group.show()

        # Enable next
        self.next_btn.setEnabled(True)
        if self._current_index >= len(self._questions) - 1:
            self.next_btn.setText("🏁 查看成绩")
        else:
            self.next_btn.setText("下一题 →")

    def _on_next_question(self) -> None:
        """Move to next question or show results."""
        if self._current_index >= len(self._questions) - 1:
            self._show_results_page()
        else:
            self._current_index += 1
            self._display_question()

    # ═══════════════════════════════════════════════════════════════
    # Results
    # ═══════════════════════════════════════════════════════════════

    def _display_results(self) -> None:
        """Show final score and review list."""
        total = len(self._questions)
        correct_count = 0
        wrong_indices = []

        for i, q in enumerate(self._questions):
            correct = q.get("正确答案", "").strip().upper()
            selected = self._answers.get(i, "")
            if selected == correct:
                correct_count += 1
            else:
                wrong_indices.append(i)

        score_pct = int(correct_count / total * 100) if total > 0 else 0

        # Score banner
        if score_pct >= 80:
            bg_color = "#E8F8F0"
            border_color = "#27AE60"
            emoji = "🎉"
            desc = "优秀！"
        elif score_pct >= 60:
            bg_color = "#FFFBF0"
            border_color = "#F39C12"
            emoji = "👍"
            desc = "不错，继续加油！"
        else:
            bg_color = "#FDEDEC"
            border_color = "#E74C3C"
            emoji = "💪"
            desc = "继续努力！"

        self.score_label.setText(
            f"{emoji} {desc}  得分：{correct_count}/{total}（{score_pct}%）"
        )
        self.score_label.setStyleSheet(
            f"QLabel {{ font-size: 20px; font-weight: bold; padding: 16px; "
            f"border-radius: 10px; background: {bg_color}; "
            f"border: 2px solid {border_color}; color: #1a1a2e; }}"
        )

        # Review list
        self._build_review(wrong_indices)

        # Retry button
        self.retry_wrong_btn.setEnabled(len(wrong_indices) > 0)
        if not wrong_indices:
            self.retry_wrong_btn.setText("🎉 全部正确！")
        else:
            self.retry_wrong_btn.setText(f"🔄 重做错题（{len(wrong_indices)} 题）")

    def _build_review(self, wrong_indices: list[int]) -> None:
        """Build the review content for the results page."""
        # Clear existing
        for i in reversed(range(self.review_content_layout.count())):
            item = self.review_content_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

        for i, q in enumerate(self._questions):
            correct = q.get("正确答案", "").strip().upper()
            selected = self._answers.get(i, "未作答")
            is_correct = selected == correct

            card = QFrame()
            card.setStyleSheet(
                "QFrame { background: #FFF; border: 1px solid #E4E8EE; "
                "border-radius: 8px; padding: 12px; }"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(6)

            # Header row
            header_row = QHBoxLayout()
            icon = "✅" if is_correct else "❌"
            status_text = (
                f"{icon} 第 {i+1} 题  "
                f"{'正确' if is_correct else f'错误（你选{selected}，正确{correct}）'}"
            )
            header_label = QLabel(status_text)
            header_label.setStyleSheet(
                f"QLabel {{ font-size: 14px; font-weight: bold; "
                f"color: {'#27AE60' if is_correct else '#E74C3C'}; }}"
            )
            header_row.addWidget(header_label)
            header_row.addStretch()
            card_layout.addLayout(header_row)

            # Question
            q_label = QLabel(q.get("题干", ""))
            q_label.setWordWrap(True)
            q_label.setStyleSheet("QLabel { font-size: 14px; color: #333; }")
            card_layout.addWidget(q_label)

            # Correct answer explanation (only for wrong answers)
            if not is_correct:
                expl = QLabel(f"💡 {q.get('解析', '')}")
                expl.setWordWrap(True)
                expl.setStyleSheet(
                    "QLabel { font-size: 12px; color: #666; padding: 8px; "
                    "background: #FFFBF0; border-radius: 4px; }"
                )
                card_layout.addWidget(expl)

            self.review_content_layout.addWidget(card)

        self.review_content_layout.addStretch()

    def _on_retry_wrong(self) -> None:
        """Retry only wrong questions."""
        wrong_indices = []
        for i, q in enumerate(self._questions):
            correct = q.get("正确答案", "").strip().upper()
            if self._answers.get(i, "") != correct:
                wrong_indices.append(i)

        if not wrong_indices:
            return

        # Keep only wrong questions
        new_questions = [self._questions[i] for i in wrong_indices]
        self._questions = new_questions
        self._answers = {}
        self._show_quiz_page()

    # ═══════════════════════════════════════════════════════════════
    # Styling helpers
    # ═══════════════════════════════════════════════════════════════

    def _option_style(self, accent_color: str, state: str = "normal") -> str:
        """Build QPushButton stylesheet for option buttons.

        Args:
            accent_color: the color for border/highlight
            state: "normal" / "correct" / "wrong" / "disabled"
        """
        if state == "correct":
            bg = "#E8F8F0"
            border = accent_color
            text_color = "#1a7a3a"
        elif state == "wrong":
            bg = "#FDEDEC"
            border = accent_color
            text_color = "#B03A2E"
        elif state == "disabled":
            bg = "#F5F5F5"
            border = accent_color
            text_color = "#AAA"
        else:
            bg = "#FFF"
            border = "#D0D5DD"
            text_color = "#333"

        return (
            f"QPushButton {{ font-size: 15px; padding: 10px 18px; "
            f"border: 2px solid {border}; border-radius: 10px; "
            f"background: {bg}; color: {text_color}; text-align: left; }} "
            f"QPushButton:hover {{ "
            f"background: {'#F0F4FF' if state == 'normal' else bg}; "
            f"border-color: {'#4A90D9' if state == 'normal' else border}; }}"
        )
