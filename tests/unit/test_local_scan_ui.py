# -*- coding: utf-8 -*-
"""扫描本地端口的接线护栏（0.20.4）。

这层只钉「线与出口在」：真正的探测行为由 test_local_endpoints 覆盖。
历史教训：功能建了但界面没有入口（0.25.0 台账的「建好没接线」），
所以桥面槽、结果属性、QML 按钮/填入函数三处必须同时存在。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


def test_bridge_exposes_scan_slot_and_results():
    src = _read("app/ui/bridge.py")
    assert re.search(r"def scanLocalPorts\(", src), "桥面缺少 scanLocalPorts 槽"
    assert "localScanFinished" in src, "缺少扫描完成信号"
    assert "localScanResults" in src, "缺少扫描结果属性"
    assert "_LocalScanWorker" in src, "扫描必须在后台线程，不能在 UI 线程阻塞"
    assert "local_ep.scan_ports" in src, "扫描必须走本地端点纯函数层"


def test_settings_qml_has_scan_entry_and_apply_function():
    src = _read("app/ui/qml/SettingsPanel.qml")
    assert "扫描本地" in src, "设置页没有扫描入口"
    assert "bridge.scanLocalPorts" in src, "按钮没有接桥面槽"
    assert "bridge.localScanResults" in src, "结果列表没有接桥面属性"
    assert re.search(r"function applyLocalHit\(", src), "缺少「点一条填入表单」的实现"
    assert "keyField.text = \"\"" in src, "本地端点填入时必须清空 Key 字段"
