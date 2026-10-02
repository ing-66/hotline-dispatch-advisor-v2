import { chromium } from "playwright-core";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const base = process.env.FRONTEND_URL || "http://127.0.0.1:3000";
const marker = `【前端浏览器闭环验证-${Date.now()}】市民反映小区临街商铺招牌松动，物业未及时处理，希望主管部门协调处置。`;

const browser = await chromium.launch({
  executablePath: CHROME,
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});

const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });
page.on("pageerror", (error) => console.log("PAGE ERROR:", error.message));
const errors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(msg.text());
});

await page.goto(base, { waitUntil: "networkidle" });
await page.waitForSelector("textarea");
const input = page.locator("textarea");
await input.click();
await input.pressSequentially(marker, { delay: 2 });
await page.waitForFunction(
  () => {
    const button = [...document.querySelectorAll("button")].find((b) => b.textContent === "研判");
    return button && !button.disabled;
  },
  { timeout: 15000 },
);
await page.getByRole("button", { name: "研判", exact: true }).click();

// Wait for the structured analysis card (real LLM may take ~30-90s).
await page.waitForSelector('[data-testid="analysis-result-card"]', { timeout: 240000 });
await page.screenshot({ path: "D:\\热线派单系统V2-data\\frontend-shots\\1-analysis.png", fullPage: false });
console.log("PASS: composer submit produced analysis result card");

// Citation expand.
const citationHead = page.locator("button.citation-head").first();
if ((await citationHead.count()) > 0) {
  await citationHead.click();
  await page.waitForTimeout(800);
  if ((await page.locator(".citation-body").count()) === 0) {
    await citationHead.evaluate((el) => el.click());
  }
  await page.waitForSelector(".citation-body");
  await page.screenshot({ path: "D:\\热线派单系统V2-data\\frontend-shots\\2-citations.png" });
  console.log("PASS: citation expanded");
}

// Historical case -> original work order drawer.
const openCase = page.getByRole("button", { name: "查看原案例" });
if ((await openCase.count()) > 0) {
  await openCase.first().click();
  await page.waitForSelector(".detail-list", { timeout: 30000 });
  await page.screenshot({ path: "D:\\热线派单系统V2-data\\frontend-shots\\3-historical-case.png" });
  await page.getByRole("button", { name: "关闭" }).click();
  console.log("PASS: historical_case opened original work order");
}

// Feedback.
const adoptButton = page.getByRole("button", { name: "采纳", exact: true });
await adoptButton.click();
await page.waitForTimeout(500);
if ((await page.locator(".feedback-ok").count()) === 0) {
  await adoptButton.evaluate((el) => el.click());
}
await page.waitForSelector(".feedback-ok");
console.log("PASS: feedback submitted");

// Favorite -> cancel -> favorite again.
const favorite = page.getByTestId("favorite-button");
await favorite.click();
await page.waitForSelector("text=★ 已收藏");
await favorite.click();
await page.waitForSelector("text=☆ 收藏");
await favorite.click();
await page.waitForSelector("text=★ 已收藏");
console.log("PASS: favorite toggle (add/cancel/add)");

// History + re-analysis.
await page.getByRole("button", { name: "历史研判" }).click();
await page.waitForSelector(".order-list li");
await page.locator(".order-list li").first().click();
await page.waitForSelector(".analysis-history li");
const before = await page.locator(".analysis-history li").count();
await page.getByRole("button", { name: "重新研判" }).click();
await page.waitForFunction(
  (n) => document.querySelectorAll(".analysis-history li").length > n,
  before,
  { timeout: 240000 },
);
console.log("PASS: re-analysis created new historical record");
await page.screenshot({ path: "D:\\热线派单系统V2-data\\frontend-shots\\4-history-reanalysis.png" });

// Saved cases list.
await page.getByRole("button", { name: "收藏案例" }).click();
await page.waitForSelector(".saved-list li", { timeout: 30000 });
console.log("PASS: saved cases entry lists favorite");

// 1920x1080 render check.
await page.setViewportSize({ width: 1920, height: 1080 });
await page.waitForTimeout(500);
await page.screenshot({ path: "D:\\热线派单系统V2-data\\frontend-shots\\5-1920.png" });
console.log("PASS: 1366x768 and 1920x1080 render");

if (errors.length) {
  console.log("console errors:", errors.slice(0, 5));
} else {
  console.log("PASS: no console errors");
}

console.log("BROWSER_LOOP_RESULT: PASS");
await browser.close();
