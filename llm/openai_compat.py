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
from ..utils.logger import get_logger, mask_key, request_summary, log_exception

_log = get_logger()


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
        _log.info(f"[urllib] 请求: {request_summary(payload)} timeout={timeout}s")
        resp = urlopen(req, timeout=timeout, context=ctx)
        body = resp.read().decode("utf-8")
        status = resp.getcode()
        if status != 200:
            try:
                err = json.loads(body)
                msg = err.get("error", {}).get("message", body[:500])
            except Exception:
                msg = body[:500]
            _log.error(f"[urllib] HTTP {status}: {msg}")
            raise RuntimeError(f"API 错误 ({status}): {msg}")
        _log.info(f"[urllib] 成功: {len(body)} bytes")
        return body
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(error_body)
            msg = err.get("error", {}).get("message", error_body)
        except Exception:
            msg = error_body[:500]
        _log.error(f"[urllib] HTTP {e.code}: {msg}")
        raise RuntimeError(f"API 错误 ({e.code}): {msg}")
    except URLError as e:
        _log.error(f"[urllib] 网络错误: {e.reason}")
        raise RuntimeError(f"网络错误: {e.reason}")
    except (RuntimeError, IncompleteRead):
        raise
    except Exception as e:
        _log.error(f"[urllib] 未知错误: {e}")
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
    _log.info(f"[curl] 请求: {request_summary(payload)} timeout={timeout}s")
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

    kwargs = dict(
        input=data.encode("utf-8"),
        capture_output=True,
        timeout=timeout + 15,
        text=False,
    )
    if platform.system() == "Windows":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # 阻止弹出黑色终端框
    result = subprocess.run(cmd, **kwargs)
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")

    if result.returncode != 0:
        err_msg = stderr.strip() if stderr.strip() else f"curl exit code {result.returncode}"
        _log.error(f"[curl] 失败: {err_msg}")
        raise RuntimeError(f"curl 请求失败: {err_msg}")

    if not stdout.strip():
        _log.error("[curl] API 返回空响应")
        raise RuntimeError("API 返回空响应")

    _log.info(f"[curl] 成功: {len(stdout)} bytes")
    return stdout


