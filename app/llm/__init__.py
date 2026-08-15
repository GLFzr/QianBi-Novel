# -*- coding: utf-8 -*-
"""LLM 接入层：providers（服务商预设）/ client（统一调用）/ router（槽位路由）"""
from .client import LLMClient, LLMError, clean_llm_output, check_base_url
from .router import ModelRouter
from . import providers

__all__ = ["LLMClient", "LLMError", "clean_llm_output", "check_base_url",
           "ModelRouter", "providers"]
