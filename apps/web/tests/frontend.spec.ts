import { expect, test, type Page } from "@playwright/test";
import { showTestModel } from "./local-chat-fixture";

const api = "http://127.0.0.1:8000";
let workspaceId: string;
let chatId: string;
let answer: Record<string, unknown>;
let browserErrors: string[];

test.beforeAll(async ({ request }) => {
  const created = await request.post(`${api}/api/workspaces`, {
    data: { name: `Frontend verification ${Date.now()}` },
  });
  workspaceId = (await created.json()).id;
  const upload = await request.post(
    `${api}/api/workspaces/${workspaceId}/documents`,
    {
      multipart: {
        file: {
          name: "frontend.md",
          mimeType: "text/markdown",
          buffer: Buffer.from(
            "# Frontend evidence\nThe FRONTENDPROOF release preserves verified citations and keyboard navigation.",
          ),
        },
      },
    },
  );
  expect(upload.ok()).toBeTruthy();
  await expect
    .poll(
      async () =>
        (
          await (
            await request.get(`${api}/api/workspaces/${workspaceId}/documents`)
          ).json()
        ).filter((d: { status: string }) => d.status === "ready").length,
    )
    .toBe(1);
  chatId = (
    await (
      await request.post(`${api}/api/workspaces/${workspaceId}/chats`, {
        data: {},
      })
    ).json()
  ).id;
  const response = await request.post(
    `${api}/api/chats/${chatId}/messages?workspace_id=${workspaceId}`,
    { data: { content: "What does FRONTENDPROOF preserve?" } },
  );
  expect(response.ok()).toBeTruthy();
  answer = await response.json();
});
test.beforeEach(async ({ page }) => {
  browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.addInitScript(
    (id) => localStorage.setItem("nexus-workspace", id),
    workspaceId,
  );
});
test.afterEach(async () => {
  expect(browserErrors).toEqual([]);
});

async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
}

