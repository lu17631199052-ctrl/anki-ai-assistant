"""Configuration management with provider presets.

Stores config via Anki's addon manager. Defines preset providers
that the user can select from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import os

from aqt import mw

# Dynamically determine the addon module name (folder name).
# When installed from AnkiWeb, the folder is a numeric ID, not the package name.
ADDON_NAME = os.path.basename(os.path.dirname(os.path.abspath(__file__)))

# Preset provider definitions
PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-v4-flash",
        "models": "deepseek-v4-pro, deepseek-v4-flash",
    },
    "qwen": {
        "name": "通义千问 (Qwen)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "models": "qwen-turbo, qwen-plus, qwen-max",
    },
    "zhipu": {
        "name": "智谱清言 (GLM)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
        "models": "glm-4-flash, glm-4, glm-4-plus",
    },
    "moonshot": {
        "name": "Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
        "models": "moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k",
    },
    "ollama": {
        "name": "Ollama (本地)",
        "base_url": "http://localhost:11434/v1",
        "default_model": "qwen2.5:7b",
        "models": "",
    },
    "custom": {
        "name": "自定义",
        "base_url": "",
        "default_model": "",
        "models": "",
    },
}

DEFAULT_CONFIG: dict[str, Any] = {
    "provider": "deepseek",
    "api_key": "",
    "model": "deepseek-v4-flash",
    "base_url": "https://api.deepseek.com/v1",
    "temperature": 0.7,
    "max_tokens": 4096,
    "default_deck": "",
    "default_note_type": "",
    "md_to_html": False,
}


def get_config() -> dict[str, Any]:
    cfg = mw.addonManager.getConfig(ADDON_NAME)
    if cfg is None:
        cfg = dict(DEFAULT_CONFIG)
        mw.addonManager.writeConfig(ADDON_NAME, cfg)
    # Merge missing keys from default
    changed = False
    for key, val in DEFAULT_CONFIG.items():
        if key not in cfg:
            cfg[key] = val
            changed = True
    # Migrate old DeepSeek model names
    if cfg.get("model") == "deepseek-chat":
        cfg["model"] = "deepseek-v4-flash"
        changed = True
    if cfg.get("model") == "deepseek-reasoner":
        cfg["model"] = "deepseek-v4-pro"
        changed = True
    if changed:
        mw.addonManager.writeConfig(ADDON_NAME, cfg)
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    mw.addonManager.writeConfig(ADDON_NAME, cfg)


def get_provider_preset(provider_id: str) -> dict[str, str]:
    return PROVIDER_PRESETS.get(provider_id, PROVIDER_PRESETS["custom"])


def get_active_base_url() -> str:
    cfg = get_config()
    provider = cfg.get("provider", "deepseek")
    if provider == "custom":
        return cfg.get("base_url", "")
    preset = get_provider_preset(provider)
    return preset.get("base_url", "")


def get_active_api_key() -> str:
    cfg = get_config()
    return cfg.get("api_key", "")


def get_active_model() -> str:
    cfg = get_config()
    provider = cfg.get("provider", "deepseek")
    if provider == "custom":
        return cfg.get("model", "")
    preset = get_provider_preset(provider)
    return cfg.get("model") or preset.get("default_model", "")
