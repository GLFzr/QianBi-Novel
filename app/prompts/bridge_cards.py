# -*- coding: utf-8 -*-
"""C43-2 桥段打法卡（prompts 侧）·6 张自写打法卡

与 scene_cards（6 张通用场景卡）的分工：场景卡讲「这类戏怎么演」，打法卡讲
「这个具体桥段的成套打法」——只覆盖结构复杂、最容易写崩的高价值码。
版权绿档：全部字段自写（网文创作通识），不含任何原文摘录、真实书名或语料
画像内容；码值路由不做二次定义，一律引用 bridge_codes.BRIDGE_CODES 的 card
映射（单一事实源，防双轨漂移——附录B卡5 风险②）。

字段（与附录B卡5 打法卡 schema 同形，措辞全自产）：
  trigger 触发条件（细纲可指认的启用前提）
  beats   打法步骤（章内顺序拍；每拍一条可执行指令）
  joint   章钩衔接（与下一章的收口方式）
  failure 失败态（写崩样貌，供自检与后续审校面复用）

注入纪律：example 不进 prompt（示例句会被模型当成情节抄——scene_cards 既有
纪律）；play_block 输出 ≤9 行，只由 scene_cards.craft_block 在开关开且主码
命中时追加，关闭时零消费、装配字节不变。
"""
from __future__ import annotations

from .bridge_codes import BRIDGE_CODES

# 键 = 桥段码（bridge_codes.BRIDGE_CODES 的子集；一码一卡，路由无歧义）
BRIDGE_PLAY_CARDS: dict[str, dict] = {
    "DB": {"name": "大比",
           "trigger": "细纲出现有规则、有轮次、有观众席的公开竞技场合（大比/擂台/排名赛），且本章处于赛程中",
           "beats": ["开场只写规则里对主角最不利的一条",
                     "首轮对小敌一招定胜负，不写满回合",
                     "强敌轮之前插入看台反应与赔率变化",
                     "胜局靠前文埋的底牌，代价当场兑现"],
           "joint": "章末停在下一轮对阵签公布或强敌登场，不写赛后总结",
           "failure": ["轮次平均用力，看台无反应，赛程变流水账",
                       "底牌提前亮完，决赛无牌可打"]},
    "TP": {"name": "突破进阶",
           "trigger": "细纲写境界/职级/能力的档位跃升，且此前至少有一处铺垫（瓶颈/资源/机缘）",
           "beats": ["突破前先写一次失败或险象，立下成本",
                     "突破动因用前文埋的具体条件，不临时掉宝",
                     "突破瞬间只给一个外部可观察的信号",
                     "新档位的第一个后果章内就到场（敌意/关注/账单）"],
           "joint": "章末用新档位引来的第一份敌意或邀约收口",
           "failure": ["无代价突破，回顾式宣告「他变强了」",
                       "新档位对后续剧情零影响"]},
    "SF": {"name": "身份揭露",
           "trigger": "细纲要求某角色真实身份揭开，且此前至少埋过两处可回看的线索",
           "beats": ["揭露前让身份线索最后一次平静出场",
                     "揭露由冲突逼出，不由角色自述",
                     "给一个在场者先于读者的局部反应",
                     "揭露后立刻改写一段既有关系的含义"],
           "joint": "章末停在最受伤或最得利那人的第一个动作上",
           "failure": ["台词自报家门式揭露",
                       "揭露后众人反应整齐划一，无利益重排"]},
    "DC": {"name": "派系内斗",
           "trigger": "同一阵营内两股以上势力利益相抵，且本章要有一次实质性互相使绊",
           "beats": ["先用一句公账说明两派为何不能当场翻脸",
                     "使绊走流程内手段（调令/排期/名额），不直接动刀",
                     "主角夹在中间选边，或做收渔利的第三方",
                     "输的一方留下可回看的后手"],
           "joint": "章末以后手的第一个信号收口，不写胜负定论",
           "failure": ["对手无能化，一招即溃",
                       "内斗与主线资源无关，纯支线空转"]},
    "MO": {"name": "算计",
           "trigger": "一方设局且布局痕迹要求可回看，局在本章或近章收网",
           "beats": ["开局只展示猎物视角的顺利",
                     "中段放一条读者能看懂、当事人看不破的破绽",
                     "收网时逐步回放三处前文细节作证据",
                     "代价由设局者自己承担一部分"],
           "joint": "章末停在局中最后一枚未收口的棋子上",
           "failure": ["全局靠巧合推进，无主动布局者",
                       "收网靠反派自陈动机，而非证据回放"]},
    "PZ": {"name": "扮猪吃虎",
           "trigger": "主角以低于实力的姿态入场，且本章至少有一层底牌要亮",
           "beats": ["低姿态要付真实代价（被轻视/让利/挨罚）",
                     "让旁人先替读者低估一次",
                     "亮底牌只亮一层，且由冲突逼出",
                     "识货者的反应代替主角自证"],
           "joint": "章末停在识货者递出的第一个试探上",
           "failure": ["扮猪阶段无代价，纯姿态表演",
                       "一次亮完所有底牌"]},
}


def play_block(code: str) -> str:
    """渲染主码对应的打法卡块（追加进 craft_block 工艺路线）。

    无打法卡的码（位置码/反例码/过渡码等）返回空串——调用方零追加，
    与关态字节一致。
    """
    key = (code or "").upper()
    card = BRIDGE_PLAY_CARDS.get(key)
    if not card:
        return ""
    out = [f"桥段打法·{card['name']}（{key}）",
           f"- 触发：{card['trigger']}"]
    out.append("- 步骤：" + "；".join(
        f"{i}）{b}" for i, b in enumerate(card["beats"], 1)))
    out.append(f"- 章钩衔接：{card['joint']}")
    for f in card["failure"]:
        out.append(f"- 失败态：{f}")
    return "\n".join(out)


def play_codes_ok() -> bool:
    """打法卡→码路由一致性自检（单测与后续账本批复用）。

    全部键必须是 BRIDGE_CODES 内的非反例码且路由目标为合法场景卡；返回
    False = 打法卡与码表脱钩（例如码表改名后未同步）。
    """
    for key, card in BRIDGE_PLAY_CARDS.items():
        meta = BRIDGE_CODES.get(key)
        if meta is None or meta.get("advisory_only"):
            return False
        if not meta.get("card"):
            return False
        if not card.get("beats") or not card.get("failure"):
            return False
    return True
