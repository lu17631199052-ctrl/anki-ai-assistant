"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)


class BaseLLMProvider(ABC):

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        ...

    def test_connection(self) -> bool:
        """Quick connectivity check. Raises on failure for detailed error."""
        resp = self.chat(
            [
                LLMMessage(role="user", content="Say 'OK'"),
            ],
            max_tokens=32,
        )
        return bool(resp.content.strip())
