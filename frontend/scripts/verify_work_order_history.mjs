import { chromium } from "playwright-core";

const apiBase = "http://127.0.0.1:8000";
const createOrder = await fetch(`${apiBase}/api/work-orders`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    title: "WorkOrderHistory Verify Ticket",
    content: "WorkOrderHistory Verify Ticket content building facility issue",
    request_type: "求助",
  }),
});
const order = await createOrder.json();
for (let i = 0; i < 2; i++) {
  const response = await fetch(`${apiBase}/api/work-orders/${order.id}/analyses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!response.ok) throw new Error(`analysis ${i + 1} failed: ${await response.text()}`);
}

const browser = await chromium.launch({
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
await page.getByRole("button", { name: "Work order history" }).click();
await page.waitForSelector("text=工单历史");
const row = page.getByText("WorkOrderHistory Verify Ticket", { exact: false }).first();
await row.click();
await page.waitForSelector("text=研判 #1");
await page.waitForSelector("text=研判 #2");
await page.screenshot({ path: "work-order-history.png" });
console.log("WORK_ORDER_HISTORY: PASS");
await browser.close();
