# -*- coding: utf-8 -*-
"""W0.6 project_header 利用率审计（成本优化战役 v2）

对照 deepseek-harness 社区审计（GitHub discussion #2064：tool schemas 占前缀 86%，
其中一半根本用不到），回答同类问题：project_header（app/core/shared_prefix.py）的
每一块，到底被哪些下游相位真正消费？

做什么（全部只读 app/ 与 projects/，不联网、不改前缀本身）：
  1. 在 tempfile 里按 shared_prefix 的读取路径搭最小项目夹具，调真实 project_header()
     取头部，按块切分，统计字符数与估算 token（中文字符×0.6，粗估口径）；
  2. 对每块的「概念 / 组装函数 / 重复注入」做正则扫描（app/ 下全部 .py，含
     app/prompts/ 与 app/core/ 的全部文件），产出「块 × 消费方」矩阵；
  3. 对仓库内真实项目（projects/，只读）量实际头部的逐块大小；
  4. 产出 docs/header审计_v2.md，并同步打印到 stdout。

夹具最小集（先读代码确认，见 docs/header审计_v2.md §1）：
  - 设定/题材定位.md、设定/正则.md、设定/世界书.md 三件必需；
  - pipeline_state.json：state.load_state 缺文件时返回 DEFAULT_STATE（不报错），
    genre_preset 取到空串 → 块01 缺席。最小夹具（夹具A）不建；
    为覆盖全部六块另建夹具B（多一个两键 state 文件，真实项目必有此文件）。

可重复运行：临时夹具用完即删（tempfile.TemporaryDirectory），输出整体重写、
不含时间戳，同一仓库状态下多次运行产出逐字节一致。
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import project as app_project                    # noqa: E402（零副作用模块）
from app.core.shared_prefix import project_header         # noqa: E402（经 app/core/__init__ 引入 orchestrator→PySide6，仅导入无副作用）

DOC_PATH = os.path.join(ROOT, "docs", "header审计_v2.md")
TOKEN_PER_HAN = 0.6          # 粗估口径：1 个中文字符 ≈ 0.6 token（DeepSeek 量级估）
HAN_RE = re.compile(r"[\u4e00-\u9fff]")
ASSEMBLER = "app/core/shared_prefix.py"

# ==================== 夹具内容（最小集，逐文件对应 shared_prefix 的读取路径）====================

CORE_MD = """# 核心设定：《审计测例之书》

## 类型定位
都市修仙爽文，单主角，节奏优先。

### 金手指约束条款
- 「墨账」每日最多改写三条因果，超出即反噬宿主
- 每次改写消耗一枚「墨鳞」，墨鳞全书上限九枚

### 全局红线
- 禁止无代价外挂：一切改写必须有可感代价
- 禁止主角知晓全书剧情走向

### 授权自创清单
- 墨鳞（金手指消耗品，本书自创）
- 灯下当铺（主场景，本书自创）

## 主要角色表
- 陈测：主角，当铺账房
"""

REGEX_MD = """# 正则（逻辑约束规则集）

- 规则：正文不得出现现代计量单位（米/公里/公斤）｜level：must｜scope：全书
- 规则：金手指每次使用必须写出代价症状｜level：must｜scope：全书
- 规则：配角名字不用叠字｜level：should｜scope：全书
"""

# 首条带 [常驻] 标记（进头部块05）；次条无常驻标记（只进逐章 worldbook_block）
WORLDBOOK_MD = """## 规则

