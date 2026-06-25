"""AI quiz generator — reads deck content and generates practice questions."""

import json
import re

from aqt import mw

from ..config import get_config, get_active_base_url, get_active_api_key, get_active_model
from ..llm.base import LLMMessage
from ..llm.openai_compat import OpenAICompatProvider


QUIZ_SYSTEM_PROMPT = """你是中医内科学出题专家。根据提供的疾病知识生成选择题，帮助区分易混淆疾病。

【出题原则】
1. 重点出鉴别诊断题：两个相似疾病在病因/病机/病位/治则上的区别
2. 约60%鉴别型（两病对比），约40%单一疾病题
3. 避免定义默写，考察理解和鉴别能力
4. 错误选项必须是同章节疾病，有干扰性
5. 解析简洁：正确选项为何对，错误选项各对应哪个病

【输出格式】严格JSON，不要其他内容：
```json
{
  "questions": [
    {
      "题干": "...",
      "选项A": "...",
      "选项B": "...",
      "选项C": "...",
      "选项D": "...",
      "正确答案": "A",
      "解析": "对：... | 错：A对应X病，B对应Y病..."
    }
  ]
}
```
正确答案只能是 A/B/C/D 之一。题干具体说明在问什么。选项简洁。"""


def read_deck_group_notes(deck_prefix: str) -> dict[str, dict[str, str]]:
    """Read all notes under a deck group, grouped by disease name."""
    all_decks = mw.col.decks.all_names_and_ids()
    matching_decks = [d for d in all_decks if d.name.startswith(deck_prefix)]
    if not matching_decks:
        return {}

    all_nids: list[int] = []
    for deck in matching_decks:
        nids = mw.col.find_notes(f'"deck:{deck.name}"')
        all_nids.extend(nids)
    all_nids = list(set(all_nids))
    if not all_nids:
        return {}

    did_to_name: dict[int, str] = {d.id: d.name for d in matching_decks}
    result: dict[str, dict[str, str]] = {}

    for nid in all_nids:
        try:
            note = mw.col.get_note(nid)
        except Exception:
            continue

        cids = mw.col.db.list("SELECT id FROM cards WHERE nid = ? LIMIT 1", nid)
        if not cids:
            continue
        card = mw.col.get_card(cids[0])
        deck_name = did_to_name.get(card.did, "")

        parts = deck_name.split("::")
        disease_raw = parts[-1] if parts else deck_name
        disease = re.sub(r'^\d+\s*', '', disease_raw).strip()
        if not disease:
            disease = disease_raw

        if disease not in result:
            result[disease] = {}

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
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    text = '\n'.join(line.strip() for line in text.split('\n') if line.strip())
    return text


def count_notes_in_deck(deck_prefix: str) -> tuple[int, int]:
    grouped = read_deck_group_notes(deck_prefix)
    disease_count = len(grouped)
    total_fields = sum(len(fields) for fields in grouped.values()) if grouped else 0
    return disease_count, total_fields


def build_quiz_prompt(
    grouped_notes: dict[str, dict[str, str]],
    num_questions: int = 10,
    question_type: str = "differentiating",
    custom_instruction: str = "",
) -> list[LLMMessage]:
    # Build compact disease summary: one line per disease with key info
    disease_lines = []
    for i, (disease, fields) in enumerate(grouped_notes.items(), 1):
        # Extract key fields concisely
        parts = [disease]
        for key in ["病因", "病机", "治则", "治法", "病位"]:
            if key in fields:
                val = fields[key].replace("\n", "；")
                # Truncate very long field values
                if len(val) > 200:
                    val = val[:200] + "..."
                parts.append(f"{key}：{val}")
        if "口诀" in fields:
            rhyme = fields["口诀"].replace("\n", " ")
            if len(rhyme) > 150:
                rhyme = rhyme[:150] + "..."
            parts.append(f"口诀：{rhyme}")
        disease_lines.append(" | ".join(parts))

    all_content = "\n".join(disease_lines)

    # Truncate if too long
    max_chars = 40000
    if len(all_content) > max_chars:
        all_content = all_content[:max_chars] + "\n...（内容过长已截断）"

    type_instruction = {
        "differentiating": "重点生成鉴别型题目（区分两个相似疾病）。",
        "single_disease": "重点生成单一疾病知识题。",
        "mixed": "鉴别型约60%，单一疾病约40%。",
    }.get(question_type, "")

    user_content = f"以下为 {len(grouped_notes)} 个疾病的知识。请生成 {num_questions} 道选择题。{type_instruction}\n\n{all_content}"

    if custom_instruction.strip():
        user_content += f"\n\n额外要求：{custom_instruction.strip()}"

    return [
        LLMMessage(role="system", content=QUIZ_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_content),
    ]


