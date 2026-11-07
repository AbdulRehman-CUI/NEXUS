import { expect, test } from "@playwright/test";

test("server login, private workspace, member permissions and logout", async ({
  page,
}) => {
  test.skip(
    process.env.NEXUS_SERVER_TEST !== "1",
    "Requires the explicitly isolated server-profile fixture; local mode uses no accounts.",
  );
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("release-owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill("Synthetic owner password 123");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page
    .getByRole("button", { name: "Account and appearance", exact: true })
    .click();
  await expect(
    page.getByText("Signed in as release-owner", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close panel", exact: true }).click();
  page.once("dialog", (dialog) => dialog.accept("Private server workspace"));
  if (
    await page
      .getByRole("heading", { name: "Create your first workspace." })
      .isVisible()
  ) {
    await page
      .locator("#main")
      .getByRole("button", { name: "Create workspace", exact: true })
      .click();
  } else {
    await page
      .getByRole("button", { name: "Switch workspace", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Create workspace", exact: true })
      .click();
  }
  await expect(
    page.getByRole("heading", { name: /Your knowledge/ }),
  ).toBeVisible();
  await page.goto("/library");
  await page.getByLabel("Upload documents", { exact: true }).setInputFiles({
    name: "server-proof.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(
      "# Server proof\nAuthenticated cookie and CSRF upload preserve source evidence.",
    ),
  });
  await expect(page.locator(".document-status.ready")).toHaveCount(1, {
    timeout: 30000,
  });
  await page.goto("/settings");
  await page.locator(".workspace-administration > summary").click();
  await page.getByRole("button", { name: "Load members", exact: true }).click();
  await expect(
    page.getByText("release-owner · owner", { exact: false }),
  ).toBeVisible();
  await page
    .getByLabel("Member username", { exact: true })
    .fill("release-viewer");
  await page
    .getByRole("combobox", { name: "Member role", exact: true })
    .selectOption("viewer");
  await page
    .getByRole("button", { name: "Save membership", exact: true })
    .click();
  await expect(
    page.getByText("release-viewer · viewer", { exact: false }),
  ).toBeVisible();
  await page.screenshot({
    path: "../../artifacts/phase3-server-members.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Account and appearance", exact: true })
    .click();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
