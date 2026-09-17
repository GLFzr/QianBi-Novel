# -*- coding: utf-8 -*-
"""WP-01 护栏：CI 工作流里的探针名单必须对照实际文件校验。

事故留档：8b3fb80 的名单里出现过不存在的名字（probe_outline_parse /
probe_chapter_lock_probe——实际文件是 probe_co_outline_parse，且
chapter_lock_probe 从未存在过）；CI 整文件又曾被 filter-branch 事故从
main 上删掉。

WP-14 补牙（旧实现两个洞）：
- 只验「名单里的名字都存在」+ `≥25` 兜底——磁盘 46 支、CI 只列 34 支，
  再悄悄摘 9 支也绿 ⇒ 现在双向核对：磁盘上可离线判定的每支 runner 都必须在
  CI 名单 ∪ 显式豁免名单里；
- YAML 折行时 `line.split("run_probe_fleet.py",1)[-1]` 只取首行 ⇒ 静默缩面
  ⇒ 现在**折叠容错**抽取：从 run: 行起吞并后续续行直到缩进回到块级，再
  shlex 切词（不引入 pyyaml 依赖，但折行/多行名单不再漏采）。
"""
import os
import re
import shlex
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WF = os.path.join(ROOT, ".github", "workflows", "tests.yml")

# 显式豁免名单（环境不判/不适用 CI，每一支注明原因）：
# —— helper 库（被其他探针 import，不单独运行）——
# —— 需真 Key（CI 无 Key，进名单即恒红）——
# —— 需 onedir 打包产物（probe_packaged --exe）——
CI_EXEMPT_PROBES = {
    "probe_format_guard": "helper 库（format_or_die 被 30+ 探针 import）",
    "probe_guard": "helper 库（arm_config_guard 被新探针挂载）",
    "probe_official_flash": "需真 Key（LLM 调用）",
    "probe_models": "需真 Key（LLM 调用）",
    "probe_review_gold": "需真 Key（opt-in 金标回放）",
    "probe_flash_reasoning": "需真 Key + 长测夹具（根因实验）",
    "probe_thinking_param": "需真 Key + 长测夹具（根因实验）",
    "probe_max_thinking": "需真 Key + 长测夹具（根因实验）",
    "probe_outline_batch": "需真 Key + 官方 api 项目夹具（批次实验）",
    "probe_packaged": "需 onedir 打包产物（--exe），干净构建后才可跑",
}


def test_workflow_file_exists():
    assert os.path.isfile(WF), (
        ".github/workflows/tests.yml 不在磁盘上——CI 已不存在（filter-branch 事故重演）")


def _fleet_invocation_names(src):
    """折叠容错抽取 fleet 调用的探针名集合。

    从含 run_probe_fleet.py 的行起，吞并后续续行（YAML 折叠标量/多行名单），
    直到出现缩进 ≤ 该行基础缩进的新键或注释块级行；再 shlex 切词取 probe_*。
    """
    lines = src.splitlines()
    for i, ln in enumerate(lines):
        if "run_probe_fleet.py" not in ln:
            continue
        base_indent = len(ln) - len(ln.lstrip())
        buf = [ln]
        for j in range(i + 1, len(lines)):
            nxt = lines[j]
            if not nxt.strip() or nxt.strip().startswith("#"):
                continue
            ind = len(nxt) - len(nxt.lstrip())
            if ind <= base_indent and re.match(r"\s*[-\w]", nxt):
                break  # 回到块级：续行结束
            buf.append(nxt)
        text = " ".join(b.strip() for b in buf)
        after = text.split("run_probe_fleet.py", 1)[-1]
        try:
            tokens = shlex.split(after, posix=True)
        except ValueError:
            tokens = after.split()
        return {t for t in tokens if re.fullmatch(r"probe_\w+", t)}
    return set()


