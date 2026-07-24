"""Answerer：通道 2 的 VLM 精判/验证阶段（契约化，不直写库）。

倒序早停模式下每次只验证一小批最新的候选帧（默认 2 帧）：
found + chosen_index 指明在哪一帧看到了目标，供上层用**该帧**的时间
计算 last_seen/新鲜度（修复：不再用召回集合的最大时间冒充目击时间）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import StageAgent
from ..llm.base import LLMClient


class AnswerInput(BaseModel):
    query_name: str
    candidates_text: str = Field(description="本批候选帧（编号+caption+时间）与语音转写列表文本")


class AnswerOutput(BaseModel):
    found: bool
    location: str | None = None
    confidence: float = 0.0
    answer_text: str = ""
    # 本批候选帧中看到目标的那一帧编号（0 起）；未找到或无法确定时为 null
    chosen_index: int | None = None


ANSWER_PROMPT = """你是现实记忆系统的找物助手。用户问："{query_name}" 在哪里？

下面是本批候选场景帧（按时间从新到旧编号，0 号最新；可能附带对应图片）：
{candidates_text}

请判断本批里哪一帧包含"{query_name}"，它在什么表面/位置上。
- chosen_index 填看到目标的那一帧编号；本批都没有则 found=false、chosen_index=null。
- 如果没有任何候选包含它，found=false，confidence 给低分。
- answer_text 用中文、口语化，必须带"最后一次看到"式的时间表述。"""


def build_answerer(llm: LLMClient) -> StageAgent[AnswerInput, AnswerOutput]:
    return StageAgent(
        name="answerer",
        task="answer",
        input_model=AnswerInput,
        output_model=AnswerOutput,
        prompt_template=ANSWER_PROMPT,
        llm_client=llm,
    )
