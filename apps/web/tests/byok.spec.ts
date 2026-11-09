import { expect, test } from "@playwright/test";
import { showTestModel } from "./local-chat-fixture";

const api = "http://127.0.0.1:8000";
const root = "/api/me/provider-configurations";
const fakeKey = "browser-only-fake-secret-12345";
const models = [
  {
    id: "openrouter/browser-model",
    name: "Browser model",
    provider: "openrouter",
    context_window: 8192,
    max_output_tokens: 2048,
    supported_parameters: ["temperature"],
    capabilities: ["text"],
    cost_status: "unknown",
    pricing: null,
  },
];
let errors: string[];
test.beforeEach(async ({ page, request }) => {
  expect(
    (await (await request.get(`${api}/health`)).json()).embedding_provider,
  ).toBe("hash");
  await request.delete(`${api}/api/me/provider-default`);
  const previous = await (await request.get(`${api}${root}`)).json();
  for (const config of previous.configurations.filter((c: { name: string }) =>
    ["Private cloud browser", "Local browser model"].includes(c.name),
  ))
    await request.delete(`${api}${root}/${config.id}`);
  errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const workspace = await (
    await request.post(`${api}/api/workspaces`, {
      data: { name: `BYOK browser ${Date.now()}` },
    })
  ).json();
  await page.addInitScript(
    (id) => localStorage.setItem("nexus-workspace", id),
    workspace.id,
  );
});
test.afterEach(() => {
  expect(errors).toEqual([]);
});

