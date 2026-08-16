# -*- coding: utf-8 -*-
"""M6 Phase B/C · 真实 LLM 全量测试（唯一途径：OpenCode Go · deepseek-v4-flash）

Phase B（功能验证）：
  B1 E2E 全流水线：立项→设定→大纲→细纲→2 章微循环（含审校/去味/摘要链）
  B2 想法注入：预置「红围巾」想法 → 验证进入正文 prompt 且软校验正文
  B3 全局偏好注入：文风/禁忌 → 验证进入每章 prompt
  B4 流式信号：阶段标签序列完整性（细纲/草稿/审校…）
Phase C（缩短版长跑）：
  连续再写 3 章（共 5 章），每章采样内存，报告稳定性

用法：.venv/Scripts/python.exe tests/m6_llm.py [--chapters 5]
"""
import os
import sys
import time

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())

from app import config as cfg_mod, project
from app.core.orchestrator import Orchestrator
from app.core import state as st
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication

# ---- 途径锁定：OpenCode Go · deepseek-v4-flash（唯一允许）----
CFG = cfg_mod.load_config()
CONN = None
for c in CFG.get("connections", []):
    if "opencode" in c.get("base_url", "") and c.get("model") == "deepseek-v4-flash" and c.get("api_key"):
        CONN = c
        break
assert CONN, "未找到 OpenCode Go deepseek-v4-flash 连接（唯一测试途径）"
BASE, KEY = CONN["base_url"], CONN["api_key"]
print(f"[m6-llm] 途径锁定：OpenCode Go · deepseek-v4-flash · {BASE}", flush=True)

TOTAL_CHAPTERS = 5
IDEA_TEXT = "主角在下一章出场时围着一条褪色的红围巾，并有具体描写"
STYLE_PREF = "多用短句，段落简练"
TABOO_PREF = "不出现任何现实品牌名"

test_cfg = {
    "connections": [
        {"id": "ocgo", "name": "OpenCode Go · V4 Flash（M6 测试）", "provider": "custom",
         "base_url": BASE, "api_key": KEY, "model": "deepseek-v4-flash",
         "temperature": 0.7, "max_tokens": 65536, "timeout": 900, "thinking": "disabled"},
    ],
    "slots": {"writing": "ocgo", "helper": "ocgo", "review": "ocgo"},
    "gates": {"strategy": "mark_continue", "deslop_max_rounds": 2,
              "word_tolerance": 0.25, "review_enabled": True, "review_max_rounds": 1},
    "llm": {"max_retries": 2, "backoff_base": 2.0},
    "writing": {"chapter_word_target": 1600, "style_pref": STYLE_PREF,
                "taboos": TABOO_PREF, "pace_pref": ""},
    "last_project": "", "recent_projects": [],
}

root = os.path.join(os.getcwd(), "tests_output")
PROJ = project.create_project(root, f"M6全量测试_{time.strftime('%m%d_%H%M')}")
project.write_idea_info(PROJ, "都市悬疑", "番茄",
                         "外卖骑手小雨发现每晚十一点后接到的订单都会指向同一个不存在的地址，"
                         "她决定跟到底", 0)
print(f"[m6-llm] 项目：{PROJ}", flush=True)

state = st.load_state(PROJ)
st.add_idea(PROJ, state, IDEA_TEXT, "next")
st.save_state(PROJ, state)

logs = []
records = []
stage_labels = []
prompt_snaps = []
mem_samples = []
fail = {"msg": ""}
stopped = {"done": False}


def rss_mb():
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1048576, 1)
    except Exception:
        return -1


def on_log(level, msg):
    logs.append(f"[{level}] {msg}")
    print("  " + msg, flush=True)


def on_stage(label):
    stage_labels.append(label)


def on_chapter_done(record):
    records.append(record)
    mem_samples.append((record["num"], rss_mb()))
    print(f"[m6-llm] 第 {record['num']} 章定稿 {record['words']} 字 · "
          f"AI味阻断 {record.get('deslop_blocking', 0)} · 审校阻塞 {record.get('review_blocking', 0)} · "
          f"RSS {rss_mb()}MB", flush=True)
    # 抓一次最近正文 prompt（验证想法/偏好注入）
    try:
        if orch.last_prompt:
            prompt_snaps.append((record["num"], orch.last_prompt))
    except Exception:
        pass
    if len(records) >= TOTAL_CHAPTERS:
        orch.stop()
        stopped["done"] = True


