# -*- coding: utf-8 -*-
"""0.20.3 全量实测 Phase 1 共写档驱动（offscreen QGuiApplication + Bridge Slots）

用法（工作区根目录执行）：
    ./.venv/Scripts/python.exe tests/or_phase1_drive.py <step>
step ∈ setup | core | outline | worldbook | unit | prose1 | prose2 | status

- 配置隔离：QIANBI_CONFIG_DIR=tests_output/_phase1_cfg（gitignored，真实配置零污染）
- 网络：剥死代理 env + NO_PROXY=*（本机 127.0.0.1:7897 已死）
- API Key：仅经环境变量 QIANBI_TEST_KEY 注入连接配置；不打印、不入仓
- 结果：逐步追加 JSONL → 项目/_phase1_results.jsonl；人读日志 → _phase1_drive.log
"""
import json
import os
import sys
import time

# ---- 环境必须在任何 qianbi/httpx import 之前定形 ----
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
           "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QIANBI_TEST_COST_STACK"] = "1"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
# 二测参数化：QIANBI_TEST_PROJ / QIANBI_TEST_CFG_DIR / QIANBI_TEST_BASE / QIANBI_TEST_MODEL
os.environ.setdefault("QIANBI_CONFIG_DIR",
                      os.environ.get("QIANBI_TEST_CFG_DIR")
                      or os.path.join(_ROOT, "tests_output", "_phase1_cfg"))
sys.path.insert(0, _ROOT)

PROJ = os.environ.get("QIANBI_TEST_PROJ") or os.path.join(
    _ROOT, "tests_output", "or_长测_改命笔记")
RESULTS = os.path.join(PROJ, "_phase1_results.jsonl")
DRIVELOG = os.path.join(PROJ, "_phase1_drive.log")
CONN_ID = os.environ.get("QIANBI_TEST_CONN_ID", "or-stealth")
MODEL = os.environ.get("QIANBI_TEST_MODEL", "stealth/space-bunny-alpha")
BASE_URL = os.environ.get("QIANBI_TEST_BASE", "https://openrouter.ai/api/v1")

_t0 = time.time()


