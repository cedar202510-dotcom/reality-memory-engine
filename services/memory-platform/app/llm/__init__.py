"""LLM 客户端工厂 + StageAgent 基类。

StageAgent 是严格契约化的流水线阶段（不是自治 agent 循环）：
  输入 schema 校验 → 渲染 prompt → LLM 调用 → 输出 schema 校验 → 失败重试 1 次 → 拒绝/降级。
模型永远不能直写数据库；所有写库都经过显式服务层函数。
"""
from __future__ import annotations

import json
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import get_settings
from .base import LLMClient
from .fake import FakeLLMClient
from .openai_client import OpenAICompatibleClient

InT = TypeVar("InT", bound=BaseModel)
OutT = TypeVar("OutT", bound=BaseModel)


def build_llm_client(fake: FakeLLMClient | None = None) -> LLMClient:
    """按配置构造客户端；测试/冒烟注入 FakeLLMClient。

    provider：
    - fake        → FakeLLMClient（无 API key 开箱即用）
    - kimi-coding → Kimi Code API（OpenAI 兼容，k3 只接受 temperature=1，
                    按官方文档要求带真实 User-Agent 标识）
    - openai/其它 → 任意 OpenAI 兼容端点
    """
    if fake is not None:
        return fake
    s = get_settings()
    if s.llm_provider == "fake":
        return FakeLLMClient()
    if s.llm_provider == "kimi-coding":
        return OpenAICompatibleClient(
            base_url=s.kimi_code_api_base_url or "https://api.kimi.com/coding/v1",
            api_key=s.kimi_api_key,
            vision_model=s.llm_vision_model if s.llm_vision_model != "fake-vision" else "k3",
            text_model=s.llm_text_model if s.llm_text_model != "fake-text" else "k3",
            embedding_base_url=s.embedding_base_url,
            embedding_api_key=s.embedding_api_key,
            embedding_model=s.embedding_model,
            timeout=s.llm_timeout_seconds,
            temperature=s.llm_temperature if s.llm_temperature is not None else 1.0,
            user_agent="rme-memory-platform/0.1",
            trust_env=s.llm_trust_env,
        )
    return OpenAICompatibleClient(
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        vision_model=s.llm_vision_model,
        text_model=s.llm_text_model,
        embedding_base_url=s.embedding_base_url,
        embedding_api_key=s.embedding_api_key,
        embedding_model=s.embedding_model,
        timeout=s.llm_timeout_seconds,
        temperature=s.llm_temperature if s.llm_temperature is not None else 0.0,
        trust_env=s.llm_trust_env,
    )


class StageAgent(Generic[InT, OutT]):
    """流水线阶段：严格输入/输出契约，输出不合法则重试一次后返回 None（降级/弃帧）。"""

    def __init__(
        self,
        *,
        name: str,
        task: str,
        input_model: type[InT],
        output_model: type[OutT],
        prompt_template: str,
        llm_client: LLMClient,
    ) -> None:
        self.name = name
        self.task = task
        self.input_model = input_model
        self.output_model = output_model
        self.prompt_template = prompt_template
        self.llm = llm_client

    async def run(self, input: InT, *, images: list[str] | None = None) -> OutT | None:
        input = self.input_model.model_validate(input)
        prompt = self.prompt_template.format(**input.model_dump())
        schema_hint = json.dumps(self.output_model.model_json_schema(), ensure_ascii=False)
        full_prompt = (
            f"{prompt}\n\n只输出一个 JSON 对象，必须符合此 JSON Schema：\n{schema_hint}"
        )
        for attempt in range(2):  # 首次 + 重试 1 次
            try:
                raw = await self.llm.complete_json(task=self.task, prompt=full_prompt, images=images)
                return self.output_model.model_validate(raw)
            except (ValidationError, ValueError, TypeError, KeyError):
                if attempt == 1:
                    return None
        return None
