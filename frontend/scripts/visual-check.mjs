import { chromium } from "playwright";

const browser = await chromium.launch({ channel: "msedge", headless: true });
const results = [];

for (const config of [
  { name: "desktop", viewport: { width: 1440, height: 900 } },
  { name: "mobile", viewport: { width: 390, height: 844 } },
]) {
  const page = await browser.newPage({ viewport: config.viewport, deviceScaleFactor: 1 });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  await page.goto("http://127.0.0.1:5173/", { waitUntil: "networkidle" });
  await page.screenshot({ path: `${config.name}-preview.png`, fullPage: true });
  const home = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    heading: document.querySelector("h1")?.textContent,
    brand: document.querySelector(".wordmark")?.textContent,
  }));
  await page.getByRole("button", { name: "打开我的" }).click();
  await page.locator(".profile-sheet > button").filter({ hasText: "所有" }).click();
  await page.waitForTimeout(200);
  const allCount = await page.locator(".object-card").count();
  await page.screenshot({ path: `${config.name}-all-pile.png` });
  await page.evaluate(() => window.scrollTo(0, document.querySelector(".pile-stage").offsetTop + window.innerHeight * .55));
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${config.name}-all-spread.png` });
  await page.locator(".object-card").first().click();
  const detailHeading = await page.locator(".detail-head h1").textContent();
  await page.locator("input[type=range]").fill("1");
  const detailOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  if (config.name === "desktop") {
    await page.getByRole("button", { name: "返回" }).click();
    await page.getByRole("button", { name: "现在", exact: true }).first().click();
    await page.getByRole("button", { name: /戴上眼镜查看/ }).click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: "glass-preview.png" });
    await page.getByRole("button", { name: "查看禁采场景" }).click();
    const privateScene = await page.getByText("当前空间已禁采", { exact: true }).isVisible();
    results.push({ name: config.name, home, allCount, detailHeading, detailOverflow, privateScene, errors });
  } else {
    results.push({ name: config.name, home, allCount, detailHeading, detailOverflow, errors });
  }
  await page.close();
}

await browser.close();
console.log(JSON.stringify(results, null, 2));
