import { expect, test, type Page } from "@playwright/test";

/**
 * Nothing of one shipment's investigation shows on another's page: narration, the Canopus
 * conversation, quotes and graph highlights each belong to the case on screen. Read-only apart
 * from two questions (which store nothing).
 *
 *   SUHAIL_LIVE_URL=http://127.0.0.1:8021 SUHAIL_ISOLATION_CASES=<id>,<id> npx playwright test \
 *     --config playwright.live.config.ts case-isolation
 */
const CASES = (process.env.SUHAIL_ISOLATION_CASES ?? "").split(",").filter(Boolean);
test.skip(CASES.length < 2, "set SUHAIL_ISOLATION_CASES to two investigated case ids");
test.setTimeout(8 * 60 * 1000);

interface Detail {
  case_id: string;
  shipment_id: string;
  evidence: { nodes: { id: string }[] };
  narration: { run_id: string; events: { id: string; case_id: string; shipment_id: string; run_id: string; title_en: string; text_en: string; graph_node_ids: string[] }[] };
}

async function openFromQueue(page: Page, detail: Detail) {
  // In-app navigation, as an operator switches: no page reload between the two cases (a
  // resolved case is not in the queue table, so the router is driven directly).
  await page.evaluate((path) => {
    window.history.pushState({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, `/app/cases/${detail.case_id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(detail.shipment_id, {
    timeout: 60000,
  });
  await expect(page.getByTestId("narration-strip")).toContainText(
    `of ${detail.narration.events.length} recorded messages`,
    { timeout: 60000 },
  );
}

test("Each case shows only its own narration, conversation and highlights", async ({
  page,
  request,
}) => {
  const [a, b] = (await Promise.all(
    CASES.slice(0, 2).map(async (id) => (await request.get(`/cases/${id}`)).json()),
  )) as Detail[];
  // The records themselves: every stored message carries its own case, shipment and run.
  for (const detail of [a, b])
    for (const event of detail.narration.events) {
      expect(event.case_id).toBe(detail.case_id);
      expect(event.shipment_id).toBe(detail.shipment_id);
      expect(event.run_id).toBe(detail.narration.run_id);
    }
  await page.goto("/app/operations");
  await expect(page.locator(".environment-badge")).toHaveText("Connected", { timeout: 90000 });
  const check = async (detail: Detail, other: Detail) => {
    await openFromQueue(page, detail);
    // Every bubble on every step is one of this case's stored messages, none of the other's.
    const own = new Set(detail.narration.events.map((event) => event.text_en.trim()));
    const foreign = new Set(
      other.narration.events
        .map((event) => event.text_en.trim())
        .filter((text) => !own.has(text)),
    );
    for (const step of ["Collect", "Diagnose", "Review", "Disposition"]) {
      await page.getByRole("button", { name: new RegExp(`^${step} ·`) }).click();
      // The strip on the page (the folded copy in the Canopus panel is checked by its count).
      const texts = await page
        .getByTestId("narration-strip")
        .getByTestId("narration-bubble")
        .locator("p")
        .allInnerTexts();
      for (const text of texts) {
        expect(own.has(text.trim()), `${detail.shipment_id} ${step}: ${text.slice(0, 80)}`).toBe(true);
        expect(foreign.has(text.trim())).toBe(false);
      }
    }
    // A highlight lights only nodes of this case's graph.
    const nodes = new Set(detail.evidence.nodes.map((node) => node.id));
    const lit = page.locator(".narration-strip .narration-bubble footer button:not([disabled])").first();
    if (await lit.count()) {
      await lit.click({ timeout: 15000 });
      const ids = await page
        .getByTestId("knowledge-graph")
        .locator(".react-flow__node:has(.evidence-path)")
        .evaluateAll((items) => items.map((item) => item.getAttribute("data-id")));
      expect(ids.length).toBeGreaterThan(0);
      for (const id of ids) expect(nodes.has(id!), `${detail.shipment_id}: ${id}`).toBe(true);
    }
  };
  await check(a, b);
  // A question about the first case stays with the first case.
  await page.getByRole("button", { name: "Open Canopus assistant" }).click();
  const panel = page.locator(".canopus-window");
  const ask = async (question: string) => {
    await panel.getByRole("textbox", { name: "Ask Canopus about this case" }).fill(question);
    const [response] = await Promise.all([
      page.waitForResponse((item) => item.url().endsWith("/canopus/ask"), { timeout: 120000 }),
      panel.getByRole("button", { name: "Send question" }).click(),
    ]);
    return (await response.json()) as { case_id: string; shipment_id: string; answer_en: string };
  };
  const first = await ask("What did the reviewer say?");
  expect(first.case_id).toBe(a.case_id);
  await expect(panel.getByTestId("canopus-answer")).toHaveCount(1, { timeout: 120000 });
  await panel.getByRole("button", { name: "Minimize Canopus conversation" }).click();
  await check(b, a);
  await page.getByRole("button", { name: "Open Canopus assistant" }).click();
  // The second case starts with an empty conversation; the first case's answer is not here.
  await expect(panel.getByTestId("canopus-answer")).toHaveCount(0);
  const second = await ask("What did the reviewer say?");
  expect(second.case_id).toBe(b.case_id);
  expect(second.shipment_id).toBe(b.shipment_id);
  await expect(panel.getByTestId("canopus-answer")).toHaveCount(1, { timeout: 120000 });
  await expect(panel.getByTestId("canopus-answer")).toContainText(second.answer_en.slice(0, 50));
  await panel.getByRole("button", { name: "Minimize Canopus conversation" }).click();
  // Back on the first case, its own answer is still there, unchanged.
  await openFromQueue(page, a);
  await page.getByRole("button", { name: "Open Canopus assistant" }).click();
  await expect(panel.getByTestId("canopus-answer")).toHaveCount(1);
  await expect(panel.getByTestId("canopus-answer")).toContainText(first.answer_en.slice(0, 50));
  console.log(
    `isolation held: ${a.shipment_id} (${a.narration.events.length} messages) and ${b.shipment_id} (${b.narration.events.length} messages)`,
  );
});
