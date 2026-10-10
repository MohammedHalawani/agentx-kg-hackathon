# Frontend integration seams

The UI is isolated in `C:\Projects\suhail_ui`. Work in this lab does not require access to `C:\Projects\demo`.

| Area                   | Contract and implementation                                                                                                                                                                   |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| UI data                | `src/domain/types.ts`: typed shipments, parcel observations, graph relationships, proposed actions, operator decisions, execution receipts, independently verified outcomes, and audit events |
| Operations adapter     | `OperationsService` in `src/domain/types.ts`; current implementation `src/services/mock-operations.ts` is a browser-only fixture store                                                        |
| Canopus adapter        | `CanopusService` in `src/domain/canopus.ts`; current implementation `src/services/mock-canopus.ts` uses fixture selection and timed text fragments                                            |
| Read-only page actions | `src/domain/page-actions.ts`; `src/services/mock-intents.ts` validates a supported set of requests; page handlers apply the resulting filters, selections, and views                          |
| Queries                | `src/services/page-queries.ts`: shipment filtering and audit filtering, chronological sorting, unique counts, and pagination                                                                  |
| Display state          | `src/state/operations.tsx`, `src/state/preferences.tsx`, and `src/state/canopus.tsx`                                                                                                          |
| Design system          | `components.json` records the Nova / Radix preset; official components are in `src/components/ui`; brand tokens are in `src/styles/brand.css`                                                 |

## Canopus and a future V2 integration

`CanopusProvider` accepts an optional `CanopusService` adapter. A later Claude V2 integration can supply that implementation without changing the conversation, citation, loading, retry, or scrolling components. The lab supplies no credentials or remote implementation.

```ts
interface CanopusService {
  stream(
    request: CanopusRequest,
    options: { signal: AbortSignal },
  ): AsyncIterable<CanopusStreamEvent>;
}
```

A request includes its ID, message, participant, language, and screen context: selected case, selected evidence, stage, and current filters. The adapter emits `activity`, text `delta`, and a final typed `complete` reply. Cancellation uses AbortSignal. Adapter errors are displayed with a retry control that retains the original request and avoids duplicating the question.

Each assistant message retains its own request context. Retry continues to target that message after a later question or a reload; an interrupted stream is shown with explicit retry feedback. Conversation history is stored in sessionStorage. Presentation has three states: collapsed, floating, and expanded. The non-modal floating window remains mounted and inert while minimized, preserving its transcript position and per-thread draft without exposing hidden controls to the keyboard.

The final reply contains a summary and labeled blocks for `observation`, `hypothesis`, `recommendation`, `decision`, and `outcome`. The outcome’s `verified` flag must describe independently supported results, never a recommendation or approval. Each reference includes its kind, label, and navigation target.

Currently supported citation targets:

- `/cases/:id?evidence=:evidenceId` focuses the parcel observation in the map, graph, and inspector.
- `/cases/:id?stage=:stageIndex` selects the corresponding investigation stage.
- `/cases/:id?section=assessment` opens the case assessment.
- `/decisions?case=:id` opens the matching decision review.
- `/audit?case=:id&mode=by_shipment&timeRange=all` opens its chronological history.

One global `CanopusPanel` renders through a portal above normal page, map, and graph controls. The case's inline Ask Suhail action opens this same window. Expanding changes only the conversation geometry; it does not change the application layout. Case history follows navigation, while opening a new screen adopts that screen's current context.

`PageAssistant` is a headless bridge to the existing Explore and Audit callbacks. `CanopusPageTools` supplies the pathname, current page context, apply handler, and Undo handler. Supported frontend rules update the actual filters, selection, and view through those callbacks. Unsupported requests leave the page unchanged. These tools never authorize or execute operational actions.

## Verification and notifications

Automatic investigation is a local 2.4-second demonstration timer. Pausing it stops new starts and lets the active case finish its mandatory review, execution, and verification path. A proposed action and an operator decision remain distinct from an execution receipt and a verified outcome.

Operational notifications observe actual mock-state transitions. One official shadcn Sonner Toaster lives at the application root, on the opposite side from Canopus on desktop and at the top on mobile. The existing Nova / Radix foundation is preserved. Message, MessageGroup, Bubble, Message Scroller, Marker, Spinner, Command, and Popover use compatible official implementations. The composer remains fixed while the transcript scrolls independently, with user-turn anchoring and a jump-to-latest control.

English and Arabic direction are supplied by the shared preferences and DirectionProvider. Map and graph coordinates remain left-to-right spatial canvases inside the localized shell. Reduced-motion preferences apply to transitions, transcript navigation, and message presentation.
