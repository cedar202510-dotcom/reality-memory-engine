import config from "../config.js";

const SESSION_STORAGE_KEY = "realgit.aiui.session-id";

function normalizedBaseUrl() {
  return String(config.apiBaseUrl || "").trim().replace(/\/+$/, "");
}

function newCorrelationId() {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return `aiui:${crypto.randomUUID()}`;
  }
  return `aiui:${Date.now()}:${Math.random().toString(16).slice(2)}`;
}

function readSessionId() {
  try {
    return localStorage.getItem(SESSION_STORAGE_KEY) || "";
  } catch (error) {
    console.warn("Unable to read the RealGit AIUI session", error);
    return "";
  }
}

function writeSessionId(sessionId) {
  if (!sessionId) {
    return;
  }
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  } catch (error) {
    console.warn("Unable to persist the RealGit AIUI session", error);
  }
}

async function responseError(response) {
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    // The status below is enough when the server did not return JSON.
  }
  return `RealGit 服务返回 HTTP ${response.status}`;
}

async function withTimeout(promise, timeoutMs) {
  let timeoutId;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => {
      reject(new Error("连接 RealGit 超时"));
    }, timeoutMs);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function askRealGit(message, requestedSessionId = "") {
  const baseUrl = normalizedBaseUrl();
  if (!baseUrl || baseUrl.includes("replace-with-realgit-api.example")) {
    throw new Error("尚未配置 RealGit 后端地址");
  }
  if (!baseUrl.startsWith("https://")) {
    throw new Error("AIUI 正式网络请求必须使用 HTTPS");
  }

  const headers = {
    "Content-Type": "application/json"
  };
  if (config.clientToken) {
    headers["X-RealGit-Client-Token"] = config.clientToken;
  }

  const body = {
    message,
    session_id: requestedSessionId || readSessionId() || undefined,
    source: "ROKID_AIUI",
    response_channel: "AIUI_CONVERSATION",
    correlation_id: newCorrelationId(),
    device_id: config.deviceId || undefined
  };
  const response = await withTimeout(
    fetch(`${baseUrl}/v1/chat`, {
      method: "POST",
      headers,
      body: JSON.stringify(body)
    }),
    Number(config.requestTimeoutMs) || 20000
  );

  if (!response.ok) {
    throw new Error(await responseError(response));
  }

  const payload = await response.json();
  if (
    payload.response_channel !== "AIUI_CONVERSATION" ||
    typeof payload.reply !== "string"
  ) {
    throw new Error("RealGit 返回了不兼容的回答契约");
  }
  writeSessionId(payload.session_id);
  return payload;
}

export function speakReply(text) {
  if (
    !config.enableTts ||
    typeof speechSynthesis === "undefined" ||
    typeof SpeechSynthesisUtterance === "undefined"
  ) {
    return;
  }
  const value = String(text || "").trim();
  if (!value) {
    return;
  }
  try {
    speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(value);
    utterance.lang = "zh-CN";
    utterance.rate = 1;
    utterance.pitch = 1;
    utterance.volume = 1;
    speechSynthesis.speak(utterance);
  } catch (error) {
    console.warn("Unable to speak the RealGit reply", error);
  }
}
