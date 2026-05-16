"""Shared file parsing utilities — extract text from various document formats."""

import os
import re
import zlib
import tempfile
import subprocess
import shutil
import base64
from typing import Callable, Optional
from xml.etree import ElementTree


def _parse_pdf_text_operators(raw: bytes) -> str:
    """Parse basic PDF text operators (Tj, TJ, ') into a string."""
    parts: list[str] = []
    for m in re.finditer(rb'\((.*?)\)\s*Tj', raw):
        parts.append(m.group(1).decode("latin-1", errors="replace"))
    for m in re.finditer(rb'\[(.*?)\]\s*TJ', raw):
        for sm in re.finditer(rb'\((.*?)\)', m.group(1)):
            parts.append(sm.group(1).decode("latin-1", errors="replace"))
    for m in re.finditer(rb'\((.*?)\)\s*\'', raw):
        parts.append(m.group(1).decode("latin-1", errors="replace"))
    return "".join(parts)


def _extract_pdf_text_pure(path: str) -> str:
    """Extract text from a text-based PDF using pure Python (no pdftotext)."""
    result: list[str] = []
    with open(path, "rb") as f:
        data = f.read()

    text_pattern = re.compile(rb'BT(.*?)ET', re.DOTALL)
    stream_pattern = re.compile(rb'stream\r?\n(.*?)\r?\nendstream', re.DOTALL)

    for match in stream_pattern.finditer(data):
        stream_data = match.group(1)
        try:
            decompressed = zlib.decompress(stream_data)
            for text_match in text_pattern.finditer(decompressed):
                result.append(_parse_pdf_text_operators(text_match.group(1)))
        except (zlib.error, Exception):
            for text_match in text_pattern.finditer(stream_data):
                result.append(_parse_pdf_text_operators(text_match.group(1)))

    if not result:
        for text_match in text_pattern.finditer(data):
            result.append(_parse_pdf_text_operators(text_match.group(1)))

    return "\n".join(r for r in result if r.strip())


def _extract_pdf_images(path: str) -> list[str]:
    """Extract embedded JPEG/JPX images from a PDF (for scanned PDFs)."""
    images: list[str] = []
    with open(path, "rb") as f:
        data = f.read()

    dct_pattern = re.compile(rb'/Filter\s*/DCTDecode.*?stream\r?\n(.*?)\r?\nendstream', re.DOTALL)
    for match in dct_pattern.finditer(data):
        jpeg_data = match.group(1)
        if jpeg_data[:2] == b'\xff\xd8':
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.write(jpeg_data)
            tmp.close()
            images.append(tmp.name)

    if not images:
        jpx_pattern = re.compile(rb'/Filter\s*/JPXDecode.*?stream\r?\n(.*?)\r?\nendstream', re.DOTALL)
        for match in jpx_pattern.finditer(data):
            jpx_data = match.group(1)
            if jpx_data[:4] == b'\x00\x00\x00\x0c':
                tmp = tempfile.NamedTemporaryFile(suffix=".jp2", delete=False)
                tmp.write(jpx_data)
                tmp.close()
                images.append(tmp.name)

    return images


def _run_vision_ocr(
    img_path: str,
    base_url: str,
    api_key: str,
    model: str,
) -> str:
    """Run vision-model OCR on a single image. Returns extracted text."""
    ext = os.path.splitext(img_path)[1].lower()
    mime_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif", ".bmp": "bmp", ".webp": "webp"}
    mime = mime_map.get(ext, "jpeg")

    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("ascii")
    data_url = f"data:image/{mime};base64,{img_b64}"

    from ..llm.base import LLMMessage
    from ..llm.openai_compat import OpenAICompatProvider

    client = OpenAICompatProvider(base_url=base_url, api_key=api_key)
    msg = LLMMessage(
        role="user",
        content="请提取这张图片中的所有文字内容，保持原有格式。如果是表格请用 Markdown 表格格式输出。只输出文字，不要添加额外说明。",
        images=[data_url],
    )
    response = client.chat([msg], model=model, temperature=0.1, max_tokens=4096)
    return response.content.strip()


