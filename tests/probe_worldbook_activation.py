# -*- coding: utf-8 -*-
"""真书世界书激活自查：工作区内所有 设定/世界书.md 逐本多档预算装配（W1/W2 验收口）

单测用夹具书覆盖语义，这里覆盖**真实产物**的形状（表格/嵌套标题/裸标题残渣/
反哺长描述）。判定：① 快速路径逐字返回；② 输出不超预算；③ 不产生装配层新造的
空壳节（源文件本来就有的尾巴不算，逐字返回时它也在）；④ 反哺登记逐字在场。

运行：python tests/probe_worldbook_activation.py
"""
import glob
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import wb  # noqa: E402

BUDGETS = (300, 600, 1200, 2000)


def _books():
    """工作区里全部真实世界书（同一本书的多个副本只取一份）"""
    seen, out = set(), []
    for path in sorted(glob.glob(os.path.join(ROOT, "..", "*", "**", "设定", "世界书.md"),
                                 recursive=True)):
        book = os.path.dirname(os.path.dirname(path))
        if book in seen:
            continue
        seen.add(book)
        out.append((book, path))
    return out


def _holes(out: str) -> list:
    """装配层新造的空壳标题：标题后面没有本节的任何内容"""
    lines = out.splitlines()
    bad = []
    for i, l in enumerate(lines):
        if not l.startswith("#"):
            continue
        level = len(l) - len(l.lstrip("#"))
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines):
            bad.append(l)                       # 标题就是输出末尾：整节空壳
        elif lines[j].startswith("#") and \
                len(lines[j]) - len(lines[j].lstrip("#")) <= level:
            bad.append(l)                       # 同节没带进内容（更深级=容器，合法）
    return bad


def main() -> bool:
    fails = 0
    checked = 0
    for rel, path in _books():
        doc = io.open(path, encoding="utf-8").read()
        if len(doc) < 50:
            continue
        checked += 1
        src_tail_shell = bool(_holes(doc))       # 源文件自带的空壳尾巴：不记装配层的账
        entries = wb.parse(doc)
        kinds = {}
        for e in entries:
            kinds[e.kind] = kinds.get(e.kind, 0) + 1
        print("=" * 78)
        print("%s\n   doc=%d entries=%d %s" % (rel, len(doc), len(entries), kinds))
        if wb.assemble(rel, num=0, budget=len(doc), doc=doc)["text"] != doc:
            print("   FAIL 快速路径不逐字")
            fails += 1
        # N-15 B 案断言组（更强、且物理可满足）：
        #   ①近窗反哺逐字在场（最新章视角）②反哺保序（无"远的在场近的被裁"）
        #   ③被裁必进 dropped 报告 ④反哺总量可容时全量逐字（原语义的可满足域）
        backflow = [e for e in entries if e.is_backflow and e.kind != "prose" and e.size > 0]
        max_seen = max([e.meta["first_seen"] or 0 for e in backflow] or [0])
        bf_total = sum(e.size for e in backflow)
        for budget in BUDGETS:
            r = wb.assemble(rel, num=1, budget=budget, doc=doc)
            out = r["text"]
            holes = _holes(out)
            if holes and not src_tail_shell:
                print("   FAIL budget=%d 空壳标题=%s" % (budget, holes[:3]))
                fails += 1
            if len(out) > budget + 1:
                print("   FAIL budget=%d 超预算 out=%d" % (budget, len(out)))
                fails += 1
            dropped_names = {d["name"] for d in r["dropped"]}
            # ① 近窗反哺（最新章视角 [max-窗口, max]）逐字在场
            r_new = (wb.assemble(rel, num=max_seen or 1, budget=budget, doc=doc)
                     if backflow else r)
            near_bf = [e for e in backflow
                       if e.meta["first_seen"]
                       and (max_seen - wb.RECENT_WINDOW) <= e.meta["first_seen"] <= max_seen]
            near_total = sum(e.size for e in near_bf)
            if near_bf and budget - wb.TRIM_FLOOR >= near_total:
                for e in near_bf:
                    if e.name not in r_new["text"]:
                        print("   FAIL budget=%d 近窗反哺「%s」被挤掉（B 案近窗保证）"
                              % (budget, e.name))
                        fails += 1
            # ② 保序：反哺按首见距离升序保留，被保留集必须是前缀
            # 只比「唯一名」（名在源文档恰出现一次）——子串误配会造成假倒序
            def unique_name(e):
                return doc.count(e.name) == 1
            present = [e for e in backflow if e.name in out and unique_name(e)]
            absent = [e for e in backflow if e.name not in out and unique_name(e)]
            if present and absent:
                far_present = max((e.meta["first_seen"] or 0) for e in present)
                near_absent = min(((e.meta["first_seen"] or 10 ** 9) for e in absent),
                                  default=10 ** 9)
                if far_present and near_absent < far_present:
                    print("   FAIL budget=%d 反哺裁剪倒序：远登记在场而近登记被裁" % budget)
                    fails += 1
            # ③ 被裁必进 dropped 报告（装配层说得清丢了什么）
            for e in absent:
                if len(out) >= budget * 0.5 and e.name not in dropped_names:
                    print("   FAIL budget=%d 被裁反哺「%s」不在 dropped 报告" % (budget, e.name))
                    fails += 1
            # ④ 反哺总量可容时全量逐字（原断言的可满足域）
            if bf_total and bf_total <= budget - wb.TRIM_FLOOR:
                for e in backflow:
                    if e.name not in out:
                        print("   FAIL budget=%d 反哺总量可容却裁「%s」" % (budget, e.name))
                        fails += 1
            print("   budget=%-5d out=%-5d act=%-3d drop=%-3d 空壳=%d" % (
                budget, len(out), len(r["activated"]), len(r["dropped"]), len(holes)))
    print("=" * 78)
    print("TOTAL %d 本 / %d 项失败" % (checked, fails))
    print("PROBE_DONE " + ("PASS" if not fails else "FAIL"))
    return not fails


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
