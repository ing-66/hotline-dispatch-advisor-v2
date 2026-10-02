import { chromium } from "playwright-core";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const base = process.env.FRONTEND_URL || "http://127.0.0.1:3000";
const marker = `【Starter恢复浏览器验证-${Date.now()}】市民反映小区临街商铺招牌松动，物业未及时处理，希望主管部门协调处置。`;
const shots = "D:\\热线派单系统V2-data\\frontend-shots\\starter";
import { mkdirSync } from "node:fs";
mkdirSync(shots, { recursive: true });

const browser = await chromium.launch({
  executablePath: CHROME,
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});

for (const [width, height, name] of [[1366, 768, "initial-1366"], [1920, 1080, "initial-1920"]]) {
  const page = await browser.newPage({ viewport: { width, height } });
  await page.goto(base, { waitUntil: "networkidle" });
  await page.waitForSelector("text=How can I help you today?");
  await page.waitForSelector('[placeholder="Send a message..."]');
  const body = await page.locator("body").innerText();
  for (const expected of ["assistant-ui", "New Thread", "How can I help you today?"]) {
    if (!body.includes(expected)) throw new Error(`missing initial text: ${expected}`);
  }
  if (body.includes("热线研判工作台") || body.includes("历史研判")) {
    throw new Error("custom workspace still present");
  }
  await page.screenshot({ path: `${shots}\\${name}.png` });
  await page.close();
}

const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto(base, { waitUntil: "networkidle" });

const composer = page.locator('[placeholder="Send a message..."]').first();
await composer.click();
await composer.pressSequentially(marker, { delay: 2 });
const send = page.getByRole("button", { name: "Send message" });
await send.waitFor({ state: "visible" });
await send.click();

await page.waitForSelector("text=建议承办单位", { timeout: 240000 });
await page.screenshot({ path: `${shots}\\result-message.png` });
console.log("PASS: original composer -> real analysis rendered as assistant message");
console.log("STARTER_BROWSER_RESULT: PASS");
await browser.close();
