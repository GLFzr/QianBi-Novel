# -*- coding: utf-8 -*-
"""新增能力验证：审校解析 / 细纲拆半降级 / 闸门策略 / 配置迁移 / 重试分级

不触网、不需要 Qt；用假 router/ctx 驱动。
运行：.venv/Scripts/python.exe tests/test_quality.py
"""
import os
import sys

sys.path.insert(0, os.getcwd())

from app import config as cfg_mod
from app.core import gates, state as st
from app.core.stages import (parse_outlines, parse_review_findings,
                             _generate_outline_batch)
from app.llm.client import _status_retryable

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  OK  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name} {detail}")


print("1 审校输出解析")
text = ("===BLOCKING===\n- 主角能力与设定冲突\n- 伏笔提前回收\n"
        "===ADVISORY===\n- 时间线略可疑\n无")
blocking, advisory = parse_review_findings(text)
check("blocking 提取", blocking == ["主角能力与设定冲突", "伏笔提前回收"], blocking)
check("advisory 提取", advisory == ["时间线略可疑"], advisory)
b2, a2 = parse_review_findings("===BLOCKING===\n无\n===ADVISORY===\n无")
check("空结果", b2 == [] and a2 == [])

print("2 细纲解析")
out = parse_outlines("===第1章===\n### 第 1 章：雨夜\n- 核心事件：x\n===第2章===\n### 第 2 章：摊牌\n- 核心事件：y")
check("解析两章", [o[0] for o in out] == [1, 2] and out[0][1] == "雨夜", out)


class FakeClient:
    def __init__(self, mode):
        self.mode = mode
        self.calls = 0

    def chat(self, prompt):
        self.calls += 1
        if self.mode == "bad":
            return "模型完全没按格式输出"
        return ("===第1章===\n### 第 1 章：测试\n- 核心事件：x\n"
                "===第2章===\n### 第 2 章：测试2\n- 核心事件：y")

    def chat_stream(self, prompt, on_chunk=None, on_reasoning=None):
        result = self.chat(prompt)
        if on_chunk:
            on_chunk(result)
        return result


class FakeCtx:
    def __init__(self, mode):
        self.router = _FakeRouter(mode)
        self.proj = "."
        self.cfg = {}
        self.last_prompt = ""
        self.logs = []
        self.streamed = []

    def log(self, level, msg):
        self.logs.append((level, msg))

    def checkpoint(self):
        pass

    def stream_chunk(self, text):
        self.streamed.append(text)


class _FakeRouter:
    def __init__(self, mode):
        self._client = FakeClient(mode)

    def client(self, slot):
        return self._client


print("3 细纲批失败 → 拆半逐章降级")
ctx = FakeCtx("bad")
out = _generate_outline_batch(ctx, [1, 2, 3, 4, 5], 3000, "设定", "大纲", "相邻")
check("全失败返回空", out == [], out)
skips = [l for l in ctx.logs if "已跳过" in l[1]]
check("5 章都逐章尝试并跳过", len(skips) == 5, f"跳过日志 {len(skips)} 条")
print("  调用次数 =", ctx.router._client.calls, "（≤ 5 次单章 + 1 整批 + 2 半批 = 8）")

ctx2 = FakeCtx("good")
out2 = _generate_outline_batch(ctx2, [1, 2], 3000, "s", "o", "n")
check("正常批直接成功", [o[0] for o in out2] == [1, 2] and ctx2.router._client.calls == 1)

print("4 闸门策略裁决")


class FakeStrictCtx:
    cfg = {"gates": {"strategy": "strict"}}

    def __init__(self):
        self.paused = False
        self.logs = []

    def auto_pause(self, reason):
        self.paused = True

    def log(self, level, msg):
        self.logs.append(msg)


class FakeMarkCtx(FakeStrictCtx):
    cfg = {"gates": {"strategy": "mark_continue"}}


gr = gates.GateResult()
strict_ctx = FakeStrictCtx()
gates.resolve_failed(strict_ctx, "第 1 章去味未通过", gr)
check("strict → needs_fix", gr.final_status == "needs_fix")
check("strict → 触发 auto_pause", strict_ctx.paused, strict_ctx.logs)
gr2 = gates.GateResult()
mark_ctx = FakeMarkCtx()
gates.resolve_failed(mark_ctx, "第 1 章去味未通过", gr2)
check("mark_continue → needs_fix 不暂停", gr2.final_status == "needs_fix" and not mark_ctx.paused)

print("5 内置连接 max_tokens 迁移")
cfg = {"connections": [
    {"id": "ds-v4-pro", "max_tokens": 8192},
    {"id": "ds-v4-flash", "max_tokens": 8192},
    {"id": "custom-x", "max_tokens": 8192},
]}
cfg_mod._migrate_builtin_connections(cfg)
check("ds-v4-pro → 32768", cfg["connections"][0]["max_tokens"] == 32768)
check("ds-v4-flash → 16384", cfg["connections"][1]["max_tokens"] == 16384)
check("自定义不动", cfg["connections"][2]["max_tokens"] == 8192)

print("6 HTTP 状态码重试分级")
check("429 可重试", _status_retryable(429))
check("500 可重试", _status_retryable(500))
check("502 可重试", _status_retryable(502))
check("401 不可重试", not _status_retryable(401))
check("404 不可重试", not _status_retryable(404))

print("7 旧 state 文件兼容（含已删字段）")
import json
old_state = {"stage": "prose", "current_chapter": 12, "retry_count": 3,
             "invalidated": {"outlines_from": 5, "chapters_from": 8},
             "history": [{"num": 12, "title": "x", "words": 3000, "status": "pass"}]}
proj = os.path.join(os.getcwd(), "smoke_tmp", "冒烟测试书")
os.makedirs(proj, exist_ok=True)
with open(os.path.join(proj, "pipeline_state.json"), "w", encoding="utf-8") as f:
    json.dump(old_state, f, ensure_ascii=False)
loaded = st.load_state(proj)
check("旧字段不崩且保留", loaded["current_chapter"] == 12 and loaded["stage"] == "prose")
check("未知旧键可共存", "invalidated" in loaded)
check("缺失新键有默认", "total_chapters" in loaded)

print()
if FAILED:
    print("FAILED:", FAILED)
    sys.exit(1)
print("ALL_QUALITY_OK")
