// 冒烟：逐页打开，收集控制台错误与页面异常，截图存 /tmp
import { chromium } from "playwright";

const pages = ["/agent", "/timeline", "/galaxy", "/my", "/media", "/capture", "/live", "/pico"];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 430, height: 932 } });

let failed = false;
for (const path of pages) {
  const errors = [];
  page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
  page.on("pageerror", (err) => errors.push(String(err)));
  const response = await page.goto(`http://localhost:5199${path}`, { waitUntil: "networkidle" }).catch((error) => {
    errors.push(`页面无法打开：${error.message}`);
    return null;
  });
  await page.waitForTimeout(1200);
  if (!response || !response.ok()) errors.push(`页面响应异常：${response?.status() ?? "无响应"}`);
  if ((await page.locator("#root").textContent().catch(() => ""))?.trim() === "") {
    errors.push("页面根节点没有可见内容");
  }
  const name = path.slice(1) || "agent";
  await page.screenshot({ path: `/tmp/merge-${name}.png` });
  const real = errors.filter(e => !e.includes("Failed to load resource") && !e.includes("fetch"));
  console.log(`${path}: ${real.length === 0 ? "OK" : "ERRORS"}`);
  real.forEach(e => { console.log("  " + e.slice(0, 300)); failed = true; });
}
await browser.close();
process.exit(failed ? 1 : 0);
