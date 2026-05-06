# AI Study Assistant —— 国内可用的 Anki AI 学习助手

一款类似于 AnkiBrain 的 AI 学习插件。支持 DeepSeek、通义千问、智谱清言、Kimi、Ollama 等国内可直接使用的 AI 模型，无需翻墙。

## 功能

### 1. AI 解释卡片
复习时按 `Ctrl+E` 或右键菜单选择「AI 解释当前卡片」，AI 会详细解释卡片涉及的知识点，提供背景信息和记忆技巧。

### 2. AI 生成卡片
粘贴课堂笔记或学习材料，AI 自动提取关键知识点，生成问答卡片。支持预览和编辑后批量添加到指定牌组。

### 3. AI 对话
浮动聊天窗口，可围绕当前学习内容向 AI 提问。支持 Markdown 渲染（表格、列表、代码块等），每条 AI 回复旁边有复制按钮，可一键复制原始 Markdown 格式的表格。还可以直接从聊天内容快速创建卡片。

## 支持的 AI 模型

| 提供商 | 默认模型 | 是否需要 API Key |
|--------|----------|:---:|
| DeepSeek | deepseek-v4-flash | 是 |
| 通义千问 (Qwen) | qwen-plus | 是 |
| 智谱清言 (GLM) | glm-4-flash | 是 |
| Kimi (Moonshot) | moonshot-v1-8k | 是 |
| Ollama (本地) | 自定义 | 否 |
| 自定义接口 | 自定义 | 视情况 |

## 安装与设置

1. 安装插件后重启 Anki
2. 在菜单栏找到 **AI Assistant → 设置...**
3. 选择模型提供商，填入 API Key
4. 点击「测试连接」，确认连接成功
5. 保存后即可使用

### 获取 API Key

- **DeepSeek**: 访问 [platform.deepseek.com](https://platform.deepseek.com) 注册获取
- **通义千问**: 访问阿里云灵积平台注册获取
- **智谱清言**: 访问 [open.bigmodel.cn](https://open.bigmodel.cn) 注册获取
- **Kimi**: 访问 [platform.moonshot.cn](https://platform.moonshot.cn) 注册获取
- **Ollama**: 本地部署，无需 Key，在终端运行 `ollama serve` 即可

## 兼容性

- Anki 版本：23.10 及以上
- 操作系统：macOS / Windows / Linux
- 语言：中文（界面和 AI 回复均为中文）

## 反馈与贡献

如有问题或建议，欢迎在 [GitHub](https://github.com/lu17631199052-ctrl/anki-ai-assistant) 提交 Issue。

## 许可证

MIT License
