# -*- coding: utf-8 -*-
"""原作世界书拆解工具（同人档 · 步骤2）：设定/原作世界书.md → 世界书.md + 正则.md

这是「同人流」第二步骤的落地工具：导入的原始材料不进 prompt，拆解后才生效。
分块 → LLM 并发抽取（严格 JSON，每块独立 3 次重试）→ 按 wb.py 契约渲染 → 世界书.md / 正则.md。
同名条目（归一化）跨块去重：抽取并发跑，汇合后按块序先到先得，输出确定。
拆解完自动出 追踪/拆解覆盖度.json（期望类别 vs 实得类别），缺的提示 --theme 补拆。

专题层（--theme）：general=全量拆解（写 世界书.md/正则.md，现状逻辑）；
专题（如 民生与市场）只产出 追踪/拆解_专题_<主题名>.json（与主拆解清单同构），
条目由人工审阅后并入世界书.md 的追加登记区——本工具不自动改世界书.md。

用法：.venv/Scripts/python.exe tests/decompose_worldbook.py <项目路径> [块字符数] [--theme general|民生与市场|all]
"""
import argparse
import concurrent.futures
import json
import os
import re
import sys
import time

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())

from PySide6.QtGui import QGuiApplication          # noqa: E402
from PySide6.QtCore import Qt                      # noqa: E402

from app import config as cfg_mod                  # noqa: E402
from app import project, wb                        # noqa: E402
from app.llm.client import LLMClient, LLMError     # noqa: E402

PROMPT = """你是网文世界观设定管理员。下面是一段《{fandom}》世界观的拆解材料（可能截断）。
把它拆解成同人写作可机读的两张表。要求：

1. entries：世界观条目。每条 = 一个可独立命名的实体/规则/地点/组织/人物/物品/体系。
   - name：简短实体名（2-8字，专名优先）
   - cat：类别，限其一：人物/势力/地理/体系规则/物品/异火/丹药/斗技/历史/经济
   - desc：80-200字自足描述，数值/条件/价格必须原样保留（这是后文对账基准）
   - constant：是否为**世界级底层法则**（如等级体系、属性规则、货币制度）——是则 true，
     会常驻注入每章；普通实体一律 false
   - keys：别名/别称/相关触发词数组（没有就空数组）
2. rules：写作时**必须遵守的硬约束**，每条一句话可判定。
   - rule：约束内容（如「斗气等级从低到高依次为：斗者、斗师、大斗师、斗灵、斗王、斗皇、斗宗、斗尊、半圣、斗圣、斗帝，每级九星」）
   - level：must（违反=硬伤）或 should（风格倾向）
   - pattern：可选，条目内一段反引号包裹的字面正则（只在你确信时给，否则空串）
   只登记材料里真实写明的；禁止脑补材料没有的设定。宁缺毋滥，但材料里的硬设定一条都不许漏。

材料（第 {i}/{n} 块）：
\"\"\"{chunk}\"\"\"

只输出 JSON：{{"entries": [...], "rules": [...]}}"""

MAX_WORKERS = 3        # 分块抽取并发数
RETRY_DELAY = 2.0      # 单块解析失败后的退避秒数
PHASE = "worldbook_decompose"

# 专题层：instructions 追加到 PROMPT 之后；general 为空串=现状行为，PROMPT 一字不动
THEMES = {
    "general": {
        "title": "全量拆解",
        "instructions": "",
    },
    "民生与市场": {
        "title": "民生与市场",
        "instructions": (
            "【专题指令：民生与市场】本次是专题拆解，只抽取材料里与下列五个层面相关的条目与规则，"
            "其余内容（修炼升级、人物恩怨、地理风物、法宝丹药等）一律无视：\n"
            "- 平民生计：普通人（非斗气修行者）的营生与职业、工钱行市、生计方式\n"
            "- 物价与货币：货币制度与币值、小额货币/辅币口径（如铜币银币的进制与最小找零单位）、"
            "典型物价（粮、布、房、劳务报酬）\n"
            "- 市场管理与坊市规矩：集市/坊市/拍卖行的开闭时间、交易规矩、管理规定\n"
            "- 行会与执业制度：行会组织、入会与执业资格、行业规矩与垄断\n"
            "- 税收/佣金：税种、税率、抽头、佣金比例\n"
            "条目 cat 一律填「民生与市场」；rules 同样只收上述层面的硬约束。"
            "材料里没写明的口径宁缺毋滥，禁止脑补。"
        ),
    },
}

