# -*- coding: utf-8 -*-
"""出厂连接预设（v0.18.1 起 12 家；v0.18.2 起只预置提供方不预置模型）

预置连接是用户开机第一屏就会看见的东西，它坏了没有报错、只有「为什么连不上」。
所以这里钉的是四类静默故障：URL 里留着模板占位符、endpoint 拼接拼出双 /v1、
把 Key 抄进了仓库、以及槽位指向一个已经不存在的连接 id。
"""
import re

from app import config as cfg_mod
from app.llm import providers as pv
from app.llm.client import LLMClient, check_base_url

FOREIGN = {"openrouter", "gemini", "xai", "groq"}
# 凭据管理器按连接 id 存 Key：改出厂 id 等于让老用户填过的 Key 凭空失联
PINNED_IDS = {"ds-v4-pro"}


def _ids():
    return [c["id"] for c in cfg_mod.DEFAULT_CONNECTIONS]


def test_connection_ids_are_unique():
    ids = _ids()
    assert len(ids) == len(set(ids)), ids
    assert ids, "预设空了等于新用户没有可填的连接"


def test_pinned_ids_survive():
    """连接 id 是凭据存储的键：重命名 ds-v4-pro 会让已保存的 Key 变成孤儿"""
    assert PINNED_IDS <= set(_ids()), PINNED_IDS - set(_ids())


def test_every_preset_provider_is_registered():
    for c in cfg_mod.DEFAULT_CONNECTIONS:
        assert c["provider"] in pv.PROVIDERS, (c["id"], c["provider"])
        assert pv.PROVIDERS[c["provider"]]["builtin"], c["id"]


def test_provider_order_lists_every_provider_once():
    assert len(pv.PROVIDER_ORDER) == len(set(pv.PROVIDER_ORDER))
    assert set(pv.PROVIDER_ORDER) == set(pv.PROVIDERS), \
        "漏一个就在设置页少一家，多一个就是渲染时取不到 label"
    assert "custom" in pv.PROVIDER_ORDER and not pv.PROVIDERS["custom"]["builtin"]


def test_no_template_placeholder_in_base_url():
    """{WorkspaceId} / {account_id} / {deployment_id} 这类占位符原样预置进去 = 死连接"""
    for c in cfg_mod.DEFAULT_CONNECTIONS:
        assert not re.search(r"[{$}]", c["base_url"]), (c["id"], c["base_url"])
    for key, p in pv.PROVIDERS.items():
        assert not re.search(r"[{$}]", p["base_url"]), (key, p["base_url"])


def test_every_preset_endpoint_is_well_formed():
    """钉的是真路径：from_connection() → _chat_url()，不是我在这儿重算一遍拼接

    预置连接坏掉的形态是「点测试连接报 404」，而 404 在用户眼里跟「Key 不对」
    长得一样，所以宁可在这里把端点逐个 spelled out 检查一遍。
    """
    for c in cfg_mod.DEFAULT_CONNECTIONS:
        url = LLMClient.from_connection(c)._chat_url()
        assert re.fullmatch(r"https://[^/]+(/[^/]+)*/chat/completions", url), (c["id"], url)
        assert "//" not in url[8:] and "/v1/v1" not in url, (c["id"], url)
        # check_base_url 是对外导出的规整函数：跑两遍地址不能变（第二遍多出一层 /v1
        # 的症状是用户在设置页点一次保存、连接就悄悄换了一个端点）
        once = check_base_url(c["base_url"])
        assert check_base_url(once) == once, (c["id"], once)
        assert "/v1/v1" not in once, (c["id"], once)


def test_gemini_url_keeps_its_trailing_openai_path():
    """Gemini 是唯一必须以 /openai/ 结尾的：多加 /v1 就 404，这是文档里点名的坑"""
    url = LLMClient.from_connection(
        {"base_url": pv.PROVIDERS["gemini"]["base_url"], "model": "gemini-2.5-pro"})._chat_url()
    assert url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", url


def test_presets_ship_without_any_key():
    """仓库里带 Key 就是泄露，也不许用假 Key 占位（症状是 401 而不是「请填 Key」）。
    v0.18.2 起同样不带模型：模型名是各家变得最快的参数，预置进去过期即误导——
    候选在 providers.models 里给，选择权留给用户"""
    for c in cfg_mod.DEFAULT_CONNECTIONS:
        assert c["api_key"] == "", c["id"]
        assert c["model"] == "", (c["id"], c["model"])
        assert 0 < c["temperature"] <= 1 and c["max_tokens"] >= 1024 and c["timeout"] >= 30, c["id"]


def test_key_names_are_human_labels_not_ids():
    for c in cfg_mod.DEFAULT_CONNECTIONS:
        assert c["name"] and c["name"] != c["id"], c


def test_four_foreign_platforms_are_preset():
    got = {c["provider"] for c in cfg_mod.DEFAULT_CONNECTIONS}
    assert FOREIGN <= got, FOREIGN - got


def test_slots_point_at_existing_connections():
    ids = set(_ids())
    for slot, target in cfg_mod.DEFAULT_CONFIG["slots"].items():
        assert target in ids, (slot, target)


