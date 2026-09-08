# -*- coding: utf-8 -*-
"""装配式卷终交接块（app/core/history_compaction.py）单元测试

覆盖《长程压缩与cheap区间_v1.md》§4.3.1 五条保险丝 + §6.2 触发器 + §6.3 装配路径，
以及《测试接手指南_v1.md》§5 T6 的三项验收（装配正确性 / 保险丝触发与拒绝 /
flag 关闭时字节不变）。全部用 tmp_path 造真实项目家目录（真文件名、真写入路径），
不 mock 文件系统，不触网、零 LLM 调用。
"""
import hashlib
import json
import os

import pytest

from app import project as pj
from app.core import canon_audit
from app.core import history_compaction as hc
from app.core import memory as mem
from app.core.volume_session import VolumeSession, opening_marker

CFG_ON = {"writing": {"compaction": True}}

# 每章正文体量：800 汉字正文 + 唯一收束锚点（近程尾巴必须逐字带上它）
BODY = "雨夜" * 400


@pytest.fixture(autouse=True)
def _isolate_real_usage(tmp_path, monkeypatch):
    """红线：单测绝不读/写用户真实 usage.jsonl——把全局落点指到 tmp 里的不存在文件
    （fake home 下的 usage 由各测试自己写，保险丝④的实测优先路径照测）"""
    from app import usage as usage_mod
    monkeypatch.setattr(usage_mod, "FILE", str(tmp_path / "_no_real_usage.jsonl"))


def _anchor(n: int) -> str:
    return f"第{n}章收束锚点-{n}号刻痕"


class _NoCallClient:
    """open_chapter 只合成文本不发请求——这个替身一旦被调用即测试失败"""

    def chat_turn(self, messages, **kw):   # pragma: no cover
        raise AssertionError("单测不许触网")


# ---------------- 假项目家目录（真实文件名 + 真实落盘路径） ----------------

def _make_home(tmp_path, chapters: int = 8, volumes: str = ""):
    """造 `home/.qianbi_novel/usage/` + `home/书名/{设定,大纲,正文,追踪,会话}` 全树"""
    home = tmp_path / "home"
    proj = home / "长夜灯"
    root = str(proj)
    pj.create_project(str(home), "长夜灯")
    pj.write_file(os.path.join(root, "设定", "题材定位.md"),
                  "# 题材定位\n\n## 核心设定\n都市守夜人，单主角。\n\n"
                  "### 金手指约束条款\n- 每夜只能点一次灯。\n\n"
                  "### 全局红线\n- 不出现真实机构名。\n\n"
                  "### 授权自创清单\n- 「长夜灯」为授权自创物。\n")
    pj.write_file(os.path.join(root, "设定", "正则.md"),
                  "# 正则契约\n\n- 每章至少一个钩子。｜level：must｜scope：全局\n")
    pj.write_file(os.path.join(root, "设定", "世界书.md"),
                  "## 条目\n\n- **守夜人**（身份）：掌灯者。\n  [常驻]\n")
    pj.write_file(os.path.join(root, "大纲", "大纲.md"),
                  volumes or "## 卷级大纲\n\n### 第一卷：边陲（3万字，8章）\n")
    for n in range(1, chapters + 1):
        pj.write_file(pj.get_outline_path(root, n),
                      f"### 第 {n} 章：章节{n}\n- 核心事件：守夜人巡街\n")
        pj.write_file(pj.get_chapter_path(root, n, f"章节{n}"),
                      f"# 第{n}章 章节{n}\n\n{BODY}\n\n{_anchor(n)}。\n")
        mem.append_chapter_summary(root, n, f"章节{n}", f"第{n}章摘要正文")
    mem.write_global_summary(
        root, "全局摘要甲段：守夜人接掌灯之责。锚点标记·全局甲\n\n" +
        "\n\n".join(f"第{i}节：灯下的人换了一茬又一茬，账仍在滚。补叙{BODY[:120]}"
                    for i in range(1, 9)))
    pj.write_file(pj.get_tracking_path(root, "角色状态"),
                  "# 角色状态追踪\n\n" + "".join(
                      f"- 近端状态·青竹第{i}条：值夜三班，灯火未熄，名册与更夫对得上。\n"
                      for i in range(90)) +
                  "- 远端状态·墨痕第三寸：这一行在章头 2000 字截断之外，交接块必须补上。\n")
    pj.write_file(pj.get_tracking_path(root, "时间线"),
                  "# 故事时间线\n\n| 故事内时间 | 章节 | 事件 |\n|---|---|---|\n" +
                  "".join(f"| 第{i}夜 | 第{i}章 | 时间线锚点·乙{i}：守夜人看见第二盏灯，"
                          f"更漏三刻，街尾犬吠 {BODY[:80]}|\n" for i in range(1, 13)))
    pj.write_file(pj.get_tracking_path(root, "伏笔"),
                  "# 伏笔追踪\n\n> 状态：未埋 / 已埋 / 已回收\n\n"
                  "| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |\n"
                  "|------|------|----------|------|----------|------|\n" +
                  "| 伏笔未决·青铜铃 | 道具谜团 | 第2章 | 已埋 | 第20-30章 | 未回收 |\n" +
                  "".join(f"| 伏笔未决·第{i}盏灯 | 道具谜团 | 第{i}章 | 已埋 | 第{i}十章 | "
                          f"灯芯成灰 {BODY[:60]}|\n" for i in range(3, 12)))
    canon_audit.save_ledger(root, {"人物": {"守夜人": {"state": "锚点数字444枚在身", "last_ch": 8}},
                                   "物件": {}, "制度": {}, "时间": []})
    os.makedirs(os.path.join(home, ".qianbi_novel", "usage"), exist_ok=True)
    return str(home), root


