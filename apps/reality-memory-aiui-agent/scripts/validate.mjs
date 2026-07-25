import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import process from "node:process";

const root = resolve(import.meta.dirname, "..");

async function text(path) {
  return readFile(resolve(root, path), "utf8");
}

const app = JSON.parse(await text("app.json"));
const pkg = JSON.parse(await text("package.json"));
const page = await text("pages/answer/index.ink");
const manifest = await text("AGENTS.md");
const client = await text("lib/realgit-client.js");
const config = await import(`../config.js?validate=${Date.now()}`);

const failures = [];
if (app.pages?.[0] !== "pages/answer/index") {
  failures.push("app.json 的首个页面必须是 pages/answer/index");
}
if (pkg.type !== "module") {
  failures.push("package.json 必须声明 ESM");
}
for (const marker of [
  "<script type=\"application/json\" def>",
  "<script setup>",
  "<page>",
  "<style>",
  "\"message\"",
  "\"required\""
]) {
  if (!page.includes(marker)) {
    failures.push(`AIUI 页面缺少 ${marker}`);
  }
}
for (const marker of [
  "source: \"ROKID_AIUI\"",
  "response_channel: \"AIUI_CONVERSATION\""
]) {
  if (!client.includes(marker)) {
    failures.push(`AIUI 客户端缺少路由字段 ${marker}`);
  }
}
if (!manifest.includes("本智能体只处理用户主动发起的对话")) {
  failures.push("AGENTS.md 没有声明主动对话边界");
}
if (!String(config.default.apiBaseUrl || "").startsWith("https://")) {
  failures.push("config.js 的 apiBaseUrl 必须使用 HTTPS");
}

if (failures.length) {
  for (const failure of failures) {
    console.error(`FAIL: ${failure}`);
  }
  process.exit(1);
}

console.log("PASS: RealGit AIUI 工程结构和通道路由契约有效");
if (config.default.apiBaseUrl.includes("replace-with-realgit-api.example")) {
  console.warn("WARN: 打包真机版本前需要在 config.js 配置真实 HTTPS 后端地址");
}
