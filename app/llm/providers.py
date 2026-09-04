# -*- coding: utf-8 -*-
"""服务商预设：12 家 OpenAI 兼容平台 + 自定义

这些地址不是抄来的——每条都从本机实打过一次 `<base>/chat/completions`（空 body、不带
Key）：返回 401/400 的 JSON 说明路径正确、只差鉴权；返回 404/HTML 才算 URL 拼错。
各家 hint 里写的就是这次实测结论。**模型名无法在没有 Key 的条件下验证**，填错的症状是
点「测试连接」报 model not found，而不是连不上。

一件必须说清的事：应用的内置提示词（正文/去味/审校全部 prompt 工程）是按 DeepSeek V4 系
调校的（thinking / reasoning_effort / 参数习惯）。其余平台协议上通，但不保证同样的写作
质量与闸门收敛。所以默认槽位仍指向 DeepSeek，且非 DeepSeek 连接的 hint 里写明这点——
不该让用户生成二十章之后才发现文风塌了。

刻意没预置的三处，因为它们没法用「地址 + Key + 模型」三份参数表达，预置进去等于给用户
一堆调不通的连接（需要走自定义）：
  · Azure OpenAI —— 要 deployment_id 而非模型名，v1 API 默认走 AD Token；
  · Cloudflare Workers AI —— URL 里带 {account_id}；
  · 百炼新版业务空间域名 —— URL 里带 {WorkspaceId}（旧域名官方仍支持，故预置旧的）。
"""

PROVIDERS = {
    # ---- 国内 ----
    "deepseek": {
        "label": "DeepSeek 官方",
        "builtin": True,
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-v4-pro", "deepseek-v4-flash"],
        "hint": "内置提示词就是按 DeepSeek V4 系调校的，写作质量以此为基准；Pro 适合正文与"
                "设定，Flash 适合细纲/摘要等轻量任务。加 /v1 后缀等价，与模型版本无关。",
    },
    "bailian": {
        "label": "阿里云百炼",
        "builtin": True,
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen3.8-max", "qwen3.7-plus", "deepseek-v4-pro", "ZHIPU/GLM-5.3"],
        "hint": "实测路径可用（401=只差鉴权）。官方正迁移到 {WorkspaceId}.cn-beijing.maas."
                "aliyuncs.com/compatible-mode/v1；Key 严格按地域绑定，北京 Key 调新加坡端点会"
                " 401。第三方直供模型带前缀（如 ZHIPU/GLM-5.3）。",
    },
    "zhipu": {
        "label": "智谱 BigModel",
        "builtin": True,
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-5", "glm-4-plus", "glm-4-long"],
        "hint": "实测 401=只差鉴权。glm-5 标称 128K 上下文 / 16K 输出，max_tokens 别超 16384。"
                "Coding 套餐走 /api/coding/paas/v4，Anthropic 协议走 /api/anthropic。",
    },
    "kimi": {
        "label": "Kimi（Moonshot）",
        "builtin": True,
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["kimi-k3", "kimi-k2.6", "kimi-k2.5"],
        "hint": "实测 401=只差鉴权。k3 标称 1M 上下文且始终启用思考，支持 reasoning_effort "
                "low/high/max。国际站换 api.moonshot.ai/v1。",
    },
    "ark": {
        "label": "火山引擎方舟",
        "builtin": True,
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": ["doubao-seed-2-1-pro-260628", "doubao-seed-2-0-lite-260215", "DeepSeek-V3.2"],
        "hint": "实测 401=只差鉴权。方舟模型名带日期版本号；部分模型要先在控制台创建推理端点、"
                "填 ep-xxxxxxxx 而不是模型名——报 endpoint not found 就是这个。",
    },
    "hunyuan": {
        "label": "腾讯混元",
        "builtin": True,
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "models": ["hunyuan-turbos-latest", "hunyuan-lite"],
        "hint": "实测两个域名都返回 401=只差鉴权。官方正迁移到 TokenHub"
                "（https://tokenhub.tencentmaas.com/v1），过渡期两边都能用，以控制台说明为准。",
    },
    "minimax": {
        "label": "MiniMax",
        "builtin": True,
        "base_url": "https://api.minimaxi.com/v1",
        "models": ["MiniMax-M3"],
        "hint": "国内域名注意是双 i（minimaxi）；国际站 api.minimax.io/v1，两个域名实测都通。"
                "M3 的响应带 reasoning 字段。",
    },
    "siliconflow": {
        "label": "硅基流动",
        "builtin": True,
        "base_url": "https://api.siliconflow.cn/v1",
        "models": ["deepseek-ai/DeepSeek-V4-Pro", "Qwen/Qwen2.5-VL", "THUDM/GLM-5.2"],
        "hint": "实测 401=只差鉴权。模型名必须是 provider/model 格式。国际站 api.siliconflow.us。",
    },
    # ---- 国外：本机直连实测 OpenRouter 通、Groq 被 CDN 挡（403）、Gemini 与 xAI 超时 ----
    "openrouter": {
        "label": "OpenRouter（聚合）",
        "builtin": True,
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["anthropic/claude-sonnet-4.5", "deepseek/deepseek-v4-pro", "x-ai/grok-4"],
        "hint": "实测 401=只差鉴权，且 /models 直接 200。一家能调 Claude / GPT / Gemini /"
                " DeepSeek，而且国内直连也通——这是它比别家国外平台更该排在前面的原因。模型名"
                "同样是 provider/model；想要和本地提示词同源的写作效果，选 deepseek/ 那条。",
    },
    "gemini": {
        "label": "Google Gemini",
        "builtin": True,
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash"],
        "hint": "base_url 必须以 /openai/ 结尾——少个斜杠或多加 /v1 都会报错。本机直连超时，"
                "国内基本要代理。",
    },
    "xai": {
        "label": "xAI Grok",
        "builtin": True,
        "base_url": "https://api.x.ai/v1",
        "models": ["grok-4.6", "grok-4"],
        "hint": "本机直连超时，国内要代理。模型名以控制台列表为准：grok-4 与 grok-4.6 都在流通，"
                "报 model not found 就换另一个。",
    },
    "groq": {
        "label": "Groq",
        "builtin": True,
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["openai/gpt-oss-20b", "openai/gpt-oss-70b"],
        "hint": "实测返回 403 而不是 401：CDN 会先挡掉不带 Key 的裸探测，不代表路径错。"
                "gpt-oss-20b 写长文偏弱，正文建议换 70b 或直接用 DeepSeek 系。",
    },
    "custom": {
        "label": "自定义（第三方 / OpenAI 兼容）",
        "builtin": False,
        "base_url": "",
        "models": [],
        "hint": "Azure OpenAI / Cloudflare Workers AI / 本地 Ollama、LM Studio 走这里：前两者要"
                "改 URL 模板或换鉴权方式，没法用「地址 + Key + 模型」预置。内置提示词按 DeepSeek"
                " 设计，非 DeepSeek 模型效果可能打折。",
    },
}

PROVIDER_ORDER = ["deepseek", "bailian", "zhipu", "kimi", "ark", "hunyuan", "minimax",
                  "siliconflow", "openrouter", "gemini", "xai", "groq", "custom"]


def provider_label(key: str) -> str:
    return PROVIDERS.get(key, {}).get("label", key or "自定义")


def provider_default_url(key: str) -> str:
    return PROVIDERS.get(key, {}).get("base_url", "")


def provider_default_models(key: str) -> list:
    return list(PROVIDERS.get(key, {}).get("models", []))
