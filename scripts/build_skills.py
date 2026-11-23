# -*- coding: utf-8 -*-
"""E7 qianbi-skills 导出管线（0.20.3）：引擎方法论 → Agent Skill 包

单源原则（与 E6 MCP 同一战略，t7 §0 结论 4）：skill 包不是手写副本，而是从仓库
当前成品**自动生成**——上游规则表/码表/schema 变了，重跑本脚本即同步：
- qianbi-deslop      ← app/deslop.py 规则表（45 条，源码抽取）+ 引擎逐字 vendoring
                       （app/deslop.py + app/core/deslop_metrics.py，纯标准库可独立运行）
- qianbi-bridge-codes ← app/prompts/bridge_codes.py 36 码受控码表（逐字 vendoring +
                       生成码表文档与路由查询 CLI）
- qianbi-state-card  ← app/core/state_card.py 七栏 schema（源码抽取：栏题/优先级/
                       预算/容量上限）+ 手写状态卡校验 CLI

产物：dist_skills/（结构对齐 _scratch/superiter/skill_export_mvp：SKILL.md +
scripts + references + tests 金标；顶层 marketplace.json + VERSION）。
版本号读 app/__init__.py 的 __version__（全仓唯一版本源）。

用法：
    python scripts/build_skills.py                 # 生成/刷新 dist_skills/
    python scripts/build_skills.py --out <dir>     # 生成到指定目录
    python scripts/build_skills.py --check         # drift check：重生成到临时目录，
                                                   # 与仓库现版本逐字节比对，有差异
                                                   # exit 1 并打印 diff（不写盘）
    python scripts/build_skills.py --quiet

金标（tests/）：构建期用「随包逐字 vendoring 的引擎」实跑生成期望输出——金标
永远与产物引擎自洽；tests/unit/test_build_skills.py 再用生成的 CLI 复跑金标，
验证导出包可独立运行。

确定性：全部产物逐字节可重现（固定遍历序、sort_keys、LF 换行、UTF-8），
--check 才有意义。零第三方依赖。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SRC_DESLOP = os.path.join(REPO_ROOT, "app", "deslop.py")
SRC_DESLOP_METRICS = os.path.join(REPO_ROOT, "app", "core", "deslop_metrics.py")
SRC_BRIDGE_CODES = os.path.join(REPO_ROOT, "app", "prompts", "bridge_codes.py")
SRC_STATE_CARD = os.path.join(REPO_ROOT, "app", "core", "state_card.py")
SRC_APP_INIT = os.path.join(REPO_ROOT, "app", "__init__.py")

UPSTREAM_URL = "https://github.com/GLFzr/qianbi-novel"

# 引号豁免/标题剥离的扫描前提：样章首行给章题，正文不含成对引号（引号内豁免
# 会让金标依赖引号解析——金标只要确定性，不要花活）
DESLOP_GOLD_SAMPLE = """\
# 第一千三百章 玉简

陈默把玉简按在石台上。这不是他想要的结局，而是他此刻唯一能选的结局。

石门后面没有动静，没有脚步声。

一丝血腥味顺着风飘了进来，贴着地皮往里爬。

他的目光扫过洞口——没有人，只有半枚新鲜的指印。

他不知道的是，玉简里那个声音，同三日前听到的分毫不差。
"""

# 金标必须命中的规则（防「样章被改到不再触发任何规则」的退化）
DESLOP_GOLD_EXPECTED_RULES = ("not-is-comparison", "negation-parade",
                              "trailer-ending", "em-dash", "cliche-word")

SKILL_FRONTEND_NOTE = (
    "本包由 qianbi-novel 导出管线自动生成（scripts/build_skills.py），引擎与"
    "码表为上游逐字副本；请勿手改产物——上游更新后重跑导出管线并用 --check "
    "对账。")


# ---------------- 基础设施 ----------------

def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_json(path: str, data) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, sort_keys=True,
                                indent=1) + "\n")


def read_version() -> str:
    """版本唯一源：app/__init__.py 的 __version__（正则直读，不 import 应用包）。"""
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', read_text(SRC_APP_INIT), re.M)
    if not m:
        raise RuntimeError("app/__init__.py 缺 __version__ 声明")
    return m.group(1)


def skill_frontmatter(name: str, description: str, version: str) -> str:
    return (
        "---\n"
        "name: %s\n"
        "description: %s\n"
        "license: MIT\n"
        "compatibility: 需要 Python 3.8+（仅标准库）；脚本在本 skill 目录 scripts/ "
        "下运行，适用于任何支持 Agent Skills 的客户端。\n"
        "metadata:\n"
        "  author: qianbi\n"
        "  version: %s\n"
        '  source: %s\n'
        "---\n" % (name, description, version, UPSTREAM_URL))


def extract_rule_ids(deslop_src: str) -> list:
    """从 deslop.py 源码抽取全部规则 ID（出现序去重）——规则表唯一抽取口径。"""
    ids = []
    for m in re.finditer(r'(?:add|add_span)\("([a-z0-9-]+)"|rule="([a-z0-9-]+)"',
                         deslop_src):
        rid = m.group(1) or m.group(2)
        if rid not in ids:
            ids.append(rid)
    return ids


def extract_state_card_schema(state_card_src: str) -> dict:
    """从 state_card.py 源码抽取七栏 schema（栏题/优先级/预算/容量）。"""
    titles = [(m.group("title"), int(m.group("prio"))) for m in re.finditer(
        r'^\s+\("(?P<title>[^"]+)", (?P<prio>\d+), ', state_card_src, re.M)]

    def _const(name):
        """取整常量；右侧允许纯算术式（如 `12 * 1024`）——白名单字符后 eval。"""
        m = re.search(r"^%s\s*=\s*([0-9()*+\-/ ]+?)\s*(?:#.*)?$" % name,
                      state_card_src, re.M)
        if not m or not re.fullmatch(r"[0-9()*+\-/ ]+", m.group(1)):
            raise RuntimeError("state_card.py 常量 %s 抽取失败" % name)
        return int(eval(m.group(1), {"__builtins__": {}}))  # noqa: S307 - 白名单算术

    caps = re.search(
        r"^CAP_ROLES,\s*CAP_FORESHADOW,\s*CAP_RECENT\s*=\s*(\d+),\s*(\d+),"
        r"\s*(\d+)", state_card_src, re.M)
    if len(titles) != 7 or not caps:
        raise RuntimeError("state_card.py schema 抽取失败（源码结构变了？）")
    return {
        "titles": titles,
        "byte_budget": _const("BYTE_BUDGET"),
        "cap_roles": int(caps.group(1)),
        "cap_foreshadow": int(caps.group(2)),
        "cap_recent": int(caps.group(3)),
    }


def load_bridge_codes_module():
    """按文件路径独立加载 bridge_codes.py（绕开 app.prompts 包重 __init__）。"""
    spec = importlib.util.spec_from_file_location(
        "qbn_build_bridge_codes", SRC_BRIDGE_CODES)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_vendored_deslop(vendor_pkg_dir: str):
    """按包结构加载 vendoring 后的 deslop 引擎（qianbi_vendor.deslop）。

    金标用**随包产出的引擎字节**实跑生成——金标与产物自洽，不依赖仓库内
    app 包的导入（也不拖动 app.core 重 __init__）。
    """
    import types
    pkg_dir = os.path.join(vendor_pkg_dir, "qianbi_vendor")
    pkg = types.ModuleType("qbn_vendored_qianbi_vendor")
    pkg.__path__ = [pkg_dir]
    sys.modules[pkg.__name__] = pkg

    core_pkg = types.ModuleType(pkg.__name__ + ".core")
    core_pkg.__path__ = [os.path.join(pkg_dir, "core")]
    sys.modules[core_pkg.__name__] = core_pkg

    def _load(mod_name: str, rel: str):
        spec = importlib.util.spec_from_file_location(
            mod_name, os.path.join(pkg_dir, rel))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod

    _load(pkg.__name__ + ".core.deslop_metrics",
          os.path.join("core", "deslop_metrics.py"))
    return _load(pkg.__name__ + ".deslop", "deslop.py")


def run_deslop_scan(engine, text: str) -> dict:
    """确定性扫描报告（--json 与金标共用同一序列化口径）。"""
    findings = [{
        "rule": f.rule, "level": f.level, "message": f.message,
        "text": f.text, "start": f.start, "end": f.end,
        "fix_hint": f.fix_hint,
    } for f in engine.scan_text(text)]
    return {
        "chars": len(text),
        "blocking": sum(1 for f in findings if f["level"] == "blocking"),
        "advisory": sum(1 for f in findings if f["level"] == "advisory"),
        "findings": findings,
    }


# ---------------- 包 1：qianbi-deslop ----------------

DESLOP_CHECK_CLI = '''# -*- coding: utf-8 -*-
"""网文去 AI 味 lint CLI（qianbi-deslop 导出包）——由上游导出管线生成

