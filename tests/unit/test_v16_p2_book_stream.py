# -*- coding: utf-8 -*-
"""v16 P2（A2 书级单一追加流）单测

核心断言（A2 结构保证）：
- 流文件只增不改：章节块/卷纲块追加后旧字节是严格前缀；违例被守卫拒绝并落事件
- **system(卷N+1) = system(卷N) + 追加字节**——head_rebuild_system_text 在卷界
  （新卷纲追加+新章滚动后）的输出 startswith 卷内历史输出 ⇒ 前缀缓存零塌陷
- 世界书永不入流（5.4 定稿）；flag 缺省关（off 走 v15 卷首快照路径不碰流文件）
- 三段真静态逐字入流（字节=源文件拼接）
"""
import json
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_test_v16p2_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest  # noqa: E402

from app.core import volume_session as vs  # noqa: E402


def _make_proj(tmp):
    proj = str(tmp)
    os.makedirs(os.path.join(proj, "设定"), exist_ok=True)
    os.makedirs(os.path.join(proj, "大纲"), exist_ok=True)
    os.makedirs(os.path.join(proj, "追踪"), exist_ok=True)
    os.makedirs(os.path.join(proj, "正文"), exist_ok=True)
    with open(os.path.join(proj, "设定", "题材定位.md"), "w", encoding="utf-8") as f:
        f.write("都市规则流悬疑。金手指：种子书。\n授权自创：陈默")
    with open(os.path.join(proj, "设定", "世界书.md"), "w", encoding="utf-8") as f:
        f.write("世界书条目：听痕术来源考")
    with open(os.path.join(proj, "大纲", "大纲.md"), "w", encoding="utf-8") as f:
        f.write("卷一：种子书现世（1-10章）")
    with open(os.path.join(proj, "大纲", "细纲_第001章.md"), "w", encoding="utf-8") as f:
        f.write("第1章细纲：开局钩子")
    return proj


def _write_chapter(proj, num, text, name="章节"):
    path = os.path.join(proj, "正文", "第%03d章_%s.md" % (num, name))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# 第%d章 %s\n\n%s\n" % (num, name, text))
    return path


# ---------- 装配：三段真静态逐字入流，世界书不入 ----------

def test_book_stream_assembles_three_true_static_segments(tmp_path):
    proj = _make_proj(tmp_path)
    stream = vs.build_book_stream(proj, 1)
    assert "## 设定底册（冻结）" in stream
    assert "都市规则流悬疑" in stream                      # 底册逐字
    assert "### 卷纲 · 卷1（开卷冻结）" in stream
    assert "卷一：种子书现世" in stream                     # 卷纲逐字
    assert "### 细纲 · 第1章" in stream and "开局钩子" in stream
    assert "世界书条目" not in stream                       # 5.4：世界书不入流
    # 落盘字节 = 返回值（冻结纪律）
    with open(vs.book_stream_path(proj), encoding="utf-8") as f:
        assert f.read() == stream


def test_book_stream_frozen_on_rebuild(tmp_path):
    proj = _make_proj(tmp_path)
    s1 = vs.build_book_stream(proj, 1)
    with open(os.path.join(proj, "设定", "题材定位.md"), "a", encoding="utf-8") as f:
        f.write("卷内反哺的新增设定行")          # 底册文件变了也不许回流
    assert vs.build_book_stream(proj, 1) == s1   # 字节冻结


# ---------- 追加：前缀性质 + 守卫 ----------

def test_roll_chapter_appends_strict_prefix(tmp_path):
    proj = _make_proj(tmp_path)
    vs.build_book_stream(proj, 1)
    path = vs.book_stream_path(proj)
    with open(path, encoding="utf-8") as f:
        old = f.read()
    assert vs.roll_book_stream_chapter(proj, 1, "开端", "陈默捡到本子。", "他捡到了本子")
    with open(path, encoding="utf-8") as f:
        new = f.read()
    assert new.startswith(old) and len(new) > len(old)
    assert "### 第1章 开端" in new and "> 摘要：他捡到了本子" in new
    # 第二滚继续追加
    assert vs.roll_book_stream_chapter(proj, 2, "回读", "本子又显字了。", "显字")
    with open(path, encoding="utf-8") as f:
        newer = f.read()
    assert newer.startswith(new)


