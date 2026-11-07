import { expect, test } from "@playwright/test";

test("workspace route persistence, diagnostics, comparison, feedback and portable settings", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const response = await request.post("http://127.0.0.1:8000/api/workspaces", {
    data: { name: `Release UI ${Date.now()}` },
  });
  const workspace = await response.json();
  await page.addInitScript(
    (id) => localStorage.setItem("nexus-workspace", id),
    workspace.id,
  );
  await page.goto("/library");
  await page.getByLabel("Upload documents", { exact: true }).setInputFiles({
    name: "release.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(
      "# Release evidence\nThe RELEASEPROOF system uses a tested isolated backup and verified citations.",
    ),
  });
  await expect(page.locator(".document-status.ready")).toHaveCount(1, {
    timeout: 30000,
  });
  await page.goto("/settings");
  await page.locator(".workspace-administration > summary").click();
  await page
    .getByLabel("Workspace model ID", { exact: true })
    .fill("release-demo-model");
  await page
    .getByRole("button", { name: "Save workspace model policy", exact: true })
    .click();
  await expect(
    page.locator(".workspace-administration").getByRole("status"),
  ).toContainText("Workspace policy and privacy permission saved");
  await page.reload();
  await page.locator(".workspace-administration > summary").click();
  await expect(
    page.getByLabel("Workspace model ID", { exact: true }),
  ).toHaveValue("release-demo-model");
  const downloadPromise = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export settings", exact: true })
    .click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("nexus-settings-v1.json");
  await page.goto("/");
  await page
    .getByRole("textbox", { name: "Ask a question about your documents" })
    .fill("RELEASEPROOF backup");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.locator(".message.assistant")).toHaveCount(1, {
    timeout: 30000,
  });
  await page
    .getByRole("button", { name: "wrong citation", exact: true })
    .click();
  await expect(page.locator(".answer-feedback")).toContainText(
    "Feedback saved privately",
  );
  await page.goto("/diagnostics");
  await expect(
    page.getByRole("heading", { name: "Understand your workspace." }),
  ).toBeVisible();
  await page
    .getByLabel("Comparison question", { exact: true })
    .fill("RELEASEPROOF backup");
  await page
    .getByRole("button", {
      name: "Compare saved provider with demo",
      exact: true,
    })
    .click();
  await expect(page.locator(".comparison-grid article")).toHaveCount(2, {
    timeout: 30000,
  });
  await page
    .getByRole("button", { name: "Load feedback reviews", exact: true })
    .click();
  await expect(page.locator(".diagnostics-content")).toContainText(
    "wrong citation · message",
  );
  await page.getByLabel("Search help", { exact: true }).fill("backup");
  await expect(
    page.getByText("Backup and recovery", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../../artifacts/phase3-diagnostics-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "../../artifacts/phase3-diagnostics-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    ),
  ).toBeFalsy();
  expect(errors).toEqual([]);
});