def _stream_via_curl(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout: int = 300,
) -> Generator[str, None, None]:
    """Stream SSE response via curl, yielding content chunks.

    Raises RuntimeError if the stream ends without the [DONE] marker
    (indicating an incomplete / interrupted response).
    """
    if not _CURL_BIN:
        raise RuntimeError("curl not found")

    data = json.dumps(payload)
    _log.info(f"[curl-stream] 开始: {request_summary(payload)} timeout={timeout}s")
    cmd = [
        _CURL_BIN,
        "-s",
        "-X", "POST",
        url,
        "-H", "Content-Type: application/json",
        "-H", f"Authorization: Bearer {api_key}",
        "--data-binary", "@-",
        "--connect-timeout", "15",
        "--max-time", str(timeout),
    ]

    popen_kwargs = dict(
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if platform.system() == "Windows":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # 阻止弹出黑色终端框
    proc = subprocess.Popen(cmd, **popen_kwargs)
    got_content = False
    got_done = False
    chunk_count = 0
    finish_reason: Optional[str] = None
    try:
        proc.stdin.write(data.encode("utf-8"))
        proc.stdin.close()

        for line in proc.stdout:
            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str.startswith("data:"):
                continue
            data_str = line_str[5:].strip()
            if data_str == "[DONE]":
                got_done = True
                break
            try:
                obj = json.loads(data_str)
                if "error" in obj:
                    msg = obj["error"].get("message", data_str)
                    _log.error(f"[curl-stream] API 错误: {msg}")
                    raise RuntimeError(f"API 错误: {msg}")
                choice = obj["choices"][0]
                delta = choice.get("delta", {})
                fr = choice.get("finish_reason", "") or delta.get("finish_reason", "")
                if fr:
                    finish_reason = fr
                content = delta.get("content", "")
                if content:
                    got_content = True
                    chunk_count += 1
                    if chunk_count % 50 == 0:
                        _log.debug(f"[curl-stream] 已收到 {chunk_count} 个 chunk")
                    yield content
            except (json.JSONDecodeError, KeyError, IndexError):
                continue

        proc.wait(timeout=5)
        if proc.returncode != 0:
            stderr = proc.stderr.read().decode("utf-8", errors="replace")
            if stderr.strip():
                _log.error(f"[curl-stream] curl 异常退出: {stderr.strip()}")
                raise RuntimeError(f"curl 请求失败: {stderr.strip()}")
    finally:
        proc.stdout.close()
        proc.stderr.close()
        try:
            proc.terminate()
        except Exception:
            pass

    if got_done:
        fr_str = f" finish_reason={finish_reason}" if finish_reason else ""
        _log.info(f"[curl-stream] 完成: {chunk_count} chunks{fr_str}")
        if finish_reason:
            yield f"__FINISH_REASON__:{finish_reason}"
    elif got_content:
        _log.error(f"[curl-stream] 中断: 收到 {chunk_count} chunks 但未收到 [DONE]")
        raise RuntimeError("流式响应中断：连接在接收完整回复前断开，请重试")
    else:
        _log.warning("[curl-stream] 结束: 未收到任何内容（模型可能拒绝回答）")
        if finish_reason:
            yield f"__FINISH_REASON__:{finish_reason}"


def _stream_via_urllib(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout: int = 300,
) -> Generator[str, None, None]:
    """Stream SSE via urllib, yielding content chunks.

    Raises RuntimeError if the stream ends without the [DONE] marker
    (indicating an incomplete / interrupted response).
    """
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    got_content = False
    got_done = False
    chunk_count = 0
    finish_reason: Optional[str] = None
    try:
        _log.info(f"[urllib-stream] 开始: {request_summary(payload)} timeout={timeout}s")
        resp = urlopen(req, timeout=timeout, context=ctx)
        for line in resp:
            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str.startswith("data:"):
                continue
            data_str = line_str[5:].strip()
            if data_str == "[DONE]":
                got_done = True
                break
            try:
                obj = json.loads(data_str)
                if "error" in obj:
                    msg = obj["error"].get("message", data_str)
                    _log.error(f"[urllib-stream] API 错误: {msg}")
                    raise RuntimeError(f"API 错误: {msg}")
                choice = obj["choices"][0]
                delta = choice.get("delta", {})
                fr = choice.get("finish_reason", "") or delta.get("finish_reason", "")
                if fr:
                    finish_reason = fr
                content = delta.get("content", "")
                if content:
                    got_content = True
                    chunk_count += 1
                    if chunk_count % 50 == 0:
                        _log.debug(f"[urllib-stream] 已收到 {chunk_count} 个 chunk")
                    yield content
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(error_body)
            msg = err.get("error", {}).get("message", error_body)
        except Exception:
            msg = error_body[:500]
        _log.error(f"[urllib-stream] HTTP {e.code}: {msg}")
        raise RuntimeError(f"API 错误 ({e.code}): {msg}")

    if got_done:
        fr_str = f" finish_reason={finish_reason}" if finish_reason else ""
        _log.info(f"[urllib-stream] 完成: {chunk_count} chunks{fr_str}")
        if finish_reason:
            yield f"__FINISH_REASON__:{finish_reason}"
    elif got_content:
        _log.error(f"[urllib-stream] 中断: 收到 {chunk_count} chunks 但未收到 [DONE]")
        raise RuntimeError("流式响应中断：连接在接收完整回复前断开，请重试")
    else:
        _log.warning("[urllib-stream] 结束: 未收到任何内容（模型可能拒绝回答）")
        if finish_reason:
            yield f"__FINISH_REASON__:{finish_reason}"


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
                        _log.warning(f"[retry] curl 失败，标记 _CURL_FAILED: {err_str}")
                        _CURL_FAILED = True
                    else:
                        raise

            return _request_via_urllib(url, payload, api_key, timeout)
        except (IncompleteRead, ConnectionResetError, TimeoutError, URLError) as e:
            last_error = e
            if attempt < 2:
                wait = 1.5 * (attempt + 1)
                _log.warning(f"[retry] 第 {attempt + 1} 次重试，等待 {wait:.1f}s: {e}")
                time.sleep(wait)
                continue
            _log.error(f"[retry] 3次尝试均失败: {e}")
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
        """Stream chat completion with retry and automatic fallback.

        Retries once on transient errors. If streaming fails and the
        caller has not received any content, falls back to non-streaming.
        Raises RuntimeError if all attempts fail.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": [self._build_message(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        url = self._build_url("/chat/completions")
        stream_timeout = 300

        global _CURL_FAILED
        last_error = None

        for attempt in range(2):  # 2 attempts total
            if attempt > 0:
                _log.info(f"[chat_stream] 第 {attempt + 1} 次尝试...")
            try:
                if not _CURL_FAILED and _CURL_BIN:
                    try:
                        yield from _stream_via_curl(url, payload, self.api_key, timeout=stream_timeout)
                        return
                    except RuntimeError as e:
                        err_str = str(e)
                        if "curl exit code" in err_str or "curl 请求失败" in err_str:
                            _log.warning(f"[chat_stream] curl-stream 失败，标记 _CURL_FAILED: {err_str}")
                            _CURL_FAILED = True
                        else:
                            raise

                yield from _stream_via_urllib(url, payload, self.api_key, timeout=stream_timeout)
                return
            except (IncompleteRead, ConnectionResetError, TimeoutError, URLError) as e:
                last_error = e
                if attempt < 1:
                    _log.warning(f"[chat_stream] 网络错误，将重试: {e}")
                    time.sleep(1.5)
                    continue
            except RuntimeError as e:
                # Stream interrupted (e.g. no [DONE] marker) — retry once
                last_error = e
                if attempt < 1:
                    _log.warning(f"[chat_stream] 流中断，将重试: {e}")
                    time.sleep(1.5)
                    continue

        _log.error(f"[chat_stream] 2次尝试均失败: {last_error}")
        raise RuntimeError(f"流式请求失败（已重试）: {last_error}")