引擎为 qianbi-novel app/deslop.py + app/core/deslop_metrics.py 的逐字副本
（scripts/_vendor/qianbi_vendor/，MIT License, Copyright (c) 2026 GLFzr）。
上游随真机语料持续校准规则；本包随上游版本同步，请勿手改本文件。

用法：
    python deslop_check.py 章节文件.txt            # 人读报告
    python deslop_check.py 章节文件.txt --json     # 机器可读 JSON（金标同口径）
    python deslop_check.py - < 章节文件.txt        # stdin
    python deslop_check.py --rules                 # 列出本版全部规则 ID

退出码：0 = 无 blocking；1 = 存在 blocking（可作门禁）；2 = 用法/IO 错误。
仅报告，不改写。目标只是读感，不承诺任何 AIGC 检测器分数。
"""
import argparse
import io
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "_vendor"))

from qbn_exported.qianbi_vendor import deslop as engine  # noqa: E402


def _extract_rule_ids(src: str) -> list:
    ids = []
    for m in re.finditer(
            r'(?:add|add_span)\\("([a-z0-9-]+)"|rule="([a-z0-9-]+)"', src):
        rid = m.group(1) or m.group(2)
        if rid not in ids:
            ids.append(rid)
    return ids


def _report_json(text: str) -> str:
    findings = [{
        "rule": f.rule, "level": f.level, "message": f.message,
        "text": f.text, "start": f.start, "end": f.end,
        "fix_hint": f.fix_hint,
    } for f in engine.scan_text(text)]
    payload = {
        "chars": len(text),
        "blocking": sum(1 for x in findings if x["level"] == "blocking"),
        "advisory": sum(1 for x in findings if x["level"] == "advisory"),
        "findings": findings,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1)


def _line_of(text: str, offset: int) -> int:
    return text.count("\\n", 0, offset) + 1


def _report_human(text: str) -> str:
    findings = engine.scan_text(text)
    lines = ["扫描完成：%d 字，blocking %d 处，advisory %d 处"
             % (len(text),
                sum(1 for f in findings if f.level == "blocking"),
                sum(1 for f in findings if f.level == "advisory"))]
    for f in findings:
        lines.append("L%d [%s] %s：%s「%s」修法：%s"
                     % (_line_of(text, f.start), f.level, f.rule, f.message,
                        f.text[:40], f.fix_hint or "见 SKILL.md 改写方向"))
    return "\\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="deslop_check.py")
    ap.add_argument("file", nargs="?", help="章节文本文件；- 表示 stdin")
    ap.add_argument("--json", action="store_true", help="机器可读 JSON")
    ap.add_argument("--rules", action="store_true",
                    help="列出本版全部规则 ID（来自引擎源码）")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass

    if args.rules:
        src_path = os.path.join(_HERE, "_vendor", "qbn_exported",
                                "qianbi_vendor", "deslop.py")
        with io.open(src_path, encoding="utf-8") as f:
            ids = _extract_rule_ids(f.read())
        print("本版规则 %d 条：" % len(ids))
        for rid in ids:
            print("  " + rid)
        return 0

    if not args.file:
        ap.error("需要 章节文件.txt（或 --rules）")
        return 2

    try:
        if args.file == "-":
            text = sys.stdin.read()
        else:
            with io.open(args.file, encoding="utf-8") as f:
                text = f.read()
    except OSError as exc:
        print("读取失败：%s" % exc, file=sys.stderr)
        return 2

    if args.json:
        sys.stdout.write(_report_json(text) + "\\n")
    else:
        print(_report_human(text))
    blocking = sum(1 for f in engine.scan_text(text) if f.level == "blocking")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _deslop_vendor_init(version: str) -> str:
    return ('# -*- coding: utf-8 -*-\n'
            '"""qianbi-novel deslop 引擎 vendoring 包（导出管线生成，勿手改）。\n\n'
            '上游版本 %s。deslop.py 经 qbn_exported.qianbi_vendor 命名空间导入，\n'
            '内部相对导入 .core.deslop_metrics 原样保留。\n"""\n' % version)


