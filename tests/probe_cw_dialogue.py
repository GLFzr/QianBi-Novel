# -*- coding: utf-8 -*-
"""共写档对话循环探针（router 打桩，无网络）：DialogueWorker/SummarizeWorker/build_handoff
- 断言 user body 注入（方案①）：角色提示词 + 交接块 + 转写 + 本轮输入
- 断言槽位映射：core/outline/prose→writing，worldbook/unit→helper
- 断言总结定稿 → build_handoff 拆分 → 交接块落 state → 下一阶段只读交接块
"""
import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QCoreApplication
app = QCoreApplication(sys.argv)

from app import project, prompts
from app.core import state as st
from app.core import co_dialogue
from app.core.co_dialogue import DialogueWorker, SummarizeWorker

results = []


def check(name, cond):
    results.append((name, bool(cond)))


class StubClient:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def chat_stream(self, prompt, on_chunk=None, on_reasoning=None):
        self.calls.append(prompt)
        step = 7
        for i in range(0, len(self.text), step):
            if on_chunk:
                on_chunk(self.text[i:i + step])
        return self.text

    def chat(self, prompt):
        self.calls.append(prompt)
        return self.text


class StubRouter:
    def __init__(self, text):
        self.client_ = StubClient(text)
        self.last_slot = ""

    def client(self, slot):
        self.last_slot = slot
        return self.client_


tmp = tempfile.mkdtemp(prefix="qbn_cw_dlg_")
proj = project.create_project(tmp, "对话探针")
project.write_idea_info(proj, "悬疑", "番茄", "主角捡到能改命的笔记", 100)
project.write_file(os.path.join(proj, "设定", "题材定位.md"), "# 题材定位\n\n## 主要角色表\n| 角色 | 定位 |")

# ---- 1. DialogueWorker：方案① user body 注入 + 槽位 ----
state = st.load_state(proj)
co_dialogue.transcript_append(state, st.STAGE_CW_CORE, "user", "金手指不要太无敌")
co_dialogue.transcript_append(state, st.STAGE_CW_OUTLINE, "user", "开篇单元要压得住节奏")
co_dialogue.store_handoff(state, st.STAGE_CW_CORE, "关键事实：改命笔记")
st.save_state(proj, state)

stub = StubRouter("设定参考稿：主角的笔记每次改写命运都要付出代价。")
w = DialogueWorker({}, proj, st.STAGE_CW_OUTLINE, "大纲别写崩，三幕式。", router=stub)
w.run()
prompt0 = stub.client_.calls[0]
check("DialogueWorker 结果透传", w.result_text == stub.client_.text)
check("槽位=writing(outline)", stub.last_slot == "writing")
check("提示词含角色职责", "大纲 Agent" in prompt0 and "职责" in prompt0)
check("提示词含交接块", "改命笔记" in prompt0)
check("提示词含转写", "开篇单元要压得住节奏" in prompt0)
check("提示词含本轮输入", "三幕式" in prompt0)

stub2 = StubRouter("世界书草案…")
w2 = DialogueWorker({}, proj, st.STAGE_CW_WORLDBOOK, "力量体系再细化", router=stub2)
w2.run()
check("槽位=helper(worldbook)", stub2.last_slot == "helper")
check("worldbook 参考块含设定+大纲", "题材定位" in w2.last_prompt)

# ---- 2. SummarizeWorker：总结定稿 → 交接块 ----
sum_text = ("## 题材定位\n主角捡到能改命的笔记，每次改写命运都要付出代价。\n\n"
            "## 主要角色表\n| 角色 | 定位 |\n\n"
            "→ 下阶段交接\n- 关键事实：金手指=改命笔记，代价未定\n- 开放问题：代价形式\n")
stub3 = StubRouter(sum_text)
s = SummarizeWorker({}, proj, st.STAGE_CW_CORE, router=stub3)
s.run()
check("SummarizeWorker 透传", s.result_text.strip() == sum_text.strip())
check("总结提示词含产物结构", "主要角色表" in s.last_prompt)
product, handoff = co_dialogue.build_handoff(st.STAGE_CW_CORE, s.result_text)
check("产物不含交接小节", "→ 下阶段交接" not in product and "题材定位" in product)
check("交接块 ≤800 且含关键事实", len(handoff) <= 800 and "改命笔记" in handoff)
state = st.load_state(proj)
co_dialogue.store_handoff(state, st.STAGE_CW_CORE, handoff)
st.save_state(proj, state)
check("下一阶段只读交接块", "改命笔记" in co_dialogue.prev_handoff(st.load_state(proj), st.STAGE_CW_OUTLINE))

# ---- 3. 各阶段槽位映射全表 ----
expect_slots = {
    st.STAGE_CW_CORE: "writing", st.STAGE_CW_OUTLINE: "writing",
    st.STAGE_CW_WORLDBOOK: "helper", st.STAGE_CW_UNIT: "helper",
    st.STAGE_CW_PROSE: "writing",
}
for stage, expect in expect_slots.items():
    r = StubRouter("回复")
    dlg = DialogueWorker({}, proj, stage, "hi", router=r)
    dlg.run()
    check(f"槽位映射 {stage}→{expect}", r.last_slot == expect)

# ---- 4. 对话转写截断累积（≤4k 保尾）----
state = st.load_state(proj)
for i in range(20):
    co_dialogue.transcript_append(state, st.STAGE_CW_UNIT, "user", f"第{i}条意见" + "扩" * 300)
tail = co_dialogue.transcript_text(state, st.STAGE_CW_UNIT)
check("转写 ≤4000 保尾", len(tail) <= 4000 and "第19条意见" in tail)

print("=== 共写档对话循环探针 ===")
ok = True
for name, passed in results:
    print(("PASS" if passed else "FAIL"), name)
    ok = ok and passed
print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
sys.exit(0 if ok else 1)
