# -*- coding: utf-8 -*-
"""P0a 单一 payload 构造 + P1 预设参数档（全书采样基线 + 阶段档 → 请求体）

覆盖四件事：
1. 请求体只在 `_build_payload` 一处组装，phase 是选档/诊断标识、不进 HTTP 请求体；
2. 采样参数优先级：显式实参 ＞ 阶段参数档 ＞ 全书采样基线（payload_defaults）＞ 客户端实例；
   且 review 相位的 temperature 不受两层预设影响（审校 0.2 多票口径是跨书验收基线）；
3. thinking 空内容兜底改为「一次调用内退化重发」——不再递归重调、不污染实例字段；
   网关点名不支持某参数时按能力备忘录剥参数重发（进程内，不落 config.py）；
4. 预设脏值在读取层丢弃、路由换预设时整表重绑、_stream 按 phase 选槽。
"""
import json
import types

import pytest

import app.llm.client as lc
import app.presets as genre_presets


class _Resp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


class _ErrResp:
    """非 200 响应（chat 走 .text；chat_stream 走 .read().text）"""

    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text

    def read(self):
        return self

    def json(self):
        return {}


def _content_resp(text, finish="stop"):
    # 不带 usage：payload/退化测试不该写真实 usage.jsonl（用量埋点另有专测）
    return _Resp({"choices": [{"message": {"content": text}, "finish_reason": finish}]})


