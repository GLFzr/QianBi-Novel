# -*- coding: utf-8 -*-
"""演示导演（0.20.0 演示引导）

执行 assets/demo/script.json 的步骤脚本：导航 → 高亮 → 自动填表 → 伪流式回放 →
等待用户点击真控件 → 推进。用户全程零输入，只点高亮目标。

与 QML 的契约（bridge 作中转）：
  Python→QML  demoCoachJson(str)   引导气泡（text/target/container/mode/step/total）
              demoActionJson(str)  动作请求（nav / click / fill_seq）
  QML→Python  demoStart / demoSkip / demoNext / demoStepDone / demoNotifyPanel / demoAttach

演示模式硬隔离：startPipeline 在 demoActive 时直接拒绝；DemoReplayer 不碰任何
LLM 模块；演示书用真实项目目录承载，但打 demo 标记。
"""
import json
import logging
import os
import shutil

from PySide6.QtCore import QObject, QTimer

from ..core import state as st
from .. import project
from .demo_pack import DemoPack
from .demo_replay import DemoReplayer

# script.json 的 user_click 步骤 id → 完成信号来源（QML hook 或 bridge 信号分支）
_STEP_DONE_HOOKS = {
    "click_new_project": "qml",        # newProjectDialog.onOpened 里 demoStepDone
    "click_create": "projectOpened",   # bridge.projectOpened 信号
    "cw_switch": "cw",                 # cwModeChanged 且 runMode==cw
    "cw_send": "cw_submit",            # submitCwMessage 演示分支
    "cw_write_send": "cw_submit",
    "cw_confirm": "cw_confirm",        # confirmCwStage 演示分支
    "finish_nav": "panel:settings",    # demoNotifyPanel("settings")
}


logger = logging.getLogger("qianbi.demo")


