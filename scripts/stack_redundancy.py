# -*- coding: utf-8 -*-
"""栈内重复行审计（W-2 的量具）：每章往卷栈里写了多少"栈里早就有的字"

为什么需要它：T3 的 53 章曲线量出栈深 +35k tok/章，而三向对账的结论是**每章追加里
60.5% 是栈内已有行**——主战场从来不是思考预算，而是"每章往栈里写了什么"。但要改
就得知道**是谁写的**：正文重写（enrich/deslop/trim/review_fix 各留一份全文）、审校票
整章回声、tracking/摘要与下一章章头互相抄、章头里"其实不变"的节、清算请求重发…
这份脚本把每个卷栈按章切开，逐行做"本行此前是否逐字出现过"的判定，再按归属汇总，
产出可直接排序的账：**每章新增字 / 每章输出字 / 重复率 / 重复来源 TopN**。

只读盘上 jsonl，零网络、零真机调用。

用法：
  python scripts/stack_redundancy.py                      # 扫全部 bench 变体的 会话/*.jsonl
  python scripts/stack_redundancy.py --variant t3b_long60 # 只看某个变体
  python scripts/stack_redundancy.py --top 15             # 重复来源前 15 条
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
BENCH = os.path.join(ROOT, "tests_output", "bench")

_OPEN_RE = re.compile(r"^【第 (\d+) 章开幕：", re.M)
_HAN_RE = re.compile(r"[一-鿿]")

# 归属标签：**按整条消息**判（逐行判不出来源——重复行绝大多数是正文句子）。
# 规则按顺序命中即停；(标签, 角色或 None, 头部正则)
_KINDS = (
    ("⚠重发 system 前缀", "user", r"【项目设定基准|## 核心设定节选|## 全局写作纪律"),
    ("开幕轮(章头+指令)", "user", r"^【第 \d+ 章开幕："),
    ("正文引用轮(重贴全文)", "user", r"^## 本章正文"),
    ("审校请求", "user", r"===A_GOLDEN_OPEN===|## 评审输出格式|6 维最终审核"),
    ("修复请求", "user", r"请按以下意见修改|根因|逐段修改|===PATCH"),
    ("清算请求", "user", r"设定清算|自创设定|violations"),
    ("tracking 请求", "user", r"状态台账|时间线|伏笔台账|更新.*台账"),
    ("摘要请求", "user", r"章.*摘要|全局摘要"),
    ("扩写/压缩请求", "user", r"字数|扩写|压缩到"),
    ("去味请求", "user", r"AI 味|去味|机器腔"),
    ("正文(章稿)", "assistant", r"^#\s*第[0-9一二三四五六七八九十百]+章"),
    ("票/评审输出", "assistant", r"^===|^\s*-\s*\[[A-F]\]|^\*\*判定"),
    ("JSON 输出", "assistant", r"^\s*[\{\[]"),
)
_KIND_RE = [(k, r, re.compile(p, re.S)) for k, r, p in _KINDS]


def han(text: str) -> int:
    return len(_HAN_RE.findall(text or ""))


def kind_of(msg: dict) -> str:
    role = msg.get("role")
    head = (msg.get("content") or "")[:400]
    for k, r, pat in _KIND_RE:
        if role == r and pat.search(head):
            return k
    if role == "user":
        return "user·其它"
    if role == "assistant":
        return "assistant·其它"
    return role or "?"


def analyze(path: str) -> dict:
    """一个卷栈 → 逐章新增/重复字，以及**按消息类别**归属的重复来源。

    seen 跨章累计：卷栈是 append-only 的，"以前出现过的行"就是这次请求里的重复字节。"""
    msgs = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                m = json.loads(ln)
            except ValueError:
                continue
            if isinstance(m, dict) and isinstance(m.get("content"), str):
                msgs.append(m)
    seen = set()
    ch = {}
    kinds = {}
    cur = 0
    sys_lines = set()
    for m in msgs:
        if m.get("role") == "system":
            sys_lines = {ln.strip() for ln in m["content"].split("\n") if ln.strip()}
            break
    for m in msgs:
        if m.get("role") == "system":
            continue
        content = m["content"]
        mm = _OPEN_RE.match(content) or _OPEN_RE.search(content[:200])
        if mm:
            cur = int(mm.group(1))
        if cur == 0:
            continue
        d = ch.setdefault(cur, {"new": 0, "dup": 0, "dupsys": 0, "msgs": 0})
        d["msgs"] += 1
        kind = kind_of(m)
        k = kinds.setdefault(kind, {"new": 0, "dup": 0, "dupsys": 0, "msgs": 0})
        k["msgs"] += 1
        for line in content.split("\n"):
            key = line.strip()
            if not key:
                continue
            h = han(line)
            if key in sys_lines:
                d["dupsys"] += h
                k["dupsys"] += h
            if key in seen:
                d["dup"] += h
                k["dup"] += h
            else:
                seen.add(key)
                d["new"] += h
                k["new"] += h
    return {"ch": ch, "kinds": kinds}


def main() -> None:
    ap = argparse.ArgumentParser(description="卷栈每章新增字 vs 重复字（W-2 量具）")
    ap.add_argument("--variant", default="", help="只看某个 bench 变体")
    ap.add_argument("--path", default="", help="直接指定 jsonl（覆盖 --variant）")
    ap.add_argument("--top", type=int, default=10, help="重复来源 TopN")
    a = ap.parse_args()
    if a.path:
        files = [a.path]
    else:
        pat = os.path.join(BENCH, a.variant or "*", "bench", "*", "会话", "卷*_messages.jsonl")
        files = sorted(glob.glob(pat))
    if not files:
        print("没有可分析的栈文件（%s）" % pat)
        return
    for p in files:
        r = analyze(p)
        chs = sorted(r["ch"])
        tot_new = sum(r["ch"][c]["new"] for c in chs)
        tot_dup = sum(r["ch"][c]["dup"] for c in chs)
        print("\n== %s" % os.path.relpath(p, ROOT))
        print("   章数 %d｜新增 %s han 字｜重复 %s han 字｜**重复率 %.1f%%**｜每章 新增 %s／重复 %s"
              % (len(chs), format(tot_new, ","), format(tot_dup, ","),
                 100.0 * tot_dup / max(1, tot_new + tot_dup),
                 format(tot_new // max(1, len(chs)), ","),
                 format(tot_dup // max(1, len(chs)), ",")))
        tot_sys = sum(r["ch"][c]["dupsys"] for c in chs)
        print("   每章重发 **system 已有**的字：%s han 字（＝整卷每次都发的前缀被再骑一遍，"
              "②-e/②-a 的硬指标）" % format(tot_sys // max(1, len(chs)), ","))
        print("   谁往栈里写了字（按消息类别，前 %d 类；重复率＝该类内部逐行重复占比）：" % a.top)
        print("     %-22s %5s %10s %10s %10s %10s %7s %8s"
              % ("类别", "笔数", "新增字", "重复字", "骑system", "合计字", "重复率", "每章合计"))
        rows = []
        for name, d in r["kinds"].items():
            tot = d["new"] + d["dup"]
            rows.append((tot, name, d))
        for tot, name, d in sorted(rows, key=lambda x: -x[0])[:a.top]:
            print("     %-22s %5d %10s %10s %10s %10s %6.1f%% %8s"
                  % (name, d["msgs"], format(d["new"], ","), format(d["dup"], ","),
                     format(d["dupsys"], ","), format(tot, ","),
                     100.0 * d["dup"] / max(1, tot), format(tot // max(1, len(chs)), ",")))
        print("   逐章（前 8 章）：" + "、".join(
            "第%d章 %d/%d" % (c, r["ch"][c]["new"], r["ch"][c]["dup"])
            for c in chs[:8]))


if __name__ == "__main__":
    main()
