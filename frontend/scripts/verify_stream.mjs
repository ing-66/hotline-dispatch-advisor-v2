import { chromium } from "playwright-core";

const browser = await chromium.launch({
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
const composer = page.locator('[placeholder="Send a message..."]').first();
const marker = "StreamVerifyFinal：市民反映小区外墙瓷砖脱落存在安全隐患希望尽快处理";
await composer.click();
await composer.pressSequentially(marker, { delay: 1 });
await page.getByRole("button", { name: "Send message" }).click();
await page.waitForSelector("text=建议承办单位", { timeout: 240000 });
await page.waitForTimeout(1200);
await page.screenshot({ path: "stream-final.png" });
console.log("STREAM_RESULT: PASS");
await browser.close();
