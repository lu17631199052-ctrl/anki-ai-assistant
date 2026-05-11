# Anki AI Study Assistant

这是一个 Anki 插件，为 Anki 复习软件提供 AI 学习辅助功能。

## 技术栈
- Python 3，基于 Anki Qt API（aqt）
- 支持 OpenAI 兼容 API（DeepSeek / 通义千问 / 智谱 / Kimi / Ollama）
- HTTP 请求优先使用 curl，失败时回退到 urllib
- UI 使用 PyQt（QDialog, QTextEdit, QTableWidget 等）

## 目录结构
```
anki-ai-assistant/
  __init__.py              # 插件入口，注册菜单和快捷键
  manifest.json            # Anki 插件元数据
  config.py                # 配置管理，提供商预设
  features/
    explain.py             # AI 解释当前卡片（Ctrl+E）
    generate.py            # AI 从文本生成卡片（JSON 解析 + 添加到牌组）
    chat.py                # AI 对话会话管理（支持流式）
  llm/
    base.py                # LLM 抽象基类
    openai_compat.py       # OpenAI 兼容 API 客户端（curl + urllib）
  ui/
    chat_dialog.py         # AI 对话窗口（流式显示、markdown 渲染、写入背面）
    generate_dialog.py     # AI 生成卡片窗口（预览表格 + 详情区域）
    settings.py            # 设置窗口
    markdown.py            # Markdown 转 HTML
```

## 关键约定
- 插件安装路径：`~/Library/Application Support/Anki2/addons21/anki_ai_assistant/`
- 源项目路径：`~/ClaudeStudy/anki-ai-assistant/`（git 仓库）
- GitHub：`https://github.com/lu17631199052-ctrl/anki-ai-assistant`
- 修改代码后需要同步到 addons21 目录，清除 `__pycache__`，重启 Anki 生效
- 打包命令：`python3 -c "import shutil; shutil.make_archive('/Users/lujinbo/Desktop/anki_ai_assistant', 'zip', '/Users/lujinbo/Library/Application Support/Anki2/addons21/anki_ai_assistant'); import os; os.rename('/Users/lujinbo/Desktop/anki_ai_assistant.zip', '/Users/lujinbo/Desktop/anki_ai_assistant.ankiaddon')"` （注意：zip 根目录直接放文件，不要嵌套文件夹）
- 安装包放桌面，上传到 AnkiWeb 发布更新
- 版本号在 manifest.json 的 human_version 字段
- 用户使用中文，笔记类型通常是"正面/背面"两字段
- 用户有专门的 Markdown 渲染模板，卡片内容需要保留原始 Markdown 格式
- 存储到 Anki 字段时纯文本 \n 需转为 <br>

## 用户偏好
- 中文交流
- 改完代码需要同步到 addons21、更新版本号、重新打包、git commit + push
- 不要随意改版本号，只在实际需要发布时更新
