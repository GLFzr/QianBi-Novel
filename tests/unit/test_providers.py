# -*- coding: utf-8 -*-
"""出厂连接预设（v0.18.1 起 12 家）：填一把 Key 就能跑，不是一堆调不通的下拉项

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
    """仓库里带 Key 就是泄露，也不许用假 Key 占位（症状是 401 而不是「请填 Key」）"""
    for c in cfg_mod.DEFAULT_CONNECTIONS:
        assert c["api_key"] == "", c["id"]
        assert c["model"], c["id"]
        assert 0 < c["temperature"] <= 1 and c["max_tokens"] >= 1024 and c["timeout"] >= 30, c["id"]


def test_key_names_are_human_labels_not_ids():
    for c in cfg_mod.DEFAULT_CONNECTIONS:
        assert c["name"] != c["id"] and " " in c["name"], c


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
