# -*- coding: utf-8 -*-
"""共写档「确定」之后，阶段指针必须真的落盘（无需 LLM / 无网络）。

v5 实测缺陷（本机 LM Studio 走查第一步就撞上）：`_on_cw_sum_done` 先 `_cw_save_state()`
落盘、之后才 `advance(state)` 改内存并 toast「已进入下一阶段」⇒ 盘上 cw.stage 仍是原阶段。
现象＝界面报成功、state.json 说没发生；用户再点一次「确定」就是把同一阶段重新定稿一遍。
旧覆盖（probe_cw_state.py）只把 advance() 当纯函数测，测不到"推进之后有没有再保存"。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

import probe_guard                                  # noqa: E402
probe_guard.arm_config_guard()                      # 真 config/凭据沙箱

from PySide6.QtGui import QGuiApplication           # noqa: E402

app = QGuiApplication.instance() or QGuiApplication(sys.argv)

from app import config as cfg_mod, dialogue_log     # noqa: E402
from app import prompts                              # noqa: E402
from app.core import state as st                     # noqa: E402
from app.core.co_writing import CoWriting           # noqa: E402
from app.ui.bridge import Bridge                     # noqa: E402

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "[FAIL] ") + name + ("  " + extra if extra else ""), flush=True)


def make_cw_project(stage):
    proj = tempfile.mkdtemp(prefix="qbn_stgpersist_")
    state = {"stage": "init", "total_chapters": 0,
             "cw": {"mode": "cw", "stage": stage, "project": {"genre": "都市"},
                    "transcript": {}}}
    with open(os.path.join(proj, "pipeline_state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    return proj


def summary_with_handoff():
    return ("主角欲望：证明自己不再是废物；金手指：能听见物件残响，代价是每次使用遗忘一段记忆；"
            "第一卷结局：查明灭门真相但失去妹妹的最后一句嘱托。"
            + "\n\n" + prompts.HANDOFF_MARKER + "\n下阶段须扣住「遗忘代价」这条硬约束。")


def disk_stage(proj):
    with open(os.path.join(proj, "pipeline_state.json"), encoding="utf-8") as f:
        return ((json.load(f).get("cw") or {}).get("stage"))


b = Bridge()
b.cfg = cfg_mod.load_config()
FAILS = 0

for stage, label in [(st.STAGE_CW_CORE, "核心设定"), (st.STAGE_CW_OUTLINE, "剧情总大纲")]:
    proj = make_cw_project(stage)
    b.proj = proj
    # Bridge 的 _cw 初值是 None（打开项目时才建）；hasattr 判"存在"会一直沿用 None
    if getattr(b, "_cw", None) is None:
        b._cw = CoWriting(proj)
    else:
        b._cw.proj = proj
    assert b._cw is not None and getattr(b, "proj", "") == proj
    expected = CoWriting(proj).advance(json.loads(json.dumps(
        {"cw": {"mode": "cw", "stage": stage, "project": {"genre": "都市"}, "transcript": {}}})))
    b._on_cw_sum_done(summary_with_handoff())
    got = disk_stage(proj)
    ok = got == expected
    FAILS += 0 if ok else 1
    check("「%s」确定后盘上阶段推进到 %s" % (label, expected), ok,
          "(实得 %s；toast 已宣称进入下一阶段)" % got)
    check("「%s」产物文件已落盘" % label,
          os.path.isdir(proj) and any(
              os.path.getsize(os.path.join(r, fn)) > 0
              for r, _d, fs in os.walk(proj) for fn in fs if fn.endswith(".md")))

print("TOTAL %d / %d" % (sum(1 for _, p in RESULTS if p), len(RESULTS)), flush=True)
_rc = 1 if FAILS or not all(p for _, p in RESULTS) else 0
sys.stdout.flush()
sys.stderr.flush()
import atexit as _ax
_ax._run_exitfuncs()
os._exit(_rc)