def _parse_docx_text(path: str) -> str:
    """Extract text from a .docx file (ZIP containing XML). No external deps."""
    import zipfile
    from xml.etree import ElementTree

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []

    with zipfile.ZipFile(path, "r") as zf:
        if "word/document.xml" not in zf.namelist():
            raise RuntimeError("无效的 docx 文件：未找到 word/document.xml")
        xml_content = zf.read("word/document.xml")
        root = ElementTree.fromstring(xml_content)
        for p_elem in root.iter(f"{{{ns['w']}}}p"):
            text_parts: list[str] = []
            for t_elem in p_elem.iter(f"{{{ns['w']}}}t"):
                if t_elem.text:
                    text_parts.append(t_elem.text)
            if text_parts:
                paragraphs.append("".join(text_parts))

    return "\n".join(paragraphs)


def parse_file_to_text(
    path: str,
    vision_config: Optional[dict] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> str:
    """Parse any supported file to text.

    Supported: txt, md, py, json, csv, xml, html, css, js, ts, pdf, docx,
               png, jpg, jpeg, gif, bmp, webp

    vision_config: {"base_url": ..., "api_key": ..., "model": ...}
    progress_callback: called with status messages during processing
    """
    ext = os.path.splitext(path)[1].lower()

    # Plain text files
    if ext in (".txt", ".md", ".py", ".json", ".csv", ".xml", ".html", ".css", ".js", ".ts"):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    # PDF
    if ext == ".pdf":
        # Try pdftotext first
        pdftotext_bin = None
        for candidate in [
            "/opt/homebrew/bin/pdftotext",
            "/usr/local/bin/pdftotext",
        ]:
            if os.path.isfile(candidate):
                pdftotext_bin = candidate
                break
        if pdftotext_bin is None:
            pdftotext_bin = shutil.which("pdftotext")
        if pdftotext_bin is None and os.name == "nt":
            for candidate in [
                r"C:\Program Files\poppler\bin\pdftotext.exe",
                r"C:\poppler\bin\pdftotext.exe",
            ]:
                if os.path.isfile(candidate):
                    pdftotext_bin = candidate
                    break

        if pdftotext_bin is not None:
            result = subprocess.run(
                [pdftotext_bin, "-layout", path, "-"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()

        # Pure Python fallback
        text = _extract_pdf_text_pure(path)
        if text:
            return text

        # Scanned PDF — try image extraction + OCR
        if not vision_config or not vision_config.get("api_key"):
            raise RuntimeError("PDF 中未提取到文字，需要配置视觉模型 API Key 进行 OCR 识别")

        images = _extract_pdf_images(path)
        if not images:
            raise RuntimeError("PDF 中未提取到文字，也找不到嵌入图片。请尝试用截图方式。")

        if progress_callback:
            progress_callback(f"扫描版 PDF，正在识别 {len(images)} 页...")

        all_text: list[str] = []
        for i, img_path in enumerate(images):
            if progress_callback:
                progress_callback(f"正在识别第 {i + 1}/{len(images)} 页...")
            try:
                page_text = _run_vision_ocr(
                    img_path,
                    base_url=vision_config["base_url"],
                    api_key=vision_config["api_key"],
                    model=vision_config["model"],
                )
                if page_text.strip():
                    all_text.append(page_text.strip())
            finally:
                os.unlink(img_path)

        if not all_text:
            raise RuntimeError("AI 未能识别出图片中的文字")
        return "\n\n".join(all_text)

    # Images — OCR
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
        if not vision_config or not vision_config.get("api_key"):
            raise RuntimeError("需要配置视觉模型 API Key 进行图片识别")
        if progress_callback:
            progress_callback("正在用 AI 识别图片中的文字...")
        return _run_vision_ocr(
            path,
            base_url=vision_config["base_url"],
            api_key=vision_config["api_key"],
            model=vision_config["model"],
        )

    # DOCX
    if ext == ".docx":
        return _parse_docx_text(path)

    # Unknown — try as plain text
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
