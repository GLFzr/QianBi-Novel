# -*- coding: utf-8 -*-
"""本机推理服务端点（Ollama / llama.cpp / LM Studio / vLLM / KoboldCpp / text-gen-webui）。

为什么单独一层：本机服务与云端网关有三个结构性差异——
1. **没有 Key**：免 Key 判定必须是「地址是不是回环」而不是「用户忘没忘填」；
2. **端口各家不同**：11434/8080/1234/8000/5001/5000，让用户背端口就是劝退；
3. **地址常缺协议头**：`127.0.0.1:11434` 直接交给 httpx 会当畸形 URL，
   远端地址则**不能**替用户猜协议（猜错把 https 变明文）。

本模块只做纯函数与一次探测；网络调用可注入 `get(url, timeout) -> (status, text)`，
单测不碰真端口。所有请求 `trust_env=False`，避免系统代理把本机请求劫走。
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

import httpx

# 服务清单：port 是出厂端口；native 是 OpenAI 兼容层不可用时的原生模型列表路径
LOCAL_SERVICES = (
    {"key": "local-ollama", "label": "Ollama", "port": 11434, "native": "/api/tags"},
    {"key": "local-llamacpp", "label": "llama.cpp", "port": 8080, "native": ""},
    {"key": "local-lmstudio", "label": "LM Studio", "port": 1234, "native": ""},
    {"key": "local-vllm", "label": "vLLM", "port": 8000, "native": ""},
    {"key": "local-koboldcpp", "label": "KoboldCpp", "port": 5001, "native": ""},
    {"key": "local-textgen", "label": "text-generation-webui", "port": 5000, "native": ""},
)

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "::"})
_BARE_LOCAL_RE = re.compile(
    r"^(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|::1)(?::\d{1,5})?(?:[/?#].*)?$",
    re.IGNORECASE)


def service_for_port(port: int):
    for svc in LOCAL_SERVICES:
        if svc["port"] == int(port):
            return svc
    return None


def label_for_port(port: int) -> str:
    svc = service_for_port(port)
    return svc["label"] if svc else "本地服务"


def _host_of(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "http://" + u
    try:
        return (httpx.URL(u).host or "").lower()
    except Exception:  # noqa: BLE001  畸形 URL 一律当非本地
        return ""


def is_local_host(host: str) -> bool:
    h = (host or "").strip().lower().strip("[]")
    return h in _LOOPBACK_HOSTS or h.endswith(".localhost")


def is_local_base_url(url: str) -> bool:
    """是否为回环地址（含无协议头写法）。远端伪装域名不算。

    只认 http（或无协议头→按 http）：https 指向回环是极罕见配置，且证书必然对不上，
    按远端处理能保住「必须填 Key」的既有语义与错误话术。
    """
    u = (url or "").strip()
    if not u:
        return False
    if "://" in u and u.split("://", 1)[0].strip().lower() != "http":
        return False
    return is_local_host(_host_of(u))


def normalize_local_url(text: str) -> str:
    """给无协议头的**回环**地址补 http://；远端地址原样返回（不猜协议）。"""
    u = (text or "").strip()
    if not u or "://" in u:
        return u
    if _BARE_LOCAL_RE.match(u):
        return "http://" + u
    return u


def needs_api_key(conn: dict) -> bool:
    """该连接是否必须填 Key：本地回环免 Key，远端一律要。"""
    conn = conn or {}
    if str(conn.get("api_key") or "").strip():
        return False
    return not is_local_base_url(str(conn.get("base_url") or ""))


def sanitize_proxy_env(env=None) -> None:
    """剥掉 NO_PROXY 里的 IPv6 字面量（httpx 0.28 解析 `::1`/`[::1]` 会抛 InvalidURL）。

    这不是洁癖：Windows 上 `NO_PROXY=localhost,127.0.0.1,::1,[::1]` 是常见写法，
    httpx 0.28 会把 `::1` 当 host:port 切出 `:1]`，于是**所有**远端请求在建 Client
    时就炸（本机实测）。远端 NO_PROXY 里的回环条目对远端域名本就没有意义，删掉安全；
    本地端点反正走 trust_env=False。
    """
    target = os.environ if env is None else env
    for key in ("NO_PROXY", "no_proxy"):
        raw = target.get(key)
        if not raw:
            continue
        kept = []
        for part in raw.split(","):
            item = part.strip()
            if not item:
                continue
            if "[" in item or "]" in item or item.count(":") >= 2:
                continue     # IPv6 字面量：httpx 解析不了，且与本机直连无关
            kept.append(item)
        target[key] = ",".join(kept)


def parse_openai_models(payload) -> list:
    """OpenAI /v1/models → 排序去重的 id 列表（坏形状返回空表）。"""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    ids = set()
    for item in data:
        if isinstance(item, dict):
            mid = str(item.get("id") or "").strip()
            if mid:
                ids.add(mid)
    return sorted(ids)


def parse_ollama_tags(payload) -> list:
    """Ollama /api/tags → name 列表（该接口用的是 name 而不是 id）。"""
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    names = set()
    for item in models:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if name:
                names.add(name)
    return sorted(names)


def _loads(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _default_get(url: str, timeout: float):
    # trust_env=False：本机请求绝不能被系统代理/NO_PROXY 的畸形值劫走
    resp = httpx.get(url, timeout=timeout, trust_env=False)
    return resp.status_code, resp.text


def _try_models(get, url: str, timeout: float, parser):
    try:
        status, text = get(url, timeout)
    except Exception:  # noqa: BLE001  连接拒绝/超时/协议错都只是「没这个服务」
        return None
    if status != 200:
        return None
    payload = _loads(text)
    if payload is None:
        return None
    return parser(payload)


def probe_service(port: int, timeout: float = 0.6, get=None, host: str = "127.0.0.1"):
    """探测一个本机端口；在跑则返回 {port, base_url, service, models, count}，否则 None。

    先走 OpenAI 兼容 /v1/models；Ollama 在旧版本/关闭兼容层时回退原生 /api/tags。
    200 + 空列表也算「在跑」（服务起来了但还没拉模型），由调用方给人话提示。
    """
    get = get or _default_get
    base = "http://%s:%d" % (host, int(port))
    models = _try_models(get, base + "/v1/models", timeout, parse_openai_models)
    if models is not None:
        return {"port": int(port), "base_url": base, "service": label_for_port(port),
                "models": models, "count": len(models)}
    svc = service_for_port(port)
    if svc and svc.get("native"):
        models = _try_models(get, base + svc["native"], timeout, parse_ollama_tags)
        if models is not None:
            return {"port": int(port), "base_url": base, "service": svc["label"],
                    "models": models, "count": len(models)}
    return None


def scan_ports(timeout: float = 0.6, ports=None, probe=None, host: str = "127.0.0.1") -> list:
    """并发扫一遍本机常用端口，返回在跑的服务（按端口升序）。

    probe(port) 可注入以便离线测试；异常一律当「没这个服务」，扫描本身绝不抛。
    """
    targets = list(ports) if ports is not None else [s["port"] for s in LOCAL_SERVICES]
    if not targets:
        return []

    def _one(port):
        try:
            if probe is not None:
                return probe(port)
            return probe_service(port, timeout=timeout, host=host)
        except Exception:  # noqa: BLE001
            return None

    with ThreadPoolExecutor(max_workers=max(1, min(8, len(targets)))) as pool:
        hits = [h for h in pool.map(_one, targets) if h]
    hits.sort(key=lambda h: int(h.get("port") or 0))
    return hits
