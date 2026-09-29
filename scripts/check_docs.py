# -*- coding: utf-8 -*-
"""check_docs.py —— 文档口径核对脚本（QW-D3 / C03）。

五项检查，全部红/绿可判定（规格见 docs/落地计划附录A C03 卡 + _scratch/superiter/w4_docs.md §4.2）：

  1. 数字口径：README.md / README.en.md 中的测试数与探针数必须等于本机实跑
     `pytest tests/unit --collect-only` 的收集数与 tests/probe_*.py 实际个数
     （抓的就是 README「1061 passed」「EN 594 tests / 44 probe」这类数字腐烂）。
     口径说明：README 测试节的命令是 `pytest tests/unit -q`，所以核对基准取
     tests/unit 收集数（全仓 --co 口径更大，不混用）。
  2. 手册行数下限：docs/用户手册_v2.md ≥ 500 行（C40 手册 v2 落地，判据 C 数字要件；
     仍保留 v1 ≥ 200 的下限——v1 作为 0.20.0 口径快照随仓库留档，防误删）。
  3. 内链有效：扫描 README.md / README.en.md / CHANGELOG.md / docs/用户手册_v1.md /
     docs/用户手册_v2.md / docs/排障_v1.md / docs/README.md 的全部 markdown 相对链接
     （含图片），目标文件不存在即红；指向 README.md / README.en.md 的 #锚点与同文件
     #锚点按 GitHub slug 规则核对（抓的就是 CHANGELOG 曾出现的 `README.md#使用指南` 死锚）。
  4. 排障页文案对照：docs/排障_v1.md「错误对照表」每条屏幕文案必须能在 app/ 源码
     里 grep 到（逐字碎片匹配：f-string 变量处写「…」或照抄 {name}，变量两侧的文案
     必须逐字命中）——防文档文案与屏幕文案漂移，这是排障页的生命线。
     表外章节（SmartScreen 等系统级提示）不在 app 内，不参与本检查。
  5. 排障对照表条数 ≥10（当前 15+，每条含屏幕原文 → 含义 → 动作 → 报障包出口）。

范围外（待其他批次后补，勿在此提前红灯）：
  - latest.json 数字核对：待 S3 的 latest.json 改动合入后补（C03 该部分跳过）。
  - CI 接线：待 S3 的 .github/workflows/tests.yml 改动合入后，在现有 job 尾部加一步
    `python scripts/check_docs.py`（本轮不接 CI，本脚本仅本地手跑）。
  - i18n 声明行检查项（README 顶部「界面语言：简体中文」声明存在性）：待 C12-i18n
    落地后作为第 6 项检查扩入（TODO）。

用法：.venv/Scripts/python.exe scripts/check_docs.py   （全绿退出码 0，任一红退出码 1）
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MANUAL_MIN_LINES = 500          # 检查 2：手册 v2 行数下限（C40 判据 C 数字要件）
MANUAL_V1_MIN_LINES = 200       # 检查 2：v1 快照下限（留档防误删）
TROUBLE_TABLE_MIN_ROWS = 10     # 检查 5：排障对照表条数下限
DOC_LINE_MIN_PREFIX = 6         # 检查 4：文案逐字前缀的最短长度（字符）

LINK_SCAN_FILES = [
    "README.md",
    "README.en.md",
    "CHANGELOG.md",
    "docs/用户手册_v1.md",
    "docs/用户手册_v2.md",
    "docs/排障_v1.md",
    "docs/README.md",
]

ANCHOR_CHECK_TARGETS = {"README.md", "README.en.md"}   # 只对两份 README 核对 #锚点


# ---------- 工具 ----------

def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _strip_code_blocks(text: str) -> str:
    """去掉 ``` 围栏代码块，避免把代码示例里的链接/数字当正文核对。"""
    return re.sub(r"```.*?```", "", text, flags=re.S)


def github_slug(heading: str) -> str:
    """GitHub 风格锚 slug：小写、去标点（保留中日文/字母数字/空格/连字符）、空格转 -。"""
    t = re.sub(r"[`*_]", "", heading.strip())
    t = t.lower()
    out = []
    for ch in t:
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff" or ch in " -_":
            out.append(ch)
    return "".join(out).replace(" ", "-")


def headings_of(text: str) -> set:
    slugs = set()
    for m in re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", text):
        slugs.add(github_slug(m.group(2)))
    return slugs


