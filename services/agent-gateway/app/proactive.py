"""主动式提醒：拉取平台信号 → 措辞成建议（只建议，不执行任何现实动作）。

判断在平台规则引擎，这里只做措辞：默认确定性模板（可测试、不会跑偏）；
PROACTIVE_LLM_WORDING=true 时用 LLM 润色（失败降级回模板）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .llm import ChatLLM

_TEMPLATES = {
    "LOW_CONSUMABLE": "{entity_name}可能快用完了，需要加入待办清单吗？",
    "STALE_LOCATION": "{entity_name}已经很久没确认过位置了（上次在{location}），要我下次看到时留意一下吗？",
}


@dataclass
class Suggestion:
    signal_id: str
    signal_type: str
    entity_name: str
    text: str
    confidence: float


def template_wording(signal: dict[str, Any]) -> str:
    payload = signal.get("payload") or {}
    template = _TEMPLATES.get(signal.get("signal_type", ""), "{entity_name}有一条状态提醒。")
    try:
        return template.format(**{"entity_name": "物品", "location": "未知位置", **payload})
    except (KeyError, IndexError):
        return f"{payload.get('entity_name', '物品')}有一条状态提醒。"


async def llm_wording(llm: ChatLLM, signal: dict[str, Any]) -> str:
    """LLM 润色：只措辞不判断；输出跑偏/失败一律降级回模板。"""
    fallback = template_wording(signal)
    try:
        turn = await llm.chat(
            [
                {
                    "role": "system",
                    "content": "把下面的结构化状态信号转成一句简短、口语化的中文提醒建议。"
                    "只建议（如'需要加入待办吗？'），不得替用户执行任何动作，不得夸大确定性。只输出这一句话。",
                },
                {"role": "user", "content": str(signal)},
            ]
        )
        text = (turn.content or "").strip()
        return text if 0 < len(text) <= 120 else fallback
    except Exception:  # noqa: BLE001 - 措辞失败不阻塞提醒
        return fallback


async def build_suggestions(
    signals: list[dict[str, Any]], *, llm: ChatLLM | None = None
) -> list[Suggestion]:
    out: list[Suggestion] = []
    for sig in signals:
        text = await llm_wording(llm, sig) if llm is not None else template_wording(sig)
        out.append(
            Suggestion(
                signal_id=str(sig.get("id")),
                signal_type=str(sig.get("signal_type")),
                entity_name=str((sig.get("payload") or {}).get("entity_name", "")),
                text=text,
                confidence=float(sig.get("confidence", 0.0)),
            )
        )
    return out
