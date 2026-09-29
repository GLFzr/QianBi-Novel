# -*- coding: utf-8 -*-
"""C43-1 桥段码账本（prompts 侧）·36 码桥段类型学受控码表

口径：网文桥段类型学 7 组 36 码（爽点 8 + 冲突 5 + 悬念 6 + 情感 6 + 过渡 4 +
钩子 2 + 反例 5）。上游拆解框架自称「28 码」、逐点枚举实为 36 码——对外统一
「36 码」口径并以此文件为准。命名坑显式化：**SJ（收获兑现，爽点组）与
SJ2（闭关跳时，过渡组）前缀撞车**，解析与路由一律按整码 token 匹配（见
parse_bridge_codes），不许按前缀截断。

版权绿档：码表为自写受控词表——码名取通用网文类型学术语；判据/典型位置/
路由词全部自写（网文通识表达），不含任何原文摘录、真实书名或语料画像内容。
反例 5 码（WATER/OOC/BAL/LOGIC/REP）为审校面证据码：advisory_only=True，
只进审校与账本对照，**不进正文/细纲路由**。

开关：writing.bridge_codes_enabled（config.py 出厂键，默认 off）。本文件是纯
数据面——开关关闭时没有任何消费方读到本模块产出，装配字节与现状一致。
stages 接线（C43）：B3 切段后 craft_block 调用点位于 _mc_draft（prose_kw
构造处），接线在该调用前执行
scene_cards.set_bridge_codes_enabled(bridge_codes.enabled_from_cfg(ctx.cfg))；
细纲模板「- 桥段：」字段指令属 planning/co_writing 批（卡3 槽位），本卡不碰。
打法卡（触发/步骤/失败态）在 bridge_cards.py，scene_cards.craft_block 开态追加。
"""
from __future__ import annotations

import re

# ---- 开关键位（config.py "writing" 出厂键；本函数组是唯一读取口径）----
CFG_SECTION = "writing"
CFG_KEY = "bridge_codes_enabled"
DEFAULT_ENABLED = False

# 场景卡合法键（与 scene_cards.SCENE_CARDS 对齐；此处不导入以免环）
_SCENE_CARD_KEYS = ("battle", "payoff", "emotion", "dialogue", "mystery", "lowkey")

# 组顺序（账本落盘与对外文档统一口径）
GROUP_ORDER = ("爽点", "冲突", "悬念", "情感", "过渡", "钩子", "反例")

GROUP_EXPECTED = {"爽点": 8, "冲突": 5, "悬念": 6, "情感": 6,
                  "过渡": 4, "钩子": 2, "反例": 5}

