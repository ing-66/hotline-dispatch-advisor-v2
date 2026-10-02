import { chromium } from "playwright-core";

const browser = await chromium.launch({
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});

for (const [width, height, name] of [[1366, 768, "popover-1366"], [1920, 1080, "popover-1920"]]) {
  const page = await browser.newPage({ viewport: { width, height } });
  await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
  const trigger = page.getByRole("button", { name: "Work order history" });
  const triggerBox = await trigger.boundingBox();
  await trigger.click();
  const popup = page.locator('[data-slot="popover-content"]');
  await popup.waitFor({ state: "visible" });
  const box = await popup.boundingBox();
  if (!box || !triggerBox) throw new Error("missing boxes");
  if (box.width < 800 || box.height > 620 || box.width <= box.height) throw new Error("not wide panel");
  if (box.x < triggerBox.x + triggerBox.width - 4) throw new Error("not anchored right of trigger");
  if (Math.abs(box.y - triggerBox.y) > 30) throw new Error("not start aligned");
  if ((await page.locator('[data-slot="dialog-content"]').count()) > 0) throw new Error("old dialog still rendered");
  await page.screenshot({ path: `${name}.png` });
  await page.close();
}
console.log("WORKORDER_POPOVER: PASS");
await browser.close();