def _write_usage(home: str, rows: list):
    path = os.path.join(home, ".qianbi_novel", "usage", "usage.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def _write_session_stack(root: str, volume: int, contents: list, gen: int = 0):
    """卷会话栈落盘（保险丝④字符口径的原料）；gen>0 = 压缩后另起的那一代栈"""
    name = ("卷%d_messages.jsonl" % volume if gen <= 0
            else "卷%d_c%d_messages.jsonl" % (volume, gen))
    path = os.path.join(root, "会话", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    msgs = [{"role": "system", "content": contents[0]}] + [
        {"role": ("user" if i % 2 == 0 else "assistant"), "content": c}
        for i, c in enumerate(contents[1:])]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for m in msgs:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    return path


# ==================== 一、装配正确性 ====================

def test_block_contains_all_required_sections(tmp_path):
    """§6.3 四类原料齐备：近程原文 / 近 3 章摘要 / 全局摘要节 / 台账快照（含连续性台账指针）"""
    _home, proj = _make_home(tmp_path)
    r = hc.build_handoff_block(proj, cfg=CFG_ON, write=False)
    assert r.ok, r.reason
    assert r.flag_on and r.trigger == "manual"
    assert "近程结尾原文（逐字保留" in r.text
    assert "近 3 章摘要" in r.text
    assert "主线进度（全局摘要" in r.text
    assert "台账快照" in r.text
    for name in ("追踪/角色状态.md", "追踪/时间线.md", "追踪/伏笔.md",
                 "追踪/全局摘要.md", "追踪/连续性台账.json"):
        assert name in r.text, f"{name} 必须以文件指针出现在块里（保险丝⑤）"


def test_near_window_endings_verbatim_and_remote_chapters_gone(tmp_path):
    """保险丝②的正面：第 8 章末 800 字 / 第 7 章末 400 字逐字在块内；
    第 6 章及更早的原文不许留在块里（那才是被压缩掉的部分）"""
    _home, proj = _make_home(tmp_path)
    r = hc.build_handoff_block(proj, cfg=CFG_ON, write=False)
    endings = hc.near_endings(proj, 8)
    assert [e.num for e in endings] == [8, 7]
    assert len(endings[0].tail) <= hc.NEAR_TAIL_CHARS[0]
    assert len(endings[1].tail) <= hc.NEAR_TAIL_CHARS[1]
    for e in endings:
        assert e.tail in r.text                       # 严格逐字（非近似）
        assert _anchor(e.num) in r.text
    assert _anchor(6) not in r.text                  # 远程原文已被替换掉
    assert "第8章摘要正文" in r.text and "第6章摘要正文" in r.text
    assert "第5章摘要正文" not in r.text              # 摘要窗口只 3 章


def test_resident_ledger_is_not_restated(tmp_path):
    """保险丝③：章头已常驻注入的行不得复述；常驻截断之外的行必须补上（台账零丢失）"""
    _home, proj = _make_home(tmp_path)
    r = hc.build_handoff_block(proj, cfg=CFG_ON, write=False)
    assert "近端状态·青竹第3条" not in r.text, "章头已注入 → 块里不得重复（#5766 教训）"
    assert "墨痕第三寸" in r.text, "章头 2000 字截断之外的台账尾部必须补进块"
    assert "伏笔未决·青铜铃" not in r.text, "伏笔表常驻注入 → 只给指针不复述"
    assert "锚点标记·全局甲" not in r.text, "全局摘要常驻注入 → 只给指针不复述"
    assert "已全部随章头常驻注入，本块不重复" in r.text
    dropped = {s["label"]: s["dropped_lines"] for s in r.sections["ledger"]["sections"]}
    assert dropped["角色状态"] > 0 and dropped["伏笔"] > 0


def test_exact_anchors_stay_in_ledger(tmp_path):
    """保险丝⑤：块只做叙事记忆——台账 JSON 里的精确锚点以文件指针代替复述"""
    _home, proj = _make_home(tmp_path)
    r = hc.build_handoff_block(proj, cfg=CFG_ON, write=False)
    assert "444" not in r.text
    assert "以台账为准" in r.text and "不复述数值" in r.text


def test_artifacts_written_as_json_and_markdown(tmp_path):
    """§6.2 产物：追踪/交接块_卷N.md + .json 双写，机读面与结果对象一致"""
    _home, proj = _make_home(tmp_path)
    r = hc.build_handoff_block(proj, cfg=CFG_ON, upto=8, volume=1,
                               trigger="volume_boundary")
    md = hc.handoff_md_path(proj, 1)
    js = hc.handoff_json_path(proj, 1)
    assert r.artifacts == (md, js)
    assert md == pj.get_tracking_path(proj, "交接块_卷1")
    assert os.path.basename(js) == "交接块_卷1.json"
    assert pj.read_file(md) == r.text + "\n"
    d = hc.load_handoff(proj, 1)
    assert d["kind"] == hc.ARTIFACT_KIND and d["volume"] == 1
    assert d["text"] == r.text and d["sha256"] == r.sha256
    assert d["to_chapter"] == 8 and d["from_chapter"] == 7
    assert d["trigger"] == "volume_boundary" and d["token_meter"] == r.meter
    assert d["sections"]["near_endings"][0]["num"] == 8


def test_build_is_deterministic_and_write_false_writes_nothing(tmp_path):
    """同一盘态两次装配逐字节一致（sha256 稳定可锁）；write=False 零落盘"""
    _home, proj = _make_home(tmp_path)
    a = hc.build_handoff_block(proj, cfg=CFG_ON, write=False)
    b = hc.build_handoff_block(proj, cfg=CFG_ON, write=False)
    assert a.text == b.text and a.sha256 == b.sha256
    assert a.sha256 == hashlib.sha256(a.text.encode("utf-8")).hexdigest()
    assert a.artifacts == () and b.artifacts == ()
    assert not os.path.exists(hc.handoff_json_path(proj, 1))
    assert not os.path.exists(hc.handoff_md_path(proj, 1))
    assert "2026" not in a.text and "T" not in a.text[:0]   # 块内无时间戳


def test_load_handoff_tolerant_of_missing_and_corrupt(tmp_path):
    """断点续跑读侧：缺失/损坏/kind 不符一律空 dict（绝不抛）"""
    _home, proj = _make_home(tmp_path)
    assert hc.load_handoff(proj, 3) == {}
    js = hc.handoff_json_path(proj, 1)
    pj.write_file(js, "{坏 json")
    assert hc.load_handoff(proj, 1) == {}
    pj.write_file(js, json.dumps({"kind": "别的产物", "text": "x"}, ensure_ascii=False))
    assert hc.load_handoff(proj, 1) == {}


# ==================== 二、五条保险丝的拒绝路径 ====================

def test_fuse1_shrink_check_fails_open(tmp_path):
    """保险丝①：去掉常驻去重后块不再显著更小 → fail-open 返回「未压缩」，不落盘"""
    _home, proj = _make_home(tmp_path)
    r = hc.build_handoff_block(proj, cfg=CFG_ON, write=False, resident_texts=())
    assert not r.ok and r.text == "" and r.artifacts == ()
    assert r.shrunk is False and r.reason.startswith("保险丝①拒绝")
    assert r.tokens > r.replaced_tokens * hc.SHRINK_MAX_RATIO
    assert not os.path.exists(hc.handoff_json_path(proj, 1))


def test_fuse1_shrink_ok_helper():
    """保险丝①内核：无历史可替换（replaced<=0）即拒绝；显著更小才放行"""
    assert hc._shrink_ok(100, 400) is True
    assert hc._shrink_ok(300, 400) is False      # 0.75 > 0.5
    assert hc._shrink_ok(100, 0) is False        # 没东西可压
    assert hc._shrink_ok(0, 0) is False


def test_fuse2_refuses_when_tail_not_verbatim(tmp_path, monkeypatch):
    """保险丝②：装配后校验近程尾巴逐字在场——被裁掉即拒绝（不静默降级）"""
    _home, proj = _make_home(tmp_path)
    monkeypatch.setattr(hc, "render_handoff",
                        lambda volume, upto, endings, summaries, ledger:
                        "## 交接块（尾巴被裁了）\n远程锚点不在这里")
    r = hc.build_handoff_block(proj, cfg=CFG_ON, write=False)
    assert not r.ok and "保险丝②拒绝" in r.reason and "第 8 章结尾原文未逐字保留" in r.reason
    assert r.text == "" and r.artifacts == ()


def test_fuse2_helper_detects_mangled_tail(tmp_path):
    """保险丝②内核：严格子串比对（空白归一不算逐字）"""
    _home, proj = _make_home(tmp_path)
    endings = hc.near_endings(proj, 8)
    block = "前缀" + endings[0].tail + "中间" + endings[1].tail
    assert hc._verbatim_ok(block, endings) == ""
    assert "第 9 章" in hc._verbatim_ok(block, endings + (hc.NearEnding(
        num=9, title="补", tail="缺 一 角 的 尾 巴"),))          # 丢尾巴 → 报章号
    assert "第 8 章" in hc._verbatim_ok(block.replace("雨夜", "雨 夜"), endings)


def test_fuse3_dedup_resident_helper():
    """保险丝③内核：去空白行级比对，命中常驻即剔除并计数"""
    body = "- 甲：已在常驻里\n- 乙：常驻没这条\n\n- 丙：  也已  在常驻里"
    kept, dropped = hc.dedup_resident(body, "……\n- 丙：也已 在常驻里\n- 甲：已在常驻里")
    assert dropped == 2 and kept == "- 乙：常驻没这条"


def test_missing_chapters_refuse_without_history(tmp_path):
    """零章可交 / 只有 1-2 章（没有远程历史可替换）→ 全部 fail-open 拒绝"""
    _home, proj = _make_home(tmp_path, chapters=1)
    r = hc.build_handoff_block(proj, cfg=CFG_ON, write=False)
    assert not r.ok and r.text == ""
    assert "保险丝①" in r.reason or "近程" in r.reason or "没有" in r.reason
    assert hc.build_handoff_block(proj, cfg=CFG_ON, upto=0, write=False).ok is False


# ==================== 三、保险丝④：token 计量走真实 usage ====================

def test_han_caliber_is_repo_caliber_not_four_chars():
    """400 汉字 → 240 tok（0.6/汉字，同 scripts/header_audit.py）；DSH 的 4 字符
    启发式会给出 100——那正是被禁的口径"""
    text = "雨" * 400
    assert hc.han_tokens(text) == 240
    assert hc.han_tokens(text) != len(text) // 4
    assert hc.han_tokens("") == 0 and hc.han_tokens("abc\n# ") == 0


def test_session_input_estimate_prefers_real_usage(tmp_path):
    """触发器②的输入规模优先取 usage.jsonl 的实测 prompt_tokens（会话相位）"""
    home, proj = _make_home(tmp_path)
    _write_session_stack(proj, 1, ["全书前缀" + "雨" * 4000, "开幕轮" + "雪" * 4000])
    _write_usage(home, [{"phase": "prose", "in": 517000, "out": 1500, "hit": 500000},
                        {"phase": "canon_audit", "in": 9999999, "out": 10},
                        {"phase": "", "in": 8888888},
                        "{坏行不炸",
                        {"phase": "tracking", "in": "非数字"}])
    est, meter = hc.session_input_estimate(proj)
    assert est == 517000 and meter == "usage-measured"
    assert hc.real_input_tokens(proj) == 517000
    assert hc.usage_path(proj).endswith(os.path.join(".qianbi_novel", "usage", "usage.jsonl"))


def test_session_input_estimate_falls_back_to_stack_chars(tmp_path):
    """没有实测记录（首次跑/用量被清理）才退字符口径：盘上卷栈全文 × 0.6/汉字"""
    home, proj = _make_home(tmp_path)
    assert hc.usage_rows(proj) == []
    stack = _write_session_stack(proj, 1, ["全书前缀" + "雨" * 1000, "开幕轮" + "雪" * 500])
    est, meter = hc.session_input_estimate(proj)
    assert meter == "han-caliber"
    assert est == hc.han_tokens(pj.read_file(stack))
    # 指定卷号时该卷文件缺失也不炸（回退到最大卷）
    assert hc.session_input_estimate(proj, 7)[0] == est


def test_usage_search_is_depth_bounded(tmp_path):
    """保险丝④的数据卫生：用量落点上溯有层数上限——超出家数层的 usage.jsonl
    （另一本书 / 用户真实控制台）绝不采信；界内的正常找到。"""
    base = tmp_path
    for i in range(hc.MAX_HOME_UPWARD + 1):
        base = base / ("层%d" % i)
    pj.create_project(str(base), "深巢书")
    proj = str(base / "深巢书")
    far_home = str(tmp_path)                                  # 距 proj 超过上限
    _write_usage(far_home, [{"phase": "prose", "in": 7_000_000}])
    assert hc.usage_rows(proj) == []                          # 界外 → 不读
    assert hc.real_input_tokens(proj) == 0
    near_home = base                          # proj 的上一级，远在界限之内
    _write_usage(str(near_home), [{"phase": "prose", "in": 12345}])
    assert hc.usage_path(str(proj)).startswith(str(near_home))
    assert hc.real_input_tokens(proj) == 12345


def test_handoff_result_reports_meter_and_shrink(tmp_path):
    """块自身计量口径 + 收缩账随结果落盘（事后可对账「压缩自身费用=0」）"""
    _home, proj = _make_home(tmp_path)
    r = hc.build_handoff_block(proj, cfg=CFG_ON, write=False)
    assert r.meter == "han-caliber"
    assert r.tokens == hc.han_tokens(r.text) > 0
    assert r.shrunk and 0 < r.shrink_ratio <= hc.SHRINK_MAX_RATIO
    assert r.replaced_tokens == hc.han_tokens(hc.chapter_prose(proj, 1, 8))


# ==================== 四、触发器（§6.2）====================

def test_trigger_volume_boundary(tmp_path):
    """触发器①：大纲卷号切换的那一章触发；卷内章不触发"""
    _home, proj = _make_home(
        tmp_path, chapters=8,
        volumes="## 卷级大纲\n\n### 第一卷：边陲（3万字，8章）\n\n"
                "### 第二卷：长夜（3万字，8章）\n")
    assert hc.resolve_volume(proj, 8) == 1 and hc.resolve_volume(proj, 9) == 2
    t = hc.should_compact(proj, 9, cfg=CFG_ON)
    assert t.fire and t.reason == "volume_boundary" and "卷 2" in t.detail
    assert hc.should_compact(proj, 8, cfg=CFG_ON).fire is False


def test_trigger_input_threshold_boundary(tmp_path):
    """触发器②：估算输入 ≥ 阈值（默认 800k tok）——阈值边界两侧各测一次"""
    _home, proj = _make_home(tmp_path)
    assert hc.token_threshold({}) == hc.DEFAULT_TOKEN_THRESHOLD == 800_000
    cfg = {"writing": {"compaction": True, "compaction_token_threshold": 100_000}}
    assert hc.should_compact(proj, 5, cfg=cfg, input_tokens=100_000).reason == "input_threshold"
    assert hc.should_compact(proj, 5, cfg=cfg, input_tokens=99_999).fire is False
    assert hc.token_threshold({"writing": {"compaction_token_threshold": "坏值"}}) == 800_000


def test_trigger_manual_and_real_usage_reading(tmp_path):
    """触发器③：手动；不传 input_tokens 时读数同样走实测 usage"""
    home, proj = _make_home(tmp_path)
    _write_usage(home, [{"phase": "prose", "in": 900_000}])
    assert hc.should_compact(proj, 5, cfg=CFG_ON, manual=True).reason == "manual"
    assert hc.should_compact(proj, 5, cfg=CFG_ON).reason == "input_threshold"


# ==================== 五、flag 纪律：关闭时字节不变 ====================

def test_flag_off_module_never_intervenes(tmp_path):
    """flag 缺省关：装配拒绝、触发器不燃、开幕块零贡献（连手动请求也不放行）"""
    home, proj = _make_home(tmp_path)
    _write_usage(home, [{"phase": "prose", "in": 5_000_000}])
    assert hc.compaction_enabled({}) is False
    assert hc.compaction_enabled(None) is False
    assert hc.compaction_enabled({"writing": {"compaction": False}}) is False
    r = hc.build_handoff_block(proj, cfg={}, upto=8)
    assert not r.ok and r.flag_on is False and r.text == "" and r.artifacts == ()
    assert "字节不变纪律" in r.reason
    for num in (8, 9):
        assert hc.should_compact(proj, num, cfg={}, manual=True).fire is False
    ob = hc.opening_block(proj, 9, cfg={})
    assert ob.text == "" and ob.contributed is False and ob.tokens == 0
    assert ob.sha256 == hashlib.sha256(b"").hexdigest()
    assert not os.path.exists(hc.handoff_json_path(proj, 1))


def test_flag_off_open_turn_bytes_identical_to_legacy(tmp_path):
    """硬锁：即使盘上已有交接块产物，flag 关闭时 compose_open_turn 的输出必须与
    VolumeSession.open_chapter（今天的实现）逐字节一致——本模块对请求体贡献 0 字节"""
    _home, proj = _make_home(tmp_path)
    written = hc.build_handoff_block(proj, cfg=CFG_ON, upto=8, volume=1)
    assert written.ok and os.path.exists(hc.handoff_json_path(proj, 1))

    header, dyn = "【第 9 章共享上下文】细纲+台账", "## 本章动态值\n- 本章章号：第 9 章"
    legacy = VolumeSession(_NoCallClient(), "SYS", volume=2, proj="").open_chapter(
        header, dyn, chapter_num=9)
    for cfg in ({}, {"writing": {"compaction": False}}):
        mine = hc.compose_open_turn(proj, 9, header, dyn, cfg=cfg)
        assert mine == legacy
        assert mine.encode("utf-8") == legacy.encode("utf-8")     # 字节级
        assert written.text not in mine
    # flag 开：交接块插在章头之前，章头与动态值本身一字未动
    on = hc.compose_open_turn(proj, 9, header, dyn, cfg=CFG_ON)
    assert on.startswith(legacy.split("\n\n")[0] + "\n\n" + written.text + "\n\n" + header)
    assert on.endswith(dyn) and legacy.endswith(dyn)


def test_flag_on_opening_block_reads_previous_volume(tmp_path):
    """接回路径：卷界的开幕块 = 上一卷交接块（旗标开、产物缺失时幂等装配一次并落盘，
    之后每次读盘——同一 sha256，崩溃续跑不重复装配）"""
    _home, proj = _make_home(
        tmp_path, chapters=8,
        volumes="## 卷级大纲\n\n### 第一卷：边陲（3万字，8章）\n\n"
                "### 第二卷：长夜（3万字，8章）\n")
    assert hc.opening_block(proj, 1, cfg=CFG_ON).contributed is False   # 首卷首章无历史
    assert hc.load_handoff(proj, 1) == {}
    first = hc.opening_block(proj, 9, cfg=CFG_ON)
    assert first.contributed and first.reason.startswith("assembled:")
    assert os.path.exists(hc.handoff_json_path(proj, 1))
    again = hc.opening_block(proj, 9, cfg=CFG_ON)
    assert again.reason == "handoff_卷1"
    assert again.text == first.text and again.sha256 == first.sha256
    assert again.sha256 == hc.load_handoff(proj, 1)["sha256"]
    built = hc.build_handoff_block(proj, cfg=CFG_ON, upto=8, volume=1,
                                   trigger="volume_boundary")
    assert again.text == built.text and again.tokens == built.tokens


def test_wiring_via_open_chapter_prepend_is_byte_equivalent(tmp_path):
    """接线等价性：stages 只需一行改动（把交接块作为章头前缀喂给 open_chapter），
    得到的开幕轮与 compose_open_turn 逐字节一致；flag 关时前缀为空串 = 现状字节。"""
    _home, proj = _make_home(tmp_path)
    built = hc.build_handoff_block(proj, cfg=CFG_ON, upto=8, volume=1)
    header, dyn = "【第 9 章共享上下文】细纲+台账", "## 本章动态值"
    wired = VolumeSession(_NoCallClient(), "SYS", proj="").open_chapter(
        built.text + "\n\n" + header, dyn, chapter_num=9)
    assert wired.encode("utf-8") == hc.compose_open_turn(
        proj, 9, header, dyn, cfg=CFG_ON).encode("utf-8")
    # flag 关：前缀空串 → 与今天的调用逐字节一致（同一行代码，两种旗标态）
    off = hc.opening_block(proj, 9, cfg={})
    legacy = VolumeSession(_NoCallClient(), "SYS", proj="").open_chapter(
        (off.text + "\n\n" + header) if off.text else header, dyn, chapter_num=9)
    assert legacy.encode("utf-8") == VolumeSession(
        _NoCallClient(), "SYS", proj="").open_chapter(header, dyn, 9).encode("utf-8")


def test_flag_not_registered_in_config_defaults(tmp_path):
    """T6 flag 纪律：`writing.compaction` 既没写进 config 默认表也没进任何注册表——
    不显式打开就永远是关"""
    from app import config as cfg_mod
    assert "compaction" not in cfg_mod.DEFAULT_CONFIG.get("writing", {})
    assert hc.compaction_enabled(cfg_mod.DEFAULT_CONFIG) is False
    assert hc.compaction_enabled({"writing": dict(cfg_mod.DEFAULT_CONFIG["writing"])}) is False


def test_public_api_surface_is_small():
    """库的定位：无 CLI / 无 UI / 不进注册表——公开面就是这些"""
    public = {n for n in dir(hc) if not n.startswith("_")}
    assert {"should_compact", "build_handoff_block", "opening_block",
            "compose_open_turn", "load_handoff", "save_handoff", "session_input_estimate",
            "han_tokens", "real_input_tokens", "compaction_enabled",
            "handoff_md_path", "handoff_json_path"} <= public
    assert "main" not in public and not hasattr(hc, "cli")
    assert "argparse" not in dir(hc) and "PySide6" not in str(hc.__loader__)


def test_trigger_reads_live_context_not_whole_run_max(tmp_path):
    """接线回归（stages._compaction_step 的点火前提）：触发器②必须看**最近一笔**
    实测输入。整跑最大单笔在压缩后仍停在压缩前的规模，拿它当口径会让新栈刚建好
    就再次点火——每章重置一次，压缩反而把缓存域切碎（比不压更贵）。"""
    home, proj = _make_home(tmp_path)
    _write_usage(home, [{"phase": "prose", "in": 900000},        # 压缩前
                        {"phase": "prose", "in": 30000}])        # 压缩后新栈的首轮
    assert hc.real_input_tokens(proj) == 30000
    assert hc.real_input_tokens(proj, last=False) == 900000
    est, meter = hc.session_input_estimate(proj)
    assert (est, meter) == (30000, "usage-measured")
    cfg = {"writing": {"compaction": True, "compaction_token_threshold": 800000}}
    assert hc.should_compact(proj, 21, cfg=cfg).fire is False


def test_stack_text_follows_newest_generation(tmp_path):
    """字符口径同样要跟代次走：压缩后的"当前会话"是 卷N_cK，不是被弃用的原始栈"""
    home, proj = _make_home(tmp_path)
    _write_session_stack(proj, 1, ["甲" * 4000])                  # 卷1（压缩前）
    _write_session_stack(proj, 1, ["乙" * 40], gen=2)             # 卷1_c2（最新代）
    assert hc._session_stack_text(proj, 1).startswith("乙")
    assert hc._session_stack_text(proj, 1, gen=0).startswith("甲")