test("cloud key masking, discovery, private persistence, consent, defaults and key removal", async ({
  page,
  request,
}) => {
  // Only cloud metadata is mocked. CRUD, encryption, ownership and selection hit the real isolated API.
  await page.route("**/api/me/provider-configurations/preview", (route) =>
    route.fulfill({
      json: {
        models,
        connection: {
          status: "connected",
          message:
            "Provider authentication succeeded. Selected model is listed; inference was not run.",
        },
      },
    }),
  );
  await page.route(
    /\/api\/me\/provider-configurations\/[^/]+\/models$/,
    (route) => route.fulfill({ json: { models } }),
  );
  await page.goto("/settings");
  await expect(
    page.getByRole("heading", { name: "Intelligence on your terms." }),
  ).toBeVisible();
  await page
    .getByLabel("Configuration name", { exact: true })
    .fill("Private cloud browser");
  const key = page.getByLabel("Provider API key", { exact: true });
  await expect(key).toHaveAttribute("type", "password");
  await key.fill(fakeKey);
  await page
    .getByRole("button", { name: "Show unsaved key", exact: true })
    .click();
  await expect(key).toHaveAttribute("type", "text");
  await page
    .getByRole("button", { name: "Hide unsaved key", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Test connection & load models", exact: true })
    .click();
  await expect(page.locator(".connection-status")).toContainText(
    "authentication succeeded",
  );
  await page
    .getByLabel("Search provider models", { exact: true })
    .fill("browser");
  await page
    .getByLabel("Available provider models", { exact: true })
    .selectOption("openrouter/browser-model");
  await expect(page.getByLabel("Manual model ID", { exact: true })).toHaveValue(
    "openrouter/browser-model",
  );
  await page
    .getByRole("checkbox", { name: /I allow relevant evidence/ })
    .check();
  await page
    .getByRole("checkbox", { name: /I acknowledge provider billing/ })
    .check();
  const savedPromise = page.waitForResponse(
    (r) => r.url().endsWith(root) && r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Save personal configuration", exact: true })
    .click();
  const saved = await savedPromise;
  expect(saved.status()).toBe(201);
  expect(await saved.text()).not.toContain(fakeKey);
  await expect(key).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Show unsaved key", exact: true }),
  ).toBeDisabled();
  expect(
    await page.evaluate(() =>
      JSON.stringify({
        local: { ...localStorage },
        session: { ...sessionStorage },
      }),
    ),
  ).not.toContain(fakeKey);
  expect(await (await request.get(`${api}${root}`)).text()).not.toContain(
    fakeKey,
  );
  await page
    .getByRole("button", { name: "Use here", exact: true })
    .filter({ visible: true })
    .first()
    .click();
  await expect(page.locator(".alert.error")).toContainText(
    "Both personal provider consent and workspace cloud permission",
  );
  await page
    .getByRole("checkbox", {
      name: "Allow cloud excerpt transmission for this workspace",
      exact: true,
    })
    .check();
  await page
    .getByRole("button", { name: "Use here", exact: true })
    .filter({ visible: true })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: "Active here", exact: true }).first(),
  ).toBeVisible();
  await page
    .locator(".saved-model")
    .filter({ hasText: "Private cloud browser" })
    .getByRole("button", { name: "Make default", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Clear personal default", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Clear personal default", exact: true })
    .click();
  await page.goto("/");
  await expect(
    page.getByRole("link", { name: "Change model: openrouter/browser-model" }),
  ).toBeVisible();
  await page.goto("/settings");
  await page
    .getByRole("button", { name: "Edit Private cloud browser", exact: true })
    .click();
  await expect(key).toHaveValue("");
  await key.fill("replacement-browser-secret-67890");
  await page
    .getByRole("button", { name: "Save personal configuration", exact: true })
    .click();
  await expect(key).toHaveValue("");
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("button", { name: "Remove stored key", exact: true })
    .click();
  await expect(
    page.locator(".saved-model").filter({ hasText: "Private cloud browser" }),
  ).toContainText("Credential missing");
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("button", { name: "Remove Private cloud browser", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Edit Private cloud browser",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("real local-provider discovery, grounded streaming, source verification and usage", async ({
  page,
  request,
}) => {
  await page.goto("/library");
  await page.getByLabel("Upload documents", { exact: true }).setInputFiles({
    name: "byok-browser.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(
      "# BYOKBROWSER\nBYOKBROWSER preserves verified source citations and private model configuration.",
    ),
  });
  await expect(page.locator(".document-status.ready")).toHaveCount(1, {
    timeout: 30000,
  });
  const workspaceId = await page.evaluate(() =>
    localStorage.getItem("nexus-workspace"),
  );
  const before = await (
    await request.get(`${api}/api/workspaces/${workspaceId}/documents`)
  ).json();
  await page.goto("/settings");
  await page.locator(".provider-choice").filter({ hasText: "Ollama" }).click();
  await page
    .getByLabel("Configuration name", { exact: true })
    .fill("Local browser model");
  await expect(
    page.getByLabel("Provider API key", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Test connection & load models", exact: true })
    .click();
  await expect(page.locator(".connection-status")).toContainText(
    "endpoint responded",
  );
  await page
    .getByLabel("Available provider models", { exact: true })
    .selectOption("nexus-browser-fixture");
  await page
    .getByRole("button", { name: "Save personal configuration", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Test connection & load models", exact: true })
    .click();
  await expect(
    page.locator(".saved-model").filter({ hasText: "Local browser model" }),
  ).toContainText("connected");
  await page
    .locator(".saved-model")
    .filter({ hasText: "Local browser model" })
    .getByRole("button", { name: "Use here", exact: true })
    .click();
  await page.goto("/");
  await page
    .getByLabel("Ask a question about your documents")
    .fill("What does BYOKBROWSER preserve?");
  await page
    .getByRole("button", { name: "Send question", exact: true })
    .click();
  await expect(page.locator(".provisional-message")).toContainText(
    "BYOKBROWSER",
  );
  await expect(
    page.locator(".provisional-message .inline-citation"),
  ).toHaveCount(0);
  await expect(
    page.locator(".message.assistant:not(.provisional-message)"),
  ).toContainText("verified source citations");
  await expect(page.locator(".provisional-message")).toHaveCount(0);
  await page.locator(".inline-citation").first().click();
  await expect(page.getByRole("dialog")).toContainText("BYOKBROWSER");
  await expect(page.locator("mark")).not.toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.screenshot({
    path: "../../artifacts/byok-streaming-chat.png",
    fullPage: true,
  });
  await page.goto("/settings");
  await page
    .getByRole("button", { name: "Edit Local browser model", exact: true })
    .click();
  await page
    .getByRole("checkbox", { name: /Stream provisional text/ })
    .uncheck();
  await page
    .getByRole("button", { name: "Save personal configuration", exact: true })
    .click();
  await expect(page.locator(".byok-usage")).toContainText("40 / 12");
  await page.screenshot({
    path: "../../artifacts/byok-settings-desktop.png",
    fullPage: true,
  });
  const after = await (
    await request.get(`${api}/api/workspaces/${workspaceId}/documents`)
  ).json();
  expect(
    after.map((d: { id: string; version_id: string }) => [d.id, d.version_id]),
  ).toEqual(
    before.map((d: { id: string; version_id: string }) => [d.id, d.version_id]),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Intelligence on your terms." }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../../artifacts/byok-settings-mobile.png",
    fullPage: true,
  });
});

test("native select theme and keyboard behavior, real retrieval value, favicon assets and titles", async ({
  page,
  request,
}) => {
  await showTestModel(page);
  await page.route("**/api/chats/*/messages?workspace_id=*", (route) =>
    route.fulfill({
      json: { id: "reply", role: "assistant", content: "Test answer", provider: "ollama", citations: [] },
    }),
  );
  await page.goto("/");
  await expect(page).toHaveTitle("NEXUS — Personal Knowledge Intelligence");
  const select = page.getByLabel("Retrieval mode", { exact: true });
  await expect(select).toBeEnabled();
  const dark = await select
    .locator("option")
    .last()
    .evaluate((el) => ({
      bg: getComputedStyle(el).backgroundColor,
      color: getComputedStyle(el).color,
    }));
  expect(dark.bg).toBe("rgb(20, 23, 31)");
  expect(dark.color).toBe("rgb(233, 235, 243)");
  await select.focus();
  await page.keyboard.press("ArrowDown");
  await expect(select).toHaveValue("keyword");
  await page.keyboard.press("Escape");
  await page
    .getByLabel("Ask a question about your documents")
    .fill("What does this library contain?");
  const sent = page.waitForRequest(
    (r) => r.url().includes("/messages?") && r.method() === "POST",
  );
  await page
    .getByRole("button", { name: "Send question", exact: true })
    .click();
  expect((await sent).postDataJSON().options.mode).toBe("keyword");
  await expect(page.locator(".message.assistant")).toBeVisible();
  await page
    .getByRole("button", { name: "Appearance", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Switch to light appearance", exact: true })
    .click();
  await page.keyboard.press("Escape");
  const light = await select
    .locator("option")
    .last()
    .evaluate((el) => ({
      bg: getComputedStyle(el).backgroundColor,
      color: getComputedStyle(el).color,
    }));
  expect(light.bg).toBe("rgb(255, 255, 255)");
  expect(light.color).toBe("rgb(32, 36, 49)");
  await page.screenshot({
    path: "../../artifacts/byok-select-light.png",
    fullPage: true,
  });
  for (const path of [
    "/icon.svg",
    "/favicon.ico",
    "/favicon-16x16.png",
    "/favicon-32x32.png",
    "/apple-touch-icon.png",
    "/nexus-192.png",
    "/nexus-512.png",
  ]) {
    const r = await request.get(`http://127.0.0.1:3000${path}`);
    expect(r.status(), path).toBe(200);
    expect((await r.body()).length).toBeGreaterThan(100);
  }
  await page.goto("/graph");
  await expect(page).toHaveTitle("NEXUS — Knowledge Graph");
  expect(
    await page
      .locator('link[rel="icon"][type="image/svg+xml"]')
      .getAttribute("href"),
  ).toBe("/icon.svg");
  await page.reload();
  await expect(page).toHaveTitle("NEXUS — Knowledge Graph");
  await page.goto("/settings");
  await expect(page).toHaveTitle("NEXUS — Models & Privacy");
});
