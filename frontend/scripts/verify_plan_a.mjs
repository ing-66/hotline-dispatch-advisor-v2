import { mkdirSync } from "node:fs";
import { chromium } from "playwright-core";

mkdirSync("D:\\热线派单系统V2-data\\frontend-shots\\starter", { recursive: true });
const browser = await chromium.launch({
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
const marker = "PlanA历史对话验证：市民反映小区路灯故障希望尽快维修";

await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
const composer = page.locator('[placeholder="Send a message..."]').first();
await composer.click();
await composer.pressSequentially(marker, { delay: 1 });
await page.getByRole("button", { name: "Send message" }).click();
await page.waitForSelector("text=建议承办单位", { timeout: 240000 });
await page.screenshot({ path: "D:\\热线派单系统V2-data\\frontend-shots\\starter\\plan-a-result.png" });

// Reload: conversation must appear in the original Thread List.
await page.reload({ waitUntil: "networkidle" });
await page.waitForSelector("text=New Thread");
await page.waitForSelector('[data-slot="aui_thread-list-item"]', { timeout: 30000 });
const itemText = await page.locator('[data-slot="aui_thread-list-item"]').first().innerText();
if (!itemText.includes(marker.slice(0, 8))) throw new Error("persisted conversation not in ThreadList");

await page.locator('[data-slot="aui_thread-list-item"]').first().click();
await page.waitForSelector("text=建议承办单位", { timeout: 30000 });
await page.screenshot({ path: "D:\\热线派单系统V2-data\\frontend-shots\\starter\\plan-a-thread-open.png" });
console.log("PLAN_A_THREAD_LIST: PASS");
await browser.close();
