"""Explain current card content using AI."""

import threading

from aqt import mw
from aqt.utils import showInfo, showWarning, tooltip
from aqt.qt import QObject, pyqtSignal

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


class _ExplainEmitter(QObject):
    """Signal emitter for thread-safe callback from background thread."""
    chunk_ready = pyqtSignal(str)
    stream_done = pyqtSignal()
    request_failed = pyqtSignal(str)


def _build_explain_prompt(front: str, back: str) -> list[LLMMessage]:
    card_content = f"卡片正面（问题）：\n{front}\n\n卡片背面（答案）：\n{back}"
    return [
        LLMMessage(role="system", content=EXPLAIN_SYSTEM_PROMPT),
        LLMMessage(role="user", content=card_content),
    ]


def explain_current_card(main_window=None) -> None:
    """Explain the currently displayed card in the reviewer (non-blocking)."""
    mw_obj = main_window or mw
    reviewer = mw_obj.reviewer

    if reviewer is None or reviewer.card is None:
        showWarning("请先打开一张卡片进行复习", parent=mw_obj)
        return

    card = reviewer.card
    note = card.note()
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
        back = front

    cfg = get_config()
    base_url = get_active_base_url()
    api_key = get_active_api_key()
    model = get_active_model()

    if not api_key and cfg.get("provider") != "ollama":
        showWarning("请先在设置中配置 API Key（工具 -> AI Assistant -> 设置）", parent=mw_obj)
        return

    tooltip("AI 正在生成解释，请稍候...")
    messages = _build_explain_prompt(front, back)

    # Show dialog immediately, stream content progressively
    dialog, browser = _create_stream_dialog(front, mw_obj)

    emitter = _ExplainEmitter(mw_obj)
    full_content: list[str] = []

    def _on_chunk(chunk: str) -> None:
        full_content.append(chunk)
        html = _simple_md_to_html("".join(full_content))
        browser.setHtml(html)

    def _on_done() -> None:
        pass

    def _on_error(error: str) -> None:
        browser.setHtml(f"<p style='color:red;'>AI 解释失败：{error}</p>")

    emitter.chunk_ready.connect(_on_chunk)
    emitter.stream_done.connect(_on_done)
    emitter.request_failed.connect(_on_error)

    def _run() -> None:
        try:
            client = OpenAICompatProvider(base_url=base_url, api_key=api_key)
            for chunk in client.chat_stream(
                messages,
                model=model,
                temperature=cfg.get("temperature", 0.7),
                max_tokens=cfg.get("max_tokens", 4096),
            ):
                emitter.chunk_ready.emit(chunk)
            emitter.stream_done.emit()
        except Exception as e:
            emitter.request_failed.emit(str(e))
        finally:
            emitter.deleteLater()

    threading.Thread(target=_run, daemon=True).start()


def _create_stream_dialog(question: str, parent):
    """Create and show an empty dialog, return (dialog, browser) for streaming updates."""
    from aqt.qt import QDialog, QVBoxLayout, QTextBrowser, QLabel

    dialog = QDialog(parent)
    dialog.setWindowTitle("AI 解释")
    dialog.setMinimumSize(500, 400)
    layout = QVBoxLayout(dialog)

    question_label = QLabel(f"<b>题目：</b>{question}")
    question_label.setWordWrap(True)
    layout.addWidget(question_label)

    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    browser.setHtml("<p style='color:#888;'>AI 正在生成解释...</p>")
    layout.addWidget(browser)

    dialog.show()
    return dialog, browser
