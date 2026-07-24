"""全局配置：全部通过环境变量注入，FakeLLM 默认值保证无 API key 可跑通。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # services/memory-platform/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- 数据库 ---
    database_url: str = "postgresql+asyncpg://rme:rme@localhost:5432/rme"

    # --- 证据存储 ---
    evidence_dir: str = str(BASE_DIR / "data" / "evidence")
    evidence_ttl_minutes: int = 15          # 原始媒体 TTL，过期物理删除
    phash_hamming_threshold: int = 6        # 近 1 小时帧去重阈值
    phash_dedup_window_minutes: int = 60

    # --- LLM / VLM（OpenAI 兼容接口；provider=fake 时使用 FakeLLMClient） ---
    llm_provider: str = "fake"              # fake | openai
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_vision_model: str = "fake-vision"
    llm_text_model: str = "fake-text"
    llm_timeout_seconds: float = 60.0
    # None = 用 provider 默认（openai→0.0；kimi-coding→1.0，k3 只接受 temperature=1）
    llm_temperature: float | None = None
    # False = 直连 API，忽略系统代理/代理环境变量（本机代理不稳定时会随机连接失败）
    llm_trust_env: bool = False

    # --- Kimi Code（OpenAI 兼容；LLM_PROVIDER=kimi-coding 时使用） ---
    kimi_code_api_base_url: str = ""
    kimi_api_key: str = ""

    # --- VLM 传图预处理（原图可能 10MB+，先缩图再 base64 发送） ---
    vlm_image_max_side: int = 1024          # 长边像素上限
    vlm_image_jpeg_quality: int = 80

    # --- Embedding（可空；为空时检索降级为 pg_trgm 模糊匹配） ---
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dim: int = 1024

    # --- 视觉编码器（CLIP 跨模态；provider=none 时视觉检索整体关闭，可降级） ---
    vision_provider: str = "none"           # fake | local | http | none
    vision_base_url: str = ""               # http：CLIP sidecar 地址（边缘设备部署）
    vision_api_key: str = ""                # http：sidecar 认证（Bearer）
    vision_model: str = "ViT-B-32"          # local：open_clip 模型名
    vision_pretrained: str = "laion2b_s34b_b79k"  # local：预训练权重
    vision_prefer_hf_hub: bool = True       # local：False 时权重走直链缓存（HF 慢/不可达时）
    vision_dim: int = 512                   # 视觉向量维度（须与 frame_assets.visual_embedding 一致）
    vision_timeout_seconds: float = 30.0    # http：sidecar 请求超时

    # --- ASR 语音转写（provider=none 时语音流水线整体关闭，音频证据仅落盘+TTL） ---
    asr_provider: str = "none"              # fake | http | none
    asr_base_url: str = ""                  # http：ASR sidecar 地址（如 faster-whisper 服务）
    asr_api_key: str = ""                   # http：sidecar 认证（Bearer）
    asr_timeout_seconds: float = 60.0       # http：sidecar 请求超时（音频转写较慢）

    # --- 候选门 ---
    candidate_accept_threshold: float = 0.85

    # --- 实体解析（物体级合并） ---
    # 视觉辅助合并：帧 CLIP 向量与实体代表向量 cosine ≥ 阈值 且 名称 trgm ≥ 低门槛 才合并。
    # 名称低门槛是必须的：同一帧里有多个物体，纯视觉匹配会把"笔记本"错并进"手机"。
    resolver_visual_merge_threshold: float = 0.80
    resolver_name_low_bar: float = 0.25

    # --- 检索 ---
    retrieval_top_k: int = 8
    retrieval_visual_top_k: int = 8         # 视觉路召回数量（融合前）
    retrieval_fusion_visual_weight: float = 0.6  # 多路融合中视觉路权重（视觉优先）
    retrieval_fusion_transcript_weight: float = 0.5  # 多路融合中语音转写路权重
    # CLIP 文本塔为英文模型：含中文的查询先翻译成英文短语，再与原文向量取均值
    clip_query_translate: bool = True
    # 通道 2 倒序早停验证：召回后按时间从新到旧分批 VLM 验证，命中即停
    retrieval_verify_batch_size: int = 2    # 每批验证帧数（也是每批附图上限）
    retrieval_verify_max_batches: int = 3   # 最多验证批数（超过转为未找到）
    retrieval_verify_min_confidence: float = 0.5  # 达到该置信度即早停采纳

    # --- Worker ---
    worker_poll_interval_seconds: float = 1.0
    worker_batch_size: int = 10
    worker_concurrency: int = 4             # 帧/音频感知任务批内并发数（projection 仍串行）
    outbox_max_attempts: int = 3            # 单条 outbox 失败重试上限，超限标记消费+审计
    outbox_retry_backoff_seconds: float = 20.0  # 每次失败后的重试退避（× attempts）
    ttl_sweep_interval_seconds: float = 60.0

    # --- 演示/测试用 Fake 行为由调用方注入，不在配置里 ---


@lru_cache
def get_settings() -> Settings:
    return Settings()
