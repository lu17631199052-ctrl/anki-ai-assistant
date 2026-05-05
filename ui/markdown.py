"""Markdown-to-HTML conversion shared across UI components."""

import re


def md_to_html(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Fenced code block
        if line.strip().startswith("```"):
            lang = line.strip()[3:].strip()
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            code = "\n".join(code_lines)
            out.append(f"<pre><code>{_escape_html(code)}</code></pre>")
            continue

        # Table: current line starts with | and next line is separator
        if line.strip().startswith("|") and i + 1 < len(lines):
            sep = lines[i + 1].strip()
            if re.match(r'^\|[\s\-:|]+\|$', sep):
                out.append(_render_table(lines, i))
                while i < len(lines) and lines[i].strip().startswith("|"):
                    i += 1
                continue

        # Horizontal rule
        if re.match(r'^[-*_]{3,}\s*$', line.strip()):
            out.append("<hr>")
            i += 1
            continue

        # Heading
        h_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if h_match:
            level = len(h_match.group(1))
            out.append(f"<h{level}>{_inline_md(h_match.group(2))}</h{level}>")
            i += 1
            continue

        # Blockquote
        if line.startswith(">"):
            bq_lines: list[str] = []
            while i < len(lines) and lines[i].startswith(">"):
                bq_lines.append(lines[i][1:].strip())
                i += 1
            bq_text = "<br>".join(_inline_md(l) for l in bq_lines)
            out.append(f"<blockquote style='border-left:3px solid #ccc; padding-left:12px; color:#555;'>{bq_text}</blockquote>")
            continue

        # Unordered list
        if re.match(r'^[\s]*[-*+]\s+', line):
            list_lines: list[str] = []
            while i < len(lines) and re.match(r'^[\s]*[-*+]\s+', lines[i]):
                item = re.sub(r'^[\s]*[-*+]\s+', '', lines[i])
                list_lines.append(_inline_md(item))
                i += 1
            items = "".join(f"<li>{l}</li>" for l in list_lines)
            out.append(f"<ul>{items}</ul>")
            continue

        # Ordered list
        if re.match(r'^[\s]*\d+\.\s+', line):
            list_lines = []
            while i < len(lines) and re.match(r'^[\s]*\d+\.\s+', lines[i]):
                item = re.sub(r'^[\s]*\d+\.\s+', '', lines[i])
                list_lines.append(_inline_md(item))
                i += 1
            items = "".join(f"<li>{l}</li>" for l in list_lines)
            out.append(f"<ol>{items}</ol>")
            continue

        # Blank line
        if not line.strip():
            out.append("<br>")
            i += 1
            continue

        # Regular paragraph
        out.append(_inline_md(line))
        i += 1

    html = "\n".join(out)
    return f'<div style="font-size:14px; line-height:1.6;">{html}</div>'


def _render_table(lines: list[str], start: int) -> str:
    rows: list[list[str]] = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        cells = [c.strip() for c in lines[i].strip().split("|")[1:-1]]
        if not re.match(r'^[\s\-:|]+$', "|".join(cells)):
            rows.append(cells)
        i += 1

    if not rows:
        return ""

    html = '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse; width:100%; margin:8px 0;">'
    for ri, row in enumerate(rows):
        tag = "th" if ri == 0 else "td"
        style = ' style="background:#f0f0f0; font-weight:bold;"' if ri == 0 else ""
        html += "<tr>"
        for cell in row:
            html += f"<{tag}{style}>{_inline_md(cell)}</{tag}>"
        html += "</tr>"
    html += "</table>"
    return html


def _inline_md(text: str) -> str:
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'<img src="\2" alt="\1" style="max-width:100%;">', text)
    return text


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
