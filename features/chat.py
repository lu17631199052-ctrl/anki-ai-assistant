"""Chat feature - context-aware AI chat for study assistance."""

from ..config import get_config, get_active_base_url, get_active_api_key, get_active_model
from ..llm.base import LLMMessage
from ..llm.openai_compat import OpenAICompatProvider
from ..utils.logger import get_logger

_log = get_logger()

CHAT_SYSTEM_PROMPT = """你是一个 Anki 学习助手，帮助用户理解和记忆学习材料。你可以：

1. 回答用户关于当前学习内容的问题
2. 解释复杂概念
3. 提供记忆技巧和学习建议
4. 帮助用户建立知识点之间的联系

请用中文回答。保持回答简洁有帮助。"""


class ChatSession:
    """Manages a single chat conversation with context."""

    def __init__(self):
        self.messages: list[LLMMessage] = [
            LLMMessage(role="system", content=CHAT_SYSTEM_PROMPT)
        ]
        self.card_context: str = ""
        self.doc_context: str = ""
        self.doc_name: str = ""

    def set_card_context(self, front: str, back: str) -> None:
        """Set context from the current Anki card."""
        if front and back:
            self.card_context = f"用户当前正在复习以下卡片：\n问题：{front}\n答案：{back}"
        else:
            self.card_context = ""
        self._rebuild_system_prompt()

    def clear_card_context(self) -> None:
        self.card_context = ""
        self._rebuild_system_prompt()

    def set_document_context(self, doc_text: str, doc_name: str = "") -> None:
        """Set reference document context — AI answers are grounded in this material."""
        self.doc_context = doc_text
        self.doc_name = doc_name
        self._rebuild_system_prompt()

    def clear_document_context(self) -> None:
        self.doc_context = ""
        self.doc_name = ""
        self._rebuild_system_prompt()

    def _rebuild_system_prompt(self) -> None:
        """Rebuild system prompt combining base, card context, and document context."""
        parts = [CHAT_SYSTEM_PROMPT]
        if self.doc_context:
            name = self.doc_name or "参考笔记"
            grounding = "请基于以上笔记内容回答用户的问题。如果笔记中没有相关信息，请如实说明，不要编造。"
            parts.append(f"【{name}】\n{self.doc_context}\n\n{grounding}")
        if self.card_context:
            parts.append(self.card_context)
        prompt = "\n\n".join(parts)
        _log.debug(f"[chat] 系统提示词长度: {len(prompt)} 字符 (doc={bool(self.doc_context)} card={bool(self.card_context)})")
        self.messages[0] = LLMMessage(role="system", content=prompt)

    def send(self, user_message: str) -> str:
        """Send a message and get the response. Non-streaming."""
        cfg = get_config()
        base_url = get_active_base_url()
        api_key = get_active_api_key()
        model = get_active_model()

        if not api_key and cfg.get("provider") != "ollama":
            raise RuntimeError("请先在设置中配置 API Key")

        client = OpenAICompatProvider(base_url=base_url, api_key=api_key)
        self.messages.append(LLMMessage(role="user", content=user_message))

        response = client.chat(
            self.messages,
            model=model,
            temperature=cfg.get("temperature", 0.7),
            max_tokens=cfg.get("max_tokens", 4096),
        )

        self.messages.append(LLMMessage(role="assistant", content=response.content))

        # Keep conversation manageable
        if len(self.messages) > 21:  # system + 10 turns
            self.messages = [self.messages[0]] + self.messages[-20:]

        return response.content

    def send_stream(self, user_message: str):
        """Send a message and yield response chunks. Streaming version.

        If streaming fails, falls back to non-streaming.
        If response hits the token limit (finish_reason=length), auto-continues.
        """
        cfg = get_config()
        base_url = get_active_base_url()
        api_key = get_active_api_key()
        model = get_active_model()
        max_tokens = cfg.get("max_tokens", 4096)

        if not api_key and cfg.get("provider") != "ollama":
            raise RuntimeError("请先在设置中配置 API Key")

        client = OpenAICompatProvider(base_url=base_url, api_key=api_key)
        self.messages.append(LLMMessage(role="user", content=user_message))

        full_response = ""
        finish_reason = ""
        stream_failed = False
        try:
            for chunk in client.chat_stream(
                self.messages,
                model=model,
                temperature=cfg.get("temperature", 0.7),
                max_tokens=max_tokens,
            ):
                if chunk.startswith("__FINISH_REASON__:"):
                    finish_reason = chunk.split(":", 1)[1]
                    continue
                full_response += chunk
                yield chunk
        except Exception as e:
            stream_failed = True
            _log.warning(f"[chat] 流式失败，准备回退到非流式: {e}")

        if stream_failed:
            # Fallback: non-streaming request (has its own retry logic)
            try:
                response = client.chat(
                    self.messages,
                    model=model,
                    temperature=cfg.get("temperature", 0.7),
                    max_tokens=max_tokens,
                )
                full_response = response.content
                _log.info(f"[chat] 非流式回退成功: {len(full_response)} 字符")
                yield "\n\n---\n\n⚠️ 流式响应中断，已自动重新获取完整回复：\n\n" + full_response
            except Exception as e2:
                _log.error(f"[chat] 非流式回退也失败: {e2}")
                raise RuntimeError(f"流式响应失败，非流式回退也失败: {e2}") from e2

        self.messages.append(LLMMessage(role="assistant", content=full_response))

        if len(self.messages) > 21:
            self.messages = [self.messages[0]] + self.messages[-20:]

        # Auto-continue if model hit token limit
        if finish_reason == "length" and not stream_failed:
            _log.info(f"[chat] 触发自动续写 (finish_reason=length)")
            yield "\n\n---\n\n📝 回复较长，自动续写中...\n\n"
            try:
                self.messages.append(LLMMessage(role="user", content="继续完成上面的回答，直接从截断处接着写，不要重复前面的内容。"))
                for chunk in client.chat_stream(
                    self.messages,
                    model=model,
                    temperature=cfg.get("temperature", 0.7),
                    max_tokens=max_tokens * 2,
                ):
                    if chunk.startswith("__FINISH_REASON__:"):
                        continue
                    full_response += chunk
                    yield chunk
                # Merge: pop the "继续" user msg, update assistant with full content
                self.messages.pop()  # "继续" user message
                self.messages[-1] = LLMMessage(role="assistant", content=full_response)
            except Exception as e:
                _log.error(f"[chat] 自动续写失败: {e}")
                yield f"\n\n❌ 自动续写失败: {e}"
