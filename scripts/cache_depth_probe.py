# -*- coding: utf-8 -*-
"""缓存深度探针：把"章界 32k 二次计价"从 E3 机制猜测变成可读数的实验。

已实测（E1，见 docs/测试共享状态.md §5 18:45 / 19:20 条）：
  · 每章 prose 的请求是上一章末笔请求的**纯追加**（19/19 个章界 +8.3~11.3k）；
  · 但章界那一笔只命中到**上一章 prose 的前缀**（≈⌊in/256⌋×256），中间约 32k
    已在同章内被读过的内容重新按 miss 计价；
  · 同章内各相位却逐级深命中（enrich 命中 ⌊prose⌋、deslop 命中 ⌊enrich⌋…）；
  · 该现象在 tr-dsv4f 与 bailian-flash 上都复现，跨进程（新进程隔 8 分钟）也复现。

本探针用可控的阶梯前缀问三个问题：
  Q1 逐笔追加时，深前缀节点是否**当场**可读？（阶梯正常推进 = 是）
  Q2 静置 N 秒后再打最深请求，命中的是**最深**节点，还是退回某个**较浅**节点？
  Q3 那些较浅节点在同一次静置后是否仍然活着？
若 Q2 = "最深死、较浅活" → 与章界实测同型，问题在服务商的缓存写入/保留策略，
修法只能是**改变请求形状**（让章界那一笔与前缀同构），不是改计量、也不是改我们的代码。

用量：纯 httpx，不经 app/llm/client，**不写任何 usage.jsonl**（连 fake home 都不碰）。
阶梯 3 块 × --block tok，冷发一次 ≈ block 的 miss，其余全走命中价。

用法：
  python scripts/cache_depth_probe.py --conn tr-dsv4f
  python scripts/cache_depth_probe.py --conn bailian-flash --block 20000 --gap 150
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

SYSTEM = "你是长篇网络小说的设定 keeper。以下每一轮都是一段既定史料，请逐字记住，后续都以它们为基准。"
TAIL = "\n\n问：只用一句话回答——上面最早出现的人名是谁？"

# 每块约 block/0.69 汉字（中文 ≈0.69 tok/字，与 T1 实测拟合一致）；内容确定性生成，
# 同一 --block 在任何进程上逐字节相同，否则"节点是否还活着"就无从判断。
def _block(tag: str, chars: int) -> str:
    unit = ("第%s段史料：更漏七刻，司更的钟响过三遍，名册房的灯还亮着。"
            "册上记%s年冬，拾骨人阿蓟左眼的白翳又厚了一道，沈孤灯的灯焰由橙转红，"
            "他把自己最想守护的那个人的名字写在灯罩内侧，墨迹被灯火烤成褐色。"
            "临安九司各掌一夜，司籍翻到的那一页被人撕去半张，只剩半个'七'字。")
    s = (unit % (tag, tag))
    n, out = 0, []
    while n < chars:
        out.append(s)
        n += len(s)
    return "".join(out)[:chars]


def _hit_miss(usage: dict) -> tuple:
    """与 app/llm/client.py 同口径：DS 原生字段优先，缺失时回退 cached_tokens。"""
    tin = int(usage.get("prompt_tokens", 0) or 0)
    hit = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
    miss = int(usage.get("prompt_cache_miss_tokens", 0) or 0)
    if not hit and not miss:
        hit = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        miss = tin - hit
    return tin, hit, miss


class Ladder:
    def __init__(self, base: str, key: str, model: str, timeout: float):
        self.hx = httpx.Client(timeout=timeout)
        self.headers = {"Authorization": "Bearer %s" % key, "Content-Type": "application/json"}
        self.base, self.model = base.rstrip("/"), model

    def ask(self, messages: list) -> tuple:
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "max_tokens": 24, "temperature": 0.3,
                   "thinking": {"type": "disabled"}}
        t0 = time.time()
        r = self.hx.post(self.base + "/chat/completions", headers=self.headers,
                         json=payload)
        r.raise_for_status()
        u = r.json().get("usage") or {}
        return _hit_miss(u), round(time.time() - t0, 1)


def main() -> None:
    ap = argparse.ArgumentParser(description="缓存深度阶梯探针（零台账污染）")
    ap.add_argument("--conn", default="tr-dsv4f", help="凭据库里的连接 id（渠道=缓存域）")
    ap.add_argument("--block", type=int, default=20000, help="每级阶梯的 token 量级")
    ap.add_argument("--gap", type=int, default=150, help="静置秒数（模拟章界+细纲轮的间隔）")
    ap.add_argument("--base-url", default="", help="显式覆盖连接（默认按 --conn 从凭据库解析）")
    ap.add_argument("--api-key", default="", help="显式覆盖 Key")
    ap.add_argument("--model", default="", help="显式覆盖模型名")
    a = ap.parse_args()

    if a.api_key:
        conn = {"key": a.api_key, "base": a.base_url, "model": a.model}
    else:
        from cost_bench import _load_key
        conn, _pro = _load_key(prefer_id=a.conn)
    lad = Ladder(conn["base"], conn["key"], conn["model"], timeout=600.0)
    chars = int(a.block / 0.69)
    print("渠道 %s @ %s ｜阶梯 %d tok/级 ×3｜静置 %ds"
          % (conn["model"], conn["base"], a.block, a.gap))

    msgs, levels, rows = [{"role": "system", "content": SYSTEM}], [], []

    def probe(tag: str, extra_user: str, note: str = ""):
        req = msgs + [{"role": "user", "content": extra_user + TAIL}]
        (tin, hit, miss), lat = lad.ask(req)
        rows.append({"tag": tag, "in": tin, "hit": hit, "miss": miss, "lat": lat,
                     "note": note, "levels": [(t, l) for t, l in levels]})
        print("  %-4s in=%-8s hit=%-8s miss=%-8s %5.1fs  %s"
              % (tag, format(tin, ","), format(hit, ","), format(miss, ","), lat, note))
        return tin, hit

    print("== Q1 阶梯推进（同一次运行内逐级追加，期望每级命中上一级的前缀）==")
    for i, tag in enumerate(["甲", "乙", "丙"]):
        body = _block(tag, chars)
        t0 = time.time()
        tin, hit = probe("L%d" % (i + 1), body, "第 %d 级阶梯%s" % (i + 1, "（冷发）" if i == 0 else ""))
        msgs.append({"role": "user", "content": body + TAIL})
        msgs.append({"role": "assistant", "content": "已记录第%s段史料。" % tag})
        levels.append((("L%d" % (i + 1)), tin))
        print("       ↑ 阶梯落盘 %d tok（%.0fs）" % (tin, time.time() - t0))

    deepest = levels[-1][1]
    print("== 静置 %ds（模拟章界：中间隔一轮细纲生成）==" % a.gap)
    time.sleep(a.gap)

    print("== Q2 静置后再打最深请求（期望 hit≈⌊%.0f⌋；若退回较浅层即与章界实测同型）==" % deepest)
    _t, deep_hit = probe("R1", "追加一小段：次日黄昏，钟未响。", "最深链复打")
    print("== Q3 同一次静置后**逐字重放 L1 原始请求**（测最浅层节点是否仍活着；"
          "必须原样重放，改写会让前缀在消息内部就分叉）==")
    _t2, shallow_hit = probe("R2", msgs[1]["content"][:-len(TAIL)], "L1 原样重放")

    print("== Q4 深前缀 + **大追加**（≈%.0fk tok 新料，复刻章界那一笔的形状）=="
          % (a.block * 1.5 / 1000))
    _t4, big_hit = probe("R4", _block("丁", int(a.block * 1.5 / 0.69)), "最深链 + 大新尾")

    print("== 再静置 %ds，重复 Q2 看衰减 ==" % a.gap)
    time.sleep(a.gap)
    _t3, deep_hit2 = probe("R3", "追加一小段：次日黄昏，钟未响。", "最深链第二次复打")

    def f256(x):
        return (x // 256) * 256

    print("\n## 判读")
    named = [(t, l) for t, l in levels]
    for tag, h in (("R1", deep_hit), ("R2", shallow_hit), ("R4", big_hit), ("R3", deep_hit2)):
        where = next((t for t, l in named if abs(h - f256(l)) <= 256), None)
        if where is None and h >= f256(deepest):
            where = "最深链(L3) ✅"
        print("  %s hit=%-8s → %s" % (tag, format(h, ","),
              "对应 %s 的前缀%s" % (where, "（最深，节点活着）" if where == "L3" else "（**退回浅层**）")
              if where else "无匹配层级（hit=%s，最深阶梯=%s）" % (format(h, ","), format(deepest, ","))))
    print("  判读一：R1 退回浅层而 R2 仍活着 → 静置后服务商只保留了较浅节点，与章界 32k 实测同型（E1）；"
          "R1 命中最深 → 长栈静置本身没问题，要回头查我们章界请求的形状差异。")
    print("  判读二：R4（大新尾）与 R1（小新尾）落在同一层 → 新尾大小不影响命中深度，"
          "「大追加才重新计价」这一支可以排除。")
    out = os.path.join(ROOT, "tests_output", "probe_cache_depth_%s.json"
                       % time.strftime("%Y%m%d_%H%M"))
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"conn": conn["model"], "base": conn["base"], "block": a.block,
                   "gap": a.gap, "rows": rows}, f, ensure_ascii=False, indent=1)
    print("→", out)


if __name__ == "__main__":
    main()
