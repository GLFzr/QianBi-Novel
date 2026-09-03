# -*- coding: utf-8 -*-
"""单元细纲二级结构探针（M3 · router 打桩 · 无需 LLM / 无网络）：
① 滚动批次计算（已写章跳过/已生成跳过/±10 章上限） ② ≈200字/章格式解析（===第N章===）
③ 单元总纲属主（worldbook 阶段只产世界书+正则） ④ OutlineBatchWorker 落盘 ⑤ ReviewOutlinesWorker 校验
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_co3_home_")
os.environ["USERPROFILE"] = _FH

sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QCoreApplication
app = QCoreApplication(sys.argv)

from app import project, prompts
from app.core import state as st
from app.core.co_writing import CoWriting
from app.core.co_dialogue import OutlineBatchWorker, ReviewOutlinesWorker
from app.core.stages import parse_outlines, parse_review_findings

results = []


def check(name, cond):
    results.append((name, bool(cond)))


class StubClient:
    def __init__(self, text):
        self.text = text

    def chat_stream(self, prompt, on_chunk=None, on_reasoning=None, **kw):
        return self.text

    def chat(self, prompt):
        return self.text


class StubRouter:
    def __init__(self, text):
        self.client_ = StubClient(text)
        self.last_slot = ""

    def client(self, slot):
        self.last_slot = slot
        return self.client_


def make_proj():
    tmp = tempfile.mkdtemp(prefix="qbn_co3_proj_")
    proj = project.create_project(tmp, "细纲探针")
    project.write_idea_info(proj, "都市悬疑", "番茄", "捡到改命笔记", 100)
    return proj


# ---- ① 滚动批次计算 ----
proj = make_proj()
cw = CoWriting(proj)
state = cw.load()
cw.set_unit(state, 6, 50, "开篇单元")
cw.save(state)
check("批次从单元起始章起", cw.next_outline_batch(cw.load()) == [6, 7, 8, 9, 10])
for n in range(6, 11):
    project.write_file(project.get_outline_path(proj, n), f"===第{n}章===\n内容")
check("已有细纲跳过", cw.next_outline_batch(cw.load()) == [11, 12, 13, 14, 15])

proj2 = make_proj()
cw2 = CoWriting(proj2)
s2 = cw2.load()
cw2.set_unit(s2, 1, 12, "短单元")
cw2.save(s2)
for n in range(1, 21):
    project.write_file(project.get_outline_path(proj2, n), f"===第{n}章===\n内容")
batch2 = cw2.next_outline_batch(cw2.load())
check("±10 上限（完结≤22）", batch2 == [21, 22] and batch2[-1] <= 12 + 10)

# ---- ② ≈200 字/章格式解析（===第N章===）----
batch_text = "\n\n".join(
    f"===第{n}章===\n### 第 {n} 章：章节名{n}\n- 核心事件：事件{n}\n- 故事内容：" + ("内容" * 100)
    for n in range(6, 11))
parsed = parse_outlines(batch_text)
check("解析出 5 章", len(parsed) == 5 and [o[0] for o in parsed] == [6, 7, 8, 9, 10])
check("200 字规格可解析", all("核心事件" in o[2] and "故事内容" in o[2] for o in parsed))

# ---- ③ 单元总纲属主（worldbook 阶段只产世界书+正则）----
check("worldbook 属主=两文件", st.CW_STAGE_PRODUCTS[st.STAGE_CW_WORLDBOOK] == ["设定/世界书.md", "设定/正则.md"])
check("单元总纲属主=cw_unit", "大纲/单元总纲.md" in st.CW_STAGE_PRODUCTS[st.STAGE_CW_UNIT]
      and "单元总纲" not in " ".join(st.CW_STAGE_PRODUCTS[st.STAGE_CW_WORLDBOOK]))
wb, rg = project.split_worldbook_product("## 世界书\n力量体系。\n\n## 正则（逻辑约束规则集）\n- 规则：X｜level：must｜scope：全书")
check("worldbook 确定不产单元总纲", wb.startswith("## 世界书") and rg.startswith("## 正则"))

# ---- ④ OutlineBatchWorker 落盘（helper 槽）----
proj3 = make_proj()
cw3 = CoWriting(proj3)
s3 = cw3.load()
cw3.set_unit(s3, 1, 50, "开篇单元")
co_dialogue_store = __import__("app.core.co_dialogue", fromlist=["store_handoff"])
co_dialogue_store.store_handoff(s3, st.STAGE_CW_WORLDBOOK, "关键事实：改命笔记")
cw3.save(s3)
batch3 = cw3.next_outline_batch(cw3.load())
batch3_text = "\n\n".join(
    f"===第{n}章===\n### 第 {n} 章：章节名{n}\n- 核心事件：事件{n}\n- 故事内容：" + ("内容" * 100)
    for n in batch3)
stub = StubRouter(batch3_text)
w = OutlineBatchWorker({}, proj3, batch3, cw3.unit(s3), router=stub)
w.run()
check("批次 worker 槽位=helper", stub.last_slot == "helper")
check("批次 worker 落盘 5 章", len(w.result) == 5
      and all(os.path.exists(project.get_outline_path(proj3, n)) for n in range(1, 6)))
check("批次 worker prompt 含单元块", "开篇单元" in w.last_prompt and "改命笔记" in w.last_prompt)

# ---- ⑤ ReviewOutlinesWorker 校验（阻塞/通过两态）----
blocking_text = "===BLOCKING===\n- 第 3 章未承接上一章结尾\n\n===ADVISORY===\n- 第 5 章钩子偏弱"
w2 = ReviewOutlinesWorker({}, proj3, [1, 2, 3, 4, 5], cw3.unit(cw3.load()), router=StubRouter(blocking_text))
w2.run()
blk, adv = parse_review_findings(w2.result_text)
check("校验检出阻塞", len(blk) == 1 and "第 3 章" in blk[0])
ok_text = "===BLOCKING===\n无\n\n===ADVISORY===\n无"
w3 = ReviewOutlinesWorker({}, proj3, [1, 2, 3, 4, 5], cw3.unit(cw3.load()), router=StubRouter(ok_text))
w3.run()
blk2, adv2 = parse_review_findings(w3.result_text)
check("校验通过无阻塞", blk2 == [] and adv2 == [])
check("校验 prompt 含世界书/正则", "世界书" in w3.last_prompt and "正则" in w3.last_prompt)

print("=== 单元细纲二级结构探针 ===")
ok = True
for name, passed in results:
    print(("PASS" if passed else "FAIL"), name)
    ok = ok and passed
print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
sys.exit(0 if ok else 1)
