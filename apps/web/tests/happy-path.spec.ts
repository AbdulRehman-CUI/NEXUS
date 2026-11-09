import { expect, test } from "@playwright/test";
import { openLocalEvidenceChat } from "./local-chat-fixture";

const api = "http://localhost:8000";

test("upload PDF and Markdown, ask, open evidence, inspect history and mobile UI", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const workspaceResponse = await request.post(`${api}/api/workspaces`, {
    data: { name: `Browser test ${Date.now()}` },
  });
  expect(workspaceResponse.ok()).toBeTruthy();
  const workspace = await workspaceResponse.json();
  await page.addInitScript(
    (id) => localStorage.setItem("nexus-workspace", id),
    workspace.id,
  );
  await page.goto("/library");
  await expect(
    page.getByRole("heading", { name: "A home for your sources." }),
  ).toBeVisible();
  await page
    .getByLabel("Upload documents", { exact: true })
    .setInputFiles([
      "../../examples/aurora-notes.md",
      "../../examples/aurora-brief.pdf",
    ]);
  await expect(page.locator(".document-status.ready")).toHaveCount(2, {
    timeout: 45000,
  });
  await openLocalEvidenceChat(page, request, workspace.id, {
    content: "When is the Aurora launch and readiness review?",
  });
  await expect(page.locator(".message.assistant")).toContainText("November");
  await expect(page.locator(".inline-citation").first()).toBeVisible();
  await page.locator(".inline-citation").first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.locator("mark")).toContainText(/aurora/i);
  await page.screenshot({
    path: "../../artifacts/source-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Close source" }).click();
  await page.screenshot({
    path: "../../artifacts/chat-desktop.png",
    fullPage: true,
  });
  await page.reload();
  await page.locator(".chat-title").first().click();
  await expect(page.locator(".message.assistant")).toContainText("November");
  await page.getByRole("link", { name: "Settings & providers" }).click();
  await page.getByRole("tab", { name: "Server defaults", exact: true }).click();
  await expect(
    page.getByRole("checkbox", { name: /I explicitly allow/ }),
  ).not.toBeChecked();
  await page.screenshot({
    path: "../../artifacts/settings-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /Your knowledge/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(
    page.getByRole("link", { name: "Document library" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Document library" }).click();
  await expect(
    page.getByRole("heading", { name: "A home for your sources." }),
  ).toBeVisible();
  await page.screenshot({
    path: "../../artifacts/library-mobile.png",
    fullPage: true,
  });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBeFalsy();
  expect(errors).toEqual([]);
});
