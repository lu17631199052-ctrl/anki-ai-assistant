"""AI quiz generator — reads deck content and generates practice questions."""

import json
import re

from aqt import mw
from aqt.utils import showWarning

from ..config import get_config, get_active_base_url, get_active_api_key, get_active_model
from ..llm.base import LLMMessage
from ..llm.openai_compat import OpenAICompatProvider


QUIZ_SYSTEM_PROMPT = """你是一位中医内科学考试出题专家。你的任务是根据提供的疾病知识，生成高质量的中医内科学选择题，帮助考生通过做题来区分容易混淆的疾病。

【内容来源】
用户会提供一组疾病的知识卡片，每张卡片包含以下字段：
- 病名
- 病因
- 病机
- 治则/治法
- 病位
- 口诀
- 其他可能的补充字段

【出题原则】
1. **重点考察鉴别诊断**：两个相似疾病在病因/病机/病位/治则方面的区别
2. 优先出以下几类题目：
   a) 两个相似疾病在病因/病机/病位方面的区别（如"以下哪个病的病机涉及...？"）
   b) 两个相似疾病在治则/治法方面的区别
   c) 针对某个疾病的病因病机、治则治法的理解题
   d) 综合多个疾病的分类归属题
3. **避免单纯的"定义默写"题**，应考察理解和鉴别能力
4. 每道题必须有清晰的正确答案和**详细的解析**
5. 解析必须包含：正确选项为什么对 + 错误选项分别错在哪里（对应哪个病）
6. 错误选项应有合理的干扰性，要选同章节的疾病作为干扰项

【题量分配】
- 鉴别型题目（两病对比）约占 60%
- 单一疾病题目约占 40%
- 每个涉及到的疾病至少出一道题

【输出格式】
必须严格按照以下 JSON 格式输出，不要包含任何其他内容：
```json
{
  "questions": [
    {
      "题干": "题目文字，必须包含清晰的问题指向",
      "选项A": "选项内容（通常是病名或病机描述）",
      "选项B": "选项内容",
      "选项C": "选项内容",
      "选项D": "选项内容",
      "正确答案": "A",
      "解析": "正确答案的详细解析，包含正确选项分析及各错误选项的纠正"
    }
  ]
}
```

注意：
- 正确答案字段只能是一个大写字母 A、B、C 或 D
- 题干不要用"下列哪项"开头，应该具体说明在问什么
- 选项内容要简洁明确
"""


def read_deck_group_notes(deck_prefix: str) -> dict[str, dict[str, str]]:
    """Read all notes under a deck group, grouped by disease name.

    Returns dict like:
        {"感冒": {"病因": "...", "病机": "...", "病位": "...", ...},
         "咳嗽": {...}, ...}
    """
    # Find all matching decks
    all_decks = mw.col.decks.all_names_and_ids()
    matching_decks = [
        d for d in all_decks
        if d.name.startswith(deck_prefix)
    ]

    if not matching_decks:
        return {}

    # Collect all note IDs from matching decks
    all_nids: list[int] = []
    for deck in matching_decks:
        nids = mw.col.find_notes(f'"deck:{deck.name}"')
        all_nids.extend(nids)

    # Deduplicate (a note can be in multiple sub-decks)
    all_nids = list(set(all_nids))

    if not all_nids:
        return {}

    # Read notes, group by deck path (disease name)
    # First build a deck-id -> deck-name map
    did_to_name: dict[int, str] = {d.id: d.name for d in matching_decks}

    result: dict[str, dict[str, str]] = {}
    for nid in all_nids:
        try:
            note = mw.col.get_note(nid)
        except Exception:
            continue

        # Determine disease name from the card's deck
        cids = mw.col.db.list(
            "SELECT id FROM cards WHERE nid = ? LIMIT 1", nid
        )
        if not cids:
            continue
        card = mw.col.get_card(cids[0])
        deck_name = did_to_name.get(card.did, "")

        # Extract disease name: last segment of deck path
        # e.g. "考研/中内/01 肺系/01 感冒" -> "感冒"
        parts = deck_name.split("::")
        disease_raw = parts[-1] if parts else deck_name
        # Remove leading number prefix like "01 "
        disease = re.sub(r'^\d+\s*', '', disease_raw).strip()
        if not disease:
            disease = disease_raw

        if disease not in result:
            result[disease] = {}

        # Read all note fields
        model = note.note_type()
        if model is None:
            continue
        field_names = [f["name"] for f in model["flds"]]

        for i, val in enumerate(note.fields):
            if i >= len(field_names):
                continue
            cleaned = _strip_html(val)
            if cleaned.strip():
                field_name = field_names[i]
                existing = result[disease].get(field_name, "")
                if cleaned not in existing:
                    result[disease][field_name] = (
                        existing + ("\n" if existing else "") + cleaned
                    )

    return result


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities from text."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode common entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    # Collapse whitespace but preserve newlines
    text = '\n'.join(line.strip() for line in text.split('\n') if line.strip())
    return text


