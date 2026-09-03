"""plan v3 C1 - 场景卡（6 类）·汉化关键词增强版

TUI 原本只有英文关键词路由（battle/fight/duel...），对中文细纲命中率≈0。
本版加中文关键词字典，并提供中文标签（label_zh）+ 中文化 method 翻译，
使 chapter_to_cards() 能正确路由中文细纲，render_cards_zh() 输出中文注入。
"""

# ---- 6 张场景卡（保留英文 method/example 不变，作为 LLM 技法提示）----

SCENE_CARDS = {
  "battle": {
    "label": "battle",
    "label_zh": "战斗",
    "method": [
      "Round-based: goal -> probe -> exchange -> cost -> settle",
      "Space anchors: terrain/light/distance change each round",
      "Damage = body part + function loss, NEVER abstract HP",
      "Observable cost: stamina/position/cover/psychology, not just -HP",
    ],
    "method_zh": [
      "回合制：目标→试探→交锋→代价→收束",
      "空间锚点：每回合的地形/光线/距离都不同",
      "伤害=身体部位+功能丧失，禁止抽象 HP 数字",
      "可观察代价：体力/位置/掩体/心理，而非单纯扣血",
    ],
    "example": "Chen Luo crept along the wall — the moss damp from the brick crack behind him. Sword point tilted 3 inches; he jammed his short blade into the bamboo curtain. The bamboo snapped clean — but his short blade had already reached the wrist holding the sword.",
    "axes": ["Quick: 3 rounds, minimal action", "Attrition: 6+ rounds, layered wear", "Psyche: <=4 rounds, dual-intent hidden"],
  },
  "payoff": {
    "label": "payoff",
    "label_zh": "爽点",
    "method": [
      "Setup pressure <= payoff length: identifiable injustice/mockery/silence",
      "Reversal action: decide -> act -> hit, NO he-figured-it-out announcement",
      "Bystander reaction >= 1/4 length: ally/opponent/onlooker differentiated",
      "Settlement token: number / status symbol / onlooker attitude — pick one",
    ],
    "method_zh": [
      "铺垫压力≤爽点长度：可指认的不公/嘲讽/沉默",
      "反转动作：决定→出手→命中，禁止'他恍然大悟'式宣告",
      "围观反应≥1/4 长度：盟友/对手/旁观者差异化",
      "结算镜头：数字/地位符号/旁观者态度，三选一",
    ],
    "example": "Chen Luo tilted the brush washer glaze toward the streetlight. The three vein-lines flipped a page of gloss. Behind him came a fist on the table — three hundred! — not him shouting, it was the old-timer next door.",
    "axes": ["Hard: instant incoming", "Soft: status/respect/belonging change", "Chain: two adjacent payoffs"],
  },
  "emotion": {
    "label": "emotion",
    "label_zh": "情绪",
    "method": [
      "Physiological chain: stimulus -> body -> action loss -> cognitive lag",
      "NEVER name emotions, only act out (symptom + behavior)",
      "Pressure made concrete: WHICH consequence of X, not X in general",
      "Anti-climax after peak: he sat down / he turned to latrine",
    ],
    "method_zh": [
      "生理链：刺激→身体→动作丧失→认知滞后",
      "禁止命名情绪，只演症状+行为",
      "压力具象化：X 的哪个具体后果，而非 X 本身",
      "高潮后反高潮：他坐下了/他转身去茅房",
    ],
    "example": "When his fingers touched the washer, the temperature felt drained by half a degree — not cold, empty. He did not pull back, flipped the washer glaze up. His shoulder blade twitched under the cloth — he did not notice, the stall-keeper did.",
    "axes": ["Suppressed: strong physiology", "Outburst: bystander observer", "Silent: body+action only"],
  },
  "dialogue": {
    "label": "dialogue",
    "label_zh": "对话",
    "method": [
      "Per-character speech fingerprint: length/address/tic",
      "Each round advances info or pressure",
      "<= 8 rounds MUST insert action/environment beat",
      "Ends non-consensual: one side stops or one conclusion line",
    ],
    "method_zh": [
      "角色台词指纹：句长/称呼/口头禅差异化",
      "每轮推进信息或压力",
      "≤8 轮必须插入动作/环境节拍",
      "非共识收尾：一方停下或一句结论性台词",
    ],
    "example": "'This washer is fake.' The stall-keeper looked again. 'The glaze is old.' 'Then look at the base.' He flipped, saw the bottom mark. Silence. 'Three hundred.' 'I am not selling to you.'",
    "axes": ["Push: A pushes B pushes C", "Confrontation: up the stakes", "Pure dialogue: short sentences"],
  },
  "mystery": {
    "label": "mystery",
    "label_zh": "悬疑",
    "method": [
      "3-column info gap: char knows / char thinks / reader knows — at least 1 differs",
      "Delayed delivery: half + 1 anomalous detail, NEVER answer in 1 go",
      "Discover -> Track -> Reveal: 3 time points",
      "Fair play: clues shown in first 1/3",
    ],
    "method_zh": [
      "三栏信息差：角色知/角色想/读者知，至少 1 栏不同",
      "延迟交付：半+1 异常细节，禁止一次性给答案",
      "发现→追踪→揭示：3 个时间点",
      "公平解谜：线索在前 1/3 出场",
    ],
    "example": "The blue-and-white on the base was one shade lighter than the glaze. This cobalt is usually fired from the same kiln — should not differ. Unless the base was later repaired. He pressed his fingertip — right there, a hair-thin seam.",
    "axes": ["Physical: weight/temp/seam", "Speech-act: behavior contradiction", "Numerical: accounts/time/distance"],
  },
  "lowkey": {
    "label": "lowkey",
    "label_zh": "日常",
    "method": [
      "Relationship deposit: specific object/promise to be collected later",
      "Daily detail warmth: meal/walk/sky with 1 specific small action",
      "Relationship progression: -1 to +1 micro, not jump table",
      "End with room: atmosphere/position/action freeze, not forced hook",
    ],
    "method_zh": [
      "关系存钱罐：具体物件/承诺，留待后文兑现",
      "日常细节温度：一餐/一走/一景带 1 个具体小动作",
      "关系推进：-1 到 +1 的微调，禁止跳表",
      "留白收尾：氛围/位置/动作定格，不强求钩子",
    ],
    "example": "When Chen Luo got home it was already dark. Porridge still warm. His mother sat peeling beans: 'Eat.' He sat, brought the bowl. The porridge was thin but had red dates — she usually could not bear to use them. He did not ask, ate half a bowl. 'I am off the day after tomorrow.' Her hand paused, then continued.",
    "axes": ["Repair: mend a tiny crack", "Accumulation: stockpile chips", "Token: bury object/promise"],
  },
}