class DemoDirector(QObject):
    def __init__(self, bridge):
        super().__init__(bridge)
        self.bridge = bridge
        self.pack = None
        self.step_idx = -1
        self.cw_turn_idx = 0
        self.demo_book_path = ""
        self._win = None                       # demoAttach 挂进来的 QQuickWindow
        self._replayer = DemoReplayer(bridge, self)
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._auto_fire)
        self._shot_dir = os.environ.get("QIANBI_DEMO_SHOT_DIR", "")
        self._shot_n = 0
        # 环境变量：QIANBI_DEMO_AUTO=1 全自动代点（自测/冒烟/截图扫描用）
        self.auto_mode = os.environ.get("QIANBI_DEMO_AUTO") == "1"

    # ============ 状态 ============

    @property
    def active(self) -> bool:
        return self.pack is not None and 0 <= self.step_idx < len(self.pack.steps)

    @property
    def step(self) -> dict:
        if self.active:
            return self.pack.steps[self.step_idx]
        return {}

    # ============ 入口（bridge 调） ============

    def start(self) -> bool:
        self.pack = DemoPack.load()
        if self.pack is None:
            self.bridge.toast.emit("warn", "演示内容包缺失或损坏（assets/demo）")
            return False
        self.step_idx = -1
        self.cw_turn_idx = 0
        self._shot_n = 0
        self._replayer.stop()
        logger.info("演示启动：auto=%s shot_dir=%s win=%s",
                    self.auto_mode, self._shot_dir or "未设置", self._win is not None)
        self._reset_demo_book()
        self._advance()
        return True

    def skip(self):
        self._replayer.stop()
        self._auto_timer.stop()
        self._cleanup_stream()
        self._set_demo_done()
        self.step_idx = -1
        self._emit_coach(None)
        self.bridge.toast.emit("info", "演示已跳过——随时可在书架空态再看一次")

    def _cleanup_stream(self):
        """中途退出：把编辑器从流式展示态拉回磁盘态，别让 isStreaming 卡死"""
        b = self.bridge
        b._streaming = False
        b._stream_stage_label = ""
        b.streamingChanged.emit()
        b.streamStageChanged.emit()
        if b.proj:
            chapters = project.list_chapters(b.proj)
            if chapters:
                b._cur_num = chapters[-1][0]
                b._chapter_path = chapters[-1][2]
                b._chapter_text = project.read_file(chapters[-1][2])
                b.chapterTextChanged.emit()

    def next(self):
        if self.active:
            self._advance()

    def step_done(self, step_id: str):
        s = self.step if self.active else {}
        if s.get("mode") == "fill_seq" and step_id == "fill_seq_done":
            self._advance()
        elif self.active and s.get("id") == step_id:
            self._advance()

    def notify_panel(self, panel: str):
        if self.active and self.step.get("mode") == "user_click" \
                and _STEP_DONE_HOOKS.get(self.step.get("id")) == f"panel:{panel}":
            self._advance()

    def on_cw_mode_changed(self):
        # 注意重入：_enter_cw_stage 里会再发 cwModeChanged——先推进步骤
        # （step 不再匹配 cw 钩子）再布置舞台，环就断了
        if self.active and _STEP_DONE_HOOKS.get(self.step.get("id")) == "cw" \
                and self.bridge.runMode() == "cw":
            self._advance()
            self._enter_cw_stage()

    # ============ 共写演示分支（bridge.submitCwMessage / confirmCwStage 调） ============

    def cw_submit(self, text: str, mode: str) -> bool:
        """演示中拦截共写发送：真实转写 + 伪流式回复。返回 True=已接管。
        回放结束才推进步骤（回复流完之前不进入下一步）"""
        if not self.active:
            return False
        s = self.step
        if s.get("mode") != "user_click" or \
                _STEP_DONE_HOOKS.get(s.get("id")) != "cw_submit":
            return False
        turn = self.pack.cw_turn(0 if s.get("id") == "cw_send" else 1)
        text = (text or "").strip()
        if not turn or not text:
            return False
        b = self.bridge
        from ..core import co_dialogue
        stage = b._get_cw_stage_key()
        state = b._cw.load()
        co_dialogue.transcript_append(state, stage, "user", text)
        b._cw_save_state(state)
        b._cw_sync_messages()
        b._console_log("user", text)
        reply = str(turn.get("reply") or "")
        if turn.get("mode") == "write":
            body = ""
            bf = turn.get("body_file")
            if bf and self.pack.book_has(bf):
                body = self.pack.book_file(bf)
            reply = (reply + "\n\n" + body).strip()
        b._cw_reply = ""
        b._set_cw_busy(True)
        self._emit_coach({**s, "text": "AI 正在流式回复——真实产品里也是这样逐字出来的（演示加速）"})
        tl = [self._replayer.op_wait(400)] + self._replayer.op_stream(reply, 6, 30)

        def _done():
            b._set_cw_busy(False)
            b._on_cw_done(reply)
            self._shot("cw_reply_end")
            self._advance()

        self._replayer.play(tl, on_done=_done)
        return True

    def cw_confirm(self) -> bool:
        """演示中拦截「✓ 确定」：真实推进共写阶段状态机，不调 LLM"""
        if not self.active:
            return False
        b = self.bridge
        from ..core import co_dialogue
        stage = b._get_cw_stage_key()
        state = b._cw.load()
        co_dialogue.transcript_append(
            state, stage, "agent",
            "✅ 阶段定稿（演示）：讨论结论已收敛——规则收紧为「预言必须付出等价代价」，"
            "父亲的「不可贪」批注作为悬案保留，0317 的延迟确认按疏密重排放进第 2-3 章。")
        order = st.CW_STAGE_ORDER
        i = order.index(stage) if stage in order else 0
        if i + 1 < len(order):
            state.setdefault("cw", {})["stage"] = order[i + 1]
        b._cw_save_state(state)
        b._cw_sync_messages()
        b.cwStageChanged.emit()
        b.generalChanged.emit()
        b.toast.emit("ok", "已进入「" + st.CW_STAGE_LABELS.get(
            b._get_cw_stage_key(), "下一阶段") + "」（演示）")
        self._advance()
        return True

    # ============ 步骤引擎 ============

    def _advance(self):
        self._auto_timer.stop()
        self.step_idx += 1
        if not self.active:
            self._set_demo_done()
            self._emit_coach(None)
            return
        self._run_step(self.step)
        # 延迟截图：等 QML 把新气泡/遮罩渲染出来，否则拍到的是上一步的画面。
        # tag/n 立即绑定——lambda 晚绑定会把快进后的步骤名拍进去
        if self._shot_dir and self._win is not None:
            tag = self.step.get("id") or f"s{self.step_idx}"
            QTimer.singleShot(450, lambda t=tag: self._shot(t))

    def _run_step(self, s: dict):
        b = self.bridge
        panel = s.get("panel") or ""
        if panel:
            b.demoNav.emit(panel)
        self._emit_coach(s)
        mode = s.get("mode")
        if mode == "user_click":
            if self.auto_mode:
                self._auto_timer.start(500)
            # 手动：等 QML hook / 对应信号推进（见 _STEP_DONE_HOOKS）
        elif mode == "user_click_cw":
            if self.auto_mode:
                self._auto_timer.start(500)
        elif mode == "fill_seq":
            self._emit_action({"action": "fill_seq", "arg": s.get("fills") or []})
            # QML 填完回调 demoStepDone("fill_seq_done")
        elif mode == "replay":
            self._replayer.play(self._build_replay(s.get("replay") or ""),
                                on_done=self._advance)
        elif mode == "button_next":
            if self.auto_mode:
                self._auto_timer.start(400)
        elif mode == "finish":
            self._set_demo_done()
            self._leave_cw_back_to_auto()
        # user_click / user_click_cw：等 QML hook / 对应信号推进

    def _leave_cw_back_to_auto(self):
        """演示收尾：把运行档位悄悄切回自动档，用户填完 Key 点「开始」不被共写档拦住"""
        b = self.bridge
        try:
            if b.runMode() == "cw":
                b.setRunMode("auto")
        except Exception:  # noqa: BLE001  # 收尾兜底，失败不追究
            pass

    def _auto_fire(self):
        """auto 模式代点：模拟用户按下高亮目标"""
        if not self.active:
            return
        s = self.step
        if s.get("mode") in ("button_next", "auto", "fill_seq"):
            self.next()
            return
        target = s.get("target") or ""
        if s.get("mode") == "user_click_cw" or target == "modeChip":
            self.bridge.setRunMode("cw")
            return
        if target.startswith("nav_"):
            self._emit_action({"action": "nav", "arg": target[4:]})
            return
        self._emit_action({"action": "click", "arg": target})

    def _emit_action(self, payload: dict):
        self.bridge.demoAction.emit(json.dumps(payload, ensure_ascii=False))

    # ============ 回放时间线 ============

    def _build_replay(self, phase: str) -> list:
        b = self.bridge
        r = self._replayer
        P = self.pack
        proj = b.proj
        tl: list = []
        logs = {k: self._find_log(k) for k in
                ["上下文组装", "草稿完成", "阻断", "去味完成", "审校第 1", "审校通过", "追踪文件", "设定清算"]}

        def state_set(fn):
            state = st.load_state(proj)
            fn(state)
            st.save_state(proj, state)

        def refresh():
            b.refreshQueue()
            b._refresh_progress()
            # 强制阶段卡重读：卡片「完成」要在高亮环跳去下一步之前出现
            b.stageKeyChanged.emit()

        def w_book(rel):
            def _w():
                dst = os.path.join(proj, rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "w", encoding="utf-8", newline="\n") as f:
                    f.write(P.book_file(rel))
            return _w

        def write_many(rels):
            def _w():
                for rel in rels:
                    dst = os.path.join(proj, rel.replace("/", os.sep))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, "w", encoding="utf-8", newline="\n") as f:
                        f.write(P.book_file(rel))
            return _w

        if phase == "setting":
            tl += [r.op_console("核心设定生成中（题材预设：都市悬疑 · 平台：番茄）…"),
                   r.op_call(lambda: state_set(lambda s: s.update(stage=st.STAGE_SETTING))),
                   r.op_call(lambda: b._on_stage(st.STAGE_SETTING)),
                   r.op_wait(400)]
            tl += r.op_stream(P.book_file("设定/题材定位.md"), 42, 40)
            tl += [r.op_console("核心设定完成 → 设定/题材定位.md"),
                   r.op_console("世界书条目已生成 → 设定/世界书.md"),
                   r.op_call(w_book("设定/题材定位.md")),
                   r.op_call(w_book("设定/世界书.md")),
                   r.op_call(refresh), r.op_wait(600)]

        elif phase == "outline":
            tl += [r.op_console("全书大纲生成中…"),
                   r.op_call(lambda: state_set(lambda s: s.update(stage=st.STAGE_OUTLINE))),
                   r.op_call(lambda: b._on_stage(st.STAGE_OUTLINE)),
                   r.op_wait(300)]
            tl += r.op_stream(P.book_file("大纲/大纲.md"), 60, 35)
            tl += [r.op_console("全书大纲完成 → 大纲/大纲.md"),
                   r.op_call(w_book("大纲/大纲.md")), r.op_call(refresh), r.op_wait(500)]

        elif phase == "ch_outline":
            tl += [r.op_console("第 1 章细纲生成中…"),
                   r.op_call(lambda: state_set(lambda s: s.update(stage=st.STAGE_CH_OUTLINE))),
                   r.op_call(lambda: b._on_stage(st.STAGE_CH_OUTLINE)),
                   r.op_wait(300)]
            tl += r.op_stream(P.book_file("大纲/细纲_第001章.md"), 30, 50)
            tl += [r.op_console("细纲完成 → 大纲/细纲_第001章.md（4 节点：疏疏密密）"),
                   r.op_call(w_book("大纲/细纲_第001章.md")),
                   r.op_call(refresh), r.op_wait(500)]

        elif phase == "prose":
            tl += [r.op_call(lambda: b._on_chapter_started(1)),
                   r.op_call(lambda: state_set(lambda s: s.update(stage=st.STAGE_PROSE,
                                                                 total_chapters=66))),
                   r.op_call(lambda: b._on_stage(st.STAGE_PROSE))]
            if logs.get("上下文组装"):
                tl += [r.op_console(self._strip_stamp(logs["上下文组装"]))]
            tl += [r.op_step("assemble"), r.op_wait(800),
                   r.op_step("draft"),
                   r.op_call(lambda: b._on_stream_stage("正文草稿 · 第 1 章")),
                   r.op_wait(400)]
            stream_ops = r.op_stream(P.book_file(P.ch1["rel"]), 12, 110)
            # 中段抽帧：验证流式视觉（编辑器逐字增长、光标跟随）
            n = len(stream_ops)
            stream_ops.insert(n // 3, (0, lambda: self._shot("prose_p33")))
            stream_ops.insert(2 * n // 3, (0, lambda: self._shot("prose_p66")))
            tl += stream_ops

        elif phase == "deslop":
            tl += [r.op_step("scan"),
                   r.op_console(self._strip_stamp(logs.get("草稿完成") or "第 1 章 草稿完成")),
                   r.op_wait(700),
                   r.op_console(self._strip_stamp(logs.get("阻断") or "第 1 章 阻断 1 处 → 去味改写"), "warn"),
                   r.op_wait(500)]
            d = P.deslop or {}
            if d.get("before"):
                tl += [r.op_console("去味对照〔改前〕" + d["before"]),
                       r.op_wait(600),
                       r.op_console("去味对照〔改后〕" + (d.get("after") or "")),
                       r.op_wait(600)]
            tl += [r.op_console(self._strip_stamp(logs.get("去味完成") or "第 1 章 去味完成，复扫通过")),
                   r.op_step("deslop"), r.op_wait(500)]

        elif phase == "review":
            tl += [r.op_step("review"), r.op_wait(600)]
            votes = (P.review or {}).get("votes") or ["PASS", "PASS", "PASS"]
            for i, v in enumerate(votes, 1):
                tl += [r.op_console(f"审校第 {i}/3 票：{v}（fail=0）"), r.op_wait(1300)]
            tl += [r.op_console("审校通过（verdict=PASS）"), r.op_wait(500)]

        elif phase == "tracking":
            def finalize():
                # 正文落盘 + 章记录进 history（与真实流水线同构，全部 UI 由真实数据驱动）
                ch1 = P.ch1
                w_book(ch1["rel"])()
                state = st.load_state(proj)
                state["stage"] = st.STAGE_PROSE
                state["current_chapter"] = 1
                hist = state.setdefault("history", [])
                hist[:] = [h for h in hist if h.get("num") != 1]
                hist.append({"num": 1, "title": ch1["title"], "words": ch1["words"],
                             "deslop_blocking": 0, "review_blocking": 0,
                             "deslop_advisory": 1})
                st.save_state(proj, state)
                b._on_chapter_done({"num": 1, "title": ch1["title"], "words": ch1["words"],
                                    "deslop_blocking": 0, "review_blocking": 0,
                                    "deslop_advisory": 1})

            tl += [r.op_step("finalize"), r.op_call(finalize),
                   r.op_console(self._strip_stamp(logs.get("追踪文件") or
                                                  "追踪文件已更新：角色状态, 伏笔, 时间线, 上下文")),
                   r.op_call(write_many([f"追踪/{n}" for n in
                                         ["角色状态.md", "伏笔.md", "时间线.md", "上下文.md",
                                          "全局摘要.md", "章节摘要.md",
                                          "设定清算_第001.json", "连续性台账.json"]
                                         if P.book_has(f"追踪/{n}")])),
                   r.op_console(self._strip_stamp(logs.get("设定清算") or
                                                  "第 1 章 设定清算：违反 0（硬伤 0）")),
                   r.op_call(refresh), r.op_wait(800)]
        return tl

    @staticmethod
    def _strip_stamp(line: str) -> str:
        """queue.log 行去掉时间戳前缀，只留人话部分"""
        parts = line.split(" ", 2)
        return parts[2] if len(parts) >= 3 else line

    def _find_log(self, keyword: str) -> str:
        for ln in self.pack.log_lines():
            if keyword in ln:
                return ln
        return ""

    # ============ 演示书与配置 ============

    def _reset_demo_book(self):
        """重看演示：把上次的演示书删掉重建（幂等；只动打了 demo 标记的书）"""
        root = self.bridge.defaultBooksRoot()
        name = (self.pack.book_meta.get("name") or "种子书")
        path = os.path.join(root, name)
        marker = os.path.join(path, "pipeline_state.json")
        if os.path.isdir(path) and os.path.isfile(marker):
            try:
                state = st.load_state(path)
                if state.get("demo"):
                    shutil.rmtree(path, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass
        self.demo_book_path = path

    def _enter_cw_stage(self):
        """切到共写后，把共写阶段推进到「核心设定」（演示讨论的舞台）

        这里绝不能再发 cwModeChanged——它与 on_cw_mode_changed 互为回路，
        再发就是无限递归（真机炸过一次，faulthandler 里全是这一帧）。
        """
        b = self.bridge
        if not b.proj:
            return
        state = st.load_state(b.proj)
        cw = st.ensure_cw(state)
        if cw.get("stage") == st.STAGE_CW_PROJECT:
            cw["stage"] = st.STAGE_CW_CORE
            st.save_state(b.proj, state)
            b._cw_sync_messages()
            b.cwStageChanged.emit()
            b.toast.emit("ok", "共写阶段：核心设定（演示）")

    def _set_demo_done(self):
        try:
            self.bridge.cfg.setdefault("general", {})["demo_done"] = True
            from .. import config as cfg_mod
            cfg_mod.save_config(self.bridge.cfg)
        except Exception:  # noqa: BLE001
            pass

    # ============ 展示输出 ============

    def _emit_coach(self, step: dict):
        if step is None:
            self.bridge.demoCoach.emit("{}")
            return
        self.bridge.demoCoach.emit(json.dumps({
            "step": self.step_idx + 1,
            "total": len(self.pack.steps),
            "text": step.get("text") or "",
            "target": step.get("target") or "",
            "container": step.get("container") or "",
            "mode": step.get("mode") or "",
        }, ensure_ascii=False))

    def _shot(self, tag: str):
        """逐步截图（QIANBI_DEMO_SHOT_DIR 设置才启用；验证流水线用，不影响正常演示）"""
        if not self._shot_dir or self._win is None:
            return
        try:
            self._shot_n += 1
            img = self._win.grabWindow()
            path = os.path.join(self._shot_dir, f"{self._shot_n:03d}_{tag}.png")
            if not img.save(path):
                logger.warning("demo shot save 返回 False: %s", path)
        except Exception as e:  # noqa: BLE001  # 截图是诊断设施，失败要留痕
            logger.warning("demo shot 失败: %s", e)
