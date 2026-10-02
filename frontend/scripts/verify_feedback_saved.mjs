import { chromium } from "playwright-core";

const browser = await chromium.launch({
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });

const composer = page.locator('[placeholder="Send a message..."]').first();
const marker = "FeedbackSavedVerify：市民反映小区楼道照明损坏希望尽快维修";
await composer.click();
await composer.pressSequentially(marker, { delay: 1 });
await page.getByRole("button", { name: "Send message" }).click();
await page.waitForSelector("text=建议承办单位", { timeout: 240000 });
await page.getByRole("button", { name: "采纳", exact: true }).click();
await page.waitForSelector("text=已记录：采纳");
await page.getByRole("button", { name: /^☆ 收藏$/ }).click();
await page.waitForSelector("text=已收藏");
await page.screenshot({ path: "feedback-saved.png" });
console.log("FEEDBACK_SAVED: PASS");
await browser.close();