class _FakeHttp:
    """记录每次请求体；按脚本依次返回响应（列表耗尽后重复最后一个）"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, timeout=None):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _next(self, kwargs):
        self.calls.append(kwargs)
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[idx]

    def post(self, url, json=None, headers=None):
        return self._next(json)

    def stream(self, method, url, json=None, headers=None):
        self.calls.append(json)
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        return _StreamCtx(self.responses[idx])


class _StreamCtx:
    def __init__(self, resp):
        self.resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def status_code(self):
        return self.resp.status_code

    def read(self):
        # 真实 httpx：流式响应必须 read() 后才有 .text（否则 ResponseNotRead）
        return types.SimpleNamespace(text=getattr(self.resp, "text", ""))

    def iter_lines(self):
        content = (self.resp.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
        out = ['data: ' + json.dumps({"choices": [{"delta": {"content": content}}]})]
        if self.resp.json().get("choices"):
            out.append('data: ' + json.dumps(
                {"choices": [{"delta": {}, "finish_reason":
                              self.resp.json()["choices"][0].get("finish_reason")}]}))
        out.append("data: [DONE]")
        return iter(out)


@pytest.fixture
def http(monkeypatch):
    def _install(responses):
        fake = _FakeHttp(responses)
        monkeypatch.setattr(lc.httpx, "Client", fake)
        return fake
    return _install


# ---------- 1. 唯一构造点 ----------

def test_payload_built_in_one_place(http):
    fake = _content_resp("正文")
    recorder = http([fake])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", temperature=0.7,
                     max_tokens=4096, thinking="enabled", reasoning_effort="high")
    assert c.chat("p", temperature=0.3, phase="prose") == "正文"
    body = recorder.calls[0]
    assert body["temperature"] == 0.3 and body["max_tokens"] == 4096
    assert body["thinking"] == {"type": "enabled"} and body["reasoning_effort"] == "high"
    assert body["stream"] is False
    assert "phase" not in body          # 阶段标识只做选档/诊断，不进请求体
    assert c.last_phase == "prose"


def test_stream_payload_carries_stream_options(http):
    recorder = http([_content_resp("hi")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m")
    assert c.chat_stream("p", phase="review") == "hi"
    body = recorder.calls[0]
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert "thinking" not in body and "phase" not in body
    assert c.last_phase == "review"


# ---------- 2. 优先级 ----------

def test_payload_defaults_beat_instance_but_lose_to_explicit(http):
    recorder = http([_content_resp("ok")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", temperature=0.7, max_tokens=4096,
                     payload_defaults={"temperature": 0.4, "max_tokens": 2048,
                                       "thinking": "disabled"})
    c.chat("p")
    assert recorder.calls[0]["temperature"] == 0.4           # defaults 压过实例
    assert recorder.calls[0]["max_tokens"] == 2048
    assert recorder.calls[0]["thinking"] == {"type": "disabled"}
    c.chat("p", temperature=0.9)
    assert recorder.calls[1]["temperature"] == 0.9           # 显式实参压过 defaults


def test_zero_temperature_is_not_treated_as_missing(http):
    """0.0 是合法采样值，不能被 `or` 判成未提供"""
    recorder = http([_content_resp("ok")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", temperature=0.7,
                     payload_defaults={"temperature": 0.5})
    c.chat("p", temperature=0.0)
    assert recorder.calls[0]["temperature"] == 0.0


# ---------- 3. 退化重发（无递归） ----------

def test_empty_content_degrades_in_one_call(http):
    recorder = http([_content_resp("", finish="stop"), _content_resp("改后正文")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", temperature=0.7,
                     thinking="enabled", reasoning_effort="high", max_retries=2)
    assert c.chat("p") == "改后正文"
    assert c.thinking == "enabled" and c.reasoning_effort == "high"   # 实例字段未被改写
    assert c.last_degraded is True
    assert len(recorder.calls) == 2
    assert "thinking" in recorder.calls[0] and "thinking" not in recorder.calls[1]


def test_empty_stream_degrades_in_one_call(http):
    recorder = http([_content_resp(""), _content_resp("流式正文")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m",
                     thinking="enabled", max_retries=2)
    chunks = []
    assert c.chat_stream("p", on_chunk=chunks.append) == "流式正文"
    assert c.thinking == "enabled"
    assert c.last_degraded is True
    assert len(recorder.calls) == 2
    assert "thinking" not in recorder.calls[1]


def test_degrade_triggers_at_most_once(http):
    """退化后仍空 → 走重试预算，不再重复关闭 thinking"""
    recorder = http([_content_resp(""), _content_resp(""), _content_resp("")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m",
                     thinking="enabled", max_retries=2, backoff_base=0)
    with pytest.raises(lc.LLMError):
        c.chat("p")
    assert len(recorder.calls) == 3
    assert all("thinking" not in body for body in recorder.calls[1:])


def test_last_degraded_resets_per_call(http):
    http([_content_resp(""), _content_resp("x"), _content_resp("y")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", thinking="enabled", max_retries=2)
    assert c.chat("p") == "x" and c.last_degraded is True
    assert c.chat("q") == "y" and c.last_degraded is False


# ---------- 4. 阶段标识透传 ----------

def test_stages_stream_passes_phase():
    import app.core.stages as stages

    seen = {}

    class _Client:
        def chat_stream(self, prompt, system="", temperature=None,
                        on_chunk=None, on_reasoning=None, phase="", **kw):
            seen["phase"] = phase
            return "正文"

    class _Router:
        def client(self, slot):
            return _Client()

    class _Ctx:
        router = _Router()

        def stream_stage(self, label):
            pass

        def stream_chunk(self, c):
            pass

        def stream_reasoning(self, r):
            pass

    out = stages._stream(_Ctx(), "writing", "p", label="草稿",
                         phase=stages.PHASE_PROSE)
    assert out == "正文" and seen["phase"] == "prose"
    stages._stream(_Ctx(), "writing", "p")
    assert seen["phase"] == ""


def test_phase_names_are_stable_across_ends():
    """phase 字面量是预设 stage_params 的键与快照字段，改名即破坏兼容"""
    import app.core.stages as stages
    expected = {
        "PHASE_CORE_SETTING": "core_setting", "PHASE_VOLUME_OUTLINE": "volume_outline",
        "PHASE_WORLDBOOK": "worldbook", "PHASE_OUTLINE": "outline", "PHASE_PROSE": "prose",
        "PHASE_ENRICH": "enrich", "PHASE_TRIM": "trim", "PHASE_DESLOP": "deslop",
        "PHASE_REVIEW": "review", "PHASE_ROOT_CAUSE": "root_cause",
        "PHASE_REVIEW_FIX": "review_fix",
    }
    for name, val in expected.items():
        assert getattr(stages, name) == val


# ---------- 5. P1 阶段参数档：四级优先级 ----------

@pytest.fixture(autouse=True)
def _clean_capability_memo(monkeypatch):
    """能力备忘录是进程内全局：逐例清空，否则「不支持」结论会跨用例串味"""
    monkeypatch.setattr(lc, "_UNSUPPORTED", {})


def test_stage_params_beat_defaults_but_lose_to_explicit(http):
    recorder = http([_content_resp("ok"), _content_resp("ok"), _content_resp("ok")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", temperature=0.7, max_tokens=4096,
                     payload_defaults={"temperature": 0.4, "max_tokens": 2048},
                     stage_params={"prose": {"temperature": 0.95, "top_p": 0.9,
                                             "frequency_penalty": 0.3, "max_tokens": 8192}})
    c.chat("p", phase="prose")
    body = recorder.calls[0]
    assert body["temperature"] == 0.95 and body["max_tokens"] == 8192   # 阶段档压过 defaults
    assert body["top_p"] == 0.9 and body["frequency_penalty"] == 0.3
    c.chat("p", phase="outline")
    assert recorder.calls[1]["temperature"] == 0.4                       # 别的相位不吃 prose 档
    assert recorder.calls[1]["max_tokens"] == 2048
    assert "top_p" not in recorder.calls[1]
    c.chat("p", temperature=0.1, phase="prose")
    assert recorder.calls[2]["temperature"] == 0.1                       # 显式实参最高


def test_review_temperature_is_locked_against_preset(http):
    """审校 0.2 多票口径是跨书验收基线：预设两层来源都改不动温度，其余参数照吃"""
    recorder = http([_content_resp("ok"), _content_resp("ok")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", temperature=0.7,
                     payload_defaults={"temperature": 1.1, "top_p": 0.95},
                     stage_params={"review": {"temperature": 1.4, "top_p": 0.7, "slot": "review"}})
    c.chat("p", temperature=0.2, phase="review")
    assert recorder.calls[0]["temperature"] == 0.2
    c.chat("p", phase="review")
    assert recorder.calls[1]["temperature"] == 0.7        # 回落到连接档案：阶段档与全书基线都被锁掉
    assert recorder.calls[1]["top_p"] == 0.7              # 同档其他参数不受锁影响
    assert "slot" not in recorder.calls[1]                # 选槽字段绝不进 HTTP body


def test_no_stage_params_keeps_payload_byte_identical(http):
    """没配参数档 → 请求体与 P1 改造前逐字一致（不得凭空多出 "top_p": null）"""
    recorder = http([_content_resp("ok"), _content_resp("ok")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", temperature=0.7, max_tokens=4096)
    c.chat("p", phase="prose")
    assert set(recorder.calls[0]) == {"model", "messages", "temperature", "max_tokens", "stream"}
    c.chat_stream("p", phase="prose")
    assert set(recorder.calls[1]) == {"model", "messages", "temperature", "max_tokens",
                                      "stream", "stream_options"}


# ---------- 6. 模型能力备忘录（进程内，不落 config.py） ----------

def test_unsupported_param_is_stripped_and_memoized(http):
    recorder = http([_ErrResp(400, "Unsupported parameter: 'thinking' is not supported"),
                     _content_resp("ok"), _content_resp("ok")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", thinking="enabled",
                     reasoning_effort="high", max_retries=2, backoff_base=0)
    assert c.chat("p") == "ok"
    assert c.last_degraded is True
    assert "thinking" in recorder.calls[0] and "thinking" not in recorder.calls[1]
    assert c.chat("p") == "ok"                            # 第二次调用不再白吃一次 4xx
    assert "thinking" not in recorder.calls[2]
    assert c.thinking == "enabled"                        # 实例字段（连接档案）不被改写


def test_unrelated_4xx_still_raises_immediately(http):
    """降级只认「网关点名的参数」：其他 4xx 照旧立即抛，不烧重试预算"""
    recorder = http([_ErrResp(401, "Invalid API key")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", max_retries=2, backoff_base=0)
    with pytest.raises(lc.LLMError) as e:
        c.chat("p")
    assert "401" in str(e.value)
    assert len(recorder.calls) == 1


def test_stream_4xx_reads_real_body(http):
    """流式非 200 要先 read() 才拿得到 body：否则 ResponseNotRead 会把 4xx 洗成「流式读取中断」"""
    recorder = http([_ErrResp(400, "Unsupported parameter: 'top_p'"), _content_resp("正文")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", payload_defaults={"top_p": 0.8},
                     max_retries=2, backoff_base=0)
    assert c.chat_stream("p", phase="prose") == "正文"
    assert "top_p" in recorder.calls[0] and "top_p" not in recorder.calls[1]


# ---------- 7. 预设侧读取与接线 ----------

def test_stage_params_validation(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(genre_presets, "user_dir", lambda: str(tmp_path))
    pid = "probe_p1"
    data = {"id": pid, "name": "P1 探针预设", "version": 2, "stage_params": {
        "prose": {"temperature": 0.95, "top_p": "0.9", "slot": "writing",
                  "max_tokens": 8192.0, "frequency_penalty": 9, "unknown": 1},
        "nonsense_phase": {"temperature": 0.5},
        "review": "not-a-dict",
    }}
    with open(os.path.join(str(tmp_path), pid + ".json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    # 越界(frequency_penalty=9)、未知键、未知相位、非 dict 档位全部丢弃；字符串数值与浮点 max_tokens 归一
    assert genre_presets.stage_params(pid) == {
        "prose": {"temperature": 0.95, "top_p": 0.9, "slot": "writing", "max_tokens": 8192}}
    assert genre_presets.stage_slot(pid, "prose") == "writing"
    assert genre_presets.stage_slot(pid, "review") == ""
    assert genre_presets.stage_params("") == {}
    assert genre_presets.stage_params("没有这个预设") == {}


def test_sampling_validation(tmp_path, monkeypatch):
    """全书采样基线：白名单 + 大小写归一 + 脏值即丢；slot 不属于基线层（选槽只按相位）"""
    import os
    monkeypatch.setattr(genre_presets, "user_dir", lambda: str(tmp_path))
    pid = "probe_p1c"
    with open(os.path.join(str(tmp_path), pid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"id": pid, "version": 2, "sampling": {
            "temperature": 0.8, "top_p": "0.9", "max_tokens": 6144.0,
            "thinking": "Enabled", "reasoning_effort": "ultra",
            "slot": "writing", "presence_penalty": 3.5, "unknown": 1}}, f, ensure_ascii=False)
    assert genre_presets.sampling(pid) == {
        "temperature": 0.8, "top_p": 0.9, "max_tokens": 6144, "thinking": "enabled"}
    assert genre_presets.sampling("") == {}
    assert genre_presets.sampling("没有这个预设") == {}
    # 越界（惩罚 3.5 超出 [-2, 2]）与未知键都是丢弃而非钳位：不把「写错了」伪装成「故意设边界」
    assert "presence_penalty" not in genre_presets.sampling(pid)


def test_preset_param_layers_are_read_together(tmp_path, monkeypatch):
    """预设 → 路由的两层覆盖必须一次读齐：只接通一层（采样基线生效、阶段档失效）最难查"""
    import os
    import app.core.stages as stages
    monkeypatch.setattr(genre_presets, "user_dir", lambda: str(tmp_path))
    with open(os.path.join(str(tmp_path), "probe_p1d.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "probe_p1d", "version": 2,
                   "stage_params": {"prose": {"temperature": 0.9}},
                   "sampling": {"top_p": 0.8}}, f, ensure_ascii=False)
    monkeypatch.setattr(stages, "_preset_id", lambda proj: "probe_p1d" if proj else "")
    assert stages.preset_param_layers("书") == {
        "stage_params": {"prose": {"temperature": 0.9}}, "payload_defaults": {"top_p": 0.8}}
    assert stages.preset_param_layers("") == {"stage_params": {}, "payload_defaults": {}}


def test_stage_param_phases_match_stages_literals():
    """预设相位表必须与 stages.PHASE_* 字面量一一对应，否则参数档静默失效"""
    import app.core.stages as stages
    preset_keys = {k for k, _ in genre_presets.STAGE_PARAM_PHASES}
    stage_keys = {v for k, v in vars(stages).items() if k.startswith("PHASE_")}
    assert preset_keys == stage_keys


def test_client_param_keys_match_preset_table():
    """客户端能力备忘录认得的参数名必须与预设字段表同名：否则网关点名后剥不掉，白烧重试"""
    assert set(lc.STAGE_PARAM_KEYS) == {k for k, _l, _lo, _hi, _i in genre_presets.STAGE_PARAM_FIELDS}


def test_router_injects_and_rebinds_preset_layers():
    from app.llm.router import ModelRouter
    cfg = {"connections": [{"id": "c1", "name": "t", "base_url": "http://x/v1",
                            "api_key": "k", "model": "m", "temperature": 0.7}],
           "llm": {}}
    r = ModelRouter(cfg, stage_params={"prose": {"temperature": 0.9}},
                    payload_defaults={"top_p": 0.9})
    client = r.client("writing")
    assert client.stage_params == {"prose": {"temperature": 0.9}}
    assert client.payload_defaults == {"top_p": 0.9}
    # 换预设：已缓存客户端两层跟着重绑，且不因为换档就重建客户端
    r.set_preset_params(stage_params={"prose": {"temperature": 0.4}},
                        payload_defaults={"top_p": 0.8})
    assert (client.stage_params, client.payload_defaults) == (
        {"prose": {"temperature": 0.4}}, {"top_p": 0.8})
    assert r.client("writing") is client
    r.set_preset_params()                                     # 换到无参数档的预设：两层同时清空
    assert client.stage_params == {} and client.payload_defaults == {}


def test_stream_slot_override_from_preset(monkeypatch):
    """预设 stage_params[phase].slot 换的是「用哪条连接」，不是请求体字段"""
    import app.core.stages as stages
    seen = {}

    class _Client:
        def chat_stream(self, prompt, system="", temperature=None,
                        on_chunk=None, on_reasoning=None, phase="", **kw):
            return "正文"

    class _Router:
        def client(self, slot):
            seen["slot"] = slot
            return _Client()

    class _Ctx:
        router = _Router()
        proj = ""

        def stream_stage(self, label):
            pass

        def stream_chunk(self, c):
            pass

        def stream_reasoning(self, r):
            pass

    monkeypatch.setattr(stages, "_preset_id", lambda proj: "xiuxian")
    monkeypatch.setattr(genre_presets, "stage_slot",
                        lambda pid, phase: "review" if (pid, phase) == ("xiuxian", "prose") else "")
    stages._stream(_Ctx(), "writing", "p", phase=stages.PHASE_PROSE)
    assert seen["slot"] == "review"
    stages._stream(_Ctx(), "writing", "p", phase=stages.PHASE_TRIM)
    assert seen["slot"] == "writing"          # 未配选槽的相位沿用调用方默认槽


def test_preset_details_expose_stage_params(tmp_path, monkeypatch):
    """预设面板要能显示参数两层覆盖；三个返回分支都得带 stage_params/sampling 键（QML Object.keys 不吃 undefined）"""
    import os
    from app.ui.bridge import Bridge
    # 未跑 __init__ 的空壳即可：presetDetails 只读预设与静态视图，不碰 Qt 状态
    # （object.__new__(Bridge) 对 QObject 子类不安全）
    bridge = Bridge.__new__(Bridge)
    monkeypatch.setattr(genre_presets, "user_dir", lambda: str(tmp_path))
    with open(os.path.join(str(tmp_path), "probe_p1b.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "probe_p1b", "name": "P1 探针", "version": 2,
                   "stage_params": {"prose": {"temperature": 0.95, "slot": "review"}},
                   "sampling": {"top_p": 0.8, "thinking": "disabled"}}, f, ensure_ascii=False)
    d = bridge.presetDetails("probe_p1b")
    assert d["stage_params"]["prose"]["label"] == "正文"
    assert "温度=0.95" in d["stage_params"]["prose"]["value"]
    assert "连接槽=review" in d["stage_params"]["prose"]["value"]
    assert d["sampling"]["top_p"] == {"label": "核采样", "value": 0.8}
    assert d["sampling"]["thinking"]["label"] == "思考模式"
    for pid in ("", "没有这个预设"):
        detail = bridge.presetDetails(pid)
        assert detail["stage_params"] == {} and detail["sampling"] == {}
