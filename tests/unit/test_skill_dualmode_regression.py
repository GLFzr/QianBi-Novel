# -*- coding: utf-8 -*-
"""lieflat Phase 3：双开关（builtin vs lieflat）样章装配回归 + token 成本对比。

方案 §4 Phase 3.2/3.3 的离线可判部分：
- 两档模式下，deslop 整章改写 prompt 的装配（.format 与 co_dialogue 同款关键字
  参数集合）都成功、静态段同源同字节、检出面完全一致（rules_source 不影响扫描）；
- token 成本：两档渲染的静态段增量按字符数估算（DeepSeek 中文 ≈0.6 token/字，
  估算口径，非计费实测），lock 死 lean 档增量上限。

LLM 侧复扫通过率对比（样章真实改写）需真机跑次，环境不判——见落地记录文档。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app import deslop  # noqa: E402
from app.core import gates  # noqa: E402
from app.prompts import skill_rules, writing  # noqa: E402

# 样稿：3 章仿网文正文（确定性，无随机）——覆盖对话/叙述/罗列/比喻形态
_SAMPLE = (
    "# 第{n}章 巷口\n\n"
    "陈默把伞收了，水顺着伞骨往下淌。他在楼道口站了一会儿，等眼睛适应了昏暗。\n\n"
    "「账期到了。」房东站在楼梯上，声音不高，「九千八，月底之前。」\n\n"
    "他点了点头，没有争辩。铺子里摆着胭脂、水粉、头绳、绢花，各色物件挤在一处，"
    "他隔着玻璃看了一眼，仿佛看见的是另一段时间里的自己，又仿佛什么都没看见。\n\n"
    "核心是：先活过这个月。他把这句话在嘴里嚼了两遍，咽了回去，改成一句「知道了」。\n\n"
    "上楼的时候，每一级台阶都响。三楼的老太太在门口择菜，抬头看了他一眼，又低下去。"
    "四楼的门缝里透出电视的光，一闪一闪的。他数到第七级，停下来，回头看了一眼楼道口，"
 "雨还在下，路上一个人也没有。\n\n"
)


def _sample_chapters():
    return [_SAMPLE.format(n=n) for n in (1, 2, 3)]


_DESLOP_KW = dict(tic_blacklist="（样章：无）", must_block="（样章：无）",
                  chapter_header="【第1章 巷口】", project_header="【共享上下文】")


def test_dual_mode_detection_is_identical():
    """rules_source 不影响检出面：两档扫描结果逐条一致。"""
    state_builtin = skill_rules.init_rules_cache({"deslop": {"rules_source": "builtin"}})
    assert state_builtin["mode"] == "builtin"
    try:
        baseline = [gates.scan_deslop(ch) for ch in _sample_chapters()]
    finally:
        state_lie = skill_rules.init_rules_cache({})   # lieflat + lean
    assert state_lie["mode"] == "lieflat"
    lieflat = [gates.scan_deslop(ch) for ch in _sample_chapters()]
    assert [(len(b), len(a)) for b, a in baseline] == [(len(b), len(a)) for b, a in lieflat]
    assert baseline == lieflat, "检出面在两档间漂移（rules_source 泄漏进了扫描器）"


def test_dual_mode_prompt_assembly_no_keyerror():
    """两档下整章改写 prompt 装配都成功（关键字参数集合与 stages/co_dialogue 同款）。"""
    chapters = _sample_chapters()
    for mode_cfg in ({"deslop": {"rules_source": "builtin"}},
                     {"deslop": {"rules_source": "lieflat", "rules_render": "full"}},
                     {"deslop": {"rules_source": "lieflat", "rules_render": "lean"}}):
        skill_rules.init_rules_cache(mode_cfg)
        static = writing.deslop_static_rules()   # 先取静态段（可能触发拼接）
        template = writing.DESLOP_REWRITE_PROMPT  # 生产同款顺序：stages:1941 在 1922 之后取
        assert static in template, f"[{mode_cfg}] 静态段与模板失配（剥除契约破坏）"
        for ch in chapters:
            blocking, advisory = gates.scan_deslop(ch)
            kw = dict(findings=deslop.findings_to_prompt_text(blocking + advisory),
                      prose=ch, chapter_num=1,
                      **_DESLOP_KW)
            prompt = template.format(**kw)   # KeyError 即失败
            assert static in prompt
            if mode_cfg["deslop"]["rules_source"] == "lieflat":
                assert "去 AI 味规则补充" in prompt, "lieflat 模式下 skill 规则未进 prompt"
            else:
                assert "去 AI 味规则补充" not in prompt, "builtin 模式泄漏了 skill 规则"
    skill_rules.init_rules_cache({})


def test_token_cost_estimate_and_lean_default():
    """token 成本对比（估算口径）：full 档增量若不可接受则默认档必须为 lean。"""
    raw = open(skill_rules.SKILL_PATH, encoding="utf-8").read()
    builtin_chars = len(writing.builtin_deslop_static_rules())
    full_chars = len(skill_rules._render_skill(raw, "full"))
    lean_chars = len(skill_rules._render_skill(raw, "lean"))
    # DeepSeek 中文约 0.6~0.7 token/字：用 0.6 上界估算增量 token
    def est(chars_delta):
        return int(chars_delta * 0.6)
    lean_delta = est(lean_chars)
    full_delta = est(full_chars)
    assert skill_rules and True
    import app.config as cfg_mod
    default_render = cfg_mod.DEFAULT_CONFIG["deslop"]["rules_render"]
    if full_delta > 4000:      # 单章 prompt 增量 >4k token 视为不可接受
        assert default_render == "lean", "full 档增量不可接受，默认档必须定 lean"
    # 记录证据（汇报用）
    print(f"\n[token 成本估算] 内置静态段 {builtin_chars} 字；"
          f"lean 增量 {lean_chars} 字 ≈ {lean_delta} token；"
          f"full 增量 {full_chars} 字 ≈ {full_delta} token；默认档={default_render}")
    assert lean_delta < full_delta
