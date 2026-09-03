# -*- coding: utf-8 -*-
"""状态栏/统计 token 计量显示层（W1）与大数格式化回归锚（W2）

W1 根因：_get_tokens/_get_cost_text 曾读流水线 router 内存计数器，
共写档 self.orch=None 时恒 0；现改读 usage.summary() 的今日聚合。
W2 根因：QLocale zh_CN 对 double 默认 'g' 精度 6，≥1,000,000 显示 4.24805e+06；
QML 侧已统一 Number(n).toLocaleString(Qt.locale(), 'f', 0)，此处锁定 Python 侧口径。
"""
import importlib


def _fresh_usage(tmp_path, monkeypatch):
    import app.usage as um
    importlib.reload(um)
    monkeypatch.setattr(um, "FILE", str(tmp_path / "usage.jsonl"))
    return um


def test_bridge_token_getters_read_usage_today(tmp_path, monkeypatch):
    um = _fresh_usage(tmp_path, monkeypatch)
    um.record({}, "deepseek-v4-flash", "writing", 2_000_000, 248_050, 1.0)
    um.record({}, "deepseek-v4-pro", "review", 100, 50, 0.5)
    from app.ui.bridge import Bridge
    # getter 不依赖实例状态，直接无绑定调用（单测无需 QApplication）
    assert Bridge._get_tokens(None) == 2_248_200
    cost = Bridge._get_cost_text(None)
    assert cost.startswith("¥") and float(cost[1:]) > 0


def test_bridge_token_getters_zero_without_records(tmp_path, monkeypatch):
    _fresh_usage(tmp_path, monkeypatch)
    from app.ui.bridge import Bridge
    assert Bridge._get_tokens(None) == 0
    assert Bridge._get_cost_text(None) == "¥0.00"


def test_qlocale_fixed_point_no_scientific():
    """≥1,000,000 必须 'f',0 定点：否则默认 'g' 精度 6 显示 4.24805e+06"""
    from PySide6.QtCore import QLocale
    loc = QLocale("zh_CN")
    assert loc.toString(4248050.0, "f", 0) == "4,248,050"
    assert loc.toString(1000000.0, "f", 0) == "1,000,000"
    assert loc.toString(68589) == "68,589"
