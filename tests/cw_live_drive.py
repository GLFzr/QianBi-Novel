# -*- coding: utf-8 -*-
"""共写档真机测试驱动辅助：等待磁盘状态 + UI 操作封装（配合 ui_drive.py 使用）"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STATE_REL = "pipeline_state.json"


def state_of(proj: str) -> dict:
    p = os.path.join(proj, STATE_REL)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def cw_stage(proj: str) -> str:
    s = state_of(proj)
    return (s.get("cw") or {}).get("stage", "")


def transcript_len(proj: str, stage: str) -> int:
    s = state_of(proj)
    return len(((s.get("cw") or {}).get("transcript") or {}).get(stage) or [])


def wait_until(desc: str, cond, timeout: float = 900, interval: float = 5.0):
    """轮询等待条件成立（默认 15 分钟上限；LLM 慢时手动加大）"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cond():
                print(f"[wait] OK {desc} ({time.time() - t0:.0f}s)")
                return True
        except Exception as e:  # noqa: BLE001
            print(f"[wait] probe err {e}")
        time.sleep(interval)
    print(f"[wait] TIMEOUT {desc}")
    return False


def wait_transcript_grows(proj: str, stage: str, expect: int, timeout: float = 900):
    return wait_until(f"transcript[{stage}] >= {expect}",
                      lambda: transcript_len(proj, stage) >= expect, timeout)


def wait_stage(proj: str, stage: str, timeout: float = 900):
    return wait_until(f"stage == {stage}", lambda: cw_stage(proj) == stage, timeout)


def wait_file(proj: str, rel: str, timeout: float = 900):
    p = os.path.join(proj, rel)
    return wait_until(f"file exists {rel}", lambda: os.path.isfile(p), timeout)


if __name__ == "__main__":
    proj = os.path.join("tests_output", "cw_live", "凡人问道")
    print("stage:", cw_stage(proj), "| transcript core:", transcript_len(proj, "cw_core"))
