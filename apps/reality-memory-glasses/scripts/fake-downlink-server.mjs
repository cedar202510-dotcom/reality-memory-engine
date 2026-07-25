#!/usr/bin/env node

import { createServer } from "node:http";
import { randomUUID } from "node:crypto";

const port = Number(process.env.PORT || 8765);
const intent = (process.argv[2] || "REMINDER").toUpperCase();

const fixtures = {
  ANSWER: {
    title: "钥匙上次在客厅茶几右侧",
    body: "这是最近一次确认的位置",
    interaction: "ACKNOWLEDGE",
  },
  REMINDER: {
    title: "出门前记得带上资料",
    body: "十点的会议快开始了",
    interaction: "ACKNOWLEDGE",
  },
  TASK: {
    title: "记得把资料给小王",
    body: "你已经到公司了",
    interaction: "ACKNOWLEDGE",
  },
  CONSUMABLE: {
    title: "洗衣液大约只够这次",
    body: "需要时可以加入采购清单",
    interaction: "NONE",
  },
};

if (!(intent in fixtures)) {
  console.error(`不支持的测试意图：${intent}`);
  console.error(`可用：${Object.keys(fixtures).join(", ")}`);
  process.exit(1);
}

const deviceId = randomUUID();
const messageId = randomUUID();
const fixture = fixtures[intent];
const receipts = [];
let registeredDevice = null;
let terminal = false;

function json(response, status, value) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
  });
  response.end(body);
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  const body = Buffer.concat(chunks).toString("utf8");
  return body ? JSON.parse(body) : {};
}

function messageEnvelope() {
  const now = new Date();
  return {
    schema_ref: "rme.device-message.v0",
    message_id: messageId,
    device_id: deviceId,
    message_type: "REMINDER_SIGNAL",
    payload_schema_ref: "rme.glasses-presentation.v0",
    priority: intent === "REMINDER" ? "HIGH" : "NORMAL",
    delivery_policy: {
      allow_text: true,
      allow_tts: false,
    },
    payload: {
      presentation: {
        intent,
        title: fixture.title,
        body: fixture.body,
        interaction: fixture.interaction,
      },
      source: {
        kind: intent === "ANSWER" ? "AGENT_REPLY" : "MEMORY_SIGNAL",
        reference_id: `fake-${intent.toLowerCase()}`,
      },
      correlation_id: `fake-${intent.toLowerCase()}-test`,
    },
    sent_at: now.toISOString(),
    expires_at: new Date(now.getTime() + 120_000).toISOString(),
  };
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url || "/", `http://${request.headers.host}`);
  try {
    if (request.method === "GET" && url.pathname === "/healthz") {
      json(response, 200, { ok: true, service: "fake-downlink" });
      return;
    }

    if (request.method === "POST" && url.pathname === "/internal/v1/devices") {
      registeredDevice = await readJson(request);
      console.log(
        `[设备注册] ${registeredDevice.name || "未命名设备"} -> ${deviceId}`,
      );
      json(response, 201, {
        device_id: deviceId,
        ...registeredDevice,
      });
      return;
    }

    if (
      request.method === "GET" &&
      url.pathname === `/internal/v1/devices/${deviceId}/inbox`
    ) {
      json(response, 200, {
        messages: terminal ? [] : [messageEnvelope()],
      });
      return;
    }

    if (
      request.method === "POST" &&
      url.pathname === `/internal/v1/devices/${deviceId}/receipts`
    ) {
      const receipt = await readJson(request);
      if (receipt.message_id !== messageId) {
        console.log(
          `[旧消息回执已忽略] ${receipt.status || "UNKNOWN"} message_id=${receipt.message_id || ""}`,
        );
        json(response, 201, { receipt, ignored: true });
        return;
      }
      receipts.push(receipt);
      console.log(
        `[眼镜回执] ${receipt.status || "UNKNOWN"} message_id=${receipt.message_id || ""}`,
      );
      if (["DISMISSED", "EXPIRED", "FAILED"].includes(receipt.status)) {
        terminal = true;
      }
      json(response, 201, { receipt });
      return;
    }

    if (
      request.method === "POST" &&
      url.pathname === "/internal/v1/device-evidence"
    ) {
      json(response, 503, {
        detail: "本地消息模拟器不会接收或删除真实采集证据",
      });
      return;
    }

    json(response, 404, { detail: "not found" });
  } catch (error) {
    console.error("[模拟器错误]", error);
    json(response, 500, { detail: String(error) });
  }
});

server.listen(port, "127.0.0.1", () => {
  console.log(`本地下发模拟器已启动：http://127.0.0.1:${port}`);
  console.log(`待下发消息：${intent} / ${fixture.title}`);
  console.log("请保持 adb reverse tcp:8765 tcp:8765，然后让眼镜进入佩戴感知状态。");
});

process.on("SIGINT", () => {
  console.log(`\n已停止。共收到 ${receipts.length} 条眼镜回执。`);
  server.close(() => process.exit(0));
});
