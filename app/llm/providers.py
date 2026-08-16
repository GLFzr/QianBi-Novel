# -*- coding: utf-8 -*-
"""服务商预设：仅内置两家官方（DeepSeek 官方 / OpenCode Go 官方），其余第三方由用户自配

重要：应用的内置提示词（正文写作/去味/审校等全部 prompt 工程）只适配各家平台的
DeepSeek API（V4 系的 thinking / reasoning_effort / 参数习惯）。第三方或其他厂商
模型可通过「自定义」接入，但不保证写作质量与闸门稳定。
"""

PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek 官方",
        "builtin": True,
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-v4-pro", "deepseek-v4-flash"],
        "hint": "DeepSeek 官方接口 · 提示词完整适配；Pro 适合正文与设定，Flash 适合细纲/摘要等轻量任务",
    },
    "opencodego": {
        "label": "OpenCode Go 官方",
        "builtin": True,
        "base_url": "https://opencode.ai/zen/go/v1",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "hint": "OpenCode Go 官方网关 · 提示词完整适配 · DeepSeek V4 系支持思考模式（thinking 启用 + reasoning_effort 最高 max），长任务请调大 max_tokens（≥32768）",
    },
    "custom": {
        "label": "自定义（第三方 / OpenAI 兼容）",
        "builtin": False,
        "base_url": "",
        "models": [],
        "hint": "第三方中转 / 本地 Ollama / LM Studio 等任何 OpenAI 兼容接口 · 用户自行配置；内置提示词按 DeepSeek 设计，非 DeepSeek 模型效果可能打折",
    },
}

PROVIDER_ORDER = ["deepseek", "opencodego", "custom"]


def provider_label(key: str) -> str:
    return PROVIDERS.get(key, {}).get("label", key or "自定义")


def provider_default_url(key: str) -> str:
    return PROVIDERS.get(key, {}).get("base_url", "")


def provider_default_models(key: str) -> list:
    return list(PROVIDERS.get(key, {}).get("models", []))