# ---------- 检查 1：数字口径 ----------

def truth_numbers() -> dict:
    """实跑 collect-only 取单测收集数 + 数 probe_*.py 个数。"""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit", "--co", "-q",
         "--tb=no", "-p", "no:cacheprovider"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180)
    out = proc.stdout or ""
    m = None
    for line in out.splitlines():
        mm = re.search(r"(\d+) tests? collected", line)
        if mm:
            m = mm
    probes = sorted(p.name for p in (ROOT / "tests").glob("probe_*.py"))
    return {"collect": int(m.group(1)) if m else -1,
            "probes": len(probes), "pytest_ok": proc.returncode == 0 and m is not None}


PATTERNS_COLLECT = [
    (re.compile(r"收集\s*(\d+)\s*项"), "收集 N 项"),
    (re.compile(r"(\d+)\s*passed\b"), "N passed"),
    (re.compile(r"(\d+)\s*(?:offline\s+)?tests\b"), "N tests"),
]
PATTERNS_PROBES = [
    (re.compile(r"共\s*(\d+)\s*支"), "共 N 支"),
    (re.compile(r"(\d+)\s*probe_"), "N probe_*"),
    (re.compile(r"probe_\*\.py\s*\*{0,2}\s*(\d+)"), "probe_*.py N"),
]


def check_numbers(fails: list) -> dict:
    truth = truth_numbers()
    if not truth["pytest_ok"]:
        fails.append(f"[1] 无法取得实跑收集数（pytest --collect-only 失败），数字口径无从核对")
        return truth
    for rel in ("README.md", "README.en.md"):
        # 数字多写在代码围栏的注释里（命令即口径），此处不剥代码块、全文件扫描
        text = _read(rel)
        for pat, label in PATTERNS_COLLECT:
            for mm in pat.finditer(text):
                n = int(mm.group(1))
                if n != truth["collect"]:
                    fails.append(f"[1] {rel}：{label}={n} ≠ 实跑收集数 {truth['collect']}"
                                 f"（pytest tests/unit --co 口径）")
        for pat, label in PATTERNS_PROBES:
            for mm in pat.finditer(text):
                n = int(mm.group(1))
                if n != truth["probes"]:
                    fails.append(f"[1] {rel}：{label}={n} ≠ 探针实数 {truth['probes']}"
                                 f"（tests/probe_*.py 个数）")
    return truth


# ---------- 检查 2：手册行数下限 ----------

def check_manual_lines(fails: list) -> dict:
    """v2（正式手册，下限 500）+ v1（0.20.0 口径快照，下限 200）双查。"""
    out = {}
    for rel, floor in (("docs/用户手册_v2.md", MANUAL_MIN_LINES),
                       ("docs/用户手册_v1.md", MANUAL_V1_MIN_LINES)):
        n = len((ROOT / rel).read_text(encoding="utf-8", errors="replace").splitlines())
        out[rel] = n
        if n < floor:
            fails.append(f"[2] {rel} 只有 {n} 行 < 下限 {floor}（手册被误删/大幅缩水？）")
    return out


# ---------- 检查 3：内链有效 ----------

LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


def check_links(fails: list) -> dict:
    stats = {"links": 0, "anchors": 0}
    heading_cache = {}
    for rel in LINK_SCAN_FILES:
        path = ROOT / rel
        if not path.exists():
            continue
        base = path.parent
        text = _strip_code_blocks(path.read_text(encoding="utf-8", errors="replace"))
        if rel not in heading_cache:
            heading_cache[rel] = headings_of(text)
        for mm in LINK_RE.finditer(text):
            target = mm.group(1)
            if target.startswith(("http://", "https://", "mailto:", "<")):
                continue
            stats["links"] += 1
            if target.startswith("#"):   # 同文件锚
                stats["anchors"] += 1
                if target[1:] not in heading_cache[rel]:
                    fails.append(f"[3] {rel}：同文件死锚 {target}")
                continue
            file_part, _, anchor = target.partition("#")
            tp = (base / file_part).resolve()
            if not tp.exists():
                fails.append(f"[3] {rel}：链接目标不存在 → {target}")
                continue
            if anchor and file_part in ANCHOR_CHECK_TARGETS:
                stats["anchors"] += 1
                trel = str(tp.relative_to(ROOT)).replace("\\", "/")
                if trel not in heading_cache:
                    heading_cache[trel] = headings_of(_strip_code_blocks(_read(trel)))
                if anchor not in heading_cache[trel]:
                    fails.append(f"[3] {rel}：死锚 {target}（{trel} 无此标题锚）")
    return stats


