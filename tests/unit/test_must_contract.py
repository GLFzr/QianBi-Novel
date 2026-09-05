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


# ---------- 阶段 3：契约槽接线护栏 ----------

import ast
import string

_APP_ROOT = os.path.join(os.path.dirname(os.path.dirname(  # tests/unit -> repo root
    os.path.dirname(os.path.abspath(__file__)))), "app")

# 会产出/改写正文的五张模板：都必须带 must 契约
CONTRACT_TEMPLATES = ("PROSE_WRITING_PROMPT", "ENRICH_PROMPT", "TRIM_PROMPT",
                      "DESLOP_REWRITE_PROMPT", "SELECTION_REWRITE_PROMPT")


def _template_fields(name):
    from app import prompts
    text = getattr(prompts, name)
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def test_no_prose_template_lacks_must_contract():
    """五张产文模板都不许缺 must 契约——走哪个槽都行，但不能没有

    正文生成走 {regex_block}（全量规则集，含 should），四次整章/整段重写走
    {must_block}（只给 must，那四张已装着整章正文、预算更紧）。
    断言「两条路至少有一条」，才是「没有哪一步在裸写正文」的正确表达。
    """
    from app import prompts
    for name in CONTRACT_TEMPLATES:
        text = getattr(prompts, name)
        assert ("{must_block}" in text or "{regex_block}" in text), \
            "%s 不带任何 must 契约槽，该步在裸写正文" % name
    # 四张重写模板必须走 must 专属槽（它们没有题材块/全量规则块）
    for name in CONTRACT_TEMPLATES[1:]:
        assert "{must_block}" in getattr(prompts, name), name


def _dict_literal_keys(tree):
    """收集模块内 `name = {...字符串键 dict 字面量}` 的键集合（v0.19 章会话
    分支把 kwargs 抽成 dict 后 **var 解包传入，扫描器需解析才看得见字段）"""
    out = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Dict)):
            keys = set()
            for k in node.value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
            out[node.targets[0].id] = keys
    return out


def _format_callsites(template_name):
    """扫遍 app/，抓 `X.<template_name>.format(...)` 的关键字实参集合

    刻意不写死调用点清单：将来谁再加一处调用，这里自动纳入断言。
    test_barrier_removal._smoke_format 是从模板反推字段名再 format，
    看不见「调用方漏传 kwarg」——那正是 KeyError 崩在运行期的成因。
    支持 `format(**kwargs_var)`：var 为同文件中的 dict 字面量时展开其键。
    """
    hits = []
    for dp, dns, fns in os.walk(_APP_ROOT):
        dns[:] = [d for d in dns if d != "__pycache__"]
        for fn in fns:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dp, fn)
            tree = ast.parse(project.read_file(path), filename=path)
            dicts = _dict_literal_keys(tree)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "format"):
                    continue
                recv = node.func.value
                if (isinstance(recv, ast.Attribute)
                        and recv.attr == template_name):
                    kwargs = {kw.arg for kw in node.keywords if kw.arg}
                    for kw in node.keywords:
                        if kw.arg is None and isinstance(kw.value, ast.Name)                                 and kw.value.id in dicts:
                            kwargs |= dicts[kw.value.id]
                    hits.append((os.path.relpath(path, _APP_ROOT), kwargs))
    return hits


def test_every_callsite_passes_every_placeholder():
    """五张模板的每个调用点都必须传满占位符，漏一处就是运行期 KeyError"""
    checked = 0
    for name in CONTRACT_TEMPLATES:
        fields = _template_fields(name)
        sites = _format_callsites(name)
        assert sites, "没找到 %s 的任何调用点，扫描逻辑失效了" % name
        for where, kwargs in sites:
            missing = fields - kwargs
            assert not missing, "%s 在 %s 漏传 %s" % (name, where, sorted(missing))
            checked += 1
    assert checked >= 5, "只核到 %d 处调用点，覆盖面异常" % checked


def test_contract_hit_reaches_review_l0_block(tmp_path):
    """第二层处置：确定性命中必须经 review_l0_block 进终审

    这是流水线 / 修复复审 / 共写手动审校三个入口共用的唯一装配点，
    在这里钉住就等于三处一起钉住。
    """
    from app.core import stages
    proj = _make_proj(tmp_path)
    # 可满足的契约：不追加任何块（避免把「没问题」也写成一段噪声）
    _write_rules(proj, "# 规则集\n- 不得出现「仿佛」：`仿佛`｜level：must｜mode：forbid\n")
    assert "正则 must 契约" not in stages.review_l0_block(proj, 1, "他推门进去，说了 50 元。")
    # require 型契约在本章没有落点：必须作为 advisory 进审校，并点名是哪条
    _write_rules(proj, "# 规则集\n- 每章至少写明一处当票面额：`￥\\d+`｜level：must｜mode：require\n")
    block = stages.review_l0_block(proj, 1, "他推门进去，什么也没写。")
    assert "正则 must 契约" in block and "当票面额" in block
    assert "ADVISORY" in block              # require 判不动只漏报，不阻断


def test_contract_precheck_only_blocks_on_blocking(tmp_path):
    """第三层处置：锁定闸门的 item 形状与「advisory 不拦人」"""
    proj = _make_proj(tmp_path)
    prose = "他推门进去，什么也没写。"
    # 无违规 → 三空元组，调用方直接放行
    _write_rules(proj, "# 规则集\n- 不得出现「仿佛」：`仿佛`｜level：must｜mode：forbid\n")
    assert mustscan.contract_precheck(proj, 1, prose) == ([], [], "")
    # require 缺失只是 advisory：绝不能拦锁定，否则假阻断会把人逼成无脑强锁
    _write_rules(proj, "# 规则集\n- 每章写明当票面额：`￥\\d+`｜level：must｜mode：require\n")
    assert mustscan.contract_precheck(proj, 1, prose) == ([], [], "")
    # forbid 命中才拦，且 item 与审校 v2 同构、带可验真的原文
    _write_rules(proj, "# 规则集\n- 不得出现「仿佛」：`仿佛`｜level：must｜mode：forbid\n")
    items, blocking, verdict = mustscan.contract_precheck(proj, 1, "他仿佛看见父亲。")
    assert verdict == "REJECT" and len(items) == 1 and len(blocking) == 1
    it = items[0]
    assert it["text"].startswith("[正则must]")
    assert it["dim"] and it["level"] == "fail" and it["root_layer"] == "ROOT_REGEX"
    assert it["quote"] and it["quote"] in "他仿佛看见父亲。"