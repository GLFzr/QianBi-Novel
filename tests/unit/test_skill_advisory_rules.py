# -*- coding: utf-8 -*-
"""lieflat Phase 2 验证资产：两条新增 advisory 正则的上线门禁（方案 §4 Phase 2.3）。

- 误报：扫**入库夹具** tests/fixtures/corpus_min/（原创简体人类文风短篇，
  WP-15④：旧实现扫 tests/corpus_pd 整库——该目录被 .gitignore 忽略，干净机/CI
  只能红在"资产缺失"，且繁体原文与新规则词表简体不同口径，误报分母不可复核。
  夹具版 CI 可判；corpus_pd 整库扫描降级为本地可选，资产在则多扫一道）
  ——两条新规则必须 0 触发；simile-marker-density 同样 0 触发。
- 召回：植入样例（正例必须触发 / 单例低于阈值不触发）。
  偏差说明：tests/planted_defects/defects.json 是审校六维（A-F）雷集，不含
  去 AI 味维度条目——召回样例按同构思路植入本文件（文档化于方案落地记录）。

同时锁死 Phase 2 联动决策：CLICHE_SIMILE 单词命中不再产生 blocking。
"""
import glob
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app import deslop


def _rules_of(findings):
    return {f.rule for f in findings}


def _blocking_of(findings):
    return [f for f in findings if f.level == "blocking"]


_ADVISORY_RULES = ("prompting-colon", "dunhao-list-density", "simile-marker-density")


def _assert_no_advisory_hits(text, label):
    rules = _rules_of(deslop.scan_text(text))
    for banned in _ADVISORY_RULES:
        assert banned not in rules, f"人类语料误报：{label} 触发 {banned}"


# ---------- 误报：入库夹具（CI 可判） ----------

def test_human_corpus_min_no_false_positives():
    files = sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures",
                                          "corpus_min", "*.txt")))
    assert len(files) >= 3, f"corpus_min 夹具缺失（只找到 {len(files)} 篇）"
    total = 0
    for path in files:
        text = open(path, encoding="utf-8").read()
        total += len(text)
        _assert_no_advisory_hits(text, os.path.basename(path))
    assert total > 2000, "corpus_min 语料量异常（<2 千字，误报测试失去分母）"


# ---------- 误报：corpus_pd 整库（本地可选——资产被 gitignore，不在则跳过） ----------

def test_human_corpus_pd_full_scan_local_optional():
    files = sorted(glob.glob(os.path.join(ROOT, "tests", "corpus_pd", "**", "*.txt"),
                             recursive=True))
    if not files:
        pytest.skip("corpus_pd 未入库（.gitignore）——CI 判据由 corpus_min 夹具承担，"
                    "整库扫描为本地可选复核")
    total_chars = 0
    for path in files:
        text = open(path, encoding="utf-8").read()
        total_chars += len(text)
        _assert_no_advisory_hits(text, os.path.basename(path))
    assert total_chars > 10000, "corpus_pd 语料量异常（<1 万字，误报测试失去分母）"


# ---------- 召回：植入样例必须触发 ----------

FILLER = ("他把账本推到桌子对面，声音压得很低。老周没有接话，只把茶碗转了半圈，"
          "窗外的雨还在下，屋檐水砸在青石上，溅起的湿气顺着门缝往里钻，"
          "谁也没开灯，屋里就剩下挂钟走针的响动。")


def test_prompting_colon_recall():
    # 2 处提示性冒号、正文 ≥1 千字（阈值 max(2, 1/千字)=2）→ 必触发
    text = ("# 第1章 试探\n" + FILLER * 7
            + "他把烟摁灭在缸里，说核心是：把成本降下来，别的都可以谈。"
              "隔了很久又补一句，关键在于：时机一过，谁也别想再开这个口。"
            + FILLER * 7)
    assert len(text) > 1000
    assert "prompting-colon" in _rules_of(deslop.scan_text(text)), "提示性冒号正召回失败"


def test_prompting_colon_below_threshold_silent():
    # 仅 1 处提示性冒号（低于阈值 2）→ 不触发
    text = ("# 第1章 试探\n" + FILLER * 7
            + "他把烟摁灭在缸里，说核心是：把成本降下来，别的都可以谈。"
            + FILLER * 8)
    assert len(text) > 1000
    assert "prompting-colon" not in _rules_of(deslop.scan_text(text))


