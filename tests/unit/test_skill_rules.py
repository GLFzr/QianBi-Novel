# -*- coding: utf-8 -*-
"""lieflat-less-ai-tone 集成 Phase 3：loader 单测 + 快照锁（方案 §4 Phase 3.1）。

- loader 行为：正常切片 / frontmatter 剥离 / 规则 8 句子删除 / 标题缺失整体回退 /
  花括号防护 / 交互节（## 用法、## 有风格参考时先读它）绝不进渲染产物（§5 验收
  用断言测试锁死）；
- 渲染产物快照：锁住并集静态段全文（lean 档）——上游 re-vendor 或内置规则改动时
  切片/剥除契约失配会在这里现形（golden 有差异=人工确认后重新生成）；
- deslop.py 规则族清单快照：防止规则表无意识漂移。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.prompts import skill_rules, writing  # noqa: E402

SNAPSHOT_DIR = os.path.join(ROOT, "tests", "snapshots")
UNION_SNAPSHOT = os.path.join(SNAPSHOT_DIR, "lieflat_union_lean.txt")
RULE_FAMILY_SNAPSHOT = os.path.join(SNAPSHOT_DIR, "deslop_rule_families.txt")


@pytest.fixture()
def lieflat_cache():
    state = skill_rules.init_rules_cache({})   # DEFAULT：lieflat + lean
    yield state
    skill_rules.init_rules_cache({})           # 还原进程默认


def _load_raw_skill():
    with open(skill_rules.SKILL_PATH, encoding="utf-8") as f:
        return f.read()


# ---------- loader 行为 ----------

def test_frontmatter_stripped(lieflat_cache):
    suffix = lieflat_cache["skill_suffix"]
    assert "name: lieflat-less-ai-tone" not in suffix
    assert suffix.startswith("## 去 AI 味规则补充")


def test_required_sections_present_and_interactive_dropped(lieflat_cache):
    union = lieflat_cache["union"]
    # 取用的五节
    for anchor in ("硬性边界", "不改的情况", "不作为改写理由",
                   "改写规则", "最终验收"):
        assert anchor in union, f"预期章节缺失：{anchor}"
    # 丢弃的两节——§5 验收：交互节内容不得出现在任何注入 prompt 中
    assert "用户丢一段文字过来" not in union
    assert "有风格参考时先读它" not in union
    assert "风格文档与本规则冲突时" not in union
    assert "先锁定原文框架" not in union


def test_rule8_author_hint_sentence_removed(lieflat_cache):
    union = lieflat_cache["union"]
    assert "提示作者" not in union
    assert skill_rules.RULE8_DROP_SENTENCE not in union
    # 该句所在"不改"段其余内容保留
    assert "原文确实只有概括、没有具体材料时" in union


def test_boundary_adapted_wording(lieflat_cache):
    union = lieflat_cache["union"]
    assert "检出问题清单 / 口头禅黑名单 / 本书正则契约" in union
    # 原始白名单措辞（未适配版）不得残留
    assert "没有命中任何规则的句子必须逐字保留" not in union


def test_title_missing_falls_back_to_builtin(monkeypatch):
    raw = _load_raw_skill()
    broken = raw.replace("## 不作为改写理由", "## 负表")   # 破坏一个预期标题
    real_open = open

    def fake_open(path, *a, **kw):
        if str(path) == skill_rules.SKILL_PATH:
            import io
            return io.StringIO(broken)
        return real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", fake_open)
    state = skill_rules.init_rules_cache({"deslop": {"rules_source": "lieflat"}})
    assert state["mode"] == "builtin"
    assert "标题缺失" in state["reason"] or "缺失" in state["reason"]
    assert state["union"] is None
    # 整体回退：不半截拼接——builtin 切片保持原样
    assert writing.deslop_static_rules() == writing.builtin_deslop_static_rules()


def test_missing_vendor_file_falls_back(monkeypatch):
    monkeypatch.setattr(skill_rules, "SKILL_PATH",
                        os.path.join(skill_rules.VENDOR_DIR, "__no_such__.md"))
    state = skill_rules.init_rules_cache({"deslop": {"rules_source": "lieflat"}})
    assert state["mode"] == "builtin"
    assert state["union"] is None


def test_braces_in_render_fall_back(monkeypatch):
    raw = _load_raw_skill()

    class Braced(str):
        pass

    real_open = open

    def fake_open(path, *a, **kw):
        import io
        if str(path) == skill_rules.SKILL_PATH:
            return io.StringIO(raw.replace("说白了", "说{白}了", 1))
        return real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", fake_open)
    state = skill_rules.init_rules_cache({"deslop": {"rules_source": "lieflat"}})
    assert state["mode"] == "builtin", "渲染产物含花括号必须整体回退（.format 防护）"


def test_full_and_lean_render_modes():
    raw = _load_raw_skill()
    full = skill_rules._render_skill(raw, "full")
    lean = skill_rules._render_skill(raw, "lean")
    assert len(full) > len(lean), "full 档应含 ❌/✅ 示例，体积大于 lean"
    assert "❌" in full and "✅" in full
    assert "❌" not in lean, "lean 档应裁掉示例块"
    # 两档都保留规则实体（触发标记与改法）
    for mode_text in (full, lean):
        assert "翻案腔" in mode_text and "段首零主语评论" in mode_text
        assert "触发标记" in mode_text and "说白了" in mode_text


# ---------- 快照锁 ----------

def test_union_static_segment_snapshot(lieflat_cache):
    """并集静态段快照（lean 档）：切片/剥除契约的 golden。

    重新生成方式：删除 golden 文件后跑一次本测试（写入新模式），人工 diff 确认
    差异只来自预期中的 vendor 更新或内置规则修改，再入库。
    """
    union = writing.deslop_static_rules()
    assert union, "并集静态段为空"
    if not os.path.exists(UNION_SNAPSHOT):
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        with open(UNION_SNAPSHOT, "w", encoding="utf-8", newline="") as f:
            f.write(union)
        pytest.skip("golden 不存在，已写入当前产物——人工 diff 后入库重跑")
    golden = open(UNION_SNAPSHOT, encoding="utf-8").read()
    assert union == golden, (
        "并集静态段与快照不一致——vendor 更新或内置规则改动改变了切片/剥除契约；"
        "确认差异符合预期后删除并重新生成 golden")


def test_deslop_rule_family_snapshot():
    """deslop.py 规则族清单快照：防规则表无意识漂移。"""
    from app import deslop as d
    families = sorted({r.rule for r in d.scan_text(
        "他站在桥头上。" * 40)})   # 任意正文：只取规则 ID 清单
    # 规则常量清点（Phase 2 后的预期全族）
    expected_families = sorted({
        "not-is-comparison", "reverse-not-is", "negation-parade", "voice-contrast",
        "flat-voice", "trailer-ending", "trailer-summary", "fate-summary",
        "em-dash", "daizhe-adverb", "cliche-word", "simile-marker-density",
        "prompting-colon", "dunhao-list-density", "telling-cognition",
        "metaphor-density", "micro-action-tic", "abstract-summary-tic",
        "reasoning-chain", "period-stutter", "long-paragraph", "quote-emphasis",
        "gaze-density", "brake-sentence", "brake-standalone-para", "one-line-para",
        "stamp-para", "mengdi-density",
    })
    # CLICHE 表：比喻标记已移出，剩 8 组
    assert len(d.CLICHE_PATTERNS) == 8, "CLICHE_PATTERNS 数量漂移"
    assert d.CLICHE_SIMILE.pattern == r"仿佛|犹如|宛若|如同"
    golden_path = RULE_FAMILY_SNAPSHOT
    current = "\n".join(expected_families + ["", f"CLICHE_PATTERNS={len(d.CLICHE_PATTERNS)}",
                                             f"scan_rule_ids={'|'.join(sorted(set(families)))}"])
    if not os.path.exists(golden_path):
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        with open(golden_path, "w", encoding="utf-8", newline="") as f:
            f.write(current)
        pytest.skip("golden 不存在，已写入当前规则族——人工确认后入库重跑")
    golden = open(golden_path, encoding="utf-8").read()
    assert current == golden, "deslop 规则族清单漂移（见 tests/snapshots/…）"


# ---------- 契约：剥除/卷级头同源（§5 验收第 2 条的静态面） ----------

def test_union_contract_strip_and_volume_head(lieflat_cache):
    union = writing.deslop_static_rules()
    # 1) 并集在模板里（同源同字节）
    assert union in writing.DESLOP_REWRITE_PROMPT
    # 2) 并集在格式化后的会话轮里（_rewrite_phase 剥除契约）
    import app.prompts as prompts
    kw = dict(findings="F", prose="P", tic_blacklist="T", must_block="M",
              chapter_header="CH", project_header="PH")
    turn = prompts.session_turn_text(writing.DESLOP_REWRITE_PROMPT).format(**kw)
    assert union in turn
    # 3) 标记切片仍完整（模板结构未被拼接破坏）
    assert writing.DESLOP_RULES_MARKER in writing.DESLOP_REWRITE_PROMPT
    assert writing.DESLOP_RULES_END_MARKER in writing.DESLOP_REWRITE_PROMPT
    # 4) 三个模板占位符数量不变（kw 集合不变 ⇒ 无 KeyError）
    for ph in ("{findings}", "{prose}", "{tic_blacklist}", "{must_block}",
               "{project_header}", "{chapter_header}"):
        assert ph in writing.DESLOP_REWRITE_PROMPT