def count_notes_in_deck(deck_prefix: str) -> tuple[int, int]:
    """Count diseases and notes in a deck group. Returns (disease_count, note_count)."""
    grouped = read_deck_group_notes(deck_prefix)
    disease_count = len(grouped)
    note_count = sum(
        len(fields) for fields in grouped.values()
    ) if grouped else 0
    return disease_count, note_count


def build_quiz_prompt(
    grouped_notes: dict[str, dict[str, str]],
    num_questions: int = 10,
    question_type: str = "differentiating",
    custom_instruction: str = "",
) -> list[LLMMessage]:
    """Build system and user messages for quiz generation.

    Args:
        grouped_notes: {disease_name: {field_name: content, ...}, ...}
        num_questions: desired number of questions
        question_type: "differentiating" / "single_disease" / "mixed"
        custom_instruction: extra user instructions
    """
    # Build disease content text
    disease_texts = []
    for i, (disease, fields) in enumerate(grouped_notes.items(), 1):
        parts = [f"疾病 {i}：{disease}"]
        for fname, fcontent in fields.items():
            parts.append(f"  {fname}：{fcontent}")
        disease_texts.append("\n".join(parts))

    all_content = "\n\n".join(disease_texts)

    # Truncate if too long (rough estimate: ~60K chars = ~15K tokens)
    max_chars = 60000
    if len(all_content) > max_chars:
        all_content = all_content[:max_chars] + "\n\n...（内容过长已截断）"

    # Type-specific instructions
    type_instruction = {
        "differentiating": "重点生成鉴别型题目，即要求考生区分两个相似疾病。每个题目应该对比两个不同的疾病在病因/病机/病位/治则等方面的区别。",
        "single_disease": "重点生成针对单个疾病的题目，考察该疾病的病因、病机、治则、病位等核心知识。",
        "mixed": "混合生成鉴别型题目（约60%）和单一疾病题目（约40%）。",
    }.get(question_type, "")

    user_content = f"""以下是一个中医内科学牌组 "{len(grouped_notes)} 个疾病" 的所有知识卡片内容。
请根据这些内容生成 {num_questions} 道选择题。

{type_instruction}

【疾病知识卡片】

{all_content}

请生成 {num_questions} 道高质量的鉴别诊断选择题。"""

    if custom_instruction.strip():
        user_content += f"\n\n【用户额外要求】\n{custom_instruction.strip()}"

    return [
        LLMMessage(role="system", content=QUIZ_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_content),
    ]