def build_deslop_package(out: str, version: str, summary: dict) -> None:
    deslop_src = read_text(SRC_DESLOP)
    metrics_src = read_text(SRC_DESLOP_METRICS)
    rule_ids = extract_rule_ids(deslop_src)
    pkg_root = os.path.join(out, "qianbi-deslop")
    vendor_pkg = os.path.join(pkg_root, "scripts", "_vendor", "qbn_exported")

    # ---- vendoring（逐字副本 + 命名空间壳）----
    write_text(os.path.join(vendor_pkg, "__init__.py"),
               '# -*- coding: utf-8 -*-\n'
               '"""qbn_exported：导出包 vendor 命名空间壳（生成物，勿手改）"""\n')
    write_text(os.path.join(vendor_pkg, "qianbi_vendor", "__init__.py"),
               _deslop_vendor_init(version))
    write_text(os.path.join(vendor_pkg, "qianbi_vendor", "deslop.py"),
               deslop_src)
    write_text(os.path.join(vendor_pkg, "qianbi_vendor", "core", "__init__.py"),
               '# -*- coding: utf-8 -*-\n"""度量层 vendoring 壳（生成物）"""\n')
    write_text(os.path.join(vendor_pkg, "qianbi_vendor", "core",
                            "deslop_metrics.py"), metrics_src)
    write_text(os.path.join(pkg_root, "scripts", "deslop_check.py"),
               DESLOP_CHECK_CLI)

    # ---- 金标：用随包引擎实跑生成 ----
    engine = _load_vendored_deslop(vendor_pkg)
    gold_report = run_deslop_scan(engine, DESLOP_GOLD_SAMPLE)
    fired = {f["rule"] for f in gold_report["findings"]}
    missing = [r for r in DESLOP_GOLD_EXPECTED_RULES if r not in fired]
    if missing:
        raise RuntimeError("deslop 金标样章不再命中规则：%s（样章或引擎变了，"
                           "请核对 DESLOP_GOLD_SAMPLE）" % missing)
    write_text(os.path.join(pkg_root, "tests", "deslop_gold.txt"),
               DESLOP_GOLD_SAMPLE)
    write_json(os.path.join(pkg_root, "tests", "deslop_gold.json"), gold_report)

    # ---- references/rule-basis.md（规则表单源：live 抽取清单 + 方法论）----
    rule_rows = "\n".join("- `%s`" % r for r in rule_ids)
    write_text(os.path.join(pkg_root, "references", "rule-basis.md"),
               u"""# 规则依据与定标（qianbi-deslop，自动生成）

> 本文件由导出管线从上游 `app/deslop.py` 生成；本版引擎含 **%d 条规则**。
> 引擎与阈值为上游逐字副本（scripts/_vendor/），规则注释自带语料基线数字
> 与误报学出处——规则明细以引擎源码为唯一真源，本文件只登记清单与方法论。

## 本版规则清单（%d 条，源码出现序）

%s

## 定标方法（上游口径）

- **真机语料对比**：每条密度型规则都用「人类作者语料 vs 多模型 AI 产出语料」
  的每千字密度对比定标。定标目标：人类文风零误报，AI 堆叠稳定触发。
- **双级设计**：单句式规则（形态即问题）为 blocking；密度型规则低密度是合法
  文风（advisory 或不报），超过 AI 特征密度才升级。校准纪律：有真人命中就不许
  升 blocking。
- **引号豁免**：对话引号内的文本默认豁免密度类规则——人物说话风格不属于叙述腔
  控制范围。
- **白名单**：书级白名单字面量（世界观术语/招式名）等长掩码后不参与任何规则，
  上游 `gates.load_deslop_whitelist` 产出；本 CLI 未带白名单输入，命中白名单
  类误报请人工裁量保留。

## 与上游的关系

- 本包引擎=上游逐字副本，规则行为与上游同版本完全一致；
- 上游 `python -m app.selftest` 与全量单测持续校准规则，本包随版本号同步；
- 上游 GUI 版另有契约化改写回环（改写后自动复扫+指标对比），本包步骤 4 复扫
  需手动执行。
""" % (len(rule_ids), len(rule_ids), rule_rows))

    # ---- SKILL.md ----
    write_text(os.path.join(pkg_root, "SKILL.md"), skill_frontmatter(
        "qianbi-deslop",
        u"中文网文去 AI 味 lint 与白名单式改写。确定性脚本扫描章节里的 AI 写作"
        u"痕迹（毒句式、禁用词、密度型 AI 腔、结构层指纹，本版 %d 条规则），给出"
        u"行号与修法方向，再按白名单纪律改写。当用户提到去AI味、AI味重、AI腔、"
        u"机翻感、降 AI 痕迹、润色网文章节、检查 AI slop、让文字更像人写的时候"
        u"使用。仅适用于中文虚构叙事；不讨论不承诺任何 AIGC 检测器分数，不做"
        u"非虚构文风改写。" % len(rule_ids),
        version) + u"""# 网文去 AI 味：确定性 lint + 白名单改写

目标**只是读感**：把「一眼 AI」的文本改成可读、可信的中文叙事。本 skill 不承诺、
不讨论、不尝试优化任何第三方 AIGC 检测器的分数；不注水、不故意制造错字。

本版引擎 **%d 条规则**（与上游 qianbi-novel %s 逐字一致），随包自检金标见
`tests/`。

## 流程（五步，按序执行，不得跳步）

1. **扫描**：对目标章节运行
   `python <skill目录>/scripts/deslop_check.py 章节文件.txt`
   得到 lint 报告（规则 ID / 级别 / 行号 / 修法方向）。`--json` 可得机器可读
   结果；退出码 1 表示存在 blocking。`--rules` 列出本版全部规则。
2. **定档**：按报告定本轮 AI 味等级——只有 advisory → 轻度；有 1-3 类
   blocking → 中度；blocking 覆盖 4 类以上或多段结构指纹（one-line-para /
   stamp-para）→ 重度。
3. **改写**（白名单纪律，逐条硬约束）：
   - 只处理报告列出的规则命中；清单外、且不在检出问题里的文字**逐字保留**；
   - 只改「怎么说」，不改「说什么」：不得增删情节、人物、信息与因果关系；
   - 删除比例上限：轻度 ≤15%%，中度 ≤25%%，重度 ≤35%%（按字数计，含同义改写
     压缩量）；
   - blocking 必修；advisory 逐条裁量，拿不准就保留原文；
   - 同一处命中只改一次，不得为消规则而把句子改出新的模板腔。
4. **复扫**：改完复跑步骤 1，blocking 必须为 0；advisory 数量不得高于改前。
5. **反指纹终查**：检查替换写法是否在全文复用（同一替换写法反复出现，本身会
   成为新指纹）。有复用就换写法，再复扫一次。

## 改写方向速查（高频命中的通用修法）

| 规则 | 修法方向 |
|---|---|
| not-is-comparison / reverse-not-is | 删掉翻转结构，直接写 B；或拆成动作与后果 |
| negation-parade | 否定排比至多留一项，其余改成白描或动作 |
| voice-contrast / flat-voice | 删音量/声线声明，直接写台词内容与可听见的声音特征 |
| trailer-ending / trailer-summary / fate-summary | 用具体物件、动作或未解决的问题收束；抽象总结落回角色当下 |
| cliche-word（一丝/一抹/眼中闪过…） | 换成该角色特有的动作、物件或环境反应 |
| em-dash（密度型） | 高于 6/千字时改句号、逗号断句；低密度属合法文风，不动 |
| gaze-density（盯着/看向/目光成片） | 注意力外化成动作与物件（指节抵着桌沿、茶凉了没喝） |
| brake-sentence / brake-standalone-para | 「没有×」全章至多保留 2 处，其余改成动作或对白呈现 |
| one-line-para / stamp-para | 关联动作并成复合段；单词定性段还原成可拍摄的细节，全章至多 1 处 |
| 其余密度/结构型规则 | 见 `references/rule-basis.md` 与引擎源码注释（自带语料基线与修法） |

## 边界与纪律

- 本脚本只报告，不改写；一切修改由你在步骤 3 亲手做出。
- 引号内的对话默认豁免密度类规则；对话本身有问题时按语义改，不套模板。
- 宁缺勿滥：无法确证的疑点保持 advisory，不得升级为「必须改」。
- 改写产出的段落要朗读顺口；lint 是底线，不是目标。

## 环境与故障

- 脚本纯 Python 标准库，3.8+ 可跑；Windows 控制台乱码时先 `chcp 65001` 或重定向
  到文件查看。
- 引擎为上游逐字副本：`scripts/_vendor/` 下 `qianbi_vendor/deslop.py`；
  规则与阈值明细以引擎源码注释为唯一真源。
- 上游：%s（GUI 版含全量规则、契约化改写回环与改写前后指标对比）。

%s
""" % (len(rule_ids), version, UPSTREAM_URL, SKILL_FRONTEND_NOTE))
    summary["qianbi-deslop"] = {
        "rules": len(rule_ids), "gold_findings": len(gold_report["findings"])}


