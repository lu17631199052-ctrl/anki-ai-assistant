"""OpenAI-compatible API client using curl subprocess.

Uses subprocess + curl instead of urllib to avoid SSL / proxy / IPv6
issues in Anki's bundled Python environment. curl uses the OS-native
network stack and is proven to work on the user's machine.
"""

import json
import os
import shutil
import subprocess
import platform
from typing import Any, Generator

from .base import BaseLLMProvider, LLMMessage, LLMResponse


def _find_curl() -> str | None:
    """Find curl binary across platforms."""
    path = shutil.which("curl") or shutil.which("curl.exe")
    if path:
        return path
    # Windows absolute paths
    if platform.system() == "Windows":
        for p in [
            r"C:\Windows\System32\curl.exe",
            r"C:\Windows\SysWOW64\curl.exe",
        ]:
            if os.path.isfile(p):
                return p
    return None


_CURL_BIN = _find_curl()


def _curl_request(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout: int = 60,
    stream: bool = False,
) -> str:
    """Make a POST request via curl. Returns response body as string."""
    if not _CURL_BIN:
        raise RuntimeError(
            "未找到 curl，请安装 curl 后重试。\n"
            "macOS: 系统自带\n"
            "Windows: https://curl.se/windows/\n"
            "Linux: sudo apt install curl / sudo yum install curl"
        )
    data = json.dumps(payload)
    cmd = [
        _CURL_BIN,
        "-s",
        "-X", "POST",
        url,
        "-H", "Content-Type: application/json",
        "-H", f"Authorization: Bearer {api_key}",
        "-d", data,
        "--connect-timeout", "15",
        "--max-time", str(timeout),
    ]
    if stream:
        cmd.append("--no-buffer")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout + 15,
            text=False,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")

        if result.returncode != 0:
            # curl exit code non-zero = network-level failure
            err_msg = stderr.strip() if stderr.strip() else f"curl exit code {result.returncode}"
            # Try to extract meaningful error
            if "Connection refused" in err_msg:
                raise RuntimeError(f"网络错误: 连接被拒绝，请检查 API 地址是否正确: {url}")
            elif "Could not resolve host" in err_msg:
                raise RuntimeError(f"网络错误: 无法解析域名，请检查网络连接")
            elif "SSL" in err_msg or "certificate" in err_msg:
                raise RuntimeError(f"网络错误: SSL 证书问题 - {err_msg}")
            else:
                raise RuntimeError(f"网络错误: {err_msg}")

        if not stdout.strip():
            raise RuntimeError("API 返回空响应")

        return stdout

    except subprocess.TimeoutExpired:
        raise RuntimeError("网络超时，请检查网络连接或稍后重试")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}")


class OpenAICompatProvider(BaseLLMProvider):

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _build_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def chat(
        self,
        messages: list[LLMMessage],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        url = self._build_url("/chat/completions")

        raw = _curl_request(url, payload, self.api_key, timeout=60)
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
        """Streaming - falls back to non-streaming, yields full response."""
        response = self.chat(messages, model, temperature, max_tokens)
        yield response.content
