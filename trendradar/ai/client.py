# coding=utf-8
"""
AI 客户端模块

基于 LiteLLM 的统一 AI 模型接口
支持 100+ AI 提供商（OpenAI、DeepSeek、Gemini、Claude、国内模型等）
"""

import os
from typing import Any, Dict, List

from litellm import completion


class AIClient:
    """统一的 AI 客户端（基于 LiteLLM）"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 AI 客户端

        Args:
            config: AI 配置字典
                - MODEL: 模型标识（格式: provider/model_name）
                - API_KEY: API 密钥
                - API_BASE: API 基础 URL（可选）
                - TEMPERATURE: 采样温度
                - MAX_TOKENS: 最大生成 token 数
                - TIMEOUT: 请求超时时间（秒）
                - NUM_RETRIES: 重试次数（可选）
                - FALLBACK_MODELS: 备用模型列表（可选）
                - EXTRA_PARAMS: 透传给 LiteLLM 的额外参数（可选）
        """
        self.model = config.get("MODEL", "deepseek/deepseek-chat")
        self.api_key = config.get("API_KEY") or os.environ.get("AI_API_KEY", "")
        self.api_base = config.get("API_BASE", "")
        self.temperature = config.get("TEMPERATURE", 1.0)
        self.max_tokens = config.get("MAX_TOKENS", 5000)
        self.timeout = config.get("TIMEOUT", 120)
        self.num_retries = config.get("NUM_RETRIES", 2)
        self.fallback_models = config.get("FALLBACK_MODELS", [])
        configured_extra = config.get("EXTRA_PARAMS", {})
        self.extra_params = dict(configured_extra) if isinstance(configured_extra, dict) else {}
        # chat() 仍返回 str 以兼容既有调用方；完整的结束原因和用量保存在这里。
        self.last_response_metadata: Dict[str, Any] = {}

    @staticmethod
    def _response_value(response: Any, key: str, default: Any = None) -> Any:
        if isinstance(response, dict):
            return response.get(key, default)
        return getattr(response, key, default)

    @staticmethod
    def _plain_mapping(value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        for method_name in ("model_dump", "dict"):
            method = getattr(value, method_name, None)
            if callable(method):
                try:
                    dumped = method()
                    if isinstance(dumped, dict):
                        return dumped
                except Exception:
                    pass
        result: Dict[str, Any] = {}
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "thoughts_token_count",
            "reasoning_tokens",
        ):
            item = getattr(value, key, None)
            if item is not None:
                result[key] = item
        return result

    def chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> str:
        """
        调用 AI 模型进行对话

        Args:
            messages: 消息列表，格式: [{"role": "system/user/assistant", "content": "..."}]
            **kwargs: 额外参数，会覆盖默认配置

        Returns:
            str: AI 响应内容

        Raises:
            Exception: API 调用失败时抛出异常
        """
        self.last_response_metadata = {}

        # EXTRA_PARAMS 先作为基底；明确的客户端配置和单次 kwargs 具有更高优先级。
        params: Dict[str, Any] = dict(self.extra_params)
        params.update({
            "model": self.model,
            "messages": messages,
            "timeout": kwargs.get("timeout", self.timeout),
            "num_retries": kwargs.get("num_retries", self.num_retries),
        })

        temperature = kwargs.get("temperature", self.temperature)
        if temperature is not None:
            params["temperature"] = temperature

        # 添加 API Key
        if self.api_key:
            params["api_key"] = self.api_key

        # 添加 API Base（如果配置了）
        if self.api_base:
            params["api_base"] = self.api_base

        # 添加 max_tokens（如果配置了且不为 0）
        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        if max_tokens and max_tokens > 0:
            params["max_tokens"] = max_tokens

        # 添加 fallback 模型（如果配置了）
        if self.fallback_models:
            params["fallbacks"] = self.fallback_models

        # 合并其他额外参数
        consumed = {"temperature", "timeout", "num_retries", "max_tokens"}
        for key, value in kwargs.items():
            if key not in consumed:
                params[key] = value

        # 调用 LiteLLM
        response = completion(**params)

        # 提取响应内容
        # 某些模型/提供商返回 list（内容块）而非 str，统一转为 str
        choices = self._response_value(response, "choices", []) or []
        if not choices:
            raise ValueError("AI 响应缺少 choices")
        choice = choices[0]
        message = self._response_value(choice, "message", {})
        content = self._response_value(message, "content", "")
        if isinstance(content, list):
            content = "\n".join(
                item.get("text", str(item)) if isinstance(item, dict) else str(item)
                for item in content
            )

        finish_reason = self._response_value(choice, "finish_reason", "")
        if hasattr(finish_reason, "value"):
            finish_reason = finish_reason.value
        usage = self._plain_mapping(self._response_value(response, "usage"))
        self.last_response_metadata = {
            "finish_reason": str(finish_reason or "").upper(),
            "usage": usage,
            "model": str(self._response_value(response, "model", self.model) or self.model),
            "response_id": str(self._response_value(response, "id", "") or ""),
        }
        return content or ""

    def validate_config(self) -> tuple[bool, str]:
        """
        验证配置是否有效

        Returns:
            tuple: (是否有效, 错误信息)
        """
        if not self.model:
            return False, "未配置 AI 模型（model）"

        if not self.api_key:
            return False, "未配置 AI API Key，请在 config.yaml 或环境变量 AI_API_KEY 中设置"

        # 验证模型格式（应该包含 provider/model）
        if "/" not in self.model:
            return False, f"模型格式错误: {self.model}，应为 'provider/model' 格式（如 'deepseek/deepseek-chat'）"

        return True, ""