# ---------------- 包 2：qianbi-bridge-codes ----------------

BRIDGE_ROUTE_CLI = '''# -*- coding: utf-8 -*-
"""桥段码路由/查询 CLI（qianbi-bridge-codes 导出包）——由上游导出管线生成

码表为 qianbi-novel app/prompts/bridge_codes.py 的逐字副本（scripts/_vendor/，
MIT License）。查询路由判据/典型位置/路由词；反例码（advisory_only）只作审校
证据，不进正文/细纲路由。

用法：
    python bridge_route.py --list               # 全码清单（人读）
    python bridge_route.py --list --json        # 机器可读（金标同口径）
    python bridge_route.py --group 爽点          # 按组过滤
    python bridge_route.py --code DL            # 单码详情
    python bridge_route.py --route 打脸 当众     # 按路由词查码（细纲解析兜底）

退出码：0 = 正常；2 = 用法错误。
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "_vendor"))

from qbn_exported.qianbi_vendor import bridge_codes as bc  # noqa: E402


def _group_index(code_rec):
    try:
        return bc.GROUP_ORDER.index(code_rec["group"])
    except ValueError:
        return len(bc.GROUP_ORDER)


def _all_codes():
    out = []
    for code in sorted(bc.BRIDGE_CODES):
        rec = bc.BRIDGE_CODES[code]
        out.append({
            "code": code, "name": rec["name"], "group": rec["group"],
            "rule": rec["rule"], "position": rec.get("position", ""),
            "spans": list(rec.get("spans", ())),
            "route_kw": list(rec.get("route_kw", ())),
            "card": rec.get("card", ""),
            "advisory_only": bool(rec.get("advisory_only")),
        })
    out.sort(key=lambda r: (_group_index(bc.BRIDGE_CODES[r["code"]]),
                            r["code"]))
    return out


def _print_detail(code, rec):
    print("%s %s（%s组%s）" % (
        code, rec["name"], rec["group"],
        "，反例证据码" if rec.get("advisory_only") else ""))
    print("  判据：%s" % rec["rule"])
    print("  典型位置：%s" % rec.get("position", "-"))
    spans = rec.get("spans", ("-"))
    print("  典型跨度：%d-%d 章" % (spans[0], spans[1]))
    print("  路由卡：%s" % (rec.get("card") or "（不路由）"))
    kws = rec.get("route_kw") or ()
    if kws:
        print("  路由词：%s" % "、".join(kws))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bridge_route.py")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--group")
    ap.add_argument("--code")
    ap.add_argument("--route", nargs="*", default=[])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass

    if args.code:
        rec = bc.BRIDGE_CODES.get(args.code)
        if rec is None:
            print("未知码：%s" % args.code, file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps({"code": args.code, **{
                k: (list(v) if isinstance(v, tuple) else v)
                for k, v in rec.items()}}, ensure_ascii=False, sort_keys=True,
                indent=1))
        else:
            _print_detail(args.code, rec)
        return 0

    if args.route:
        wanted = [w for w in args.route if w]
        if not wanted:
            ap.error("--route 需要至少一个路由词")
            return 2
        hits = [c for c in _all_codes()
                if any(w in (bc.BRIDGE_CODES[c["code"]].get("route_kw") or ())
                       for w in wanted)]
        if args.json:
            print(json.dumps({"route_kw": wanted, "codes": hits},
                             ensure_ascii=False, sort_keys=True, indent=1))
        else:
            for c in hits:
                _print_detail(c["code"], bc.BRIDGE_CODES[c["code"]])
        return 0

    codes = _all_codes()
    if args.group:
        codes = [c for c in codes if c["group"] == args.group]
        if args.json:
            print(json.dumps({"group": args.group, "codes": codes},
                             ensure_ascii=False, sort_keys=True, indent=1))
            return 0
    if args.json:
        print(json.dumps({"codes": codes}, ensure_ascii=False,
                         sort_keys=True, indent=1))
        return 0

    print("桥段码表 %d 码（%s）" % (
        len(codes), "、".join("%s %d" % (g, bc.GROUP_EXPECTED.get(g, -1))
                              for g in bc.GROUP_ORDER)))
    cur = None
    for c in codes:
        if c["group"] != cur:
            cur = c["group"]
            print("\\n[%s]" % cur)
        print("  %-4s %s：%s" % (c["code"], c["name"], c["rule"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def build_bridge_package(out: str, version: str, summary: dict) -> None:
    bridge_src = read_text(SRC_BRIDGE_CODES)
    bc = load_bridge_codes_module()
    codes = bc.BRIDGE_CODES
    total = len(codes)
    group_counts = {g: sum(1 for r in codes.values() if r["group"] == g)
                    for g in bc.GROUP_ORDER}
    pkg_root = os.path.join(out, "qianbi-bridge-codes")
    vendor_pkg = os.path.join(pkg_root, "scripts", "_vendor", "qbn_exported",
                              "qianbi_vendor")

    write_text(os.path.join(
        os.path.dirname(vendor_pkg), "__init__.py"),
        '# -*- coding: utf-8 -*-\n'
        '"""qbn_exported：导出包 vendor 命名空间壳（生成物，勿手改）"""\n')
    write_text(os.path.join(vendor_pkg, "__init__.py"),
               '# -*- coding: utf-8 -*-\n'
               '"""qianbi-novel bridge_codes 码表 vendoring（生成物，勿手改）。'
               '上游版本 %s"""\n' % version)
    write_text(os.path.join(vendor_pkg, "bridge_codes.py"), bridge_src)
    write_text(os.path.join(pkg_root, "scripts", "bridge_route.py"),
               BRIDGE_ROUTE_CLI)

    # ---- 金标：--list --json 期望输出（构建期按同一排序口径生成）----
    def _group_index(rec):
        try:
            return bc.GROUP_ORDER.index(rec["group"])
        except ValueError:
            return len(bc.GROUP_ORDER)

    gold = {"codes": [{
        "code": code, "name": rec["name"], "group": rec["group"],
        "rule": rec["rule"], "position": rec.get("position", ""),
        "spans": list(rec.get("spans", ())),
        "route_kw": list(rec.get("route_kw", ())),
        "card": rec.get("card", ""),
        "advisory_only": bool(rec.get("advisory_only")),
    } for code, rec in sorted(codes.items())]}
    gold["codes"].sort(key=lambda r: (_group_index(codes[r["code"]]),
                                      r["code"]))
    write_json(os.path.join(pkg_root, "tests", "bridge_gold.json"), gold)

    # ---- references/code-table.md ----
    rows = []
    for c in gold["codes"]:
        rec = codes[c["code"]]
        rows.append("| %s | %s | %s | %s | %s | %d-%d | %s | %s |" % (
            c["code"], c["name"], c["group"], c["rule"],
            c["position"] or "-",
            rec.get("spans", (0, 0))[0], rec.get("spans", (0, 0))[1],
            rec.get("card") or "-", "、".join(rec.get("route_kw", ())) or "-"))
    group_line = "、".join("%s %d 码" % (g, group_counts[g])
                           for g in bc.GROUP_ORDER)
    write_text(os.path.join(pkg_root, "references", "code-table.md"), u"""\
# 桥段码表（qianbi-bridge-codes，自动生成）

> 本文件由导出管线从上游 `app/prompts/bridge_codes.py` 生成。码表为自写受控
> 词表——码名取通用网文类型学术语，判据/典型位置/路由词全部自写，不含任何
> 原文摘录、真实书名或语料画像内容（版权绿档）。本版 **%d 码**：%s。
> 判据明细以引擎源码为唯一真源；路由/查询用 `scripts/bridge_route.py`。

## 使用纪律（上游口径）

- 码是**写法契约**不是标签：登记「本章用哪码」时须能对照判据指出对应段落，
  对不上=未兑现（爽点账本 beats_declared/delivered 对账口径）。
- 整码 token 匹配：SJ（收获兑现，爽点组）与 SJ2（闭关跳时，过渡组）前缀撞车，
  解析一律按整码 token，不按前缀截断。
- 反例 5 码（WATER/OOC/BAL/LOGIC/REP）是审校证据码：advisory_only，只进审校
  与账本对照，**不进正文/细纲路由**。

## 全表

| 码 | 名称 | 组 | 判据（一句话） | 典型位置 | 跨度(章) | 路由卡 | 路由词 |
|---|---|---|---|---|---|---|---|
%s
""" % (total, group_line, "\n".join(rows)))

    # ---- SKILL.md ----
    write_text(os.path.join(pkg_root, "SKILL.md"), skill_frontmatter(
        "qianbi-bridge-codes",
        u"中文网文桥段类型学受控码表路由（%d 码 7 组：爽点/冲突/悬念/情感/过渡/"
        u"钩子/反例）。为章节细纲选码、按路由词反查码、对账「声明了什么码实际写"
        u"了什么」。当用户提到桥段设计、爽点套路、打脸/扮猪吃虎/绝境翻盘、细纲"
        u"选码、桥段对账、套路落点的时候使用。反例码只作审校证据不进路由。" % total,
        version) + u"""# 桥段码表：受控词表 + 路由判据

码是**写法契约**不是标签：每码带一句话判据（可指认、可对账）、典型位置（章内
锚点）、典型跨度（章）、路由词与路由场景卡。本版 **%d 码 7 组**（%s），
与上游 qianbi-novel %s 码表逐字一致。

## 流程（三步）

1. **选码**：按本章要写的桥段，在 `references/code-table.md` 或
   `python <skill目录>/scripts/bridge_route.py --list` 里选码；一组选码总数
   要克制（一章通常 1-3 码），每码登记时写明「打算落在哪里」。
2. **写作对齐**：写作时对照码的判据与典型位置——判据对不上段落=未兑现，
   宁可去掉声明也不硬凑。
3. **对账**：成稿后逐码自查「声明的码实际兑现了没有」（上游爽点账本
   beats_declared/beats_delivered 同口径）；可用
   `python bridge_route.py --route <词>…` 反查与本章内容相关的候选码做交叉
   核对。

## 命令速查

```
python scripts/bridge_route.py --list                # 全码清单（按组）
python scripts/bridge_route.py --group 爽点          # 按组过滤
python scripts/bridge_route.py --code DL             # 单码详情
python scripts/bridge_route.py --route 打脸 当众     # 按路由词反查
# 以上均可加 --json
```

## 纪律与边界

- **SJ/SJ2 整码匹配**：SJ（收获兑现）与 SJ2（闭关跳时）前缀撞车，登记与解析
  一律整码 token，不按前缀截断。
- **反例码不路由**：WATER（强行解释）/OOC/BAL（平衡说教）/LOGIC/REP 五码是
  审校证据码（advisory），只在「本章避开了哪些坑」的对账里出现。
- 码表是类型学不是模板清单：同码反复用要换具体事件与物件，判据命中但读感
  重复=失败（上游 deslop 的 formulaic-parallelism 会抓）。
- 完整判据/路由词以 `scripts/_vendor/` 码表源码为唯一真源；金标见 `tests/`。

%s
""" % (total, group_line, version, SKILL_FRONTEND_NOTE))
    summary["qianbi-bridge-codes"] = {"codes": total,
                                      "groups": len(bc.GROUP_ORDER)}


# ---------------- 包 3：qianbi-state-card ----------------

STATE_CARD_VALIDATE_CLI = '''# -*- coding: utf-8 -*-
"""续写状态卡校验 CLI（qianbi-state-card 导出包）——由上游导出管线生成

schema 由 qianbi-novel app/core/state_card.py 源码抽取生成（七栏栏题/优先级/
字节预算）。用于：外部 agent 手写/改造状态卡后的结构自检（引擎同款渲染契约）。

用法：
    python state_card_validate.py 状态卡.md            # 人读报告
    python state_card_validate.py 状态卡.md --json     # 机器可读（金标同口径）
    python state_card_validate.py 状态卡.md --budget 12288

退出码：0 = 合格；1 = 有违例；2 = 用法/IO 错误。
"""
import argparse
import io
import json
import re
import sys

