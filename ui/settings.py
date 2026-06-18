"""Settings dialog for API provider configuration."""

import os

from aqt.qt import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QPushButton,
    QGroupBox,
    QFormLayout,
    QMessageBox,
    QDoubleSpinBox,
    QSpinBox,
    QCheckBox,
    QWidget,
    QTextBrowser,
    Qt,
    QApplication,
)
from aqt.utils import showInfo, showWarning, tooltip
from aqt import mw

from ..config import (
    get_config,
    save_config,
    PROVIDER_PRESETS,
    get_provider_preset,
)
from ..llm.openai_compat import OpenAICompatProvider
from ..utils.logger import get_log_file


class SettingsDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Assistant 设置")
        self.setMinimumWidth(520)
        self.resize(540, 580)
        self.cfg = get_config()
        self._build_ui()
        self._load_config()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 13px; color: #2C3E50;
                border: 1px solid #E0E4E8; border-radius: 8px;
                margin-top: 12px; padding-top: 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 6px;
                color: #4A90D9;
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                border: 1px solid #D0D5DD; border-radius: 6px;
                padding: 6px 10px; font-size: 13px; background: #FFF;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #4A90D9;
            }
            QCheckBox { font-size: 13px; }
            QPushButton#primary {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #5B9BD5, stop:1 #4A90D9);
                color: white; border: none; border-radius: 6px;
                padding: 8px 24px; font-size: 14px; font-weight: bold;
            }
            QPushButton#primary:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #4A90D9, stop:1 #357ABD);
            }
            QPushButton#outline {
                background: #FFF; color: #4A90D9;
                border: 1.5px solid #4A90D9; border-radius: 6px;
                padding: 8px 20px; font-size: 13px;
            }
            QPushButton#outline:hover {
                background: #EBF3FC;
            }
            QPushButton#success {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #5CB85C, stop:1 #449D44);
                color: white; border: none; border-radius: 6px;
                padding: 8px 24px; font-size: 14px; font-weight: bold;
            }
            QPushButton#success:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #449D44, stop:1 #398439);
            }
            QPushButton#warn {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #F5A623, stop:1 #E8961A);
                color: white; border: none; border-radius: 6px;
                padding: 6px 14px; font-size: 12px; font-weight: bold;
            }
            QPushButton#warn:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #E8961A, stop:1 #D48514);
            }
        """)

        # Scroll area wrapping all settings content
        from aqt.qt import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll, 1)

        # Provider selection
        provider_group = QGroupBox("模型提供商")
        provider_layout = QFormLayout()
        self.provider_combo = QComboBox()
        for pid, preset in PROVIDER_PRESETS.items():
            self.provider_combo.addItem(preset["name"], pid)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_layout.addRow("提供商:", self.provider_combo)
        provider_group.setLayout(provider_layout)
        layout.addWidget(provider_group)

        # API settings
        api_group = QGroupBox("API 设置")
        api_layout = QFormLayout()
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("输入你的 API Key")
        api_layout.addRow("API Key:", self.api_key_edit)

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.example.com/v1")
        api_layout.addRow("Base URL:", self.base_url_edit)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setMinimumWidth(200)
        api_layout.addRow("模型:", self.model_combo)
        api_group.setLayout(api_layout)
        layout.addWidget(api_group)

        # Vision API settings (for image recognition)
        vision_group = QGroupBox("视觉模型设置（用于图片识别，可不填则使用上方主模型）")
        vision_layout = QFormLayout()
        self.vision_provider_combo = QComboBox()
        for pid, preset in PROVIDER_PRESETS.items():
            self.vision_provider_combo.addItem(preset["name"], pid)
        self.vision_provider_combo.currentIndexChanged.connect(self._on_vision_provider_changed)
        vision_layout.addRow("视觉提供商:", self.vision_provider_combo)

        self.vision_api_key_edit = QLineEdit()
        self.vision_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.vision_api_key_edit.setPlaceholderText("留空则使用上方 API Key")
        vision_layout.addRow("视觉 API Key:", self.vision_api_key_edit)

        self.vision_model_combo = QComboBox()
        self.vision_model_combo.setEditable(True)
        self.vision_model_combo.setMinimumWidth(200)
        vision_layout.addRow("视觉模型:", self.vision_model_combo)
        vision_group.setLayout(vision_layout)
        layout.addWidget(vision_group)

        # Parameters
        param_group = QGroupBox("生成参数")
        param_layout = QFormLayout()

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setDecimals(1)
        param_layout.addRow("Temperature:", self.temp_spin)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(256, 65536)
        self.max_tokens_spin.setSingleStep(256)
        param_layout.addRow("Max Tokens:", self.max_tokens_spin)
        param_group.setLayout(param_layout)
        layout.addWidget(param_group)

        # Card defaults
        card_group = QGroupBox("默认卡片设置（快速创建卡片时使用）")
        card_layout = QFormLayout()

        self.default_deck_combo = QComboBox()
        self.default_deck_combo.addItem("（不预设）", "")
        for deck in mw.col.decks.all_names_and_ids():
            self.default_deck_combo.addItem(deck.name, deck.id)
        card_layout.addRow("默认牌组:", self.default_deck_combo)

        self.default_note_type_combo = QComboBox()
        self.default_note_type_combo.addItem("（不预设）", "")
        for nt in mw.col.models.all():
            self.default_note_type_combo.addItem(nt["name"], nt["id"])
        card_layout.addRow("默认笔记类型:", self.default_note_type_combo)

        self.md_to_html_check = QCheckBox("将 Markdown 转为 HTML 再存入卡片（关闭则存原始 Markdown）")
        card_layout.addRow(self.md_to_html_check)

        card_group.setLayout(card_layout)
        layout.addWidget(card_group)

        # Quick chat prompts
        prompt_group = QGroupBox("AI 对话快捷提示词（最多4个，显示在输入框下方）")
        prompt_layout = QFormLayout()
        self.prompt_edits: list[QLineEdit] = []
        default_prompts = [
            "请用中文解释这张卡片的核心概念",
            "请帮我总结这张卡片的关键要点",
            "请为这张卡片的内容生成3道选择题",
            "请用一个通俗易懂的比喻帮助我理解这个知识点",
        ]
        for i in range(4):
            edit = QLineEdit()
            edit.setPlaceholderText(f"提示词 {i+1}（留空则不显示按钮）")
            edit.setText(default_prompts[i] if i < len(default_prompts) else "")
            edit.setClearButtonEnabled(True)
            prompt_layout.addRow(f"提示词 {i+1}:", edit)
            self.prompt_edits.append(edit)
        prompt_group.setLayout(prompt_layout)
        layout.addWidget(prompt_group)

        # Buttons pinned at bottom (outside scroll area)
        btn_layout2 = QHBoxLayout()
        btn_layout2.setContentsMargins(16, 8, 16, 12)

        self.test_btn = QPushButton("🔗 测试连接")
        self.test_btn.setObjectName("outline")
        self.test_btn.clicked.connect(self._test_connection)
        self.test_btn.setMinimumHeight(36)
        btn_layout2.addWidget(self.test_btn)

        self.log_btn = QPushButton("📋 查看日志")
        self.log_btn.setObjectName("outline")
        self.log_btn.clicked.connect(self._show_log)
        self.log_btn.setMinimumHeight(36)
        btn_layout2.addWidget(self.log_btn)

        btn_layout2.addStretch()

        self.save_btn = QPushButton("保存")
        self.save_btn.setObjectName("primary")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setMinimumHeight(36)
        self.save_btn.setMinimumWidth(100)
        btn_layout2.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("outline")
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setMinimumHeight(36)
        btn_layout2.addWidget(self.cancel_btn)

        main_layout.addLayout(btn_layout2)

    def _show_log(self) -> None:
        _show_log_dialog(self)

    def _load_config(self) -> None:
        idx = self.provider_combo.findData(self.cfg.get("provider", "deepseek"))
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self.api_key_edit.setText(self.cfg.get("api_key", ""))
        self.base_url_edit.setText(self.cfg.get("base_url", ""))

        # Populate model combo
        provider = self.cfg.get("provider", "deepseek")
        preset = get_provider_preset(provider)
        models_str = preset.get("models", "")
        self.model_combo.clear()
        if models_str:
            for m in models_str.split(","):
                self.model_combo.addItem(m.strip())
        current_model = self.cfg.get("model", "")
        if current_model:
            self.model_combo.setCurrentText(current_model)

        # Vision settings
        vp = self.cfg.get("vision_provider", "") or "qwen"
        idx = self.vision_provider_combo.findData(vp)
        if idx >= 0:
            self.vision_provider_combo.setCurrentIndex(idx)
        self.vision_api_key_edit.setText(self.cfg.get("vision_api_key", ""))
        self._populate_vision_models(vp)
        vm = self.cfg.get("vision_model", "")
        if vm:
            self.vision_model_combo.setCurrentText(vm)

        self.temp_spin.setValue(self.cfg.get("temperature", 0.7))
        self.max_tokens_spin.setValue(self.cfg.get("max_tokens", 8192))

        default_deck = self.cfg.get("default_deck", "")
        idx = self.default_deck_combo.findData(default_deck)
        if idx >= 0:
            self.default_deck_combo.setCurrentIndex(idx)

        default_nt = self.cfg.get("default_note_type", "")
        idx = self.default_note_type_combo.findData(default_nt)
        if idx >= 0:
            self.default_note_type_combo.setCurrentIndex(idx)

        self.md_to_html_check.setChecked(self.cfg.get("md_to_html", False))

        # Load chat prompts
        prompts = self.cfg.get("chat_prompts", [])
        for i, edit in enumerate(self.prompt_edits):
            if i < len(prompts):
                edit.setText(prompts[i])
            else:
                edit.clear()

    def _on_provider_changed(self) -> None:
        provider = self.provider_combo.currentData()
        preset = get_provider_preset(provider)
        self.base_url_edit.setText(preset.get("base_url", ""))

        self.model_combo.clear()
        models_str = preset.get("models", "")
        if models_str:
            for m in models_str.split(","):
                self.model_combo.addItem(m.strip())
        self.model_combo.setCurrentText(preset.get("default_model", ""))

        if provider == "custom":
            self.base_url_edit.setReadOnly(False)
        else:
            self.base_url_edit.setReadOnly(True)

    def _save(self) -> None:
        provider = self.provider_combo.currentData()
        self.cfg["provider"] = provider
        self.cfg["api_key"] = self.api_key_edit.text().strip()
        self.cfg["model"] = self.model_combo.currentText().strip()

        if provider == "custom":
            self.cfg["base_url"] = self.base_url_edit.text().strip()
        else:
            preset = get_provider_preset(provider)
            self.cfg["base_url"] = preset.get("base_url", "")

        self.cfg["temperature"] = self.temp_spin.value()
        self.cfg["max_tokens"] = self.max_tokens_spin.value()
        self.cfg["default_deck"] = self.default_deck_combo.currentData()
        self.cfg["default_note_type"] = self.default_note_type_combo.currentData()
        self.cfg["md_to_html"] = self.md_to_html_check.isChecked()
        self.cfg["chat_prompts"] = [e.text().strip() for e in self.prompt_edits]
        self.cfg["vision_provider"] = self.vision_provider_combo.currentData()
        self.cfg["vision_api_key"] = self.vision_api_key_edit.text().strip()
        self.cfg["vision_model"] = self.vision_model_combo.currentText().strip()
        try:
            save_config(self.cfg)
            showInfo("设置已保存", parent=self)
            self.accept()
        except Exception as e:
            showWarning(f"保存设置失败：{e}", parent=self)

    def _on_vision_provider_changed(self) -> None:
        vp = self.vision_provider_combo.currentData()
        self._populate_vision_models(vp)

    def _populate_vision_models(self, provider_id: str) -> None:
        self.vision_model_combo.clear()
        if provider_id == "qwen":
            for m in ["qwen-vl-plus", "qwen-vl-max", "qwen-plus", "qwen-max"]:
                self.vision_model_combo.addItem(m)
        elif provider_id == "zhipu":
            for m in ["glm-4v", "glm-4v-flash", "glm-4", "glm-4-plus"]:
                self.vision_model_combo.addItem(m)
        elif provider_id == "deepseek":
            for m in ["deepseek-v4-flash", "deepseek-v4-pro"]:
                self.vision_model_combo.addItem(m)
        elif provider_id == "moonshot":
            for m in ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"]:
                self.vision_model_combo.addItem(m)
        elif provider_id == "ollama":
            self.vision_model_combo.addItem("llava:latest")
        else:
            preset = get_provider_preset(provider_id)
            models_str = preset.get("models", "")
            if models_str:
                for m in models_str.split(","):
                    self.vision_model_combo.addItem(m.strip())
            else:
                self.vision_model_combo.addItem(preset.get("default_model", ""))
        vp = self.cfg.get("vision_provider", "") or "qwen"
        # Set default vision model
        defaults = {"qwen": "qwen-vl-plus", "zhipu": "glm-4v", "deepseek": "deepseek-v4-flash",
                    "moonshot": "moonshot-v1-8k", "ollama": "llava:latest"}
        if provider_id == vp:
            vm = self.cfg.get("vision_model", "") or defaults.get(provider_id, "")
            if vm:
                self.vision_model_combo.setCurrentText(vm)

    def _test_connection(self) -> None:
        provider = self.provider_combo.currentData()
        base_url = self.base_url_edit.text().strip()
        api_key = self.api_key_edit.text().strip()
        model = self.model_combo.currentText().strip()

        if not base_url:
            showWarning("请先设置 Base URL", parent=self)
            return
        if not api_key and provider != "ollama":
            showWarning("请先输入 API Key", parent=self)
            return
        if not model:
            showWarning("请先输入模型名称", parent=self)
            return

        self.test_btn.setEnabled(False)
        self.test_btn.setText("测试中...")

        try:
            client = OpenAICompatProvider(base_url=base_url, api_key=api_key)
            ok = client.test_connection(model=model)
            if ok:
                showInfo("连接成功！", parent=self)
            else:
                showWarning("连接失败：未收到有效响应", parent=self)
        except Exception as e:
            showWarning(f"连接失败：{e}", parent=self)
        finally:
            self.test_btn.setEnabled(True)
            self.test_btn.setText("测试连接")


def _show_log_dialog(parent=None) -> None:
    """Standalone function: open a dialog showing the plugin log file content.
    Can be called from both the settings dialog and the main menu.
    """
    log_path = get_log_file()
    dialog = QDialog(parent)
    dialog.setWindowTitle("插件日志")
    dialog.setMinimumSize(680, 500)
    layout = QVBoxLayout(dialog)

    # Info bar: log path + copy button
    info_layout = QHBoxLayout()
    info_label = QLabel(f"日志文件: {log_path}")
    info_label.setStyleSheet("color: #666; font-size: 12px;")
    info_layout.addWidget(info_label)
    info_layout.addStretch()

    # Read raw log content first (for clipboard)
    raw_content = ""
    try:
        if os.path.exists(log_path):
            fsize = os.path.getsize(log_path)
            read_size = min(fsize, 100 * 1024)
            with open(log_path, "r", encoding="utf-8") as f:
                if fsize > read_size:
                    f.seek(fsize - read_size)
                    f.readline()
                raw_content = f.read()
    except Exception:
        raw_content = ""

    copy_btn = QPushButton("复制日志内容")
    copy_btn.setObjectName("warn")
    copy_btn.setMinimumHeight(28)
    copy_btn.clicked.connect(lambda: (
        QApplication.clipboard().setText(raw_content),
        tooltip("日志已复制，可直接粘贴发送")
    ))
    info_layout.addWidget(copy_btn)
    layout.addLayout(info_layout)

    # Log content browser
    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    browser.setStyleSheet("""
        QTextBrowser {
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 12px;
            background: #1E1E1E;
            color: #D4D4D4;
            border: 1px solid #444;
            border-radius: 4px;
            padding: 8px;
        }
    """)

    if raw_content:
        # Escape HTML entities for safe display
        content = raw_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        # Highlight error/warning lines
        content = content.replace(
            "[ERROR]", '<span style="color:#F44747;">[ERROR]</span>'
        ).replace(
            "[WARNING]", '<span style="color:#CCA700;">[WARNING]</span>'
        )
        if fsize > read_size:
            header = f'<pre style="color:#888;">... 文件共 {fsize / 1024:.0f} KB，仅显示最近 {read_size / 1024:.0f} KB</pre>'
            browser.setHtml(f"{header}<pre>{content}</pre>")
        else:
            browser.setHtml(f"<pre>{content}</pre>")
    else:
        browser.setHtml("<p style='color:#888;'>日志文件尚未创建。使用一次插件功能后会自动生成。</p>")

    layout.addWidget(browser)

    # Close button
    close_btn = QPushButton("关闭")
    close_btn.setObjectName("primary")
    close_btn.clicked.connect(dialog.accept)
    close_btn.setMinimumHeight(36)
    close_btn.setMinimumWidth(100)
    btn_row = QHBoxLayout()
    btn_row.addStretch()
    btn_row.addWidget(close_btn)
    layout.addLayout(btn_row)

    dialog.show()