def log(msg: str):
    line = f"[{time.time() - _t0:7.1f}s] {msg}"
    print(line, flush=True)
    try:
        with open(DRIVELOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def record(step: str, **data):
    row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "step": step, **data}
    with open(RESULTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def die(msg: str, code: int = 2):
    log(f"FAIL: {msg}")
    record("abort", step_name=os.environ.get("_STEP", "?"), reason=msg)
    sys.exit(code)


# ---- Qt/app import 在 env 定形后 ----
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from app import config as cfg_mod  # noqa: E402
from app import project  # noqa: E402
from app.core import state as st  # noqa: E402
from app.core.co_writing import CoWriting  # noqa: E402
from app.ui.bridge import Bridge  # noqa: E402


def make_app():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    return app


class Driver:
    def __init__(self):
        self.app = make_app()
        self.toasts = []
        self.bridge = Bridge()
        self.bridge.toast.connect(self._on_toast)
        if not os.path.isdir(PROJ):
            die(f"项目不存在：{PROJ}")
        # 老项目残缺骨架补齐（此前只建了 设定/追踪；is_project 要求四目录齐）
        for d in ("设定", "大纲", "正文", "追踪"):
            os.makedirs(os.path.join(PROJ, d), exist_ok=True)
        self.bridge.openProject(PROJ)
        if not self.bridge.proj:
            die("项目打开失败")
        self.cw = CoWriting(PROJ)

    def _on_toast(self, level: str, msg: str):
        self.toasts.append({"level": level, "msg": msg})
        log(f"TOAST[{level}] {msg}")

    # ---- 等待原语 ----

    def wait_idle(self, timeout: float, desc: str = "idle"):
        """共写 worker 全链空闲（_cw_busy 贯穿 dialogue/summarize/batch/validate/supervisor）"""
        t0 = time.time()
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(2000)

        def check():
            if not self.bridge._cw_busy:
                log(f"[wait] {desc} 完成（{time.time() - t0:.0f}s）")
                loop.quit()

        timer.timeout.connect(check)
        timer.start()
        killer = QTimer()
        killer.setSingleShot(True)
        killer.timeout.connect(lambda: (log(f"[wait] TIMEOUT {desc}"),
                                        loop.quit()))
        killer.start(int(timeout * 1000))
        loop.exec()
        timer.stop()
        if self.bridge._cw_busy:
            die(f"等待超时：{desc}（{timeout:.0f}s 后仍在 busy）")
        return time.time() - t0

    def wait_idle_soft(self, timeout: float, desc: str = "idle"):
        """同 wait_idle，但超时不 die（M4 读改揣摩有节流，可能根本不触发）"""
        t0 = time.time()
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(2000)

        def check():
            if not self.bridge._cw_busy:
                if time.time() - t0 > 2:
                    log(f"[wait] {desc} 完成（{time.time() - t0:.0f}s）")
                loop.quit()

        timer.timeout.connect(check)
        timer.start()
        killer = QTimer()
        killer.setSingleShot(True)
        killer.timeout.connect(loop.quit)
        killer.start(int(timeout * 1000))
        loop.exec()
        timer.stop()
        return time.time() - t0

    def sleep(self, sec: float):
        loop = QEventLoop()
        QTimer.singleShot(int(sec * 1000), loop.quit)
        loop.exec()

    # ---- 观测 ----

    def snapshot(self) -> dict:
        state = self.cw.load()
        cw = st.ensure_cw(state)
        prods = {}
        for stage_key, rels in st.CW_STAGE_PRODUCTS.items():
            for rel in rels:
                p = os.path.join(PROJ, rel)
                prods[rel] = os.path.getsize(p) if os.path.isfile(p) else 0
        tr = {}
        for k, v in (cw.get("transcript") or {}).items():
            tr[k] = len(v or [])
        outlines = [n for n, _p in project.list_outlines(PROJ)]
        chapters = [n for n, _t, _p in project.list_chapters(PROJ)]
        # 共写锁定真源 = 章节标注 locked 标记（project.set_chapter_locked）
        locked = [n for n in chapters if project.is_chapter_locked(PROJ, n)]
        supervised = cw.get("supervised") or {}
        return {"stage": cw.get("stage"), "mode": cw.get("mode"),
                "products": prods, "transcript_lens": tr,
                "outlines": outlines, "chapters": chapters,
                "locked": sorted(locked), "supervised": sorted(supervised),
                "busy": bool(self.bridge._cw_busy)}

    def usage_rows(self, since_ts: str = "") -> list:
        """真实台账 ~/.qianbi_novel/usage/usage.jsonl（app/usage.py 固定家目录），
        按模型过滤（隔离测试调用与用户自身用量），since_ts 以来"""
        import glob
        path = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "usage",
                            "usage.jsonl")
        rows = []
        if not os.path.isfile(path):
            return rows
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("model") != MODEL:
                        continue
                    if since_ts and str(r.get("ts", "")) < since_ts:
                        continue
                    rows.append(r)
        except OSError:
            pass
        return rows

    def usage_totals(self, since_ts: str = "") -> dict:
        rows = self.usage_rows(since_ts)
        tot = {"calls": len(rows), "prompt": 0, "completion": 0,
               "latency": 0.0, "empty": 0}
        for r in rows:
            tot["prompt"] += int(r.get("in") or 0)
            tot["completion"] += int(r.get("out") or 0)
            tot["latency"] += float(r.get("latency") or 0)
            if r.get("st"):
                tot["empty"] += 1
        return tot

    def run(self, step: str):
        os.environ["_STEP"] = step
        fn = getattr(self, f"step_{step}", None)
        if fn is None:
            die(f"未知 step：{step}")
        log(f"===== step {step} 开始 =====")
        snap0 = self.snapshot()
        log(f"前态：stage={snap0['stage']} mode={snap0['mode']} "
            f"outlines={len(snap0['outlines'])} chapters={len(snap0['chapters'])} "
            f"locked={len(snap0['locked'])}")
        since = time.strftime("%Y-%m-%d %H:%M:%S")
        fn()
        time.sleep(1.0)
        snap1 = self.snapshot()
        usage1 = self.usage_totals(since)
        delta = {"calls": usage1["calls"], "prompt": usage1["prompt"],
                 "completion": usage1["completion"],
                 "latency": round(usage1["latency"], 1), "empty": usage1["empty"]}
        record(step, before=snap0, after=snap1, usage_delta=delta,
               usage_rows=self.usage_rows(since), toasts=len(self.toasts))
        log(f"后态：stage={snap1['stage']} outlines={len(snap1['outlines'])} "
            f"chapters={len(snap1['chapters'])} locked={len(snap1['locked'])} "
            f"delta={delta}")
        log(f"===== step {step} 结束 =====")

    # ---- 步骤 ----

    def step_setup(self):
        key = os.environ.get("QIANBI_TEST_KEY", "").strip()
        if not key:
            die("缺少 QIANBI_TEST_KEY 环境变量")
        cfg = cfg_mod.load_config()
        conns = cfg.setdefault("connections", [])
        conn = next((c for c in conns if c.get("id") == CONN_ID), None)
        if conn is None:
            conn = {"id": CONN_ID, "name": "OpenRouter-stealth-test"}
            conns.append(conn)
        conn.update({"base_url": BASE_URL, "api_key": key, "model": MODEL,
                     "stream": False, "max_tokens": 16384, "timeout": 900,
                     "temperature": 0.7})
        slots = cfg.setdefault("slots", {})
        for s in cfg_mod.SLOT_LABELS:
            slots[s] = CONN_ID
        cfg.setdefault("writing", {})["chapter_word_target"] = 2000
        cfg_mod.save_config(cfg)
        log(f"连接已配置：{MODEL} stream=false max_tokens=16384；"
            f"slots={sorted(slots)}")
        # 校验连接面：from_connection 必须带 stream_enabled=False
        c = cfg_mod.slot_connection(cfg, "writing")
        from app.llm.client import LLMClient
        lc = LLMClient.from_connection(c)
        if lc.stream_enabled:
            die("连接 stream:false 未生效（stream_enabled 应为 False）")
        log("C44 校验通过：stream_enabled=False")
        # 档位迁移：auto → cw
        state = self.cw.load()
        if st.ensure_cw(state).get("mode") != "cw":
            self.bridge.setCwMode(True)
            state = self.cw.load()
        if st.ensure_cw(state).get("mode") != "cw":
            die("档位迁移失败")
        # 项目阶段确认（纯本地，不烧 LLM）：cw_project → cw_core
        snap = self.snapshot()
        if snap["stage"] == st.STAGE_CW_PROJECT:
            self.bridge.confirmCwStage()
            self.sleep(1.0)
            snap = self.snapshot()
        log(f"setup 完成：stage={snap['stage']}")

    def _discuss_and_confirm(self, msg: str, expect_stage: str, wait_sec: float):
        """讨论一轮 → 确定总结定稿 → 断言推进到 expect_stage"""
        self.bridge.submitCwMessage(msg, "discuss")
        self.wait_idle(wait_sec, f"讨论回复({expect_stage})")
        state = self.cw.load()
        stage = self.bridge._get_cw_stage_key()
        reply = (co_dialogue_transcript_tail(state, stage))
        if not reply.strip():
            die(f"{stage} 讨论无 agent 回复")
        log(f"讨论回复 {len(reply)} 字")
        self.bridge.confirmCwStage()
        self.wait_idle(wait_sec, f"总结定稿({expect_stage})")
        snap = self.snapshot()
        if snap["stage"] != expect_stage:
            die(f"阶段推进失败：期望 {expect_stage}，实际 {snap['stage']}")
        return reply

    def step_core(self):
        self._discuss_and_confirm(
            "基于选题信息给出核心设定：题材定位、核心看点、主要角色表（含陈默/"
            "笔记本前主人线索角色）、读者契约。讨论要短，直接给结构化草案。",
            st.STAGE_CW_OUTLINE, 1800)

    def step_outline(self):
        self._discuss_and_confirm(
            "依据核心设定产出全书大纲草案：单元划分与章节区间（全书约 300 章）、"
            "主线推进节奏、终局储备。要点式即可。",
            st.STAGE_CW_WORLDBOOK, 1800)

    def step_worldbook(self):
        # ③ 世界书：先「生成草案」（compose 撰写）再确定落盘（拆 世界书+正则）
        self.bridge.generateCwDraft()
        self.wait_idle(1800, "世界书草案")
        state = self.cw.load()
        stage = self.bridge._get_cw_stage_key()
        reply = co_dialogue_transcript_tail(state, stage)
        if not reply.strip():
            die("世界书草案无 agent 回复——拒绝在空转写上定稿（空回复守卫）")
        log(f"世界书草案 {len(reply)} 字")
        self.bridge.confirmCwStage()
        self.wait_idle(1800, "世界书定稿")
        snap = self.snapshot()
        if snap["stage"] != st.STAGE_CW_UNIT:
            die(f"世界书阶段推进失败：实际 {snap['stage']}")
        for rel in ("设定/世界书.md", "设定/正则.md"):
            if not snap["products"].get(rel):
                die(f"{rel} 未落盘")

    def step_unit(self):
        # ④ 单元细纲：登记单元 → 总纲草案 → 确定触发滚动批次 → 校验 → 进正文
        self.bridge.setCwUnitRange(1, 10, "开篇：捡到改命笔记，第一次改命与代价")
        self.bridge.generateCwDraft()
        self.wait_idle(1800, "单元总纲草案")
        self.bridge.confirmCwStage()
        self.wait_idle(3600, "单元定稿+细纲批次")
        state = self.cw.load()
        if not project.list_outlines(PROJ):
            die("细纲批次未落盘（大纲/细纲_*.md 缺失）")
        n = len(project.list_outlines(PROJ))
        log(f"细纲已出 {n} 章")
        # 校验最新批 → 通过即进入正文
        self.bridge.validateCwOutlines()
        self.wait_idle(1800, "细纲校验")
        snap = self.snapshot()
        log(f"unit 完成后：stage={snap['stage']} outlines={snap['outlines']}")

    def step_unitfix(self):
        """校验拦截后的作者修复路径：按校验意见改细纲 → 复检 → 进正文"""
        p = os.path.join(PROJ, "大纲", "细纲_第004章.md")
        text = open(p, encoding="utf-8").read()
        bad = "陈默找到前主人留下的三步纸条，获得首次尝试的操作框架。"
        good = ("陈默找到一张来源未明、疑似与前主人有关的纸条，"
                "获得首次尝试的操作框架。")
        if bad in text:
            open(p, "w", encoding="utf-8").write(text.replace(bad, good))
            log("细纲_第004章 已按校验意见修改（纸条归属改为来源未明）")
        else:
            log("细纲_第004章 未见预期原句（可能已改过），跳过编辑直接复检")
        self.bridge.validateCwOutlines()
        self.wait_idle(1800, "细纲复检")
        snap = self.snapshot()
        log(f"unitfix 后：stage={snap['stage']} outlines={snap['outlines']}")
        if snap["stage"] != st.STAGE_CW_PROSE:
            state = self.cw.load()
            tr = ((st.ensure_cw(state).get("transcript") or {})
                  .get(st.STAGE_CW_UNIT) or [])
            tail = (tr[-1] or {}).get("text", "") if tr else ""
            die(f"复检后未进入正文阶段。校验尾部：{tail[:500]}")

    def step_prose1(self):
        # ⑤ 正文：第 1 章 草案 → 提取落稿 → supervisor 比对 → 确定锁定
        # （真作者路径：字数不足先扩写一轮；比对需调整走 F2 自动改写）
        self.bridge.openChapter(1)
        self.sleep(0.5)
        body = (self.bridge._chapter_text or "").strip()
        if not body:
            self.bridge.generateCwDraft()
            self.wait_idle(3600, "第1章正文草案")
        self.bridge.proseToEditor()
        self.wait_idle_soft(600, "保存后读改揣摩（M4）")
        body = (self.bridge._chapter_text or self.bridge._working_text or "").strip()
        if not body:
            die("第1章正文未落稿")
        log(f"第1章草稿 {len(body)} 字")
        if len(body) < 1800:
            log("字数低于 2000 目标带（±15%），按作者路径扩写一轮")
            self.bridge.submitCwMessage(
                "本章正文约%d字，低于目标2000字。请在保持现有情节、人物、"
                "证据链与结尾钩子完全不变的前提下扩写到1950~2300字："
                "补足场景肌理与人物反应，不要新增独立支线。" % len(body),
                "compose")
            self.wait_idle(3600, "第1章扩写")
            self.bridge.proseToEditor()
            self.wait_idle_soft(600, "扩写后读改揣摩")
            body = (self.bridge._chapter_text or self.bridge._working_text or "").strip()
            log(f"第1章扩写后 {len(body)} 字")
        self.bridge.confirmCwStage()   # 触发 supervisor 比对
        self.wait_idle(3600, "第1章衔接比对")
        state = self.cw.load()
        sup = (st.ensure_cw(state).get("supervised") or {})
        if str(1) not in sup:
            # 比对结论=需调整时已自动派改写（F2）——等改写完成再落稿复检
            self.wait_idle(3600, "第1章自动改写（F2）")
            self.bridge.proseToEditor()
            self.wait_idle_soft(600, "改写后读改揣摩")
            self.bridge.confirmCwStage()
            self.wait_idle(3600, "第1章复检")
            state = self.cw.load()
            sup = (st.ensure_cw(state).get("supervised") or {})
        if str(1) not in sup:
            report = (st.ensure_cw(state).get("report") or {})
            die(f"第1章比对未收口：supervised={sup} report={report.get('num')} "
                f"attention={getattr(self.bridge, '_cw_supervisor_attention', None)}")
        self.bridge.confirmCwStage()   # 已比对 → 确认即锁定
        self.sleep(1.0)
        snap = self.snapshot()
        if 1 not in snap["locked"]:
            die(f"第1章未锁定：locked={snap['locked']}")
        log("第1章已锁定 ✓")

    def step_prose1b(self):
        """第1章收口续：按报告手动定向改写一轮 → 复检；仍未收口走越权出口（留痕）"""
        self.bridge.openChapter(1)
        self.sleep(0.5)
        state = self.cw.load()
        if str(1) not in (st.ensure_cw(state).get("supervised") or {}):
            self.bridge.submitCwMessage(
                "主 Agent 复检提出三处衔接缺口，请定向改写本章（其余内容不动）："
                "①交代编号透明袋的拆袋/转接与双方见证，弥合证物保管链；"
                "②让陈默的翻页决定有明确动机转变（由「今天不翻」到行动的理由）；"
                "③明确临时保管期限（18:00 前）内的行动安排，为下章返回复核留出时间锚点。",
                "compose")
            self.wait_idle(3600, "第1章定向改写")
            self.bridge.proseToEditor()
            self.wait_idle_soft(600, "定向改写后读改揣摩")
            self.bridge.confirmCwStage()
            self.wait_idle(3600, "第1章三比对")
            state = self.cw.load()
        sup = (st.ensure_cw(state).get("supervised") or {})
        if str(1) in sup:
            self.bridge.confirmCwStage()   # 已比对 → 锁定
        else:
            log("两轮比对仍需调整——按作者判断走「无视报告并锁定（留痕）」出口")
            self.bridge.forceLockChapter()
        self.sleep(1.0)
        snap = self.snapshot()
        if 1 not in snap["locked"]:
            # 字数闸门弹出确认框（lockBlocked）——作者点「仍要锁定」＝强锁留痕
            log("字数闸门拦截——按作者决断走 forceConfirmChapterLocked（强锁留痕）")
            self.bridge.forceConfirmChapterLocked()
        self.sleep(1.0)
        snap = self.snapshot()
        if 1 not in snap["locked"]:
            die(f"第1章仍未锁定：locked={snap['locked']}")
        state = self.cw.load()
        locked_meta = (st.ensure_cw(state).get("locked") or {}).get("1") or {}
        log(f"第1章已锁定 ✓ locked_meta={json.dumps(locked_meta, ensure_ascii=False)[:200]}")

    def step_prose2(self):
        # 第 2 章：F1 跳过比对出口 + 写作规约沉淀 + 反哺补跑（真模型走一遍）
        from app.core import writing_rules
        # 上一轮驱动退出打断了第1章反哺 worker——CW-G6 补跑（force 越过新鲜度去重）
        self.bridge._maybe_backflow(1, force=True)
        self.wait_idle_soft(1800, "第1章反哺补跑")
        # D4 写作规约沉淀：把第 1 章作者反馈沉淀为持久规约（下章注入验证 2/2）
        r = writing_rules.add_rule(
            PROJ, "章节开头三段内必须出现与上一章结尾直接挂钩的具体动作或对话，不写环境铺垫。",
            source_ch=1)
        log(f"写作规约沉淀：{'成功 id=' + str(r.get('id')) if r else '被去重跳过'}")
        self.bridge.openChapter(2)
        self.sleep(0.5)
        self.bridge.generateCwDraft()
        self.wait_idle(3600, "第2章正文草案")
        self.bridge.proseToEditor()
        self.wait_idle_soft(600, "第2章读改揣摩")
        body = (self.bridge._chapter_text or self.bridge._working_text or "").strip()
        if not body:
            die("第2章正文未落稿")
        log(f"第2章草稿 {len(body)} 字")
        # F1 出口：不走比对，直接「跳过比对并锁定」（= forceLockChapter，强锁留痕）
        self.bridge.forceLockChapter()
        self.sleep(1.0)
        snap = self.snapshot()
        if 2 not in snap["locked"]:
            # 字数闸门弹出确认框——作者点「仍要锁定」＝强锁留痕
            log("字数闸门拦截——按作者决断走 forceConfirmChapterLocked（强锁留痕）")
            self.bridge.forceConfirmChapterLocked()
        self.sleep(1.0)
        snap = self.snapshot()
        if 2 not in snap["locked"]:
            die(f"第2章未锁定：locked={snap['locked']}")
        log("第2章已锁定（F1 跳过比对出口，强锁留痕）✓")
        # D4 注入验证：状态卡应含写作规约段
        from app.core import state_card
        from app import project as proj_mod
        card = state_card.build_state_card(PROJ, 2, proj_io=proj_mod)
        has_rules = "写作规约" in card if isinstance(card, str) else None
        record("prose2_extra", rule_added=bool(r), state_card_has_rules=has_rules)

    def _wait_backflowed(self, nums, timeout: float):
        """反哺 worker 不走 _cw_busy——轮询 state['backflowed'] 落账为准"""
        import time as _t
        t0 = _t.time()
        pending = set(nums)
        while pending and _t.time() - t0 < timeout:
            self.sleep(3.0)
            state = self.cw.load()
            done = set((state.get("backflowed") or {}).keys())
            pending -= {str(n) for n in nums} & done
            if not pending:
                break
        return not pending

    def step_prose2b(self):
        """收尾：补跑两章反哺（前两轮 worker 被驱动退出杀死）+ D4 状态卡注入验证"""
        for n in (1, 2):
            state = self.cw.load()
            if str(n) in (state.get("backflowed") or {}):
                log(f"第{n}章反哺已有落账，跳过")
                continue
            self.bridge._maybe_backflow(n, force=True)
            ok = self._wait_backflowed([n], 1800)
            log(f"第{n}章反哺：{'完成' if ok else '超时未落账'}")
        # D4 注入验证：状态卡应含写作规约段（proj_io 参数注入，S6a 口径）
        from app.core import state_card
        from app import project as proj_mod
        card = state_card.build_state_card(PROJ, 2, proj_io=proj_mod)
        has_rules = "写作规约" in card if isinstance(card, str) else None
        rules = None
        try:
            rules = json.load(open(os.path.join(PROJ, "追踪", "写作规约.json"),
                                   encoding="utf-8")).get("rules")
        except Exception:  # noqa: BLE001
            pass
        record("prose2_extra", state_card_has_rules=has_rules,
               rules=rules, backflowed=(self.cw.load().get("backflowed") or {}))
        log(f"状态卡含写作规约段：{has_rules}；规约条数：{len(rules or [])}")

    def step_status(self):
        snap = self.snapshot()
        log(json.dumps(snap, ensure_ascii=False, indent=1))
        log(f"usage={self.usage_totals()}")


def co_dialogue_transcript_tail(state: dict, stage: str) -> str:
    from app.core import co_dialogue
    return co_dialogue.transcript_text(state, stage) or ""


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    step = sys.argv[1]
    d = Driver()
    d.run(step)
    # 不调用 app.quit()——offscreen 下直接退出即可
    sys.exit(0)


if __name__ == "__main__":
    main()
