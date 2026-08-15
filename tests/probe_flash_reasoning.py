# -*- coding: utf-8 -*-
"""根因实验：OpenCode Go 的 deepseek-v4-flash 长输出失败原因与对策

假设：模型带推理模式，reasoning tokens 计入输出预算，长任务把 max_tokens 吃光 → content 为空/截断。
实验：
  A. max_tokens=16384 是否出内容？reasoning_tokens 多少？
  B. max_tokens=32768 是否完整？
  C. 额外参数尝试关闭推理：reasoning_effort / enable_thinking / thinking
  D. 小任务 baseline（对比推理 token 量）
"""
import httpx
import time

KEY = "sk-IkI4WScZQulFk14oJdTVaj8ttgdwjyon2ni9kNNs8TL25cqf8qNpzgp1VolMCEGk"
BASE = "https://opencode.ai/zen/go/v1"
MODEL = "deepseek-v4-flash"

core = open(r"G:\ai\酒馆\qianbi-novel\tests_output\改命笔记\设定\题材定位.md", encoding="utf-8").read()
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
                       json=payload, timeout=300)
        d = r.json()
        choices = d.get("choices") or [{}]
        msg = choices[0].get("message", {}) if choices else {}
        c = msg.get("content") or ""
        rc = msg.get("reasoning_content") or ""
        u = d.get("usage") or {}
        print(f"[{tag}] HTTP {r.status_code} ({time.monotonic()-t0:.0f}s) "
              f"content={len(c)} reasoning={len(rc)} "
              f"finish={choices[0].get('finish_reason')} "
              f"usage={u}", flush=True)
        if r.status_code != 200:
            print("   body:", str(d)[:300], flush=True)
        return c
    except Exception as e:
        print(f"[{tag}] ERR {type(e).__name__} {e}", flush=True)
        return ""


print("=== A. max_tokens=16384 大纲 ===", flush=True)
call("A", outline_prompt, 16384)

print("=== B. max_tokens=32768 大纲 ===", flush=True)
call("B", outline_prompt, 32768)

print("=== C1. reasoning_effort=low ===", flush=True)
call("C1", outline_prompt, 8192, {"reasoning_effort": "low"})

print("=== C2. enable_thinking=false ===", flush=True)
call("C2", outline_prompt, 8192, {"enable_thinking": False})

print("=== C3. thinking=false ===", flush=True)
call("C3", outline_prompt, 8192, {"thinking": False})

print("=== D. baseline 小任务（max_tokens=8192）===", flush=True)
call("D", "用三句话概括：什么是网络小说的大纲？", 8192)

print("DONE", flush=True)
