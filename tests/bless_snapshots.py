# -*- coding: utf-8 -*-
"""快照 golden 人工再生成通道（WP-15 / R11）。

背景：旧实现"golden 缺失 → 自动写入当前产物 → pytest.skip"= R11 违规①——
删掉快照，任何未来输出都会被当成正确答案。现在测试在 golden 缺失时直接
fail；再生成必须走本脚本（人工通道），且生成后必须人工 diff：

    python tests/bless_snapshots.py
    git diff tests/snapshots/      # 人工确认差异只来自预期中的改动
    git add tests/snapshots/

本脚本绝不被任何测试自动调用。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SNAPSHOT_DIR = os.path.join(ROOT, "tests", "snapshots")
UNION_SNAPSHOT = os.path.join(SNAPSHOT_DIR, "lieflat_union_lean.txt")
RULE_FAMILY_SNAPSHOT = os.path.join(SNAPSHOT_DIR, "deslop_rule_families.txt")


def main():
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    from app.prompts import skill_rules, writing
    from tests.unit.test_skill_rules import _derived_rule_families

    skill_rules.init_rules_cache({})   # DEFAULT：lieflat + lean
    union = writing.deslop_static_rules()
    assert union, "并集静态段为空——loader 回退了？先查 fallback_reason"
    with open(UNION_SNAPSHOT, "w", encoding="utf-8", newline="") as f:
        f.write(union)
    print(f"[bless] 写入 {os.path.relpath(UNION_SNAPSHOT, ROOT)}（{len(union)} 字）")

    from app import deslop as d
    families = sorted({r.rule for r in d.scan_text("他站在桥头上。" * 40)})
    derived = _derived_rule_families()
    current = "\n".join(derived + ["", f"CLICHE_PATTERNS={len(d.CLICHE_PATTERNS)}",
                                   f"scan_rule_ids={'|'.join(sorted(set(families)))}"])
    with open(RULE_FAMILY_SNAPSHOT, "w", encoding="utf-8", newline="") as f:
        f.write(current)
    print(f"[bless] 写入 {os.path.relpath(RULE_FAMILY_SNAPSHOT, ROOT)}"
          f"（{len(derived)} 规则族，从代码派生）")
    skill_rules.init_rules_cache({})   # 还原进程默认
    print("[bless] 完成——下一步必须 `git diff tests/snapshots/` 人工确认后再入库")
    return 0


if __name__ == "__main__":
    sys.exit(main())
