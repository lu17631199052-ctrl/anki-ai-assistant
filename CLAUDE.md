# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Anki AI Study Assistant

这是一个 Anki 插件，为 Anki 复习软件提供 AI 学习辅助功能。

## 技术栈
- Python 3，基于 Anki Qt API（aqt）
- 支持 OpenAI 兼容 API（DeepSeek / 通义千问 / 智谱 / Kimi / Ollama）
- HTTP 请求优先使用 curl，失败时回退到 urllib（`_CURL_FAILED` 全局标记控制）
- UI 使用 PyQt（QDialog, QTextEdit, QTableWidget, QDockWidget 等）

## 目录结构
```
anki-ai-assistant/
  __init__.py              # 插件入口，注册菜单（快捷键 Ctrl+E / Ctrl+W）
  manifest.json            # Anki 插件元数据，版本号在 human_version 字段
  config.py                # 配置管理：提供商预设、本地备份 user_config.json、视觉模型配置
  features/
    explain.py             # AI 解释当前卡片（Ctrl+E），流式 QTextBrowser
    generate.py            # AI 从文本生成卡片（JSON 解析 + 添加到牌组）
    chat.py                # ChatSession 管理对话历史，支持流式/非流式
    wrong_answer.py        # 错题截图分析：视觉模型识别 → JSON 解析 → 生成卡片
  llm/
    base.py                # LLMMessage / LLMResponse dataclass + BaseLLMProvider 抽象类
    openai_compat.py       # OpenAI 兼容 API 客户端（curl + urllib，均支持流式和非流式）
  ui/
    chat_dialog.py         # AI 对话窗口：侧边栏 QDockWidget / 浮动窗口切换，流式 Markdown 渲染
    generate_dialog.py     # AI 生成卡片窗口：左右分栏、格式工具栏、文件上传、PDF OCR、视觉识别
    wrong_answer_dialog.py # AI 错题整理窗口：截图上传/粘贴、AI 分析、添加到 MCQ 笔记类型
    settings.py            # 设置窗口：提供商选择、视觉模型配置、测试连接
    markdown.py            # Markdown 转 HTML（表格、代码块、列表、引用等）
```

## 核心架构

### LLM 层
- `LLMMessage` 支持 `images` 字段（base64 图片列表），自动构建 vision API 格式
- `OpenAICompatProvider.chat()` 同步请求，`chat_stream()` 流式请求（Generator）
- `_do_request()` 自动重试 3 次（`IncompleteRead`, `ConnectionResetError`, `TimeoutError`），退避 1.5s
- 流式解析 SSE（`data: ...`），遇到 `[DONE]` 结束

### 配置系统
- 优先级：`user_config.json`（本地备份）> Anki `addonManager.getConfig()`
- `save_config()` 同时写 Anki 系统和本地备份，解决 Windows 上 config 持久化问题
- `get_vision_config()` 返回视觉模型配置，未单独设置则回退到主模型配置

### MCQ 笔记类型（选择题）
- `ensure_mcq_note_type()` 自动创建名为 "选择题" 的笔记类型
- 正面模板包含内嵌 Markdown 渲染 JS + 可点击选项框（sessionStorage 记忆选择状态）
- 背面模板解析正确答案并显示对错结果
- 卡片正面格式要求：题目 → 空行 → `- A. xxx` 无序列表

## 关键约定
- 插件安装路径：`~/Library/Application Support/Anki2/addons21/anki_ai_assistant/`
- 源项目路径：`~/ClaudeStudy/anki-ai-assistant/`（git 仓库）
- GitHub：`https://github.com/lu17631199052-ctrl/anki-ai-assistant`
- 修改代码后需要同步到 addons21 目录，清除 `__pycache__`，重启 Anki 生效
- 打包命令：
  ```
  python3 -c "import shutil; shutil.make_archive('/Users/lujinbo/Desktop/anki_ai_assistant', 'zip', '/Users/lujinbo/Library/Application Support/Anki2/addons21/anki_ai_assistant'); import os; os.rename('/Users/lujinbo/Desktop/anki_ai_assistant.zip', '/Users/lujinbo/Desktop/anki_ai_assistant.ankiaddon')"
  ```
  注意：zip 根目录直接放文件，不要嵌套文件夹
- 安装包放桌面，上传到 AnkiWeb 发布更新

### 卡片字段处理
- 用户使用中文，笔记类型通常是"正面/背面"两字段
- 用户有专门的 Markdown 渲染模板，默认保留原始 Markdown 格式
- 只有 `md_to_html` 配置为 true 时才转为 HTML 存储
- 纯文本换行符 `\n` 转为 `<br>` 存储到 Anki 字段
- MCQ 笔记类型存储原始 Markdown（不转换），由模板内嵌 JS 渲染

## 用户偏好
- 中文交流
- 改完代码需要同步到 addons21、更新版本号、重新打包、git commit + push
- 不要随意改版本号，只在实际需要发布时更新