def parse_quiz_response(content: str) -> list[dict[str, str]]:
    if not content or not content.strip():
        return []

    json_str = _extract_json_block(content)
    if not json_str:
        json_match = re.search(r'\{.*"questions"\s*:.*\}', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
    if not json_str:
        return []

    try:
        data = json.loads(json_str)
        return data.get("questions", [])
    except json.JSONDecodeError:
        fixed = _fix_json_string_newlines(json_str)
        try:
            data = json.loads(fixed)
            return data.get("questions", [])
        except json.JSONDecodeError:
            return []


def _extract_json_block(text: str) -> str:
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
    return _find_balanced_json(text[content_start:end].strip())


def _find_balanced_json(text: str) -> str:
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
    stream_callback=None,
) -> list[dict[str, str]]:
    """Orchestrate the full quiz generation flow with streaming support.

    Args:
        deck_prefix: deck path prefix, e.g. "考研/中内/01 肺系"
        num_questions: number of questions to generate
        question_type: "differentiating" / "single_disease" / "mixed"
        custom_instruction: extra user instructions
        progress_callback: callable(str) for status messages
        stream_callback: callable(str) called with each content chunk as it arrives

    Returns:
        List of question dicts with keys: 题干, 选项A-D, 正确答案, 解析
    """
    # Step 1: Read deck content
    if progress_callback:
        progress_callback("正在读取牌组内容...")

    grouped = read_deck_group_notes(deck_prefix)
    if not grouped:
        raise RuntimeError(
            f'在牌组组 "{deck_prefix}" 中没有找到任何笔记。'
        )

    disease_count = len(grouped)
    if progress_callback:
        progress_callback(f"已读取 {disease_count} 个疾病，正在生成题目...")

    # Step 2: Build prompt
    messages = build_quiz_prompt(
        grouped, num_questions, question_type, custom_instruction
    )

    # Step 3: Call LLM with streaming for real-time feedback
    cfg = get_config()
    api_key = get_active_api_key()
    base_url = get_active_base_url()
    model = get_active_model()

    if not api_key and cfg.get("provider") != "ollama":
        raise RuntimeError("请先在设置中配置 API Key")

    client = OpenAICompatProvider(base_url=base_url, api_key=api_key)

    # Use streaming — show progress as AI generates
    accumulated = ""
    char_count = 0
    try:
        for chunk in client.chat_stream(
            messages,
            model=model,
            temperature=cfg.get("temperature", 0.7),
            max_tokens=4096,  # 10 questions ~2-3K tokens, 4096 is plenty
        ):
            # Skip finish reason markers
            if chunk.startswith("__FINISH_REASON__:"):
                continue
            accumulated += chunk
            char_count += len(chunk)
            # Status update every ~200 chars
            if stream_callback and char_count % 200 < len(chunk):
                stream_callback(f"已生成 {len(accumulated)} 字...")
    except RuntimeError:
        # If streaming fails, fall back to non-streaming
        if progress_callback:
            progress_callback("流式请求失败，切换为非流式模式...")
        response = client.chat(
            messages,
            model=model,
            temperature=cfg.get("temperature", 0.7),
            max_tokens=4096,
        )
        accumulated = response.content

    # Step 4: Parse response
    questions = parse_quiz_response(accumulated)
    if not questions:
        raise RuntimeError("AI 未能生成有效的题目。请重试。")

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
            answer = q.get("正确答案", "").strip().upper()
            if answer in ("A", "B", "C", "D"):
                q["正确答案"] = answer
                valid_questions.append(q)

    if not valid_questions:
        raise RuntimeError("AI 返回的题目格式不正确，请重试")

    if progress_callback:
        progress_callback(f"✅ 成功生成 {len(valid_questions)} 道题目")

    return valid_questions
