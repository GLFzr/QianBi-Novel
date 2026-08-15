# -*- coding: utf-8 -*-
"""服务商预设：酒馆式连接管理，仅 DeepSeek / OpenAI / 自定义 OpenAI 兼容"""

PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-v4-pro", "deepseek-v4-flash"],
        "hint": "DeepSeek 官方接口；Pro 适合正文与设定，Flash 适合细纲/摘要等轻量任务",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini"],
        "hint": "OpenAI 官方接口，需可访问的网络环境",
    },
    "opencodego": {
        "label": "OpenCode Go",
        "base_url": "https://opencode.ai/zen/go/v1",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "hint": "OpenCode Go 网关；DeepSeek V4 系支持思考模式（thinking 启用 + reasoning_effort 最高 max），长任务请调大 max_tokens（≥32768）",
    },
    "custom": {
        "label": "自定义（OpenAI 兼容）",
        "base_url": "",
        "models": [],
        "hint": "任何 OpenAI 兼容接口：中转网关 / 本地 Ollama / LM Studio 等",
    },
}

PROVIDER_ORDER = ["deepseek", "openai", "opencodego", "custom"]


def provider_label(key: str) -> str:
    return PROVIDERS.get(key, {}).get("label", key or "自定义")


def provider_default_url(key: str) -> str:
    return PROVIDERS.get(key, {}).get("base_url", "")


def provider_default_models(key: str) -> list:
    return list(PROVIDERS.get(key, {}).get("models", []))
