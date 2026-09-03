# -*- coding: utf-8 -*-
"""正则 must 契约：pattern/mode 解析、levels 过滤、mustscan 确定性判定

阶段 1 的范围（零 prompt 注入）：
- project.regex_rules 多带 pattern + mode 两个字段，且既有字段逐字不变
- project.regex_block 新增 levels：默认路径字节级向后兼容，过滤路径整行取舍
- app.mustscan 只判 pattern 非空的规则，三条判定路径（forbid 命中 / require 缺失 /
  不可编译）各有归属级别
"""
import os

from app import mustscan, project


def _make_proj(tmp_path, name="测试书"):
    return project.create_project(str(tmp_path), name)


def _write_rules(proj, body):
    project.write_file(os.path.join(proj, project.REGEX_PATH), body)


# ---------- pattern / mode 解析 ----------

def test_pattern_extracted_from_backticks_and_mode_parsed(tmp_path):
    proj = _make_proj(tmp_path)
    _write_rules(proj, "# 规则集\n"
                       "- 禁止三连感叹：`!{3,}`｜level：must｜scope：全书\n"
                       "- 必须有具体金额：`\\d+元`｜level：must｜mode：require\n")
    rules = project.regex_rules(proj)
    assert [r["pattern"] for r in rules] == ["!{3,}", r"\d+元"]
    # 缺省 forbid：命中即违规，这一侧不会造成假阻断
    assert rules[0]["mode"] == "forbid" and rules[1]["mode"] == "require"
    # mode 标记本身不该混进给人看的规则文本
    assert "mode" not in rules[1]["rule"] and "require" not in rules[1]["rule"]
    # 既有字段保持原语义（pattern/mode 纯属新增）
    assert rules[0]["level"] == "must" and rules[0]["scope"] == "全书"


def test_natural_language_rule_has_empty_pattern(tmp_path):
    """绝大多数 must 是整句话，机器判不了——pattern 必须是空串而非整句"""
    proj = _make_proj(tmp_path)
    _write_rules(proj, "# 规则集\n- 规则：改命必须索回代价｜level：must｜scope：全书\n")
    r = project.regex_rules(proj)[0]
    assert r["pattern"] == ""
    # 拿 rule 文本去 compile 是错的（那是整句话），所以 mustscan 必须直接跳过它
    assert mustscan.check_patterns("他改了一次命。", [r]) == []


# ---------- regex_block：向后兼容 + levels 过滤 ----------

def test_regex_block_default_path_is_byte_identical(tmp_path):
    """levels=None 必须走历史行为（含半句截断）——真实书规则超 1500 字时靠它不漂"""
    proj = _make_proj(tmp_path)
    _write_rules(proj, "# 规则集\n"
                       "- 短规则甲｜level：must｜scope：全书\n"
                       "- 短规则乙｜level：should｜scope：全书\n")
    assert project.regex_block(proj) == project.regex_block(proj, "logic", 1500)
    assert "level: must" in project.regex_block(proj)
    assert "level: should" in project.regex_block(proj)


def test_regex_block_default_truncation_still_mid_line(tmp_path):
    """故意保留历史半句截断：改了就会漂动所有规则超长的真实书基线"""
    proj = _make_proj(tmp_path)
    _write_rules(proj, "# 规则集\n" + "".join(
        "- 规则：很长的约束第%d条%s｜level：must｜scope：全书\n" % (i, "填" * 120)
        for i in range(20)))
    out = project.regex_block(proj, "logic", 300)
    assert out.endswith("…（截断）") and len(out) == 300 + len("…（截断）")


def test_regex_block_levels_filters_and_keeps_whole_lines(tmp_path):
    proj = _make_proj(tmp_path)
    _write_rules(proj, "# 规则集\n"
                       "- 必须保留的甲｜level：must｜scope：全书\n"
                       "- 应当尽量乙｜level：should｜scope：全书\n"
                       "- 必须保留的丙｜level：must｜scope：全书\n")
    only = project.regex_block(proj, "logic", 1500, levels=("must",))
    assert "必须保留的甲" in only and "必须保留的丙" in only
    assert "应当尽量乙" not in only and "should" not in only
    # 过滤路径预算不足时整行取舍，并显式声明漏了几条（绝不给模型半句残规则）
    tight = project.regex_block(proj, "logic", 40, levels=("must",))
    assert "…（截断）" not in tight
    assert "未注入" in tight and "条未注入" in tight
    for line in tight.splitlines():
        assert not line.endswith("（")        # 没有断在词中间的行


