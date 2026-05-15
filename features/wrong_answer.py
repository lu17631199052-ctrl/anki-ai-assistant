"""Analyze wrong multiple-choice questions from screenshots and create Anki cards."""

import json
import re
import os

from aqt import mw

from ..config import get_config, get_vision_config
from ..llm.base import LLMMessage
from ..llm.openai_compat import OpenAICompatProvider

MCQ_NOTE_TYPE_NAME = "选择题"

WRONG_ANSWER_SYSTEM_PROMPT = """你是一个专业的中医综合（中综）考试辅导助手。用户会提供一道选择题的截图，请仔细分析图片内容后，按以下要求输出：

1. 识别题目文字和所有选项（A/B/C/D 等）
2. 根据题目内容判断正确答案
3. 对每个选项进行分析，解释为什么对/错
4. 提供相关知识点总结和记忆技巧

**卡片正面格式（必须严格遵守，用于生成可点击的选项框）**：
```
题目文字

- A. 选项A内容
- B. 选项B内容
- C. 选项C内容
- D. 选项D内容
```
即：题目单独一段，空一行，每个选项用 "- A." 等开头（Markdown 无序列表格式），每个选项单独一行。

**卡片背面格式**：
- 正确答案及理由
- 各选项分析（错误选项错在哪里）
- 相关知识点补充
- 如有记忆口诀请一并提供
- 所有内容使用 Markdown 格式

请严格按照以下 JSON 格式返回，不要包含其他内容：
```json
{
  "cards": [
    {
      "front": "题目文字和选项（Markdown格式）",
      "back": "正确答案和详细解析（Markdown格式）"
    }
  ]
}
```

注意：
- 如果截图中包含多道题，请为每道题生成一张卡片
- 如果截图中明确标出了正确答案（如红笔圈出、打勾等），以标注为准
- 如果无法确定正确答案，请根据你的知识判断最可能的答案，并在解析中说明"""  # noqa: E501


# ═══════════════════════════════════════════════════════════════════
# Image analysis
# ═══════════════════════════════════════════════════════════════════

def analyze_wrong_answer(image_path: str) -> list[dict[str, str]]:
    import base64

    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif", ".bmp": "bmp", ".webp": "webp"}
    mime = mime_map.get(ext, "jpeg")

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("ascii")
    data_url = f"data:image/{mime};base64,{img_b64}"

    vc = get_vision_config()
    if not vc["api_key"]:
        raise RuntimeError("请在设置中配置视觉模型 API Key")

    client = OpenAICompatProvider(base_url=vc["base_url"], api_key=vc["api_key"])
    messages = [
        LLMMessage(role="system", content=WRONG_ANSWER_SYSTEM_PROMPT),
        LLMMessage(role="user", content="请分析这道错题截图，生成 Anki 卡片。", images=[data_url]),
    ]

    response = client.chat(
        messages,
        model=vc["model"],
        temperature=0.3,
        max_tokens=get_config().get("max_tokens", 4096),
    )

    cards = _parse_cards_json(response.content)
    if not cards:
        raw = response.content.strip()
        if raw:
            cards = [{"front": "错题分析（请编辑题目）", "back": raw}]
        else:
            raise RuntimeError("AI 返回为空，请重试")

    for card in cards:
        for key in ("front", "back"):
            if key in card:
                card[key] = card[key].replace("\\n", "\n")

    return cards


# ═══════════════════════════════════════════════════════════════════
# JSON parsing
# ═══════════════════════════════════════════════════════════════════