def test_roll_records_session_events(tmp_path):
    proj = _make_proj(tmp_path)
    vs.build_book_stream(proj, 1)
    assert vs.roll_book_stream_chapter(proj, 1, "开端", "正文", "摘要") is True
    events = os.path.join(proj, "追踪", "session_events.jsonl")
    with open(events, encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    rolled = [r for r in rows if r.get("event") == "corpus_rolled"]
    assert any(r.get("appended", 0) > 0 and r.get("ch") == 1 for r in rolled)


def test_volume_outline_lazy_append_at_boundary(tmp_path):
    proj = _make_proj(tmp_path)
    vs.build_book_stream(proj, 1)
    with open(vs.book_stream_path(proj), encoding="utf-8") as f:
        v1 = f.read()
    # 卷界：新卷纲落盘后 ensure 卷2
    with open(os.path.join(proj, "大纲", "大纲.md"), "w", encoding="utf-8") as f:
        f.write("卷二：规则反噬（11-20章）")
    assert vs._ensure_book_stream_volume_outline(proj, 2) is True
    with open(vs.book_stream_path(proj), encoding="utf-8") as f:
        v2 = f.read()
    assert v2.startswith(v1)                          # 前缀性质
    assert "### 卷纲 · 卷2（开卷冻结）" in v2 and "规则反噬" in v2
    # 幂等：同卷重复 ensure 不再追加
    assert vs._ensure_book_stream_volume_outline(proj, 2) is False
    with open(vs.book_stream_path(proj), encoding="utf-8") as f:
        assert f.read() == v2


# ---------- 结构保证：system(卷N+1) startswith system(卷N) ----------

def test_system_text_prefix_continuous_across_volume_boundary(tmp_path):
    """A2 的存在理由：卷界（卷纲追加+章滚动）后 system 只在尾部增长。
    旧架构此处会全灭重贴（卷首快照重冻结+语料换文件）；新架构 startswith。"""
    proj = _make_proj(tmp_path)
    kw = dict(review_in_system=True, instruction_in_head=True)
    head_v1 = vs.head_rebuild_system_text(proj, 1, corpus_head=False,
                                          book_stream=True, review_tail="审校静态尾段",
                                          **kw)
    assert vs.roll_book_stream_chapter(proj, 1, "开端", "第一章正文。", "摘要一")
    head_v1b = vs.head_rebuild_system_text(proj, 1, corpus_head=False,
                                           book_stream=True, review_tail="审校静态尾段",
                                           **kw)
    assert head_v1b.startswith(head_v1)               # 章界：只增不改
    # 卷界：卷2 纲追加 + 卷1 尾章滚动
    with open(os.path.join(proj, "大纲", "大纲.md"), "w", encoding="utf-8") as f:
        f.write("卷二：规则反噬（11-20章）")
    assert vs.roll_book_stream_chapter(proj, 2, "回读", "第二章正文。", "摘要二")
    assert vs._ensure_book_stream_volume_outline(proj, 2) is True
    head_v2 = vs.head_rebuild_system_text(proj, 2, corpus_head=False,
                                          book_stream=True, review_tail="审校静态尾段",
                                          **kw)
    assert head_v2.startswith(head_v1b)               # 卷界：零塌陷的结构保证
    assert "卷纲 · 卷2" in head_v2


def test_book_stream_head_excludes_worldbook_and_legacy_snapshot(tmp_path):
    proj = _make_proj(tmp_path)
    head = vs.head_rebuild_system_text(proj, 1, book_stream=True)
    assert "世界书条目" not in head                    # 世界书不入书级头
    assert "设定底册（冻结）" in head                  # 三段真静态在 system
    assert vs.head_snapshot_path(proj, 1) != "" and \
        not os.path.exists(vs.head_snapshot_path(proj, 1))   # 不再产卷首快照


def test_book_stream_off_keeps_legacy_paths(tmp_path):
    """flag 缺省关：off 时不创建流文件、head 走 v15 卷首快照路径（含世界书）。"""
    proj = _make_proj(tmp_path)
    head = vs.head_rebuild_system_text(proj, 1, corpus_head=True)
    assert not os.path.exists(vs.book_stream_path(proj))
    assert "世界书条目" in head                        # legacy 模式世界书仍在卷首快照
    assert "## 世界书（卷首冻结" in head


# ---------- 摘要链与 meta ----------

def test_meta_tracks_appended_volumes(tmp_path):
    proj = _make_proj(tmp_path)
    vs.build_book_stream(proj, 1)
    with open(os.path.join(proj, "大纲", "大纲.md"), "w", encoding="utf-8") as f:
        f.write("卷二")
    vs._ensure_book_stream_volume_outline(proj, 2)
    meta = vs._load_book_stream_meta(proj)
    assert meta["volumes"] == [1, 2]