def test_regex_block_levels_empty_has_distinct_placeholder(tmp_path):
    proj = _make_proj(tmp_path)
    _write_rules(proj, "# 规则集\n- 全是建议项｜level：should｜scope：全书\n")
    assert "该等级" in project.regex_block(proj, "logic", 1500, levels=("must",))
    # 无规则文件时仍是历史占位（probe_worldbook_format 依赖这句）
    empty = _make_proj(tmp_path / "b", "空书")
    assert "尚未生成正则约束规则集" in project.regex_block(empty)


# ---------- mustscan 三条判定路径 ----------

def _rule(pattern, mode="forbid", rule="示例规则"):
    return {"rule": rule, "level": "must", "scope": "全书",
            "pattern": pattern, "mode": mode}


def test_forbid_hit_is_blocking_with_verifiable_quote():
    fs = mustscan.check_patterns("他走了。!!!然后回头", [_rule("!{3,}")])
    assert len(fs) == 1 and fs[0]["level"] == "blocking"
    assert fs[0]["code"] == "L0-MUST"
    # quote 必须是正文里真实存在的片段，才能被 scan.verify_quote 验真后进修复环
    assert fs[0]["quote"] and fs[0]["quote"] in "他走了。!!!然后回头"


def test_forbid_miss_is_silent():
    assert mustscan.check_patterns("他走了。然后回头", [_rule("!{3,}")]) == []


def test_require_miss_is_advisory_never_blocking():
    """require 判不动只会漏报，绝不该阻断好章节 → 一律 advisory 交 LLM"""
    # \d 只认 ASCII 数字，「三十元」不算命中
    assert mustscan.check_patterns("他付了 30元 就走了", [_rule(r"\d+元", mode="require")]) == []
    miss = mustscan.check_patterns("他付了三十块钱就走了", [_rule(r"\d+元", mode="require")])
    assert len(miss) == 1 and miss[0]["level"] == "advisory"
    assert "未命中" in miss[0]["text"]


def test_uncompilable_pattern_degrades_to_advisory():
    """规则写坏是作者的配置问题，不能变成流水线的阻断"""
    fs = mustscan.check_patterns("任意正文", [_rule("(((", rule="写坏的模式")])
    assert len(fs) == 1 and fs[0]["level"] == "advisory"
    assert "不可编译" in fs[0]["text"]


def test_overlong_pattern_skipped_not_compiled():
    """超长 pattern 多半是写坏了或在灾难性回溯，直接跳过判定"""
    fs = mustscan.check_patterns("正文", [_rule("a" * 500)])
    assert len(fs) == 1 and fs[0]["level"] == "advisory"


def test_scan_proj_reads_book_rules_and_filters_should(tmp_path):
    proj = _make_proj(tmp_path)
    _write_rules(proj, "# 规则集\n"
                       "- 禁止三连感叹：`!{3,}`｜level：must\n"
                       "- 建议少用破折号：`——`｜level：should\n")
    # 默认只看 must：正文里的破折号不该被报出来
    fs = mustscan.scan_proj(proj, "他走了!!!——然后")
    assert len(fs) == 1 and "三连感叹" in fs[0]["text"]
    # 显式要 should 才会命中另一条（should 不参与默认确定性阻断）
    only_should = mustscan.scan_proj(proj, "他走了——", levels=("should",))
    assert len(only_should) == 1 and "破折号" in only_should[0]["text"]


def test_violation_keys_detect_newly_introduced_breach():
    """重写步骤前后比对：只拦「本步新引入」的违规，不背上游的锅"""
    before = mustscan.check_patterns("干净正文", [_rule("!{3,}", rule="甲")])
    after = mustscan.check_patterns("被改坏了!!!", [_rule("!{3,}", rule="甲")])
    assert mustscan.violation_keys(before) == set()
    new = mustscan.violation_keys(after) - mustscan.violation_keys(before)
    assert len(new) == 1


def test_format_must_findings_placeholder_and_whole_lines():
    assert "未发现" in mustscan.format_must_findings([])
    fs = mustscan.check_patterns("!!!", [_rule("!{3,}", rule="禁止三连感叹")])
    block = mustscan.format_must_findings(fs)
    assert "BLOCKING" in block and "L0-MUST" in block and "原文：" in block
    assert not block.rstrip().endswith("（")
