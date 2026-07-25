#!/usr/bin/env bash
set -euo pipefail

base_url="${1:-http://127.0.0.1:8765}"
device_id="${2:-}"
intent="${3:-REMINDER}"

python3 - "$base_url" "$device_id" "$intent" <<'PY'
import json
import sys
import urllib.request

base_url, device_id, intent = sys.argv[1:4]
intent = intent.upper()

fixtures = {
    "ANSWER": {
        "title": "钥匙上次在客厅茶几右侧",
        "body": "这是最近一次确认的位置",
        "source": "AGENT_REPLY",
        "interaction": "NONE",
    },
    "REMINDER": {
        "title": "出门前记得带上资料",
        "body": "十点的会议快开始了",
        "source": "MEMORY_SIGNAL",
        "interaction": {
            "type": "ACKNOWLEDGE",
            "action_id": "test-reminder-acknowledge",
        },
    },
    "TASK": {
        "title": "记得把资料给小王",
        "body": "你已经到公司了",
        "source": "MEMORY_SIGNAL",
        "interaction": {
            "type": "COMPLETE_TASK",
            "action_id": "test-task-complete",
        },
    },
    "CONSUMABLE": {
        "title": "洗衣液大约只够这次",
        "body": "采购提醒",
        "source": "MEMORY_SIGNAL",
        "interaction": {
            "type": "ADD_TO_SHOPPING_LIST",
            "action_id": "test-shopping-list-add",
        },
    },
}

if intent not in fixtures:
    raise SystemExit(f"不支持的测试意图：{intent}；可用：{', '.join(fixtures)}")


def request(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


if not device_id:
    devices = request("GET", "/internal/v1/devices").get("devices", [])
    glasses = [item for item in devices if item.get("kind") == "glasses"]
    if not glasses:
        raise SystemExit("后端还没有已登记的眼镜；请先启动并佩戴安装了 0.1.7 的 RV101")
    device_id = glasses[0]["device_id"]

fixture = fixtures[intent]
payload = {
    "message_type": "REMINDER_SIGNAL",
    "payload_schema_ref": "rme.glasses-presentation.v0",
    "priority": "HIGH" if intent == "REMINDER" else "NORMAL",
    "ttl_seconds": 120,
    "delivery_policy": {"allow_text": True, "allow_tts": False},
    "payload": {
        "presentation": {
            "intent": intent,
            "title": fixture["title"],
            "body": fixture["body"],
            "interaction": fixture["interaction"],
        },
        "source": {
            "kind": fixture["source"],
            "reference_id": f"manual-{intent.lower()}",
        },
        "correlation_id": f"manual-{intent.lower()}-test",
    },
}
created = request(
    "POST",
    f"/internal/v1/devices/{device_id}/messages",
    payload,
)
message = created["message"]
print(f"已下发 {intent} 到设备 {device_id}")
print(f"message_id={message['message_id']}")
print(f"pushed_connections={created['pushed_connections']}（HTTP 轮询版通常为 0，仍会落库）")
print("眼镜处于佩戴感知状态时，应在约 3 秒内拉取并显示。")
PY
