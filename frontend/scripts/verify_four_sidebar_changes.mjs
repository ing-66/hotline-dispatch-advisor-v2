import { chromium } from "playwright-core";

const apiBase = "http://127.0.0.1:8000";
const orders = await (await fetch(`${apiBase}/api/work-orders?page=1&page_size=20`)).json();
const order = orders.items.find((item) => item.source_case_id === null);
const analyses = await (
  await fetch(`${apiBase}/api/work-orders/${order.id}/analyses?page=1&page_size=20`)
).json();
let saved = null;
if (analyses.items.length > 0) {
  saved = await (
    await fetch(`${apiBase}/api/saved-cases`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ work_order_id: order.id, analysis_id: analyses.items[0].id, note: "visual verify" }),
    })
  ).json();
}

const browser = await chromium.launch({
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
await page.waitForSelector('[data-slot="aui_thread-list-new"]');

if (!(await page.locator("body").innerText()).includes("热线派单顾问")) throw new Error("logo text missing");
if ((await page.locator(".aui-sidebar-header a").count()) !== 0) throw new Error("logo is link");
const newBox = await page.locator('[data-slot="aui_thread-list-new"]').boundingBox();
const workBox = await page.getByRole("button", { name: "Work order history" }).boundingBox();
if (newBox.y >= workBox.y) throw new Error("New Thread not above Work order history");
if (!(await page.locator("body").innerText()).includes("历史对话")) throw new Error("history label missing");
await page.screenshot({ path: "sidebar-four.png" });

await page.getByRole("button", { name: "Saved cases" }).click();
await page.waitForSelector('[data-slot="popover-content"]');
await page.waitForTimeout(1000);
const savedBody = await page.locator('[data-slot="popover-content"]').innerText();
if (!savedBody.includes("取消收藏")) throw new Error("saved detail missing");
await page.screenshot({ path: "saved-popover-new.png" });
console.log("FOUR_SIDEBAR_CHANGES: PASS");
await browser.close();
if (saved) await fetch(`${apiBase}/api/saved-cases/${saved.id}`, { method: "DELETE" });
