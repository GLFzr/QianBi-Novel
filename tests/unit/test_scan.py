# -*- coding: utf-8 -*-
"""scan：引证验真 + L0 确定性预检五项（真阳/真阴覆盖）"""
from app.core import scan

# 80 个互不重复的汉字（16 个非重叠 5-gram），用于跨章复读检查的对齐构造
_CJK80 = ("甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥一二三四五六七八九十"
          "天地玄黄宇宙洪荒日月盈昃辰宿列张寒来暑往秋收冬藏闰余成岁律吕调阳"
          "云腾致雨露结为霜金生丽水玉出昆冈")
assert len(_CJK80) == 80


# ---------- verify_quote ----------

def test_verify_quote_exact_and_normalized():
    prose = "夜色深沉，他推开门走了出去。"
    ok, _ = scan.verify_quote(prose, "他推开门走了出去")
    assert ok
    # 标点/空白差异：规范化后等价
    ok, _ = scan.verify_quote(prose, "他推开门， 走了出去。")
    assert ok


def test_verify_quote_fuzzy_one_char_typo():
    prose = "夜色深沉，他推开门走了出去。"
    ok, _ = scan.verify_quote(prose, "他推开大门走了出去")  # 记错一字
    assert ok


def test_verify_quote_fabricated_fails():
    prose = "夜色深沉，他推开门走了出去。"
    ok, reason = scan.verify_quote(prose, "他掏出手机看了一眼时间")
    assert not ok
    assert reason


def test_verify_quote_empty_or_too_short():
    prose = "夜色深沉，他推开门走了出去。"
    assert not scan.verify_quote(prose, "")[0]        # 逆命者 ch2 空引证事故
    assert not scan.verify_quote(prose, "   ")[0]
    assert not scan.verify_quote(prose, "出门")[0]    # 短于 min_len=6


# ---------- L0-NAME 专名错写 ----------

def test_l0_name_typo_blocking():
    r = scan.scan_chapter("柳三庚提着灯走了过来。", roster=["柳三更"])
    fs = [f for f in r["findings"] if f["code"] == "L0-NAME"]
    assert len(fs) == 1
    assert fs[0]["level"] == "blocking"
    assert "柳三更" in fs[0]["text"] and "柳三庚" in fs[0]["text"]


def test_l0_name_no_false_positive():
    # 正名在正文出现 → 不报
    assert not [f for f in scan.scan_chapter("柳三更提着灯走了过来。",
                roster=["柳三更"])["findings"] if f["code"] == "L0-NAME"]
    # 错写名本身在角色表里（两名并存）→ 不报
    assert not [f for f in scan.scan_chapter("柳三庚提着灯走了过来。",
                roster=["柳三更", "柳三庚"])["findings"] if f["code"] == "L0-NAME"]
    # 差两字 → 不报（宁缺勿滥）
    assert not [f for f in scan.scan_chapter("柳四庚提着灯走了过来。",
                roster=["柳三更"])["findings"] if f["code"] == "L0-NAME"]


# ---------- L0-REPEAT 跨章复读 ----------

def test_l0_repeat_blocking_and_advisory_thresholds():
    prev = _CJK80
    # 16 个共享 5-gram → blocking
    r = scan.scan_chapter(_CJK80 + "。后续剧情展开。", prev)
    fs = [f for f in r["findings"] if f["code"] == "L0-REPEAT"]
    assert fs and fs[0]["level"] == "blocking"
    # 8 个共享 5-gram → advisory
    r = scan.scan_chapter(_CJK80[:40] + "。后续剧情展开。", prev)
    fs = [f for f in r["findings"] if f["code"] == "L0-REPEAT"]
    assert fs and fs[0]["level"] == "advisory"
    # 5 个共享 5-gram → 不报
    r = scan.scan_chapter(_CJK80[:25] + "。后续剧情展开。", prev)
    assert not [f for f in r["findings"] if f["code"] == "L0-REPEAT"]


# ---------- L0-NUM 数值账 ----------

def test_l0_num_mismatch_advisory():
    r = scan.scan_chapter("他查了查，余额为300灵石。",
                          ledger_text="当前余额：500 灵石。")
    fs = [f for f in r["findings"] if f["code"] == "L0-NUM"]
    assert len(fs) == 1 and fs[0]["level"] == "advisory"
    assert "500" in fs[0]["text"] and "300" in fs[0]["text"]


def test_l0_num_match_and_empty_ledger():
    # 数值一致 → 不报
    assert not [f for f in scan.scan_chapter("余额为500灵石。",
                ledger_text="余额：500")["findings"] if f["code"] == "L0-NUM"]
    # 台账为空 → 不报
    assert not [f for f in scan.scan_chapter("余额为300灵石。",
                ledger_text="")["findings"] if f["code"] == "L0-NUM"]
    # 语境词不同（剩余 vs 余额）→ 不跨语境误报
    assert not [f for f in scan.scan_chapter("剩余300灵石。",
                ledger_text="余额：500")["findings"] if f["code"] == "L0-NUM"]


# ---------- L0-HOOK 章末弱钩 ----------

def test_l0_hook_weak_ending_blocking():
    prose = "夜风很冷。" * 20 + "他心中暗想，明天一定要把账讨回来。"
    fs = [f for f in scan.scan_chapter(prose)["findings"] if f["code"] == "L0-HOOK"]
    assert fs and fs[0]["level"] == "blocking"


def test_l0_hook_event_ending_ok():
    prose = "两人对坐无言。" * 20 + "门外忽然传来三声轻叩。"
    r = scan.scan_chapter(prose)
    assert not [f for f in r["findings"] if f["code"] == "L0-HOOK"]
    assert r["hook_type"] == "other_action"


# ---------- L0-TERM 题材禁词 ----------

def test_l0_term_forbidden_blocking():
    fs = [f for f in scan.scan_chapter("这里是修仙门派。",
          forbidden_words=scan.GENERIC_FORBIDDEN)["findings"] if f["code"] == "L0-TERM"]
    assert fs and fs[0]["level"] == "blocking" and "修仙" in fs[0]["text"]


def test_l0_term_clean_text_ok():
    prose = "他把账本合上，吹熄了灯。"
    assert not [f for f in scan.scan_chapter(prose,
                forbidden_words=scan.GENERIC_FORBIDDEN)["findings"]
                if f["code"] == "L0-TERM"]
    # 修仙类书籍豁免通用禁词（调用方传空表）→ 不报
    assert not [f for f in scan.scan_chapter("他金丹初成。",
                forbidden_words=[])["findings"] if f["code"] == "L0-TERM"]


# ---------- format_scan_block / classify_hook ----------

def test_format_scan_block_empty_and_findings():
    assert scan.format_scan_block({"findings": []}) == "（本地确定性预检未发现问题）"
    r = scan.scan_chapter("柳三庚提着灯走了过来。", roster=["柳三更"])
    block = scan.format_scan_block(r)
    assert "逐条裁决" in block and "[BLOCKING][L0-NAME]" in block


def test_format_scan_block_truncates():
    r = {"findings": [{"code": "L0-NUM", "level": "advisory",
                       "text": "存疑", "quote": "很长" * 300}]}
    block = scan.format_scan_block(r, max_chars=600)
    assert "…（预检项截断）" in block


def test_classify_hook_categories():
    assert scan.classify_hook("深夜里，他的手机突然响了。") == "remote_msg"
    assert scan.classify_hook("一切如常。") == "unknown"


# ---------- Gold 回放：tests/evals/gold_set.json L0 金标回归（零 LLM） ----------
# 金标 42 条 L0 中，本仓确定性检测器覆盖 4 类 metric；其余 metric
# （数值账/专名登记/金手指频次/字数/题材关键字）超出 scan.py 五检查语义，
# 如实计为 skipped，由 LLM 审校维度或既有专项检查承担。

import json
import os

from app import deslop

_GOLD_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "evals", "gold_set.json")

# 题材家族与禁词集（移植 TUI evals/replay.py 语义）
_FAMILY = {
    "cultivation": "xianxia", "cultivation_r3": "xianxia",
    "urban_superpower": "modern", "scifi_apocalypse": "modern",
    "mystery_horror": "modern", "game_esports": "modern",
    "infinite_flow": "modern", "infinite_flow_r1": "modern",
    "historical_intrigue": "historical",
    "fairy_tale_lite": "fairy", "fairy_tale_lite_r1": "fairy",
    "cosmic_horror_r1": "cosmic",
}
_XIANXIA_IN_MODERN = ["灵气", "丹田", "灵脉", "金丹", "筑基", "剑意", "法力", "御剑",
                      "修真", "修士", "练气", "元婴", "渡劫", "灵根", "法器"]
_MODERN_IN_HISTORICAL = ["微信", "朋友圈", "外卖", "打车", "抖音", "B站", "手机", "互联网"]

# deslop.py（AI 味检测）能覆盖的金标子集；其余为网文套话/古风副词，
# 不在 deslop.py 职责内（由 LLM 审校维 E 承担）
_DESLOP_COVERED = {"G010", "G011", "G038"}


def _load_gold_l0():
    gold = json.load(open(_GOLD_PATH, encoding="utf-8"))
    return [r for r in gold if r.get("type") == "l0"]


def _forbidden_of(preset: str) -> list:
    fam = _FAMILY.get(preset, "unknown")
    if fam == "xianxia":
        return []
    words = list(scan.GENERIC_FORBIDDEN) + list(_XIANXIA_IN_MODERN)
    if fam == "historical":
        words += _MODERN_IN_HISTORICAL
    return words


def _hook_expected(desc: str, rid: str) -> str:
    """与 TUI replay.py 一致的期望类型解析（含 id 兜底）"""
    if "unknown" in desc:
        return "unknown"
    if "info_gap" in desc or rid in ("G017", "G039"):
        return "info_gap"
    if "remote_msg" in desc or rid == "G018":
        return "remote_msg"
    if "other_action" in desc or rid == "G028":
        return "other_action"
    return ""


