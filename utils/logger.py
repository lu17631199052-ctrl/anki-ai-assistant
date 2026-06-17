"""Centralized logging for the AI Assistant addon.

Logs to {addon_dir}/plugin.log with rotation (500KB × 3 files).
Never logs full API keys or message content — only summaries.
"""

import logging
import logging.handlers
import os
import sys
import traceback
from typing import Any

_logger: logging.Logger | None = None
_log_file: str = ""


def get_logger() -> logging.Logger:
    """Get the plugin logger. Must call setup_logging() first."""
    global _logger
    if _logger is None:
        # Fallback: basic console logger so log calls don't crash
        _logger = logging.getLogger("anki_ai")
        _logger.setLevel(logging.DEBUG)
        if not _logger.handlers:
            _logger.addHandler(logging.StreamHandler(sys.stderr))
            _logger.warning("Logger not initialized — using stderr fallback")
    return _logger


def get_log_file() -> str:
    """Return the path to the current log file."""
    return _log_file


def setup_logging(addon_dir: str) -> None:
    """Initialize file logging. Call once at plugin startup."""
    global _logger, _log_file

    _log_file = os.path.join(addon_dir, "plugin.log")

    _logger = logging.getLogger("anki_ai")
    _logger.setLevel(logging.DEBUG)

    # Remove any existing handlers (in case of Anki profile reload)
    _logger.handlers.clear()

    # Rotating file handler: 500KB × 3 files
    fh = logging.handlers.RotatingFileHandler(
        _log_file,
        maxBytes=500 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh.setFormatter(fmt)
    _logger.addHandler(fh)

    # Platform / version info
    import platform
    try:
        from aqt import mw
        anki_ver = mw.appVersion if hasattr(mw, 'appVersion') else "unknown"
    except Exception:
        anki_ver = "unknown"

    _logger.info("=" * 50)
    _logger.info("AI Assistant 插件启动")
    _logger.info(f"  平台: {platform.system()} {platform.release()} ({platform.machine()})")
    _logger.info(f"  Python: {platform.python_version()}")
    _logger.info(f"  Anki: {anki_ver}")

    # Check curl availability
    from ..llm.openai_compat import _CURL_BIN
    if _CURL_BIN:
        _logger.info(f"  curl: {_CURL_BIN}")
    else:
        _logger.warning("  curl: 未找到，将使用 urllib")


def mask_key(key: str) -> str:
    """Mask an API key, showing only the last 4 characters."""
    if not key:
        return "(empty)"
    if len(key) <= 8:
        return "***"
    return f"{key[:3]}...{key[-4:]}"


def request_summary(payload: dict[str, Any]) -> str:
    """Return a human-readable summary of an API request payload."""
    parts = []
    model = payload.get("model", "?")
    parts.append(f"model={model}")

    msgs = payload.get("messages", [])
    parts.append(f"messages={len(msgs)}")

    total_chars = sum(len(str(m.get("content", ""))) for m in msgs)
    parts.append(f"chars={total_chars}")

    if payload.get("stream"):
        parts.append("stream=True")

    max_tok = payload.get("max_tokens", "?")
    parts.append(f"max_tokens={max_tok}")

    temp = payload.get("temperature", "?")
    parts.append(f"temperature={temp}")

    # Image count
    img_count = 0
    for m in msgs:
        content = m.get("content", "")
        if isinstance(content, list):
            img_count += sum(1 for p in content if p.get("type") == "image_url")

    if img_count:
        parts.append(f"images={img_count}")

    return ", ".join(parts)


def log_exception(msg: str = "") -> None:
    """Log the current exception with traceback."""
    tb = traceback.format_exc()
    get_logger().error(f"{msg}\n{tb}" if msg else tb)
