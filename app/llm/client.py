# -*- coding: utf-8 -*-
"""LLM 统一调用客户端：OpenAI 兼容接口（分级重试 / 超时 / 输出清洗）

重试策略：
- 可重试：网络错误 / 超时 / HTTP 429 / 5xx（指数退避，最多 max_retries 次）
- 不可重试：4xx 其余错误 / 响应格式异常（立即抛出，不浪费重试）
"""
import hashlib
import json
import logging
import os
import re
import time

import httpx

from .. import dialogue_log   # WP-27：对话全量落盘（每次 HTTP 请求一条）

logger = logging.getLogger("qianbi.llm")


class LLMError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable  # 是否属于可重试错误


class _SubscriberError(Exception):
    """H-7：on_chunk/on_reasoning 订阅方（UI/管线）自身抛错的原样载体。

    旧实现掉进流式循环的 except Exception 被洗成「流式读取中断」，按
    max_retries 把同一份深栈原样重发——订阅方的 Python bug 烧的是真金。
    这里原样上抛不重试，from 保留原因链。"""


def _emit_to_subscriber(cb, text: str):
    """订阅回调的隔离发射：订阅方异常包成 _SubscriberError 上抛，不在重试射程"""
    try:
        cb(text)
    except Exception as e:
        raise _SubscriberError(f"订阅方回调异常（不重试）: {e}") from e


def _looks_like_dns_error(exc: BaseException) -> bool:
    """httpx.ConnectError 是否由域名解析失败引起（Windows 11001/11003、
    getaddrinfo、*nix 的 Name or service not known / Temporary failure in
    name resolution 等措辞都归进来，供 test_connection 给出对症提示）"""
    text = str(exc).lower()
    markers = ("getaddrinfo", "name resolution", "name or service",
               "nodename", "11001", "11003", "errno -2")
    return any(m in text for m in markers)


def check_base_url(url: str) -> str:
    """base_url 规则：以 # 结尾则原样使用；否则缺少 /vN 后缀时补 /v1"""
    url = (url or "").strip()
    if not url:
        return url
    if url.endswith("#"):
        return url.rstrip("#")
    import re
    if not re.search(r"/v\d+$", url) and "/v1" not in url:
        url = url.rstrip("/") + "/v1"
    return url


def _status_retryable(status: int) -> bool:
    """HTTP 状态码是否值得重试：429 限流与 5xx 服务端错误"""
    return status == 429 or 500 <= status <= 599


# 预设 stage_params 可改写的参数（slot 只用于选客户端，不进请求体）
STAGE_PARAM_KEYS = ("slot", "temperature", "top_p", "presence_penalty",
                    "frequency_penalty", "max_tokens", "thinking", "reasoning_effort")
# 值存在才进请求体的采样参数：无预设时请求体逐字不变（不凭空多出 "top_p": null）
OPTIONAL_PARAM_KEYS = ("top_p", "presence_penalty", "frequency_penalty")
# QW-B2 值校验白名单：这些参数的 4xx 拒收若在错误文本里**回显了我方发的值**，
# 说明网关拒的是「取值」而不是「参数本身」——按名即剥会让用户的配置错误被藏起来，
# 还把该参数整进程停发（max_tokens 给大了被剥掉 = 这个模型本进程收不到输出上限）。
# 名单外的参数（thinking 等枚举/开关）网关通常不回显值，维持按名即剥。
_VALUE_ECHO_KEYS = frozenset({"max_tokens", "temperature", "top_p",
                              "presence_penalty", "frequency_penalty"})
# 章级配置快照（P2）留存的采样字段：只记实际进了请求体的，「没下发」本身也是信息
SAMPLING_TRACE_KEYS = STAGE_PARAM_KEYS[1:] + ("thinking", "reasoning_effort")
# temperature 锁死相位：审校多票判定口径（gates.review_temperature=0.2）是跨书可比的
# 验收基线。预设若能把审校温度调回 0.7，多票就退化成同一温度下的复读。
TEMP_LOCKED_PHASES = frozenset({"review"})

# 模型能力备忘录（进程内，跨客户端实例共享）：网关报错明确「不支持某参数」后，
# 本进程内同 base_url+model 不再下发该参数。刻意不进 config.py —— 它是探测结果
# 而非用户意图，写进用户配置会污染设置页与双端同步面，且换网关后即失效。
_UNSUPPORTED = {}
_UNSUPPORTED_HINT_KEYS = STAGE_PARAM_KEYS[1:] + ("thinking", "reasoning_effort", "stream_options")

# W-7：「配了 effort 却没开思考」的告警去重（进程内；组合级，换相位/档位会再提示一次）
_EFFORT_DROPPED_WARNED = set()

# W-01：思考模型「只思考不吐正文」自愈的能力表。空内容自愈的旧判据是
# payload.get("thinking")——只问「我方是否发了 thinking 键」，不问「模型是否在想」，
# 于是 DeepSeek 默认开思考、产品连接又不下发 thinking 键的相位（prose/core/volume/
# worldbook…）永远不自愈，只会原样重发同一发（v15 每章 6 笔空流×3 的真凶）。
# 下列常量把「怎么关这个渠道的思考」按 provider 分开，见 _escalate_after_empty。
_THINKING_PARAM_HOSTS = ("deepseek",)  # 顶层 thinking={"type":"disabled"} 是确定有效的降档
_ESCALATE_CEILING = 32768              # 抬高 max_tokens 的硬顶：给它把思考跑完再吐正文的空间

# C05（QW-B1/E 识别层）四件配套常量：
# - 非流式输出地板：思考计入输出上限，max_tokens 给太小（如 1024）时思考就能把它
#   吃光、正文零输出。easy-writing NON_STREAM_MIN_TOKENS=2048 同源结论（实测不够）。
_NON_STREAM_MIN_TOKENS = 2048
# - Retry-After 尊重上限（秒）：服务端限流头照办，但防一个恶意/坏值把挂机跑吊死几小时
_RETRY_AFTER_CAP = 120.0
# - finish_reason 人话对照（E 识别层：last_finish_reason 落在 client 实例上，后续
#   G2 截断拦截消费；这三条文案先把「为什么空/为什么短」翻译给人）
_FINISH_REASON_HINTS = {
    "length": "输出达到 max_tokens 上限被截断（思考或长文吃光了输出预算）",
    "stop": "模型正常收尾",
    "content_filter": "内容被网关安全过滤器拦截",
}


