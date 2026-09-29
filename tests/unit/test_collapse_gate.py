# -*- coding: utf-8 -*-
"""卡9-P4 本地规则质检（gates.check_collapse / repeat_findings / sensitive_findings）

- 46% 稿触发断流闸（crash 信号）；60% 稿断流闸不触发但 90% 质量闸不达标
  ——两闸语义分离互不联动（原型坑②）
- 整段复读 ≥16 字段落重复 → blocking 附引文；短段复读不报
- 敏感词永远 advisory 只提示不停机；词库缺失 fail-open
全部纯本地零 API。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core import gates

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# ---- 55% 断流闸（与 90% 质量闸语义分离） ----

def test_collapse_triggers_at_46pct():
    """原型金标：1382/3000 = 46% < 55% → crash 信号（凡人问道第2章真实形态）"""
    collapsed, actual = gates.check_collapse("字" * 1382, target=3000)
    assert collapsed is True and actual == 1382


def test_collapse_and_word_gate_independent():
    """90% 质量闸与 55% 断流闸语义分离，绝不合并：
    60% 稿——质量闸不达标（触发扩写），断流闸不触发（不是故障）；
    46% 稿——两闸同时失守，但只有断流闸是停机语义。"""
    low_ok, _high, _ = gates.check_word_bounds("字" * 1800, 3000)     # 60%
    word_ok, _ = gates.check_words("字" * 1800, target=3000)
    collapsed, _ = gates.check_collapse("字" * 1800, target=3000)
    assert low_ok is False and word_ok is False and collapsed is False
    collapsed46, _ = gates.check_collapse("字" * 1382, 3000)
    assert collapsed46 is True
    # 边界：恰好 55%（1649/3000=int(3000*0.55)=1650 下界之下）→ 触发；1650 → 不触发
    assert gates.check_collapse("字" * 1649, 3000)[0] is True
    assert gates.check_collapse("字" * 1650, 3000)[0] is False


# ---- 整段复读 ----

def test_repeat_paragraph_blocking_with_quote():
    para = "他推开门走进屋里，桌上的茶已经凉透了，窗外的雨还在下着没停的意思。"
    filler = "她把伞收好靠在门边，弯腰换鞋的时候听见里屋传来翻动纸页的细碎声响。"
    text = "\n\n".join([para, filler, para, filler2(filler), para])
    fs = gates.repeat_findings(text)
    assert len(fs) == 1
    f = fs[0]
    assert f.rule == "paragraph-repeat" and f.level == "blocking"
    assert f.text == para[:60] and "×3" in f.message


def filler2(filler):
    return filler + "灯芯结出了一朵小小的灯花，爆开时溅了一星火。"


def test_repeat_short_paragraphs_ignored():
    """<16 字段落重复不算（模板占位/对白短句复读是另一族病，归 deslop 规则管）"""
    text = "\n\n".join(["他点头。", "他点头。", "他点头。"])
    assert gates.repeat_findings(text) == []
    assert gates.repeat_findings("") == []


def test_repeat_cap_three_quotes():
    para_a = "甲段内容足够长足够长足够长足够长足够长足够长足够长足够长了。"
    para_b = "乙段内容也足够长也足够长也足够长也足够长也足够长也足够长也足够长。"
    para_c = "丙段内容照样够长照样够长照样够长照样够长照样够长照样够长照样够长。"
    para_d = "丁段内容依旧够长依旧够长依旧够长依旧够长依旧够长依旧够长依旧够长。"
    text = "\n\n".join([para_a, para_b, para_c, para_d,
                        para_a, para_b, para_c, para_d])
    fs = gates.repeat_findings(text)
    assert len(fs) == 3                        # ≤3 条引文上限


# ---- 敏感词（advisory 只提示不停机） ----

def test_sensitive_words_advisory_never_blocking():
    words = gates.load_sensitive_words()       # 真词库随仓走（assets/sensitive_words.txt）
    assert len(words) >= 11
    text = "他在黑市弄到了一支枪支，又从走私船上进了一批毒品。"
    fs = gates.sensitive_findings(text)
    assert fs and all(f.level == "advisory" for f in fs)
    assert all(f.rule == "sensitive-word" for f in fs)
    assert any("枪支" in f.text for f in fs)
    # 命中密度再高也不升级——advisory 是本族的硬性质
    hot = "枪支" * 200
    assert all(f.level == "advisory" for f in gates.sensitive_findings(hot))
    # 干净正文零命中
    assert gates.sensitive_findings("他沿着河堤慢慢走，水面浮着零星的灯光。") == []


def test_sensitive_words_missing_file_fail_open(tmp_path):
    missing = str(tmp_path / "不存在.txt")
    assert gates.load_sensitive_words(missing) == []
    assert gates.sensitive_findings("枪支枪支", words=gates.load_sensitive_words(missing)) == []
    # 显式词表注入（分类可省略）
    fs = gates.sensitive_findings("提到了枪支和炸药", words=[("枪支", "违禁"), ("炸药", "")])
    assert [f.message.split("]")[0] for f in fs] == ["敏感词[违禁", "敏感词[未分类"]


# ---- 质检单聚合 ----

def test_collapse_report_combines_three_rules():
    para = "他推开门走进屋里，桌上的茶已经凉透了，窗外的雨还在下着没停的意思。"
    text = "\n\n".join([para[:20], "字" * 100, para[:20]])     # 短稿（<55% of 3000）
    rep = gates.collapse_report(text, target=3000)
    assert rep["collapsed"] is True and rep["actual"] == gates.project.count_chars(text)
    assert isinstance(rep["repeat"], list) and isinstance(rep["sensitive"], list)