# spfmt 字段约定：
#   name  码名（通用类型学术语）
#   group 组名（GROUP_ORDER 之一）
#   rule  一句话判据（可指认、可对账的写法）
#   position 典型位置（章内锚点；跨章码写窗口）
#   spans (min, max) 典型跨度（章）
#   route_kw 路由词（本卡不消费，供后续轮细纲解析兜底与审校提示复用）
#   card  路由目标场景卡（_SCENE_CARD_KEYS 之一；"" = 位置码/反例码不路由）
#   advisory_only True = 反例码：只进审校/账本，不进路由
BRIDGE_CODES: dict[str, dict] = {
    # ---- 爽点 / 期待 8 码 ----
    "DL": {"name": "打脸", "group": "爽点", "spans": (1, 3),
           "rule": "前文占上风的人或论断，在本章被公开事实当众推翻",
           "position": "章中后段（压抑完成后兑现）",
           "route_kw": ("打脸", "当众", "揭穿"),
           "card": "payoff", "advisory_only": False},
    "PZ": {"name": "扮猪吃虎", "group": "爽点", "spans": (3, 10),
           "rule": "主角以低于实力的姿态入场，底牌只在冲突现场分层亮出",
           "position": "章中段入场、章末亮底",
           "route_kw": ("扮猪吃虎", "深藏不露", "藏拙"),
           "card": "payoff", "advisory_only": False},
    "LT": {"name": "亮底牌", "group": "爽点", "spans": (2, 6),
           "rule": "此前隐藏的关键筹码（底牌/关系/凭证）首次摊开使用",
           "position": "章末",
           "route_kw": ("亮底牌", "摊牌", "亮出"),
           "card": "payoff", "advisory_only": False},
    "QC": {"name": "绝境翻盘", "group": "爽点", "spans": (1, 3),
           "rule": "本章先入必败之局，再靠此前埋下的条件反败为胜",
           "position": "章末",
           "route_kw": ("绝境", "翻盘", "反败为胜"),
           "card": "battle", "advisory_only": False},
    "SJ": {"name": "收获兑现", "group": "爽点", "spans": (1, 2),
           "rule": "前文铺垫的收益（资源/宝物/名次/报酬）本章实际到手落袋",
           "position": "章中后段",
           "route_kw": ("收获", "到手", "进账", "落袋"),
           "card": "payoff", "advisory_only": False},
    "TP": {"name": "突破进阶", "group": "爽点", "spans": (1, 3),
           "rule": "境界/能力/职级发生一次可量化的档位跃升",
           "position": "章末或章中高潮点",
           "route_kw": ("突破", "进阶", "破境", "晋升"),
           "card": "payoff", "advisory_only": False},
    "PK": {"name": "公开价值确认", "group": "爽点", "spans": (1, 3),
           "rule": "主角的货物/作品/本事在公开场合被权威或市场定价确认",
           "position": "章中后段",
           "route_kw": ("拍卖", "鉴定", "定价", "竞价"),
           "card": "payoff", "advisory_only": False},
    "WS": {"name": "身份地位跃升", "group": "爽点", "spans": (2, 6),
           "rule": "社会身份/头衔/座次可见改变，旁人态度随之重排",
           "position": "章末",
           "route_kw": ("册封", "升职", "座次", "地位"),
           "card": "payoff", "advisory_only": False},
    # ---- 冲突 5 码 ----
    "ZY": {"name": "资源争夺", "group": "冲突", "spans": (3, 8),
           "rule": "两方以上围绕同一份稀缺资源正面对抗或竞价",
           "position": "章中段",
           "route_kw": ("争夺", "竞价", "抢占", "矿脉"),
           "card": "dialogue", "advisory_only": False},
    "DC": {"name": "派系内斗", "group": "冲突", "spans": (3, 10),
           "rule": "同一阵营内部两股以上势力为利益互相使绊",
           "position": "章中段",
           "route_kw": ("内斗", "派系", "倾轧", "内讧"),
           "card": "dialogue", "advisory_only": False},
    "DB": {"name": "大比", "group": "冲突", "spans": (3, 8),
           "rule": "有规则、有轮次、有公开观众席的定期竞技场合",
           "position": "章中后段（多章跨度）",
           "route_kw": ("大比", "擂台", "排名赛", "比武大会"),
           "card": "battle", "advisory_only": False},
    "MO": {"name": "算计", "group": "冲突", "spans": (2, 8),
           "rule": "一方设局，布局痕迹可回看，局在章内或近章收网",
           "position": "章末收网",
           "route_kw": ("设局", "算计", "圈套", "下套"),
           "card": "mystery", "advisory_only": False},
    "TS": {"name": "追杀", "group": "冲突", "spans": (2, 6),
           "rule": "存在明确追捕方与逃亡方，且本章内未彻底解除",
           "position": "章首入局",
           "route_kw": ("追杀", "追捕", "通缉", "逃亡"),
           "card": "battle", "advisory_only": False},
    # ---- 悬念 6 码 ----
    "MX": {"name": "谜团", "group": "悬念", "spans": (2, 10),
           "rule": "本章抛出至少一个与常识不符、暂不解释的未解之问",
           "position": "章中段抛出",
           "route_kw": ("谜团", "蹊跷", "怪事", "不解"),
           "card": "mystery", "advisory_only": False},
    "HT": {"name": "伏笔种", "group": "悬念", "spans": (5, 30),
           "rule": "本章植入一件当时不解释、后续章节回收的物件/信息/承诺",
           "position": "章中前段",
           "route_kw": ("埋下", "种下", "伏笔", "留下"),
           "card": "mystery", "advisory_only": False},
    "HC": {"name": "伏笔收", "group": "悬念", "spans": (1, 2),
           "rule": "此前埋下的伏笔在本章回收，或显式改期（不许无声挂起）",
           "position": "章中后段",
           "route_kw": ("回收", "揭晓", "应验", "兑现"),
           "card": "payoff", "advisory_only": False},
    "SF": {"name": "身份揭露", "group": "悬念", "spans": (3, 15),
           "rule": "某角色或势力的真实身份在章内被部分或全部揭开",
           "position": "章末",
           "route_kw": ("真实身份", "揭露", "暴露", "身份败露"),
           "card": "mystery", "advisory_only": False},
    "FY": {"name": "世界观反转", "group": "悬念", "spans": (5, 20),
           "rule": "本章给出一条颠覆读者既有认知的新规则或新史实",
           "position": "章中后段",
           "route_kw": ("颠覆", "真相", "史实", "规则竟是"),
           "card": "mystery", "advisory_only": False},
    "NG": {"name": "内鬼", "group": "悬念", "spans": (5, 20),
           "rule": "阵营内存在暗桩，本章给出指向性证据（不必实锤）",
           "position": "章末",
           "route_kw": ("内鬼", "暗桩", "细作", "奸细"),
           "card": "mystery", "advisory_only": False},
    # ---- 情感 6 码 ----
    "XL": {"name": "羁绊", "group": "情感", "spans": (2, 10),
           "rule": "两个角色的关系本章发生正向加固（共患难/托付/和解）",
           "position": "章中后段",
           "route_kw": ("羁绊", "托付", "并肩", "和解"),
           "card": "emotion", "advisory_only": False},
    "BL": {"name": "背叛", "group": "情感", "spans": (2, 8),
           "rule": "信任关系的持有者做出实质背叛行为（超出误会级别）",
           "position": "章末",
           "route_kw": ("背叛", "倒戈", "出卖"),
           "card": "emotion", "advisory_only": False},
    "SX": {"name": "牺牲", "group": "情感", "spans": (2, 8),
           "rule": "角色以让渡重大利益或生命为代价，换取他人存续或目标推进",
           "position": "章末",
           "route_kw": ("牺牲", "舍命", "代价"),
           "card": "emotion", "advisory_only": False},
    "CJ": {"name": "重逢", "group": "情感", "spans": (1, 3),
           "rule": "久别分离的角色或势力在本章重新照面",
           "position": "章中后段",
           "route_kw": ("重逢", "再会", "久别"),
           "card": "emotion", "advisory_only": False},
    "CC": {"name": "传承", "group": "情感", "spans": (2, 6),
           "rule": "技艺/意志/职责在两代人或师徒间完成一次正式交接",
           "position": "章中后段",
           "route_kw": ("传承", "衣钵", "接任"),
           "card": "emotion", "advisory_only": False},
    "HW": {"name": "感情线", "group": "情感", "spans": (5, 30),
           "rule": "主角与情感对象的关系推进一小步（靠近/表白/误会加深）",
           "position": "章末",
           "route_kw": ("表白", "心动", "情愫", "感情"),
           "card": "emotion", "advisory_only": False},
    # ---- 过渡 4 码 ----
    "DH": {"name": "换图升格", "group": "过渡", "spans": (1, 1),
           "rule": "本章完成舞台的大规模切换（进城/跨域/升入更高一层世界）",
           "position": "全章",
           "route_kw": ("换图", "迁往", "抵达", "新地图"),
           "card": "lowkey", "advisory_only": False},
    "SJ2": {"name": "闭关跳时", "group": "过渡", "spans": (1, 2),
            "rule": "主角进入封闭修炼或打造状态，时间被显式压缩跳过",
            "position": "章中段",
            "route_kw": ("闭关", "死关", "闭死关"),
            "card": "lowkey", "advisory_only": False},
    "GL": {"name": "经营蒙太奇", "group": "过渡", "spans": (2, 5),
           "rule": "以蒙太奇快写产业/势力/资产的经营增长",
           "position": "全章",
           "route_kw": ("经营", "产业", "扩张", "蒙太奇"),
           "card": "lowkey", "advisory_only": False},
    "LX": {"name": "日常缓冲", "group": "过渡", "spans": (1, 2),
           "rule": "无主线冲突的生活章，用于蓄压与关系存款",
           "position": "全章",
           "route_kw": ("日常", "休整", "缓冲", "生活"),
           "card": "lowkey", "advisory_only": False},
    # ---- 钩子 2 码（位置码：不路由场景卡，供细纲字段与钩型账本互引）----
    "YQ": {"name": "危机开局", "group": "钩子", "spans": (1, 1),
           "rule": "章首五百字内出现必须立刻应对的事件/异象/数字压力（非环境白描开局）",
           "position": "章首",
           "route_kw": ("变故", "异变", "危机"),
           "card": "", "advisory_only": False},
    "KT": {"name": "章末钩", "group": "钩子", "spans": (1, 1),
           "rule": "章末三段内抛出未闭合的新压力或新信息，迫使读者翻页",
           "position": "章末（最后三段）",
           "route_kw": ("章末钩", "翻页"),
           "card": "", "advisory_only": False},
    # ---- 反例 5 码（审校面证据码：只进审校/账本，不进路由）----
    "WATER": {"name": "注水", "group": "反例", "spans": (1, 1),
              "rule": "删除后不影响任何后续因果的段落占比过高",
              "position": "全章（审校）",
              "route_kw": (),
              "card": "", "advisory_only": True},
    "OOC": {"name": "崩坏", "group": "反例", "spans": (1, 1),
            "rule": "角色言行与已确立的动机、口吻、底线相悖",
            "position": "全章（审校）",
            "route_kw": (),
            "card": "", "advisory_only": True},
    "BAL": {"name": "战力失衡", "group": "反例", "spans": (1, 1),
            "rule": "交手结果与既有境界/资源设定矛盾，赢面无支撑",
            "position": "战斗段（审校）",
            "route_kw": (),
            "card": "", "advisory_only": True},
    "LOGIC": {"name": "降智", "group": "反例", "spans": (1, 1),
              "rule": "反派或配角为成全主角，做出明显低于其智力设定的选择",
              "position": "全章（审校）",
              "route_kw": (),
              "card": "", "advisory_only": True},
    "REP": {"name": "爽点同质化", "group": "反例", "spans": (10, 10),
            "rule": "近 10 章内同主码桥段连排 ≥3，套路感可指认",
            "position": "跨章·近 10 章窗口（账本/L0）",
            "route_kw": (),
            "card": "", "advisory_only": True},
}

