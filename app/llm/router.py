# -*- coding: utf-8 -*-
"""任务槽位路由：写作槽 / 辅助槽 / 审校槽 → 各自连接对应的 LLMClient"""
from .. import config as cfg_mod
from .client import LLMClient


class ModelRouter:
    """按槽位分发 LLMClient；共享底层配置，调用统计聚合"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._clients = {}

    def client(self, slot: str) -> LLMClient:
        if slot not in self._clients:
            conn = cfg_mod.slot_connection(self.cfg, slot)
            if not conn:
                from .client import LLMError
                raise LLMError(f"槽位 {cfg_mod.SLOT_LABELS.get(slot, slot)} 未绑定任何连接")
            llm_cfg = self.cfg.get("llm", {})
            self._clients[slot] = LLMClient.from_connection(
                conn,
                max_retries=llm_cfg.get("max_retries", 2),
                backoff_base=llm_cfg.get("backoff_base", 2.0),
            )
        return self._clients[slot]

    def invalidate(self):
        """配置变更后调用，丢弃缓存客户端"""
        self._clients.clear()

    def slot_model_name(self, slot: str) -> str:
        conn = cfg_mod.slot_connection(self.cfg, slot)
        return conn.get("model", "") if conn else ""

    def slot_display(self, slot: str) -> str:
        conn = cfg_mod.slot_connection(self.cfg, slot)
        if not conn:
            return "未配置"
        return f"{conn.get('name', '')} · {conn.get('model', '')}"

    def any_api_key_missing(self) -> bool:
        """任一已绑定连接的 api_key 为空（本地接口除外）"""
        for slot in cfg_mod.SLOT_ORDER:
            conn = cfg_mod.slot_connection(self.cfg, slot)
            if not conn:
                return True
            url = conn.get("base_url", "")
            if not conn.get("api_key") and "localhost" not in url and "127.0.0.1" not in url:
                return True
        return False

    def total_tokens(self) -> int:
        return sum(c.total_prompt_tokens + c.total_completion_tokens for c in self._clients.values())

    def estimate_cost(self) -> float:
        """粗估成本（元）：按 DeepSeek 官方价位加权，仅作体感参考"""
        cost = 0.0
        for client in self._clients.values():
            model = (client.model or "").lower()
            if "flash" in model or "mini" in model:
                in_rate, out_rate = 1.0, 2.0  # 元/百万 tokens 量级
            else:
                in_rate, out_rate = 2.0, 8.0
            cost += client.total_prompt_tokens / 1e6 * in_rate
            cost += client.total_completion_tokens / 1e6 * out_rate
        return cost
