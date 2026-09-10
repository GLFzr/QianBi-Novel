# -*- coding: utf-8 -*-
"""测试渠道优先级链（用户裁决 2026-09-09）回归

_pick_flash_conn 是 cost_bench 供数的唯一入口，链序：
    ocgo-omen（opencodego）→ bailian-flash（百炼）→ ds-v41-flash（DS 官方 0910 期限）
    → tr-dsv4f（TokenRhythm，余额耗尽殿后）
链上全缺才落老兜底（cap-flash → DS 官方 flash），且选择理由显式返回供日志标注——
渠道 = 缓存域（N2），任何静默换道都会使 hit% 曲线断裂。
"""
import pytest

from scripts.cost_bench import TEST_CONN_PRIORITY, _pick_flash_conn


def _c(cid):
    return {"id": cid, "api_key": "sk-" + cid, "base_url": "https://%s/v1" % cid,
            "model": "deepseek-v4-flash"}


FULL = [_c("cap-flash"), _c("ocgo-omen"), _c("bailian-flash"),
        _c("ds-official-flash"), _c("tr-dsv4f")]


def test_priority_chain_constant_order():
    assert TEST_CONN_PRIORITY == ["ocgo-omen", "bailian-flash", "ds-official-flash", "tr-dsv4f"]


def test_picks_omen_first_when_all_present():
    conn, how = _pick_flash_conn(FULL)
    assert conn["id"] == "ocgo-omen"
    assert "优先级链" in how


def test_falls_to_bailian_when_omen_missing():
    conn, _ = _pick_flash_conn([_c("cap-flash"), _c("bailian-flash"),
                                _c("ds-official-flash"), _c("tr-dsv4f")])
    assert conn["id"] == "bailian-flash"


def test_falls_to_ds_v41_when_omen_and_bailian_missing():
    conn, _ = _pick_flash_conn([_c("cap-flash"), _c("ds-official-flash"), _c("tr-dsv4f")])
    assert conn["id"] == "ds-official-flash"


def test_falls_to_tr_when_chain_above_missing():
    conn, _ = _pick_flash_conn([_c("cap-flash"), _c("tr-dsv4f")])
    assert conn["id"] == "tr-dsv4f"   # 余额耗尽仍是链上成员，只是殿后


def test_legacy_fallback_cap_flash_when_chain_all_missing():
    conn, how = _pick_flash_conn([_c("cap-flash")])
    assert conn["id"] == "cap-flash"
    assert "兜底" in how   # 兜底必须显式可见，不许静默


def test_pin_beats_priority_chain():
    conn, how = _pick_flash_conn(FULL, prefer_id="bailian-flash")
    assert conn["id"] == "bailian-flash"
    assert "钉定" in how


def test_pin_missing_raises_with_available_list():
    with pytest.raises(SystemExit) as ei:
        _pick_flash_conn(FULL, prefer_id="no-such-conn")
    assert "ocgo-omen" in str(ei.value)   # 报错列出可用连接，不静默回退


def test_conn_without_key_is_skipped():
    nokey = dict(_c("ocgo-omen"), api_key="")
    rest = [_c("cap-flash"), _c("bailian-flash"), _c("ds-official-flash")]
    conn, _ = _pick_flash_conn([nokey] + rest)
    assert conn["id"] == "bailian-flash"   # 无 Key 的首选连接跳过，落第二条
