import { describe, expect, it } from "vitest";
import { initialSnapshot } from "@/data/fixtures";
import { MockCanopusService } from "@/services/mock-canopus";
import type {
  CanopusReply,
  CanopusRequest,
  CanopusStreamEvent,
} from "@/domain/canopus";
const snapshot = initialSnapshot();
const request: CanopusRequest = {
  id: "conversation-1",
  message: "Explain the highlighted node and approval",
  participant: "investigator",
  language: "en",
  context: {
    screen: "investigation",
    caseId: "SHP-10482",
    selectedEvidenceId: "gps",
    stage: 5,
  },
};
async function collect(adapter: MockCanopusService, input: CanopusRequest) {
  const events: CanopusStreamEvent[] = [];
  for await (const event of adapter.stream(input, {
    signal: new AbortController().signal,
  }))
    events.push(event);
  return {
    events,
    reply: (
      events.find((event) => event.type === "complete") as {
        type: "complete";
        reply: CanopusReply;
      }
    ).reply,
  };
}
describe("typed local Canopus adapter", () => {
  it("streams fixture facts with evidence links and separates proposed actions from verified outcomes", async () => {
    const before = JSON.stringify(snapshot);
    const { events, reply } = await collect(
      new MockCanopusService(() => snapshot),
      request,
    );
    expect(events.some((event) => event.type === "delta")).toBe(true);
    expect(reply.blocks[0].text).toContain("vehicle position only");
    expect(
      reply.blocks[0].references.some((reference) =>
        reference.href.endsWith("?evidence=gps"),
      ),
    ).toBe(true);
    expect(
      reply.blocks.find((block) => block.kind === "recommendation")?.text,
    ).toContain("C-04");
    expect(
      reply.blocks.find((block) => block.kind === "outcome")?.verified,
    ).toBe(false);
    expect(JSON.stringify(snapshot)).toBe(before);
  });
  it("provides Arabic replies and refuses to invent unknown shipments", async () => {
    const { reply } = await collect(new MockCanopusService(() => snapshot), {
      ...request,
      language: "ar",
    });
    expect(reply.blocks[0].text).toContain("لا يثبت حيازة الطرد");
    expect(
      reply.blocks.find((block) => block.kind === "recommendation")?.text,
    ).toContain("تفويضاً صريحاً");
    const unknown = await collect(new MockCanopusService(() => snapshot), {
      ...request,
      message: "Explain SHP-99999",
    });
    expect(unknown.reply.blocks).toHaveLength(0);
    expect(unknown.reply.summary).toContain("not in this synthetic workspace");
  });
  it("exercises a simulated failure, succeeds on retry, and honors cancellation", async () => {
    const adapter = new MockCanopusService(() => snapshot),
      input = { ...request, simulateFailure: true };
    await expect(collect(adapter, input)).rejects.toThrow("simulated response");
    expect((await collect(adapter, input)).reply.source).toBe("synthetic");
    const controller = new AbortController();
    controller.abort();
    const stream = adapter.stream(request, { signal: controller.signal });
    await stream.next();
    await expect(stream.next()).rejects.toHaveProperty("name", "AbortError");
  });
});
