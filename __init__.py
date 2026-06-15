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

    import sys
    from aqt.qt import QShortcut, QKeySequence
    from .features.explain import explain_current_card

    reviewer = mw.reviewer
    if reviewer is None:
        return

    # On macOS, Qt maps "Ctrl" → Cmd (⌘); use "Meta" to get the real Control (^) key.
    # On Windows, "Ctrl+<key>" conflicts with Anki built-in shortcuts
    # (Ctrl+Q=Quit, Ctrl+W=Close window, Ctrl+E=Export), so use Ctrl+Shift instead.
    if sys.platform == "darwin":
        _explain_key = "Meta+W"
        _wrong_key = "Meta+R"
        _chat_key = "Meta+Q"
        _generate_key = "Meta+E"
    else:
        _explain_key = "Ctrl+Shift+W"
        _wrong_key = "Ctrl+Shift+R"
        _chat_key = "Ctrl+Shift+Q"
        _generate_key = "Ctrl+Shift+E"

    # AI 解释当前卡片
    shortcut_explain = QShortcut(QKeySequence(_explain_key), reviewer.web)
    qconnect(shortcut_explain.activated, lambda: explain_current_card(mw))

    # AI 错题整理
    shortcut_wrong = QShortcut(QKeySequence(_wrong_key), reviewer.web)
    qconnect(shortcut_wrong.activated, _open_wrong_answer)

    # AI 对话
    shortcut_chat = QShortcut(QKeySequence(_chat_key), reviewer.web)
    qconnect(shortcut_chat.activated, _open_chat)

    # AI 生成卡片
    shortcut_generate = QShortcut(QKeySequence(_generate_key), reviewer.web)
    qconnect(shortcut_generate.activated, _open_generate)

    _shortcut_registered = True


gui_hooks.reviewer_did_show_question.append(_on_reviewer_did_show)

_setup_menu()
