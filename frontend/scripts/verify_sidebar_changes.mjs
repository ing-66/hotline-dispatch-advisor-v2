import { chromium } from "playwright-core";

const apiBase = "http://127.0.0.1:8000";
const orderPage = await (await fetch(`${apiBase}/api/work-orders?page=1&page_size=20`)).json();
const order = orderPage.items.find((item) => item.source_case_id === null);
const analysisPage = await (
  await fetch(`${apiBase}/api/work-orders/${order.id}/analyses?page=1&page_size=20`)
).json();
let saved = null;
if (analysisPage.items.length > 0) {
  saved = await (
    await fetch(`${apiBase}/api/saved-cases`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ work_order_id: order.id, analysis_id: analysisPage.items[0].id, note: "Visual verify saved case" }),
    })
  ).json();
}

const browser = await chromium.launch({
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
await page.waitForSelector('[data-slot="aui_thread-list-item"]');

const anchors = await page.locator('.aui-sidebar-header a[href*="assistant-ui.com"]').count();
const github = await page.getByText("GitHub", { exact: true }).count();
const settings = await page.getByText("Settings", { exact: true }).count();
if (anchors !== 0) throw new Error("logo anchor still exists");
if (github !== 0) throw new Error("github footer still exists");
if (settings !== 1) throw new Error("settings footer missing");
await page.screenshot({ path: "sidebar-new.png" });

await page.getByRole("button", { name: "Work order history" }).click();
await page.waitForSelector('[role="dialog"]');
await page.locator('[role="dialog"] ul li button').first().click();
await page.waitForTimeout(1000);
await page.screenshot({ path: "work-history-new.png" });
await page.keyboard.press("Escape");

if (saved) {
  await page.getByRole("button", { name: "Saved cases" }).click();
  await page.waitForSelector('[role="dialog"]');
  await page.waitForTimeout(800);
  await page.screenshot({ path: "saved-cases-new.png" });
  await page.keyboard.press("Escape");
}
console.log("SIDEBAR_CHANGES: PASS");
await browser.close();
if (saved) await fetch(`${apiBase}/api/saved-cases/${saved.id}`, { method: "DELETE" });
