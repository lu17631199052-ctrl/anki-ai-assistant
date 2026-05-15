"""
AI Study Assistant - Anki addon for AI-powered study features.
Supports DeepSeek, Qwen, Zhipu, Moonshot, Ollama, and custom APIs.
"""

from aqt import mw, gui_hooks
from aqt.utils import qconnect
from aqt.qt import QAction, QMenu

# Delay heavy imports until features are actually used

# Keep references to modeless dialogs so they aren't garbage-collected
_generate_dialog = None
_wrong_answer_dialog = None


def _open_chat() -> None:
    from .ui.chat_dialog import _open_chat as _chat_open
    _chat_open()


def _open_generate() -> None:
    from .ui.generate_dialog import GenerateDialog
    global _generate_dialog
    _generate_dialog = GenerateDialog(mw)
    _generate_dialog.show()


def _open_wrong_answer() -> None:
    from .ui.wrong_answer_dialog import WrongAnswerDialog
    global _wrong_answer_dialog
    _wrong_answer_dialog = WrongAnswerDialog(mw)
    _wrong_answer_dialog.show()


def _open_settings() -> None:
    from .ui.settings import SettingsDialog
    dialog = SettingsDialog(mw)
    dialog.show()


def _explain_current_card() -> None:
    from .features.explain import explain_current_card
    explain_current_card(mw)


def _setup_menu() -> None:
    menu: QMenu = QMenu("AI Assistant", mw)

    chat_action: QAction = QAction("AI 对话", mw)
    qconnect(chat_action.triggered, _open_chat)
    menu.addAction(chat_action)

    explain_action: QAction = QAction("AI 解释当前卡片", mw)
    qconnect(explain_action.triggered, _explain_current_card)
    menu.addAction(explain_action)

    generate_action: QAction = QAction("AI 生成卡片", mw)
    qconnect(generate_action.triggered, _open_generate)
    menu.addAction(generate_action)

    wrong_answer_action: QAction = QAction("AI 错题整理", mw)
    qconnect(wrong_answer_action.triggered, _open_wrong_answer)
    menu.addAction(wrong_answer_action)

    menu.addSeparator()

    settings_action: QAction = QAction("设置...", mw)
    qconnect(settings_action.triggered, _open_settings)
    menu.addAction(settings_action)

    mw.form.menubar.addMenu(menu)


# Register reviewer shortcut for explanation (once only)
_shortcut_registered = False


def _on_reviewer_did_show(card) -> None:
    global _shortcut_registered
    if _shortcut_registered:
        return
    _shortcut_registered = True

    from aqt.qt import QShortcut, QKeySequence
    from .features.explain import explain_current_card

    reviewer = mw.reviewer
    if reviewer is None:
        return

    shortcut_e = QShortcut(QKeySequence("Ctrl+E"), reviewer.web)
    qconnect(shortcut_e.activated, lambda: explain_current_card(mw))

    shortcut_w = QShortcut(QKeySequence("Ctrl+W"), reviewer.web)
    qconnect(shortcut_w.activated, _open_wrong_answer)


gui_hooks.reviewer_did_show_question.append(_on_reviewer_did_show)

_setup_menu()