# 细纲「- 桥段：」码行（本文件是解析与后续细纲模板指令共用的单一事实源）
_BRIDGE_LINE_RE = re.compile(r"^-\s*桥段[：:]\s*(.+?)\s*$", re.M)
# 整码 token：SJ2 与 SJ 必须作为不同 token 命中（贪婪吃掉尾随数字，防前缀截断）
_CODE_TOKEN_RE = re.compile(r"[A-Z][A-Z0-9]*")


def parse_bridge_codes(outline: str) -> tuple[str, str]:
    """解析细纲「- 桥段：DL(主)+MX(次)」码行 → (主码, 次码)。

    只认 BRIDGE_CODES 内的整码 token（码表外 token 忽略，不拦截——拦截属
    后续轮 L0 判据）；无行/无合法码返回 ("", "")。大小写不敏感。
    """
    m = _BRIDGE_LINE_RE.search(outline or "")
    if not m:
        return ("", "")
    codes: list[str] = []
    for tok in _CODE_TOKEN_RE.findall(m.group(1).upper()):
        if tok in BRIDGE_CODES and tok not in codes:
            codes.append(tok)
    main = codes[0] if codes else ""
    sub = codes[1] if len(codes) > 1 else ""
    return (main, sub)


def route_to_cards(genre_block_main: str = "", extra_keywords: str = ""):
    """桥段码优先路由：码行主码 → 目标场景卡；返回 (main, subs) 或 None。

    None = 无码行 / 主码为位置码（YQ/KT）或反例码（card=""）——调用方
    （scene_cards.chapter_to_cards）回退现有关键词路由。子卡：次码的场景卡
    （非 lowkey 且异于主卡时）按现有约定叠加。
    """
    main_code, sub_code = parse_bridge_codes(
        f"{genre_block_main or ''}\n{extra_keywords or ''}")
    if not main_code:
        return None
    main_card = BRIDGE_CODES[main_code].get("card", "")
    if main_card not in _SCENE_CARD_KEYS:
        return None
    subs: list[str] = []
    if main_card != "lowkey":
        subs.append("lowkey")
    if sub_code:
        sub_card = BRIDGE_CODES[sub_code].get("card", "")
        if sub_card in _SCENE_CARD_KEYS and sub_card != main_card and sub_card not in subs:
            subs.append(sub_card)
    return (main_card, subs)


def enabled_from_cfg(cfg: dict | None) -> bool:
    """读 cfg 开关；缺省 off（字节隔离纪律：关 = 本模块产出零消费）。"""
    section = (cfg or {}).get(CFG_SECTION) or {}
    try:
        return bool(section.get(CFG_KEY, DEFAULT_ENABLED))
    except AttributeError:  # pragma: no cover - 非映射配置按关态处理
        return False
