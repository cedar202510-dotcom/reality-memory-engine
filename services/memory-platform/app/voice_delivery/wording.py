"""把结构化信号措辞成耳机里的一句话。

这里是**唯一**允许 LLM 介入语音提醒的地方，而且只管「怎么说」，不管「说不说」。
`MemorySignal` 的模型注释写死了这条边界：

    生成走规则引擎（signals/rules.py），措辞归 Agent；平台绝不用 LLM 生成信号。

所以本模块拿到的输入永远是一条**已经被规则判定值得说**的信号，它的自由度只有语言。
把这两件事混在一起的系统会退化成「模型觉得该说话就说话」，那是另一个产品。

模板兜底不是可选项：LLM 挂了、超时了、返回了不合法 JSON，提醒也必须能播出去。
宁可说一句干巴巴的话，也不能安静地吞掉一条已经判定该说的提醒。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import StageAgent
from ..llm.base import LLMClient

# 耳机播报的长度上限。一句话说完要 3 秒以内——戴着耳机的人正在做别的事，
# 一段 30 秒的播报不是提醒，是骚扰。
MAX_SPOKEN_CHARS = 40


class WordingInput(BaseModel):
    signal_type: str
    entity_name: str
    facts: str = Field(description="信号载荷里的结构化事实，一行一条")


class WordingOutput(BaseModel):
    text: str = Field(description="一句中文口语，直接播给用户听")


WORDING_PROMPT = """你在给一个戴着耳机的人念一条提醒。

提醒类型：{signal_type}
相关物品：{entity_name}
已知事实：
{facts}

要求：
- 一句话，中文口语，{max_chars} 字以内，说完不超过三秒。
- 只陈述已知事实，不要编造时间、数量或原因。
- 不要用"根据记录""系统检测到"这类机器腔，就像室友随口提醒一句。
- 不要提问，不要要求用户回复——他现在多半腾不出手。"""


def build_wording_agent(llm: LLMClient) -> StageAgent[WordingInput, WordingOutput]:
    return StageAgent(
        name="voice-wording",
        task="wording",
        input_model=WordingInput,
        output_model=WordingOutput,
        prompt_template=WORDING_PROMPT.replace("{max_chars}", str(MAX_SPOKEN_CHARS)),
        llm_client=llm,
    )


def template_text(signal_type: str, payload: dict) -> str:
    """确定性兜底措辞。LLM 不可用时用它，永远不会失败。"""
    name = payload.get("entity_name") or "有个东西"
    if signal_type == "LOW_CONSUMABLE":
        return f"{name}快用完了"
    if signal_type == "STALE_LOCATION":
        location = payload.get("location")
        if location:
            return f"{name}很久没动了，上次在{location}"
        return f"{name}很久没见到了"
    return f"关于{name}有一条提醒"


def _facts_text(payload: dict) -> str:
    skip = {"entity_name"}
    lines = [f"- {k}: {v}" for k, v in (payload or {}).items() if k not in skip and v is not None]
    return "\n".join(lines) or "-（无额外事实）"


async def compose(
    *, llm: LLMClient | None, signal_type: str, payload: dict
) -> tuple[str, str]:
    """返回 (播报文本, 措辞来源)。来源进审计与回执，用来分辨这句话是谁写的。"""
    fallback = template_text(signal_type, payload or {})
    if llm is None:
        return fallback, "template"

    agent = build_wording_agent(llm)
    result = await agent.run(
        WordingInput(
            signal_type=signal_type,
            entity_name=str((payload or {}).get("entity_name") or ""),
            facts=_facts_text(payload),
        )
    )
    if result is None or not result.text.strip():
        return fallback, "template_fallback"

    text = result.text.strip()
    if len(text) > MAX_SPOKEN_CHARS * 2:
        # 模型话太多：截断会把话截半句，不如退回模板说完整的一句
        return fallback, "template_too_long"
    return text, "llm"


__all__ = ["MAX_SPOKEN_CHARS", "compose", "template_text"]
