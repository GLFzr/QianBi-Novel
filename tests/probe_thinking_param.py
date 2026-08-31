# -*- coding: utf-8 -*-
"""关键实验：thinking 结构体参数能否关闭 flash 的推理（DeepSeek 官方新格式）"""
import httpx
import os
import sys
import time

KEY = os.environ.get("QIANBI_TEST_KEY", "")
BASE = "https://opencode.ai/zen/go/v1"
MODEL = "deepseek-v4-flash"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CORE = os.path.join(_ROOT, "tests_output", "长测_改命笔记", "设定", "题材定位.md")
if not os.path.exists(_CORE):
    sys.exit(f"夹具缺失: {_CORE}")
core = open(_CORE, encoding="utf-8").read()
outline_prompt = f"""你是网络小说结构设计师。基于以下核心设定，设计全书卷级大纲与第一卷详细大纲。

## 核心设定
{core}

## 全书规模
- 预计总字数：100 万字
- 每章约：2000 字

只输出大纲内容，不要解释。"""


def call(tag, payload):
    t0 = time.monotonic()
    try:
        r = httpx.post(f"{BASE}/chat/completions",
                       headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
                       json=payload, timeout=300)
        d = r.json()
        choices = d.get("choices") or [{}]
        msg = choices[0].get("message", {}) if choices else {}
        c = msg.get("content") or ""
        rc = msg.get("reasoning_content") or ""
        u = d.get("usage") or {}
        print(f"[{tag}] HTTP {r.status_code} ({time.monotonic()-t0:.0f}s) "
              f"content={len(c)} reasoning={len(rc)} finish={choices[0].get('finish_reason')} "
              f"usage={u}", flush=True)
        if r.status_code != 200:
            print("   body:", str(d)[:400], flush=True)
        if c:
            print("   开头:", c[:120].replace("\n", " "), flush=True)
    except Exception as e:
        print(f"[{tag}] ERR {type(e).__name__} {e}", flush=True)


base = {"model": MODEL,
        "messages": [{"role": "user", "content": outline_prompt}],
        "max_tokens": 8192, "temperature": 0.7}

print("=== E1. thinking={'type':'disabled'} ===", flush=True)
p = dict(base); p["thinking"] = {"type": "disabled"}
call("E1", p)

print("=== E2. thinking={'type':'enabled'} 对照 ===", flush=True)
p = dict(base); p["thinking"] = {"type": "enabled"}
call("E2", p)

print("=== E3. 3000字章节写作任务 + disabled ===", flush=True)
p = dict(base)
p["messages"] = [{"role": "user", "content":
    "写一个都市悬疑小说的章节正文，约2000字：主角在废弃医院发现神秘笔记本，写下第一个愿望。要求：场景具体、对话自然、节奏紧凑、不用破折号。"}]
p["thinking"] = {"type": "disabled"}
call("E3", p)

print("DONE", flush=True)
