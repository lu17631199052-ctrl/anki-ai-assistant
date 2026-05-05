"""Chat feature - context-aware AI chat for study assistance."""

from ..config import get_config, get_active_base_url, get_active_api_key, get_active_model
from ..llm.base import LLMMessage
from ..llm.openai_compat import OpenAICompatProvider

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

    def set_card_context(self, front: str, back: str) -> None:
        """Set context from the current Anki card."""
        self.card_context = f"用户当前正在复习以下卡片：\n问题：{front}\n答案：{back}"
        # Update the system message with context
        base = CHAT_SYSTEM_PROMPT
        if self.card_context:
            base += f"\n\n{self.card_context}"
        self.messages[0] = LLMMessage(role="system", content=base)

    def clear_card_context(self) -> None:
        self.card_context = ""
        self.messages[0] = LLMMessage(role="system", content=CHAT_SYSTEM_PROMPT)

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
        """Send a message and yield response chunks. Streaming version."""
        cfg = get_config()
        base_url = get_active_base_url()
        api_key = get_active_api_key()
        model = get_active_model()

        if not api_key and cfg.get("provider") != "ollama":
            raise RuntimeError("请先在设置中配置 API Key")

        client = OpenAICompatProvider(base_url=base_url, api_key=api_key)
        self.messages.append(LLMMessage(role="user", content=user_message))

        full_response = ""
        for chunk in client.chat_stream(
            self.messages,
            model=model,
            temperature=cfg.get("temperature", 0.7),
            max_tokens=cfg.get("max_tokens", 4096),
        ):
            if chunk:
                full_response += chunk
                yield chunk

        self.messages.append(LLMMessage(role="assistant", content=full_response))

        if len(self.messages) > 21:
            self.messages = [self.messages[0]] + self.messages[-20:]