# 由导出管线注入：七栏栏题（按渲染顺序）与默认字节预算（state_card.BYTE_BUDGET）
CANONICAL_TITLES = __SCHEMA_TITLES__
DEFAULT_BUDGET = __SCHEMA_BUDGET__

TITLE_RE = re.compile(r"^# 续写状态卡（第(\\d+)章）\\s*$")
HEADER_RE = re.compile(r"^##\\s*(.+?)\\s*$")


def validate(text: str, budget: int) -> dict:
    problems = []
    lines = text.splitlines()
    if not lines or not TITLE_RE.match(lines[0].strip()):
        problems.append({
            "check": "title",
            "message": "首行须为「# 续写状态卡（第N章）」，实际：%r"
                       % (lines[0][:40] if lines else "<空文件>"),
        })
    headers = [(i, m.group(1)) for i, m in
               ((i, HEADER_RE.match(ln.strip())) for i, ln in enumerate(lines))
               if m]
    seen = []
    for lineno, title in headers:
        if title not in CANONICAL_TITLES:
            problems.append({
                "check": "column",
                "line": lineno + 1,
                "message": "未知栏「%s」（七栏之一：%s）"
                           % (title, "、".join(CANONICAL_TITLES)),
            })
        elif title in seen:
            problems.append({
                "check": "column", "line": lineno + 1,
                "message": "栏「%s」重复出现" % title,
            })
        else:
            if seen and CANONICAL_TITLES.index(title) < max(
                    CANONICAL_TITLES.index(s) for s in seen):
                problems.append({
                    "check": "column-order", "line": lineno + 1,
                    "message": "栏「%s」不在规范顺序（%s）"
                               % (title, " → ".join(CANONICAL_TITLES)),
                })
            seen.append(title)
    # 栏内条目必须是「- 」整项（渲染契约：整项取舍不截半句）
    cur_col = None
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        m = HEADER_RE.match(stripped)
        if m:
            cur_col = m.group(1)
            continue
        if not stripped or stripped.startswith("#"):
            continue
        if cur_col and not stripped.startswith("- "):
            problems.append({
                "check": "item-format", "line": i + 1,
                "message": "栏「%s」条目须以「- 」起头：%r" % (cur_col,
                                                             stripped[:30]),
            })
    size = len(text.encode("utf-8"))
    if size > budget:
        problems.append({
            "check": "budget",
            "message": "状态卡 %d 字节超出预算 %d（超 %d 字节；上游按 P5→P1 "
                       "优先级整项裁剪）" % (size, budget, size - budget),
        })
    return {
        "bytes": size, "budget": budget,
        "columns_present": [t for t in CANONICAL_TITLES if t in seen],
        "problems": problems, "ok": not problems,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="state_card_validate.py")
    ap.add_argument("file")
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    try:
        with io.open(args.file, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        print("读取失败：%s" % exc, file=sys.stderr)
        return 2

    report = validate(text, args.budget)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1))
    elif report["ok"]:
        print("状态卡合格：%d 字节（预算 %d），栏目 %s"
              % (report["bytes"], report["budget"],
                 "、".join(report["columns_present"]) or "（无内容栏）"))
    else:
        for p in report["problems"]:
            print("违例 [%s]%s：%s" % (p["check"],
                                      (" L%d" % p["line"]) if p.get("line")
                                      else "", p["message"]))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
