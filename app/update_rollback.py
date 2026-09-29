# -*- coding: utf-8 -*-
"""更新后首启观察期与引导回滚（GUI-only，R3）

裁决（w5_update.md §3）：**只做引导式回滚，不做自动回滚**——新版首启即崩时
app 自己就是崩的那个，真自动回滚需要一个熬过 app 死亡的观察者进程，等于在最
不允许出错的路径上新增常驻活动部件；误判的代价（静默降级+抹掉现场）不对称。

这里只回答三个问题，动作全部留给用户：
  ① 「刚更新过」可感知：journal（update_install.write_journal，C19）装完即被
     main.py 对账清掉，罩不住「首启崩溃后第二次启动」——所以相位另落一份
     update_first_run.json（updates/ 下），活过「装完后的第一次成功启动」；
  ② 更新后首启崩没崩：相位停在 first_run（=正常关闭标记 stable 还没打上）∧
     crashes/ 里有 mtime 晚于更新时刻的新 dump → 判崩溃；
  ③ 回滚的路子在不在：updates/ 保留的上一版安装包（U-C prune 保当前+上一版，
     必有货）——恢复对话框数据一次给齐，桥（bridge）只负责把横幅亮出来。

判定与落盘全在本模块（纯函数可测）；bridge._check_update_rollback 只做 IO 编排。
"""
from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger("qianbi.update")

STATE_NAME = "update_first_run.json"   # first_run 相位文件：updates/ 下

PHASE_FIRST_RUN = "first_run"   # 更新完成、首次运行观察中（正常关闭标记还没打上）
PHASE_STABLE = "stable"         # 正常关闭标记：首启一整轮无新崩溃现场


def state_path(updates_dir: str = "") -> str:
    from . import update_check as uc
    return os.path.join(updates_dir or uc.updates_dir(), STATE_NAME)


