"""Perception 流水线阶段定义：Captioner（帧描述）与 Extractor（结构化抽取）。

都是 StageAgent：输入 schema → LLM → 输出 schema 校验 → 失败重试 1 次后弃帧。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import StageAgent
from ..llm.base import LLMClient
from ..schemas import AtomicObservationIn

PARSER_VERSION = "extractor-v0.1"


class CaptionInput(BaseModel):
    file_name: str
    captured_at: str
    meta_hint: str = ""
    audio_context: str = ""


class CaptionOutput(BaseModel):
    caption: str = Field(description="一句话中文场景描述")
    scene_tags: list[str] = Field(default_factory=list, description="显著物体列表")


# audio_context 是「同一段视频里说的话」。它存在的理由是纯视觉命名有天花板：
# VLM 看着一小块炸物只能写「黄色颗粒状食物」，而同一时刻录到的话是「这个鸡米花已经软了」。
# 把转写喂进来，画面里那团东西才能落到「鸡米花」这个名字上——
# 这不只是描述更好看，而是跨模态能不能指向同一个实体的前提：
# 视觉侧记「黄色颗粒状食物」、语音侧记「鸡米花」，实体解析会把它们当成两个物体，
# 喜好度那边就永远算不出「你觉得鸡米花软了不好吃」。
CAPTION_PROMPT = """你是一个现实记忆系统的场景描述器。请描述这张照片。
文件名提示：{file_name}
拍摄时间：{captured_at}
采集端元数据：{meta_hint}
同一段视频中说的话（可能提到画面里东西的名字）：{audio_context}

要求：
- caption：一句话中文场景描述，包含显著物体与其所在表面/位置。
- scene_tags：画面中显著物体名列表（中文名词）。
- 命名优先用说话里出现的具体名称：只要画面里的东西与话里提到的对得上，
  就用话里的名字（如「鸡米花」「橙皮」），不要退回「黄色颗粒状食物」这类纯外观描述。
- 但不要硬凑：话里提到而画面上确实没有的东西，不要写进 scene_tags。"""


class ExtractInput(BaseModel):
    file_name: str
    caption: str
    scene_tags: str
    captured_at: str
    audio_context: str = ""


class ExtractOutput(BaseModel):
    observations: list[AtomicObservationIn] = Field(default_factory=list)


EXTRACT_PROMPT = """你是现实记忆系统的结构化观察抽取器。基于下面的场景描述，抽取原子观察（AtomicObservation）列表。
文件名提示：{file_name}
场景描述：{caption}
显著物体：{scene_tags}
拍摄时间：{captured_at}
同一段视频中说的话（可能提到画面里东西的名字）：{audio_context}

predicate 只能是：OBSERVED_AT/PLACED/MOVED/TAKEN/PUT_IN/TAKEN_OUT/OPENED/CLOSED/USED/CONSUMED/PREFERENCE_EXPRESSED/INTENT_CREATED。
每条观察给出 object_text（物体名）、value.location（所在表面/位置，若有）、confidence 五个分量与 aggregate。

object_text 命名规范（重要，用于跨帧、跨模态识别同一个物体）：
- 用通用类别名，如「智能手机」「笔记本电脑」「杯子」，不要把颜色、状态、品牌等属性写进名字；
- 属性信息放到 value 里（如 value.color / value.state）；
- 同一个物体在不同帧里必须用同一个名字；
- 话里出现过该物体的具体名称时优先采用（「黄色颗粒状食物」→「鸡米花」），
  这样语音抽到的观察和画面抽到的观察才能落到同一个实体上。
