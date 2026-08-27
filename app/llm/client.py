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


class LLMClient:
    """单连接配置对应的调用客户端（无状态，可反复使用）"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.7, max_tokens: int = 8192, timeout: int = 300,
                 max_retries: int = 2, backoff_base: float = 2.0, thinking: str = "",
                 reasoning_effort: str = ""):
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
        # 调用统计
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        # 最近一次请求现场（诊断/失败 dump 用）
        self.last_prompt = ""
        self.last_error = ""
        self.last_latency = 0.0

    @classmethod
    def from_connection(cls, conn: dict, max_retries: int = 2,
                        backoff_base: float = 2.0) -> "LLMClient":
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
        )

    def _chat_url(self) -> str:
        if "/v1" in self.base_url:
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def chat(self, prompt: str, system: str = "", temperature: float = None) -> str:
        """单轮对话，分级重试（网络/超时/429/5xx 指数退避），返回文本内容"""
        self.last_prompt = prompt
        self.last_error = ""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self.thinking:
            payload["thinking"] = {"type": self.thinking}
        if self.thinking == "enabled" and self.reasoning_effort:
            # DeepSeek V4 顶层参数：思考强度 low/high/max（参考 DeepSeek 官方 Thinking Mode 文档
            # 与 opencode-go provider 的 effort 映射；max 为最高档）
            payload["reasoning_effort"] = self.reasoning_effort
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
                    if not err.retryable:
                        self.last_error = str(err)
                        self.last_latency = time.monotonic() - t0
                        raise err
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
                        if self.thinking:
                            # thinking 模式偶发"只思考不输出"：关闭 thinking 降级重试一次
                            logger.warning(
                                "模型返回空内容(finish_reason=%s)，降级重试（关闭 thinking）", finish)
                            saved_t, saved_e = self.thinking, self.reasoning_effort
                            self.thinking = None
                            self.reasoning_effort = None
                            try:
                                return self.chat(prompt, system, temperature)
                            finally:
                                self.thinking, self.reasoning_effort = saved_t, saved_e
                        if attempt < self.max_retries:
                            last_err = LLMError(
                                f"模型返回空内容 (finish_reason={finish})", retryable=True)
                            continue
                        raise LLMError(f"模型返回空内容 (finish_reason={finish})")
                    usage = data.get("usage") or {}
                    self.total_prompt_tokens += usage.get("prompt_tokens", 0)
                    self.total_completion_tokens += usage.get("completion_tokens", 0)
                    self.last_latency = time.monotonic() - t0
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
                    on_chunk=None, on_reasoning=None) -> str:
        """流式单轮对话：stream=true 逐块回调（on_chunk 收到增量文本），返回完整文本。

        回调约定：
          on_chunk(text)      —— 内容增量
          on_reasoning(text)  —— 推理内容增量（DeepSeek 思考模式，可选）
        重试/错误语义与 chat() 一致；失败时已回调的增量不回收（UI 按现场处理）。
        """
        self.last_prompt = prompt
        self.last_error = ""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if self.thinking:
            payload["thinking"] = {"type": self.thinking}
        if self.thinking == "enabled" and self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort

        t0 = time.monotonic()
        last_err = None
        parts = []
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    with client.stream("POST", self._chat_url(), json=payload, headers=headers) as resp:
                        if resp.status_code != 200:
                            err = LLMError(
                                f"API 返回 {resp.status_code}: {resp.text[:500]}",
                                retryable=_status_retryable(resp.status_code))
                            if not err.retryable:
                                self.last_error = str(err)
                                self.last_latency = time.monotonic() - t0
                                raise err
                            last_err = err
                            continue
                        for line in resp.iter_lines():
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
                usage = getattr(resp, "_usage", None) if False else None
                # stream 模式 usage 通常在最后一块；未能解析也不影响
                if not parts:
                    # 流式全程无内容：thinking 模式先降级重试；否则记入可重试错误
                    if self.thinking:
                        logger.warning("流式返回空内容，降级重试（关闭 thinking）")
                        saved_t, saved_e = self.thinking, self.reasoning_effort
                        self.thinking = None
                        self.reasoning_effort = None
                        try:
                            return self.chat_stream(prompt, system, temperature,
                                                    on_chunk=on_chunk, on_reasoning=on_reasoning)
                        finally:
                            self.thinking, self.reasoning_effort = saved_t, saved_e
                    last_err = LLMError("模型返回空内容 (stream)", retryable=True)
                    continue
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
                # 流中断（连接断开等）视为可重试，但已产生的增量不回收
                last_err = LLMError(f"流式读取中断: {e}", retryable=True)
            if attempt < self.max_retries:
                delay = self.backoff_base * (2 ** attempt)
                logger.warning("LLM stream retry %s/%s after %.1fs: %s",
                               attempt + 1, self.max_retries, delay, last_err)
                time.sleep(delay)
        content = "".join(parts).strip()
        self.last_latency = time.monotonic() - t0
        if last_err and not content:
            self.last_error = str(last_err)
            raise last_err
        if not content and not last_err:
            if self.thinking:
                # thinking 模式偶发"只思考不输出"（reasoning_content 有流、content 全空）：
                # 关闭 thinking 降级重试一次
                logger.warning("流式返回空内容，降级重试（关闭 thinking）")
                saved_t, saved_e = self.thinking, self.reasoning_effort
                self.thinking = None
                self.reasoning_effort = None
                try:
                    return self.chat_stream(prompt, system, temperature,
                                            on_chunk=on_chunk, on_reasoning=on_reasoning)
                finally:
                    self.thinking, self.reasoning_effort = saved_t, saved_e
            # 空流（服务端生成为空/中断）：非 thinking 时也允许在重试预算内重试一次，
            # 避免偶发空流直接中断整条流水线
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