# ---- 轴变体汉化（SCENE_CARDS["axes"] 是英文技法标签，中文注入时整行会漏英文）----

AXES_ZH = {
    "battle": ["快攻：3 回合内解决，动作精简",
               "消耗：6 回合以上，损耗层层加码",
               "心理：≤4 回合，双重意图暗写"],
    "payoff": ["硬爽：反击当场到来，不隔夜",
               "软爽：地位/尊重/归属发生位移",
               "连环：两个爽点前后相接，前一个引出后一个"],
    "emotion": ["压抑：身体反应重，语言反而轻",
                "爆发：借在场者的眼睛来写",
                "无声：只写身体与动作，不写一句心理"],
    "dialogue": ["进逼：A 逼 B，B 再逼 C，压力单向传导",
                 "对峙：赌注逐轮抬高，谁先退让谁说软话",
                 "纯对话：短句推进，节拍靠小动作切开"],
    "mystery": ["实物：重量/温度/接缝/成色",
                "言行：行为与说法自相矛盾",
                "数字：账目/时间/距离对不上"],
    "lowkey": ["修复：把上一场留下的一道小裂缝补上",
               "积累：攒下筹码、默契与信息",
               "信物：埋下一件物件或一句承诺"],
}


# ---- 中英文双语关键词字典（路由更准）----

_KEYWORDS = {
    "battle": [
        # 英文（兼容 TUI 路由）
        "battle", "fight", "duel", "arena", "ambush", "hunt", "clash",
        # 中文（细纲实际写法）
        "打", "战", "斗", "场", "擂台", "比武", "决斗", "偷袭", "围剿", "搏斗",
        "厮杀", "交锋", "拼杀", "对攻", "过招", "出手", "格挡", "闪避",
    ],
    "payoff": [
        # 英文
        "payoff", "face-slap", "reveal", "settle", "dominate", "counter-attack", "humble-brag",
        # 中文
        "爽", "反", "打脸", "反杀", "逆袭", "翻盘", "绝杀", "碾压", "装逼",
        "出气", "当众", "揭露", "亮出", "揭穿", "反转", "扬眉吐气", "出人意料",
    ],
    "emotion": [
        # 英文
        "emotion", "sad", "anger", "grief", "break", "mirror",
        # 中文
        "哭", "悲", "怒", "恨", "痛", "伤", "崩", "丧", "泪", "崩溃",
        "心碎", "绝望", "委屈", "愧疚", "自责", "落寞", "怅然", "激动",
    ],
    "dialogue": [
        # 英文
        "dialogue", "negotiate", "discuss", "interrogate", "testimony",
        # 中文（避免单字"对"误匹配，改用 2 字+ 词组）
        "谈判", "问讯", "对质", "劝说", "说服", "辩论", "议事", "对话为主",
        "口供", "询问", "审讯", "商量", "商议", "议论", "交涉", "审问",
        "讨论", "开口", "回应", "答话", "辩驳", "口角",
    ],
    "mystery": [
        # 英文
        "mystery", "clue", "discover", "track", "doubt", "investigate",
        # 中文
        "谜", "疑", "案", "线索", "发现", "追踪", "调查", "推理", "疑点", "不对劲",
        "异常", "反常", "蛛丝马迹", "疑团", "悬案", "破绽",
    ],
    # lowkey: 兜底（无关键词命中时）
    "lowkey": [],
}


