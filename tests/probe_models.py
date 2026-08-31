# -*- coding: utf-8 -*-
"""模型探测：哪个 opencode go 模型能完成长输出（大纲级）"""
import httpx
import os
import sys
import time

KEY = os.environ.get("QIANBI_TEST_KEY", "")
BASE = "https://opencode.ai/zen/go/v1"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CORE = os.path.join(_ROOT, "tests_output", "长测_改命笔记", "设定", "题材定位.md")
if not os.path.exists(_CORE):
    sys.exit(f"夹具缺失: {_CORE}")
core = open(_CORE, encoding="utf-8").read()
prompt = f"""你是网络小说结构设计师。基于以下核心设定，设计全书卷级大纲与第一卷详细大纲。

## 核心设定
{core}

## 全书规模
- 预计总字数：100 万字
- 每章约：2000 字

只输出大纲内容，不要解释。"""

tests = [
    ("deepseek-v4-flash", 8192),
    ("glm-5.1", 8192),
    ("kimi-k3", 8192),
    ("deepseek-v4-pro", 4096),
    ("qwen3.7-max", 8192),
]
for model, mt in tests:
    t0 = time.monotonic()
    try:
        r = httpx.post(f"{BASE}/chat/completions",
                       headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
                       json={"model": model, "messages": [{"role": "user", "content": prompt}],
                             "max_tokens": mt, "temperature": 0.7},
                       timeout=180)
        d = r.json()
        choices = d.get("choices") or [{}]
        msg = choices[0].get("message", {}) if choices else {}
        c = msg.get("content") or ""
        print(f"{model} mt={mt}: HTTP {r.status_code} ({time.monotonic()-t0:.0f}s) "
              f"content={len(c)} finish={choices[0].get('finish_reason')} "
              f"total_tokens={d.get('usage', {}).get('total_tokens')}", flush=True)
        if r.status_code != 200:
            print("   body:", str(d)[:300], flush=True)
    except Exception as e:
        print(f"{model} mt={mt}: ERR {type(e).__name__} {e}", flush=True)
