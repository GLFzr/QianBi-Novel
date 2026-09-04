# -*- coding: utf-8 -*-
"""原作世界书导入（同人档）：酒馆世界书 JSON 转条目，纯文本存档等人工拆解

导入是「新建项目那天」的功能，坏了的症状是用户以为导进去了、写作时却一字未注入——
所以这里钉三件事：转换产物必须被 wb.parse 认成条目（触发标记不丢）、绝不覆盖已有产物、
纯文本路线绝不进 prompt（那是世界书.md 才有的资格，拆解是用户自己的活）。
"""
import json
import os

import pytest

from app import project, wb


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "同人测试"
    p.mkdir()
    for d in project.PROJECT_DIRS:
        (p / d).mkdir()
    for d in project.SETTING_SUBDIRS:
        (p / "设定" / d).mkdir()
    return str(p)


def _write(tmp_path, name, obj):
    f = tmp_path / name
    f.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(f)


ST_BOOK = {
    "entries": {
        "0": {"uid": 0, "key": ["灯盟", "当票"], "keysecondary": [],
              "comment": "灯盟", "content": "控制当铺行业的联盟，总部在泗水。\n\n### 内部三堂",
              "constant": False, "disable": False, "order": 100},
        "1": {"uid": 1, "key": [], "comment": "玛娜潮汐",
              "content": "魔力每七天一次涨潮，涨潮时禁用一切术式。",
              "constant": True, "disable": False},
        "2": {"uid": 2, "key": ["废案"], "comment": "废案",
              "content": "这条被禁用了，不该出现。", "disable": True},
    }
}


def test_st_json_converts_into_parseable_entries(proj, tmp_path):
    """转换产物要过 wb.parse：条目数、常驻标记、关键词触发一样不能丢"""
    src = _write(tmp_path, "worldbook.json", ST_BOOK)
    msg = project.import_worldbook(proj, src)
    assert "2 条" in msg, msg   # 3 条里 1 条 disable，只该有 2 条入库
    doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    entries = wb.parse(doc)
    by_name = {e.name: e for e in entries}
    assert "灯盟" in by_name and "玛娜潮汐" in by_name, [e.name for e in entries]
    assert "废案" not in by_name, "disable 的条目不该被导入"
    assert by_name["玛娜潮汐"].meta["constant"] is True
    assert set(by_name["灯盟"].meta["keywords"]) >= {"灯盟", "当票"}
    # 条目块内禁 `#` 标题：转换时必须剥掉，否则追加登记分区会被切断
    assert "###" not in by_name["灯盟"].body


def test_st_json_never_overwrites_existing_worldbook(proj, tmp_path):
    """世界书.md 已有内容（流水线生成过/人工写过）时只报不写——导入不许毁产物"""
    project.write_file(os.path.join(proj, project.WORLDBOOK_PATH), "## 世界书\n\n手写内容\n")
    src = _write(tmp_path, "worldbook.json", ST_BOOK)
    msg = project.import_worldbook(proj, src)
    assert "未覆盖" in msg
    assert "手写内容" in project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))


def test_plain_text_archives_without_entering_prompts(proj, tmp_path):
    """纯文本路线：存进 原作世界书.md，绝不混进 世界书.md——拆解是用户自己的活"""
    src = tmp_path / "原作设定.txt"
    src.write_text("青云宗：正道第一大派，山门在青云山。\n掌门：李长生。", encoding="utf-8")
    msg = project.import_worldbook(proj, str(src))
    assert "原作世界书.md" in msg
    archived = project.read_file(os.path.join(proj, project.WORLDBOOK_SOURCE_PATH))
    assert "青云宗" in archived
    assert not project.read_file(os.path.join(proj, project.WORLDBOOK_PATH)).strip(), \
        "纯文本导入不该动 世界书.md"


def test_plain_text_refuses_overwrite(proj, tmp_path):
    src = tmp_path / "设定.txt"
    src.write_text("新内容", encoding="utf-8")
    project.write_file(os.path.join(proj, project.WORLDBOOK_SOURCE_PATH), "旧存档")
    assert "未覆盖" in project.import_worldbook(proj, str(src))
    assert "旧存档" in project.read_file(os.path.join(proj, project.WORLDBOOK_SOURCE_PATH))


def test_character_card_v2_book_is_recognized(proj, tmp_path):
    """角色卡 v2 壳：data.character_book.entries（列表）也要认得"""
    card = {"data": {"character_book": {"entries": [
        {"keys": ["符纸"], "name": "符纸", "content": "黄纸朱砂，可封一夜邪祟。",
         "enabled": True, "constant": False}]}}}
    src = _write(tmp_path, "card.json", card)
    msg = project.import_worldbook(proj, src)
    assert "条目" in msg
    doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    assert any(e.name == "符纸" for e in wb.parse(doc))


def test_gbk_text_is_read_correctly(proj, tmp_path):
    src = tmp_path / "gbk.txt"
    src.write_bytes("青云宗，正道魁首。".encode("gb18030"))
    project.import_worldbook(proj, str(src))
    assert "青云宗" in project.read_file(os.path.join(proj, project.WORLDBOOK_SOURCE_PATH))


def test_missing_or_empty_file_raises(proj, tmp_path):
    with pytest.raises(FileNotFoundError):
        project.import_worldbook(proj, str(tmp_path / "不存在.json"))
    empty = tmp_path / "empty.txt"
    empty.write_text("  \n", encoding="utf-8")
    with pytest.raises(ValueError):
        project.import_worldbook(proj, str(empty))


def test_new_project_slot_signature_still_callable():
    """bridge.newProject 加了 worldbookFile 参数：QML 老调用（7 参）不能炸"""
    import inspect
    from app.ui import bridge as b
    sig = inspect.signature(b.Bridge.newProject)
    assert list(sig.parameters)[1:] == ["location", "name", "genre", "platform",
                                        "totalWan", "idea", "presetId", "worldbookFile"]
    assert sig.parameters["presetId"].default == ""
    assert sig.parameters["worldbookFile"].default == ""
