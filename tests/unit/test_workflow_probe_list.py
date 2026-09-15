# -*- coding: utf-8 -*-
"""WP-01 护栏：CI 工作流里的探针名单必须对照实际文件校验。

事故留档：8b3fb80 的名单里出现过不存在的名字（probe_outline_parse /
probe_chapter_lock_probe——实际文件是 probe_co_outline_parse，且
chapter_lock_probe 从未存在过）；CI 整文件又曾被 filter-branch 事故从
main 上删掉。本护栏双查：工作流存在 + 名单里每支 probe_*.py 真实存在。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WF = os.path.join(ROOT, ".github", "workflows", "tests.yml")


def test_workflow_file_exists():
    assert os.path.isfile(WF), (
        ".github/workflows/tests.yml 不在磁盘上——CI 已不存在（filter-branch 事故重演）")


def test_workflow_probe_list_matches_reality():
    src = open(WF, encoding="utf-8").read()
    assert "run_probe_fleet.py" in src or "probe_" in src, "工作流里没有探针名单"
    # 只取 fleet 驱动调用行里的名单（排除注释里的举例）
    names = set()
    for line in src.splitlines():
        if "run_probe_fleet.py" in line:
            # 排除驱动器名自身被 findall 命中（run_probe_fleet 里的 probe_fleet）
            names |= set(re.findall(r"\bprobe_\w+", line.split("run_probe_fleet.py", 1)[-1]))
    assert names, "fleet 调用行里没有解析到探针名单"
    missing = [n for n in sorted(names) if not os.path.isfile(os.path.join(ROOT, "tests", n + ".py"))]
    assert not missing, f"工作流点名的探针不存在于 tests/：{missing}"
    assert len(names) >= 25, f"离线舰队名单只剩 {len(names)} 支（应 ≥25）——疑似被悄悄缩编"


def test_workflow_probe_list_excludes_key_required_probes():
    """CI 无 API Key：已知需真 Key 的探针不得进名单（否则 CI 恒红或诱人登记豁免）。"""
    src = open(WF, encoding="utf-8").read()
    for banned in ("probe_agent_relay", "probe_cw_dialogue", "probe_official_flash",
                   "probe_models", "probe_review_gold", "probe_flash_reasoning",
                   "probe_thinking_param", "probe_max_thinking", "probe_outline_batch"):
        assert banned not in src, f"{banned} 需真 Key/参数，不得进 CI 名单"
