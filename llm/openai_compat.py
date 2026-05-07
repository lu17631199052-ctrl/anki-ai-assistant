"""OpenAI-compatible API client.

Tries curl first (most reliable), falls back to urllib if curl unavailable
or crashes (e.g. some Windows environments).
"""

import json
import os
import shutil
import subprocess
import platform
import ssl
import time
from typing import Any, Generator, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from http.client import IncompleteRead

from .base import BaseLLMProvider, LLMMessage, LLMResponse


def _find_curl() -> Optional[str]:
    path = shutil.which("curl") or shutil.which("curl.exe")
    if path:
        return path
    if platform.system() == "Windows":
        for p in [
            r"C:\Windows\System32\curl.exe",
            r"C:\Windows\SysWOW64\curl.exe",
        ]:
            if os.path.isfile(p):
                return p
    return None


_CURL_BIN = _find_curl()
_CURL_FAILED = False  # track if curl previously failed


def _request_via_urllib(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout: int = 60,
) -> str:
    """Fallback HTTP request using urllib with relaxed SSL."""
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        resp = urlopen(req, timeout=timeout, context=ctx)
        body = resp.read().decode("utf-8")
        status = resp.getcode()
        if status != 200:
            try:
                err = json.loads(body)
                msg = err.get("error", {}).get("message", body[:500])
            except Exception:
                msg = body[:500]
            raise RuntimeError(f"API 错误 ({status}): {msg}")
        return body
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(error_body)
            msg = err.get("error", {}).get("message", error_body)
        except Exception:
            msg = error_body[:500]
        raise RuntimeError(f"API 错误 ({e.code}): {msg}")
    except URLError as e:
        raise RuntimeError(f"网络错误: {e.reason}")
    except (RuntimeError, IncompleteRead):
        raise
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}")


def _request_via_curl(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout: int = 60,
) -> str:
    """Primary HTTP request using curl. Data is piped via stdin to avoid
    command-line argument length limits (important for vision API with large
    base64-encoded images)."""
    if not _CURL_BIN:
        raise RuntimeError("curl not found, using fallback")

    data = json.dumps(payload)
    cmd = [
        _CURL_BIN,
        "-s",
        "-X", "POST",
        url,
        "-H", "Content-Type: application/json",
        "-H", f"Authorization: Bearer {api_key}",
        "--data-binary", "@-",  # read payload from stdin
        "--connect-timeout", "15",
        "--max-time", str(timeout),
    ]

    result = subprocess.run(
        cmd,
        input=data,
        capture_output=True,
        timeout=timeout + 15,
        text=False,
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")

    if result.returncode != 0:
        err_msg = stderr.strip() if stderr.strip() else f"curl exit code {result.returncode}"
        raise RuntimeError(f"curl 请求失败: {err_msg}")

    if not stdout.strip():
        raise RuntimeError("API 返回空响应")

    return stdout


def _do_request(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout: int = 60,
    _retry: int = 0,
) -> str:
    """Try curl, fall back to urllib. Retry on transient network errors."""
    global _CURL_FAILED

    last_error = None
    for attempt in range(3):
        try:
            if not _CURL_FAILED and _CURL_BIN:
                try:
                    return _request_via_curl(url, payload, api_key, timeout)
                except RuntimeError as e:
                    err_str = str(e)
                    if "curl exit code" in err_str or "curl 请求失败" in err_str:
                        _CURL_FAILED = True
                    else:
                        raise

            return _request_via_urllib(url, payload, api_key, timeout)
        except (IncompleteRead, ConnectionResetError, TimeoutError, URLError) as e:
            last_error = e
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise RuntimeError(f"网络错误（已重试2次仍失败）: {e}") from e
        except RuntimeError:
            raise

    raise RuntimeError(f"网络错误（已重试2次仍失败）: {last_error}")


class OpenAICompatProvider(BaseLLMProvider):

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _build_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _build_message(self, m: LLMMessage) -> dict[str, Any]:
        """Build API message dict, supporting both text and vision."""
        if not m.images:
            return {"role": m.role, "content": m.content}
        # Vision format: content is an array of text + image_url blocks
        parts: list[dict[str, Any]] = []
        if m.content.strip():
            parts.append({"type": "text", "text": m.content})
        for img_data in m.images:
            # img_data should be a data URL: "data:image/jpeg;base64,..."
            if not img_data.startswith("data:"):
                # MIME type detection fallback
                prefix = "data:image/jpeg;base64,"
            else:
                prefix = ""
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"{prefix}{img_data}" if prefix else img_data},
            })
        return {"role": m.role, "content": parts}

    def chat(
        self,
        messages: list[LLMMessage],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [self._build_message(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        url = self._build_url("/chat/completions")
        raw = _do_request(url, payload, self.api_key, timeout=60)
        body = json.loads(raw)

        if "error" in body:
            msg = body["error"].get("message", raw[:500])
            raise RuntimeError(f"API 错误: {msg}")

        choice = body["choices"][0]
        content = choice["message"]["content"]
        usage = body.get("usage", {})
        return LLMResponse(
            content=content.strip(),
            model=body.get("model", model),
            usage=usage,
        )

    def chat_stream(
        self,
        messages: list[LLMMessage],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Generator[str, None, None]:
        response = self.chat(messages, model, temperature, max_tokens)
        yield response.content
