# -*- coding: utf-8 -*-
"""span 级修订输出（v0.20 战役 E1.1 / 优化方向 O1）：修订类相位只回「改动」，不回全文

理论源头：SWE-agent ACI 的最小充分输出纪律（检索只回文件名、编辑只回 diff，
summarized 输出反而 +6pp）与 show-me-the-story 的引用式段落修订（网文界同源实现）。
四个修订类相位（deslop/trim/enrich/review_fix）的本质都是"改局部"——整章重写让
模型把 90% 的输出 token 花在逐字复读没改动的段落上。span 模式把输出契约换成
「段落编号 + 操作 + 新文本」的紧凑 JSON，理论砍这些相位 50-80% 输出。

机制：
  annotate()   给原文每段行首加 ⟦Pnn⟧ 编号标记（进 prompt，不进落盘正文）；
  parse_spans()从模型回复中解析编辑列表（容忍 markdown 围栏/前后噪声）；
  apply_spans()把编辑应用到原文并做健全性校验（任何畸形 → SpanEditError，
               调用方按 E1.1 kill criteria 回退全量模式重试一次）。

设计取舍：
  - 标记用 ⟦⟧（U+27E6/27E7）：中文网文正文与「」引号无碰撞风险，tokenizer 开销
    每段 2-3 token，相比输出侧 50-80% 的节省可忽略；
  - 严格失败语义：段落越界/未知操作/空替换文本一律报错回退，而不是钳位——
    把「模型写错了」伪装成「故意这么改」会污染正文（与 presets._coerce_param 同哲学）；
  - 合并保证「未点名段落逐字节保留」由构造保证（只重写被点名的行），
    调用方原有的健全性守卫（字数闸门/复扫/长度骤减拒绝）全部照旧生效。
"""
import json
import re

# 段落编号标记：⟦P01⟧
_MARK_RE = re.compile(r"⟦P(\d{1,4})⟧")
_MARK_FMT = "⟦P%02d⟧"

# 合法操作（op 白名单；replace/delete 需 para，insert_after 需 para+text）
_OPS = ("replace", "delete", "insert_after")

OUTPUT_CONTRACT = """## 输出契约（span 修订模式——只输出 JSON 编辑列表，禁止输出正文全文）
上方正文中每段行首的 ⟦Pnn⟧ 是段落编号标记（按出现顺序连续编号）。请只输出一个 JSON 数组，
每项一个编辑操作，描述你对正文要做的修改：
  [{"op":"replace","para":3,"text":"该段替换后的完整新文本"},
   {"op":"delete","para":7},
   {"op":"insert_after","para":12,"text":"在该段之后新插入的一段"}]
- replace：把该段整段替换为 text（text 本身不得再带 ⟦⟧ 标记）；
  delete：删除该段；insert_after：在该段之后插入一段新文本
- **只改必要的段落**：没出现在编辑列表里的段落等于逐字保留，不要为了"顺一遍"而全量重写
- 只输出 JSON 数组本身，不要解释、不要 markdown 代码围栏以外的任何文字"""


class SpanEditError(ValueError):
    """span 解析或应用失败（调用方据此回退全量模式）"""


def annotate(prose: str) -> str:
    """给每段（非空行）行首加 ⟦Pnn⟧ 编号；空行原样保留、不编号。

    编号按「非空行出现顺序」连续（P01 起）——正文一行一段是网文惯例，
    标题行（# 第N章 …）同样算一段并持有编号（可被 replace 改章名）。
    """
    out, k = [], 0
    for line in (prose or "").split("\n"):
        if line.strip():
            k += 1
            out.append(_MARK_FMT % k + " " + line)
        else:
            out.append(line)
    return "\n".join(out)


def parse_spans(raw: str) -> list:
    """从模型回复解析编辑列表。

    容忍：markdown 围栏、JSON 前后的解释性文字（取第一个 '[' 到最后一个 ']'）。
    畸形（无 JSON 数组/元素非 dict/op 非法/字段缺失/para 非正整数）→ SpanEditError。
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    l, r = text.find("["), text.rfind("]")
    if l < 0 or r <= l:
        raise SpanEditError("回复中未找到 JSON 数组")
    try:
        data = json.loads(text[l:r + 1])
    except ValueError as e:
        raise SpanEditError("JSON 解析失败：%s" % e)
    if not isinstance(data, list):
        raise SpanEditError("顶层不是数组")
    spans = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise SpanEditError("第 %d 项不是对象" % (i + 1))
        op = str(item.get("op", "")).strip()
        if op not in _OPS:
            raise SpanEditError("第 %d 项 op 非法：%r" % (i + 1, op))
        try:
            para = int(item.get("para"))
        except (TypeError, ValueError):
            raise SpanEditError("第 %d 项 para 缺失或非整数" % (i + 1))
        if para < 1:
            raise SpanEditError("第 %d 项 para=%d 越界（段落编号从 1 起）" % (i + 1, para))
        text_val = item.get("text")
        text_val = "" if text_val is None else str(text_val)
        if op in ("replace", "insert_after") and not text_val.strip():
            raise SpanEditError("第 %d 项 %s 缺 text" % (i + 1, op))
        spans.append({"op": op, "para": para, "text": text_val})
    return spans


def apply_spans(prose: str, spans: list) -> str:
    """把编辑列表应用到原文，返回合并后文本。

    健全性保证（违反任一即 SpanEditError，调用方回退全量）：
      - para 必须落在原文非空行编号范围内；
      - 未被点名的段落逐字节保留（由构造保证）；
      - 替换/插入文本若带 ⟦⟧ 标记则剥掉（防御模型复读标记）。
    同一段落被多次编辑时按列表顺序依次生效（最后一条为准）。
    """
    lines = (prose or "").split("\n")
    idx_of = {}   # 段号 → lines 下标
    k = 0
    for i, line in enumerate(lines):
        if line.strip():
            k += 1
            idx_of[k] = i
    total = k
    for s in spans:
        if s["para"] > total:
            raise SpanEditError("para=%d 越界（正文共 %d 段）" % (s["para"], total))
    for s in spans:
        i = idx_of[s["para"]]
        text = _MARK_RE.sub("", s["text"]).strip()
        if s["op"] == "delete":
            lines[i] = ""
        elif s["op"] == "replace":
            lines[i] = text
        else:   # insert_after
            lines[i] = lines[i] + "\n" + text
    return "\n".join(lines)


def span_stats(prose: str, spans: list) -> dict:
    """编辑统计（诊断/实验记录用）：各操作计数与被点名段号"""
    return {"ops": {op: sum(1 for s in spans if s["op"] == op) for op in _OPS},
            "paras_touched": sorted({s["para"] for s in spans}),
            "total_paras": sum(1 for ln in (prose or "").split("\n") if ln.strip())}


def record_event(proj: str, phase: str, event: str, detail: str = "") -> None:
    """span 修订事件落盘（U1-c，T 轮报告 §9-E：回退率此前无任何落盘计数，
    T4b 的「span 回退率」判据无法从产物读出）。追加 追踪/span_stats.jsonl，
    任何失败静默——纯观测件，绝不影响主流水线。"""
    try:
        import datetime as _dt
        import json as _json
        import os as _os
        d = _os.path.join(proj, "追踪")
        _os.makedirs(d, exist_ok=True)
        rec = {"ts": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "phase": phase, "event": event}
        if detail:
            rec["detail"] = str(detail)[:120]
        with open(_os.path.join(d, "span_stats.jsonl"), "a", encoding="utf-8") as f:
            f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass
