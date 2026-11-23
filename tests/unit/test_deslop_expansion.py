# -*- coding: utf-8 -*-
"""C16b/C1a deslop 增量规则测试（28→45：oh-story 11 条 + humanizer 6 直命中/lieflat 实测 6 条）

- 每条新规则至少一正一反断言
- 合成毒文本（全套 45 规则投料）命中率 ≥90%
- 语料校准回归钉：7 书×前 100 章真人语料人工判定的误报类（拟声连发/对话标签/
  连词不断·不同/4 项枚举/补语尾/骈文对仗/台词内清单/定语「即将开始的」）全部不报
- 新规则必须登记 REVIEW_AXIS 二轴（fail-loud 的测试面）
全部纯本地零 API。校准数据与调参记录见 0.20.3 工作报告 P4 节。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app import deslop
from app.core import deslop_metrics

_NEW_RULES = [
    "negation-pair-tic", "stock-reaction-tic", "action-list-tic",
    "system-notice-formality-tic", "overcompressed-prose-tic",
    "low-connective-density-tic", "formulaic-parallelism", "cliche-density-tic",
    "forced-triad", "sentence-opening-run", "idealized-persona-simile",
    "adjacent-sentence-isomorph", "zero-subject-comment", "vague-rider",
    "closer-recap-tic", "sendoff-para", "recap-opening",
]


def _rules(findings, level=None):
    return {f.rule for f in findings if level is None or f.level == level}


# ---------- 1) negation-pair-tic ----------

def test_negation_pair_tic_pos_and_neg():
    pos = deslop.scan_text("他不哭，也不闹。屋子里没有门，也没有窗。她不问，也不躲，只是坐着。"
                           + "他沿着河堤慢慢走，水面浮着零星的灯光。" * 3)
    assert "negation-pair-tic" in _rules(pos)
    # 补语尾「V不X，也…」（救不了/砸不了）是语法连接不是修辞对偶——真人语料校准
    neg = deslop.scan_text("就算救不了，也不算砸不了招牌。就算输不了，也不算赢。"
                           "就算等不到，也不算白来。他沿着河堤慢慢走。")
    assert "negation-pair-tic" not in _rules(neg)


# ---------- 2) stock-reaction-tic ----------

def test_stock_reaction_tic_pos_and_neg():
    pos = deslop.scan_text("他的指尖微微一颤。她的指节攥得泛白。他喉结滚动了一下。"
                           "她眼眶发红，抿了抿唇。他声音放轻，像是在宣判。"
                           "他胸口像被撞了一下。她肩膀轻轻一颤。" + "夜色沿着河堤漫开。" * 20)
    assert "stock-reaction-tic" in _rules(pos)
    neg = deslop.scan_text("他的指尖微微一颤，随即按住了刀柄。夜色沿着河堤漫开，远处有灯火。")
    assert "stock-reaction-tic" not in _rules(neg)


# ---------- 3) action-list-tic ----------

def test_action_list_tic_pos_and_neg():
    pos = deslop.scan_text("他伸手抓起刀，转身踢开门，回头喊了一声，抬手挥刀，放下酒碗，"
                           "坐下喘气，看向门口，盯住来人。")
    assert "action-list-tic" in _rules(pos)
    neg = deslop.scan_text("他伸手抓起刀，转身踢开门，回头喊了一声，抬手挥刀。")
    assert "action-list-tic" not in _rules(neg)


# ---------- 4) system-notice-formality-tic ----------

def test_system_notice_formality_pos_and_neg():
    pos = deslop.scan_text("【访客不得进入内区】\n【违规者必须接受惩罚】\n"
                           "【禁止在公共区域喧哗，维持秩序】\n【任务失败将被视为违约】\n"
                           "【所有指令必须严格执行，同样计入考核】\n夜色深了。")
    assert "system-notice-formality-tic" in _rules(pos)
    neg = deslop.scan_text("【任务失败将被视为违约】\n夜色深了，他合上手里的册子。")
    assert "system-notice-formality-tic" not in _rules(neg)


# ---------- 5) overcompressed-prose-tic ----------

_TERSE_SHORTS = ["他推门。", "灯亮。", "茶凉。", "风停。", "夜深。", "人散。",
                 "刀出鞘，马蹄近。", "雪落无声。", "灯灭。", "他扫弦。"]
_TERSE_LONG = ("山道盘桓，直上北岭，岭上积雪未消，寒气逼人，行至半途，天色渐暗，"
               "远处灯火三两，近处虫声断续，再往上走，风声渐紧，树影摇晃如追兵。")
# ≥1200 可见字且 ≥45 段且短段 ≥58% 且自然连接 <85/千字，同时 ≥30 字承接句 <8%
# （_visible_len 只数汉字/字母不含标点，投放量按可见字口径放大）
_TERSE_TEXT = "\n".join(_TERSE_SHORTS * 24 + [_TERSE_LONG] * 10)


def test_overcompressed_prose_pos_and_neg():
    assert "overcompressed-prose-tic" in _rules(deslop.scan_text(_TERSE_TEXT))
    neg = deslop.scan_text("他沿着河堤慢慢走，水面浮着零星的灯光，远处偶尔传来一声船笛，"
                           "风把凉意送到领口里。" * 20)
    assert "overcompressed-prose-tic" not in _rules(neg)


# ---------- 6) low-connective-density-tic ----------

def test_low_connective_density_pos_and_neg():
    # 电报体：功能词/白话连接极低且无 ≥30 字承接句
    assert "low-connective-density-tic" in _rules(deslop.scan_text(_TERSE_TEXT))
    neg = deslop.scan_text("他沿着河堤慢慢走，水面浮着零星的灯光，远处偶尔传来一声船笛，"
                           "风把凉意送到领口里。" * 20)
    assert "low-connective-density-tic" not in _rules(neg)


# ---------- 7) formulaic-parallelism ----------

def test_formulaic_parallelism_pos_and_neg():
    pos = deslop.scan_text("至于去不去，怎么去，他没说。\n不吃香菜，不放辣油，汤里连葱花都不搁。"
                           "\n不是他干的。\n也不是我干的。\n只是有人想让他背这个名头。")
    assert "formulaic-parallelism" in _rules(pos)
    # 台词/指令里的否定清单是对话功能；连词「不断/不同/不管」真人高频——均不报
    neg = deslop.scan_text("「不吃香菜，不放辣油。」他说。\n他随着不断学习，不断体悟，"
                           "信念更加坚定。\n三方有不同的背景，不同的资源。\n"
                           "不管怎幺样，不管多难，他都要走完这一趟。")
    assert "formulaic-parallelism" not in _rules(neg)


# ---------- 8) cliche-density-tic ----------

def test_cliche_density_tic_pos_and_neg():
    pos = deslop.scan_text("他缓缓抬头，微微皱眉，轻轻放下茶杯，淡淡开口。" * 10)
    assert "cliche-density-tic" in _rules(pos)
    neg = deslop.scan_text("他缓缓抬头，微微皱眉，轻轻放下茶杯，淡淡开口，说了句无关紧要的话。"
                           "夜色深了。")
    assert "cliche-density-tic" not in _rules(neg)


# ---------- 9) forced-triad ----------

def test_forced_triad_pos_and_neg():
    pos = deslop.scan_text("他看着天，他看着地，他看着自己的手。"
                           "那是愤怒，那是委屈，那是解脱。夜色深了。")
    assert "forced-triad" in _rules(pos)
    # ≥4 项是列举；三段全同是复沓；「有的」枚举开头是真人惯用——均不报
    neg = deslop.scan_text("有的缺手，有的断腿，有的脑袋少了一半，有的胸口破开。"
                           "平静，平静，平静。他深吸一口气，稳住了呼吸。")
    assert "forced-triad" not in _rules(neg)


# ---------- 10) sentence-opening-run ----------

def test_sentence_opening_run_pos_and_neg():
    pos = deslop.scan_text("他笑了。他转身。他走了。院子里只剩风声。")
    assert "sentence-opening-run" in _rules(pos)
    # 拟声/惊叹连发与对话标签行是真人正常形态——不报（700 章真人语料校准）
    neg = deslop.scan_text("咚！咚！咚！\n「真的？」杨玉环欣喜地问。\n「当然。」方运道。\n"
                           "后天二重！后天三重！后天四重！")
    assert "sentence-opening-run" not in _rules(neg)


# ---------- 11) idealized-persona-simile ----------

def test_idealized_persona_simile_pos_and_neg():
    pos = deslop.scan_text("那声音像是高高在上的神明。他仿佛一位智慧的导师，一言不发。")
    assert "idealized-persona-simile" in _rules(pos)
    neg = deslop.scan_text("她像她的母亲，眉眼里都是温柔。灶上的粥咕嘟着。")
    assert "idealized-persona-simile" not in _rules(neg)


# ---------- 12) adjacent-sentence-isomorph ----------

def test_adjacent_isomorph_pos_and_neg():
    pos = deslop.scan_text("他的刀已经出鞘，天色还没有亮。她的马已经备好，雨势还没有停。"
                           "我的路已经看清，风声还没有歇。它的灯已经点亮，夜色还没有深。\n"
                           "他的酒已经温好，席面还没有齐。她的信已经写完，墨迹还没有干。"
                           "我的琴已经调准，弦音还没有定。它的巢已经筑好，幼鸟还没有归。")
    assert "adjacent-sentence-isomorph" in _rules(pos)
    # 骈文/古赋对仗（洛神赋式）无现代功能词——文体传统豁免；2 对同构不报
    neg = deslop.scan_text("肩若削成，腰如约素。延颈秀项，皓质呈露。芳泽无加，铅华弗御。\n"
                           "他要出门，天还没亮。她要赶路，雨还没停。")
    assert "adjacent-sentence-isomorph" not in _rules(neg)


# ---------- 13) zero-subject-comment ----------

def test_zero_subject_comment_pos_and_neg():
    pos = deslop.scan_text("头一段交代来历。\n听起来像是推脱。\n看起来不像是伪造。\n"
                           "说起来全是巧合。\n他合上册子走了。")
    assert "zero-subject-comment" in _rules(pos)
    neg = deslop.scan_text("听起来像是推脱。\n听起来这像是推脱。\n听起来那像是缓兵之计。")
    assert "zero-subject-comment" not in _rules(neg)


# ---------- 14) vague-rider ----------

def test_vague_rider_pos_and_neg():
    pos = deslop.scan_text("目光落在旧照片上，仿佛在诉说着往事。风吹过空巷，像是在宣告着什么。")
    assert "vague-rider" in _rules(pos)
    neg = deslop.scan_text("目光落在旧照片上，仿佛在诉说着往事。夜色深了。")
    assert "vague-rider" not in _rules(neg)


# ---------- 15) closer-recap-tic ----------

def test_closer_recap_pos_and_neg():
    pos = deslop.scan_text("这就是答案。这就是代价。这就是他的选择。夜色深了。")
    assert "closer-recap-tic" in _rules(pos)
    neg = deslop.scan_text("这就是答案。夜色深了，他把纸折好放进内袋。")
    assert "closer-recap-tic" not in _rules(neg)


# ---------- 16) sendoff-para ----------

def test_sendoff_para_pos_and_neg():
    pos = deslop.scan_text("他关灯下楼。\n前路还长，未来可期，希望不灭，命运终会转向黎明。")
    assert "sendoff-para" in _rules(pos)
    neg = deslop.scan_text("他关灯下楼。\n「未来会更好的。」他说完就走了，夜风把门带上。")
    assert "sendoff-para" not in _rules(neg)


# ---------- 17) recap-opening ----------

def test_recap_opening_pos_and_neg():
    pos = deslop.scan_text("上一章说到，他在祠堂里发现了那半块玉佩。\n"
                           + "他沿着河堤慢慢走，水面浮着零星的灯光，远处偶尔传来一声船笛。" * 10)
    assert "recap-opening" in _rules(pos)
    # 开篇窗（前 400 可见字）之外的复述句式不报
    neg = deslop.scan_text("他沿着河堤慢慢走，水面浮着零星的灯光，远处偶尔传来一声船笛。" * 30
                           + "\n上一章说到，他在祠堂里发现了那半块玉佩。")
    assert "recap-opening" not in _rules(neg)


# ---------- 合成毒文本：全套 45 规则命中率 ≥90% ----------

def _build_poison2():
    filler = "他沿着河堤慢慢走，水面浮着零星的灯光，远处偶尔传来一声船笛，风把凉意送到领口里。"
    blocks = [
        # recap-opening（章首窗）+ 一段正常叙述
        "上一章说到，他在祠堂里发现了那半块玉佩。",
        filler * 2,
        # 常规毒块（0.22 存量规则）
        "这不是结束，而是新的开始。",
        "胜利是必然的，不是偶然的。",
        "没有人来，没有敲门声。",
        "他的声音不大，却压住了整间屋子。",
        "她的语气毫无波澜。",
        "他深吸一口气，眼中闪过一丝疲惫。",
        "他攥紧拳头，带着不肯认输的狠劲。",
        "他知道答案。她明白结局。我意识到危险逼近。",
        "他盯着她。她看向窗外。他注视地面。她望向远处。目光相遇又分开。",
        "门开了。他进去。灯亮着。屋里没人。桌上有灰。他坐下。",
        '"自由"和"救赎"之外，还有"代价"与"选择"。',
        # 密度投料（阈值随千字数缩放，投放量留足余量）
        "他没有动。她没有回头。" * 10,                                   # brake ×20
        "他猛地起身。她猛地回头。" * 8,                                   # mengdi ×16
        "他笑了一下，挥了下手，叹了口气。" * 26,                          # micro ×78
        "这好像是一种默契。" * 40,                                        # metaphor ×40
        "雨丝仿佛帘幕。" * 26,                                            # simile ×26
        "剑、刀、枪摆满了一架。" * 26,                                    # dunhao ×26
        "一句话总结：他要赢。核心是：活下去。原因如下：门锁了。结论是：没人认错。" * 4,
        "他缓缓抬头，微微皱眉，轻轻放下茶杯，淡淡开口。" * 40,            # cliche-density ×160
        "他的指尖微微一颤。她的指节攥得泛白。" * 10,                      # stock ×20
        "他知道任务。这意味着风险。必须维持局面。任务与规则。" * 12,       # reasoning 四桶
        "他走了——又停——回头——看她——笑了笑——挥手——离开。" * 12,          # em-dash ×72
        # 新规则投料
        "他不哭，也不闹。没有门，也没有窗。她不问，也不躲。",             # negation-pair ×3
        "他伸手抓起刀，转身踢开门，回头喊了一声，抬手挥刀，放下酒碗，坐下喘气，看向门口。",
        "【访客不得进入内区】\n【违规者必须接受惩罚】\n【禁止在公共区域喧哗，维持秩序】\n"
        "【任务失败将被视为违约】\n【所有指令必须严格执行，同样计入考核】",
        "至于去不去，怎么去，他没说。\n不吃香菜，不放辣油，汤里连葱花都不搁。",
        "他看着天，他看着地，他看着自己的手。那是愤怒，那是委屈，那是解脱。",
        "他笑了。他转身。他走了。院子里只剩风声。",
        "那声音像是高高在上的神明。他仿佛一位智慧的导师，一言不发。",
        "他的刀已经出鞘，天色还没有亮。她的马已经备好，雨势还没有停。"
        "我的路已经看清，风声还没有歇。它的灯已经点亮，夜色还没有深。",
        "听起来像是推脱。\n看起来不像是伪造。\n说起来全是巧合。",
        "目光落在旧照片上，仿佛在诉说着往事。风吹过空巷，像是在宣告着什么。",
        "这就是答案。这就是代价。这就是他的选择。",
        # 命运/抽象总结
        "这一刻，他终于明白。从这一刻开始。命运的齿轮开始转动。早已布好的棋局。" * 12,
        # 过度精炼短段 + 低连接（共用一大块电报体）
        "\n".join(_TERSE_SHORTS * 5 + [_TERSE_LONG] * 12),
        # 否定排比两模式
        "他没炫技，没有那种张扬的架势。他只是把歌唱完了。",
        # 文末 600 字窗口：预告族
        "他不知道的是，门口站着一个人。",
        "没人知道他去了哪里。",
        "这一夜，注定无人入眠。新的篇章即将拉开序幕！",
        # sendoff-para（末段）
        "前路还长，未来可期，希望不灭，命运终会转向黎明。",
    ]
    return "# 测试章\n\n" + "\n\n".join(blocks)


_POISON2 = _build_poison2()
_P2_FINDINGS = deslop.scan_text(_POISON2)
_P2_RULES = _rules(_P2_FINDINGS)


def test_poison2_hits_at_least_90pct_of_all_rule_families():
    all_rules = set(deslop_metrics.REVIEW_AXIS)
    assert len(all_rules) == 45, f"规则族应为 45，实际 {len(all_rules)}"
    hit = all_rules & _P2_RULES
    assert len(hit) / len(all_rules) >= 0.9, (
        f"毒文本命中率 {len(hit)}/{len(all_rules)} < 90%，未命中：{sorted(all_rules - _P2_RULES)}")


def test_poison2_hits_every_new_rule():
    miss = [r for r in _NEW_RULES if r not in _P2_RULES]
    assert not miss, f"新规则未被毒文本命中：{miss}"


def test_poison2_new_rules_all_advisory():
    """校准纪律：17 条新规则全部 advisory 起步（blocking 只收上游双库校准过的存量增补）"""
    for f in _P2_FINDINGS:
        if f.rule in _NEW_RULES:
            assert f.level == "advisory", f.rule


def test_all_fired_rules_registered_in_review_axis():
    """fail-loud 的测试面：任何 fired rule 必须登记 mechanical/semantic 二轴"""
    for r in _P2_RULES:
        assert r in deslop_metrics.REVIEW_AXIS, f"规则 {r} 未登记 REVIEW_AXIS"


# ---------- 语料校准回归钉（真人误报类，调参后不得复发） ----------

def test_calibration_pins_trailer_dialogue_and_attributive():
    filler = "他沿着河堤慢慢走，水面浮着零星的灯光，远处偶尔传来一声船笛，风把凉意送到领口里。"
    # 台词里的「谁也不知道」不是叙述者预告（儒道至圣 校准命中）
    assert "trailer-summary" not in _rules(
        deslop.scan_text(filler * 30 + "\n「谁也不知道他去了哪里。」他说。"))
    # 定语「即将开始的聚会」不是预告（诡秘之主 校准命中）
    assert "trailer-summary" not in _rules(
        deslop.scan_text(filler * 30 + "\n想到即将开始的聚会，他笑了笑，推门进去。"))


def test_calibration_pins_negation_parade_guards():
    # 黏着语素（沉没）与时间惯用语（没多久/没等）不是否定排比
    assert "negation-parade" not in _rules(
        deslop.scan_text("船沉没在雾里，没人回头，只有桨声一下一下拍着水。"))
    assert "negation-parade" not in _rules(
        deslop.scan_text("没多久，没等她撑伞，雨就落了下来，屋檐下挤满了人。"))


def test_trailer_summary_new_branches_pos():
    filler = "他沿着河堤慢慢走，水面浮着零星的灯光，远处偶尔传来一声船笛，风把凉意送到领口里。"
    hits = deslop.scan_text(filler * 30 + "\n这一夜，注定无人入眠。新的篇章即将拉开序幕！")
    ts = [f for f in hits if f.rule == "trailer-summary"]
    assert len(ts) >= 2    # 这一夜注定 + 新的篇章拉开序幕（正式 lookbehind 不影响）


def test_not_is_dialogue_exempt_and_affirmation_safe():
    # 正例：跨逗号翻转仍报；A9「新的开始」抽象分支并入后同句命中摘要规则
    assert "not-is-comparison" in _rules(deslop.scan_text("这不是结束，而是新的开始。"))
    assert "abstract-summary-tic" in _rules(deslop.scan_text("旧的都翻篇了。新的开始。"
                                                             "新的开始。又是新的开始。"))
    # either-or 连词「不是A就是B」的排除与引号内豁免随 C1b/B1 状态机落地（见 test_deslop_c1b）


# =====================================================================
# C16b/C1b：6 处校准改进（B1 not-is 状态机 / B2 reverse 排除集 / B3 voice-contrast
# 正则 / B4 negation-parade 排除集（随 A11 落地）/ B5 quote-emphasis 五类排除 /
# B6 reasoning 四桶四重门）+ 书级白名单 + maskQuoted 行域重写
# =====================================================================

def test_b1_not_is_state_machine_exclusions():
    # 五类排除（issue #166 误报学）：是不是问句 / 反问尾 / 确认语 / either-or / 分隔后连词
    for safe in (
        "他问了一句：「你是不是怕了？」她点头。",       # 是不是问句
        "不是已经说好了吗？他偏要再来一次。",           # 反问尾（是吗/吧/嘛同族）
        "不是第一次来。是的，他还记得那天。",           # 「是的」确认语
        "不是东风压倒西风，就是西风压倒东风。",         # either-or
        "不是我不想帮；只是我实在腾不出手。",           # 分号后连词「只是」（#166）
    ):
        assert "not-is-comparison" not in _rules(deslop.scan_text(safe)), safe
    # 正例多型（oh-story test-ai-patterns 同款：而是/，是/紧凑/逗号后「只是」承接）
    assert "not-is-comparison" in _rules(deslop.scan_text("不是害怕，是累了。"))
    assert "not-is-comparison" in _rules(deslop.scan_text("不是笨是太急。"))
    assert "not-is-comparison" in _rules(deslop.scan_text("他不是冷漠，只是累了。"))
    assert "not-is-comparison" in _rules(deslop.scan_text("这不是结束，而是新的开始。"))
    # 引号内台词「不是A，是B」是口语辩解——maskQuoted 豁免
    assert "not-is-comparison" not in _rules(
        deslop.scan_text("「不是我干的，是他逼我的。」他把杯子墩在桌上。"))
    # 跨空行分段揭示（「不是A。是B」）仍报（skipGap）
    assert "not-is-comparison" in _rules(
        deslop.scan_text("这不是放弃。\n\n是换一条路走。"))


def test_b2_reverse_not_is_exclusions():
    assert "reverse-not-is" in _rules(deslop.scan_text("胜利是必然的，不是偶然的。"))
    assert "reverse-not-is" in _rules(deslop.scan_text("他是真嗓子，不是修音修出来的。"))
    for safe in (
        "他手里拿的还是旧账本，不是新账。",             # 前字「还」合成词
        "那只是传闻，不是实情。",                       # 前字「只」合成词
        "可是他说的不是这个意思。",                     # 前字「可/但」合成词
        "是不是他，不是别人。",                         # 是不是起头
    ):
        assert "reverse-not-is" not in _rules(deslop.scan_text(safe)), safe


def test_b3_voice_contrast_regex_widened():
    # oh-story 校准正则：音量词扩到 响亮、转折扩到 但/偏、允许 ≤16 字间隔
    for hit in (
        "他的声音并不响亮，却压住了整间屋子。",
        "她的声音不高，第一句却稳稳落了地。",
        "他的声音不大，偏要在这种时候开口。",
    ):
        assert "voice-contrast" in _rules(deslop.scan_text(hit)), hit
    assert "voice-contrast" not in _rules(deslop.scan_text("他的声音不大，听得清每个字。"))


def test_b5_quote_emphasis_exclusions():
    base = '"自由"和"救赎"之外，还有"代价"与"选择"。'
    assert "quote-emphasis" in _rules(deslop.scan_text(base))
    # ①引语动词邻接=极短台词；②含句读=台词；③无叙述整行=弹幕流
    assert "quote-emphasis" not in _rules(
        deslop.scan_text('他说这是"自由"。她说这是"救赎"。她喊出"代价"。'))
    assert "quote-emphasis" not in _rules(
        deslop.scan_text('"自由，平等"写在了旗上。'))
    assert "quote-emphasis" not in _rules(
        deslop.scan_text('"叮咚""叮咚""叮咚"'))                # 引号外无叙述=拟声连发行
    # ④【】系统面板载体；⑤引号套引号（台词内强调属角色语言）
    assert "quote-emphasis" not in _rules(
        deslop.scan_text('【提示："自由"已解锁】\n【提示："救赎"已解锁】\n【提示："代价"已解锁】'))
    assert "quote-emphasis" not in _rules(
        deslop.scan_text('他念道：“碑上刻着‘自由’二字。”他念道：“旁注是‘代价’。”'
                         '他念道：“落款是‘救赎’。”'))


def test_b6_reasoning_four_gates():
    dense = "知道任务。这意味着风险。必须维持局面。任务与规则与责任。" * 6
    assert "reasoning-chain" in _rules(deslop.scan_text(dense))
    # 单桶/低密度不报（四重门）
    assert "reasoning-chain" not in _rules(
        deslop.scan_text("这意味着危险。也就是说他输了。问题在于没人信。"))
    assert "reasoning-chain" not in _rules(
        deslop.scan_text("任务、条件、风险、规则摆了一桌，他一条条核对过去。"))


def test_in_dialogue_line_scoped_no_cross_line_leak():
    from app.core import deslop_metrics as dm
    # 漏收引号只吞到行尾，不会把后面成百上千字算成台词（maskQuoted 重写核心动机：
    # 旧实现统计全文开合计数，行 1 漏收引号会把行 2 叙述判成台词内）
    text = "「他说完就走了，\n门外静悄悄的，谁也没来。"
    assert dm.in_dialogue(text, text.index("门外")) is False
    # 行内正常闭合的台词照判
    text2 = "「两句话说完了。」门外静悄悄的。"
    assert dm.in_dialogue(text2, 3) is True
    assert dm.in_dialogue(text2, text2.index("门外")) is False


# ---- C16b/C3：书级白名单 ----

def test_mask_style_text_and_scan_whitelist():
    from app import deslop as d
    poisoned = "他袖中滑出一抹青云，映亮了半间石室。"
    assert "cliche-word" in _rules(d.scan_text(poisoned))          # 一抹=一级禁用词
    kept = d.scan_text(poisoned, whitelist=["一抹青云"])           # 书里「一抹青云」是功法名
    assert "cliche-word" not in _rules(kept)
    # 白名单只掩字面 span，其余毒词照扫
    still = d.scan_text("他眼中闪过一丝疲惫，袖中滑出一抹青云。", whitelist=["一抹青云"])
    assert "cliche-word" in _rules(still)


def test_gates_load_whitelist_and_scan_deslop_proj(tmp_path):
    from app.core import gates
    proj = tmp_path / "书名"
    proj.mkdir()
    (proj / ".deslop-whitelist").write_text(
        "# 注释行\n一抹青云\n玄铁令\n", encoding="utf-8")
    wl = gates.load_deslop_whitelist(str(proj))
    assert "一抹青云" in wl and "玄铁令" in wl and "# 注释行" not in wl
    assert gates.load_deslop_whitelist(str(tmp_path)) == []        # 缺文件 fail-open
    poisoned = "他袖中滑出一抹青云，映亮了半间石室。"
    blk, adv = gates.scan_deslop(poisoned, proj=str(proj))
    assert not [f for f in blk + adv if f.rule == "cliche-word"]
    blk2, adv2 = gates.scan_deslop(poisoned)                       # 不传 proj 行为同 0.22
    assert [f for f in blk2 + adv2 if f.rule == "cliche-word"]
