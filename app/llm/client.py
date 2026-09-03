# -*- coding: utf-8 -*-
"""LLM 统一调用客户端：OpenAI 兼容接口（分级重试 / 超时 / 输出清洗）

重试策略：
- 可重试：网络错误 / 超时 / HTTP 429 / 5xx（指数退避，最多 max_retries 次）
- 不可重试：4xx 其余错误 / 响应格式异常（立即抛出，不浪费重试）
"""
import logging
import time

import httpx

logger = logging.getLogger("qianbi.llm")


class LLMError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable  # 是否属于可重试错误


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
                    "frequency_penalty", "max_tokens")
# 值存在才进请求体的采样参数：无预设时请求体逐字不变（不凭空多出 "top_p": null）
OPTIONAL_PARAM_KEYS = ("top_p", "presence_penalty", "frequency_penalty")
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


class LLMClient:
    """单连接配置对应的调用客户端（无状态，可反复使用）"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.7, max_tokens: int = 8192, timeout: int = 300,
                 max_retries: int = 2, backoff_base: float = 2.0, thinking: str = "",
                 reasoning_effort: str = "", slot: str = "",
                 payload_defaults: dict = None, stage_params: dict = None):
        self.slot = slot or ""   # 槽位标签（token 用量统计维度，插件）
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model
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

    @classmethod
    def from_connection(cls, conn: dict, max_retries: int = 2,
                        backoff_base: float = 2.0, slot: str = "",
                        payload_defaults: dict = None,
                        stage_params: dict = None) -> "LLMClient":
        return cls(
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
        )

    def _record_usage(self, usage: dict, latency: float):
        """token 用量统计埋点（插件）：本地 jsonl + 内存聚合，失败不影响调用"""
        try:
            tin = int(usage.get("prompt_tokens", 0) or 0)
            tout = int(usage.get("completion_tokens", 0) or 0)
            if tin <= 0 and tout <= 0:
                return
            self.total_prompt_tokens += tin
            self.total_completion_tokens += tout
            from .. import usage as _usage
            _usage.record(None, self.model, self.slot, tin, tout, latency)
        except Exception as e:  # noqa: BLE001
            logger.debug("用量埋点失败（忽略）: %s", e)

    def _chat_url(self) -> str:
        if "/v1" in self.base_url:
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
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

        认不出可剥参数时返回 None，调用方按原样抛错——参数降级不能变成吞错误的面子工程。
        """
        low = (err_text or "").lower()
        rejected = [p for p in _UNSUPPORTED_HINT_KEYS if p in payload and p in low]
        if not rejected:
            return None
        if len(_UNSUPPORTED) > 64:
            _UNSUPPORTED.clear()   # 备忘录只做加速，不长期吃内存（换连接配置后旧键无意义）
        _UNSUPPORTED.setdefault(self._memo_key(), set()).update(rejected)
        self.last_degraded = True
        for k in rejected:
            self.last_sampling.pop(k, None)   # 快照不能留「其实没下发」的参数
        logger.warning("模型 %s 不支持 %s，本进程内不再下发", self.model, "/".join(rejected))
        return {k: v for k, v in payload.items() if k not in rejected}

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
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self._resolve("temperature", temperature, over),
            "max_tokens": self._resolve("max_tokens", max_tokens, over),
            "stream": stream,
        }
        for key in OPTIONAL_PARAM_KEYS:   # 无配置时不下发：请求体与改造前逐字一致
            val = self._resolve(key, None, over)
            if val is not None:
                payload[key] = val
        if stream:
            payload["stream_options"] = {"include_usage": True}   # 末 chunk 携带 usage（用量统计）
        if thinking:
            payload["thinking"] = {"type": thinking}
            effort = self._resolve("reasoning_effort", reasoning_effort, over)
            if thinking == "enabled" and effort:
                # DeepSeek V4 顶层参数：思考强度 low/high/max（参考 DeepSeek 官方 Thinking Mode
                # 文档与 opencode-go provider 的 effort 映射；max 为最高档）
                payload["reasoning_effort"] = effort
        payload = self._apply_capability(payload)
        # 备忘录剥掉的参数不登记：快照要记「真正会下发的」，而不是「我以为下发了的」
        self.last_sampling = {k: payload[k] for k in SAMPLING_TRACE_KEYS if k in payload}
        return payload

    def chat(self, prompt: str, system: str = "", temperature: float = None,
             *, phase: str = "") -> str:
        """单轮对话，分级重试（网络/超时/429/5xx 指数退避），返回文本内容"""
        self.last_prompt = prompt
        self.last_error = ""
        self.last_phase = phase or ""
        self.last_degraded = False
        headers = self._headers()
        messages = self._build_messages(prompt, system)
        payload = self._build_payload(messages, stream=False, phase=phase,
                                      temperature=temperature)
        t0 = time.monotonic()
        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(self._chat_url(), json=payload, headers=headers)
                if resp.status_code != 200:
                    err = LLMError(
                        f"API 返回 {resp.status_code}: {resp.text[:500]}",
                        retryable=_status_retryable(resp.status_code))
                    if err.retryable:
                        last_err = err
                    else:
                        # 网关明确点名「不支持某参数」：剥掉它（记入能力备忘录）再发一次；
                        # 认不出可剥参数照原样抛出——降级不许把真错误吞成静默重试。
                        fixed = self._downgrade(payload, resp.text)
                        if fixed is None:
                            self.last_error = str(err)
                            self.last_latency = time.monotonic() - t0
                            raise err
                        payload = fixed
                        last_err = err
                else:
                    data = resp.json()
                    content = ""
                    try:
                        content = data["choices"][0]["message"]["content"] or ""
                    except (KeyError, IndexError):
                        pass
                    if not content:
                        # HTTP 200 但内容为空：服务端生成中断/超限，可重试
                        finish = ""
                        try:
                            finish = data["choices"][0].get("finish_reason") or ""
                        except (KeyError, IndexError):
                            pass
                        last_err = LLMError(
                            f"模型返回空内容 (finish_reason={finish})", retryable=True)
                        if payload.get("thinking") and not self.last_degraded:
                            # thinking 模式偶发"只思考不输出"：本次调用内关闭 thinking 重发
                            # （退化标记至多触发一次，不再递归重开一整轮重试预算）
                            logger.warning(
                                "模型返回空内容(finish_reason=%s)，降级重发（关闭 thinking）", finish)
                            self.last_degraded = True
                            payload = self._build_payload(
                                messages, stream=False, phase=phase,
                                temperature=temperature, thinking="", reasoning_effort="")
                            continue
                        if attempt < self.max_retries:
                            continue
                        raise last_err
                    usage = data.get("usage") or {}
                    self.last_latency = time.monotonic() - t0
                    self._record_usage(usage, self.last_latency)
                    logger.info("LLM ok model=%s prompt_tokens=%s completion_tokens=%s latency=%.1fs",
                                self.model, usage.get("prompt_tokens", 0),
                                usage.get("completion_tokens", 0), self.last_latency)
                    return content.strip()
            except httpx.TimeoutException:
                last_err = LLMError("请求超时，请检查网络或增大 timeout", retryable=True)
            except httpx.RequestError as e:
                last_err = LLMError(f"网络错误: {e}", retryable=True)
            except (KeyError, IndexError) as e:
                last_err = LLMError(f"API 响应格式异常: {e}", retryable=False)
            except LLMError as e:
                if not e.retryable:
                    raise
                last_err = e
            if attempt < self.max_retries:
                delay = self.backoff_base * (2 ** attempt)
                logger.warning("LLM retry %s/%s after %.1fs: %s",
                               attempt + 1, self.max_retries, delay, last_err)
                time.sleep(delay)
        self.last_error = str(last_err)
        self.last_latency = time.monotonic() - t0
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
        self.last_aborted = False
        self.last_prompt = prompt
        self.last_error = ""
        self.last_phase = phase or ""
        self.last_degraded = False
        headers = self._headers()
        messages = self._build_messages(prompt, system)
        payload = self._build_payload(messages, stream=True, phase=phase,
                                      temperature=temperature)

        t0 = time.monotonic()
        last_err = None
        for attempt in range(self.max_retries + 1):
            parts = []   # 每次尝试重置：断流重试不得拼接两次的部分内容
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
                            if not err.retryable:
                                fixed = self._downgrade(payload, body_text)
                                if fixed is None:
                                    self.last_error = str(err)
                                    self.last_latency = time.monotonic() - t0
                                    raise err
                                payload = fixed
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
                            delta = choices[0].get("delta") or {}
                            c = delta.get("content") or ""
                            r = delta.get("reasoning_content") or ""
                            if c:
                                parts.append(c)
                                if on_chunk:
                                    on_chunk(c)
                            if r and on_reasoning:
                                on_reasoning(r)
                if self.last_aborted:
                    # 中断优先于空内容判定：否则「点停止时还没吐字」会掉进下面的
                    # 空内容分支 continue 重开连接，把重试预算烧光。
                    break
                if not "".join(parts).strip():
                    # 全程无内容（或只有空白）：thinking 模式先退化重发，否则记入可重试错误
                    last_err = LLMError("模型返回空内容 (stream)", retryable=True)
                    if payload.get("thinking") and not self.last_degraded:
                        # thinking 偶发"只思考不输出"（reasoning_content 有流、content 全空）：
                        # 本次调用内关闭 thinking 重发（退化标记至多一次，不再递归重开重试预算）
                        logger.warning("流式返回空内容，降级重发（关闭 thinking）")
                        self.last_degraded = True
                        payload = self._build_payload(
                            messages, stream=True, phase=phase, temperature=temperature,
                            thinking="", reasoning_effort="")
                        continue
                    if attempt < self.max_retries:
                        continue
                    self.last_error = str(last_err)
                    raise last_err
                self.last_latency = time.monotonic() - t0
                self._record_usage(stream_usage or {}, self.last_latency)   # 插件：用量统计
                break
            except httpx.TimeoutException:
                last_err = LLMError("请求超时，请检查网络或增大 timeout", retryable=True)
            except httpx.RequestError as e:
                last_err = LLMError(f"网络错误: {e}", retryable=True)
            except LLMError as e:
                if not e.retryable:
                    raise
                last_err = e
            except Exception as e:
                # 流中断（连接断开等）视为可重试。返回值已按"每次尝试重置 parts"防拼接；
                # 但 on_chunk 已投递给 UI 的旧增量无法回收——UI 流式区在重试期间可能短暂
                # 显示重复尾巴，最终落盘内容以本函数返回值为准（正确）。
                last_err = LLMError(f"流式读取中断: {e}", retryable=True)
            if self.last_aborted:
                break   # 用户主动中断：不再消耗重试预算
            if attempt < self.max_retries:
                delay = self.backoff_base * (2 ** attempt)
                logger.warning("LLM stream retry %s/%s after %.1fs: %s",
                               attempt + 1, self.max_retries, delay, last_err)
                if abort is None:
                    time.sleep(delay)
                else:   # 退避等待也要可中断：否则点停止后还要白等数秒
                    _end = time.monotonic() + delay
                    while time.monotonic() < _end:
                        if abort():
                            self.last_aborted = True
                            break
                        time.sleep(0.1)
                    if self.last_aborted:
                        break
        content = "".join(parts).strip()
        self.last_latency = time.monotonic() - t0
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
        """测试连接，成功返回提示文本，失败抛 LLMError"""
        url = self.base_url
        if "/v1" not in url:
            url = url.rstrip("/") + "/v1"
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{url}/models", headers=headers)
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
            data = resp.json()
            models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
            return sorted(models)
        except httpx.RequestError as e:
            raise LLMError(f"网络错误: {e}")


def clean_llm_output(text: str) -> str:
    """清理 LLM 输出的 markdown 代码围栏"""
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t