# 覆盖度对账的期望类别（与主文件渲染的类别一致 + 专题类别）
EXPECTED_CATEGORIES = ["体系规则", "地理", "势力", "人物", "物品", "异火", "丹药",
                       "斗技", "历史", "经济", "民生与市场"]


def theme_choices() -> list:
    return list(THEMES) + ["all"]


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="原作世界书拆解工具（同人档 · 步骤2）")
    ap.add_argument("proj", help="项目路径")
    ap.add_argument("chunk_chars", nargs="?", type=int, default=8000, help="块字符数（默认 8000）")
    ap.add_argument("--theme", default="general", choices=theme_choices(),
                    help="general=全量拆解（默认，写 世界书.md/正则.md）；"
                         "专题名=只拆该专题，写 追踪/拆解_专题_*.json；all=全量+全部专题顺序跑")
    return ap.parse_args(argv)


def resolve_themes(theme: str) -> list:
    """--theme 取值 → 实跑主题序列（all = general + 全部专题顺序跑）"""
    if theme == "all":
        return list(THEMES)
    return [theme]


def build_prompt(theme: str, fandom: str, i: int, n: int, chunk: str) -> str:
    """PROMPT 套材料 + 追加专题指令（general 无追加，与现状逐字一致）"""
    text = PROMPT.format(fandom=fandom, i=i, n=n, chunk=chunk)
    extra = THEMES.get(theme, {}).get("instructions", "")
    if extra:
        text += "\n\n" + extra
    return text


def split_chunks(text: str, chunk_chars: int) -> list:
    """粗切：先按标题行切大段，再滑窗凑块（标题边界比硬切更保语义）"""
    paras = [p for p in text.split("\n\n") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) > chunk_chars and cur:
            chunks.append(cur)
            cur = ""
        cur += p + "\n\n"
    if cur.strip():
        chunks.append(cur)
    return chunks


def extract_chunk(client, prompt: str, label: str = "chunk ?",
                  phase: str = PHASE, retries: int = 3, delay: float = None):
    """单块抽取（纯函数，client 可注入假件）：流式调用 + 严格 JSON 解析，失败退避重试。

    连续 retries 次失败返回 None，绝不抛异常——并发路径由调用方按块序汇合，保证输出确定。
    delay 缺省取模块常量 RETRY_DELAY（调用时取值，单测可 monkeypatch 成 0）。
    """
    delay = RETRY_DELAY if delay is None else delay
    data = None
    for attempt in range(1, retries + 1):
        try:
            # 流式：V4 系思考+长 JSON 输出动辄几分钟，非流式会撞读超时
            out = client.chat_stream(prompt, system="只输出合法 JSON，不要解释。",
                                     temperature=0.2, phase=phase)
            m = re.search(r"\{.*\}", out, re.S)
            parsed = json.loads(m.group(0) if m else out)
            if not (isinstance(parsed, dict) and "entries" in parsed):
                raise ValueError("JSON 缺 entries 字段")
            data = parsed
            break
        except (LLMError, ValueError) as e:
            data = None
            print(f"  [{label}] 第{attempt}次解析失败：{e}", flush=True)
            time.sleep(delay)
    if data is None:
        print(f"  [{label}] 放弃该块（连续失败）", flush=True)
    return data


