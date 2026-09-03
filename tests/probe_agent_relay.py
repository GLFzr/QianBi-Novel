# -*- coding: utf-8 -*-
"""Agent 接力编排探针（M5 · router 打桩 · 无需 LLM / 无网络）：
① 每 Agent 只注入上环节产物/交接块（参考块内容与上限断言）
② SupervisorWorker 上下文 ≤6k 量级 + 只出报告不产正文
③ bridge 触发点：定稿前已比对→确定即锁定（仍受 #41 字数闸门约束）；世界书变更→影响提示（locked 章）
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_relay_home_")
os.environ["USERPROFILE"] = _FH

sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QCoreApplication
app = QCoreApplication(sys.argv)

from app import project
from app.core import state as st
from app.core.co_writing import CoWriting
from app.core import co_dialogue
from app.core.co_dialogue import SupervisorWorker
from app.ui.bridge import Bridge

results = []


def check(name, cond):
    results.append((name, bool(cond)))


class StubClient:
    def __init__(self, text):
        self.text = text

    def chat(self, prompt):
        return self.text

    def chat_stream(self, prompt, on_chunk=None, on_reasoning=None, **kw):
        return self.text


class StubRouter:
    def __init__(self, text):
        self.client_ = StubClient(text)
        self.last_slot = ""

    def client(self, slot):
        self.last_slot = slot
        return self.client_


tmp = tempfile.mkdtemp(prefix="qbn_relay_proj_")
proj = project.create_project(tmp, "接力探针")
project.write_idea_info(proj, "都市悬疑", "番茄", "捡到改命笔记", 100)
project.write_file(os.path.join(proj, "设定", "题材定位.md"), "# 题材定位\n\n## 主要角色表\n| 沈默 | 主角 |")
project.write_file(os.path.join(proj, "大纲", "大纲.md"), "# 全书大纲\n\n## 第1章-第30章 开篇单元")
project.write_file(os.path.join(proj, "设定", "世界书.md"), "## 世界书\n对等代价体系。")
project.write_file(os.path.join(proj, "设定", "正则.md"), "- 规则：改命必须索回代价｜level：must｜scope：全书")
project.write_file(project.get_outline_path(proj, 1), "===第1章===\n### 第 1 章：雨夜\n- 核心事件：捡到笔记")
project.write_file(project.get_outline_path(proj, 2), "===第2章===\n### 第 2 章：代价\n- 核心事件：首次改写")
chapter_path = project.get_chapter_path(proj, 1, "雨夜")
project.write_file(chapter_path, "# 第1章 雨夜\n\n" + "雨点敲在窗棂上，他翻开了那本笔记。" * 20)

# ---- ① 各阶段参考块只注入上环节产物/交接块 + 上限 ----
cw = CoWriting(proj)
s = cw.load()
co_dialogue.store_handoff(s, st.STAGE_CW_WORLDBOOK, "关键事实：改命笔记（≤800 字交接块）")
cw.save(s)
ref_prose = co_dialogue.compose_reference_block(proj, st.STAGE_CW_PROSE, "urban_destiny")
check("写作 Agent 参考块含细纲+世界书+正则+上文结尾",
      "细纲" in ref_prose and "世界书" in ref_prose and "正则" in ref_prose and "上一章结尾" in ref_prose)
check("写作 Agent 参考块总量受控（<6000）", len(ref_prose) < 6000)

# ---- ② SupervisorWorker：上下文 ≤6k 量级 + 只出报告不产正文（review 槽）----
report_text = ("### 主 Agent 报告\n- 衔接：本章承接上章雨夜场景，钩子指向第 2 章代价\n"
               "- 范围：未越出单元\n- 结论：通过")
stub = StubRouter(report_text)
w = SupervisorWorker({}, proj, 1, router=stub)
w.run()
check("supervisor 槽位=review", stub.last_slot == "review")
check("supervisor 输出透传", w.result_text == report_text)
check("supervisor 上下文 ≤6k 量级", len(w.last_prompt) < 8000)
check("supervisor 上下文含全量摘要/上章/下章细纲/世界书/正则",
      "全局摘要" in w.last_prompt and "下一章细纲" in w.last_prompt
      and "世界书" in w.last_prompt and "正则" in w.last_prompt)
check("supervisor 不产正文", project.read_file(chapter_path).startswith("# 第1章 雨夜")
      and "主 Agent 报告" not in project.read_file(chapter_path))
check("supervisor 输出非审校格式", "===BLOCKING===" not in w.result_text
      and "===ADVISORY===" not in w.result_text)

# ---- ③ bridge 触发点 ----
b = Bridge()
b.openProject(proj)
b.openChapter(1)
b.setCwMode(True)
# 本探针零线程零网络：比对 worker 与锁定后的反哺都只记账，不真起 QThread
sup_started, blocked = [], []
b._start_cw_supervisor = lambda: sup_started.append(1)
b._maybe_backflow = lambda num, force=False: None
b.lockBlocked.connect(lambda num, reason, actual, target, kind: blocked.append((num, target)))
s2 = st.load_state(proj)
st.ensure_cw(s2)["stage"] = st.STAGE_CW_PROSE
st.save_state(proj, s2)
b.selectCwStage(st.STAGE_CW_PROSE)   # 视图同步到机器阶段
# 触发点①前半：本章还没比对过 → 「确定」先派主 Agent，而不是直接锁
b.confirmCwStage()
check("未比对→派主 Agent 比对而非直接锁定", sup_started == [1] and b.chapterLocked is False)
# 触发点①后半：已比对过 → 确定即锁定（不重复派比对）
s2 = st.load_state(proj)
st.ensure_cw(s2)["supervised"] = {"1": "08-19 20:00"}
st.save_state(proj, s2)
# 夹具正文 345 字：把字数目标配成 350 走「达标即锁定」主路径（细纲目标受
# gates ±50% 防幻觉回退约束，改配置才是正解）
b.cfg.setdefault("writing", {})["chapter_word_target"] = 350
b.confirmCwStage()
check("已比对→确定即锁定", b.chapterLocked is True)
check("已比对不再派比对 worker/不被闸门拦下", sup_started == [1] and blocked == [])
project.attempt_unlock(proj, 1)
# #41 边界：已比对不豁免字数闸门，短章只能 lockBlocked 走强锁确认，不得静默锁定
b.cfg["writing"]["chapter_word_target"] = 3000
project.write_file(chapter_path, "# 第1章 雨夜\n\n他很惊讶。")
b.openChapter(1)
b.confirmCwStage()
check("已比对但字数未达标 → 拦截而非静默锁定",
      b.chapterLocked is False and blocked == [(1, 3000)] and sup_started == [1])
project.attempt_unlock(proj, 1)
# 触发点②：世界书变更 → locked 章影响提示（纯逻辑，不发 LLM）
project.set_chapter_locked(proj, 1, True)
s3 = b._cw.load()
had = b._cw_worldbook_changed_notice(s3)
check("世界书变更提示 locked 章", had is True and "建议显式解锁" in st.ensure_cw(s3)["report"]["text"])
project.attempt_unlock(proj, 1)
s4 = b._cw.load()
had2 = b._cw_worldbook_changed_notice(s4)
check("无 locked 章普通提示", had2 is False and "未锁定章节将按新契约续写" in st.ensure_cw(s4)["report"]["text"])
check("报告区可清空", (b.clearCwReport() or True) and b.cwReportText == "")

print("=== Agent 接力编排探针 ===")
ok = True
for name, passed in results:
    print(("PASS" if passed else "FAIL"), name)
    ok = ok and passed
print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
sys.exit(0 if ok else 1)