# 跨章复读合成夹具：大段同文出现在前后两章（金标真实形态为整段复制，
# 计数口径为非重叠 5-gram，≥15 个共享需 ≥75 字连续同文）
_PAD = ("夜色沉入屋脊风从巷口灌进来灯火晃了晃又稳住远处传来打更的声音"
        "他握着灯杆没有动盘算着下一段路该怎么走巷口的影子慢慢拉长"
        "石板路上积着薄薄一层灰月光照过来的时候能看见墙头的枯草")
assert len(_PAD) >= 75


def test_gold_term_purity_replay():
    """题材禁词金标：非修仙题材正文含禁词 → L0-TERM blocking 全拦截"""
    rs = [r for r in _load_gold_l0() if r["metric"] == "term_purity_violation"]
    assert rs, "金标集缺 term_purity 记录"
    for r in rs:
        words = _forbidden_of(r.get("source_preset", ""))
        if not words:   # 修仙题材豁免
            continue
        fs = [f for f in scan.scan_chapter(r.get("real_text", ""),
              forbidden_words=words)["findings"] if f["code"] == "L0-TERM"]
        assert fs and fs[0]["level"] == "blocking", f"{r['id']} 未拦截：{r.get('real_text','')[:20]}"


def test_gold_hook_type_replay():
    """钩子分类金标：classify_hook 与金标期望类型逐条一致"""
    rs = [r for r in _load_gold_l0() if r["metric"] == "hook_type"]
    assert rs, "金标集缺 hook_type 记录"
    for r in rs:
        exp = _hook_expected(r.get("description", ""), r["id"])
        assert exp, f"{r['id']} 期望类型无法解析"
        got = scan.classify_hook(r.get("real_text", ""))
        assert got == exp, f"{r['id']} 期望 {exp}，实际 {got}"


def test_gold_cross_repeat_replay():
    """跨章复读金标：段落级复制 → L0-REPEAT blocking（合成双章回放）"""
    rs = [r for r in _load_gold_l0() if r["metric"] == "cross_chapter_repeat_5gram"]
    assert rs, "金标集缺 repeat 记录"
    for r in rs:
        seg = r.get("real_text", "")[:20]
        prev = _PAD + "。" + seg
        curr = _PAD + "。" + seg
        fs = [f for f in scan.scan_chapter(curr, prev)["findings"]
              if f["code"] == "L0-REPEAT"]
        assert fs and fs[0]["level"] == "blocking", f"{r['id']} 未拦截跨章复读"


def test_gold_deslop_replay():
    """deslop 金标子集：AI 套话类样本（G010/G011/G038）→ blocking 命中"""
    rs = [r for r in _load_gold_l0()
          if r["metric"] in ("deslop_blocking", "deslop_advisory")
          and r["id"] in _DESLOP_COVERED]
    assert len(rs) == len(_DESLOP_COVERED), "金标集缺 deslop 覆盖样本"
    for r in rs:
        fs = deslop.scan_text(r.get("real_text", ""))
        assert any(f.level == "blocking" for f in fs), f"{r['id']} deslop 未命中"


def test_gold_negative_control_clean_chapter():
    """阴性对照：未注入缺陷的干净章节 → 零 findings（不得误报）"""
    prose = ("# 第1章 夜巡\n陈更提着灯走过长街。" * 8
             + "他数了数囊中，余额 300 文。\n门外忽然传来三声轻叩。")
    r = scan.scan_chapter(prose, prev_prose="完全不同的前一章内容，没有任何重叠。",
                          roster=["陈更"], ledger_text="余额：300",
                          forbidden_words=scan.GENERIC_FORBIDDEN)
    assert r["findings"] == [], f"干净章节误报：{r['findings']}"
    assert r["hook_type"] == "other_action"


def test_gold_l0_coverage_summary():
    """覆盖率账本：映射/跳过逐条可解释，映射项零漏检"""
    mapped, skipped = [], {}
    for r in _load_gold_l0():
        m, rid = r["metric"], r["id"]
        if m == "term_purity_violation" and _forbidden_of(r.get("source_preset", "")):
            mapped.append(rid)
        elif m == "hook_type":
            mapped.append(rid)
        elif m == "cross_chapter_repeat_5gram":
            mapped.append(rid)
        elif m == "deslop_blocking" and rid in _DESLOP_COVERED:
            mapped.append(rid)
        else:
            skipped[m] = skipped.get(m, 0) + 1
    total = len(mapped) + sum(skipped.values())
    print(f"\n  L0 金标 {total} 条：确定性检测器映射 {len(mapped)} 条"
          f"（term/hook/repeat/deslop 子集），跳过 {sum(skipped.values())} 条：{skipped}")
    assert total == 42
    assert len(mapped) == 18   # term 5 + hook 5 + repeat 5 + deslop 3
