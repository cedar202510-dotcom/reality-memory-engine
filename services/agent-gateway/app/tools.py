"""§14 工具表 → OpenAI tools schema + 分发器。

工具是高层结构化命令，不是数据库查询；服务端（平台）对每次调用二次做
scope/schema 校验——这张表不是安全边界，AgentGrant 才是。
"""
from __future__ import annotations

import json
from typing import Any

from .memory_client import MemoryClient

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "find_object",
            "description": "查询某个物品最后出现在哪里。deep=true 时做深度检索（更慢，用于快速查询没有答案时）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "物品名，如 钥匙"},
                    "deep": {"type": "boolean", "default": False},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_object_timeline",
            "description": "查询某个实体的事件时间线（位置变化历史、纠正记录）。entity_id 来自 find_object 的返回。",
            "parameters": {
                "type": "object",
                "properties": {"entity_id": {"type": "string", "description": "实体 uuid"}},
                "required": ["entity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_preference",
            "description": "查询用户对某个物品/类别表达过的偏好。",
            "parameters": {
                "type": "object",
                "properties": {"subject": {"type": "string", "description": "物品或类别名，如 胡辣汤"}},
                "required": ["subject"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_correction",
            "description": "代表用户提交一条明确的纠正（如\"不是茶几，是玄关\"）。只能在用户明确说出纠正内容后调用，不得自行推断。",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string", "description": "实体 uuid"},
                    "field": {"type": "string", "description": "被纠正的字段，如 location"},
                    "value": {"type": "string", "description": "纠正后的值"},
                    "reason": {"type": "string", "description": "用户原话/原因"},
                },
                "required": ["entity_id", "field", "value"],
            },
        },
    },
]


async def execute_tool(memory: MemoryClient, name: str, arguments: dict[str, Any]) -> str:
    """执行一个工具调用，返回 JSON 字符串（作为 tool 消息回填给模型）。"""
    try:
        if name == "find_object":
            result = await memory.find_object(
                str(arguments["name"]), deep=bool(arguments.get("deep", False))
            )
        elif name == "get_object_timeline":
            result = await memory.get_object_timeline(str(arguments["entity_id"]))
        elif name == "get_preference":
            result = await memory.get_preference(str(arguments["subject"]))
        elif name == "submit_correction":
            result = await memory.submit_correction(
                str(arguments["entity_id"]),
                str(arguments["field"]),
                arguments.get("value"),
                str(arguments.get("reason", "")),
            )
        else:
            result = {"error": f"未知工具：{name}"}
    except KeyError as exc:
        result = {"error": f"缺少必需参数：{exc}"}
    return json.dumps(result, ensure_ascii=False, default=str)
