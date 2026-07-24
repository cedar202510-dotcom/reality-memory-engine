"""Agent Harness：有界 tool-use 循环（与平台 StageAgent 是不同的编程模型）。

每条用户消息：≤ max_tool_turns 轮模型↔工具往返；超限或模型不再调工具即收尾。
模型只能通过 §14 工具触达记忆；工具结果里的 limitations 必须转达给用户。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .llm import ChatLLM
from .memory_client import MemoryClient
from .tools import TOOLS, execute_tool

SYSTEM_PROMPT = """你是 Reality Memory Engine 的个人记忆助手。你通过受限工具访问用户的现实记忆（物品位置、偏好、时间线），自己没有任何记忆数据。

回答标准（每个答案都要考虑）：
- 说清楚：结果是什么、最后观察时间、置信度如何、有没有备选位置。
- 记忆结果附带的 limitations 字段是平台对不确定性的声明，必须自然地转达给用户，不能省略。
- 置信度不是确定性：0.8 的置信度要说"应该在/我最后一次看到"，不能说"就在"。
- 带上新鲜度："最后一次看到是 X 前"比裸位置更诚实。

降级规则：
- 没有可靠记忆 → 明确说不知道，绝不编造。
- 有多个候选/歧义 → 先追问用户指的是哪一个，再查询。
- 工具返回 error 且 status=403 → 告诉用户当前授权不足，请求用户授权，不尝试绕过。
- 工具返回 error 且 status=0 → 记忆平台暂时不可用，请稍后再试；不要把对话历史当作权威替代。

纠正规则：
- 只有用户明确说出纠正内容（如"其实在玄关"）才调用 submit_correction，附上用户原话作 reason。
- 不得因为自己的推断而纠正记忆。

主动建议只到"建议"为止：不能替用户购买、下单、发消息或执行任何现实动作。
用中文口语化回答，简短直接。"""


@dataclass
class ToolTraceEntry:
    tool: str
    arguments: dict[str, Any]
    result: str


@dataclass
class TurnResult:
    reply: str
    tool_trace: list[ToolTraceEntry] = field(default_factory=list)


async def run_turn(
    *,
    llm: ChatLLM,
    memory: MemoryClient,
    history: list[dict[str, Any]],
    user_message: str,
    max_tool_turns: int = 6,
) -> TurnResult:
    """执行一条用户消息；history 就地追加（含中间 tool 消息，供后续轮次引用）。"""
    if not history:
        history.append({"role": "system", "content": SYSTEM_PROMPT})
    history.append({"role": "user", "content": user_message})

    trace: list[ToolTraceEntry] = []
    for _ in range(max_tool_turns):
        turn = await llm.chat(history, tools=TOOLS)
        if not turn.tool_calls:
            reply = turn.content or "（模型没有给出回答）"
            history.append({"role": "assistant", "content": reply})
            return TurnResult(reply=reply, tool_trace=trace)

        # 回填 assistant 的 tool_calls 消息（OpenAI 协议要求）
        history.append(
            {
                "role": "assistant",
                "content": turn.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in turn.tool_calls
                ],
            }
        )
        for tc in turn.tool_calls:
            result = await execute_tool(memory, tc.name, tc.arguments)
            trace.append(ToolTraceEntry(tool=tc.name, arguments=tc.arguments, result=result))
            history.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    # 超限降级：让模型基于已有工具结果收尾（不再提供工具）
    turn = await llm.chat(
        history
        + [{"role": "user", "content": "（系统：工具轮数已达上限，请基于已有结果直接回答，说明不确定性。）"}]
    )
    reply = turn.content or "查询轮数达到上限，暂时无法给出可靠答案。"
    history.append({"role": "assistant", "content": reply})
    return TurnResult(reply=reply, tool_trace=trace)
