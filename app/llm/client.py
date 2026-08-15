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
                 max_retries: int = 2, backoff_base: float = 2.0, thinking: str = ""):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.thinking = thinking or ""   # "disabled"/"enabled"：DeepSeek 系网关的思考开关
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
