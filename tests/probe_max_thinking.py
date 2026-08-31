# -*- coding: utf-8 -*-
"""关键实验：OpenCode Go + deepseek-v4-flash + thinking enabled + reasoning_effort=max

参考：
- DeepSeek 官方 Thinking Mode 文档：thinking={"type":"enabled"} 顶层参数 + reasoning_effort (low/high/max)
  https://api-docs.deepseek.com/guides/thinking_mode/
- hermes-agent opencode-go provider：effort 映射到顶层 reasoning_effort，DeepSeek 最高档 "max"
  https://github.com/NousResearch/hermes-agent/issues/21577

实验目标：
  A. thinking=enabled + reasoning_effort=max，大纲长任务，max_tokens=16384 → 是否完整输出？
  B. 同上但 max_tokens=32768 → 是否完整？
  C. 3000 字章节写作任务 + max 思考 → 是否完整、有无 reasoning_content
  D. 对照：thinking=disabled（旧行为）看 usage 差异
"""
import httpx
import time
import json
import os
import sys

# Key 从环境变量或 ~/.qianbi_novel/config.json 读取，禁止硬编码进仓库
KEY = os.environ.get("QIANBI_TEST_KEY", "")
if not KEY:
    cfg_path = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg0 = json.load(f)
        for c in cfg0.get("connections", []):
            if c.get("api_key"):
                KEY = c["api_key"]
                break
    except Exception:
        pass
assert KEY, "未找到 API Key（设 QIANBI_TEST_KEY 或配置 ~/.qianbi_novel/config.json）"
BASE = os.environ.get("QIANBI_TEST_BASE", "https://opencode.ai/zen/go/v1")
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


def call(tag, prompt, max_tokens, extra=None):
    payload = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
               "max_tokens": max_tokens, "temperature": 0.7}
    if extra:
        payload.update(extra)
    t0 = time.monotonic()
    try:
        r = httpx.post(f"{BASE}/chat/completions",
                       headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
                       json=payload, timeout=600)
        d = r.json()
        choices = d.get("choices") or [{}]
        msg = choices[0].get("message", {}) if choices else {}
        c = msg.get("content") or ""
        rc = msg.get("reasoning_content") or ""
        u = d.get("usage") or {}
        print(f"[{tag}] HTTP {r.status_code} ({time.monotonic()-t0:.0f}s) "
              f"content={len(c)} reasoning={len(rc)} "
              f"finish={choices[0].get('finish_reason')} "
              f"usage={json.dumps(u, ensure_ascii=False)}", flush=True)
        if r.status_code != 200:
            print("   body:", str(d)[:500], flush=True)
        return c
    except Exception as e:
        print(f"[{tag}] ERR {type(e).__name__} {e}", flush=True)
        return ""


max_think = {"thinking": {"type": "enabled"}, "reasoning_effort": "max"}
off_think = {"thinking": {"type": "disabled"}}

print(f"=== A. 大纲任务 + thinking enabled + effort=max + max_tokens=16384 ===", flush=True)
c = call("A", outline_prompt, 16384, max_think)
print("   长度:", len(c), "结尾:", c[-80:].replace("\n", " ") if c else "(空)", flush=True)

print(f"\n=== B. 大纲任务 + thinking enabled + effort=max + max_tokens=32768 ===", flush=True)
c = call("B", outline_prompt, 32768, max_think)
print("   长度:", len(c), "结尾:", c[-80:].replace("\n", " ") if c else "(空)", flush=True)

print(f"\n=== C. 章节写作 + thinking enabled + effort=max + max_tokens=32768 ===", flush=True)
write_prompt = ("写一个都市悬疑小说的章节正文，约2000字：主角在废弃医院发现神秘笔记本，"
                "写下第一个愿望。要求：场景具体、对话自然、节奏紧凑、不用破折号、"
                "不要出现'他知道/她明白'等认知直述、不要'眼中闪过一丝'等模板化微表情。")
c = call("C", write_prompt, 32768, max_think)
print("   长度:", len(c), "结尾:", c[-80:].replace("\n", " ") if c else "(空)", flush=True)

print(f"\n=== D. 对照：大纲任务 + thinking disabled + max_tokens=16384 ===", flush=True)
c = call("D", outline_prompt, 16384, off_think)
print("   长度:", len(c), flush=True)

print("\nDONE", flush=True)
