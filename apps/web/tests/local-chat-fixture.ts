import { expect, type APIRequestContext, type Page } from "@playwright/test";

const api = "http://127.0.0.1:8000";

export async function openLocalEvidenceChat(
  page: Page,
  request: APIRequestContext,
  workspaceId: string,
  data: { content: string; [key: string]: unknown },
) {
  const created = await request.post(`${api}/api/workspaces/${workspaceId}/chats`);
  expect(created.ok()).toBe(true);
  const { id } = await created.json();
  const answer = await request.post(`${api}/api/chats/${id}/messages?workspace_id=${workspaceId}`, { data });
  expect(answer.ok()).toBe(true);
  await page.goto(`/?chat=${id}`);
}

// UI-only tests inject a model and control the response to exercise the composer.
export function showTestModel(page: Page) {
  return page.route("**/api/workspaces/*/ai-selection", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: {
        ...await response.json(),
        active: { provider: "ollama", model: "test-model", streaming: false },
      },
    });
  });
}
