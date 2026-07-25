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

    # --- 图像入库归一化（HEIC/HEIF → JPEG；JPEG/PNG 等原样透传不重编码） ---
    image_normalize_jpeg_quality: int = 90
    image_normalize_max_side: int = 0       # 0 = 保留原分辨率（证据副本保真）

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

    # --- 视频抽帧 / 音轨（需要本机 ffmpeg；缺失时视频整体降级不解析） ---
    # 每帧要跑一次 VLM caption + 一次抽取，所以 max_keyframes 直接决定单个视频的成本上限：
    # 12 帧 ≈ 24 次 LLM 调用。间隔小于这个上限时会自动拉大间隔铺满全片，
    # 保证采样覆盖整段而不是只覆盖开头。
    video_keyframe_interval_seconds: float = 5.0
    video_max_keyframes: int = 12
    video_keyframe_max_side: int = 1280
    video_max_duration_seconds: int = 600   # 超长视频只处理前 N 秒；0 = 不截断

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

    # --- 区域级视觉向量（切片：让小物体在检索里存在） ---
    # 全图一个向量时，4000px 照片里 400px 的身份证缩到 CLIP 的 224 输入只剩 22px，
    # 不到一个 32x32 patch，语义被地毯/窗帘淹没。切成重叠子图各编一次即可跨过门槛。
    vision_tiling_enabled: bool = True
    vision_tile_grid: int = 2               # 按短边切几份决定瓦片边长（2 → 瓦片≈短边一半）
    vision_tile_overlap: float = 0.25       # 相邻瓦片重叠比例（避免物体正好被切缝劈开）
    vision_tile_min_side: int = 640         # 短边小于此值不切（本来就没有分辨率可挖）
    vision_tile_max: int = 12               # 单帧瓦片数上限（每片一次 CLIP，成本封顶）

    # --- 物件检测（开放词表；给每件物品切一张实拍缩略图） ---
    # 瓦片解决不了缩略图这件事：瓦片是几何等分，一块里常有好几样东西，
    # 缩到节点那么小根本看不出主体是谁。检测器拿物品名当 prompt 出框，
    # 才能回答「这件东西占的是哪几个像素」。
    detector_provider: str = "none"         # local | none（none 时节点退回纯色球）
    detector_model: str = "google/owlv2-base-patch16-ensemble"
    detector_score_threshold: float = 0.12  # OWLv2 分数整体偏低，0.1~0.2 是常用工作点
    detector_max_prompts: int = 8           # 单帧最多查几个物品名（一次前向，成本封顶）
    detector_device: str = ""               # 留空=自动（mps → cuda → cpu）

    # --- 物件缩略图落盘（不受证据 TTL 管辖：原件删了缩略图还得留着） ---
    crop_dir: str = str(BASE_DIR / "data" / "crops")
    crop_padding: float = 0.12              # 框外扩比例，给物体留一点呼吸空间
    crop_size: int = 256                    # 落盘边长（节点上最大也就百来像素）
    crop_jpeg_quality: int = 88

    # --- OCR 文字识别（带字的小物体：身份证/银行卡/快递单/书脊/药盒） ---
    # 这类物体的身份印在它自己身上，OCR 命中的是字面量，不需要模型"认出"它是什么。
    # 切片和检测都解决不了：卡面上的字在整图里不足一个 patch，caption 只会说"一些卡片"。
    ocr_provider: str = "none"              # fake | local | none
    ocr_max_side: int = 1600                # 识别前长边上限（比 VLM 高：OCR 看的是笔画）
    ocr_min_score: float = 0.5              # 低于该置信度的文本块丢弃
    ocr_max_chars: int = 2000               # 单帧文本长度上限（防菜单/说明书刷屏）
    # ⚠️ 关掉脱敏 = 身份证号/银行卡号明文长期留在库里，而原图 15 分钟后就删了。
    # 除非你明确知道自己在干什么（且数据不出本机），否则不要动它。见 app/ocr/redact.py
    ocr_redact_pii: bool = True

    # --- ASR 语音转写（provider=none 时语音流水线整体关闭，音频证据仅落盘+TTL） ---
    asr_provider: str = "none"              # fake | http | none
    asr_base_url: str = ""                  # http：ASR sidecar 地址（如 faster-whisper 服务）
    asr_api_key: str = ""                   # http：sidecar 认证（Bearer）
    asr_timeout_seconds: float = 60.0       # http：sidecar 请求超时（音频转写较慢）
    asr_language: str = ""                  # 留空=自动检测；短片段易误判，中文部署设 zh

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
    retrieval_region_search: bool = True    # 视觉路是否并搜区域向量（小物体召回的入口）
    retrieval_ocr_search: bool = True       # 文本路是否并搜 OCR 文本（带字小物体的入口）
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

    # --- Agent Access（Phase 1） ---
    # True 时启动 seed 一个开发用 Agent grant（全量首版 scope）并打印原始 token；
    # 默认 False，测试/生产不会静默获得后门 grant。
    seed_dev_agent_grant: bool = False
    # grants 管理端点（签发/撤销/列出）的 owner 凭证；为空时管理端点返回 503
    admin_token: str = ""
    # 查询响应 cache_until = now + 该秒数（Agent 侧缓存上限；纠正/遗忘后以平台为准）
    query_cache_ttl_seconds: int = 300

    # --- 前端联调 ---
    # 允许跨域的前端来源，逗号分隔；默认放行 Vite dev server（联调用）。
    # 生产收紧为实际前端域名；置空则不挂 CORS 中间件。
    cors_allow_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Signal（主动式，M4） ---
    signal_ttl_hours: int = 24              # 信号过期时间（过期不投递）
    signal_cooldown_seconds: int = 6 * 3600  # 同一 cooldown_key 再次生成的最小间隔
    signal_stale_location_hours: int = 72   # 位置超过该小时数未更新 → STALE_LOCATION 信号
    signal_low_consumable_level: float = 0.2  # 数值型余量低于该值 → LOW_CONSUMABLE 信号

    # --- 下行设备通道（通信架构 §5） ---
    # 消息默认存活期：过期消息不投递、不展示、不播报。提醒是时效性内容，
    # 宁可让设备错过，也不能在几分钟后才播报一条已经无关的建议。
    device_message_ttl_seconds: int = 600
    # 单次 inbox 拉取 / 长连重连补投的消息条数上限（防止离线久了一次涌出几十条）
    device_inbox_limit: int = 20
    # 长连心跳间隔：服务端超过该秒数没收到任何客户端帧则主动断开，交给设备重连
    device_ws_idle_timeout_seconds: float = 90.0

    # --- 语音问答（唤醒词 → 查记忆 → 念回耳朵，见 app/voice_qa/） ---
    voice_qa_enabled: bool = True
    # 唤醒词识别发生在转写之后，所以要把常见的同音误转写一起列上——
    # ASR 把「小忆」听成「小意」「小艺」是常态，只认一个写法等于一半时间叫不醒。
    voice_wake_words: str = "小忆,小意,小艺,小亿"
    # 答案比主动提醒更短命：问完十几秒才响的答案已经没用了
    voice_answer_ttl_seconds: int = 120

    # --- 语音主动播报（信号 → 耳机，见 app/voice_delivery/） ---
    # 默认关闭：主动在人耳边说话是产品决定，不该因为装了这个模块就自动发生。
    voice_delivery_enabled: bool = False
    voice_delivery_interval_seconds: float = 30.0
    voice_delivery_batch: int = 20          # 单轮最多处理的待投信号数
    # 打扰预算。这一层与信号是否正确无关：同一条信号白天值得说，凌晨三点不值得。
    voice_quiet_hours: str = "22:00-08:00"  # 本机本地时间；留空或格式错误 = 不设安静时段
    voice_max_per_hour: int = 3             # 单设备每小时自动播报条数上限
    voice_min_confidence: float = 0.6       # 低于该置信度的信号不打扰
    # 语音提醒比一般下行消息更短命：过了这段时间人早换了场景，迟到的提醒比没有更烦人
    voice_message_ttl_seconds: int = 300

    # --- 采集控制 connector（设备接入架构 04） ---
    # adb 通道要求后端进程与眼镜插在同一台机器上，是联调期形态；目标形态是 inbox。
    adb_binary: str = "adb"
    # 多台设备同时在线时指定序列号（adb devices 里那一列）；单设备留空即可
    adb_serial: str = ""
    # am start 正常在 1s 内返回；超时通常意味着 USB 掉了或设备卡死，早失败早暴露
    adb_timeout_seconds: float = 10.0
    # 发 intent 前先按 KEYCODE_WAKEUP 唤醒屏幕。熄屏时 Android 12 禁止后台启动
    # camera/microphone 前台服务，`am start` 会假装成功而采集不发生（真机实测）。
    adb_wake_before_dispatch: bool = True

    # --- 演示/测试用 Fake 行为由调用方注入，不在配置里 ---


@lru_cache
def get_settings() -> Settings:
    return Settings()