def on_failed(msg):
    fail["msg"] = msg
    print(f"[m6-llm] 失败：{msg}", flush=True)


app = QGuiApplication([])
orch = Orchestrator(PROJ, test_cfg)
orch.sig_log.connect(on_log)
orch.sig_stream_stage.connect(on_stage)
orch.sig_chapter_done.connect(on_chapter_done, Qt.DirectConnection)
orch.sig_failed.connect(on_failed)

t0 = time.monotonic()
print(f"[m6-llm] 启动：{TOTAL_CHAPTERS} 章 @1600 字（OpenCode Go · deepseek-v4-flash）", flush=True)
orch.start()


def watchdog():
    if orch.isRunning():
        QTimer.singleShot(2000, watchdog)
        return
    print(f"\n[m6-llm] 结束，耗时 {int(time.monotonic() - t0)}s", flush=True)

    RESULTS = []

    def check(item, name, cond, detail=""):
        RESULTS.append((item, name, bool(cond), str(detail)))
        print(("[PASS]" if cond else "[FAIL]"), item, name, detail, flush=True)

    # B1 流水线
    check("B1", "章节定稿数", len(records) >= min(3, TOTAL_CHAPTERS), f"{len(records)} 章")
    check("B1", "设定/大纲/细纲产物",
          os.path.isfile(os.path.join(PROJ, "设定", "题材定位.md"))
          and os.path.isfile(os.path.join(PROJ, "大纲", "大纲.md"))
          and len(project.list_outlines(PROJ)) >= len(records))
    check("B1", "字数达标率(±25%)",
          all(r["words"] >= 1600 * 0.75 for r in records) if records else False,
          "/".join(str(r["words"]) for r in records))
    # B4 流式阶段标签
    need = ["细纲", "草稿", "审校"]
    joined = "|".join(stage_labels)
    check("B4", "全阶段流式标签", all(n in joined for n in need), joined[:120])
    # B2 想法注入
    ch1 = project.read_file(project.list_chapters(PROJ)[0][2]) if project.list_chapters(PROJ) else ""
    idea_in_prompt = any("红围巾" in p for _n, p in prompt_snaps)
    check("B2", "想法进入正文 prompt", idea_in_prompt)
    check("B2", "想法体现在正文（软校验）", "围巾" in ch1, "第1章正文")
    # B3 全局偏好注入
    pref_ok = all(("短句" in p and "品牌" in p) for _n, p in prompt_snaps) if prompt_snaps else False
    check("B3", "全局偏好注入每章 prompt", pref_ok, f"{len(prompt_snaps)} 个 prompt 快照")
    # C 长跑稳定性（内存）
    if len(mem_samples) >= 3:
        grow = mem_samples[-1][1] - mem_samples[0][1]
        check("C", "连续写作内存稳定（<400MB 增长）", grow < 400, f"增量 {grow}MB")
        check("C", "无中途崩溃", not fail["msg"] and len(records) >= 3, fail["msg"][:80])
    # 状态一致性
    hist = st.load_state(PROJ).get("history", [])
    check("状态", "history 与定稿一致", len(hist) == len(records))
    # 想法消费标记
    ideas_after = st.norm_ideas(st.load_state(PROJ))
    idea_rec = [i for i in ideas_after if "红围巾" in i["text"]]
    check("W3", "想法消费后标记 applied", idea_rec and idea_rec[0]["status"] == "applied")

    passed = sum(1 for r in RESULTS if r[2])
    lines = ["# M6 Phase B/C 报告（真实 LLM：OpenCode Go · deepseek-v4-flash）", "",
             f"- 项目：{os.path.basename(PROJ)} · {TOTAL_CHAPTERS} 章 @1600 字 · 耗时 {int(time.monotonic() - t0)}s",
                 f"- 结果：**{passed} / {len(RESULTS)} PASS**", "",
                 "| 清单 | 项目 | 结果 |", "|---|---|---|"]
    for item, name, ok, detail in RESULTS:
        lines.append(f"| {item} | {name} | {'✅' if ok else '❌ ' + detail[:60]} |")
    lines += ["", "## 内存采样", ""] + [f"- 第{n}章后 RSS：{m}MB" for n, m in mem_samples]
    lines += ["", "## 流式阶段序列", "", " → ".join(stage_labels)]
    with open(os.path.join(root, "m6_phaseBC_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nPHASE_BC_TOTAL {passed}/{len(RESULTS)}", flush=True)
    app.quit()


QTimer.singleShot(5000, watchdog)
sys.exit(app.exec())
