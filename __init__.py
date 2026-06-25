"""
AI Study Assistant - Anki addon for AI-powered study features.
Supports DeepSeek, Qwen, Zhipu, Moonshot, Ollama, and custom APIs.
"""

import os

from aqt import mw, gui_hooks
from aqt.utils import qconnect
from aqt.qt import QAction, QMenu, QTimer

# Initialize logging as early as possible
ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
from .utils.logger import setup_logging
setup_logging(ADDON_DIR)

# Delay heavy imports until features are actually used

# Keep references to modeless dialogs so they aren't garbage-collected
_generate_dialog = None
_wrong_answer_dialog = None
_quiz_generator_dialog = None


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


def _open_quiz_generator() -> None:
    from .ui.quiz_generator_dialog import QuizGeneratorDialog
    global _quiz_generator_dialog
    _quiz_generator_dialog = QuizGeneratorDialog(mw)
    _quiz_generator_dialog.show()


def _open_browser_search() -> None:
    from .ui.browser_search import _open_browser_search as _browser_open
    _browser_open()


def _open_settings() -> None:
    from .ui.settings import SettingsDialog
    dialog = SettingsDialog(mw)
    dialog.show()


def _open_left_sidebar() -> None:
    from .ui.left_sidebar import init_launcher, toggle_notebook
    init_launcher()
    toggle_notebook("notepad")


def _show_log() -> None:
    from .ui.settings import _show_log_dialog
    _show_log_dialog(mw)


def _explain_current_card() -> None:
    from .features.explain import explain_current_card
    explain_current_card(mw)


def _setup_menu() -> None:
    menu: QMenu = QMenu("AI Assistant", mw)

    sidebar_action: QAction = QAction("📋 左侧工具栏", mw)
    qconnect(sidebar_action.triggered, _open_left_sidebar)
    menu.addAction(sidebar_action)

    menu.addSeparator()

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

    quiz_action: QAction = QAction("AI 出题", mw)
    qconnect(quiz_action.triggered, _open_quiz_generator)
    menu.addAction(quiz_action)

    browser_search_action: QAction = QAction("🌐 浏览器搜索", mw)
    qconnect(browser_search_action.triggered, _open_browser_search)
    menu.addAction(browser_search_action)

    menu.addSeparator()

    log_action: QAction = QAction("📋 查看日志", mw)
    qconnect(log_action.triggered, _show_log)
    menu.addAction(log_action)

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
        _quiz_key = "Meta+T"
    else:
        _explain_key = "Ctrl+Shift+W"
        _wrong_key = "Ctrl+Shift+R"
        _chat_key = "Ctrl+Shift+Q"
        _generate_key = "Ctrl+Shift+E"
        _quiz_key = "Ctrl+Shift+T"

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

    # AI 出题
    shortcut_quiz = QShortcut(QKeySequence(_quiz_key), reviewer.web)
    qconnect(shortcut_quiz.activated, _open_quiz_generator)

    _shortcut_registered = True


gui_hooks.reviewer_did_show_question.append(_on_reviewer_did_show)

_setup_menu()

# Initialize left launcher (fixed icon strip) after main window is ready.
def _delayed_init_launcher():
    from .ui.left_sidebar import init_launcher
    init_launcher()
QTimer.singleShot(500, _delayed_init_launcher)
