import { chromium } from "playwright-core";

async function createConversation(title) {
  const response = await fetch("http://127.0.0.1:8000/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return response.json();
}

const first = await createConversation("Thread Action Verify One");
const second = await createConversation("Thread Action Verify Two");

const browser = await chromium.launch({
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
await page.waitForSelector('[data-slot="aui_thread-list-item"]', { timeout: 30000 });

// Rename first conversation.
const firstItem = page.locator('[data-slot="aui_thread-list-item"]', {
  hasText: "Thread Action Verify One",
});
async function openItemMenu(item) {
  await item.hover();
  await item.locator('[data-slot="aui_thread-list-item-more"]').click();
  await page.waitForTimeout(400);
  if ((await page.locator('[role="menu"]').count()) === 0) {
    await item.locator('[data-slot="aui_thread-list-item-more"]').click();
  }
}
async function clickMenuItem(label) {
  const target = page.locator('[role="menu"]').getByText(label, { exact: true });
  await target.first().click();
}

await openItemMenu(firstItem);
await clickMenuItem("Rename");
const renameInput = page.getByLabel("Rename thread");
await renameInput.fill("Renamed Thread One");
await renameInput.press("Enter");
await page.waitForSelector("text=Renamed Thread One");

// Archive renamed conversation (removed from regular list).
const renamedItem = page.locator('[data-slot="aui_thread-list-item"]', {
  hasText: "Renamed Thread One",
});
await page.mouse.click(400, 500);
await openItemMenu(renamedItem);
await clickMenuItem("Archive");
await page.waitForFunction(
  (id) => ![...document.querySelectorAll('[data-slot="aui_thread-list-item-title"]')].some((el) => el.textContent?.includes(id)),
  "Renamed Thread One",
);

// Delete second conversation.
const secondItem = page.locator('[data-slot="aui_thread-list-item"]', {
  hasText: "Thread Action Verify Two",
});
await page.mouse.click(400, 500);
await openItemMenu(secondItem);
await clickMenuItem("Delete");
await page.waitForFunction(
  (id) => ![...document.querySelectorAll('[data-slot="aui_thread-list-item-title"]')].some((el) => el.textContent?.includes(id)),
  "Thread Action Verify Two",
);

const api = await fetch(`http://127.0.0.1:8000/api/conversations?page=1&page_size=100`);
const body = await api.json();
const one = body.items.find((item) => item.id === first.id);
const two = body.items.find((item) => item.id === second.id);
if (one?.title !== "Renamed Thread One" || one?.status !== "archived") throw new Error("archive/rename mapping failed");
if (two) throw new Error("delete mapping failed");
console.log("THREAD_ACTIONS_MAPPED: PASS");
await browser.close();
