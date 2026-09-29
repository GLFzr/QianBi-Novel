# -*- coding: utf-8 -*-
"""台账告警落账（C35 G5 的 state/session_events 写通道；S6a 自 app/usage.py 下沉）

usage 台账命中告警规则后，把异常条目写进项目 pipeline_state.json 的 anomalies 键
并同步 record_event 到 项目/追踪/session_events.jsonl。这一步本来长在 app.usage
的 report_anomaly 里（函数内延迟 import state/volume_session）——正是 usage↔core
SCC 的闭环比。S6a 依赖倒置：写通道下沉 core（core→core 合法方向），导入期向
core.ledger_view 自装订 persist 钩子；usage/orchestrator 只经 ledger_view 门面
调用，app-top 不再反向持 core 写通道。口径逐字承自 C35 原文。
"""
from . import ledger_view as _lv
from . import state as _st
from . import volume_session as _vs

_STATE_ANOMALY_KEEP = 500


def persist(proj: str, entry: dict) -> bool:
    """异常条目落账：state['anomalies'] 去重追加 + session_events 事件。

    返回是否真正新增（同 (rule, ch) 已在 state 里时只返回 False，不重复落）。
    调用方（ledger_view.report_anomaly）已兜异常——这里只管写。
    """
    state = _st.load_state(proj)
    lst = state.get("anomalies")
    if not isinstance(lst, list):
        lst = state["anomalies"] = []
    if any(a.get("rule") == entry["rule"] and a.get("ch") == entry["ch"]
           for a in lst if isinstance(a, dict)):
        return False
    lst.append(entry)
    if len(lst) > _STATE_ANOMALY_KEEP:
        del lst[: len(lst) - _STATE_ANOMALY_KEEP]
    _st.save_state(proj, state)
    _vs.record_event(proj, "usage_anomaly", rule=entry["rule"],
                     ch=entry["ch"], level=entry["level"], msg=entry["msg"])
    return True


# 导入即装订（orchestrator 导入本模块触发；proj 只在 orchestrator.run 登记后非空，
# 故未导入 orchestrator 的旁路调用天然走「只留镜像」路径，与 C35 未登记语义一致）
_lv.bind_persist(persist)