class _ThinkStreamFilter:
    """`<think>…</think>` 流式过滤状态机（C05，对拍 easy-writing ai-think-filter.ts）

    部分 OpenAI 兼容渠道把推理模型的思考过程内联在 content 里（MiniMax M2 官方接口、
    OpenRouter/硅基流动路由的部分模型）——正文场景一旦漏进思考文字会被直接写进用户
    小说，必须在请求层统一剥掉。四态：正常输出 / `<think>` 开（思考段内整体丢弃）/
    闭标签后回到正常 / 尾部半截标签 holdback（`<thi` 可能是标签开头也可能是正文，
    扣住等下一片补齐再判断）。流在思考段内结束（未闭合）→ 未吐出的部分整体丢弃。

    与 easy-writing 语义逐字对拍：大小写不敏感（`<Think>` 同样剥）；holdback 上限
    = 标签长度-1；finish() 时半截标签按普通文本如实吐出（正常收尾），思考段没闭合
    则丢弃（被打断的思考不该漏半句进正文）。
    """

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self):
        self._carry = ""
        self._in_think = False

    def _holdback_len(self, lower: str) -> int:
        """尾部若可能是半截标签（如 "<thi"），长度扣住不吐，等下一片补齐再判断"""
        ceiling = min(len(self.CLOSE) - 1, len(lower))
        for n in range(ceiling, 0, -1):
            tail = lower[-n:]
            if self.OPEN.startswith(tail) or self.CLOSE.startswith(tail):
                return n
        return 0

    def push(self, chunk: str) -> str:
        """喂一个增量，返回本次可见文本（思考段内的内容直接丢弃）"""
        self._carry += chunk or ""
        out = ""
        while True:
            lower = self._carry.lower()
            if self._in_think:
                close = lower.find(self.CLOSE)
                if close < 0:
                    # 思考内容直接丢，只留可能是半截闭标签的尾巴
                    keep = self._holdback_len(lower)
                    self._carry = self._carry[len(self._carry) - keep:]
                    return out
                self._carry = self._carry[close + len(self.CLOSE):]
                self._in_think = False
                continue
            open_at = lower.find(self.OPEN)
            if open_at >= 0:
                out += self._carry[:open_at]
                self._carry = self._carry[open_at + len(self.OPEN):]
                self._in_think = True
                continue
            keep = self._holdback_len(lower)
            cut = len(self._carry) - keep
            out += self._carry[:cut]
            self._carry = self._carry[cut:]
            return out

    def finish(self) -> str:
        """流结束收尾：正常态把扣住的尾巴如实吐回；思考段未闭合则整体丢弃"""
        rest = "" if self._in_think else self._carry
        self._carry = ""
        self._in_think = False
        return rest


def strip_think_blocks(text: str) -> str:
    """非流式整段清洗：闭合段整段删；只剩开标签没闭合（被截断）时其后全为思考内容一并丢弃"""
    t = text or ""
    t = re.sub(r"<think>[\s\S]*?</think>", "", t, flags=re.IGNORECASE)
    open_at = t.lower().find(_ThinkStreamFilter.OPEN)
    return t[:open_at] if open_at >= 0 else t


def _parse_retry_after(value, now: float = None):
    """Retry-After 头 → 秒数。认不了（空/非数字/坏日期）返回 None 走指数退避。

    HTTP-date 形式（`Wed, 21 Oct 2026 07:28:00 GMT`）按当前时刻折算成剩余秒数；
    负数（已经过期）钳成 0 = 立刻重试。
    """
    v = str(value or "").strip()
    if not v:
        return None
    try:
        return max(float(v), 0.0)
    except ValueError:
        pass
    try:
        from datetime import datetime, timezone
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if now is None:
            now = datetime.now(timezone.utc).timestamp()
        return max(dt.timestamp() - now, 0.0)
    except Exception:  # noqa: BLE001
        return None


def _finish_reason_hint(finish: str) -> str:
    """finish_reason → 人话；认不出就返回空串（不编话）"""
    return _FINISH_REASON_HINTS.get((finish or "").strip().lower(), "")


def _value_echoed_in(low_text: str, value) -> bool:
    """错误文本是否回显了我方实际下发的参数值（QW-B2 值校验的判据）

    数值参数网关可能写成 `32768` 或 `32,768`、`0.7` 或整数化的 `3`，都算回显；
    容器/布尔/None 不判（枚举与开关参数不进值校验白名单）。"""
    if value is None or isinstance(value, (bool, dict, list)):
        return False
    if isinstance(value, int):
        cands = {str(value), format(value, ",")}
    elif isinstance(value, float):
        cands = {str(value), repr(value), format(value, "g")}
        if value.is_integer():
            cands.add(str(int(value)))
    else:
        cands = {str(value).lower()}
    return any(c and c.lower() in low_text for c in cands)


def _host_of(url: str) -> str:
    """base_url → 主机名（去 schema、去端口、去路径、小写）。用于分渠道判能力。"""
    u = (url or "").lower()
    if "://" in u:
        u = u.split("://", 1)[1]
    u = u.split("/", 1)[0]
    if u.startswith("["):        # IPv6 字面量 [::1]:port
        return u.split("]", 1)[0].lstrip("[")
    return u.split(":", 1)[0]


def invalidate_capability(base_url: str = "", model: str = ""):
    """按 (base_url, model) 清掉能力备忘录（H-7 失效入口）；两者皆空 = 整表清空。

    备忘录是进程内探测结果，用户改好连接配置保存后必须重新下发——
    bridge.saveConnection 调这里定点失效，否则本进程内仍按旧结论剥参数。"""
    if not base_url and not model:
        _UNSUPPORTED.clear()
        return
    _UNSUPPORTED.pop(((base_url or "").rstrip("/"), model or ""), None)


def _is_local_template_host(host: str) -> bool:
    """本机推理网关（llama.cpp / vLLM / LM Studio）：关思考走 chat_template_kwargs。"""
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "::")


def _is_thinking_param_host(host: str) -> bool:
    """支持顶层 thinking 参数的云端网关（当前只有 DeepSeek 官方）。"""
    return any(t in host for t in _THINKING_PARAM_HOSTS)


# ---- D1 预算宪法：进程级调用观察者（0.23.0）----
# 计数事件在本层只广播不裁决：orchestrator 注册章周期计数器（GenBudget），共写/
# 探针等旁路不注册则零开销。事件 = 每个网关回了 usage 的物理响应一条（chat 与
# _stream_messages 的成功记账与 W-4 白付 empty/abort/retry 都汇经 _record_usage），
# 形状 {slot, phase, status, tin, tout, latency}；网关全程不回 usage 的失败不计次
# （时长轴兜底）。观察者异常绝不穿回调用链。
_call_observers = []


def add_call_observer(fn) -> None:
    """注册 LLM 调用观察者（D1 预算宪法接入口；重复注册幂等）"""
    if fn not in _call_observers:
        _call_observers.append(fn)