def run_theme(client, chunks: list, theme: str, fandom: str = "斗破苍穹",
              phase: str = PHASE) -> tuple:
    """单主题拆解：ThreadPoolExecutor(3) 并发抽取各块 → 汇合后按块序去重（输出确定）。

    返回 (entries, rules_dict)；同名条目（归一化）先到先得，规则按首见序去重。
    """
    n = len(chunks)
    results = [None] * n
    print(f"[拆解·{theme}] {n} 块 · 并发 {MAX_WORKERS}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = {pool.submit(extract_chunk, client, build_prompt(theme, fandom, i, n, chunk),
                            label="chunk %d" % i, phase=phase): i
                for i, chunk in enumerate(chunks, 1)}
        for fut in concurrent.futures.as_completed(futs):
            i = futs[fut]
            try:
                results[i - 1] = fut.result()
            except Exception as e:  # noqa: BLE001  单块意外不拖垮整跑
                print(f"  [chunk {i}] 意外失败：{e}", flush=True)
            print(f"  [chunk {i}] 抽取{'完成' if isinstance(results[i - 1], dict) else '失败'}",
                  flush=True)
    # ---- 汇合后按 chunk 序号有序去重：并发只提速，不改输出 ----
    all_entries, all_rules, seen = [], {}, set()
    for i, data in enumerate(results, 1):
        if not isinstance(data, dict):
            continue
        added = 0
        for e in data.get("entries", []):
            key = wb.norm_name(str(e.get("name", "")))
            if not key or key in seen:
                continue
            seen.add(key)
            all_entries.append(e)
            added += 1
        for r in data.get("rules", []):
            rule = " ".join(str(r.get("rule", "")).split())
            if rule:
                all_rules[rule] = r
        print(f"  [chunk {i}] 新条目 {added}，累计 {len(all_entries)}；规则累计 {len(all_rules)}",
              flush=True)
    return all_entries, all_rules


def render_entry(e: dict) -> str:
    name = re.sub(r'[\\/:*?"<>|｜]', "", str(e.get("name", "")).strip())[:30]
    cat = str(e.get("cat", "")).strip() or "原作"
    desc = " ".join(str(e.get("desc", "")).split())
    marker = ""
    if e.get("constant"):
        marker = "\n  [常驻]"
    else:
        keys = [str(k).strip() for k in (e.get("keys") or []) if str(k).strip()]
        keys = [k for k in keys if k and k != name][:6]
        if keys:
            marker = "\n  [关键词：%s]" % "、".join(keys)
    return "- **%s**（%s）：%s%s" % (name, cat, desc, marker)


def render_worldbook_md(entries: list, fandom: str) -> tuple:
    """entries → (世界书.md 文本, 条目数)：按类别分节渲染（wb.py 契约）"""
    by_cat = {}
    for e in entries:
        by_cat.setdefault(str(e.get("cat", "其他")).strip() or "其他", []).append(e)
    order = ["体系规则", "地理", "势力", "人物", "物品", "异火", "丹药", "斗技", "历史", "经济", "其他"]
    doc_lines = ["## 世界书", "", "> 来源：原作世界书 LLM 拆解（%s · %s）。数值为对账基准，改动即违设定。" %
                 (fandom, time.strftime("%Y-%m-%d")), ""]
    n_total = 0
    for cat in order + [c for c in by_cat if c not in order]:
        items = by_cat.get(cat)
        if not items:
            continue
        doc_lines.append("### %s" % cat)
        doc_lines.append("")
        for e in items:
            line = render_entry(e)
            if line:
                doc_lines.append(line)
                n_total += 1
        doc_lines.append("")
    return "\n".join(doc_lines), n_total


def render_regex_md(all_rules: dict) -> str:
    """规则表 → 正则.md 文本。格式：`- 规则：…｜level：must｜scope：全文`"""
    rx_lines = ["# 正则（原作硬约束）", "",
                "> 来源：原作世界书拆解。must=违反即硬伤，审校与闸门按此对账。", ""]
    for rule, r in all_rules.items():
        level = str(r.get("level", "must")).strip() or "must"
        pat = str(r.get("pattern", "") or "").strip()
        line = "- 规则：%s｜level：%s｜scope：全文" % (rule, level if level in ("must", "should") else "must")
        if pat:
            line += "｜pattern：`%s`" % pat.strip("`")
        rx_lines.append(line)
    return "\n".join(rx_lines) + "\n"


def write_ledger(proj: str, filename: str, fandom: str, entries: list,
                 all_rules: dict, n_chunks: int) -> str:
    """拆解底册（主清单与专题清单同构）：{fandom, entries, rules, chunks}"""
    path = os.path.join(proj, "追踪", filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"fandom": fandom, "entries": entries,
                   "rules": list(all_rules.values()), "chunks": n_chunks},
                  f, ensure_ascii=False, indent=2)
    return path