def test_dunhao_list_recall():
    # 罗列句 5 句、正文 ≥1 千字（阈值 max(4, 2/千字)=4）→ 必触发
    list_sentences = (
        "铺子里摆着胭脂、水粉、头绳、绢花、香料，各色物件挤在一处。"
        "隔壁是卖干果、蜜饯、炒米、糖霜的铺面，掌柜的正低头称糖。"
        "再过去是书坊，笔墨、纸张、砚台、印泥，一顺排开。"
        "街那头还有一间药铺，当归、黄芪、甘草、陈皮，一屉一屉码得整齐。"
        "巷口挑担的贩子卖的都是针头线脑、发绳、纽扣这类小物件。")
    text = ("# 第1章 市集\n" + list_sentences
            + ("她挎着篮子慢慢走，柜台后头的伙计抬起眼皮，看了看她的竹篮，"
               "又看了看她袖口磨出的毛边。她说不要什么，只是看看。"
               "檐下的灯笼一盏一盏亮起来，把湿漉漉的石板路照出一片暖黄。") * 12)
    assert len(text) > 1000
    assert "dunhao-list-density" in _rules_of(deslop.scan_text(text)), "顿号罗列正召回失败"


def test_dunhao_single_sentence_silent():
    # 单句罗列（人类文风常态，1.14/千字 以下）→ 不触发
    text = ("# 第1章 市集\n"
            "铺子里摆着胭脂、水粉、头绳、绢花、香料，各色物件挤在一处。"
            + ("柜台后头的伙计抬起眼皮，看了看她的竹篮，又看了看她袖口磨出的毛边，"
               "随口问她要些什么。她说不要什么，只是看看。伙计便也不再理会，"
               "自顾自拨起算盘来，噼里啪啦一阵响，倒像是外头又在下雨。"
               "她从铺子里出来，沿着河沿慢慢走，风把灯笼的影子吹得晃了几晃。") * 11)
    assert len(text) > 1000
    assert "dunhao-list-density" not in _rules_of(deslop.scan_text(text))


# ---------- Phase 2 联动决策锁死：比喻标记词不再 blocking ----------

def test_simile_word_is_not_blocking_anymore():
    text = ("# 第1章 雨夜\n"
            "他站在桥头，雨丝仿佛牛毛，桥下的水声犹如闷雷，远处的灯火宛若星子，"
            "雾气如同纱幔，一层一层地漫过堤岸。")
    findings = deslop.scan_text(text)
    for f in findings:
        if f.rule in ("simile-marker-density", "cliche-word", "metaphor-density"):
            assert f.level != "blocking", \
                f"联动决策被破坏：比喻标记词又回到了 blocking（{f.rule}）"


def test_simile_density_recall():
    """WP-15③：放松后的 simile-marker-density 必须有召回夹具——堆叠样张必报。
    （此前只有"不再 blocking"的单向断言：删掉整块检测，相关测试依旧全绿。）"""
    body = ("他站在桥头，雨丝仿佛牛毛。桥下的水声犹如闷雷，远处的灯火宛若星子，"
            "雾气如同纱幔，一层一层漫过堤岸。城里的钟声仿佛隔了十年，"
            "他又觉得这夜犹如一张网，把他和这条街一起兜住。"
            "灯影在水里晃，晃碎了又聚拢，聚拢了又晃碎。")
    text = "# 第1章 雨夜\n" + body + ("河水拍着桥墩，一声接一声，没有停的意思。"
                                     "他数着自己的呼吸，数到一百就重新数。"
                                     "对岸的狗叫了两声，又静下去。") * 24
    assert len(text) > 1000
    assert "simile-marker-density" in _rules_of(deslop.scan_text(text)), \
        "文言腔比喻堆叠未被检出（密度型 advisory 召回失败）"


def test_cliche_family_still_blocks_on_other_words():
    # 其余一级禁用词（一丝/一抹…）行为不变，仍是 blocking
    text = ("# 第1章 对峙\n"
            "她眼中闪过一丝惊讶，随即低下头去，指尖在桌沿上轻轻敲了两下。"
            "他注意到她指节泛白，却没有点破，只是把那份文件又往她面前推了推。"
            "屋里的挂钟走得很响，两个人都没再开口。")
    blocking = _blocking_of(deslop.scan_text(text))
    assert any(f.rule == "cliche-word" for f in blocking), \
        "一级禁用词其余词表行为回归（应仍 blocking）"


# ---------- WP-15④ 补强（v3）：blocking 全族静默样张 + 公版语料 + 期望命中数 ----------

def _blocking_rules(findings):
    return {f.rule for f in findings if f.level == "blocking"}


