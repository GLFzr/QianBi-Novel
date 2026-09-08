# -*- coding: utf-8 -*-
"""E2.2 user_id 缓存隔离探针（成本测试方案_v2 §2 / 官方 API 参考 user 字段）

问题：DeepSeek `user` 字段（连接档案 user_id → 请求体 user）能否把同前缀请求的
KV 缓存按用户隔离——隔离生效 = 分支 B 不命中分支 A 固化的前缀单元。
这是官方文档只写了一句话（"can be used for KVCache isolation for privacy
management"）、社区没有实测数字的机制，本探针补一手数据。

设计（~10 笔小调用，off-peak 成本 <¥0.05，输入用 64+ token 的公共前缀）：
  A1  user_id=A 发长前缀 P + 问题1      → 预期 miss（冷）
  A2  user_id=A 发 P + 问题2（延迟2s）  → 预期高 hit（P 已固化）
  B1  user_id=B 发 P + 问题3            → 隔离生效 ⇒ 低 hit（B 看不到 A 的 P）
                                            隔离无效 ⇒ 高 hit（缓存按前缀全局共享）
  B2  user_id=B 发 P + 问题4            → 预期高 hit（B 自己的 P 已固化）
  N1  不带 user 发 P + 问题5            → 验证无 user 请求与 A/B 的关系（对照组）
每组重复 3 轮取多数（best-effort 缓存有抖动）。

用法：python scripts/user_id_probe.py [--rounds 3]
输出：逐笔 hit/miss 表 + 裁决（ISOLATED / SHARED / INCONCLUSIVE）。
"""
from __future__ import annotations

import os
import sys
import time

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 公共前缀 P：>64 tok（官方 V2.5 公告的最低缓存门槛），稳定逐字节
PREFIX = ("【缓存探针公共前缀】你是一个严谨的中文编辑助手。以下是一段固定的写作规范："
          "第一，所有叙述使用现代白话文，避免文言腔与欧化长句；第二，对话必须使用中文引号，"
          "单句台词不超过四十字；第三，每段不超过五行，段落之间空一行；第四，禁止使用"
          "「眼中闪过一丝」「嘴角勾起一抹」式模板微表情；第五，时间单位统一用时辰、刻、息；"
          "第六，数字表述与上一段保持一致，不得自相矛盾。") * 3


def _conn():
    from app import config as cfg_mod
    from app import secrets
    cfg = secrets.hydrate(cfg_mod.load_config())
    conns = [c for c in cfg.get("connections", []) if c.get("api_key")]
    flash = next((c for c in conns if c.get("id") == "cap-flash"), None)
    if flash is None:
        flash = next((c for c in conns
                      if "api.deepseek.com" in str(c.get("base_url", ""))
                      and "flash" in str(c.get("model", ""))), None)
    if not flash:
        raise SystemExit("没有可用的官方 flash 连接（cap-flash）")
    return flash


def _ask_hitmiss(conn, user_id: str, question: str) -> tuple:
    """直接截获 _record_usage 的入参（ monkeypatch record 捕获本次 hit/miss）"""
    import app.usage as usage_mod
    from app.llm.client import LLMClient
    captured = {}

    orig = usage_mod.record

    def _spy(cfg, model, slot, tin, tout, latency=0.0, hit=0, miss=0, phase="", reasoning=0):
        captured["hit"], captured["miss"] = hit, miss
        return orig(cfg, model, slot, tin, tout, latency,
                    hit=hit, miss=miss, phase=phase, reasoning=reasoning)

    usage_mod.record = _spy
    try:
        kw = {"user_id": user_id} if user_id else {}
        client = LLMClient.from_connection(conn, max_retries=1, slot="probe", **kw)
        client.chat(PREFIX + "\n\n" + question, phase="uid_probe")
    finally:
        usage_mod.record = orig
    return captured.get("hit", 0), captured.get("miss", 0)


def main() -> None:
    rounds = 3
    if "--rounds" in sys.argv:
        rounds = max(1, int(sys.argv[sys.argv.index("--rounds") + 1]))
    conn = _conn()
    print("模型 %s @ %s ｜ %d 轮 × 5 笔" % (conn.get("model"), conn.get("base_url"), rounds))
    rows = []
    for r in range(rounds):
        plan = [
            ("A1", "A", "请用一句话复述规范第二条。"),
            ("A2", "A", "请用一句话复述规范第四条。"),
            ("B1", "B", "请用一句话复述规范第三条。"),
            ("B2", "B", "请用一句话复述规范第五条。"),
            ("N1", "", "请用一句话复述规范第六条。"),
        ]
        for tag, uid, q in plan:
            hit, miss = _ask_hitmiss(conn, uid, q)
            total = hit + miss
            pct = hit / total * 100 if total else 0.0
            rows.append((tag, r + 1, uid or "(无)", hit, miss, pct))
            print("  %-3s 轮%d user=%-5s hit %6d / miss %6d  (%5.1f%%)"
                  % (tag, r + 1, uid or "无", hit, miss, pct), flush=True)
            time.sleep(2.0)

    def _avg(tag):
        xs = [pct for t, _r, _u, _h, _m, pct in rows if t == tag]
        return sum(xs) / len(xs) if xs else 0.0

    a2, b1, b2 = _avg("A2"), _avg("B1"), _avg("B2")
    print("\n== 裁决 ==")
    print("A2（同人二次）平均命中 %.1f%% ｜ B1（异端首次）平均命中 %.1f%% ｜ B2（异端二次）%.1f%%"
          % (a2, b1, b2))
    if a2 >= 80 and b1 <= 30 and b2 >= 80:
        print("结论：ISOLATED——user 字段确实隔离 KV 缓存（B 看不到 A 的前缀）")
    elif a2 >= 80 and b1 >= 80:
        print("结论：SHARED——缓存按前缀全局共享，user 字段不影响命中（隔离无效）")
    else:
        print("结论：INCONCLUSIVE——缓存抖动超出判据（best-effort 注册延迟可能干扰），"
              "加大 --rounds 或在 off-peak 重跑")


if __name__ == "__main__":
    main()