def coverage_report(entries_groups: list, proj: str) -> dict:
    """覆盖度对账：本跑全部条目的类别 vs 期望类别 → 追踪/拆解覆盖度.json

    缺类别打印红榜，提示用 --theme 补拆（如「民生与市场」专题）。
    """
    present = set()
    for entries in entries_groups:
        for e in entries or []:
            cat = str(e.get("cat", "")).strip()
            if cat in EXPECTED_CATEGORIES:
                present.add(cat)
    report = {"categories_present": [c for c in EXPECTED_CATEGORIES if c in present],
              "categories_missing": [c for c in EXPECTED_CATEGORIES if c not in present]}
    with open(os.path.join(proj, "追踪", "拆解覆盖度.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    if report["categories_missing"]:
        print(f"[覆盖度·红榜] 缺类别：{'、'.join(report['categories_missing'])}"
              f" → 建议 --theme 补拆", flush=True)
    else:
        print("[覆盖度] 期望类别全覆盖", flush=True)
    return report


def run_decompose(proj: str, client, text: str, chunk_chars: int = 8000,
                  themes=("general",), fandom: str = "斗破苍穹") -> dict:
    """拆解主流程（不含 Qt/配置装配，client 由调用方注入，便于单测）。

    general 写 设定/世界书.md + 设定/正则.md + 追踪/拆解清单.json（现状逻辑）；
    专题只写 追踪/拆解_专题_<主题名>.json（与主清单同构），不自动改世界书.md。
    最后写 追踪/拆解覆盖度.json。返回 {theme: {entries, rules, chunks}}。
    """
    chunks = split_chunks(text, chunk_chars)
    print(f"[拆解] {len(chunks)} 块", flush=True)
    out = {}
    for theme in themes:
        entries, all_rules = run_theme(client, chunks, theme, fandom=fandom)
        n_rules = len(all_rules)
        if theme == "general":
            doc, n_total = render_worldbook_md(entries, fandom)
            project.write_file(os.path.join(proj, project.WORLDBOOK_PATH), doc)
            project.write_file(os.path.join(proj, project.REGEX_PATH), render_regex_md(all_rules))
            write_ledger(proj, "拆解清单.json", fandom, entries, all_rules, len(chunks))
            print(f"[完成] 世界书条目 {n_total} 条 → 世界书.md；硬规则 {n_rules} 条 → 正则.md",
                  flush=True)
            print("[完成] 拆解底册 → 追踪/拆解清单.json", flush=True)
        else:
            write_ledger(proj, "拆解_专题_%s.json" % theme, fandom, entries, all_rules, len(chunks))
            print(f"[完成] 专题条目 {len(entries)} 条、规则 {n_rules} 条"
                  f" → 追踪/拆解_专题_{theme}.json", flush=True)
            print(f"[专题·{theme}] 将专题条目人工并入世界书.md（本工具不自动改写）", flush=True)
        out[theme] = {"entries": entries, "rules": list(all_rules.values()), "chunks": len(chunks)}
    coverage_report([v["entries"] for v in out.values()], proj)
    return out


def main(argv=None):
    args = parse_args(argv)
    proj = args.proj
    assert os.path.isdir(proj), "项目路径不对: %s" % proj
    src = os.path.join(proj, project.WORLDBOOK_SOURCE_PATH)
    text = project.read_file(src)
    assert text.strip(), "原作世界书是空的: %s" % src

    app = QGuiApplication(sys.argv[:1])
    cfg = cfg_mod.load_config()
    conn = cfg_mod.slot_connection(cfg, cfg_mod.SLOT_HELPER)
    assert conn.get("api_key") or conn.get("key_ref"), "辅助槽没有 Key: %s" % conn.get("name")
    client = LLMClient.from_connection(conn, max_retries=2, backoff_base=2.0, slot="helper")
    print(f"[拆解] 模型={conn.get('model')} · 材料 {len(text)} 字 · 块 {args.chunk_chars} 字")

    themes = resolve_themes(args.theme)
    run_decompose(proj, client, text, chunk_chars=args.chunk_chars, themes=themes)


if __name__ == "__main__":
    main()
