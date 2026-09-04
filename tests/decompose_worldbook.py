# -*- coding: utf-8 -*-
"""原作世界书拆解工具（同人档 · 步骤2）：设定/原作世界书.md → 世界书.md + 正则.md

这是「同人流」第二步骤的落地工具：导入的原始材料不进 prompt，拆解后才生效。
分块 → LLM 抽取（严格 JSON）→ 按 wb.py 契约渲染 → 世界书.md / 正则.md。
同名条目（归一化）跨块去重，先到先得；每个 chunk 的输出解析失败自动重试一次。

用法：.venv/Scripts/python.exe tests/decompose_worldbook.py <项目路径> [块字符数]
"""
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


def main():
    proj = sys.argv[1] if len(sys.argv) > 1 else ""
    chunk_chars = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
    assert proj and os.path.isdir(proj), "项目路径不对: %s" % proj
    src = os.path.join(proj, project.WORLDBOOK_SOURCE_PATH)
    text = project.read_file(src)
    assert text.strip(), "原作世界书是空的: %s" % src

    app = QGuiApplication(sys.argv[:1])
    cfg = cfg_mod.load_config()
    conn = cfg_mod.slot_connection(cfg, cfg_mod.SLOT_HELPER)
    assert conn.get("api_key") or conn.get("key_ref"), "辅助槽没有 Key: %s" % conn.get("name")
    client = LLMClient.from_connection(conn, max_retries=2, backoff_base=2.0, slot="helper")
    print(f"[拆解] 模型={conn.get('model')} · 材料 {len(text)} 字 · 块 {chunk_chars} 字")

    # ---- 粗切：先按标题行切大段，再滑窗凑块（标题边界比硬切更保语义）----
    paras = [p for p in text.split("\n\n") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) > chunk_chars and cur:
            chunks.append(cur)
            cur = ""
        cur += p + "\n\n"
    if cur.strip():
        chunks.append(cur)
    print(f"[拆解] {len(chunks)} 块")

    fandom = "斗破苍穹"
    all_entries, all_rules = [], {}
    seen = set()
    for i, chunk in enumerate(chunks, 1):
        prompt = PROMPT.format(fandom=fandom, i=i, n=len(chunks), chunk=chunk)
        data = None
        for attempt in (1, 2, 3):
            try:
                # 流式：V4 系思考+长 JSON 输出动辄几分钟，非流式会撞读超时
                parts = []
                client.chat_stream(prompt, system="只输出合法 JSON，不要解释。",
                                   temperature=0.2, phase="worldbook_decompose",
                                   on_chunk=lambda t: parts.append(t))
                out = "".join(parts)
                m = re.search(r"\{.*\}", out, re.S)
                data = json.loads(m.group(0) if m else out)
                if isinstance(data, dict) and "entries" in data:
                    break
            except (LLMError, ValueError) as e:
                print(f"  [chunk {i}] 第{attempt}次解析失败：{e}", flush=True)
                time.sleep(2)
        if not isinstance(data, dict):
            print(f"  [chunk {i}] 放弃该块（连续失败）", flush=True)
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

    # ---- 渲染：世界书.md ----
    by_cat = {}
    for e in all_entries:
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
    project.write_file(os.path.join(proj, project.WORLDBOOK_PATH), "\n".join(doc_lines))

    # ---- 渲染：正则.md ----    规则条目格式：`- 规则：…｜level：must｜scope：全文`
    rx_lines = ["# 正则（原作硬约束）", "",
                "> 来源：原作世界书拆解。must=违反即硬伤，审校与闸门按此对账。", ""]
    for rule, r in all_rules.items():
        level = str(r.get("level", "must")).strip() or "must"
        pat = str(r.get("pattern", "") or "").strip()
        line = "- 规则：%s｜level：%s｜scope：全文" % (rule, level if level in ("must", "should") else "must")
        if pat:
            line += "｜pattern：`%s`" % pat.strip("`")
        rx_lines.append(line)
    project.write_file(os.path.join(proj, project.REGEX_PATH), "\n".join(rx_lines) + "\n")

    # ---- 拆解清单（验证①的对账底册）----
    ledger = {"fandom": fandom, "entries": all_entries,
              "rules": list(all_rules.values()), "chunks": len(chunks)}
    with open(os.path.join(proj, "追踪", "拆解清单.json"), "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
    print(f"[完成] 世界书条目 {n_total} 条 → 世界书.md；硬规则 {len(all_rules)} 条 → 正则.md")
    print(f"[完成] 拆解底册 → 追踪/拆解清单.json")


if __name__ == "__main__":
    main()
