import type { Page, Route } from "@playwright/test";
import {
  CASE_A,
  CASE_B,
  auditRows,
  detailA,
  detailB,
  exploreItems,
  page as pageOf,
  pipelineEvents,
  queueRows,
  schema,
  session,
  workerStatus,
} from "../fixtures/backend";
import type { ApiCaseDetail, ApiQueueCase } from "../../src/api/contracts";

export interface Stub {
  posts: { path: string; body: Record<string, unknown>; token: string | null }[];
  /** Mutable backend state the handlers serve. */
  state: {
    online: boolean;
    queue: ApiQueueCase[];
    detailA: ApiCaseDetail;
    worker: string;
  };
}

/**
 * Serves the backend's routes to the page in the backend's wire format. It only answers
 * requests; whatever the screens show still has to come through the real adapters.
 */
export async function stubBackend(page: Page): Promise<Stub> {
  const stub: Stub = {
    posts: [],
    state: {
      online: true,
      queue: structuredClone(queueRows),
      detailA: detailA(),
      worker: "paused",
    },
  };
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  await page.route(
    (url) =>
      url.port === "5191" &&
      /^\/(operations|cases|audit|explore|decisions|schema|graph|worker|shipments|simulation)(\/|$)/.test(
        url.pathname,
      ),
    async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      if (!stub.state.online)
        return json(
          route,
          { detail: "The validated V2 operations database is unavailable" },
          503,
        );
      if (request.method() === "POST") {
        const body = request.postData() ? JSON.parse(request.postData()!) : {};
        stub.posts.push({
          path,
          body,
          token: request.headers()["x-operations-token"] ?? null,
        });
        if (path === `/cases/${CASE_A}/decision`) {
          // The backend accepted the approval: an execution was authorized, nothing is verified.
          const approved = body.decision === "approve";
          const next = approved
            ? "AWAITING_OUTCOME"
            : body.decision === "reject"
              ? "REJECTED"
              : "ESCALATED";
          stub.state.detailA = detailA({
            workflow_state: next,
            state_version: 9,
            recommendation: {
              ...detailA().recommendation!,
              approvable: false,
              approval_rule: "LIFECYCLE-not-awaiting-decision",
              approval_reason: `The case is ${next}, not awaiting a decision.`,
            },
            executions: approved
              ? [
                  {
                    receipt_ref: "SYN-RCPT-A1",
                    action_type: "REQUEST_DEPOT_RECONCILIATION",
                    occurred_at: "2026-09-03T14:00:00+00:00",
                    status: "ACKNOWLEDGED",
                    authority: "OPERATOR_APPROVAL",
                    current_cycle: true,
                  },
                ]
              : [],
            decisions: [
              {
                decision: body.decision,
                occurred_at: "2026-09-03T14:00:00+00:00",
                actor_id: "SYN-OPERATOR-LOCAL",
              },
            ],
          });
          stub.state.queue = stub.state.queue.map((row) =>
            row.case_id === CASE_A
              ? { ...row, workflow_state: next, state_version: 9 }
              : row,
          );
          return json(route, {
            case_id: CASE_A,
            workflow_state: next,
            state_version: 9,
          });
        }
        if (path === "/worker/start" || path === "/worker/pause") {
          stub.state.worker = path.endsWith("start") ? "running" : "paused";
          return json(route, {});
        }
        return json(route, { detail: "Not found" }, 404);
      }
      if (path === "/operations/session") return json(route, session);
      if (path === "/worker/status")
        return json(route, {
          ...workerStatus,
          worker: { ...workerStatus.worker, state: stub.state.worker },
        });
      if (path === "/cases/queue") return json(route, pageOf(stub.state.queue));
      if (path === "/explore") return json(route, pageOf(exploreItems));
      if (path === "/audit") return json(route, pageOf(auditRows));
      if (path === "/schema") return json(route, schema);
      if (path === `/cases/${CASE_A}`) return json(route, stub.state.detailA);
      if (path === `/cases/${CASE_B}`) return json(route, detailB());
      if (path === `/cases/${CASE_A}/events`)
        return route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          body: `event: pipeline\ndata: ${JSON.stringify({
            workflow_state: stub.state.detailA.workflow_state,
            state_version: stub.state.detailA.state_version,
            run_id: "SYN-RUN-1",
            status: "REVIEWED",
            events: pipelineEvents,
          })}\n\n`,
        });
      return json(
        route,
        { detail: "Operational case or shipment not found" },
        404,
      );
    },
  );
  return stub;
}