def remove_call_observer(fn) -> None:
    """注销调用观察者（未注册过则静默）"""
    try:
        _call_observers.remove(fn)
    except ValueError:
        pass


def _emit_call_event(ev: dict) -> None:
    """向全部观察者广播一次调用事件（订阅方异常吞掉——预算是观测件，不碰调用链）"""
    for fn in list(_call_observers):
        try:
            fn(ev)
        except Exception as e:  # noqa: BLE001
            logger.debug("调用观察者失败（忽略）: %s", e)


def _cache_split(usage: dict, tin: int) -> tuple:
    """一次响应的 usage → (hit, miss)。W-5 口径：**"报了 0"与"没报"不是同一件事**。

    - DS 原生 `prompt_cache_hit_tokens`/`prompt_cache_miss_tokens`：键在就照收（含 0/0）；
    - OpenAI 系只回 `prompt_tokens_details.cached_tokens`：命中=cached、未命中=tin-cached，
      **cached=0 也算上报**（旧代码 `if cached:` 把"真没命中"和"网关没回字段"揉成同一行，
      omen-alpha 33.7% 的调用因此分不清是盲区还是全 miss）；
    - 什么都没回 → (0, 0)＝盲区，由 app.usage.cache_caliber 把整条输入划成 blind_tok，
      既不按命中也不按未命中计价。"""
    usage = usage or {}
    h, m = usage.get("prompt_cache_hit_tokens"), usage.get("prompt_cache_miss_tokens")
    if h is not None or m is not None:
        return int(h or 0), int(m or 0)
    det = usage.get("prompt_tokens_details")
    if isinstance(det, dict) and det.get("cached_tokens") is not None:
        cached = int(det.get("cached_tokens") or 0)
        return cached, max(tin - cached, 0)
    return 0, 0