没有可抽取内容时返回空列表。"""


def build_captioner(llm: LLMClient) -> StageAgent[CaptionInput, CaptionOutput]:
    return StageAgent(
        name="captioner",
        task="caption",
        input_model=CaptionInput,
        output_model=CaptionOutput,
        prompt_template=CAPTION_PROMPT,
        llm_client=llm,
    )


def build_extractor(llm: LLMClient) -> StageAgent[ExtractInput, ExtractOutput]:
    return StageAgent(
        name="extractor",
        task="extract",
        input_model=ExtractInput,
        output_model=ExtractOutput,
        prompt_template=EXTRACT_PROMPT,
        llm_client=llm,
    )


# ---------------------------------------------------------------- 语音语义抽取（两步式音频解析的语义层）

# v0.2：偏好带上极性与强度。v0.1 只有一句自由文本 value.preference，
# 「这个花生一般般」和「这个花生太好吃了」在库里长得一模一样，喜好度算不出来。
AUDIO_PARSER_VERSION = "audio-extractor-v0.2"

# 语音适宜的谓词：偏好/意图/使用/消耗（位置类谓词主要来自视觉帧）
AUDIO_ALLOWED_PREDICATES = ("PREFERENCE_EXPRESSED", "INTENT_CREATED", "USED", "CONSUMED")

# value.sentiment 的取值。归一化成三档而不是让模型自由发挥形容词：
# 打分侧要的是可比的极性，形容词还原成分数这件事交给模型在抽取时做一次，
# 比在打分时对着「还行」「凑合」「不赖」做字符串判断可靠得多。
SENTIMENTS = ("LIKE", "DISLIKE", "NEUTRAL")

# value.intent_kind：意图对喜好度的含义差别很大——「还想再买」是强正信号，
# 「以后别买了」是强负信号，两者都是 INTENT_CREATED，靠这个字段区分。
INTENT_KINDS = ("PURCHASE", "REPEAT", "AVOID", "OTHER")


class AudioExtractInput(BaseModel):
    file_name: str
    transcript: str
    captured_at: str
    visual_context: str = ""


class AudioExtractOutput(BaseModel):
    observations: list[AtomicObservationIn] = Field(default_factory=list)


AUDIO_EXTRACT_PROMPT = """你是现实记忆系统的语音语义抽取器。基于下面的语音转写文本，抽取原子观察（AtomicObservation）列表。
文件名提示：{file_name}
语音转写：{transcript}
录制时间：{captured_at}
同时段画面里出现的物体：{visual_context}

predicate 只能是：PREFERENCE_EXPRESSED/INTENT_CREATED/USED/CONSUMED。
- PREFERENCE_EXPRESSED：用户对某物表达了评价或偏好（好吃/难吃/一般般/喜欢/不喜欢/习惯用……）。
  value.preference：原话里的评价内容；
  value.sentiment：LIKE（正面）/ DISLIKE（负面）/ NEUTRAL（中性或褒贬参半）；
  value.intensity：0~1 的强度，「一般般/还行」≈0.2，「不错/好吃」≈0.6，「太好吃了/超爱」≈0.95，
                   「有点软/不太行」≈0.4（配 DISLIKE），「难吃死了」≈0.95（配 DISLIKE）；
  value.aspect：评价的方面，如 口味/口感/价格/外观/新鲜度，判断不出填空字符串。
- INTENT_CREATED：用户表达了意图或任务（要买/还想再来/以后别买/提醒我……）。
  value.task：任务内容；
  value.intent_kind：PURCHASE（想买/想尝试）/ REPEAT（还想再来一次）/ AVOID（以后避开）/ OTHER。
- USED / CONSUMED：用户提到使用了/消耗了某物。

object_text 命名规范（重要，视觉帧和语音必须能对上同一个物体）：
- 用通用类别名词，如「花生」「鸡米花」「耳机」，不要带「这个/那个」等指示代词；
- 转写里说「这个」「它」时，结合上面的画面物体列表还原成具体物体名；
- 属性放 value（如 value.state="软了"），不要写进名字。

每条观察给出 object_text、confidence 五个分量与 aggregate。
转写噪声大或指代还原不了时，降低 confidence，不要臆造物体。
没有可抽取内容时返回空列表。"""


def build_audio_extractor(llm: LLMClient) -> StageAgent[AudioExtractInput, AudioExtractOutput]:
    return StageAgent(
        name="audio_extractor",
        task="audio_extract",
        input_model=AudioExtractInput,
        output_model=AudioExtractOutput,
        prompt_template=AUDIO_EXTRACT_PROMPT,
        llm_client=llm,
    )