test("rail physically expands without content movement; pin, theme, tabs and one-entry brand persist", async ({
  page,
}) => {
  await page.goto("/");
  const brand = page.locator(".workspace-context .brand");
  await expect(brand).toHaveAttribute("data-reveal", "true");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const link = page.getByRole("link", {
    name: "Document library",
    exact: true,
  });
  await page.mouse.move(800, 800);
  const initial = await link.boundingBox();
  const main = await page.locator("#main").boundingBox();
  await link.hover();
  await expect
    .poll(async () => (await link.boundingBox())!.width)
    .toBeGreaterThan(190);
  expect(initial!.width).toBeLessThan(60);
  expect((await page.locator("#main").boundingBox())!.x).toBe(main!.x);
  await page.mouse.move(800, 800);
  await link.focus();
  await expect
    .poll(async () => (await link.boundingBox())!.width)
    .toBeGreaterThan(190);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/library/);
  await expect(page.locator(".workspace-context .brand")).not.toHaveAttribute(
    "data-reveal",
    "true",
  );
  await page
    .getByRole("button", { name: "Pin navigation expanded", exact: true })
    .click();
  await page.reload();
  await expect(page.locator(".navigation-rail")).toHaveClass(/is-pinned/);
  await expect(page.locator(".workspace-context .brand")).toHaveAttribute(
    "data-reveal",
    "true",
  );
  await page
    .getByRole("button", { name: "Unpin navigation", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Appearance", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Switch to light appearance" })
    .click();
  await page.keyboard.press("Escape");
  await page
    .getByRole("link", { name: "Settings & providers", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page
    .getByRole("tab", { name: "Models & privacy", exact: true })
    .focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    page.getByRole("tab", { name: "Retrieval & indexes", exact: true }),
  ).toBeFocused();
  await expect(
    page.getByRole("tab", { name: "Retrieval & indexes", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Control+k");
  await expect(
    page.getByRole("dialog", { name: "Search workspace", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
});

test("responsive routes, touch drawer and reduced motion remain usable", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const width of [1920, 1440, 1280, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const route of [
      "/",
      "/library",
      "/vaults",
      "/graph",
      "/settings",
      "/diagnostics",
    ]) {
      await page.goto(route);
      await expect(page.locator("#main h1").first()).toBeVisible();
      await noOverflow(page);
    }
  }
  await page.goto("/");
  await expect(
    page.getByLabel("Ask a question about your documents"),
  ).toBeVisible();
  const duration = await page
    .locator(".brand-letters > span")
    .first()
    .evaluate((el) => getComputedStyle(el).animationDuration);
  expect(parseFloat(duration)).toBeLessThan(0.01);
  await page.getByRole("button", { name: "Open navigation" }).click();
  const drawer = page.getByRole("dialog", { name: "Navigation", exact: true });
  await expect(drawer).toBeVisible();
  expect(
    await drawer.evaluate((el) => el.contains(document.activeElement)),
  ).toBe(true);
  await page
    .getByRole("link", { name: "Document library", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "A home for your sources." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.keyboard.press("Escape");
  await expect(drawer).not.toBeVisible();
  await page.screenshot({
    path: "../../artifacts/frontend-mobile.png",
    fullPage: true,
  });
});

test("rich answers safely render math, tables, code and verified source buttons", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const citations = answer.citations as { citation_id: string }[];
  expect(citations.length).toBeGreaterThan(0);
  const content = [
    "## Rendered answer",
    `Verified evidence [${citations[0].citation_id}]. Unknown [C9999].`,
    "",
    "| Item | Value |",
    "| --- | --- |",
    "| Proof | Present |",
    "",
    "```js",
    "const proof = true;",
    "```",
    "",
    "Inline $x^2$ and math:",
    "",
    "$$",
    "E=mc^2",
    "$$",
    "",
    "![beacon](https://tracker.invalid/pixel.png)",
    "",
    "[Unsafe](javascript:alert(1))",
    "<script>window.__unsafe = true</script>",
    '<img src="https://tracker.invalid/html.png" onerror="window.__unsafe=true">',
  ].join("\n");
  const remote: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("tracker.invalid")) remote.push(request.url());
  });
  await page.route(`**/api/chats/${chatId}?workspace_id=*`, (route) =>
    route.fulfill({ json: { messages: [{ ...answer, content }] } }),
  );
  await page.goto(`/?chat=${chatId}`);
  await expect(
    page.getByRole("heading", { name: "Rendered answer" }),
  ).toBeVisible();
  await expect(page.locator(".markdown-body table td").first()).toHaveText(
    "Proof",
  );
  await expect(page.locator(".katex")).toHaveCount(2);
  await page.getByRole("button", { name: "Copy code", exact: true }).click();
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toContain("const proof = true;");
  expect(
    await page.locator('.markdown-body a[href^="javascript:"]').count(),
  ).toBe(0);
  expect(
    await page.locator(".markdown-body img,.markdown-body script").count(),
  ).toBe(0);
  expect(
    await page.evaluate(
      () => (window as unknown as { __unsafe?: boolean }).__unsafe,
    ),
  ).toBeUndefined();
  expect(remote).toEqual([]);
  await page.locator(".inline-citation").first().click();
  await expect(page.getByRole("dialog")).toContainText("FRONTENDPROOF");
  await expect(page.locator("mark")).not.toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.locator(".inline-citation").first()).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await noOverflow(page);
  await page.screenshot({
    path: "../../artifacts/frontend-rich-mobile.png",
    fullPage: true,
  });
});

test("large document and conversation collections keep DOM bounded and remain searchable", async ({
  page,
}) => {
  const documents = Array.from({ length: 150 }, (_, i) => ({
    id: `document-${i}`,
    title: `Knowledge ${String(i).padStart(3, "0")}`,
    status: "ready",
    error: null,
    extension: ".md",
    size: 1000,
    created_at: "2026-11-04T00:00:00Z",
  }));
  const chats = Array.from({ length: 150 }, (_, i) => ({
    id: `chat-${i}`,
    title: `Conversation ${String(i).padStart(3, "0")}`,
  }));
  await page.route(`**/api/workspaces/${workspaceId}/documents`, (route) =>
    route.fulfill({ json: documents }),
  );
  await page.route(`**/api/workspaces/${workspaceId}/chats`, (route) =>
    route.fulfill({ json: chats }),
  );
  await page.goto("/library");
  await expect(page.locator(".document-row")).toHaveCount(30);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.locator(".document-row").first()).toContainText(
    "Knowledge 030",
  );
  await page.getByRole("button", { name: "List view", exact: true }).click();
  await expect
    .poll(() => page.locator(".document-row").count())
    .toBeLessThan(25);
  const list = page.locator(".virtual-document-list");
  await list.evaluate((el) => (el.scrollTop = el.scrollHeight));
  await expect(page.locator(".document-row").last()).toContainText(
    "Knowledge 149",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await noOverflow(page);
  await page.goto("/");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect.poll(() => page.locator(".chat-row").count()).toBeLessThan(40);
  await page.getByLabel("Search conversations", { exact: true }).fill("149");
  await expect(page.locator(".chat-row")).toHaveCount(1);
  await expect(page.locator(".chat-row")).toContainText("Conversation 149");
});

test("reading position survives answer completion and stop-waiting state is explicit", async ({
  page,
}) => {
  await showTestModel(page);
  const long = Array.from(
    { length: 60 },
    (_, i) =>
      `Paragraph ${i}. Evidence remains readable while a new answer is prepared.`,
  ).join("\n\n");
  await page.route(`**/api/chats/${chatId}?workspace_id=*`, (route) =>
    route.fulfill({ json: { messages: [{ ...answer, content: long }] } }),
  );
  await page.route(
    `**/api/chats/${chatId}/messages?workspace_id=*`,
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1600));
      await route
        .fulfill({
          json: { ...answer, id: "completion", content: "Completed answer." },
        })
        .catch(() => {});
    },
  );
  await page.goto(`/?chat=${chatId}`);
  await expect(page.locator(".message.assistant")).toContainText(
    "Paragraph 59",
  );
  await page
    .getByLabel("Ask a question about your documents")
    .fill("Another question");
  await page
    .getByRole("button", { name: "Send question", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Stop waiting", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Switch workspace", exact: true }),
  ).toBeDisabled();
  await page.locator(".conversation").evaluate((el) => {
    el.scrollTop = 0;
    el.dispatchEvent(new Event("scroll"));
  });
  await expect(page.locator(".message.assistant").last()).toContainText(
    "Completed answer.",
  );
  expect(
    await page.locator(".conversation").evaluate((el) => el.scrollTop),
  ).toBeLessThan(100);
  await page
    .getByLabel("Ask a question about your documents")
    .fill("Stop this wait");
  await page
    .getByRole("button", { name: "Send question", exact: true })
    .click();
  await page.getByRole("button", { name: "Stop waiting", exact: true }).click();
  await expect(
    page.getByText(/The server may still save this answer/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Send question", exact: true }),
  ).toBeEnabled();
});
