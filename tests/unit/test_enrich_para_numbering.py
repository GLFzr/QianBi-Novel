# -*- coding: utf-8 -*-
"""Q2-a 段落级增厚的段号必须与 span_edit.annotate/apply_spans 同源。

缺陷（2026-10-09 深审 V7）：`_enrich_para_rewrite` 的候选段编号取的是
`prose.split("\\n")` 的**原始行号**，而 `apply_spans` 把 `para` 按**非空行压缩段号**
解释。两个编号空间不同源：目标段前每有一个空行就错位一格。
后果一（实测 3 次）：para 越界 → SpanEditError → 整轮增厚作废（白烧一次调用）；
后果二（静默）：界内时把**别的段落**换成本段的增厚稿，原段内容丢失——
卡级三查用的是 orig（按行号取的那段）做长度/防搬运校验，守卫抓不到这种错位。
"""
import re

import pytest

from app.core import stages


class _Ctx:
    """最小可用 ctx：只带 _enrich_para_rewrite 真实读到的字段。"""

    def __init__(self, proj):
        self.proj = str(proj)
        self.cfg = {"writing": {}}
        self.logs = []
        self.last_prompt = ""

    def log(self, level, msg):
        self.logs.append((level, msg))


class _Session:
    def __init__(self):
        self.enabled = True
        self.turns = 0
        self.committed = []

    def turn_count(self):
        return self.turns

    def rollback_to(self, n):
        self.turns = n

    def commit_turn(self, req, out):
        self.turns += 1
        self.committed.append(out)


# 章标题 + 四个段落，段间空行 ⇒ 压缩段号 1..5，原始行号 1/3/5/7/9
PROSE = "\n\n".join([
    "# 第 1 章 织命司",
    "甲段：陈默把湿透的手账塞进怀里，转身往二楼走。",
    "乙段：灯管闪了一下。",
    "丙段：楼下铁门被风吹得响了三回，他没有回头。",
    "丁段：窗台的薄水泛起涟漪，映出半张陌生的脸。",
])

_THIN = "乙段：灯管闪了一下。"
_THICK = ("乙段：灯管闪了一下，又闪了一下，惨白的光在潮湿的空气里留下断续的"
          "影子。陈默抬头盯着那截忽明忽暗的灯管，听见镇流器发出细碎的嗡嗡声，"
          "像有什么东西在天花板里慢慢挪动。他把手账往肩上提了提，决定等它"
          "彻底灭掉之前先离开这一层。")


def _install_ask_stub(monkeypatch):
    """把模型回复换成「照 req 里点名的段号回一段增厚稿」——真实解析/合并链路不动。"""
    seen = {}

    def _fake_ask(ctx, session, slot, req, label="", phase="", stream=True, **kw):
        seen["req"] = req
        m = re.search(r"⟦P(\d{1,4})⟧\s*" + re.escape(_THIN), req)
        assert m, "para_block 里没找到待增厚段落的编号标记"
        return "⟦P%s⟧ %s" % (m.group(1), _THICK)

    monkeypatch.setattr(stages, "_session_ask", _fake_ask)
    return seen


def test_enrich_para_replaces_the_paragraph_it_showd(tmp_path, monkeypatch):
    """增厚必须落在「展示给模型的那一段」上：本段被替换，其余段逐字保留。"""
    seen = _install_ask_stub(monkeypatch)
    ctx, sess = _Ctx(tmp_path), _Session()

    out = stages._enrich_para_rewrite(ctx, sess, PROSE, gap=150, num=1,
                                      chapter_words=2000)

    assert out, "增厚整轮未生效（logs=%s）" % (ctx.logs[-1] if ctx.logs else "无")
    assert _THICK in out, "模型给的增厚稿没有落进正文"
    # 未点名的段落必须逐字节还在（尤其是与乙段行号相近的那一段）
    for keep in ("甲段：", "丙段：", "丁段：", "# 第 1 章 织命司"):
        assert keep in out, "未点名段落丢失：%s" % keep
    assert _THIN not in out, "被点名的原段没被替换掉"
    assert "⟦" not in out, "编号标记泄漏进落盘正文"


def test_enrich_para_paragraph_number_is_compact(tmp_path, monkeypatch):
    """编号空间纪律：⟦Pnn⟧ 的 n 必须指向「第 n 个非空行」那段文字本身。

    与 span_edit.annotate/apply_spans 同一口径；行号口径会让 n 指向别的段落。
    """
    seen = _install_ask_stub(monkeypatch)
    ctx, sess = _Ctx(tmp_path), _Session()
    stages._enrich_para_rewrite(ctx, sess, PROSE, gap=150, num=1, chapter_words=2000)

    req = seen.get("req", "")
    paras = [ln for ln in PROSE.split("\n") if ln.strip()]   # annotate 的段号空间
    texts = {ln.strip(): ln for ln in paras}
    shown = [(n, t) for n, t in re.findall(r"⟦P(\d{1,4})⟧\s*(.*)", req)
             if t.strip() in texts]     # 模板里的示例占位行（⟦Pnn⟧ <...>）不算
    assert shown, "请求里没有真实段落的编号标记"
    for n, text in shown:
        i = int(n) - 1
        assert 0 <= i < len(paras), "段号 %s 越界（正文共 %d 段）" % (n, len(paras))
        assert paras[i].strip() == text.strip(), (
            "段号 %s 指的是第 %s 段（%r），不是标给它的 %r"
            % (n, n, paras[i][:24], text[:24]))


def test_numbered_paras_is_the_annotate_numbering(tmp_path):
    """span_edit 必须对外提供一个与 annotate/apply_spans 同源的段号视图。

    三处（annotate 进 prompt、apply_spans 落盘、调用方选段）必须共用一个编号空间，
    否则「标给模型的段号」与「实际被改的段」会静默分家——本函数就是这个编号空间
    的唯一真源。
    """
    from app.core import span_edit

    got = span_edit.numbered_paras(PROSE)
    assert [t for _, t in got] == [ln for ln in PROSE.split("\n") if ln.strip()]
    assert [n for n, _ in got] == list(range(1, len(got) + 1))

    # 每个段号 replace 后，被改的必须正好是它自己，其余段落逐字不动
    for no, text in got:
        merged = span_edit.apply_spans(PROSE, [{"op": "replace", "para": no,
                                                "text": "◇"}])
        lines = [ln for ln in merged.split("\n") if ln.strip()]
        assert lines[no - 1] == "◇"
        assert all(l == t for i, (l, t) in enumerate(zip(lines, [ln for ln in PROSE.split("\n") if ln.strip()])) if i != no - 1)


def test_enrich_para_candidates_exclude_heading_but_still_count_it(tmp_path, monkeypatch):
    """候选段跳过标题行，但标题行照样占一个段号（否则后续段号整体前移）。"""
    seen = _install_ask_stub(monkeypatch)
    ctx, sess = _Ctx(tmp_path), _Session()
    stages._enrich_para_rewrite(ctx, sess, PROSE, gap=150, num=1, chapter_words=2000)
    m = re.search(r"⟦P(\d{1,4})⟧\s*" + re.escape(_THIN), seen["req"])
    assert m and int(m.group(1)) == 3, (
        "乙段是第 3 个非空行（标题占 1），实际标号 %s" % (m.group(1) if m else "无"))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
