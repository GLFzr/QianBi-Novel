# -*- coding: utf-8 -*-
"""lieflat Phase 2 验证资产：两条新增 advisory 正则的上线门禁（方案 §4 Phase 2.3）。

- 误报：扫 tests/corpus_pd 人类语料（萧红《呼兰河传》、鲁迅《野草》，繁体原文）
  ——两条新规则必须 0 触发；simile-marker-density 同样 0 触发（人类 1.14/千字
  低于 2/千字 阈值）。测不过就不上线（宁缺毋滥）。
- 召回：植入样例（正例必须触发 / 单例低于阈值不触发）。
  偏差说明：tests/planted_defects/defects.json 是审校六维（A-F）雷集，不含
  去 AI 味维度条目——召回样例按同构思路植入本文件（文档化于方案落地记录）。

同时锁死 Phase 2 联动决策：CLICHE_SIMILE 单词命中不再产生 blocking。
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app import deslop


def _rules_of(findings):
    return {f.rule for f in findings}


def _blocking_of(findings):
    return [f for f in findings if f.level == "blocking"]


# ---------- 误报：人类语料零触发 ----------

def test_human_corpus_no_false_positives():
    files = sorted(glob.glob(os.path.join(ROOT, "tests", "corpus_pd", "**", "*.txt"),
                             recursive=True))
    assert len(files) >= 3, f"corpus_pd 资产异常（只找到 {len(files)} 个文件）"
    total_chars = 0
    for path in files:
        text = open(path, encoding="utf-8").read()
        total_chars += len(text)
        rules = _rules_of(deslop.scan_text(text))
        for banned in ("prompting-colon", "dunhao-list-density", "simile-marker-density"):
            assert banned not in rules, \
                f"人类语料误报：{os.path.basename(path)} 触发 {banned}"
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


def test_cliche_family_still_blocks_on_other_words():
    # 其余一级禁用词（一丝/一抹…）行为不变，仍是 blocking
    text = ("# 第1章 对峙\n"
            "她眼中闪过一丝惊讶，随即低下头去，指尖在桌沿上轻轻敲了两下。"
            "他注意到她指节泛白，却没有点破，只是把那份文件又往她面前推了推。"
            "屋里的挂钟走得很响，两个人都没再开口。")
    blocking = _blocking_of(deslop.scan_text(text))
    assert any(f.rule == "cliche-word" for f in blocking), \
        "一级禁用词其余词表行为回归（应仍 blocking）"
