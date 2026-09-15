# -*- coding: utf-8 -*-
"""N-03 护栏：批注库损坏必须隔离留证 + 上界面告警，不得静默当空后被覆写。

旧实现 except: pass 返回空库 —— 下一次 _write_store 会把用户批注整份清掉。
复用 volume_session._keep_aside 的留证语义（追加式 .corrupt，不覆盖上次现场）。
"""
import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.ui import bridge as bridge_mod


class _Toast:
    def __init__(self):
        self.sent = []

    def emit(self, level, text):
        self.sent.append((level, text))


def _fake_bridge():
    return types.SimpleNamespace(toast=_Toast())


def _store_path(proj, num):
    return os.path.join(proj, "正文", ".annotations", f"第{num}章.json")


def _make_proj(tmp_path, num=1, raw=None):
    proj = str(tmp_path / "书")
    os.makedirs(os.path.join(proj, "正文", ".annotations"), exist_ok=True)
    if raw is not None:
        with open(_store_path(proj, num), "wb") as f:
            f.write(raw)
    return proj


def test_corrupt_json_is_quarantined_and_warned(tmp_path):
    proj = _make_proj(tmp_path, raw=b'{"annotations": [ broken')
    fb = _fake_bridge()
    data = bridge_mod.Bridge._read_store(fb, proj, 1)
    assert data == {"annotations": [], "bookmarks": [], "position": 0.0}
    corrupt = _store_path(proj, 1) + ".corrupt"
    assert os.path.exists(corrupt), "坏现场必须留证为 .corrupt"
    with open(corrupt, "rb") as f:
        assert b"broken" in f.read()
    assert fb.toast.sent, "必须上界面告警"
    level, text = fb.toast.sent[0]
    assert level == "warn" and ".corrupt" in text


def test_quarantine_is_append_only(tmp_path):
    """两次损坏不互相覆盖证据（_keep_aside 语义）。"""
    proj = _make_proj(tmp_path, raw=b'bad-1')
    fb = _fake_bridge()
    bridge_mod.Bridge._read_store(fb, proj, 1)
    # 模拟用户重开仍坏 → 证据应累加而不是清掉上一次
    with open(_store_path(proj, 1), "wb") as f:
        f.write(b'bad-2')
    bridge_mod.Bridge._read_store(fb, proj, 1)
    with open(_store_path(proj, 1) + ".corrupt", "rb") as f:
        blob = f.read()
    assert b"bad-1" in blob and b"bad-2" in blob


def test_missing_file_is_silent_empty(tmp_path):
    """首次打开（文件不存在）不算损坏：不告警、不留证。"""
    proj = _make_proj(tmp_path)
    fb = _fake_bridge()
    data = bridge_mod.Bridge._read_store(fb, proj, 7)
    assert data["annotations"] == []
    assert fb.toast.sent == []
    assert not os.path.exists(_store_path(proj, 7) + ".corrupt")


def test_good_store_untouched(tmp_path):
    proj = _make_proj(tmp_path, raw=json.dumps(
        {"annotations": [{"t": "划线"}], "bookmarks": [], "position": 0.5},
        ensure_ascii=False).encode("utf-8"))
    fb = _fake_bridge()
    data = bridge_mod.Bridge._read_store(fb, proj, 1)
    assert data["annotations"] == [{"t": "划线"}]
    assert data["position"] == 0.5
    assert fb.toast.sent == []
    assert not os.path.exists(_store_path(proj, 1) + ".corrupt")


def test_wrong_shape_top_level_quarantined(tmp_path):
    """合法 JSON 但顶层不是对象：同样会覆写丢数据，必须走隔离。"""
    proj = _make_proj(tmp_path, raw=b'[1, 2, 3]')
    fb = _fake_bridge()
    data = bridge_mod.Bridge._read_store(fb, proj, 1)
    assert data["annotations"] == []
    assert os.path.exists(_store_path(proj, 1) + ".corrupt")
    assert fb.toast.sent
