"""Explain current card content using AI."""

from aqt import mw
from aqt.utils import showInfo, showWarning, tooltip
from aqt.qt import QThread, pyqtSignal

from ..config import get_config, get_active_base_url, get_active_api_key, get_active_model
from ..llm.base import LLMMessage
from ..llm.openai_compat import OpenAICompatProvider
from ..ui.markdown import md_to_html as _simple_md_to_html

EXPLAIN_SYSTEM_PROMPT = """你是一个知识渊博的学习助手。用户会给你一张 Anki 卡片的内容（正面和背面），你需要：

1. 详细解释卡片中涉及的知识点
2. 提供相关的背景信息和上下文
3. 如果有记忆技巧（如联想、口诀），可以一并提供
4. 说明这个知识点在实际中的应用

请用中文回答，语言要清晰易懂。如果卡片是外语内容，用中文解释但保留关键术语的原文。"""


def _build_explain_prompt(front: str, back: str) -> list[LLMMessage]:
    card_content = f"卡片正面（问题）：\n{front}\n\n卡片背面（答案）：\n{back}"
    return [
        LLMMessage(role="system", content=EXPLAIN_SYSTEM_PROMPT),
        LLMMessage(role="user", content=card_content),
    ]


class ExplainWorker(QThread):
    """Background worker so Anki doesn't freeze during API call."""
    finished = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, messages: list[LLMMessage], model: str, base_url: str,
                 api_key: str, temperature: float, max_tokens: int):
        super().__init__()
        self._messages = messages
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._temperature = temperature
        self._max_tokens = max_tokens

    def run(self) -> None:
        try:
            client = OpenAICompatProvider(base_url=self._base_url, api_key=self._api_key)
            response = client.chat(
                self._messages,
                model=self._model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            self.finished.emit(response.content)
        except Exception as e:
            self.error_occurred.emit(str(e))


def explain_current_card(main_window=None) -> None:
    """Explain the currently displayed card in the reviewer (non-blocking)."""
    mw_obj = main_window or mw
    reviewer = mw_obj.reviewer

    if reviewer is None or reviewer.card is None:
        showWarning("请先打开一张卡片进行复习", parent=mw_obj)
        return

    card = reviewer.card
    note = card.note()
    # Get front and back as plain text
    front = ""
    back = ""
    for field_name, field_val in note.items():
        stripped = field_val.strip()
        if stripped:
            if not front:
                front = stripped
            else:
                back = stripped

    if not back:
        back = front  # Fallback: only one field

    cfg = get_config()
    base_url = get_active_base_url()
    api_key = get_active_api_key()
    model = get_active_model()

    if not api_key and cfg.get("provider") != "ollama":
        showWarning("请先在设置中配置 API Key（工具 -> AI Assistant -> 设置）", parent=mw_obj)
        return

    messages = _build_explain_prompt(front, back)

    # Show a loading dialog
    loading = _show_loading(front, mw_obj)

    # Run API call in background thread
    worker = ExplainWorker(
        messages=messages,
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=cfg.get("temperature", 0.7),
        max_tokens=cfg.get("max_tokens", 4096),
    )

    def on_finished(content: str) -> None:
        loading.close()
        _show_explanation(content, front, mw_obj)

    def on_error(error: str) -> None:
        loading.close()
        showWarning(f"AI 解释失败：{error}", parent=mw_obj)

    worker.finished.connect(on_finished)
    worker.error_occurred.connect(on_error)
    # Keep reference to prevent garbage collection
    worker.finished.connect(worker.deleteLater)
    worker.start()


def _show_loading(question: str, parent) -> object:
    """Show a small loading indicator while AI generates the explanation."""
    from aqt.qt import QDialog, QVBoxLayout, QLabel

    dialog = QDialog(parent)
    dialog.setWindowTitle("AI 解释中...")
    dialog.setMinimumWidth(350)
    dialog.setWindowModality(2)  # ApplicationModal to block interaction but not paint
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(f"<b>题目：</b>{question[:60]}{'...' if len(question) > 60 else ''}"))
    layout.addWidget(QLabel("AI 正在生成解释，请稍候..."))
    dialog.show()
    return dialog


def _show_explanation(content: str, question: str, parent) -> None:
    """Show explanation in a dialog."""
    from aqt.qt import QDialog, QVBoxLayout, QTextBrowser, QLabel, QFont

    dialog = QDialog(parent)
    dialog.setWindowTitle("AI 解释")
    dialog.setMinimumSize(500, 400)
    layout = QVBoxLayout(dialog)

    question_label = QLabel(f"<b>题目：</b>{question}")
    question_label.setWordWrap(True)
    layout.addWidget(question_label)

    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    html = _simple_md_to_html(content)
    browser.setHtml(html)
    layout.addWidget(browser)

    dialog.show()