# 每条 blocking 规则族一条「人类会这么写、不该被拦」的静默样张
#（不含任何该族触发形态；样张彼此独立，只断言本族静默）
BLOCKING_QUIET_SAMPLES = {
    "not-is-comparison": "他说自己不是本地人，口音带着北边的调子。",
    "reverse-not-is": "这个办法是不对的，账目对不上就是证据。",
    "negation-parade": "屋里没有开灯，桌上那碗面也坨了。",   # 单个「没有」，不成排比
    "voice-contrast": "她的声音很轻，说到一半被风吹散了。",   # 轻声不接「却」
    "flat-voice": "他把证件放在台子上，等对方核对。",
    "trailer-ending": "老陈把伞收了，雨水顺着伞骨往下滴。",   # 不写「他不知道的是」
    "trailer-summary": "案子结了，卷宗归了档，巷子又安静下来。",
    "fate-summary": "他把票据一张一张码好，用夹子夹住。",
    "em-dash": ("# 第1章 渡口\n" + "他从巷口走出来，街边的灯笼一盏一盏亮起。"
                 + ("老者抬头看了他一眼，又低下头去搅动锅里的汤。他没有停留——沿着石板路一直往北，走过石桥，桥下的水声盖过了人语。"
                 + "城门口的兵丁靠着墙打盹，谁也没注意这个背包袱的外乡人。他问了路，又往渡口去，渡船刚走，只能坐在石阶上等。"
                 + "天色一点一点暗下来，河面起了雾。摆渡的老人冲他喊：再等等，还有一趟。他点点头，把包袱搂紧了些，继续坐着。"
                 + "等船的人陆续多了，挑担子的、走亲的，各人想各人的事。")),  # 2 处破折号/0.5 千字=低密度 advisory（>6/千字才阻断）
    "daizhe-adverb": "她拎着篮子出门，顺路把信投进了邮筒。",  # 无「，带着……」
    "cliche-word": "老人把眼镜往上推了推，把报纸折好放进抽屉，起身去开窗。",
}


def test_blocking_families_have_quiet_samples():
    """v3 语料补强①：每条 blocking 规则至少一条静默样张——
    人类文风在这些族上必须零阻断（宁缺毋滥的反向门禁）。"""
    for rule, sample in BLOCKING_QUIET_SAMPLES.items():
        findings = deslop.scan_text(sample)
        blocking = _blocking_rules(findings)
        assert rule not in blocking, (
            f"静默样张被拦：{rule} 在人类句式上产生 blocking——{[f.message for f in findings if f.rule == rule]}")


def test_public_domain_excerpt_no_blocking():
    """v3 语料补强②：用**人类写的**真实段落（公版语料固化入库）测不误报。

    选段考证：紧接的下一段「没有影像，没有言辞」会被 negation-parade 命中——
    人类经典文风在该族的误报真实存在（鲁迅也逃不过），已作为已知误报记录；
    零误报判据取经验证的前两段，不夹带病文本。"""
    path = os.path.join(ROOT, "tests", "fixtures", "corpus_min", "公版_故乡选段.txt")
    text = open(path, encoding="utf-8").read()
    blocking = _blocking_rules(deslop.scan_text(text))
    assert not blocking, f"公版人类语料触发 blocking：{blocking}（词表口径过宽）"


def test_recall_expected_hit_counts_pinned():
    """v3 语料补强③：召回侧期望命中数写死——改词表/阈值必须红。"""
    # 提示性冒号样张恰有 2 处触发（与 test_prompting_colon_recall 同文）
    text = ("# 第1章 试探\n" + FILLER * 7
            + "他把烟摁灭在缸里，说核心是：把成本降下来，别的都可以谈。"
              "隔了很久又补一句，关键在于：时机一过，谁也别想再开这个口。"
            + FILLER * 7)
    hits = [f for f in deslop.scan_text(text) if f.rule == "prompting-colon"]
    assert len(hits) == 2, f"提示性冒号期望 2 处命中，实测 {len(hits)}——词表/阈值漂移"
    # 一级禁用词样张恰 2 处（一丝 + 不禁，各来自不同禁用组）
    text2 = ("# 第1章 对峙\n"
             "她眼中闪过一丝惊讶，随即低下头去，不禁攥紧了衣角。"
             "窗外的雨没有停的意思。")
    hits2 = [f for f in deslop.scan_text(text2) if f.rule == "cliche-word"]
    assert len(hits2) == 3, f"一级禁用词期望 3 处命中（眼中闪过/一丝/不禁），实测 {len(hits2)}——禁用词表漂移"