def parse_quiz_response(content: str) -> list[dict[str, str]]:
    """Parse LLM JSON response into list of question dicts.

    Each question dict has keys: 题干, 选项A, 选项B, 选项C, 选项D, 正确答案, 解析
    """
    if not content or not content.strip():
        return []

    # Try extracting JSON from code block
    json_str = _extract_json_block(content)
    if not json_str:
        # Try finding bare JSON object
        json_match = re.search(r'\{.*"questions"\s*:.*\}', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
    if not json_str:
        return []

    try:
        data = json.loads(json_str)
        return data.get("questions", [])
    except json.JSONDecodeError:
        # Try fixing string newlines
        fixed = _fix_json_string_newlines(json_str)
        try:
            data = json.loads(fixed)
            return data.get("questions", [])
        except json.JSONDecodeError:
            return []


def _extract_json_block(text: str) -> str:
    """Extract JSON from ```json ... ``` code block."""
    start = text.find("```json")
    if start == -1:
        start = text.find("```")
    if start == -1:
        return ""
    nl = text.find("\n", start)
    if nl == -1:
        return ""
    content_start = nl + 1
    end = text.find("```", content_start)
    if end == -1:
        return ""
    candidate = text[content_start:end].strip()
    return _find_balanced_json(candidate)


def _find_balanced_json(text: str) -> str:
    """Find balanced JSON object in text."""
    start_idx = text.find("{")
    if start_idx == -1:
        return ""
    depth = 0
    in_string = False
    escape = False
    for i in range(start_idx, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start_idx:i + 1]
    return ""


def _fix_json_string_newlines(json_str: str) -> str:
    """Fix literal newlines inside JSON strings."""
    result = []
    in_string = False
    escape = False
    for c in json_str:
        if escape:
            escape = False
            result.append(c)
            continue
        if c == "\\" and in_string:
            escape = True
            result.append(c)
            continue
        if c == '"':
            in_string = not in_string
            result.append(c)
            continue
        if in_string and c == "\n":
            result.append("\\n")
        elif in_string and c == "\t":
            result.append("\\t")
        elif in_string and c == "\r":
            result.append("\\r")
        else:
            result.append(c)
    return "".join(result)


def generate_quizzes(
    deck_prefix: str,
    num_questions: int = 10,
    question_type: str = "differentiating",
    custom_instruction: str = "",
    progress_callback=None,
) -> list[dict[str, str]]:
    """Orchestrate the full quiz generation flow.

    Args:
        deck_prefix: deck path prefix, e.g. "考研/中内/01 肺系"
        num_questions: number of questions to generate
        question_type: "differentiating" / "single_disease" / "mixed"
        custom_instruction: extra user instructions
        progress_callback: optional callable(str) for progress updates

    Returns:
        List of question dicts with keys: 题干, 选项A-D, 正确答案, 解析
    """
    # Step 1: Read deck content
    if progress_callback:
        progress_callback("正在读取牌组内容...")

    grouped = read_deck_group_notes(deck_prefix)
    if not grouped:
        raise RuntimeError(
            f'在牌组组 "{deck_prefix}" 中没有找到任何笔记。\n'
            f"请确认牌组路径正确且包含卡片。"
        )

    disease_count = len(grouped)
    if progress_callback:
        progress_callback(f"已读取 {disease_count} 个疾病，正在调用 AI 生成题目...")

    # Step 2: Build prompt
    messages = build_quiz_prompt(
        grouped, num_questions, question_type, custom_instruction
    )

    # Step 3: Call LLM
    cfg = get_config()
    api_key = get_active_api_key()
    base_url = get_active_base_url()
    model = get_active_model()

    if not api_key and cfg.get("provider") != "ollama":
        raise RuntimeError("请先在设置中配置 API Key")

    client = OpenAICompatProvider(base_url=base_url, api_key=api_key)
    response = client.chat(
        messages,
        model=model,
        temperature=cfg.get("temperature", 0.7),
        max_tokens=cfg.get("max_tokens", 8192),
    )

    # Step 4: Parse response
    questions = parse_quiz_response(response.content)
    if not questions:
        raise RuntimeError(
            "AI 未能生成有效的题目。请重试，或尝试调整题目数量/类型。"
        )

    # Fix literal \\n in field values
    field_keys = ["题干", "选项A", "选项B", "选项C", "选项D", "正确答案", "解析"]
    for q in questions:
        for key in field_keys:
            if key in q and isinstance(q[key], str):
                q[key] = q[key].replace("\\n", "\n")

    # Validate required fields
    valid_questions = []
    for q in questions:
        if all(key in q for key in field_keys):
            # Validate 正确答案 is a single uppercase letter A-D
            answer = q.get("正确答案", "").strip().upper()
            if answer in ("A", "B", "C", "D"):
                q["正确答案"] = answer
                valid_questions.append(q)

    if not valid_questions:
        raise RuntimeError("AI 返回的题目格式不正确，请重试")

    if progress_callback:
        progress_callback(f"✅ 成功生成 {len(valid_questions)} 道题目")

    return valid_questions
