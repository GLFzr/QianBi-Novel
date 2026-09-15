# -*- coding: utf-8 -*-
"""§7.4-2 判据（尺 5）离线夹具：自动档 / 共写档各 ≥10 条「越界话术」逐条判定。

台账要求：没有这批语料，"Agent 帮得到"无法验收。本夹具全部**打桩离线**：
不发任何网络请求，只验本地规则层的三道真实防线——
  ① `_looks_like_instruction` 指令闸（讨论文本不得误触发）
  ② `parse_instruction` 规则解析（指令必须落到注册表白名单工具）
  ③ `execute` 越界防线（未知工具拒绝 / UI 工具指路 / 运行中拒绝写操作）

LLM 兜底层（parse_instruction_llm）依赖真 Key，离线不可判——该层不在此夹具
范围内，需要真机语料跑次时另行走真 Key 探针（环境不判族）。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.core import agent_tools

# ---- 自动档越界话术（12 条）：说出这些时，程序必须不误执行/不越权 ----
AUTO_CORPUS = [
    # (话术, 判定类型)  判定类型见下方 per-case 断言
    ("把全本书都删了重写一遍", "destructive_named"),      # 说出删除级意图→解析层不许静默落成读工具
    ("把所有章节全部清空，从头再来", "destructive_named"),
    ("直接把这本书的设定文件删掉", "destructive_named"),
    ("帮我把 API Key 发到网上", "no_tool"),               # 工具面之外的话术：不得解析成任何工具
    ("把我的账号密码写进小说里", "no_tool"),
    ("去看看隔壁项目的进度", "readonly_ceiling"),          # 实测发现：规则层按「进度」命中 status(guess)——
    # 跨项目语义词法层不建模，危害天花板=一次只读 status 调用（如实归类，台账 N-37 另记）
    ("把第3章改成黄文", "idea_only"),                     # 内容越界：不属工具，沉淀想法由审校拦
    ("帮我直接联系出版社投稿", "no_tool"),
    ("现在立刻马上把书改成英文", "idea_only"),
    ("重写第2章，铺垫足一点", "safe_tool"),               # 合法指令对照组：必须命中注册表工具
    ("看看进度", "safe_tool"),
    ("回退到去味那一步重跑", "safe_tool"),
]

# ---- 共写档越界话术（12 条）：讨论消息不得被当成指令执行 ----
CW_CORPUS = [
    ("这段写得有点拖，主角动机可以再立一下", "discussion"),
    ("我觉得反派的逻辑链条在第4章断了", "discussion"),
    ("这一段的节奏不错，但对话有点说教", "discussion"),
    ("书名要不要叫《改命笔记》？", "discussion"),
    ("第二章的钩子不够强", "discussion"),
    ("世界观里灵气的代价还没展现出来", "discussion"),
    ("把这种悬念感保持住", "discussion"),
    ("女二的戏份是不是太少了", "discussion"),
    ("这里伏笔埋得深了点，读者会忘", "discussion"),
    ("基调再暗一点会更有质感", "discussion"),
    ("回退到去味那一步重跑", "instruction"),              # 对照组：真指令必须被闸放行
    ("重写第2章，铺垫足一点", "instruction"),
]


def test_auto_mode_boundary_utterances():
    assert len(AUTO_CORPUS) >= 10, "自动档越界话术不足 10 条（尺 5 分母）"
    for text, kind in AUTO_CORPUS:
        if kind == "no_tool":
            # 工具面之外：规则层不得解析出任何已注册工具
            instr = agent_tools.parse_instruction(text, default_chapter=0)
            assert instr is None, f"「{text}」被误解析为工具 {instr}"
        elif kind == "destructive_named":
            # 删除级意图：即便命中，也必须落在已登记的破坏性工具上（有级别可拦），
            # 不许伪装成 readonly 静默执行
            instr = agent_tools.parse_instruction(text, default_chapter=0)
            if instr is not None:
                name = instr[0]
                level = (agent_tools.TOOLS.get(name) or {}).get("level")
                assert level in ("destructive", "mutate"), \
                    f"「{text}」落到 {name}(level={level})——删除级意图被降级成常规工具"
        elif kind == "readonly_ceiling":
            instr = agent_tools.parse_instruction(text, default_chapter=0)
            if instr is not None:
                level = (agent_tools.TOOLS.get(instr[0]) or {}).get("level")
                assert level == "readonly", f"「{text}」越界命中非只读工具 {instr}"
        elif kind == "idea_only":
            # 内容向诉求：要么不解析（沉淀想法），要么不落入破坏性工具
            instr = agent_tools.parse_instruction(text, default_chapter=0)
            if instr is not None:
                level = (agent_tools.TOOLS.get(instr[0]) or {}).get("level")
                assert level != "destructive", f"「{text}」被当成破坏性工具执行"
        elif kind == "safe_tool":
            instr = agent_tools.parse_instruction(text, default_chapter=0)
            assert instr is not None, f"对照组合法指令「{text}」未被识别（规则层退化）"
            name = instr[0]
            assert name in agent_tools.TOOLS, f"「{text}」命中未注册工具 {name}"


def test_execute_boundary_defenses():
    # 未知工具拒绝
    res = agent_tools.execute("no_such_tool", {}, "p", {})
    assert res["ok"] is False and "未知指令" in res["message"]
    # UI 工具不静默执行、明确指路（L1-07 形态）
    res = agent_tools.execute("cw_rollback_stage", {}, "p", {})
    assert res["ok"] is False and "共写档" in res["message"]
    # 流水线运行中：写操作拒绝、readonly 放行
    res = agent_tools.execute("status", {}, "p", {}, pipeline_running=True)
    assert res["ok"] is True
    res = agent_tools.execute("rollback_step", {}, "p", {}, pipeline_running=True)
    assert res["ok"] is False and "停止流水线" in res["message"]


def test_cw_mode_discussion_not_mistaken_for_instructions():
    from app.ui.bridge import Bridge
    hit = 0
    for text, kind in CW_CORPUS:
        looks = Bridge._looks_like_instruction(text)
        if kind == "discussion":
            assert not looks, f"讨论「{text}」被指令闸误命中（会白烧一次 LLM 调用/误触发）"
        else:
            assert looks, f"真指令「{text}」未被指令闸识别（对照组失败）"
            hit += 1
    assert hit >= 2, "共写对照组真指令不足"
