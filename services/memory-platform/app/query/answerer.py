"""Answerer：通道 2 的 VLM 精判阶段（契约化，不直写库）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import StageAgent
from ..llm.base import LLMClient


class AnswerInput(BaseModel):
    query_name: str
    candidates_text: str = Field(description="候选帧 caption+时间 列表文本")


class AnswerOutput(BaseModel):
    found: bool
    location: str | None = None
    confidence: float = 0.0
    answer_text: str = ""


ANSWER_PROMPT = """你是现实记忆系统的找物助手。用户问："{query_name}" 在哪里？

下面是系统检索到的候选场景帧（按时间倒序）：
{candidates_text}

请判断哪一帧最可能包含"{query_name}"，它在什么表面/位置上。
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