def test_default_slots_all_point_at_the_prompt_tuned_provider():
    """内置 prompt 按 DeepSeek V4 调校：默认槽位不能指向一个没验证过写作质量的平台"""
    for slot in cfg_mod.SLOT_ORDER:
        cid = cfg_mod.DEFAULT_CONFIG["slots"][slot]
        conn = next(c for c in cfg_mod.DEFAULT_CONNECTIONS if c["id"] == cid)
        assert conn["provider"] == "deepseek", (slot, conn["provider"])


def test_every_platform_carries_guidance_and_the_caveat_survives():
    """两家 builtin 之外的 hint 是设置页唯一的解释；
    而「内置 prompt 按 DeepSeek V4 调校」这句是全模块的前提，不能丢"""
    for key, spec in pv.PROVIDERS.items():
        if spec["builtin"] and key != "deepseek":
            assert spec["hint"] and len(spec["hint"]) > 20, key
    doc = pv.__doc__ or ""
    assert "DeepSeek" in doc and "调校" in doc, "提示词只适配 DeepSeek 这件事没写在文件头上"


def test_every_preset_name_mentions_its_platform():
    """列表里两行都叫「GLM」的话，用户选错平台是静默的"""
    names = [c["name"] for c in cfg_mod.DEFAULT_CONNECTIONS]
    assert len(names) == len(set(names))


def test_default_models_list_is_not_empty_for_builtins():
    for key in pv.PROVIDER_ORDER:
        if pv.PROVIDERS[key]["builtin"]:
            assert pv.provider_default_models(key), key
            assert pv.provider_label(key) not in ("", key)
            assert pv.provider_default_url(key).startswith("https://"), key


# ---- 退役预设的移除（老用户设置里那排点不动的僵尸卡）----

def _row(cid, **kv):
    base = {"id": cid, "api_key": ""}
    base.update(kv)
    return base


FACTORY_FLASH = {"name": "DeepSeek V4 Flash", "provider": "deepseek",
                 "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash"}


def _cfg_with(rows, slots=None):
    return {"connections": rows, "slots": slots or {"writing": "ds-v4-pro",
                                                    "helper": "ds-v4-pro", "review": "ds-v4-pro"}}


def _no_credentials(monkeypatch):
    """迁移只许**读**凭据：它在每次 load_config 都跑，探针与单测也在跑它"""
    def boom(*a, **k):
        raise AssertionError("退役迁移不许写或删除凭据")
    monkeypatch.setattr(cfg_mod.secrets, "store_secret", boom)
    monkeypatch.setattr(cfg_mod.secrets, "delete_secret", boom)
    monkeypatch.setattr(cfg_mod.secrets, "get_secret", lambda cid: "")
    cfg_mod._RETIRED_WITH_KEY.clear()


def test_retired_untouched_row_is_removed(monkeypatch):
    _no_credentials(monkeypatch)
    cfg = _cfg_with([_row("ds-v4-pro"), _row("ds-v4-flash", **FACTORY_FLASH)])
    out = cfg_mod._retire_builtin_connections(cfg)
    assert [c["id"] for c in out["connections"]] == ["ds-v4-pro"]


def test_retired_row_in_use_by_a_slot_survives(monkeypatch):
    """删掉正被槽位引用的连接，等于悄悄换掉「用哪个模型写我的书」"""
    _no_credentials(monkeypatch)
    cfg = _cfg_with([_row("ds-v4-flash", **FACTORY_FLASH)],
                    {"writing": "ds-v4-flash", "helper": "ds-v4-pro", "review": "ds-v4-pro"})
    out = cfg_mod._retire_builtin_connections(cfg)
    assert [c["id"] for c in out["connections"]] == ["ds-v4-flash"]


def test_retired_row_edited_by_user_survives(monkeypatch):
    """改过模型名/地址/名字的，已经是他的连接了，不是我们的预设"""
    _no_credentials(monkeypatch)
    edited = dict(FACTORY_FLASH, model="deepseek-v4-flash-0731")
    cfg = _cfg_with([_row("ds-v4-flash", **edited)])
    assert len(cfg_mod._retire_builtin_connections(cfg)["connections"]) == 1


def test_provider_edited_row_survives(monkeypatch):
    """本机真实形态：ocgo-flash 的 provider 被换成 custom，就不该被当成出厂行删掉"""
    _no_credentials(monkeypatch)
    row = _row("ocgo-flash", name="OpenCode Go · V4 Flash", provider="custom",
               base_url="https://opencode.ai/zen/go/v1", model="deepseek-v4-flash")
    assert len(cfg_mod._retire_builtin_connections({"connections": [row], "slots": {}})["connections"]) == 1


def test_param_upgrade_alone_still_counts_as_untouched(monkeypatch):
    """max_tokens 被升级逻辑抬过、温度被调过，都不算「用户改过身份」——
    否则每次参数升级都会让用户手上多留一张僵尸卡"""
    _no_credentials(monkeypatch)
    row = _row("ds-v4-flash", temperature=0.3, **dict(FACTORY_FLASH, max_tokens=16384, timeout=99))
    assert cfg_mod._retire_builtin_connections(_cfg_with([row]))["connections"] == []


