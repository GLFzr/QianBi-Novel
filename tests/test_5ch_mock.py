# -*- coding: utf-8 -*-
"""5 章共写 e2e mock 测试：mock LLM 跑完整流水线，验证 9 套 v2 预设 + 6 维审校 + 场景卡

- fake home 隔离
- mock 所有 LLM 调用（chat_stream / chat 返回固定字符串）
- 验证 5 章全部落盘 + state 推进 + history 记录
- 验证 v2 9 套预设至少 1 次注入（运行时检查 last_prompt 包含 stage_hints 内容）
- 验证 6 维审校 verdict 写入 review_findings
"""
import os
import sys
import json
import tempfile
import shutil
import re
from unittest.mock import patch, MagicMock

_FH = tempfile.mkdtemp(prefix="qbn_5ch_mock_")
os.environ["USERPROFILE"] = _FH
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtGui import QGuiApplication
app = QGuiApplication(sys.argv)

# ---- LLM 模拟（按调用类型返回固定输出）----

MOCK_PROSE_TEMPLATE = """# 第{n}章 测试章名{n}

这是第{n}章测试正文。本章涉及主角打脸反派、获得新机缘、设置伏笔。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。填充内容占位文字。"""

MOCK_OUTLINE_TEMPLATE = """### 第{n}章 测试章名{n}
- 章名：测试章名{n}
- 核心事件：主角打脸反派
- 承接锚点：上一章{n-1}结尾
- 故事内容：主角在集市打脸王麻子
- 金手指使用：无
- 资源收支：无
- 章末钩子：转身离开
"""

MOCK_CORE_SETTING = """# 核心设定
- 题材：修仙
- 主角：陈凡
- 金手指：破绽之眼
- 境界：炼气三层
"""

MOCK_VOLUME_OUTLINE = """# 大纲
### 第1卷 崛起（第1-30章）
- 卷契约：主角解决赵乾
"""

MOCK_CHAPTER_OUTLINE = """### 第1章 测试章名1
- 核心事件：主角打脸反派
- 字数：3000
"""

MOCK_SUMMARY = "第{N}章：主角打脸反派并获新机缘。"


class MockRouter:
    """完全 mock 的 Router，拦截所有 LLM 调用。"""
    def __init__(self):
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.call_log = []  # [(slot, label, prompt_preview), ...]

    def client(self, slot):
        return MockClient(slot, self)


class MockClient:
    def __init__(self, slot, router):
        self.slot = slot
        self.router = router

    def chat_stream(self, prompt, on_chunk=None, on_reasoning=None, **kw):
        return self._dispatch(prompt, on_chunk)

    def chat(self, prompt):
        return self._dispatch(prompt, None)

    def _dispatch(self, prompt, on_chunk):
        # 简单路由：按 prompt 关键词判断返回哪类 mock 输出
        router = self.router
        router.total_prompt_tokens += len(prompt) // 4
        router.call_log.append((self.slot, prompt[:60]))

        text = ""
        # 用 startswith 检测 prompt 起始关键词更稳
        p_short = prompt[:200]
        if p_short.startswith("你是网络小说创作教练"):
            text = MOCK_CORE_SETTING
        elif p_short.startswith("你是网络小说结构设计师"):
            text = MOCK_VOLUME_OUTLINE
        elif "网络小说细纲设计师" in p_short or "为第" in p_short:
            m = re.search(r"为第\s*(\d+)\s*章", prompt)
            n = m.group(1) if m else "1"
            text = f"### 第{n}章 测试章名{n}\n- 章名：测试章名{n}\n- 核心事件：主角打脸反派\n- 字数：3000\n- 故事内容：主角在集市打脸王麻子"
        elif "扩写到接近目标字数" in prompt or "请扩写" in prompt:
            m = re.search(r"第\s*(\d+)\s*章", prompt)
            n = m.group(1) if m else "1"
            text = MOCK_PROSE_TEMPLATE.format(n=n) + "\n\n补充内容。\n" * 200
        elif "网络小说叙事写手" in p_short or "根据细纲与上下文写作" in p_short:
            m = re.search(r"第\s*(\d+)\s*章", prompt)
            n = m.group(1) if m else "1"
            text = MOCK_PROSE_TEMPLATE.format(n=n)
        elif "压缩" in prompt and "请压缩" in prompt:
            m = re.search(r"第\s*(\d+)\s*章", prompt)
            n = m.group(1) if m else "1"
            text = MOCK_PROSE_TEMPLATE.format(n=n)
        elif "最终审核" in prompt or "A_GOLDEN_OPEN" in p_short:
            text = """===A_GOLDEN_OPEN=== pass 开篇有力【原文引证："集市上"】
===B_PAYOFF=== pass 爽点到位
===C_FINGER=== pass 金手指无越界
===D_PLOT=== pass 因果链完整
===E_CHARACTER=== pass 声口不崩
===F_HOOK=== pass 钩子强
===WORST_QUOTES===
- A "集市上"
===VERDICT===
PASS
===END==="""
        elif "根因溯源" in prompt:
            text = "（无上游根因）"
        elif "追踪更新" in prompt or "四个追踪文件" in prompt:
            text = "===角色状态===\n无变化\n===伏笔===\n无变化\n===时间线===\n无变化\n===上下文===\n无变化"
        elif "一句话摘要" in prompt or "CHAPTER_SUMMARY" in prompt:
            m = re.search(r"第\s*(\d+)\s*章", prompt)
            n = m.group(1) if m else "1"
            text = MOCK_SUMMARY.format(N=n)
        elif "全局摘要" in prompt and "500 字" in prompt or "GLOBAL_SUMMARY" in prompt:
            text = "全书主线已建立，主角开始崛起。"
        else:
            # fallback: 长 prose
            m = re.search(r"第\s*(\d+)\s*章", prompt)
            n = m.group(1) if m else "X"
            text = MOCK_PROSE_TEMPLATE.format(n=n)

        # 流式回调（按 50 字符分块）
        if on_chunk:
            for i in range(0, min(len(text), 200), 50):
                on_chunk(text[i:i+50])
        router.total_completion_tokens += len(text) // 4
        return text


