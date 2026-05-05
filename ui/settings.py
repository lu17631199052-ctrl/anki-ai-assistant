"""Settings dialog for API provider configuration."""

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
    Qt,
)
from aqt.utils import showInfo, showWarning
from aqt import mw

from ..config import (
    get_config,
    save_config,
    PROVIDER_PRESETS,
    get_provider_preset,
)
from ..llm.openai_compat import OpenAICompatProvider


class SettingsDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Assistant 设置")
        self.setMinimumWidth(500)
        self.cfg = get_config()
        self._build_ui()
        self._load_config()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

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

        # Buttons
        btn_layout = QHBoxLayout()
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self._test_connection)
        btn_layout.addWidget(self.test_btn)

        btn_layout.addStretch()

        self.save_btn = QPushButton("保存")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)
        btn_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)

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

        self.temp_spin.setValue(self.cfg.get("temperature", 0.7))
        self.max_tokens_spin.setValue(self.cfg.get("max_tokens", 4096))

        default_deck = self.cfg.get("default_deck", "")
        idx = self.default_deck_combo.findData(default_deck)
        if idx >= 0:
            self.default_deck_combo.setCurrentIndex(idx)

        default_nt = self.cfg.get("default_note_type", "")
        idx = self.default_note_type_combo.findData(default_nt)
        if idx >= 0:
            self.default_note_type_combo.setCurrentIndex(idx)

        self.md_to_html_check.setChecked(self.cfg.get("md_to_html", False))

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
        save_config(self.cfg)
        showInfo("设置已保存", parent=self)
        self.accept()

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
            ok = client.test_connection()
            if ok:
                showInfo("连接成功！", parent=self)
            else:
                showWarning("连接失败：未收到有效响应", parent=self)
        except Exception as e:
            showWarning(f"连接失败：{e}", parent=self)
        finally:
            self.test_btn.setEnabled(True)
            self.test_btn.setText("测试连接")
