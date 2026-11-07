import { expect, test } from "@playwright/test";

test("vault import, graph navigation, filtered chat, snapshot revision and index rollback", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const response = await request.post("http://127.0.0.1:8000/api/workspaces", {
    data: { name: `Vault browser ${Date.now()}` },
  });
  expect(response.ok()).toBeTruthy();
  const workspace = await response.json();
  await page.addInitScript(
    (id) => localStorage.setItem("nexus-workspace", id),
    workspace.id,
  );
  await page.goto("/vaults");
  await expect(
    page.getByRole("heading", { name: "Your notes belong together." }),
  ).toBeVisible();
  await page
    .getByLabel("Vault ZIP file", { exact: true })
    .setInputFiles("../../examples/evaluation/vault.zip");
  await expect(
    page.locator(".document-row .document-status.ready"),
  ).toHaveCount(10, { timeout: 30000 });
  await expect(page.locator(".sync-card")).toContainText(
    "Last successful scan",
  );
  await page
    .getByRole("button", { name: "Projects/Aurora.md", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("14 November 2026");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Connections for Projects/Aurora.md" })
    .click();
  await expect(page.locator(".connection-detail")).toContainText("Backlinks");
  await page.screenshot({
    path: "../../artifacts/phase2-vault-desktop.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: /Explore graph/ }).click();
  await expect(page.locator(".graph-node-list button")).not.toHaveCount(0);
  await page
    .locator(".graph-node-list")
    .getByRole("button", { name: /People\/Mira.md/ })
    .click();
  await expect(page.locator("svg [data-node].selected")).toHaveCount(1);
  await expect(page.locator("svg .graph-edge.highlighted")).not.toHaveCount(0);
  await expect(page.locator("svg [data-node].connected")).not.toHaveCount(0);
  await page.getByRole("button", { name: "Zoom in graph" }).click();
  await expect(page.locator(".graph-zoom")).toContainText("120%");
  await page.getByRole("button", { name: "Open note source" }).click();
  await expect(page.getByRole("dialog")).toContainText("Mira is the owner");
  await page.getByRole("button", { name: "Close source" }).click();
  await page.screenshot({
    path: "../../artifacts/phase2-graph-desktop.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "Ask your knowledge" }).click();
  await page
    .getByLabel("Retrieval mode", { exact: true })
    .selectOption("keyword");
  await page.getByRole("button", { name: /Source filters/ }).click();
  const vaults = await (
    await request.get(
      `http://127.0.0.1:8000/api/workspaces/${workspace.id}/vaults`,
    )
  ).json();
  await page
    .getByRole("combobox", { name: "Vault", exact: true })
    .selectOption(vaults[0].id);
  await page.getByLabel("Tags (match any)").fill("launch");
  await page.getByLabel("Diagnostics", { exact: true }).check();
  await page
    .getByLabel("Ask a question about your documents")
    .fill("When does Aurora launch?");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.locator(".message.assistant")).toContainText("November");
  await page.locator(".message-diagnostics summary").click();
  await expect(page.locator(".message-diagnostics")).toContainText("lexical_0");
  await page.locator(".inline-citation").first().click();
  await expect(page.locator("mark")).not.toBeEmpty();
  await page.getByRole("button", { name: "Close source" }).click();
  await page.getByRole("link", { name: "Obsidian vaults" }).click();
  await page.getByRole("button", { name: "Update snapshot" }).click();
  await page
    .getByLabel("Vault ZIP file", { exact: true })
    .setInputFiles("../../examples/evaluation/vault-update.zip");
  await expect(
    page.locator(".document-row .document-status.ready"),
  ).toHaveCount(9, { timeout: 30000 });
  await page
    .getByRole("button", { name: "Projects/Aurora.md", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("PHASE2NEWTOKEN");
  await page.getByRole("button", { name: "Close source" }).click();
  await page.getByRole("link", { name: "Ask your knowledge" }).click();
  await page.locator(".chat-title").first().click();
  await expect(page.locator(".inline-citation").first()).toBeDisabled();
  await expect(page.locator(".inline-citation").first()).toContainText(
    "Source unavailable",
  );
  await page.getByRole("link", { name: "Settings & providers" }).click();
  await page
    .getByRole("tab", { name: "Retrieval & indexes", exact: true })
    .click();
  await page.getByLabel("Vector dimension", { exact: true }).fill("64");
  await page.getByRole("button", { name: "Build & validate index" }).click();
  const active = page
    .locator(".index-version")
    .filter({ hasText: "Active index" });
  await expect(active).toContainText("64 dimensions", { timeout: 30000 });
  await page.getByRole("button", { name: "Activate / rollback" }).click();
  await expect(active).toContainText("384 dimensions");
  await page.screenshot({
    path: "../../artifacts/phase2-index-settings.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/graph");
  await expect(
    page.getByRole("heading", { name: "A map of your thinking." }),
  ).toBeVisible();
  await expect(page.locator(".graph-node-list button")).not.toHaveCount(0);
  await page.screenshot({
    path: "../../artifacts/phase2-graph-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    ),
  ).toBeFalsy();
  expect(errors).toEqual([]);
});
