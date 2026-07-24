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


class CaptionOutput(BaseModel):
    caption: str = Field(description="一句话中文场景描述")
    scene_tags: list[str] = Field(default_factory=list, description="显著物体列表")


CAPTION_PROMPT = """你是一个现实记忆系统的场景描述器。请描述这张照片。
文件名提示：{file_name}
拍摄时间：{captured_at}
采集端元数据：{meta_hint}

要求：
- caption：一句话中文场景描述，包含显著物体与其所在表面/位置。
- scene_tags：画面中显著物体名列表（中文名词）。"""


class ExtractInput(BaseModel):
    file_name: str
    caption: str
    scene_tags: str
    captured_at: str


class ExtractOutput(BaseModel):
    observations: list[AtomicObservationIn] = Field(default_factory=list)


EXTRACT_PROMPT = """你是现实记忆系统的结构化观察抽取器。基于下面的场景描述，抽取原子观察（AtomicObservation）列表。
文件名提示：{file_name}
场景描述：{caption}
显著物体：{scene_tags}
拍摄时间：{captured_at}

predicate 只能是：OBSERVED_AT/PLACED/MOVED/TAKEN/PUT_IN/TAKEN_OUT/OPENED/CLOSED/USED/CONSUMED/PREFERENCE_EXPRESSED/INTENT_CREATED。
每条观察给出 object_text（物体名）、value.location（所在表面/位置，若有）、confidence 五个分量与 aggregate。

object_text 命名规范（重要，用于跨帧识别同一个物体）：
- 用通用类别名，如「智能手机」「笔记本电脑」「杯子」，不要把颜色、状态、品牌等属性写进名字；
- 属性信息放到 value 里（如 value.color / value.state）；
- 同一个物体在不同帧里必须用同一个名字。
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

AUDIO_PARSER_VERSION = "audio-extractor-v0.1"

# 语音适宜的谓词：偏好/意图/使用/消耗（位置类谓词主要来自视觉帧）
AUDIO_ALLOWED_PREDICATES = ("PREFERENCE_EXPRESSED", "INTENT_CREATED", "USED", "CONSUMED")


class AudioExtractInput(BaseModel):
    file_name: str
    transcript: str
    captured_at: str


class AudioExtractOutput(BaseModel):
    observations: list[AtomicObservationIn] = Field(default_factory=list)


AUDIO_EXTRACT_PROMPT = """你是现实记忆系统的语音语义抽取器。基于下面的语音转写文本，抽取原子观察（AtomicObservation）列表。
文件名提示：{file_name}
语音转写：{transcript}
录制时间：{captured_at}

predicate 只能是：PREFERENCE_EXPRESSED/INTENT_CREATED/USED/CONSUMED。
- PREFERENCE_EXPRESSED：用户表达了偏好（喜欢/不喜欢/习惯用……），value.preference 记录偏好内容。
- INTENT_CREATED：用户表达了意图或任务（要买/要做/提醒我……），value.task 记录任务内容。
- USED / CONSUMED：用户提到使用了/消耗了某物。
每条观察给出 object_text（涉及的物体/事物名）、confidence 五个分量与 aggregate。
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