'''

STATE_CARD_GOLD = u"""\
# 续写状态卡（第7章）

## 当前位置

- 主角在青云宗外门杂役院，刚领到每月三枚灵石的份例。

## 下一章承诺

- 细纲：主角发现灵石里藏着一缕陌生神识，追查来历。

## 活跃伏笔(作者真相)

- 青云剑裂纹（第2章埋）：实为上古封印松动，计划第12章揭示。

## 连贯性风险

- 第6章配角「赵管事」口头承诺未兑现，逾期 2 章。

## 核心角色状态

- 陈默（主角）：炼气三层，知道剑有裂纹，不知剑灵存在。

## 长期约束(正则must)

- 主角不得在筑基前暴露剑灵；宗门大比每三年一次，下次在第 30 章前后。

## 近三章速记(读者已知)

- 第5章：主角用裂纹剑退掉黑风寨探子。
- 第6章：赵管事许诺调主角进藏书阁。
- 第4章：设定——外门弟子每月三枚灵石（读者已知常驻）。
"""


def build_state_card_package(out: str, version: str, summary: dict) -> None:
    schema_src = read_text(SRC_STATE_CARD)
    schema = extract_state_card_schema(schema_src)
    titles = [t for t, _p in schema["titles"]]
    pkg_root = os.path.join(out, "qianbi-state-card")

    cli = (STATE_CARD_VALIDATE_CLI
           .replace("__SCHEMA_TITLES__", repr(titles))
           .replace("__SCHEMA_BUDGET__", str(schema["byte_budget"])))
    write_text(os.path.join(pkg_root, "scripts", "state_card_validate.py"),
               cli)

    # ---- 金标：合格卡 + 超预算违例卡 ----
    write_text(os.path.join(pkg_root, "tests", "state_card_gold.md"),
               STATE_CARD_GOLD)
    write_text(os.path.join(pkg_root, "tests", "state_card_bad.md"),
               STATE_CARD_GOLD.replace("## 长期约束(正则must)\n",
                                       "## 不认识的栏\n") + "多余条目\n"
               + "x" * (schema["byte_budget"]) + "\n")

    # ---- references/state-card-schema.md ----
    rows = "\n".join("| %s | P%d |" % (t, p) for t, p in schema["titles"])
    write_text(os.path.join(pkg_root, "references", "state-card-schema.md"),
               u"""\
# 续写状态卡 schema（qianbi-state-card，自动生成）

> 本文件由导出管线从上游 `app/core/state_card.py` 源码抽取生成（栏题/优先级/
> 预算/容量为源码常量，非手抄）。上游按本契约渲染每章续写状态卡，注入下一章
> prompt 代替对话记忆；外部 agent 手写或改造状态卡后，用
> `scripts/state_card_validate.py` 自检。

## 七栏定义（按渲染顺序；P 数字大者先裁剪，P0 永不裁）

| 栏题 | 裁剪优先级 |
|---|---|
%s

## 硬契约

- **字节预算**：整卡 ≤ **%d 字节**（UTF-8；`BYTE_BUDGET`）。超限按 P5→P1
  优先级**整项丢弃**（从各栏尾部=最旧/最低价值起），不截半句。
- **标题行**：`# 续写状态卡（第N章）`。
- **栏格式**：`## 栏题` 起头，条目每行一个 `- ` 整项；空栏整栏省略
  （渲染器跳过无内容栏——校验器因此只查「出现的栏」，不要求七栏全在场）。
- **容量上限**（源码常量）：核心角色 ≤%d 条、活跃伏笔 ≤%d 条、近三章速记
  ≤%d 条。

## 各栏语义（写作约束口径）

- **当前位置**：主角此刻在哪、刚发生什么——下一章的地板。
- **下一章承诺**：细纲/大纲对下一章的许诺，未兑现=下一章欠账。
- **活跃伏笔(作者真相)**：作者视角真相（读者不可知部分不得泄进正文表述）。
- **连贯性风险**：到期未回收伏笔、空头承诺、零登场角色等，写前须处置。
- **核心角色状态**：出场角色的可见状态（境界/伤势/持物/知情范围）。
- **长期约束(正则must)**：跨卷硬约束，违反=断 contract。
- **近三章速记(读者已知)**：读者已知事件（区别于作者真相）——表述不得越过
  读者认知边界。
""" % (rows, schema["byte_budget"], schema["cap_roles"],
       schema["cap_foreshadow"], schema["cap_recent"]))

    # ---- SKILL.md ----
    write_text(os.path.join(pkg_root, "SKILL.md"), skill_frontmatter(
        "qianbi-state-card",
        u"中文网文续写状态卡（七栏 ≤12KB 续写上下文契约）的解读与手写校验。"
        u"把「下一章 prompt 不靠对话记忆，只注入一张状态卡」的工程契约用于外部"
        u"写作流：按七栏 schema 手写状态卡、校验字节预算与栏结构。当用户提到"
        u"状态卡、续写上下文、写作前摘要卡、跨章一致性上下文、12KB 状态卡的"
        u"时候使用。",
        version) + u"""# 续写状态卡：七栏续写上下文契约

上游 qianbi-novel 每章开写前把书状态压缩成一张 ≤%d 字节的七栏状态卡，直接
注入下一章 prompt——不靠对话记忆。本 skill 把这张卡的 schema 与校验器交给
外部写作流：你也可以为手写章节维护同样的卡。

完整 schema（栏语义/裁剪序/容量上限）见 `references/state-card-schema.md`；
本版契约与上游 qianbi-novel %s 逐字一致。

## 流程（三步）

1. **取数**：按 schema 七栏从你的书状态里取数（当前位置/下一章承诺/活跃
   伏笔(作者真相)/连贯性风险/核心角色状态/长期约束(正则must)/近三章速记
   (读者已知)）。注意「作者真相」与「读者已知」两栏的认知边界不得互串。
2. **渲染**：`# 续写状态卡（第N章）` 标题 + `## 栏题` + `- ` 整项条目；
   空栏整栏省略；写完自查字节数 ≤%d。
3. **校验**：`python <skill目录>/scripts/state_card_validate.py 状态卡.md`
   ——退出码 0 才算合格；`--json` 可得机器可读报告。超预算按 P5→P1 优先级
   整项丢，不截半句。

## 纪律与边界

- 状态卡是**约束**不是资料堆：每条都要对下一章写作有约束力，没有就删。
- 「活跃伏笔(作者真相)」栏内容永不进正文表述——那是作者兜里的牌。
- 裁剪序固定：先丢近三章速记(P5)，再长期约束(P4)、连贯性风险(P3)、核心角色
  (P2)、活跃伏笔(P1)；位置/承诺(P0)永不丢。
- 引擎版（上游 GUI）会从账本自动取数并裁剪；本 skill 是给手写流用的同款
  契约与自检器，不做自动取数。

%s
""" % (schema["byte_budget"], version, schema["byte_budget"],
       SKILL_FRONTEND_NOTE))
    summary["qianbi-state-card"] = {"byte_budget": schema["byte_budget"],
                                    "columns": len(titles)}


# ---------------- 顶层与编排 ----------------

def build(out: str, version: str) -> dict:
    summary = {}
    if os.path.isdir(out):
        shutil.rmtree(out)  # 幂等重建——产物集固定，删除再生成保证无陈旧残留
    # 字节码缓存会污染产物树（--check 逐字节比对），构建期一律不写 .pyc
    old_flag = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        build_deslop_package(out, version, summary)
        build_bridge_package(out, version, summary)
        build_state_card_package(out, version, summary)
    finally:
        sys.dont_write_bytecode = old_flag

    # 顶层 VERSION / README / marketplace.json
    write_text(os.path.join(out, "VERSION"), version + "\n")
    pkgs = ", ".join("%s（%s）" % (k, v) for k, v in sorted(summary.items()))
    write_text(os.path.join(out, "README.md"), u"""\
# qianbi-skills（自动生成，勿手改）

千笔网文方法论 skill 包：由 qianbi-novel `scripts/build_skills.py` 从仓库当前
成品自动生成——deslop 规则表与引擎逐字 vendoring、桥段码表、状态卡 schema
均以源码为唯一真源。上游版本 **%s**。

- %s

对账：`python scripts/build_skills.py --check`（与仓库 dist_skills/ 逐字节
比对，有差异 exit 1）。上游：%s
""" % (version, pkgs, UPSTREAM_URL))
    write_json(os.path.join(out, ".claude-plugin", "marketplace.json"), {
        "name": "qianbi-skills",
        "owner": {"name": "qianbi", "url": UPSTREAM_URL},
        "plugins": [{
            "name": "qianbi-skills",
            "description": "千笔网文方法论 skill 包：去 AI 味 lint / 桥段码表"
                           "路由 / 续写状态卡契约（确定性脚本，纯标准库）",
            "version": version,
            "source": "./",
            "skills": ["./qianbi-deslop", "./qianbi-bridge-codes",
                       "./qianbi-state-card"],
            "license": "MIT",
            "keywords": ["novel", "writing", "chinese", "webnovel",
                         "deslop", "consistency"],
        }],
    })
    return summary


def _tree(root: str) -> dict:
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            out[rel] = read_text(full)
    return out


def check(out_dir: str) -> list:
    """drift check：重生成到临时目录，与 out_dir 逐文件比对。返回差异描述。"""
    with tempfile.TemporaryDirectory(prefix="qbn_skills_check_") as tmp:
        build(tmp, read_version())
        fresh = _tree(tmp)
    current = _tree(out_dir) if os.path.isdir(out_dir) else {}
    diffs = []
    for rel in sorted(set(fresh) | set(current)):
        if rel not in current:
            diffs.append("缺失：%s（重新生成可得）" % rel)
        elif rel not in fresh:
            diffs.append("多余：%s（生成器已不再产出）" % rel)
        elif fresh[rel] != current[rel]:
            diffs.append("漂移：%s" % rel)
    return diffs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="build_skills.py",
                                 description="qianbi-skills 导出管线（E7）")
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "dist_skills"),
                    help="产物目录（默认 <repo>/dist_skills）")
    ap.add_argument("--check", action="store_true",
                    help="drift check：重生成比对，不写盘；有差异 exit 1")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    version = read_version()
    if args.check:
        diffs = check(args.out)
        if diffs:
            if not args.quiet:
                print("dist_skills 与生成器存在 %d 处差异：" % len(diffs))
                for d in diffs:
                    print("  " + d)
                print("重跑：python scripts/build_skills.py")
            return 1
        if not args.quiet:
            print("drift check 通过：dist_skills 与生成器逐字节一致（v%s）"
                  % version)
        return 0

    summary = build(args.out, version)
    if not args.quiet:
        n_files = len(_tree(args.out))
        print("qianbi-skills v%s → %s（%d 个文件）" % (version, args.out,
                                                      n_files))
        for k, v in sorted(summary.items()):
            print("  %s: %s" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