def chapter_to_cards(genre_block_main="", extra_keywords=""):
    """根据细纲文本路由场景卡。

    Returns:
        (main_key, sub_keys_list)  例如 ("battle", ["lowkey", "mystery"])
    """
    text = (genre_block_main + " " + extra_keywords).lower()
    main = "lowkey"

    # payoff 优先于 battle：避免 "打脸" 误匹配到 battle 的 "打"
    # 优先级：payoff > battle > emotion > dialogue > mystery > lowkey
    if any(w in text for w in _KEYWORDS["payoff"]):
        main = "payoff"
    elif any(w in text for w in _KEYWORDS["battle"]):
        main = "battle"
    elif any(w in text for w in _KEYWORDS["emotion"]):
        main = "emotion"
    elif any(w in text for w in _KEYWORDS["dialogue"]):
        main = "dialogue"
    elif any(w in text for w in _KEYWORDS["mystery"]):
        main = "mystery"

    sub = []
    if main != "lowkey":
        sub.append("lowkey")
    if main != "mystery" and any(w in text for w in _KEYWORDS["mystery"]):
        sub.append("mystery")
    if main != "dialogue" and any(w in text for w in _KEYWORDS["dialogue"]):
        sub.append("dialogue")
    if main == "lowkey":
        # 日常过场章：可加一个 mystery 暗线或 dialogue 收尾
        if any(w in text for w in _KEYWORDS["mystery"]):
            sub.append("mystery")
    # 按插入序去重：set() 的顺序随进程哈希随机化，会让同一细纲每次拼出不同 prompt
    return main, [k for i, k in enumerate(sub) if k not in sub[:i]]


def render_cards(main_key, sub_keys, ch_no, total, lang="zh"):
    """渲染场景卡提示块（注入到 CHAPTER_OUTLINE_PROMPT）。

    Args:
        main_key: 主卡键
        sub_keys: 子卡键列表
        ch_no: 当前章号
        total: 总章数
        lang: "zh" 输出中文版；"en" 输出原 TUI 英文版
    """
    axis = (ch_no + total) % 3
    out = [f"[scene card ch{ch_no} route={main_key}]"]
    main = SCENE_CARDS[main_key]
    label = main["label_zh"] if lang == "zh" else main["label"]
    methods = main["method_zh"] if lang == "zh" else main["method"]

    out.append(f"### 主卡：{label}" if lang == "zh" else f"### main: {label}")
    for m in methods:
        out.append(f"- {m}")
    if lang == "zh":
        out.append(f"### 轴变体：{AXES_ZH[main_key][axis]}")
    else:
        out.append(f"### axis: {main['axes'][axis]}")
    for sk in sub_keys:
        if sk in SCENE_CARDS:
            sub = SCENE_CARDS[sk]
            sub_label = sub["label_zh"] if lang == "zh" else sub["label"]
            sub_methods = sub["method_zh"][:2] if lang == "zh" else sub["method"][:2]
            if lang == "zh":
                out.append(f"### 叠加：{sub_label}")
            else:
                out.append(f"### overlay: {sub_label}")
            for m in sub_methods:
                out.append(f"- {m}")
    return "\n".join(out)


def hint_for_chapter(num: int, total: int, outline: str, extra: str = "") -> str:
    """为细纲 prompt 注入场景卡提示（一行版，不展开 example 避免 prompt 膨胀）。

    Returns:
        一行字符串，例如 "## 本章主卡：战斗（回合制·试探→交锋→代价）｜子卡：日常"
    """
    main, subs = chapter_to_cards(outline, extra)
    main_zh = SCENE_CARDS[main]["label_zh"]
    if not subs:
        return f"## 本章主卡：{main_zh}"
    sub_zh = "、".join(SCENE_CARDS[s]["label_zh"] for s in subs)
    return f"## 本章主卡：{main_zh}｜子卡：{sub_zh}"


def craft_block(num: int, total: int, outline: str, extra: str = "") -> str:
    """正文用工艺路线：主卡全套手法 + 本章轴变体 + 子卡前两条手法。

    与 hint_for_chapter 的分工：细纲只要知道「这章是什么戏」，正文要知道「这场戏怎么演」。
    不含标题行（标题由 prompt 模板给）、不含 example（示例句会被模型当成情节抄）。
    """
    main, subs = chapter_to_cards(outline, extra)
    axis = (num + total) % 3
    card = SCENE_CARDS[main]
    out = [f"主卡·{card['label_zh']}（本章演法：{AXES_ZH[main][axis]}）"]
    out += [f"- {m}" for m in card["method_zh"]]
    for sk in subs[:2]:
        sub = SCENE_CARDS[sk]
        out.append(f"叠加·{sub['label_zh']}")
        out += [f"- {m}" for m in sub["method_zh"][:2]]
    return "\n".join(out)