def _disk_runner_probes():
    """磁盘上的全部 probe_*.py（含 helper 库；由 import 关系派生库集合）"""
    names = {f[:-3] for f in os.listdir(os.path.join(ROOT, "tests"))
             if f.startswith("probe_") and f.endswith(".py")}
    imported = set()
    for n in names:
        src = open(os.path.join(ROOT, "tests", n + ".py"), encoding="utf-8").read()
        for m in re.finditer(r"(?:from|import)\s+(probe_\w+)", src):
            imported.add(m.group(1))
    return names, imported


# 豁免的源码标记（机器可验）：真 Key / 金标 opt-in / 需打包产物。
# 白名单条目源码里一个标记都没有 = 给离线探针开后门 ⇒ 红
#（A-4 复验动作：把 probe_word_block 这类离线探针塞进白名单必红）
_EXEMPT_MARKERS = ("QIANBI_TEST_KEY", "DEEPSEEK_API_KEY", "QIANBI_GOLD_PROBE",
                   "--exe", "_MEIPASS")


def _probe_source(name):
    return open(os.path.join(ROOT, "tests", name + ".py"), encoding="utf-8").read()


def test_whitelist_entries_are_genuinely_not_offline():
    """A-4：白名单不许给离线探针开后门。每条豁免（helper 库除外）的源码必须
    含真 Key / 金标 / 打包产物至少一种标记；v3 曾把可离线全绿的
    probe_agent_relay / probe_cw_dialogue 误挂「需真 Key」——这类误分类在
    本断言下会当场红。"""
    _disk, imported = _disk_runner_probes()
    offenders = []
    for n, reason in CI_EXEMPT_PROBES.items():
        if n in imported:
            continue   # helper 库：不单独运行，豁免天经地义
        src = _probe_source(n)
        if not any(m in src for m in _EXEMPT_MARKERS):
            offenders.append(f"{n}（理由={reason}，但源码无任何豁免标记）")
    assert not offenders, "白名单给离线探针开后门：" + "；".join(offenders)


def test_workflow_probe_list_matches_reality():
    src = open(WF, encoding="utf-8").read()
    assert "run_probe_fleet.py" in src or "probe_" in src, "工作流里没有探针名单"
    ci_names = _fleet_invocation_names(src)
    assert ci_names, "fleet 调用行里没有解析到探针名单"

    # 名单 ⊆ 磁盘：CI 点名的每支必须真实存在
    missing = [n for n in sorted(ci_names)
               if not os.path.isfile(os.path.join(ROOT, "tests", n + ".py"))]
    assert not missing, f"工作流点名的探针不存在于 tests/：{missing}"

    # 磁盘 ⊆ 名单 ∪ 豁免：可离线判定的每支 runner 都必须在 CI 名单里
    #（旧实现只查反向——再悄悄摘 9 支也绿）
    disk, imported = _disk_runner_probes()
    absent = sorted(
        n for n in disk - imported - set(CI_EXEMPT_PROBES)
        if n not in ci_names)
    assert not absent, (
        f"磁盘上可离线判定的探针被悄悄摘出 CI 名单：{absent}"
        f"（豁免名单外的 runner 必须在 CI，防止名单静默缩面）")

    # 豁免名单自身不许腐化：豁免的名字必须真实存在于磁盘
    stale = sorted(n for n in CI_EXEMPT_PROBES if n not in disk)
    assert not stale, f"CI 豁免名单里有磁盘上已不存在的名字（名单腐化）：{stale}"
    assert len(ci_names) >= 25, f"离线舰队名单只剩 {len(ci_names)} 支（应 ≥25）——疑似被悄悄缩编"


def test_workflow_probe_list_excludes_key_required_probes():
    """CI 无 API Key：已知需真 Key 的探针不得进名单（否则 CI 恒红或诱人登记豁免）。"""
    src = open(WF, encoding="utf-8").read()
    for banned in ("probe_official_flash",
                   "probe_models", "probe_review_gold", "probe_flash_reasoning",
                   "probe_thinking_param", "probe_max_thinking", "probe_outline_batch"):
        assert banned not in src, f"{banned} 需真 Key/参数，不得进 CI 名单"
