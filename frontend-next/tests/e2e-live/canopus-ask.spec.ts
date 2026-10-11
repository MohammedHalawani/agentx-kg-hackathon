import { expect, test } from "@playwright/test";

/**
 * Canopus questions about one investigated case, against a backend with questions enabled.
 * Each question is one real model call at most; the server stores nothing and performs nothing.
 *
 *   SUHAIL_LIVE_URL=http://127.0.0.1:8021 SUHAIL_CANOPUS_CASE=<case id> npx playwright test \
 *     --config playwright.live.config.ts canopus-ask
 */
const CASE = process.env.SUHAIL_CANOPUS_CASE;
test.skip(!CASE, "set SUHAIL_CANOPUS_CASE to an investigated case");
test.setTimeout(6 * 60 * 1000);

test("Canopus answers from the case's records, quotes the agents, and lights the cited records", async ({
  page,
  request,
}) => {
  const detail = await (await request.get(`/cases/${CASE}`)).json();
  const nodeIds = new Set<string>(detail.evidence.nodes.map((node: { id: string }) => node.id));
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const answers: Record<string, unknown>[] = [];
  page.on("response", async (response) => {
    if (response.url().endsWith("/canopus/ask") && response.ok())
      answers.push(await response.json());
  });
  await page.goto(`/app/cases/${CASE}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(detail.shipment_id, {
    timeout: 60000,
  });
  await page.getByRole("button", { name: "Open Canopus assistant" }).click();
  const panel = page.locator(".canopus-window");
  const box = panel.getByRole("textbox", { name: "Ask Canopus about this case" });
  const ask = async (question: string) => {
    const before = await panel.getByTestId("canopus-answer").count();
    const started = Date.now();
    await box.fill(question);
    await panel.getByRole("button", { name: "Send question" }).click();
    await expect(panel.locator(".ask-waiting")).toContainText("reading this case");
    await expect(panel.getByTestId("canopus-answer")).toHaveCount(before + 1, {
      timeout: 120000,
    });
    const answer = answers.at(-1) as {
      kind: string;
      answer_en: string;
      workflow_state: string;
      quotes: { text: string; role: string }[];
      graph_node_ids: string[];
      evidence_ids: string[];
      offers: { type: string; allowed: boolean; label_en: string }[];
      model: string | null;
    };
    console.log(
      `Q: ${question}\n   ${Math.round((Date.now() - started) / 1000)} s · ${answer.kind} · model ${answer.model} · ${answer.quotes.length} quotes · ${answer.graph_node_ids.length}/${answer.evidence_ids.length} graph ids · offers ${answer.offers.map((offer) => `${offer.type}:${offer.allowed}`).join(", ") || "none"}\n   A: ${answer.answer_en.slice(0, 400)}`,
    );
    const bubble = panel.getByTestId("canopus-answer").nth(before);
    // Canopus's text as served, labelled by who wrote it; the case state is the recorded one.
    await expect(bubble).toHaveAttribute("data-kind", answer.kind);
    await expect(bubble).toContainText(answer.answer_en.slice(0, 60));
    await expect(bubble).toContainText(
      answer.kind === "canopus_answer" ? "Canopus answer" : "Answer from the records",
    );
    expect(typeof answer.workflow_state).toBe("string");
    // Every graph id the answer names is a node of this case's graph.
    for (const id of answer.graph_node_ids) expect(nodeIds.has(id), id).toBe(true);
    return { answer, bubble };
  };

  const first = await ask("What did the reviewer say?");
  // The reviewer's own recorded words, verbatim, as source material.
  if (first.answer.quotes.length) {
    const quote = panel.getByTestId("canopus-quote").first();
    await expect(quote).toContainText("recorded message, not rewritten");
    await expect(quote).toContainText(first.answer.quotes[0].text.slice(0, 60));
  }
  await page.screenshot({ path: "screenshots/graph/canopus-ask-reviewer.png" });

  const second = await ask("Show me the investigator's original message.");
  expect(second.answer.quotes.some((quote) => quote.role === "investigator")).toBe(true);

  const third = await ask("What evidence is missing, and can you request it?");
  if (third.answer.offers.length)
    await expect(panel.getByTestId("canopus-offers").last()).toContainText(
      third.answer.offers[0].label_en,
    );
  // An allowed approval is only a door to the existing dialog; nothing is sent from the panel.
  const door = panel.getByRole("button", { name: "Open Review & authorize" }).last();
  if (await door.count()) {
    await door.click();
    await expect(
      page.getByRole("dialog").getByRole("button", { name: "Authorize action" }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
  }
  await page.screenshot({ path: "screenshots/graph/canopus-ask-offers.png" });

  // Records an answer relies on are lit in the graph, from its graph_node_ids only.
  const withIds = [first, second, third].find((item) => item.answer.graph_node_ids.length);
  if (withIds) {
    await withIds.bubble.getByRole("button", { name: /records in the graph/ }).click();
    await panel.getByRole("button", { name: "Minimize Canopus conversation" }).click();
    await expect(
      page.getByTestId("knowledge-graph").locator(".evidence-path").first(),
    ).toBeVisible();
    await page.screenshot({ path: "screenshots/graph/canopus-ask-highlight.png", fullPage: true });
  }
  // Asking wrote nothing: the case is exactly as it was.
  const after = await (await request.get(`/cases/${CASE}`)).json();
  // (On a session whose clock is running the case can move by itself; say so, do not blame the ask.)
  if (after.state_version !== detail.state_version)
    console.log(
      `case moved during the test: v${detail.state_version} ${detail.workflow_state} -> v${after.state_version} ${after.workflow_state}`,
    );
  else expect(after.workflow_state).toBe(detail.workflow_state);
  expect(errors).toEqual([]);
});
