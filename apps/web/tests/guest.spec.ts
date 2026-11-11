import { expect, test } from "@playwright/test";

const baseURL = process.env.NEXUS_GUEST_BROWSER_URL;
test.use({ baseURL, ignoreHTTPSErrors: true });
test.skip(!baseURL, "Requires the isolated guest browser fixture.");

test("disabled guest access is distinct from a connection failure", async ({ page }) => {
  await page.route("**/api/auth/me", (route) => route.fulfill({ status: 401 }));
  await page.route("**/api/auth/guest", (route) =>
    route.fulfill({
      status: 404,
      json: { code: "guest_access_disabled", detail: "Guest access is unavailable on this server." },
    }),
  );
  await page.goto("/");
  const alert = page.getByRole("main").getByRole("alert");
  const retry = page.getByRole("button", { name: "Retry connection" });
  await expect(alert).toContainText("Guest access is disabled on this deployment.");
  await expect(retry).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Select LLM", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Send question" })).toBeDisabled();

  await page.unroute("**/api/auth/me");
  await page.route("**/api/auth/me", (route) => route.abort("connectionfailed"));
  await page.reload();
  await expect(alert).toContainText("Could not reach the NEXUS server.");
  await expect(retry).toBeVisible();
});

test("a fresh guest session persists across the application views", async ({ page }) => {
  const initialized = page.waitForResponse((response) =>
    response.url().endsWith("/api/auth/guest") && response.request().method() === "POST",
  );
  await page.goto("/");
  const response = await initialized;
  expect(response.status()).toBe(200);
  expect(await response.request().headerValue("origin")).toBe(new URL(page.url()).origin);
  const cookie = (await page.context().cookies()).find((item) => item.name === "__Host-nexus_guest");
  expect(cookie).toMatchObject({ httpOnly: true, secure: true, sameSite: "Strict", path: "/" });
  await expect(page.locator(".context-workspace")).toHaveText("Personal workspace");
  const identity = await page.request.get("/api/auth/me");
  expect(identity.ok()).toBe(true);
  expect(await identity.json()).toMatchObject({ guest: true, user: null });

  async function workspaces() {
    const result = await page.request.get("/api/workspaces");
    expect(result.ok()).toBe(true);
    return result.json();
  }
  const original = await workspaces();
  expect(original).toHaveLength(1);
  for (const [path, heading] of [
    ["/", /Your knowledge/],
    ["/library", "A home for your sources."],
    ["/vaults", "Your notes belong together."],
    ["/graph", "A map of your thinking."],
    ["/diagnostics", "Understand your workspace."],
    ["/settings", "Your models. Your choice."],
    ["/models", "Select an LLM"],
  ] as const) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
    await expect(page.getByLabel("Username")).toHaveCount(0);
    await expect(page.getByLabel("Setup token")).toHaveCount(0);
  }
  await expect(page.getByRole("combobox", { name: "Provider", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Provider", exact: true })).toBeVisible();
  expect(await workspaces()).toEqual(original);
});

test("homepage renders immediately and the mobile model picker opens", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  let unblock!: () => void;
  const wait = new Promise<void>((resolve) => { unblock = resolve; });
  await page.route("**/api/auth/me", async (route) => {
    await wait;
    await route.continue();
  });
  try {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /Your knowledge/ })).toBeVisible();
    await expect(page.getByRole("link", { name: "Select an LLM to start chatting" })).toBeVisible();
    await expect(page.getByLabel("Username")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Send question" })).toBeDisabled();
    await page.getByRole("link", { name: "Select LLM", exact: true }).click();
    await expect(page).toHaveURL(/\/models$/);
    await expect(page.getByRole("heading", { name: "Select an LLM" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Select LLM", exact: true })).toBeInViewport();
  } finally {
    unblock();
  }
  await expect(page.getByRole("combobox", { name: "Provider", exact: true })).toBeVisible();
});

test("guest tests a key, selects and switches a model, chats, and removes the key", async ({ page, browser }) => {
  const key = "fixture-model-key-12345";
  const replacement = "fixture-replacement-key-67890";
  const badKey = "invalid-fixture-key-000";
  await page.goto("/");
  await page.getByRole("link", { name: "Select LLM", exact: true }).click();
  await page.getByRole("combobox", { name: "Provider", exact: true }).selectOption("openrouter");
  const input = page.getByLabel("API key", { exact: true });
  await expect(input).toHaveAttribute("type", "password");
  await input.fill(badKey);
  await page.getByRole("button", { name: "Show key" }).click();
  await expect(input).toHaveAttribute("type", "text");
  await page.getByRole("button", { name: "Hide key" }).click();
  const check = page.getByRole("button", { name: "Test connection and load models" });
  await check.click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Authentication failed");
  await expect(page.getByRole("main").getByRole("alert")).not.toContainText(badKey);
  await input.fill(key);
  await check.click();
  await expect(page.getByRole("status").filter({ hasText: "Connection verified" })).toBeVisible();
  await page.getByRole("combobox", { name: "Model", exact: true }).selectOption("fixture/first");
  const save = page.getByRole("button", { name: "Save and use model" });
  await expect(save).toBeDisabled();
  await page.getByLabel(/I allow OpenRouter/).check();
  await save.click();
  await expect(page).toHaveURL(/\/$/);
  const current = page.getByRole("link", { name: "Change model: fixture/first" });
  await expect(current).toBeVisible();
  await page.reload();
  await expect(current).toBeVisible();
  const question = page.locator("#question");
  await question.fill("Hello from a private guest");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.getByText("Fixture response from fixture/first using the first key.")).toBeVisible();
  await question.fill("Report a provider unavailable error");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Provider request failed");
  await expect(page.getByRole("main").getByRole("alert")).not.toContainText(key);
  await current.click();
  await expect(input).toHaveValue("");
  await input.fill(replacement);
  await check.click();
  await page.getByRole("combobox", { name: "Model", exact: true }).selectOption("fixture/second");
  await save.click();
  const switched = page.getByRole("link", { name: "Change model: fixture/second" });
  await expect(switched).toBeVisible();
  await question.fill("Which model is active?");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.getByText("Fixture response from fixture/second using the replacement key.")).toBeVisible();

  await switched.click();
  await page.getByRole("combobox", { name: "Provider", exact: true }).selectOption("openai");
  await input.fill(key);
  await check.click();
  await page.getByRole("combobox", { name: "Model", exact: true }).selectOption("fixture-openai-chat");
  await page.getByLabel(/I allow OpenAI/).check();
  await expect(save).toBeDisabled();
  await page.getByLabel(/I agree to the provider’s billing terms/).check();
  await save.click();
  const openai = page.getByRole("link", { name: "Change model: fixture-openai-chat" });
  await expect(openai).toBeVisible();
  await question.fill("Which provider is active?");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.getByText("Fixture response from fixture-openai-chat using the first key.")).toBeVisible();

  const guest = await browser.newContext({ baseURL, ignoreHTTPSErrors: true });
  try {
    const [one, two] = await Promise.all([guest.newPage(), guest.newPage()]);
    const workspacesLoaded = [one, two].map((tab) =>
      tab.waitForResponse((response) => response.url().endsWith("/api/workspaces") && response.ok()),
    );
    await Promise.all([one.goto("/"), two.goto("/")]);
    await expect(one.getByRole("link", { name: "Select LLM", exact: true })).toBeVisible();
    await expect(two.getByRole("link", { name: "Select LLM", exact: true })).toBeVisible();
    await expect.poll(async () => (await guest.cookies()).some((cookie) => cookie.name === "__Host-nexus_guest")).toBe(true);
    const [first, second] = await Promise.all([
      page.request.get("/api/workspaces").then((response) => response.json()),
      guest.request.get("/api/workspaces").then((response) => response.json()),
    ]);
    expect(first[0].id).not.toBe(second[0].id);
    for (const loaded of await Promise.all(workspacesLoaded))
      expect((await loaded.json())[0].id).toBe(second[0].id);
    expect((await guest.request.get(`/api/workspaces/${first[0].id}/chats`)).status()).toBe(404);
    const cookies = await guest.cookies();
    expect(cookies.find((cookie) => cookie.name === "__Host-nexus_guest")).toMatchObject({
      httpOnly: true, secure: true, sameSite: "Strict", path: "/",
    });
    await guest.clearCookies();
    const renewed = one.waitForResponse((response) => response.url().endsWith("/api/workspaces") && response.ok());
    await one.reload();
    expect((await (await renewed).json())[0].id).not.toBe(second[0].id);
  } finally {
    await guest.close();
  }

  await openai.click();
  await page.getByRole("button", { name: "Remove saved key" }).click();
  await expect(page.getByText("Saved API key removed.")).toBeVisible();
  await page.getByRole("banner").getByRole("link", { name: "NEXUS home" }).click();
  await expect(page.getByRole("link", { name: "Select an LLM to start chatting" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Send question" })).toBeDisabled();
});