# ---------- 检查 4/5：排障页文案对照与条数 ----------

def _app_sources() -> tuple:
    raws, joined = [], []
    for p in sorted((ROOT / "app").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        raws.append(t)
        # Python 隐式字符串拼接（"abc"\n"def"）拼合，容忍跨源码行的长文案
        joined.append(re.sub(r'"\s*\n\s*"', "", t))
    return "".join(raws), "".join(joined)


def _fragments(span: str) -> list:
    """把文案切成可逐字 grep 的碎片：f-string 变量写「{name}」或「…」，变量两侧都逐字。"""
    parts = re.split(r"…|\{[^{}]*\}", span)
    return [p.strip() for p in parts if p.strip()]


def trouble_table_rows(text: str) -> list:
    """取「错误对照表」小节的表格数据行（跳过表头与分隔行）。"""
    lines = text.splitlines()
    start = end = None
    for i, ln in enumerate(lines):
        if ln.startswith("#") and "错误对照表" in ln:
            start = i
            break
    if start is None:
        return []
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("#"):   # 下一个小节
            end = j
            break
    end = end if end is not None else len(lines)
    rows = []
    for ln in lines[start:end]:
        if ln.strip().startswith("|") and not re.match(r"^\s*\|[\s:\-|]+\|\s*$", ln):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if cells and cells[0].isdigit():   # 数据行（表头 #、分隔行已排除）
                rows.append(cells)
    return rows


def check_troubleshoot(fails: list) -> dict:
    rel = "docs/排障_v1.md"
    path = ROOT / rel
    if not path.exists():
        return {"skip": True, "rows": 0, "grep_ok": 0}
    text = _strip_code_blocks(path.read_text(encoding="utf-8", errors="replace"))
    rows = trouble_table_rows(text)
    stats = {"skip": False, "rows": len(rows), "grep_ok": 0}
    if len(rows) < TROUBLE_TABLE_MIN_ROWS:
        fails.append(f"[5] {rel} 错误对照表只有 {len(rows)} 条 < {TROUBLE_TABLE_MIN_ROWS}")
    raw_src, joined_src = _app_sources()
    for cells in rows:
        spans = re.findall(r"`([^`]+)`", " | ".join(cells))
        hit = None
        for span in spans:
            for frag in _fragments(span):
                if len(frag) < DOC_LINE_MIN_PREFIX:
                    continue
                if frag in raw_src or frag in joined_src:
                    hit = frag
                    break
            if hit:
                break
        if hit is None:
            fails.append(f"[4] {rel} 对照表第 {cells[0]} 条：屏幕文案在 app/ 源码里 grep 不到"
                         f"（逐字碎片均未命中）→ {' | '.join(cells)[:80]}…")
        else:
            stats["grep_ok"] += 1
    return stats


# ---------- 主流程 ----------

def main() -> int:
    fails: list = []
    truth = check_numbers(fails)
    manuals = check_manual_lines(fails)
    links = check_links(fails)
    trouble = check_troubleshoot(fails)

    print("=" * 64)
    print("check_docs —— 文档口径核对（规格：C03/QW-D3，w4_docs §4.2）")
    print("=" * 64)
    print(f"实跑口径：tests/unit 收集 {truth['collect']} 项；"
          f"探针 {truth['probes']} 支；"
          + "；".join("%s %d 行" % (k.split('/')[-1], v) for k, v in manuals.items())
          + f"；内链 {links['links']} 条（其中锚点 {links['anchors']} 条）")
    if trouble.get("skip"):
        print("[4]/[5] SKIP：docs/排障_v1.md 尚未创建（待 C13）")
    else:
        print(f"[4] 排障文案对照：{trouble['grep_ok']}/{trouble['rows']} 条可逐字 grep 到 app/ 源码")
        print(f"[5] 对照表条数：{trouble['rows']}（下限 {TROUBLE_TABLE_MIN_ROWS}）")
    print("-" * 64)
    if fails:
        for f in fails:
            print("FAIL", f)
        print(f"结果：红，{len(fails)} 处不合格")
        return 1
    print("结果：绿（5 项检查全部通过"
          + ("；4/5 因排障页未创建而 SKIP）" if trouble.get("skip") else "）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
