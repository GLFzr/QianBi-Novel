# -*- coding: utf-8 -*-
"""DeepSeek 官方 API 的 flash 行为探测（对比 OpenCode Go 转接）

注意：本项目测试约定 —— 只允许用 deepseek-v4-flash。
"""
import json
import os
import time

import httpx

# 官方 key：优先环境变量，否则读真实应用配置
KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not KEY:
    cfg_path = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for c in cfg.get("connections", []):
            if c.get("base_url", "").find("deepseek.com") >= 0 and c.get("api_key"):
                KEY = c["api_key"]
                break
    except Exception:
        pass
print("KEY 来源:", "环境变量" if os.environ.get("DEEPSEEK_API_KEY") else "应用配置", flush=True)

BASE = "https://api.deepseek.com"
MODEL = "deepseek-v4-flash"

core = open(r"G:\ai\酒馆\qianbi-novel\tests_output\改命笔记\设定\题材定位.md", encoding="utf-8").read()
outline_prompt = f"""你是网络小说结构设计师。基于以下核心设定，设计全书卷级大纲与第一卷详细大纲。

## 核心设定
{core}

## 全书规模
- 预计总字数：100 万字
- 每章约：2000 字

只输出大纲内容，不要解释。"""


def call(tag, prompt, max_tokens=8192, extra=None):
    payload = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
               "max_tokens": max_tokens, "temperature": 0.7}
    if extra:
        payload.update(extra)
    t0 = time.monotonic()
    try:
        r = httpx.post(f"{BASE}/v1/chat/completions",
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
            print("   body:", str(d)[:300], flush=True)
        if c:
            print("   开头:", c[:100].replace("\n", " "), flush=True)
        return c
    except Exception as e:
        print(f"[{tag}] ERR {type(e).__name__} {e}", flush=True)
        return ""


print("=== 1. 官方 flash 小任务 ===", flush=True)
call("t1", "只回复两个字：正常")

print("=== 2. 官方 flash 大纲（默认参数）===", flush=True)
call("t2", outline_prompt)

print("=== 3. 官方 flash 大纲（thinking disabled）===", flush=True)
call("t3", outline_prompt, extra={"thinking": {"type": "disabled"}})

print("DONE", flush=True)