class LLMClient:
    """单连接配置对应的调用客户端（无状态，可反复使用）"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.7, max_tokens: int = 8192, timeout: int = 300,
                 max_retries: int = 2, backoff_base: float = 2.0, thinking: str = "",
                 reasoning_effort: str = "", slot: str = "",
                 payload_defaults: dict = None, stage_params: dict = None,
                 user_id: str = ""):
        self.slot = slot or ""   # 槽位标签（token 用量统计维度，插件）
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.user_id = user_id or ""   # DeepSeek user 字段：KV 缓存隔离（E2.2，官方 API 参考）
        # opencode 的 Console Go 网关（omen-alpha）要求 `x-session-id`，缺失直接 400
        # MissingSessionID；DS / TokenRhythm 不看这个头。取 user_id 派生的**稳定**值：
        # 同一跑次同一会话域——按进程随机会把缓存域打散，长测命中直接失真。
        self.session_id = (user_id or "qianbi-novel").strip().replace(" ", "-") or "qianbi-novel"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.thinking = thinking or ""   # "disabled"/"enabled"：DeepSeek 系网关的思考开关
        self.reasoning_effort = reasoning_effort or ""  # "low"/"high"/"max"：思考强度（DeepSeek 顶层参数）
        # 预设全书采样基线（不分相位）：优先级低于阶段档、高于上面的实例默认值
        self.payload_defaults = dict(payload_defaults or {})
        # 预设阶段参数表 {phase: {param: value}}：整体替换、只读，换预设时由路由重绑
        self.stage_params = dict(stage_params or {})
        # C44 连接级流式开关：部分模型（如 OpenRouter stealth 系）不支持流式——
        # 长 prompt 流式请求返回空内容。False 时 stages._stream 走 chat() 非流式。
        self.stream_enabled = True
        # 调用统计
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        # 最近一次请求现场（诊断/失败 dump 用）
        self.last_prompt = ""
        self.last_error = ""
        self.last_latency = 0.0
        self.last_phase = ""        # 最近一次调用的阶段标签（选档与快照用）
        self.last_degraded = False  # 最近一次调用是否发生过「不支持参数」降级
        self.last_aborted = False   # 最近一次流式调用是否被调用方 abort 中断
        self.last_sampling = {}     # 最近一次请求体实际下发的采样参数（章级配置快照）
        # E 方案识别层：最近一次响应的 finish_reason（流式过去根本不读这个字段）。
        # G2 截断拦截（「length 结束的稿子不得进闸门链」）后续从这里取值。
        self.last_finish_reason = ""

    @classmethod
    def from_connection(cls, conn: dict, max_retries: int = 2,
                        backoff_base: float = 2.0, slot: str = "",
                        payload_defaults: dict = None,
                        stage_params: dict = None) -> "LLMClient":
        client = cls(
            base_url=conn.get("base_url", ""),
            api_key=conn.get("api_key", ""),
            model=conn.get("model", ""),
            temperature=conn.get("temperature", 0.7),
            max_tokens=conn.get("max_tokens", 8192),
            timeout=conn.get("timeout", 300),
            max_retries=max_retries,
            backoff_base=backoff_base,
            thinking=conn.get("thinking", ""),
            reasoning_effort=conn.get("reasoning_effort", ""),
            slot=slot,
            payload_defaults=payload_defaults,
            stage_params=stage_params,
            user_id=conn.get("user_id", ""),
        )
        # C44：连接级流式开关（连接 dict 键 "stream"，缺省 True=维持流式）
        client.stream_enabled = bool(conn.get("stream", True))
        return client

    def _record_usage(self, usage: dict, latency: float, phase: str = "",
                      status: str = ""):
        """token 用量统计埋点（插件）：本地 jsonl + 内存聚合，失败不影响调用

        status 非空＝这一发**没产出可用正文却可能已经花钱**（"empty"/"abort"），
        落到用量行的 `st` 字段，台账据此分列 retry_spend（W-4）。"""
        try:
            tin = int(usage.get("prompt_tokens", 0) or 0)
            tout = int(usage.get("completion_tokens", 0) or 0)
            if _call_observers:
                # D1：调用事件在记账前广播（0/0 usage 的响应也计次——物理响应真实
                # 发生了；tokens 按实报数，没报就是 0）
                _emit_call_event({"slot": self.slot, "phase": phase or "",
                                  "status": status or "", "tin": tin, "tout": tout,
                                  "latency": float(latency or 0.0)})
            # DeepSeek 上下文缓存命中/未命中 tokens（其他网关可能不返回）
            hit, miss = _cache_split(usage, tin)
            # 推理 tokens 口径（OpenAI 兼容 completion_tokens_details.reasoning_tokens，
            # DeepSeek 思考模式等网关可能不返回，默认 0）
            reasoning = int((usage.get("completion_tokens_details") or {})
                            .get("reasoning_tokens") or 0)
            if tin <= 0 and tout <= 0:
                return
            self.total_prompt_tokens += tin
            self.total_completion_tokens += tout
            from .. import usage as _usage
            _usage.record(None, self.model, self.slot, tin, tout, latency,
                          hit=hit, miss=miss, phase=phase, reasoning=reasoning,
                          sent=getattr(self, "last_sampling", None) or None,
                          status=status)
        except Exception as e:  # noqa: BLE001
            logger.debug("用量埋点失败（忽略）: %s", e)

    def _retry_wait(self, attempt: int, abort=None, reason=None,
                    retry_after=None) -> bool:
        """重试前的统一指数退避（W-4）。返回 False＝等待期间被中止，调用方应 break。

        过去只有「抛异常」那条路径会睡，429/5xx 与空内容两条 `continue` 直接绕过退避
        立刻重发同一份几百 k 的深栈——TR 的 503 SERVICE_BUSY 三连就是这么把整跑打死的。
        C05：网关 429 带了 Retry-After 头就照它等（尊重服务端的节流节奏比瞎猜指数
        更省配额）；没有头/认不出该值则退回指数退避，行为与改动前逐字一致。
        """
        ra = _parse_retry_after(retry_after)
        if ra is not None:
            delay = min(ra, _RETRY_AFTER_CAP)
            logger.warning("LLM retry %s/%s after %.1fs (Retry-After): %s",
                           attempt + 1, self.max_retries, delay, reason)
        else:
            delay = self.backoff_base * (2 ** attempt)
            logger.warning("LLM retry %s/%s after %.1fs: %s",
                           attempt + 1, self.max_retries, delay, reason)
        if abort is None:
            time.sleep(delay)
            return True
        _end = time.monotonic() + delay
        while time.monotonic() < _end:      # 退避也要可中断：否则点停止后还要白等数秒
            if abort():
                self.last_aborted = True
                return False
            time.sleep(0.1)
        return True

    def _charge_failed_attempt(self, usage, t0: float, phase: str, status: str) -> None:
        """没走到「成功记账」就要退出的一发：网关回了 usage 就如实记账（打 status），
        没回就不编数字——白付至少记到「这笔存在」的粒度，账上不再恒等于 0。"""
        if not usage:
            return
        try:
            self._record_usage(usage, time.monotonic() - t0, phase=phase, status=status)
        except Exception:  # noqa: BLE001
            pass

    def _chat_url(self) -> str:
        if "/v1" in self.base_url:
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if "opencode" in self.base_url:
            # 仅 opencode（omen-alpha / Console Go）要求；DS 与 TokenRhythm 不看，
            # 多发一个头可能影响它们的路由/缓存，所以别的渠道一个字节都不加。
            headers["x-session-id"] = self.session_id
        return headers

    def _build_messages(self, prompt: str, system: str = "") -> list:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _memo_key(self) -> tuple:
        return (self.base_url, self.model)

    def _unsupported(self) -> set:
        """本模型已被网关拒收的参数（进程内探测结果，随进程结束失效）"""
        return _UNSUPPORTED.get(self._memo_key(), set())

    def _apply_capability(self, payload: dict) -> dict:
        """按能力备忘录剥掉本模型不支持的参数（首次拒收后，后续调用直接走这条路）"""
        drop = self._unsupported() & set(payload)
        if not drop:
            return payload
        return {k: v for k, v in payload.items() if k not in drop}

    def _downgrade(self, payload: dict, err_text: str):
        """网关 4xx 明确点名了请求体里的某参数 → 剥掉重发并记入备忘录

        按名即剥 + 值校验白名单（QW-B2）：只有 `_UNSUPPORTED_HINT_KEYS` 白名单内的
        参数名才可能被剥（白名单外点了名也不剥）；白名单内但错误文本回显了我方发的
        值（`_VALUE_ECHO_KEYS`）说明拒的是取值——不剥、不进备忘录，返回 None 让
        调用方把真错误原样抛给用户去改配置。认不出可剥参数时同样返回 None——
        参数降级不能变成吞错误的面子工程。
        """
        low = (err_text or "").lower()
        rejected = [p for p in _UNSUPPORTED_HINT_KEYS if p in payload and p in low]
        if not rejected:
            return None
        echoed = [p for p in rejected
                  if p in _VALUE_ECHO_KEYS and _value_echoed_in(low, payload.get(p))]
        if echoed:
            # 值级拒收：剥参数只会掩盖「你给的数不合法」。如实抛错，备忘录不留错结论。
            logger.warning("网关拒收的是 %s 的取值（错误文本回显了该值），不剥参数：%s",
                           "/".join(echoed), (err_text or "")[:200])
            return None
        if len(_UNSUPPORTED) > 64:
            _UNSUPPORTED.clear()   # 备忘录只做加速，不长期吃内存（换连接配置后旧键无意义）
        _UNSUPPORTED.setdefault(self._memo_key(), set()).update(rejected)
        self.last_degraded = True
        for k in rejected:
            self.last_sampling.pop(k, None)   # 快照不能留「其实没下发」的参数
        logger.warning("模型 %s 不支持 %s，本进程内不再下发", self.model, "/".join(rejected))
        return {k: v for k, v in payload.items() if k not in rejected}

    def invalidate_capability(self):
        """清掉本 (base_url, model) 的能力备忘录（H-7 失效入口）。

        备忘录按 (base_url, model) 进程内记忆「网关不支持某参数」；用户改好
        配置点保存后必须重新下发——bridge.saveConnection 调这里定点失效。"""
        invalidate_capability(self.base_url, self.model)

    def _overrides(self, phase: str) -> dict:
        """非显式参数覆盖层合并视图：预设全书基线打底 + 本阶段档压顶

        review 相位抹掉一切预设来源的 temperature —— 审校 0.2 多票口径是跨书验收
        基线，全书基线同样不该把它调回 0.7（显式实参仍最高，调用点传多少就是多少）。
        """
        ov = dict(self.payload_defaults)
        if phase:
            ov.update((self.stage_params or {}).get(phase) or {})
        ov.pop("slot", None)   # slot 供调用方选客户端（stages._stream），不进 HTTP body
        if phase in TEMP_LOCKED_PHASES:
            ov.pop("temperature", None)
        return ov

    def _resolve(self, key: str, explicit=None, over: dict = None):
        """采样参数优先级：显式实参 ＞ 预设覆盖层（全书基线 → 阶段档）＞ 客户端实例"""
        if explicit is not None:
            return explicit
        if over and over.get(key) is not None:
            return over[key]
        return getattr(self, key, None)

    def _build_payload(self, messages: list, *, stream: bool, phase: str = "",
                       temperature=None, max_tokens=None,
                       thinking=None, reasoning_effort=None) -> dict:
        """请求体唯一构造点（chat / chat_stream 共用）

        phase 不进 HTTP body：它只用于选预设档位（stage_params）与诊断/快照留存。
        """
        over = self._overrides(phase)
        thinking = self._resolve("thinking", thinking, over) or ""
        _dbg = os.environ.get("QIANBI_DEBUG_PAYLOAD")
        if _dbg:
            # 诊断门控（v0.19）：逐请求记录消息栈形状与会话前缀指纹，
            # 用于离线核对前缀缓存为何未命中（不落正文，只落尺寸/哈希/角色序）
            try:
                _roles = [m.get("role", "") for m in messages]
                _lens = [len(m.get("content", "")) for m in messages]
                # 逐消息哈希：等长改写只看 lens 是看不见的（章界 32k 二次计价的定位就靠它）
                _hashes = [hashlib.sha1(m.get("content", "").encode("utf-8")).hexdigest()[:10]
                           for m in messages]
                _h = _hashes[0] if _hashes else ""
                _line = json.dumps({"phase": phase or "", "roles": _roles,
                                    "lens": _lens, "sys_hash": _h, "hashes": _hashes,
                                    "model": self.model, "user": self.user_id or ""},
                                   ensure_ascii=False)
                with open(_dbg, "a", encoding="utf-8") as _f:
                    _f.write(_line + chr(10))
            except Exception:
                pass
        mt = self._resolve("max_tokens", max_tokens, over)
        if not stream and isinstance(mt, (int, float)) and mt < _NON_STREAM_MIN_TOKENS:
            # C05 非流式输出地板：思考计入输出上限，太小的 max_tokens 会被思考吃光
            # 只回一个空内容（再烧一次自愈重试）。流式不受此限（增量天然可截断）。
            logger.info("非流式 max_tokens=%s 低于地板，抬到 %s", mt, _NON_STREAM_MIN_TOKENS)
            mt = _NON_STREAM_MIN_TOKENS
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self._resolve("temperature", temperature, over),
            "max_tokens": mt,
            "stream": stream,
        }
        for key in OPTIONAL_PARAM_KEYS:   # 无配置时不下发：请求体与改造前逐字一致
            val = self._resolve(key, None, over)
            if val is not None:
                payload[key] = val
        if self.user_id:
            # 连接档案 user_id → API `user` 字段：DeepSeek 官方口径"can be used for
            # KVCache isolation"——实验分支/不同书之间隔离缓存空间（E2.2）
            payload["user"] = self.user_id
        if stream:
            payload["stream_options"] = {"include_usage": True}   # 末 chunk 携带 usage（用量统计）
        if thinking:
            payload["thinking"] = {"type": thinking}
            effort = self._resolve("reasoning_effort", reasoning_effort, over)
            if thinking == "enabled" and effort:
                # DeepSeek V4 顶层参数：思考强度 low/high/max（参考 DeepSeek 官方 Thinking Mode
                # 文档与 opencode-go provider 的 effort 映射；max 为最高档）
                payload["reasoning_effort"] = effort
            elif effort:
                # W-7：effort 只在思考模式下生效——配了档却没开思考＝整条配置空转
                # （过去完全静默；产品连接不设 thinking 时尤其容易踩）。同一组合只提示一次。
                _key = (self.model, phase or "", thinking, str(effort))
                if _key not in _EFFORT_DROPPED_WARNED:
                    _EFFORT_DROPPED_WARNED.add(_key)
                    logger.warning(
                        "相位 %s 配了 reasoning_effort=%s 但 thinking=%s：该参数不会随请求下发"
                        "（DeepSeek 仅思考模式接受）。要真正降档请改 thinking 本身。",
                        phase or "(无相位名)", effort, thinking)
        payload = self._apply_capability(payload)
        # 备忘录剥掉的参数不登记：快照要记「真正会下发的」，而不是「我以为下发了的」
        self.last_sampling = {k: payload[k] for k in SAMPLING_TRACE_KEYS if k in payload}
        return payload

    def _escalate_after_empty(self, payload: dict, finish: str = ""):
        """W-01：空内容后，按渠道能力算出「下一次该发什么」——保证与本次**不同**。

        判据从「我方是否发了 thinking 键」改成「这个渠道能不能关思考 / 该关没关」。
        阶梯一次只走一格，靠请求体自身内容自限（改过的格不会再触发），天然收敛，不额外
        撑开重试预算：
          1) 我方显式开了思考 → 关掉 + 撤 effort（DeepSeek 确定有效）；
          2) DeepSeek 默认开思考、我方没发 thinking 键 → 这次显式下发 disabled；
             （prose/core/volume/worldbook 等相位正落在这里，旧自愈对它们完全失效）
          3) 本机推理网关 → 下发 chat_template_kwargs.thinking=false；
          4) 没有更便宜的关思考手段时抬 max_tokens 到硬顶，给思考跑完再吐正文的空间。
        无可升级时返回 (None, "")，调用方按普通重试/抛错处理。
        """
        host = _host_of(self.base_url)
        th = payload.get("thinking")
        if isinstance(th, dict) and th.get("type") != "disabled":
            nxt = dict(payload)
            nxt["thinking"] = {"type": "disabled"}
            nxt.pop("reasoning_effort", None)
            return nxt, "关闭思考（thinking=disabled）"
        if "thinking" not in payload and _is_thinking_param_host(host):
            nxt = dict(payload)
            nxt["thinking"] = {"type": "disabled"}
            return nxt, "对 DeepSeek 显式下发 thinking=disabled"
        if _is_local_template_host(host) and "chat_template_kwargs" not in payload:
            nxt = dict(payload)
            nxt["chat_template_kwargs"] = {"thinking": False}
            return nxt, "对本地下发 chat_template_kwargs.thinking=false"
        mt = payload.get("max_tokens")
        if isinstance(mt, int) and mt < _ESCALATE_CEILING:
            nxt = dict(payload)
            nxt["max_tokens"] = min(mt * 2, _ESCALATE_CEILING)
            return nxt, f"抬高 max_tokens {mt}→{nxt['max_tokens']}"
        return None, ""

    def chat(self, prompt: str, system: str = "", temperature: float = None,
             *, phase: str = "") -> str:
        """单轮对话，分级重试（网络/超时/429/5xx 指数退避），返回文本内容"""
        if not self.model:
            # v0.18.2 起出厂预设只预置提供方：空模型不该变成 API 400 的一堆英文
            raise LLMError("这条连接还没选模型——到 设置 · 连接与模型 里为它选一个（下拉候选或「拉取」）")
        self.last_prompt = prompt
        self.last_error = ""
        self.last_phase = phase or ""
        self.last_degraded = False
        self.last_finish_reason = ""
        headers = self._headers()
        messages = self._build_messages(prompt, system)
        payload = self._build_payload(messages, stream=False, phase=phase,
                                      temperature=temperature)
        t0 = time.monotonic()
        last_err = None
        _dl_done = {"n": 0}   # WP-27：本尝试已记过一条（保证 一请求=一记录）

        def _dl(outcome, reply="", usage=None, err="", note=""):
            if _dl_done["n"] >= attempt + 1:
                return
            _dl_done["n"] = attempt + 1
            dialogue_log.record_chat(
                client=self, phase=phase, outcome=outcome, prompt=prompt,
                system=system, reply=reply, usage=usage, error=err, note=note,
                attempt=attempt + 1, degraded=self.last_degraded,
                latency=time.monotonic() - t0, stream=False)

        for attempt in range(self.max_retries + 1):
            last_retry_after = None   # Retry-After 只对引发本次等待的那一发生效
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(self._chat_url(), json=payload, headers=headers)
                if resp.status_code != 200:
                    err = LLMError(
                        f"API 返回 {resp.status_code}: {resp.text[:500]}",
                        retryable=_status_retryable(resp.status_code))
                    if resp.status_code == 429:
                        # C05：429 时记下 Retry-After 头，重试等待按服务端要求来
                        _h = getattr(resp, "headers", None)
                        last_retry_after = _h.get("Retry-After") if _h is not None else None
                    if err.retryable:
                        last_err = err
                        _dl(f"http_{resp.status_code}", err=str(err), note="retryable")
                    else:
                        # 网关明确点名「不支持某参数」：剥掉它（记入能力备忘录）再发一次；
                        # 认不出可剥参数照原样抛出——降级不许把真错误吞成静默重试。
                        fixed = self._downgrade(payload, resp.text)
                        if fixed is None:
                            self.last_error = str(err)
                            self.last_latency = time.monotonic() - t0
                            _dl(f"http_{resp.status_code}", err=str(err), note="fatal")
                            raise err
                        payload = fixed
                        last_err = err
                        _dl(f"http_{resp.status_code}", err=str(err), note="downgraded")
                else:
                    data = resp.json()
                    content = ""
                    try:
                        content = data["choices"][0]["message"]["content"] or ""
                    except (KeyError, IndexError):
                        pass
                    try:
                        # E 识别层：finish_reason 无论内容空否都记录（空分支过去才读，
                        # 流式过去根本不读——G2 截断拦截要靠它分辨「写完」与「被截断」）
                        self.last_finish_reason = data["choices"][0].get("finish_reason") or ""
                    except (KeyError, IndexError):
                        pass
                    if not content:
                        # HTTP 200 但内容为空：服务端生成中断/超限，可重试
                        finish = self.last_finish_reason
                        hint = _finish_reason_hint(finish)
                        last_err = LLMError(
                            "模型返回空内容 (finish_reason=%s%s)" % (finish, f"：{hint}" if hint else ""),
                            retryable=True)
                        # W-4：这一发的 token 是真花了的（usage 已在响应里），先记账
                        self._charge_failed_attempt(data.get("usage"), t0, phase, "empty")
                        _dl('ok_empty', usage=data.get('usage') or {}, note=f'finish_reason={finish}')
                        nxt, why = self._escalate_after_empty(payload, finish)
                        if nxt is not None and nxt != payload:
                            # 空内容多半是「思考把 max_tokens 吃光 / 只思考不输出」：按渠道能力
                            # 换一发**不同**的请求体（旧自愈只在发过 thinking 键时才动，对
                            # DeepSeek 默认开思考的相位形同虚设，且会原样重发同一发白烧预算）。
                            logger.warning(
                                "模型返回空内容(finish_reason=%s)，第 %s 次降级重发：%s",
                                finish, attempt + 1, why)
                            self.last_degraded = True
                            payload = nxt
                            self._retry_wait(attempt, None, last_err)
                            continue
                        if attempt < self.max_retries:
                            self._retry_wait(attempt, None, last_err)
                            continue
                        raise last_err
                    usage = data.get("usage") or {}
                    self.last_latency = time.monotonic() - t0
                    self._record_usage(usage, self.last_latency, phase=phase)
                    logger.info("LLM ok model=%s prompt_tokens=%s completion_tokens=%s latency=%.1fs",
                                self.model, usage.get("prompt_tokens", 0),
                                usage.get("completion_tokens", 0), self.last_latency)
                    _dl("ok", reply=content, usage=usage)
                    return content.strip()
            except httpx.TimeoutException:
                last_err = LLMError("请求超时，请检查网络或增大 timeout", retryable=True)
                _dl("timeout", err=str(last_err))
            except httpx.RequestError as e:
                last_err = LLMError(f"网络错误: {e}", retryable=True)
                _dl("network", err=str(last_err))
            except (KeyError, IndexError) as e:
                last_err = LLMError(f"API 响应格式异常: {e}", retryable=False)
                _dl("error", err=str(last_err))
            except LLMError as e:
                if not e.retryable:
                    _dl("error", err=str(e))
                    raise
                last_err = e
            if attempt < self.max_retries:
                # W-4 统一退避入口；429 带了 Retry-After 就按服务端要求等
                self._retry_wait(attempt, None, last_err, retry_after=last_retry_after)
        self.last_error = str(last_err)
        self.last_latency = time.monotonic() - t0
        _dl("error", err=str(last_err), note="retries-exhausted")
        raise last_err

    def chat_stream(self, prompt: str, system: str = "", temperature: float = None,
                    on_chunk=None, on_reasoning=None, *, phase: str = "",
                    abort=None) -> str:
        """流式单轮对话：stream=true 逐块回调（on_chunk 收到增量文本），返回完整文本。

        回调约定：
          on_chunk(text)      —— 内容增量
          on_reasoning(text)  —— 推理内容增量（DeepSeek 思考模式，可选）
        重试/错误语义与 chat() 一致；失败时已回调的增量不回收（UI 按现场处理）。

        abort：可选的无参谓词，返回真即中断本次流式。逐块 + 退避等待时各查一次
        （读一个 bool，相对网络往返可忽略）。**不在本层抛停止异常**——
        PipelineStopped 属 core 的语义，本层只置 last_aborted 并回已收增量，
        由调用方决定怎么中止。abort=None 时行为与改动前逐字一致。
        """
        messages = self._build_messages(prompt, system)
        return self._stream_messages(messages, on_chunk=on_chunk,
                                     on_reasoning=on_reasoning, phase=phase,
                                     temperature=temperature, abort=abort)

    def chat_turn(self, messages: list, *, on_chunk=None, on_reasoning=None,
                  phase: str = "", temperature=None, abort=None) -> str:
        """多轮消息直通：messages 原样作为请求体（调用方持有会话栈）。

        语义与 chat_stream 完全一致（重试/退避/abort/流式回调/用量埋点），
        只是不再从 prompt+system 构造 messages。诊断字段 last_prompt 取
        messages 中最后一条 user 轮内容。
        """
        return self._stream_messages(list(messages), on_chunk=on_chunk,
                                     on_reasoning=on_reasoning, phase=phase,
                                     temperature=temperature, abort=abort)

    def _stream_messages(self, messages: list, *, on_chunk=None, on_reasoning=None,
                         phase: str = "", temperature=None, abort=None) -> str:
        """流式内核（chat_stream / chat_turn 共用）：messages 原样作为请求体。

        请求/重试/退避/abort/流式回调/用量埋点即原 chat_stream 主体（逐字保留）；
        chat_stream 只负责从 prompt+system 构造 messages 后转调，对外行为不变。
        """
        if not self.model:
            raise LLMError("这条连接还没选模型——到 设置 · 连接与模型 里为它选一个（下拉候选或「拉取」）")
        self.last_aborted = False
        # 诊断现场：单轮路径下恰为 prompt（最后一条 user 轮），多轮直通取最后一条 user
        self.last_prompt = ""
        for _m in messages:
            if isinstance(_m, dict) and _m.get("role") == "user":
                self.last_prompt = _m.get("content")
        self.last_error = ""
        self.last_phase = phase or ""
        self.last_degraded = False
        self.last_finish_reason = ""
        headers = self._headers()
        payload = self._build_payload(messages, stream=True, phase=phase,
                                      temperature=temperature)

        t0 = time.monotonic()
        last_err = None
        _dl_done = {"n": 0}   # WP-27：本尝试已记过一条（保证 一请求=一记录）

        def _dl(outcome, reply="", usage=None, err="", note=""):
            if _dl_done["n"] >= attempt + 1:
                return
            _dl_done["n"] = attempt + 1
            dialogue_log.record_chat(
                client=self, phase=phase, outcome=outcome,
                prompt=self.last_prompt, reply=reply, usage=usage, error=err,
                note=note, attempt=attempt + 1, degraded=self.last_degraded,
                latency=time.monotonic() - t0, stream=True)

        for attempt in range(self.max_retries + 1):
            parts = []   # 每次尝试重置：断流重试不得拼接两次的部分内容
            think = _ThinkStreamFilter()   # C05：内联 <think> 过滤状态机（逐尝试重置）
            stream_usage = None   # 末 chunk 的 usage（include_usage）
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    with client.stream("POST", self._chat_url(), json=payload, headers=headers) as resp:
                        if resp.status_code != 200:
                            # 流式响应必须先 read() 才有 body：直接取 .text 会抛
                            # ResponseNotRead，被下面的 except Exception 误判成「流式读取中断」
                            # 从而把 4xx 的真人话错误洗成网络抖动、白烧重试预算。
                            try:
                                body_text = resp.read().text
                            except Exception:  # noqa: BLE001
                                body_text = ""
                            err = LLMError(
                                f"API 返回 {resp.status_code}: {body_text[:500]}",
                                retryable=_status_retryable(resp.status_code))
                            last_err = err
                            _dl(f"http_{resp.status_code}", err=body_text[:500],
                                note="retryable" if err.retryable else "fatal-or-downgrade")
                            if not err.retryable:
                                fixed = self._downgrade(payload, body_text)
                                if fixed is None:
                                    self.last_error = str(err)
                                    self.last_latency = time.monotonic() - t0
                                    raise err
                                payload = fixed
                                continue   # 换参数重发（网关点名不支持），不是限流 → 立刻发
                            # W-4：429/5xx 也要退避。过去这条 continue 绕过退避睡眠，
                            # 同一份几百 k 的深栈当场再打一遍——TR 的 503 三连就是这么打死整跑的
                            _ra = getattr(resp, "headers", None).get("Retry-After") \
                                if (resp.status_code == 429
                                    and getattr(resp, "headers", None) is not None) else None
                            if attempt < self.max_retries and not self._retry_wait(
                                    attempt, abort, err, retry_after=_ra):
                                break
                            continue
                        for line in resp.iter_lines():
                            if abort is not None and abort():
                                self.last_aborted = True
                                break
                            if not line or not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            import json as _json
                            try:
                                chunk = _json.loads(data)
                            except Exception:
                                continue
                            if chunk.get("usage"):
                                stream_usage = chunk["usage"]   # include_usage 末块
                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            fr = choices[0].get("finish_reason") or ""
                            if fr:
                                # E 识别层：流式过去从不读 finish_reason；G2 截断拦截要靠它
                                self.last_finish_reason = fr
                            delta = choices[0].get("delta") or {}
                            c = delta.get("content") or ""
                            r = delta.get("reasoning_content") or ""
                            if c:
                                visible = think.push(c)   # C05：内联 <think> 段丢弃+半截标签 holdback
                                if visible:
                                    parts.append(visible)
                                    if on_chunk:
                                        _emit_to_subscriber(on_chunk, visible)
                            if r and on_reasoning:
                                _emit_to_subscriber(on_reasoning, r)
                        # 流正常收尾：holdback 扣住的尾巴按普通文本吐回；
                        # 流停在思考段内（未闭合）时 finish() 返回空串=整体丢弃
                        _tail = think.finish()
                        if _tail:
                            parts.append(_tail)
                            if on_chunk:
                                _emit_to_subscriber(on_chunk, _tail)
                if self.last_aborted:
                    # 中断优先于空内容判定：否则「点停止时还没吐字」会掉进下面的
                    # 空内容分支 continue 重开连接，把重试预算烧光。
                    # W-4：中止≠免费——末块 usage 已到就如实记一发（没到就不编）。
                    self._charge_failed_attempt(stream_usage, t0, phase, "abort")
                    _dl("abort", reply="".join(parts), usage=stream_usage)
                    stream_usage = None
                    break
                if not "".join(parts).strip():
                    # 全程无内容（或只有空白）：thinking 模式先退化重发，否则记入可重试错误
                    _fr = self.last_finish_reason
                    _hint = _finish_reason_hint(_fr)
                    last_err = LLMError("模型返回空内容 (stream%s)" % (
                        ", finish_reason=%s：%s" % (_fr, _hint) if _fr else ""), retryable=True)
                    self._charge_failed_attempt(stream_usage, t0, phase, "empty")
                    stream_usage = None
                    _dl('ok_empty', usage=stream_usage)
                    nxt, why = self._escalate_after_empty(payload, "")
                    if nxt is not None and nxt != payload:
                        # 流式全程无正文（reasoning_content 有流、content 全空＝思考吃光预算）：
                        # 与 chat 同一套按渠道能力的升级，第二次必发不同请求体，不再原样重烧。
                        logger.warning("流式返回空内容，第 %s 次降级重发：%s", attempt + 1, why)
                        self.last_degraded = True
                        payload = nxt
                        if not self._retry_wait(attempt, abort, last_err):
                            break
                        continue
                    if attempt < self.max_retries:
                        if not self._retry_wait(attempt, abort, last_err):
                            break
                        continue
                    self.last_error = str(last_err)
                    raise last_err
                self.last_latency = time.monotonic() - t0
                self._record_usage(stream_usage or {}, self.last_latency,
                                   phase=phase)   # 插件：用量统计
                _dl("ok", reply="".join(parts), usage=stream_usage)
                break
            except httpx.TimeoutException:
                last_err = LLMError("请求超时，请检查网络或增大 timeout", retryable=True)
                _dl("timeout", err=str(last_err))
            except httpx.RequestError as e:
                last_err = LLMError(f"网络错误: {e}", retryable=True)
                _dl("network", err=str(last_err))
            except LLMError as e:
                if not e.retryable:
                    _dl("error", err=str(e))
                    raise
                last_err = e
            except _SubscriberError:
                # H-7：订阅方（UI/管线）自己的 bug 原样上抛——不重试、不伪装成
                # 「流式读取中断」，原因链见 _emit_to_subscriber
                raise
            except Exception as e:
                # 流中断（连接断开等）视为可重试。返回值已按"每次尝试重置 parts"防拼接；
                # 但 on_chunk 已投递给 UI 的旧增量无法回收——UI 流式区在重试期间可能短暂
                # 显示重复尾巴，最终落盘内容以本函数返回值为准（正确）。
                last_err = LLMError(f"流式读取中断: {e}", retryable=True)
                _dl("stream_error", err=str(last_err))
            if self.last_aborted:
                # 用户主动中断：不再消耗重试预算（W-4：已到手的 usage 照样记账）
                self._charge_failed_attempt(stream_usage, t0, phase, "abort")
                stream_usage = None
                break
            if attempt < self.max_retries:
                # 网络/流中断：退避后重发（W-4 统一到 _retry_wait）
                self._charge_failed_attempt(stream_usage, t0, phase, "retry")
                stream_usage = None
                if not self._retry_wait(attempt, abort, last_err):
                    break
        content = "".join(parts).strip()
        self.last_latency = time.monotonic() - t0
        if last_err and not content:
            # 最终防线前的如实落账（重试耗尽仍无内容）；dl_done 保证本尝试不重记
            _dl("error", err=str(last_err), note="retries-exhausted")
        if self.last_aborted:
            # 已收增量交回调用方处置（core 据此抛 PipelineStopped），不当成错误
            return content
        if last_err and not content:
            self.last_error = str(last_err)
            raise last_err
        if not content:
            # 空流兜底（理论上已被循环内的退化/重试分支吃掉，保留最终防线）
            raise LLMError("模型返回空内容 (stream)", retryable=True)
        return content

    def test_connection(self) -> str:
        """测试连接，成功返回提示文本，失败抛 LLMError。

        H-8：空地址/非法协议/超时/DNS 失败四类连接错误在这里就地翻译成
        可读中文——裸 httpx 异常穿到 _NetWorker（只认 LLMError）会让新用户
        点「测试连接」直接崩掉。

        QW-A4 空模型黄牌：连接还没选模型时直接返回警告级结果（⚠ 前缀），
        不发起任何真实请求——「测试通过 ≠ 能写作」，与其让用户拿一张绿灯牌
        到第一章才撞「还没选模型」，不如点测试的当场就说清。黄牌不是红牌：
        连接配置本身没判死刑，不拦保存；桥侧按 ⚠ 前缀给琥珀级呈现（C06）。
        """
        if not (self.model or "").strip():
            return ("⚠ 这条连接还未选择模型——写作前必须选一个：到 设置 · 连接与模型 "
                    "点模型下拉选一个，或点「拉取」拿实时列表。")
        url = (self.base_url or "").strip()
        if not url:
            raise LLMError("连接失败：接口地址为空——请先填写 Base URL（如 https://api.deepseek.com）")
        if "/v1" not in url:
            url = url.rstrip("/") + "/v1"
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(f"{url}/models", headers=headers)
        except httpx.UnsupportedProtocol as e:
            scheme = url.split(":", 1)[0] if ":" in url else "(无)"
            raise LLMError(
                f"连接失败：不支持「{scheme}:」协议——地址需以 http:// 或 https:// 开头") from e
        except httpx.TimeoutException as e:
            raise LLMError("连接失败：请求超时（30 秒无响应）——请检查网络，或地址/端口是否可达") from e
        except httpx.ConnectError as e:
            if _looks_like_dns_error(e):
                raise LLMError(f"连接失败：域名解析失败（{url}）——请检查地址拼写与本机 DNS") from e
            raise LLMError(f"连接失败：无法连接到 {url}——请检查地址与端口，或服务是否在线") from e
        except httpx.RequestError as e:
            raise LLMError(f"连接失败：网络错误（{e.__class__.__name__}）——请检查网络与代理设置") from e
        if resp.status_code != 200:
            raise LLMError(f"连接失败 {resp.status_code}: {resp.text[:300]}")
        return "连接成功"

    def list_models(self) -> list:
        """拉取接口可用模型列表（OpenAI /v1/models 格式）"""
        url = self.base_url
        if "/v1" not in url:
            url = url.rstrip("/") + "/v1"
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(f"{url}/models", headers=headers)
            if resp.status_code != 200:
                raise LLMError(f"拉取失败 {resp.status_code}: {resp.text[:300]}")
            try:
                data = resp.json()
            except ValueError as e:
                # H-8：代理门户/错误页劫持时 200 + HTML——裸 JSONDecodeError 同样会穿成崩溃
                raise LLMError("拉取失败：接口返回的不是 JSON（地址可能被代理门户或错误页劫持）") from e
            models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
            return sorted(models)
        except httpx.RequestError as e:
            raise LLMError(f"网络错误: {e}")


def clean_llm_output(text: str) -> str:
    """清理 LLM 输出：内联 `<think>` 思考段（非流式路径，C05）+ markdown 代码围栏

    先剥思考段再剥围栏：`<think>` 打头会把 fence 检测顶掉，顺序反了就两头都漏。"""
    t = strip_think_blocks((text or "").strip()).strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t
