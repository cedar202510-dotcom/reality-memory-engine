"""agent-gateway 配置：全部环境变量注入。

关键边界：本服务只持有 MEMORY_AGENT_TOKEN（受限 AgentGrant token），
通过 HTTP 契约访问记忆平台；绝不直连平台数据库、绝不 import 平台内部模块。
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- 记忆平台（唯一数据来源） ---
    memory_base_url: str = "http://localhost:8000"
    memory_agent_token: str = ""            # AgentGrant token（POST /v1/agent/grants 签发）
    memory_timeout_seconds: float = 60.0

    # --- 对话 LLM（需支持 OpenAI tools 协议；provider=fake 用于测试） ---
    llm_provider: str = "fake"              # fake | openai | kimi-coding
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "fake-chat"
    llm_timeout_seconds: float = 60.0
    llm_temperature: float | None = None    # None = provider 默认
    llm_trust_env: bool = False

    # --- Harness ---
    max_tool_turns: int = 6                 # 单次用户消息内最多工具循环轮数（超限降级作答）
    session_ttl_minutes: int = 30           # 会话内存态 TTL（§12：不长期保存查询结果）
    max_sessions: int = 1000

    # --- 主动式 ---
    proactive_llm_wording: bool = False     # False = 确定性模板措辞（可测试）；True = LLM 润色

    # --- 眼镜结果投递 ---
    # 默认关闭，避免 Web/手机端对话在没有明确路由时突然打断眼镜用户。请求体显式传
    # delivery 时不受此开关影响；本地整链联调可打开并配置默认眼镜。
    glasses_auto_delivery_enabled: bool = False
    glasses_default_device_id: str = ""
    glasses_default_allow_tts: bool = False
    glasses_answer_ttl_seconds: int = 90
    glasses_reminder_ttl_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