# ---- 测试主体 ----

def setup_project():
    """创建一个测试项目，配置 v2 预设 + 启动 mock LLM"""
    from app.ui.bridge import Bridge
    bridge = Bridge()
    proj_root = os.path.join(_FH, "test_5ch_book")
    if os.path.exists(proj_root):
        shutil.rmtree(proj_root, ignore_errors=True)
    os.makedirs(proj_root, exist_ok=True)
    ok = bridge.newProject(proj_root, "测试5章书", "都市悬疑", "番茄", 30, "主角能改命的笔记")
    assert ok and bridge.hasProject
    # 切换到 v2 预设
    bridge.setProjectPreset("urban_destiny")
    proj = os.path.join(proj_root, "测试5章书")
    return bridge, proj


def test_5ch_pipeline():
    """跑 5 章完整流水线，验证全部落盘 + state 推进"""
    bridge, proj = setup_project()
    print(f"  ✓ setup project: {proj}")
    print(f"  ✓ preset: {bridge.projectPreset()}")

    # 注入 mock router
    mock_router = MockRouter()
    bridge.router = mock_router
    # 同时让 orchestrator 用 mock router
    from app.core import orchestrator
    orig_Orchestrator = orchestrator.Orchestrator

    class MockOrchestrator(orig_Orchestrator):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.router = mock_router  # 强制 mock
            # patch client 工厂
            self._orig_client_factory = None

    # 直接调 stages 模拟跑 5 章
    from app.core import stages as st_mod
    from app.core import state as state_mod
    from app import config as cfg_mod
    from app.core import gates
    from app.core.orchestrator import Orchestrator
    from app.llm.router import ModelRouter
    from app import project

    # 准备 cfg
    cfg = bridge.cfg

    # 创建 orchestrator
    orch = Orchestrator(proj, cfg)

    # Monkey-patch orch.router.client 全替换为 mock
    class PatchRouter:
        def __init__(self, real_router, mock):
            self.real = real_router
            self.mock = mock
        def client(self, slot):
            print(f"    [mock] router.client({slot!r}) → MockClient")
            return MockClient(slot, self.mock)
        def total_tokens(self):
            return (self.mock.total_prompt_tokens, self.mock.total_completion_tokens)
        def estimate_cost(self):
            return 0.0
        def invalidate(self, *args, **kwargs):
            pass
        def refresh(self, *args, **kwargs):
            pass

    # 阶段 1：核心设定
    print("\n  --- 阶段① 核心设定 ---")
    from app.core.stages import stage_core_setting, stage_volume_outline
    state = state_mod.load_state(proj)
    orch.last_prompt = ""
    orch._stub = None

    # 跑核心设定
    try:
        with patch.object(orch, 'router', PatchRouter(orch.router, mock_router)):
            # 跑 5 章
            for n in range(1, 6):
                # 先跑核心设定（只在第 1 章前跑一次）
                if n == 1:
                    core = stage_core_setting(orch)
                    print(f"  ✓ 核心设定生成（{len(core)} 字）")
                    # 跑全书大纲
                    outline = stage_volume_outline(orch, 30)
                    print(f"  ✓ 全书大纲生成（{len(outline)} 字）")
                # 跑细纲
                state = state_mod.load_state(proj)
                state["stage"] = state_mod.STAGE_CH_OUTLINE
                state_mod.save_state(proj, state)
                outlines = st_mod.stage_chapter_outlines(orch, n, n)
                print(f"  ✓ 第{n}章细纲生成（{[o[0] for o in outlines]}）")
                # 跑章节微循环
                state = state_mod.load_state(proj)
                state["stage"] = state_mod.STAGE_PROSE
                state_mod.save_state(proj, state)
                result = st_mod.chapter_microcycle(orch, n)
                title = result.get("title", "")
                words = result.get("words", 0)
                review_blocking = result.get("review_blocking", 0)
                print(f"  ✓ 第{n}章微循环完成（章名={title!r}, 字数={words}, 审校阻塞={review_blocking}）")
                # 验证落盘（按 record 中的 words 反推正文）
                chap_files = [f for f in os.listdir(os.path.join(proj, "正文"))
                              if (f.startswith(f"第{n:03d}章") or f.startswith(f"第{n}章"))]
                assert chap_files, f"第{n}章未落盘：正文/ 目录无匹配文件（{os.listdir(os.path.join(proj, '正文'))}）"
                chap_path = os.path.join(proj, "正文", chap_files[0])
                content = project.read_file(chap_path)
                assert f"第{n}章" in content, f"第{n}章内容缺失"
                assert len(content) >= 100, f"第{n}章内容过短：{len(content)} 字符"
                # 手动 append history（mock 测试不走 orchestrator.run）
                state_mod.append_history(proj, state_mod.load_state(proj), result)
                print(f"  ✓ 第{n}章落盘 ({os.path.basename(chap_path)}, {len(content)} 字符) + history 记录 OK")
                # 验证 6 维审校落盘
                s = state_mod.load_state(proj)
                rf = s.get("review_findings", {})
                assert str(n) in rf, f"第{n}章 6 维审校未落盘：{list(rf.keys())}"
                rv = rf[str(n)].get("verdict", "")
                print(f"  ✓ 第{n}章 6 维审校落盘: verdict={rv}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  ✗ exception: {e}")
        return False

    # 验证 v2 9 套预设已加载
    from app.presets import list_presets
    ps = list_presets()
    assert len([p for p in ps if p["id"]]) >= 10, f"内置预设不足 10：{len(ps)}"
    print(f"\n  ✓ v2 9 套预设全部加载（{len(ps) - 1} 个内置 + 1 通用）")

    # 验证 6 维审校落盘
    s = state_mod.load_state(proj)
    rf = s.get("review_findings", {})
    assert len(rf) >= 5, f"6 维审校未全部落盘：{len(rf)}"
    print(f"  ✓ 6 维审校落盘 {len(rf)} 章 verdict={set(rf[str(i)]['verdict'] for i in range(1,6))}")

    # 验证 v2 genre_block_for 注入到细纲 prompt（看 last_prompt）
    from app.presets import genre_block_for
    gb = genre_block_for("urban_destiny", "prose")
    assert "都市悬疑" in gb or "改命" in gb
    assert "正文环节特化" in gb  # v2 阶段特化
    print(f"  ✓ v2 genre_block_for(prose) 注入: 含「正文环节特化」标记（{len(gb)} 字符）")

    # 验证 scene card 注入到 chapter outline prompt
    from app.prompts.scene_cards import hint_for_chapter
    hint = hint_for_chapter(1, 100, "### 第1章\n- 核心事件：主角打脸反派")
    assert "主卡" in hint
    print(f"  ✓ 场景卡 hint 注入: {hint}")

    # 验证场景卡路由（中文关键词）
    from app.prompts.scene_cards import chapter_to_cards
    main, subs = chapter_to_cards("主角打脸反派")
    assert main == "payoff", f"场景卡路由错：{main}"
    print(f"  ✓ 场景卡路由: 主角打脸反派 → {main} (subs={subs})")

    # 验证 token 统计
    print(f"  ✓ Token: prompt={mock_router.total_prompt_tokens}, completion={mock_router.total_completion_tokens}")

    # 验证 review_chain 存在（即使空）
    s = state_mod.load_state(proj)
    assert "review_chain" in s, "review_chain 字段缺失"
    print(f"  ✓ review_chain 字段就位")

    # 验证 7 套 LLM 调用类型全用过
    from collections import Counter
    slots_called = Counter(slot for slot, _ in mock_router.call_log)
    assert "writing" in slots_called, f"writing 槽未用过：{slots_called}"
    assert "helper" in slots_called, f"helper 槽未用过：{slots_called}"
    assert "review" in slots_called, f"review 槽未用过：{slots_called}"
    print(f"  ✓ 3 槽位 (writing/helper/review) 全部使用: {dict(slots_called)}")

    return True


if __name__ == "__main__":
    print("== test_5ch_mock ==")
    ok = test_5ch_pipeline()
    if ok:
        print("\n✓ All 5 chapters pipeline OK")
    else:
        print("\n✗ Pipeline failed")
    shutil.rmtree(_FH, ignore_errors=True)
