# -*- coding: utf-8 -*-
"""正则契约的界面级读写（#10）：改一条不能碰坏别的条

设定/正则.md 是作者的书本资产，编辑器的底线是「只动我点的那一条」。
这里全部走真实文件往返，不打桩——格式化与行号区间的一致性本身就是被测对象。
"""
import os

import pytest

from app import project, mustscan


DOC = """## 正则（逻辑约束规则集）

- 规则：突破必须有资源代价，且消耗需有情节来源｜level：must｜scope：修炼/经济
- 规则：不得出现口水词：`仿佛|似乎`｜level：should｜scope：全书
- 规则：现代货币单位不得入文：`￥\\d+`｜level：must｜scope：全书｜mode：forbid
- 规则：已被作者停用的条目｜level：must｜scope：全书｜disabled

- 规则：多行条目首行｜level：must｜scope：主角
  这一行是续行，属于同一条规则
"""


@pytest.fixture
def proj(tmp_path):
    p = str(tmp_path)
    os.makedirs(os.path.join(p, "设定"), exist_ok=True)
    project.write_file(os.path.join(p, project.REGEX_PATH), DOC)
    return p


def _read(p):
    return project.read_file(os.path.join(p, project.REGEX_PATH))


# ---------------------------------------------------------------- 解析与序号

def test_disabled_entry_is_not_indexable(proj):
    rules = project.regex_rules(proj)
    assert [r["level"] for r in rules].count("must") >= 1
    assert not any("已被作者停用" in r["rule"] for r in rules)
    # 界面下标 = 可见条目下标，所以第 4 条（index 3）是多行那条，不是 disabled 那条
    assert "多行条目首行" in rules[3]["rule"]
    assert "续行" in rules[3]["rule"], "多行块应并成一条"


def test_line_spans_cover_continuation_lines(proj):
    rules = project.regex_rules(proj)
    lines = DOC.splitlines()
    for r in rules:
        block = "\n".join(lines[r["line_start"]:r["line_end"] + 1])
        head = r["rule"].split("：", 1)[-1][:6]
        assert head in block, (r["rule"], block)


# ---------------------------------------------------------------- 改一条

def test_update_only_touches_its_own_line(proj):
    before = _read(proj).splitlines()
    assert project.update_regex_rule(proj, 0, rule="突破必须有灵石代价",
                                     level="should", scope="修炼") is True
    after = _read(proj).splitlines()
    assert len(after) == len(before), "改一条不该增删行"
    assert after[2] == "- 规则：突破必须有灵石代价｜level：should｜scope：修炼"
    for i in (0, 1, 3, 4):
        assert after[i] == before[i], f"第{i}行被误改"


def test_update_survives_parse_roundtrip(proj):
    project.update_regex_rule(proj, 2, rule="现代货币不得入文：`￥\\d+`",
                              level="must", scope="全书", mode="forbid")
    r = project.regex_rules(proj)[2]
    assert r["level"] == "must" and r["scope"] == "全书" and r["mode"] == "forbid"
    assert r["pattern"] == r"￥\d+"


def test_update_can_promote_should_to_must(proj):
    """等级是这条契约有没有硬闸门的开关，作者必须改得动"""
    assert project.regex_rules(proj)[1]["level"] == "should"
    project.update_regex_rule(proj, 1, level="must")
    assert project.regex_rules(proj)[1]["level"] == "must"


def test_update_collapses_double_rule_prefix(proj):
    project.update_regex_rule(proj, 0, rule="规则：重复前缀要收敛")
    line = _read(proj).splitlines()[2]
    assert line == "- 规则：重复前缀要收敛｜level：must｜scope：修炼/经济"


def test_update_out_of_range_leaves_file_untouched(proj):
    before = _read(proj)
    assert project.update_regex_rule(proj, 99, rule="x") is False
    assert project.update_regex_rule(proj, -1, rule="x") is False
    assert _read(proj) == before


def test_update_of_multiline_entry_folds_to_one_line(proj):
    before = _read(proj)
    assert project.update_regex_rule(proj, 3, rule="多行条目改完变单行") is True
    after = _read(proj)
    assert "这一行是续行" not in after
    assert len(after.splitlines()) == len(before.splitlines()) - 1


# ---------------------------------------------------------------- 删一条

def test_delete_removes_entry_and_its_continuation(proj):
    rules = project.regex_rules(proj)
    assert project.delete_regex_rule(proj, 3) is True
    left = project.regex_rules(proj)
    assert len(left) == len(rules) - 1
    assert not any("多行条目" in r["rule"] for r in left)
    assert "这一行是续行" not in _read(proj)


def test_delete_keeps_heading_and_siblings(proj):
    before = _read(proj)
    project.delete_regex_rule(proj, 1)
    after = _read(proj)
    assert after.startswith("## 正则")
    assert "突破必须有资源代价" in after
    assert "口水词" not in after
    assert len(after.splitlines()) == len(before.splitlines()) - 1


def test_delete_shifts_indices_consistently(proj):
    """删完之后的下标必须还能继续删——界面就是按下标逐条操作"""
    project.delete_regex_rule(proj, 0)
    project.delete_regex_rule(proj, 0)
    left = project.regex_rules(proj)
    assert [r["rule"] for r in left] == [
        "规则：现代货币单位不得入文：`￥\\d+`", "规则：多行条目首行 这一行是续行，属于同一条规则"]


def test_delete_out_of_range_is_noop(proj):
    before = _read(proj)
    assert project.delete_regex_rule(proj, 42) is False
    assert _read(proj) == before


# ---------------------------------------------------------------- 闸门联动

def test_edited_pattern_takes_effect_in_gate_immediately(proj):
    """改完判定式，下一次锁定预检就得按新规矩来（不能靠重启）"""
    prose = "他把￥3000 拍在桌上。"
    _items, blocking, verdict = mustscan.contract_precheck(proj, 1, prose)
    assert blocking and verdict == "REJECT"
    project.update_regex_rule(proj, 2, rule="不得出现美元金额：`\\$\\d+`")
    _items2, blocking2, _v = mustscan.contract_precheck(proj, 1, prose)
    assert blocking2 == [], "改掉的 pattern 不该再命中"