def read_state(updates_dir: str = "") -> dict:
    """读不到/读坏都返回 {}：相位文件只是观察期记号，坏了不能挡正常启动"""
    try:
        with open(state_path(updates_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(entry: dict, updates_dir: str = "") -> dict:
    """先写临时文件再 replace，断电不留半份（同 write_journal 的落盘纪律）"""
    path = state_path(updates_dir)
    parent = os.path.dirname(path)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError:
        pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(entry, f, ensure_ascii=False)
    os.replace(tmp, path)
    return entry


def clear_state(updates_dir: str = "") -> None:
    try:
        os.remove(state_path(updates_dir))
    except OSError:
        pass


def begin_first_run(journal: dict, marker_text: str = "",
                    updates_dir: str = "") -> dict:
    """journal(launching) + marker → first_run 相位：更新装完了，观察期开始

    update_ts 取 journal.ts（拉起安装器前落盘的时刻）——「晚于更新时刻的 dump」
    的基准就是它。marker_text 只做存在性判断（版本以 journal.to 为准，干净）。
    """
    entry = {"phase": PHASE_FIRST_RUN,
             "from": str((journal or {}).get("from") or ""),
             "to": str((journal or {}).get("to") or ""),
             "pkg": str((journal or {}).get("pkg") or ""),
             "update_ts": float((journal or {}).get("ts") or 0.0),
             "begun_at": time.time()}
    return write_state(entry, updates_dir)


def mark_stable(entry: dict, updates_dir: str = "") -> dict:
    """正常关闭标记：首启一整轮没留下任何新崩溃现场 → 相位推进 stable

    观察期到「下一次启动」为止：硬杀/断电没有 dump，证据不在场就不喊回滚，
    相位照常收口——回滚横幅只认崩溃现场，不拿「可能被硬杀」吓人。
    """
    entry = dict(entry or {})
    entry["phase"] = PHASE_STABLE
    entry["stable_at"] = time.time()
    return write_state(entry, updates_dir)


def list_dumps(crashes_dir: str = "") -> list:
    """crashes/ 里的崩溃现场（crash_*.md），按新→旧排；目录读不了就是没有"""
    if not crashes_dir:
        from .crash import CRASH_DIR
        crashes_dir = CRASH_DIR
    out = []
    try:
        for n in os.listdir(crashes_dir):
            if not n.startswith("crash_"):
                continue
            p = os.path.join(crashes_dir, n)
            try:
                out.append({"path": p, "mtime": os.path.getmtime(p)})
            except OSError:
                continue
    except OSError:
        return []
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def evaluate(state: dict, dumps: list) -> dict:
    """崩溃判定（纯函数）：first_run 相位 ∧ 有晚于更新时刻的新 dump → 判崩溃

    - state 空或相位不是 first_run（stable/缺失=正常关闭标记在）→ none；
    - first_run 而无新 dump → watch（观察继续，不声不响）；
    - first_run ∧ 新 dump → crash：恢复对话框数据一次给齐（from/to/pkg/dump）。
    """
    if not state or state.get("phase") != PHASE_FIRST_RUN:
        return {"state": "none"}
    ts = float(state.get("update_ts") or 0.0)
    fresh = [d for d in (dumps or []) if float(d.get("mtime") or 0.0) > ts]
    if not fresh:
        return {"state": "watch", "to": str(state.get("to") or "")}
    d0 = fresh[0]
    return {"state": "crash", "active": True,
            "from": str(state.get("from") or ""), "to": str(state.get("to") or ""),
            "pkg": str(state.get("pkg") or ""),
            "dump": str(d0.get("path") or ""), "dump_ts": float(d0.get("mtime") or 0.0),
            "update_ts": ts}


def previous_installer(updates_dir: str, current_version: str) -> str:
    """updates/ 里版本号比当前版旧的最近一份安装包（回滚用的就是它）

    U-C 的 prune 保「当前+上一版」→ 正常必有货；实在没有（被手动清了）就返回
    空串，横幅退化为只给发布页指引，绝不编一个不存在的路径出来。
    """
    from . import update_check as uc
    from . import update_install as ui
    try:
        names = os.listdir(updates_dir or uc.updates_dir())
    except OSError:
        return ""
    cur = uc.parse_ver(current_version or "")
    best, best_v = "", None
    for n in sorted(names):
        if not n.lower().endswith(".exe"):
            continue
        m = ui._VER_IN_NAME.search(n)
        if not m:
            continue
        v = uc.parse_ver(m.group(1))
        if v >= cur:
            continue
        if best_v is None or v > best_v:
            best, best_v = os.path.join(updates_dir or uc.updates_dir(), n), v
    return best


def startup_check(journal: dict, marker_text: str, current_version: str,
                  crashes_dir: str = "", updates_dir: str = "") -> dict:
    """启动对账处的回滚检查（IO 编排 + 判定，bridge 一行接线用）

    相位机（崩在半路也不丢，相位文件活过对账对 journal 的清理）：
      无相位文件 ∧ journal(launching) ∧ marker 在 → begin_first_run（这次刚装完，
        本轮只立相位不打标——首启还没开始跑，不能自己给自己开「正常关闭」证明）；
      相位 stable → 观察期已正常收口，清文件归零；
      相位 first_run（上次运行没走到收口）：
        - 现在跑的已不是当时装的版（用户自己动过）→ 观察失效，清文件；
        - 无新 dump → mark_stable（正常关闭标记：首启整轮无现场）→ 返回 none；
        - 有新 dump → 判崩溃，相位**保留**（横幅每次启动都亮，直到用户表态：
          「继续用新版/运行上一版」都会 consume 掉相位文件）。
    """
    from . import update_check as uc
    updates_dir = updates_dir or uc.updates_dir()
    state = read_state(updates_dir)
    created_now = False
    if not state:
        if journal and journal.get("phase") == "launching" and marker_text:
            state = begin_first_run(journal, marker_text, updates_dir)
            created_now = True
        else:
            return {}                     # 没更新过（或安装器没跑完，归 C19 notify 管）
    if state.get("phase") == PHASE_STABLE:
        clear_state(updates_dir)          # 上一相位已确认正常关闭：收口归零
        return {}
    if state.get("phase") != PHASE_FIRST_RUN:
        return {}
    to_ver = str(state.get("to") or "")
    if to_ver and to_ver != str(current_version or ""):
        clear_state(updates_dir)          # 跑的已不是当时装的那个版：观察失效
        return {}
    verdict = evaluate(state, list_dumps(crashes_dir))
    if verdict.get("state") == "crash":
        verdict["installer"] = previous_installer(updates_dir, current_version)
        verdict["updatesDir"] = updates_dir
        logger.warning("更新后首启崩溃命中：to=%s dump=%s installer=%s",
                       verdict.get("to"), verdict.get("dump"), verdict.get("installer"))
        return verdict
    if not created_now:
        mark_stable(state, updates_dir)   # 首启一整轮无新现场：打正常关闭标记
    return {}
