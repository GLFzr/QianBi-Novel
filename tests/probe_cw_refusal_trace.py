# -*- coding: utf-8 -*-
"""共写档「立项阶段拒绝对话」必须给用户的发言留痕（尺5，无 LLM / 无网络）。

缺陷：submitCwMessage / generateCwDraft 在 cw_project 阶段先 toast 再 return，
transcript_append 在其后 ⇒ 用户打的那句话（或点的按钮）被无声丢弃，事后翻对话也找不到。
本探针把阶段钉在 cw_project，发一句话 / 点一次草案，断言：
  ① 用户条进转写；② Agent 拒因条进转写；③ 已落盘（重读文件仍在）；④ 阶段没被推进、没起对话线程。
撤掉修复 ⇒ ①②③ 全红（旧码在 append 之前就 return）。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

import probe_guard                                  # noqa: E402
probe_guard.arm_config_guard()

from PySide6.QtGui import QGuiApplication           # noqa: E402

app = QGuiApplication.instance() or QGuiApplication(sys.argv)

from app import config as cfg_mod                   # noqa: E402
from app.core import state as st                    # noqa: E402
from app.core.co_writing import CoWriting           # noqa: E402
from app.ui.bridge import Bridge                    # noqa: E402

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "[FAIL] ") + name + ("  " + extra if extra else ""), flush=True)


def make_cw_project(stage):
    proj = tempfile.mkdtemp(prefix="qbn_cwrefusal_")
    state = {"stage": "init", "total_chapters": 0,
             "cw": {"mode": "cw", "stage": stage, "project": {"genre": "都市"},
                    "transcript": {}}}
    with open(os.path.join(proj, "pipeline_state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    return proj


def read_transcript(proj, stage):
    with open(os.path.join(proj, "pipeline_state.json"), encoding="utf-8") as f:
        cw = (json.load(f).get("cw") or {})
    return cw.get("transcript", {}).get(stage) or [], cw.get("stage")


def new_bridge(proj):
    b = Bridge()
    b.cfg = cfg_mod.load_config()
    b.proj = proj
    b._cw = CoWriting(proj)
    b._cw_view = st.STAGE_CW_PROJECT
    b._cw_busy = False
    return b


b = new_bridge(make_cw_project(st.STAGE_CW_PROJECT))
# 选一句不含指令动词、不会命中 agent_tools 猜测的自然语言，确保落到 cw_project 拒收分支
msg = "我先说说我的想法好吗"
b.submitCwMessage(msg, mode="discuss")
tr, stage_after = read_transcript(b.proj, st.STAGE_CW_PROJECT)
roles = [it.get("role") for it in tr]
texts = [it.get("text", "") for it in tr]
check("① 被拒的用户发言进了转写（不是无声丢弃）",
      "user" in roles and any(msg in t for t in texts),
      "roles=%s" % roles)
check("② Agent 拒因条进了转写（含『选题』指路）",
      "agent" in roles and any("选题" in t or "表单" in t for t in texts),
      "roles=%s" % roles)
check("③ 转写已落盘（重读 pipeline_state.json 仍在）",
      any("user" == it.get("role") for it in tr))
check("④ 拒收未推进阶段、未起对话线程",
      stage_after == st.STAGE_CW_PROJECT and not b._cw_busy,
      "stage=%s busy=%s" % (stage_after, b._cw_busy))

# generateCwDraft 同型
b2 = new_bridge(make_cw_project(st.STAGE_CW_PROJECT))
b2.generateCwDraft()
tr2, _s2 = read_transcript(b2.proj, st.STAGE_CW_PROJECT)
texts2 = [it.get("text", "") for it in tr2]
check("⑤ 点击「生成草案」也被记录（用户条 + 拒因）",
      any("生成草案" in t for t in texts2) and
      any(("agent" == it.get("role")) and ("选题" in it.get("text") or "表单" in it.get("text")) for it in tr2),
      "texts=%s" % texts2)

print("TOTAL %d / %d" % (sum(1 for _, p in RESULTS if p), len(RESULTS)), flush=True)
_rc = 0 if all(p for _, p in RESULTS) else 1
sys.stdout.flush()
sys.stderr.flush()
import atexit as _ax
_ax._run_exitfuncs()
os._exit(_rc)