- **灵石十进制**（规则）：灵石兑换恒为十进制，一贯钱=十文 [常驻]
- **坊市宵禁**（规则）：子时后坊市清场，违者罚灵石十两
"""

STATE_JSON = '{"genre_preset": "cultivation"}\n'   # 夹具B 追加（真实项目必有）


def build_fixture(tmp_root: str, with_state: bool) -> str:
    """按 shared_prefix 的读取路径搭最小项目夹具，返回项目路径"""
    proj = os.path.join(tmp_root, "审计夹具书")
    setting = os.path.join(proj, "设定")
    os.makedirs(setting, exist_ok=True)
    for name, content in (("题材定位.md", CORE_MD), ("正则.md", REGEX_MD),
                          ("世界书.md", WORLDBOOK_MD)):
        with open(os.path.join(setting, name), "w", encoding="utf-8") as f:
            f.write(content)
    if with_state:
        with open(os.path.join(proj, "pipeline_state.json"), "w", encoding="utf-8") as f:
            f.write(STATE_JSON)
    return proj


# ==================== 头部切块（按 _header_cached 的固定块标题）====================

# 块边界 = 各块的固定起始行前缀（来自 _header_cached / constraints_block 的字面标题）。
# 约束三节在头部里同为「【」开头、以空行相连，故合并为块03。
BOUNDARIES = (
    ("01 题材预设", "## 题材预设"),
    ("02 核心设定节选", "## 核心设定节选"),
    ("03 约束条款（金手指/红线/授权自创）", "【金手指约束条款】"),
    ("03 约束条款（金手指/红线/授权自创）", "【全局红线】"),
    ("03 约束条款（金手指/红线/授权自创）", "【授权自创清单】"),
    ("04 正则契约全文", "## 正则契约"),
    ("05 世界书·常驻条目", "## 世界书·常驻条目"),
    ("06 全局写作纪律", "## 全局写作纪律"),
)


def split_header(text: str) -> list:
    """真实头部文本 → [(块key, 起始行, 块文本)]；首行横幅单独成块；
    约束三节（同为【】开头、空行相连）合并为块03"""
    lines = text.split("\n")
    starts = []
    for i, ln in enumerate(lines):
        for key, pref in BOUNDARIES:
            if ln.startswith(pref):
                starts.append((i, key))
                break
    banner = lines[0] if lines else ""
    chunks = [("00 头部横幅", banner, banner)]
    merged = {}
    order = []
    for n, (i, key) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        body = "\n".join(lines[i:end]).strip("\n")
        if key in merged:
            merged[key] = (merged[key][0], merged[key][1] + "\n\n" + body)
        else:
            merged[key] = (lines[i], body)
            order.append(key)
    for key in order:
        head, body = merged[key]
        chunks.append((key, head, body))
    return chunks


def est_metrics(text: str) -> dict:
    """字符口径：len()（Python 字符，含空白与 markdown 标记）；
    token 口径：中文字符数×0.6（粗估，非中文字符不计，DeepSeek 实际分词有偏差）"""
    han = len(HAN_RE.findall(text))
    return {"chars": len(text), "han": han, "tok": int(han * TOKEN_PER_HAN + 0.5)}


# ==================== 消费方扫描（app/ 全部 .py）====================

BLOCK_PROBES = (
    {"key": "01 题材预设",
     "concept": r"题材预设|genre_block|genre_preset",
     "consumer": r"genre_block_for\(|genre_block\(",
     "reinject": r"genre_block\s*=|_genre_block\(",
     "note": "组装点唯一（shared_prefix 按 prose 档注入）；独立消费方 stages._genre_block 按"
             "相位（core_setting/outline/worldbook/unit_outline）再注入各自特化档——其余四相位"
             "头部档与相位档并存（两份题材文本），正文相位只靠头部这份。"},
    {"key": "02 核心设定节选",
     "concept": r"核心设定|题材定位",
     "consumer": r"read_file\([^\n]*题材定位",
     "reinject": r"core_setting\s*=|core_text\s*=",
     "note": "头部只装 题材定位.md 前 1500 字符；独立读方多：stages 卷纲重读前 4000 字符、"
             "enrich 重读前 1500 字符、project.worldbook_anchors 读角色表做锚点、"
             "canon_audit 读授权自创清单——内容被多处按需重读，头部副本有普适依据。"},
    {"key": "03 约束条款（金手指/红线/授权自创）",
     "concept": r"金手指约束|全局红线|授权自创|constraints_block",
     "consumer": r"constraints_block\(",
     "reinject": None,
     "note": "唯一独立消费方 canon_audit：清算两 prompt（AUDIT/AUDIT_REVIEW）各自独立注入"
             "constraints_block，并单独解析「授权自创清单」做专名豁免；planning.py 是这三节的"
             "产出侧（生成指令）不是消费侧；其余相位纯搭车。移出头部前须确认审校/正文对红线"
             "的隐性依赖（设计意图：红线随时在场）→ 交 gate 裁决。"},
    {"key": "04 正则契约全文",
     "concept": r"正则契约|正则约束|正则规则|must 规则",
     "consumer": r"regex_rules\(|regex_block\(|scan_proj\(|canon_digest\(",
     "reinject": r"regex_block\s*=|must_block\s*=",
     "note": "独立消费方最多的一块：mustscan.scan_proj 本地硬校验、stages 各相位 "
             "regex_block/must_block 再注入、co_dialogue 六处、importdoc、canon_digest。"
             "头部灌的是 设定/正则.md 整文件（含 should 与注释），与标题「must 全文」名实"
             "不符——保留也应过滤。与逐章 regex_block 构成双份注入。"},
    {"key": "05 世界书·常驻条目",
     "concept": r"世界书|worldbook",
     "consumer": r"constant_entries\(",
     "reinject": r"worldbook_block\s*=|worldbook_text\(|wb\.assemble\(",
     "note": "constant_entries 在全仓只有一个调用方——组装点 shared_prefix 自身；按判定标准"
             "（消费方只有组装点自身）属疑似低利用。且 wb.assemble 逐章装配（prose/细纲/终审"
             "的 worldbook_block）时同批常驻条目按 P_CONSTANT 最高档**再次进入**——头部这份与"
             "逐章块重复；仅当逐章 2000 字预算把常驻条目挤掉时头部版才兜底。移出候选之首。"},
    {"key": "06 全局写作纪律",
     "concept": r"全局写作纪律|STYLE_DISCIPLINE|style_discipline",
     "consumer": r"STYLE_DISCIPLINE",
     "reinject": r"[\"'{]style_discipline|style_discipline\s*=",
     "note": "唯一独立消费方 = 正文模板的 {style_discipline} 槽（stages.py 组 kwargs 注入 "
             "PROSE_WRITING_PROMPT）——正文相位本就双份；纪律条目 4-15 全是正文工艺，大纲/"
             "审校/摘要等相位无独立消费证据，属搭车。移出头部对正文零损失（模板槽已自带），"
             "其余相位瘦头。"},
)


def app_py_files() -> list:
    out = []
    base = os.path.join(ROOT, "app")
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def role_of(rel: str) -> str:
    if rel == ASSEMBLER:
        return "组装点"
    if rel.startswith("app/prompts/"):
        return "prompts模板"
    if rel.startswith("app/core/"):
        return "core逻辑"
    if rel.startswith("app/ui/"):
        return "UI"
    if rel.startswith(("app/presets/", "app/llm/")):
        return "基建"
    return "app根模块"


def scan_app(pattern: str) -> list:
    hits = []
    for path in app_py_files():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        for i, ln in enumerate(lines, 1):
            if re.search(pattern, ln):
                hits.append((rel, i, ln.strip()))
    return hits


def hit_kind(line: str) -> str:
    if line.startswith("#"):
        return "注释"
    if re.match(r"^(from\s|import\s)", line):
        return "转出口"
    if re.match(r"^def\s", line) or re.match(r"^[A-Z_]{4,}\s*=", line):
        return "定义"
    if re.match(r"^[A-Z_][A-Z0-9_]*,?$", line):          # import 列表里的裸名续行
        return "转出口"
    if re.match(r"^\"[^\"]*\"(,\s*\"[^\"]*\")*,?$", line):   # __all__ 之类的字符串列表行
        return "转出口"
    return "引用"


def refs_only(hits: list) -> list:
    """排除组装点自身与定义/转出/注释行后的「真实引用」"""
    return [h for h in hits if hit_kind(h[2]) == "引用" and role_of(h[0]) != "组装点"]


def fmt_refs(refs: list, limit: int = 4) -> str:
    per = {}
    for rel, ln, _s in refs:
        per.setdefault(rel, []).append(ln)
    parts = ["%s×%d" % (rel, len(lns)) for rel, lns in sorted(per.items())]
    if not parts:
        return "（无）"
    if len(parts) > limit:
        return "、".join(parts[:limit]) + " 等%d个文件" % len(parts)
    return "、".join(parts)


def templates_with_header() -> list:
    """含 {project_header} 占位符的 prompt 模板常量（头部整体注入方清单）"""
    out = []
    for path in app_py_files():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        for m in re.finditer(r"^([A-Z][A-Z0-9_]{3,})\s*=\s*(?:f|r|rf|fr)?\"\"\"", text, re.M):
            end = text.find("\"\"\"", m.end())
            if end != -1 and "{project_header}" in text[m.end():end]:
                out.append("%s :: %s" % (rel, m.group(1)))
    return out


def real_projects() -> list:
    base = os.path.join(ROOT, "projects")
    out = []
    if not os.path.isdir(base):
        return out
    for dirpath, dirnames, _f in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "pipeline_debug")]
        if app_project.is_project(dirpath):
            out.append(os.path.relpath(dirpath, ROOT).replace("\\", "/"))
            dirnames[:] = []
    return sorted(out)


# ==================== 审计产出 ====================

def audit() -> str:
    app_files = app_py_files()
    n_prompts = sum(1 for p in app_files if "/app/prompts/" in p.replace("\\", "/"))
    n_core = sum(1 for p in app_files if "/app/core/" in p.replace("\\", "/"))

    with tempfile.TemporaryDirectory(prefix="header_audit_") as tmp:
        proj_a = build_fixture(tmp, with_state=False)
        header_a = project_header(proj_a)
        proj_b = build_fixture(tmp, with_state=True)
        header_b = project_header(proj_b)

    chunks_b = split_header(header_b)
    metrics = [(key, head, est_metrics(body)) for key, head, body in chunks_b]
    total_chars = sum(m["chars"] for _k, _h, m in metrics)
    total_tok = sum(m["tok"] for _k, _h, m in metrics)
    block05_tok = next(m["tok"] for k, _h, m in metrics if k.startswith("05"))
    block06_tok = next(m["tok"] for k, _h, m in metrics if k.startswith("06"))
    block04_chars = next(m["chars"] for k, _h, m in metrics if k.startswith("04"))
    m_a = est_metrics(header_a)

    # 逐块扫描
    scans = []
    for bd in BLOCK_PROBES:
        concept = scan_app(bd["concept"])
        cons_hits = scan_app(bd["consumer"]) if bd.get("consumer") else []
        re_hits = scan_app(bd["reinject"]) if bd.get("reinject") else []
        cons_refs, re_refs = refs_only(cons_hits), refs_only(re_hits)
        files = sorted({h[0] for h in cons_refs})
        if not files:
            verdict = "疑似低利用"
        elif len(files) == 1:
            verdict = "专属相位"
        else:
            verdict = "全员共享"
        if re_refs:
            verdict += "（含重复注入）"
        scans.append({"bd": bd, "concept": concept, "cons_refs": cons_refs,
                      "re_refs": re_refs, "files": files, "verdict": verdict})

    tpl_list = templates_with_header()
    all_block_keys = ["01 题材预设", "02 核心设定节选",
                      "03 约束条款（金手指/红线/授权自创）", "04 正则契约全文",
                      "05 世界书·常驻条目", "06 全局写作纪律"]
    reals = []
    for rel in real_projects():
        proj = os.path.join(ROOT, rel)
        chunks = split_header(project_header(proj))
        per = {k: est_metrics(body) for k, _h, body in chunks}
        missing = ["%s" % k.split(" ")[0] for k in all_block_keys if k not in per]
        reals.append({"rel": rel, "per": per,
                      "chars": sum(m["chars"] for m in per.values()),
                      "tok": sum(m["tok"] for m in per.values()),
                      "missing": missing})

    # ---------- 组 markdown ----------
    L = []
    L.append("# project_header 利用率审计（W0.6 · 成本优化战役 v2）\n")
    L.append("本文件由 `scripts/header_audit.py` 产出（幂等可复跑，不含时间戳；"
             "复跑：`cd %s && .venv/Scripts/python.exe scripts/header_audit.py`）。" % ROOT)
    L.append("对照对象：deepseek-harness 社区审计 #2064——tool schemas 占前缀 86%，其中一半"
             "根本用不到。本项目没有工具表，对应物是 **project_header 的设定全家桶**。"
             "本审计回答：头部六块各被谁真正消费，谁是无用块。\n")

    L.append("## 1. 口径与夹具\n")
    L.append("**数字口径**：")
    L.append("- 字符数 = Python `len()`（含空白与 markdown 标记的原始字符）；")
    L.append("- 估算 token = **中文字符数 × 0.6**（粗估口径，非中文字符与空白不计入；"
             "DeepSeek 实际分词与公式有 ±20% 量级偏差，正则/表格等 ASCII 密集块会低估，"
             "只用于块间量级比较，精确值以 usage.jsonl 实测为准）；")
    L.append("- 占比 = 块字符数 / 头部总字符数。\n")
    L.append("**夹具最小集**（先读代码确认）：`project_header` 的读取路径 = "
             "`设定/题材定位.md`（全文截 1500 + 约束三节各截 600）、`设定/正则.md`（整文件）、"
             "`设定/世界书.md`（仅 [常驻] 条目）、`pipeline_state.json` 的 `genre_preset`"
             "（题材预设源）。`state.load_state` 缺文件时返回 DEFAULT_STATE 不报错，"
             "`genre_preset` 取到空串 → 块01 缺席。因此：")
    L.append("- **夹具A**（最小集，三件设定文件，不建 state）：验证缺文件行为——"
             "块01 确实缺席，头部 %d 字符 / 估算 %d tok；" % (m_a["chars"], m_a["tok"]))
    L.append("- **夹具B**（A + 单键 `pipeline_state.json`，仅 `genre_preset=cultivation`；"
             "真实项目必有该文件）：六块齐全，作为主测量口径，下表数字全部来自真实 "
             "`project_header()` 输出。\n")

    L.append("## 2. 头部逐块审计表（夹具B · cultivation 预设 · prose 档）\n")
    L.append("| 块 | 字符 | 估算token | 占比 | 独立消费方（非组装点·真实引用） | 判定 |")
    L.append("|---|---:|---:|---:|---|---|")
    for key, head, m in metrics:
        if key.startswith("00"):
            L.append("| – | 头部横幅 | %d | %d | %.1f%% | –（结构行，全员共享） |"
                     % (m["chars"], m["tok"], 100.0 * m["chars"] / total_chars))
            continue
        sc = next(s for s in scans if s["bd"]["key"] == key)
        L.append("| %s | %d | %d | %.1f%% | %s | **%s** |"
                 % (key.split(" ")[0], m["chars"], m["tok"],
                    100.0 * m["chars"] / total_chars,
                    fmt_refs(sc["cons_refs"]).replace("|", "\\|"), sc["verdict"]))
    L.append("| **合计** | **%d** | **%d** | 100%% | %d 个模板常量经 `{project_header}` 整体注入（见 §3） | – |"
             % (total_chars, total_tok, len(tpl_list)))
    L.append("")
    L.append("**逐块审计说明**（判定标准：疑似低利用 = 独立消费方只有组装点自身，"
             "没有任何 prompt 模板或逻辑读取其内容；专属相位 = 独立消费方集中在单一相位；"
             "全员共享 = 跨相位多处独立消费。「含重复注入」= 头部之外还有调用点把同一来源"
             "内容再注入一遍）：\n")
    for sc in scans:
        key = sc["bd"]["key"]
        m = next(mm for k, _h, mm in metrics if k == key)
        L.append("- **%s**（%d 字符 / 估算 %d tok，占比 %.1f%%）→ %s。%s"
                 % (key, m["chars"], m["tok"], 100.0 * m["chars"] / total_chars,
                    sc["verdict"], sc["bd"]["note"]))

    L.append("\n## 3. 消费方扫描明细\n")
    L.append("扫描范围：`app/` 下全部 %d 个 .py（app/prompts/ %d 个 + app/core/ %d 个 + "
             "根模块/UI/基建其余），逐行正则命中；引用行排除定义/转出口/注释与组装点自身。"
             "整体注入方（模板含 `{project_header}` 占位符，任何块都随头部进这些调用）：\n"
             % (len(app_files), n_prompts, n_core))
    for t in tpl_list:
        L.append("- `%s`" % t)
    stages_calls = len([h for h in scan_app(r"project_header\(")
                        if h[0] == "app/core/stages.py"])
    L.append("- `app/core/stages.py`：%d 处 `project_header(...)` 调用点（核心设定/卷纲/细纲批/"
             "正文/扩写/压缩/去味/终审/审校票/作者复审/追踪/摘要等相位组装）；另有 "
             "chapter_session/co_dialogue/ui bridge 直接拼 system" % stages_calls)
    L.append("")
    for sc in scans:
        bd = sc["bd"]
        L.append("### %s\n" % bd["key"])
        L.append("- 消费探针 `%s` → 真实引用：%s"
                 % (bd["consumer"], fmt_refs(sc["cons_refs"])))
        for rel, ln, s in sc["cons_refs"][:8]:
            L.append("  - `%s:%d` [%s] `%s`" % (rel, ln, role_of(rel), s[:110]))
        if bd.get("reinject"):
            L.append("- 重复注入探针 `%s` → %s" % (bd["reinject"], fmt_refs(sc["re_refs"])))
            for rel, ln, s in sc["re_refs"][:6]:
                L.append("  - `%s:%d` [%s] `%s`" % (rel, ln, role_of(rel), s[:110]))
        concept_files = sorted({h[0] for h in sc["concept"]})
        L.append("- 概念探针 `%s` → %d 处命中 / %d 个文件（含泛指与产出侧，仅作背景）"
                 % (bd["concept"], len(sc["concept"]), len(concept_files)))
        L.append("")

    L.append("## 4. 真实项目样本（projects/，只读实测）\n")
    L.append("| 项目 | 头部字符 | 估算token | 在场块（字符） | 缺席块 |")
    L.append("|---|---:|---:|---|---|")
    for r in reals:
        present = "、".join("%s=%d" % (k.split(" ")[0], m["chars"])
                            for k, m in sorted(r["per"].items()) if not k.startswith("00"))
        if not present:
            present = "仅横幅"
        L.append("| %s | %d | %d | %s | %s |"
                 % (r["rel"], r["chars"], r["tok"], present,
                    "、".join(r["missing"]) or "无"))
    L.append("")
    L.append("读法：以表中「缺席块」列为准。两本现有真实书均未进入世界书/正则阶段"
             "（无 `设定/正则.md`、`设定/世界书.md` → 块04/05 缺席），state 也没有 "
             "`genre_preset`（块01 缺席），且题材定位.md 未含「金手指约束条款」三节"
             "（块03 缺席——planning 模板要求生成该三节，这两本早期书没有）→ 真实头部 "
             "≈ 横幅 + 核心设定节选 + 全局写作纪律，两本书的设定全文都顶到 1500 字截断"
             "上限。推论：**块03 的约束注入对存量书是空的**（头部与 canon_audit 同源，"
             "两边一起空）；共写档（`CW_STAGE_WORLDBOOK`）落盘正则/世界书后块04/05 才"
             "上场，届时正则文件的体量决定块04 占比（「H 主力」之说只对有正则的书成立）。\n")

    L.append("## 5. 发现与建议（交 gate 裁决，本包不改 app/）\n")
    L.append("**F1 疑似低利用块清单**：")
    L.append("- **块05 世界书·常驻条目**：`wb.constant_entries` 全仓唯一调用方是组装点自身"
             "（判定标准直接命中）；且逐章 `worldbook_block`（wb.assemble 的 P_CONSTANT 档）"
             "把同批条目**再注入一遍**——头部版只在逐章 2000 字预算挤掉常驻条目时兜底。"
             "移出方向二选一：① 头部移出、`wb.assemble` 对常驻条目保底（语义不变，头部瘦"
             " %d tok）；② 保留头部、assemble 排除 constant 防双份（省的是逐章 hit 价）。"
             % block05_tok)
    L.append("- **块06 全局写作纪律（次级候选，专属相位）**：唯一独立消费方是正文模板的 "
             "`{style_discipline}` 槽——正文相位双份，其余相位纯搭车。移出头部：正文总输入"
             "不变（模板槽已自带），其余每笔省 %d tok（hit 价）；需 gate 确认审校相位是否"
             "依赖纪律条目 6/11/13 的跨章条款。" % block06_tok)
    L.append("- **块03 约束条款（专属相位，谨慎）**：唯一独立消费方是清算 canon_audit"
             "（两 prompt 独立注入 + 授权自创豁免解析）；但设计意图是红线随时在场。"
             "建议保留头部，或仅随创作类相位注入。\n")
    L.append("**F2 正文相位三重重复注入**：正文一笔 prompt 里同时有 头部块04（正则整文件）"
             "+ `{regex_block}`、头部块05（常驻条目）+ `{worldbook_block}`、头部块06 + "
             "`{style_discipline}`。哪怕块不移出，去重也能省（hit 价口径）。\n")
    L.append("**F3 块04 名实不符**：标题写「must 全文 · 违反即硬伤」，实现是 "
             "`read_file(REGEX_PATH)` 整文件——`level：should` 规则与 `#` 注释行一并注入并被"
             "冠以 must 之名。若 gate 决定保留，至少按 must 级过滤后再入头部"
             "（本夹具口径下块04=%d 字符，其中 should 条约占 1/3）。\n" % block04_chars)
    L.append("**F4 头部指纹不含 genre_preset**：`_fingerprint` 只看三个设定文件的 mtime，"
             "块01 的数据源 `pipeline_state.json` 不在其中——进程内切预设不会失效已缓存头部"
             "（「下一章生效」实际依赖跨进程重启）。仅记录；另注意 `_header_cached` 是进程内 "
             "LRU，同一 (proj, 指纹) 二次调用逐字节一致，符合设计。\n")
    L.append("**F5 移出节省的口径**（token 口径，不折现；价目见 "
             "`docs/成本优化深度调研报告_v2.md` §缓存计价横评，DeepSeek hit=miss×1/31）：")
    L.append("- 每笔**暖命中**调用省：块 tok × hit 价（= miss 价 / 31）；")
    L.append("- 每次**冷启动**（进程首笔 / TTL 过期 / 前缀变更后首笔）省：块 tok × miss 价；")
    L.append("- context rot：头部每瘦 1k tok，注意力噪声与首笔延迟同降（不可量化，只记方向）。\n")
    L.append("**F6 · N3 红线（改动前缀的一次性代价）**：前缀按位置逐字节匹配——任何块移出/"
            "过滤都会让**下一跑首笔全 miss**（整个头部按 miss 价重算一次，约等于全头部 tok × "
            "miss 价；夹具B 全头部 %d tok，真实书以实测为准），之后重新暖起。因此：所有前缀"
            "变更（移出块05/06、块04 过滤 should）**合并为一次变更**上线，不要分多次折腾"
            "前缀；变更时机选挂机队列起点。\n" % total_tok)
    L.append("**F7 与 harness #2064 的对照结论**：我们没有 86% 那样的单一巨块——头部六块里"
             "没有「一半根本用不到」的体量；最接近的对应物是**块05 的重复注入**（用不到的"
             "「第二份常驻条目」）与块04 的 should/注释杂质。结构性结论：本项目的缓存大头"
             "治理应继续走 O7（缓存卫生）与 O1/O2（输出/思考侧），头部只做上述小修。\n")
    return "\n".join(L) + "\n"


def main() -> int:
    md = audit()
    os.makedirs(os.path.dirname(DOC_PATH), exist_ok=True)
    with open(DOC_PATH, "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    print("=== 已写入 %s ===" % DOC_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