def _parse_cards_json(content: str) -> list[dict[str, str]]:
    json_str = _extract_json_block(content)
    if not json_str:
        json_match = re.search(r'\{.*"cards"\s*:.*\}', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
    if not json_str:
        return []

    try:
        data = json.loads(json_str)
        return data.get("cards", [])
    except json.JSONDecodeError:
        fixed = _fix_json_string_newlines(json_str)
        try:
            data = json.loads(fixed)
            return data.get("cards", [])
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
    candidate = text[content_start:end].strip()
    return _find_balanced_json(candidate)


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


# ═══════════════════════════════════════════════════════════════════
# JavaScript Markdown renderer
# ═══════════════════════════════════════════════════════════════════

_MARKDOWN_JS = """
<script>
function mdToHtml(text) {
  var lines = text.split('\\n');
  var out = [];
  var i = 0;

  while (i < lines.length) {
    var line = lines[i];
    var trimmed = line.trim();

    if (trimmed.startsWith('```')) {
      i++;
      var codeLines = [];
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      i++;
      out.push('<pre><code>' + escHtml(codeLines.join('\\n')) + '</code></pre>');
      continue;
    }

    if (trimmed.startsWith('|') && i + 1 < lines.length && isTableSep(lines[i + 1].trim())) {
      out.push(renderTable(lines, i));
      while (i < lines.length && lines[i].trim().startsWith('|')) i++;
      continue;
    }

    if (/^[-*_]{3,}\\s*$/.test(trimmed)) {
      out.push('<hr>');
      i++;
      continue;
    }

    var hm = trimmed.match(/^(#{1,6})\\s+(.+)$/);
    if (hm) {
      var level = hm[1].length;
      out.push('<h' + level + '>' + inlineMd(hm[2]) + '</h' + level + '>');
      i++;
      continue;
    }

    if (line.startsWith('>')) {
      var bqLines = [];
      while (i < lines.length && lines[i].startsWith('>')) {
        bqLines.push(lines[i].substring(1).trim());
        i++;
      }
      out.push('<blockquote>' + bqLines.map(function(l) { return inlineMd(l); }).join('<br>') + '</blockquote>');
      continue;
    }

    if (/^\\s*[-*+]\\s+/.test(line)) {
      var ulLines = [];
      while (i < lines.length && /^\\s*[-*+]\\s+/.test(lines[i])) {
        ulLines.push(lines[i].replace(/^\\s*[-*+]\\s+/, ''));
        i++;
      }
      out.push('<ul>' + ulLines.map(function(l) { return '<li>' + inlineMd(l) + '</li>'; }).join('') + '</ul>');
      continue;
    }

    if (/^\\s*\\d+\\.\\s+/.test(line)) {
      var olLines = [];
      while (i < lines.length && /^\\s*\\d+\\.\\s+/.test(lines[i])) {
        olLines.push(lines[i].replace(/^\\s*\\d+\\.\\s+/, ''));
        i++;
      }
      out.push('<ol>' + olLines.map(function(l) { return '<li>' + inlineMd(l) + '</li>'; }).join('') + '</ol>');
      continue;
    }

    if (!trimmed) {
      out.push('<br>');
      i++;
      continue;
    }

    out.push(inlineMd(line));
    i++;
  }

  return out.join('\\n');
}

function inlineMd(text) {
  text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
  text = text.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
  text = text.replace(/\\*(.+?)\\*/g, '<i>$1</i>');
  text = text.replace(/~~(.+?)~~/g, '<s>$1</s>');
  text = text.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g, '<a href="$2">$1</a>');
  return text;
}

function escHtml(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function isTableSep(line) {
  return /^\\|[\\s\\-:|]+\\|$/.test(line);
}

function renderTable(lines, start) {
  var rows = [];
  var i = start;
  while (i < lines.length && lines[i].trim().startsWith('|')) {
    var cells = lines[i].trim().split('|').slice(1, -1).map(function(c) { return c.trim(); });
    if (!/^[\\s\\-:|]+$/.test(cells.join('|'))) {
      rows.push(cells);
    }
    i++;
  }
  if (!rows.length) return '';
  var html = '<table>';
  for (var ri = 0; ri < rows.length; ri++) {
    var tag = ri === 0 ? 'th' : 'td';
    var style = ri === 0 ? ' style="background:#F0F3F8; font-weight:600;"' : '';
    html += '<tr>';
    for (var ci = 0; ci < rows[ri].length; ci++) {
      html += '<' + tag + style + '>' + inlineMd(rows[ri][ci]) + '</' + tag + '>';
    }
    html += '</tr>';
  }
  html += '</table>';
  return html;
}
</script>
"""


# ═══════════════════════════════════════════════════════════════════
# MCQ Note Type
# ═══════════════════════════════════════════════════════════════════

def ensure_mcq_note_type() -> int:
    col = mw.col
    model = col.models.by_name(MCQ_NOTE_TYPE_NAME)
    if model:
        if model["tmpls"]:
            model["tmpls"][0]["qfmt"] = _build_front_template()
            model["tmpls"][0]["afmt"] = _build_back_template()
            col.models.save(model)
        return model["id"]

    model = col.models.new(MCQ_NOTE_TYPE_NAME)
    field_q = col.models.new_field("题目")
    col.models.add_field(model, field_q)
    field_a = col.models.new_field("解析")
    col.models.add_field(model, field_a)

    template = col.models.new_template("选择题")
    template["qfmt"] = _build_front_template()
    template["afmt"] = _build_back_template()
    col.models.add_template(model, template)

    col.models.add(model)
    col.models.save(model)
    return model["id"]


def _build_front_template() -> str:
    return _MARKDOWN_JS + r"""<div id="mq-raw" style="display:none">{{题目}}</div>
<div id="mq-content" class="mcq-card"></div>

<style>
.mcq-card {
  font-family: -apple-system, "Microsoft YaHei", "PingFang SC", "Noto Sans", sans-serif;
  max-width: 780px;
  margin: 0 auto;
  padding: 32px 36px;
}
.mcq-badge {
  display: inline-block;
  background: linear-gradient(135deg, #5B7FFF 0%, #3366FF 100%);
  color: #fff;
  padding: 6px 22px;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 2px;
  margin-bottom: 28px;
}
.mcq-question {
  font-size: 21px;
  line-height: 1.8;
  color: #1a1a2e;
  font-weight: 500;
  margin-bottom: 30px;
  padding-bottom: 22px;
  border-bottom: 2px solid #EEF0F4;
}
.mcq-options {
  list-style: none;
  padding: 0;
  margin: 0;
}
.mcq-option {
  display: flex;
  align-items: flex-start;
  padding: 14px 18px;
  margin-bottom: 8px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.15s;
  border: 2px solid transparent;
}
.mcq-option:hover {
  background: #F5F7FB;
  border-color: #D8DFE8;
}
.mcq-option.selected {
  background: #EDF3FF;
  border-color: #5B7FFF;
}
.mcq-check {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  border: 2.5px solid #C0C7D0;
  flex-shrink: 0;
  margin-right: 16px;
  margin-top: 1px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  font-size: 14px;
  font-weight: 700;
  color: transparent;
  box-sizing: border-box;
}
.mcq-option.selected .mcq-check {
  border-color: #5B7FFF;
  background: #5B7FFF;
  color: #fff;
}
.mcq-option-text {
  font-size: 18px;
  line-height: 1.6;
  color: #333;
}
.mcq-option-text strong { color: #2c3e50; }
.mcq-hint {
  margin-top: 30px;
  font-size: 13px;
  color: #BBC3CD;
  text-align: center;
  letter-spacing: 1px;
}
</style>

<script>
(function() {
  var el = document.getElementById('mq-raw');
  if (!el) return;
  var raw = (el.innerText || el.textContent || '').trim();
  var html = mdToHtml(raw);

  // Find <ul> block (options list) and separate from question
  var ulStart = html.indexOf('<ul>');
  var ulEnd = html.indexOf('</ul>');
  var questionHtml, optionsHtml = '';

  if (ulStart !== -1 && ulEnd !== -1) {
    questionHtml = html.substring(0, ulStart);
    var items = html.substring(ulStart + 4, ulEnd);
    // Add checkbox + onclick to each li
    items = items.replace(
      /<li>/g,
      '<li class="mcq-option" onclick="this.classList.toggle(\'selected\');saveMcqSelection()">' +
      '<span class="mcq-check">✓</span>' +
      '<span class="mcq-option-text">'
    );
    items = items.replace(/<\/li>/g, '</span></li>');
    optionsHtml = '<ul class="mcq-options">' + items + '</ul>';
  } else {
    questionHtml = html;
  }

  // Generate a stable key from question text for sessionStorage
  var firstLine = raw.split('\n')[0].trim();
  var hash = 0;
  for (var i = 0; i < firstLine.length; i++) {
    hash = ((hash << 5) - hash) + firstLine.charCodeAt(i);
    hash |= 0;
  }
  window._mcqKey = 'mcq_' + Math.abs(hash);

  window.saveMcqSelection = function() {
    var selected = [];
    var opts = document.querySelectorAll('.mcq-option.selected .mcq-option-text');
    for (var i = 0; i < opts.length; i++) {
      var t = opts[i].textContent.trim();
      var m = t.match(/^([A-E])/);
      if (m) selected.push(m[1]);
    }
    try { sessionStorage.setItem(window._mcqKey, selected.sort().join('')); } catch(e) {}
  };

  // Restore previous selection if exists
  try {
    var prev = sessionStorage.getItem(window._mcqKey);
    if (prev) {
      var opts = document.querySelectorAll('.mcq-option-text');
      for (var i = 0; i < opts.length; i++) {
        var t = opts[i].textContent.trim();
        var m = t.match(/^([A-E])/);
        if (m && prev.indexOf(m[1]) !== -1) {
          opts[i].parentNode.classList.add('selected');
        }
      }
    }
  } catch(e) {}

  document.getElementById('mq-content').innerHTML =
    '<div class="mcq-badge">选择题</div>' +
    '<div class="mcq-question">' + questionHtml + '</div>' +
    optionsHtml +
    '<div class="mcq-hint">选择答案后翻面查看解析</div>';
})();
</script>
"""


def _build_back_template() -> str:
    return _MARKDOWN_JS + """<div id="mq-raw-q" style="display:none">{{题目}}</div>
<div id="mq-raw-a" style="display:none">{{解析}}</div>
<div id="mq-content" class="mcq-card"></div>

<style>
.mcq-card {
  font-family: -apple-system, "Microsoft YaHei", "PingFang SC", "Noto Sans", sans-serif;
  max-width: 720px;
  margin: 0 auto;
  padding: 28px 32px;
}
.mcq-card .mcq-badge {
  display: inline-block;
  background: linear-gradient(135deg, #5B7FFF 0%, #3366FF 100%);
  color: #fff;
  padding: 4px 18px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 1px;
  margin-bottom: 20px;
}
.mcq-card .mcq-q-section {
  background: #F8FAFB; border: 1px solid #E4E8EE; border-radius: 10px;
  padding: 16px 20px; margin-bottom: 20px;
}
.mcq-card .mcq-q-label {
  font-size: 12px; color: #8899AA; font-weight: 600;
  letter-spacing: 2px; text-transform: uppercase; margin-bottom: 8px;
}
.mcq-card .mcq-q-body { font-size: 16px; line-height: 1.9; color: #1a1a2e; }
.mcq-card .mcq-q-body p { margin: 0 0 8px 0; }
.mcq-card .mcq-q-body strong { color: #2c3e50; }
.mcq-card .mcq-divider {
  border: none; border-top: 2px solid #E8ECF1; margin: 24px 0;
}
.mcq-card .mcq-a-label {
  font-size: 12px; color: #27AE60; font-weight: 600;
  letter-spacing: 2px; text-transform: uppercase; margin-bottom: 12px;
}
.mcq-card .mcq-a-body { font-size: 15px; line-height: 1.9; color: #333; }
.mcq-card .mcq-a-body h1, .mcq-card .mcq-a-body h2, .mcq-card .mcq-a-body h3 {
  color: #2c3e50; margin: 18px 0 10px 0; font-weight: 600;
}
.mcq-card .mcq-a-body h2 {
  border-bottom: 2px solid #EEF2F7; padding-bottom: 6px;
}
.mcq-card .mcq-a-body strong { color: #E74C3C; font-weight: 600; }
.mcq-card .mcq-a-body p { margin: 0 0 10px 0; }
.mcq-card .mcq-a-body ul, .mcq-card .mcq-a-body ol { padding-left: 24px; margin: 8px 0; }
.mcq-card .mcq-a-body li { margin: 6px 0; }
.mcq-card .mcq-a-body code {
  background: #EEF2F7; padding: 2px 6px; border-radius: 4px; font-size: 90%;
}
.mcq-card .mcq-a-body pre {
  background: #F5F7FA; padding: 14px 18px; border-radius: 8px;
  border: 1px solid #E4E8EE; overflow-x: auto; font-size: 14px; line-height: 1.6;
}
.mcq-card .mcq-a-body blockquote {
  border-left: 3px solid #27AE60; padding: 8px 18px; margin: 14px 0;
  color: #5A6A7E; background: #F8FAFB; border-radius: 0 6px 6px 0;
}
.mcq-card .mcq-a-body table {
  border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 14px;
}
.mcq-card .mcq-a-body th {
  background: #F0F3F8; font-weight: 600; padding: 8px 14px;
  border: 1px solid #D8DEE6; text-align: left;
}
.mcq-card .mcq-a-body td {
  padding: 8px 14px; border: 1px solid #E4E8EE;
}
.mcq-card .mcq-a-body hr { border: none; border-top: 1px solid #E4E8EE; margin: 16px 0; }
.mcq-card .mcq-a-body a { color: #5B7FFF; }
</style>

<script>
(function() {
  var elQ = document.getElementById('mq-raw-q');
  var elA = document.getElementById('mq-raw-a');
  if (!elQ || !elA) return;

  function decodeRaw(el) {
    var raw = el.innerHTML;
    raw = raw.replace(/<br\\s*\\/?>/gi, '\\n');
    raw = raw.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/&quot;/g, '"');
    raw = raw.replace(/<div>/gi, '').replace(/<\\/div>/gi, '\\n');
    return raw.trim();
  }

  var qHtml = mdToHtml(decodeRaw(elQ));
  var aHtml = mdToHtml(decodeRaw(elA));

  // Parse correct answer from 解析 field
  var rawA = decodeRaw(elA);
  var correctMatch = rawA.match(/正确答案[：:]\s*([A-E]+)/);
  var correct = correctMatch ? correctMatch[1].split('').sort().join('') : '';

  // Read user selection from sessionStorage
  var firstLine = decodeRaw(elQ).split('\\n')[0].trim();
  var hash = 0;
  for (var i = 0; i < firstLine.length; i++) {
    hash = ((hash << 5) - hash) + firstLine.charCodeAt(i);
    hash |= 0;
  }
  var key = 'mcq_' + Math.abs(hash);
  var selected = '';
  try { selected = sessionStorage.getItem(key) || ''; } catch(e) {}

  // Build result banner
  var resultHtml = '';
  if (correct && selected) {
    var isCorrect = (selected === correct);
    var badgeColor = isCorrect ? '#27AE60' : '#E74C3C';
    var badgeIcon = isCorrect ? '✓' : '✗';
    var badgeText = isCorrect ? '回答正确' : '回答错误';
    resultHtml =
      '<div style="margin-bottom:18px;padding:12px 20px;border-radius:10px;' +
      'background:' + (isCorrect ? '#E8F8F0' : '#FDEDEC') + ';' +
      'border:1.5px solid ' + badgeColor + ';display:flex;align-items:center;gap:14px;">' +
      '<span style="display:flex;align-items:center;justify-content:center;' +
      'width:32px;height:32px;border-radius:50%;background:' + badgeColor + ';color:#fff;' +
      'font-size:18px;font-weight:700;flex-shrink:0;">' + badgeIcon + '</span>' +
      '<div><div style="font-size:15px;font-weight:700;color:' + badgeColor + ';">' + badgeText + '</div>' +
      '<div style="font-size:13px;color:#666;margin-top:2px;">' +
      '你的答案：<b>' + (selected || '未选择') + '</b>　正确答案：<b>' + correct + '</b></div></div></div>';
  }

  document.getElementById('mq-content').innerHTML =
    '<div class="mcq-badge">选择题</div>' +
    resultHtml +
    '<div class="mcq-q-section"><div class="mcq-q-label">题 目</div><div class="mcq-q-body">' + qHtml + '</div></div>' +
    '<div class="mcq-divider"></div>' +
    '<div class="mcq-a-label">解 析</div><div class="mcq-a-body">' + aHtml + '</div>';
})();
</script>
"""


# ═══════════════════════════════════════════════════════════════════
# Add cards to deck (MCQ variant — preserves raw Markdown)
# ═══════════════════════════════════════════════════════════════════

def add_mcq_cards_to_deck(
    cards: list[dict[str, str]],
    deck_id: int,
    note_type_id: int,
    tags: str = "",
) -> int:
    from anki.notes import Note

    col = mw.col
    deck = col.decks.get(deck_id)
    if not deck:
        raise RuntimeError("目标牌组不存在")

    model = col.models.get(note_type_id)
    if not model:
        raise RuntimeError("目标笔记类型不存在")

    added = 0
    for card in cards:
        note = Note(col, model)
        note.fields[0] = card.get("front", "")
        note.fields[1] = card.get("back", "")
        if tags:
            note.tags = [t.strip() for t in tags.split() if t.strip()]
        col.add_note(note, deck_id)
        added += 1

    return added
