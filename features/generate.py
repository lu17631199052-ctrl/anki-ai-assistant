"""Generate Anki cards from text using AI."""

import json
import re

from aqt import mw
from aqt.utils import showInfo, showWarning, tooltip

from ..config import get_config, get_active_base_url, get_active_api_key, get_active_model
from ..llm.base import LLMMessage
from ..llm.openai_compat import OpenAICompatProvider

GENERATE_SYSTEM_PROMPT = """你是一个专业的 Anki 卡片生成助手。用户会给你一段学习材料，请从中提取关键知识点，生成问答形式的卡片。

要求：
1. 仔细分析文本，提取最重要的知识点（通常 5-10 个）
2. 每个知识点生成一张卡片，包含正面（问题）和背面（答案）
3. 问题要简洁明确，答案要准确完整
4. 如果知识点之间存在层次关系，可以生成一些概括性的卡片
5. 对于概念性知识，可以制作"概念-定义"型卡片
6. 对于过程性知识，可以制作"步骤-说明"型卡片

请严格按照以下 JSON 格式返回，不要包含其他内容：
```json
{
  "cards": [
    {"front": "问题或提示", "back": "答案或解释"},
    ...
  ]
}
```"""


def generate_cards(text: str) -> list[dict[str, str]]:
    """Generate card Q&A pairs from text. Returns list of {front, back} dicts."""
    cfg = get_config()
    base_url = get_active_base_url()
    api_key = get_active_api_key()
    model = get_active_model()

    if not api_key and cfg.get("provider") != "ollama":
        raise RuntimeError("请先在设置中配置 API Key")

    client = OpenAICompatProvider(base_url=base_url, api_key=api_key)
    messages = [
        LLMMessage(role="system", content=GENERATE_SYSTEM_PROMPT),
        LLMMessage(role="user", content=f"请根据以下内容生成 Anki 卡片：\n\n{text}"),
    ]

    response = client.chat(
        messages,
        model=model,
        temperature=cfg.get("temperature", 0.7),
        max_tokens=cfg.get("max_tokens", 4096),
    )

    cards = _parse_cards_json(response.content)
    if not cards:
        raise RuntimeError("AI 未能生成有效的卡片，请尝试调整文本内容或重试")

    # Fix: LLM 有时在 JSON 字符串中输出字面量 \n（两个字符）
    # 而不是换行符，导致 markdown 表格被挤成一行
    for card in cards:
        for key in ("front", "back"):
            if key in card:
                val = card[key]
                # 把字面量 \n 替换为真正的换行符
                val = val.replace("\\n", "\n")
                # 也处理 \n\n（双换行/段落分隔）
                card[key] = val

    return cards


def _parse_cards_json(content: str) -> list[dict[str, str]]:
    """Extract and parse the cards JSON from the LLM response."""
    # Try to find JSON block
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find bare JSON object
        json_match = re.search(r'\{.*"cards"\s*:.*\}', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            json_str = content

    try:
        data = json.loads(json_str)
        return data.get("cards", [])
    except json.JSONDecodeError:
        return []


def add_cards_to_deck(
    cards: list[dict[str, str]],
    deck_id: int,
    note_type_id: int,
    field_mapping: dict[int, str],
    tags: str = "",
) -> int:
    """Add generated cards to a deck. Returns number of cards added."""
    from anki.collection import Collection
    from anki.notes import Note

    col: Collection = mw.col
    deck = col.decks.get(deck_id)
    if not deck:
        raise RuntimeError("目标牌组不存在")

    model = col.models.get(note_type_id)
    if not model:
        raise RuntimeError("目标笔记类型不存在")

    added = 0
    for card in cards:
        note = Note(col, model)
        for field_idx, card_key in field_mapping.items():
            if card_key == "front":
                text = card.get("front", "")
            elif card_key == "back":
                text = card.get("back", "")
            else:
                text = card.get(card_key, "")
            if text and not text.strip().startswith("<"):
                text = text.replace("\n", "<br>")
            note.fields[field_idx] = text
        if tags:
            note.tags = [t.strip() for t in tags.split() if t.strip()]
        col.add_note(note, deck_id)
        added += 1

    return added