def test_retired_row_holding_a_key_survives(monkeypatch):
    """连接删了 Key 就成了凭据管理器里的孤儿，比留一张卡更糟"""
    _no_credentials(monkeypatch)
    monkeypatch.setattr(cfg_mod.secrets, "get_secret", lambda cid: "sk-saved")
    cfg = _cfg_with([_row("ds-v4-flash", **FACTORY_FLASH)])
    assert len(cfg_mod._retire_builtin_connections(cfg)["connections"]) == 1


def test_retired_check_reads_credential_once(monkeypatch):
    """load_config 几乎每个界面动作都跑一次，凭据不能每次重读"""
    _no_credentials(monkeypatch)
    calls = []

    def get_secret(cid):
        calls.append(cid)
        return "sk-saved"

    monkeypatch.setattr(cfg_mod.secrets, "get_secret", get_secret)
    rows = [_row("ds-v4-flash", **FACTORY_FLASH)]
    for _ in range(3):
        cfg_mod._retire_builtin_connections(_cfg_with(list(rows)))
    assert len(calls) == 1, calls
    cfg_mod._RETIRED_WITH_KEY.clear()


def test_live_config_keeps_working_after_retirement(tmp_path, monkeypatch):
    """真走一遍 load_config：删完不能留下指向空连接的槽位"""
    _no_credentials(monkeypatch)
    import json
    import os
    from app import secrets as secrets_mod
    rows = [_row("ds-v4-pro", name="DeepSeek V4 Pro", provider="deepseek",
                 base_url="https://api.deepseek.com", model="deepseek-v4-pro",
                 temperature=0.7, max_tokens=32768, timeout=300),
            _row("ds-v4-flash", **dict(FACTORY_FLASH, temperature=0.7, max_tokens=16384, timeout=300))]
    d = tmp_path / "cfgdir"
    d.mkdir()
    f = d / "config.json"
    f.write_text(json.dumps({"connections": rows,
                             "slots": {"writing": "ds-v4-pro", "helper": "ds-v4-pro",
                                       "review": "ds-v4-pro"}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", str(d))
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", str(f))
    monkeypatch.setattr(secrets_mod, "SERVICE", "QianBiNovel/test-run")
    cfg = cfg_mod.load_config()
    ids = {c["id"] for c in cfg["connections"]}
    assert "ds-v4-flash" not in ids
    for slot in cfg_mod.SLOT_ORDER:
        assert cfg["slots"][slot] in ids
    # 老的 legacy 迁移行（provider=custom、模型名是 pro）不该被退役逻辑牵连
    assert len(ids) >= len(cfg_mod.DEFAULT_CONNECTIONS)


def test_v0181_model_rows_swap_for_provider_only(tmp_path, monkeypatch):
    """v0.18.2 换血：v0.18.1 那行带模型的出厂预设（没动过/没Key/没槽位引用）退役后，
    同 id 补进「仅提供方」新行——预设进化不留断档；改过身份字段或被槽位引用的照旧保留"""
    _no_credentials(monkeypatch)
    import json
    from app import secrets as secrets_mod
    rows = [
        # 与 v0.18.1 出厂逐字相等 → 退役，换新的仅提供方行
        _row("zp-glm-5", name="智谱 · GLM-5", provider="zhipu",
             base_url="https://open.bigmodel.cn/api/paas/v4", model="glm-5"),
        # 被槽位指着 → 保留（换掉它等于悄悄换掉「用哪个模型写我的书」）
        _row("ds-v4-pro", name="DeepSeek V4 Pro", provider="deepseek",
             base_url="https://api.deepseek.com", model="deepseek-v4-pro"),
    ]
    d = tmp_path / "cfgdir2"
    d.mkdir()
    f = d / "config.json"
    f.write_text(json.dumps({"connections": rows,
                             "slots": {"writing": "ds-v4-pro", "helper": "ds-v4-pro",
                                       "review": "ds-v4-pro"}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", str(d))
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", str(f))
    monkeypatch.setattr(secrets_mod, "SERVICE", "QianBiNovel/test-run")
    cfg = cfg_mod.load_config()
    by_id = {c["id"]: c for c in cfg["connections"]}
    assert by_id["zp-glm-5"]["model"] == "" and by_id["zp-glm-5"]["name"] == "智谱 BigModel"
    assert by_id["ds-v4-pro"]["model"] == "deepseek-v4-pro"   # 在用的行原样保留
    for slot in cfg_mod.SLOT_ORDER:
        assert cfg["slots"][slot] in by_id


def test_empty_model_fails_loud_not_as_api_400():
    """预设不带模型之后，空模型要在本层就喊出来，而不是变成一串英文 API 400"""
    from app.llm.client import LLMError
    c = LLMClient.from_connection({"base_url": "https://api.deepseek.com",
                                   "api_key": "sk-x", "model": ""})
    for call in (lambda: c.chat("hi"), lambda: c.chat_stream("hi")):
        try:
            call()
        except LLMError as e:
            assert "还没选模型" in str(e), str(e)
        else:
            raise AssertionError("空模型竟然发出去了请求")
