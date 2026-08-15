# -*- coding: utf-8 -*-
"""流水线断点状态机：pipeline_state.json 原子读写

任何阶段失败/暂停/崩溃后，重新打开项目可从断点续跑。
"""
import json
import os
import tempfile

STATE_FILENAME = "pipeline_state.json"

# 总流水线阶段
STAGE_INIT = "init"            # 立项（仅有选题信息）
STAGE_SETTING = "setting"      # 核心设定
STAGE_OUTLINE = "outline"      # 全书大纲
STAGE_CH_OUTLINE = "ch_outline"  # 章节细纲
STAGE_PROSE = "prose"          # 正文微循环
STAGE_DONE = "done"            # 完本

STAGE_LABELS = {
    STAGE_INIT: "立项",
    STAGE_SETTING: "核心设定",
    STAGE_OUTLINE: "全书大纲",
    STAGE_CH_OUTLINE: "章节细纲",
    STAGE_PROSE: "正文写作",
    STAGE_DONE: "完本",
}
STAGE_ORDER = [STAGE_SETTING, STAGE_OUTLINE, STAGE_CH_OUTLINE, STAGE_PROSE, STAGE_DONE]

# 章节微循环步骤
STEP_ASSEMBLE = "assemble"
STEP_DRAFT = "draft"
STEP_ENRICH = "enrich"
STEP_SCAN = "scan"
STEP_DESLOP = "deslop"
STEP_REVIEW = "review"
STEP_FINALIZE = "finalize"

STEP_LABELS = {
    STEP_ASSEMBLE: "上下文组装",
    STEP_DRAFT: "草稿生成",
    STEP_ENRICH: "字数扩写",
    STEP_SCAN: "AI 味扫描",
    STEP_DESLOP: "去味改写",
    STEP_REVIEW: "审校",
    STEP_FINALIZE: "定稿落库",
}
STEP_ORDER = [STEP_ASSEMBLE, STEP_DRAFT, STEP_SCAN, STEP_DESLOP, STEP_REVIEW, STEP_FINALIZE]

DEFAULT_STATE = {
    "stage": STAGE_INIT,
    "current_chapter": 0,       # 最近定稿的章号
    "chapter_step": "",         # 当前章执行到微循环哪一步（断点用）
    "total_chapters": 0,        # 计划总章数（0=不限）
    "paused": False,
    "history": [],              # [{num,title,words,deslop_blocking,deslop_advisory,status,ts}]
    "pending_guidance": {},     # {章号: 重写指导语}：用户"带指导重写"时暂存，续跑时消费
}


def set_guidance(proj: str, state: dict, num: int, text: str):
    """登记某章的重写指导（写入 state 并落盘）"""
    state.setdefault("pending_guidance", {})[num] = text
    save_state(proj, state)


def take_guidance(state: dict, num: int) -> str:
    """取走某章的待用指导（消费即删除）"""
    pg = state.get("pending_guidance") or {}
    return pg.pop(str(num), "")


def state_path(proj: str) -> str:
    return os.path.join(proj, STATE_FILENAME)


def load_state(proj: str) -> dict:
    path = state_path(proj)
    state = json.loads(json.dumps(DEFAULT_STATE))
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                state[k] = v
        except Exception:
            pass
    return state


def save_state(proj: str, state: dict):
    """原子写入：先临时文件再替换，防中途崩溃损坏状态"""
    path = state_path(proj)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=proj)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def append_history(proj: str, state: dict, record: dict):
    import datetime
    record = dict(record)
    record["ts"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state["history"] = [h for h in state.get("history", []) if h.get("num") != record.get("num")]
    state["history"].append(record)
    state["history"].sort(key=lambda h: h.get("num", 0))
    save_state(proj, state)
