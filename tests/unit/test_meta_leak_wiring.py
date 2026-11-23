# -*- coding: utf-8 -*-
"""生成退化检测必须接上生产，且认得实测真实形态（2026-10-09 深审 断链②）。

两件事，都缺一件都不算修：
  A. `_DEGEN_META_RE` 的词表认不出这轮长跑里真出现的四种自述开场白——
     检测器不是「没接线」这么简单，它对现场形态是**瞎的**；
  B. `degeneration_findings` 与字数双带在 `app/` 里零消费（gates.py:412 注释自陈
     TODO(D-stages)），所以这些自述一路进了落盘正文：
     实测书 `正文/第003章_织命司.md` 第 1 行就是「这是一个针对你提供的文本进行的去AI味改写。」，
     第 6 章开头是「用户要求修改第 6 章正文，解决……」，第 5 章是「好的，以下是第 5 章正文。」
"""
import pytest

from app.core import gates

# 现场样本：逐字取自 tests_output/or_二测_改命笔记/正文/ 的落盘稿
META_3 = """这是一个针对你提供的文本进行的去AI味改写。

**主要修改点：**
1.  **删除所有“不是A，而是B”句式**：将否定句直接转化为肯定描述或动作描写。
2.  **替换禁用词**：“一丝”改为具体动作。

***

# 第 3 章 织命司

雨丝打在二楼窗台的玻璃上，留下一片模糊的水雾。陈默盯着街角那辆黑色轿车。
"""

META_6 = """用户要求修改第 6 章正文，解决“必须覆盖节点缺失”的问题。

查看提供的【原文】（即上一轮生成的第 6 章正文）：
# 第 6 章 黑鸽离顶

雨丝打在二楼窗台的玻璃上。陈默盯着街角那辆黑色轿车。
"""

META_5 = """好的，以下是第 5 章正文。
# 第 5 章 黑鸽离顶

陈默从卫生间转移到二楼窗台时，雨水顺着玻璃滑落。
"""

CLEAN = """# 第 7 章 主理人的裂纹

陈默把湿透的手账塞进怀里，转身往二楼走。
“不是恐惧。”他对自己说，“是别的什么。”
"""

# 第 007 章现场（同书 49 章实测：标题在第 38 行，前 1.5k 字全是「核对过程」自述）
META_7 = """经过仔细核对，您提供的【被处理正文】部分在上下文中显示为“内容缺失”或为空，因此我无法执行针对具体文本的精准改写。

### 检测与修改分析：
1.  **禁用词「一丝」**：原文中未发现“一丝”。

# 第 7 章 主理人的裂纹

陈默把湿透的手账塞进怀里，转身往二楼走。
"""


# ---------- A. 检测器要认得现场形态 ----------

@pytest.mark.parametrize("sample,tag", [
    (META_3, "去AI味改写自述"), (META_6, "用户要求改正文"), (META_5, "以下是第N章正文"),
    (META_7, "核对过程自述（标题在第38行）")])
def test_degeneration_detects_real_meta_openings(sample, tag):
    rules = [f.rule for f in gates.degeneration_findings(sample)]
    assert "degeneration-metaleak" in rules, "%s 没被检测出来：%s" % (tag, rules)


def test_degeneration_does_not_fire_on_clean_chapter():
    rules = [f.rule for f in gates.degeneration_findings(CLEAN)]
    assert "degeneration-metaleak" not in rules, rules


# ---------- B. 定稿前剥掉章标题之前的自述块 ----------

@pytest.mark.parametrize("sample", [META_3, META_6, META_5, META_7])
def test_strip_meta_preamble_keeps_body_and_drops_narration(sample):
    out, stripped = gates.strip_meta_preamble(sample)
    assert stripped is True
    assert out.lstrip().startswith("# 第"), out[:60]
    for gone in ("这是一个针对", "主要修改点", "用户要求修改", "查看提供的", "好的，以下是"):
        assert gone not in out
    assert "***" not in out.split("\n\n")[0]
    # 正文一字不动
    assert "陈默" in out and len(out) > 30


def test_strip_meta_preamble_is_noop_on_clean_chapter():
    out, stripped = gates.strip_meta_preamble(CLEAN)
    assert stripped is False and out == CLEAN


def test_strip_meta_preamble_never_guesses_without_a_heading():
    """认不出章标题就什么都不做——宁可留着可疑文字，也不许删正文。"""
    body = "这一段没有章标题。\n\n“我们改写了正文。”陈默说。\n"
    out, stripped = gates.strip_meta_preamble(body)
    assert stripped is False and out == body


def test_strip_meta_preamble_keeps_epigraph_without_meta_markers():
    """标题前的题记/引文不是模型自述：没有自述特征就不许剥。"""
    body = "“命运不是安排，而是选择。”\n\n# 第 9 章 选择\n\n陈默推开门。\n"
    out, stripped = gates.strip_meta_preamble(body)
    assert stripped is False and out == body


# ---------- C. 定稿落库必须经过这两道 ----------

def test_finalize_calls_cleaner_before_writing_chapter(tmp_path):
    import ast
    import inspect

    src = inspect.getsource(gates)          # 探测器本身必须真有词表（不许空转）
    assert "这是一个针对" in src or "主要修改点" in src, "元话语词表没落进检测器"

    from app.core import stages
    tree = ast.parse(inspect.getsource(stages))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_mc_finalize")
    names = {n.func.attr for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "strip_meta_preamble" in names, "定稿段没调用正文卫生"
    assert "degeneration_findings" in names, "定稿段没跑生成退化检测"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
