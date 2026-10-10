# Suhail UI Lab — verification

Verified on **10 October 2026** in the isolated frontend project at `C:\Projects\suhail_ui`. The development app runs at **http://127.0.0.1:5180/**.

| Check                                                  | Result                                                                                                                              |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| TypeScript and production build                        | Passed (`npm run build`)                                                                                                            |
| ESLint                                                 | Passed (`npm run lint`)                                                                                                             |
| Unit tests                                             | 16 passed across 3 files (`npm test`)                                                                                               |
| Browser tests                                          | 20 passed in installed Google Chrome (`npm run test:e2e`)                                                                           |
| Approval, automatic investigation, and failed recovery | Controlled browser clocks check each execution and verification transition, including continuing the active case after pausing Auto |

## Browser coverage

- **Canopus:** one 56px global launcher; hover and keyboard-focus tooltip; 420×590 floating window; optional centered expanded workspace; no map/graph resizing. Opening a case inherits its evidence context. Case history persists across navigation; minimizing preserves the selected case, multiline draft, message count, and exact scroll position. Compact expandable notes distinguish observations, hypotheses, recommendations, decisions, and verified outcomes. Citations focus evidence and open assessments or the matching decision review, including repeated references. Simulated streaming, errors, and retry after reload or a later question work without duplicating questions or changing operational state.
- **Conversation accessibility:** keyboard mentions, Enter/Shift+Enter, nested Escape handling, launcher focus restoration, inert minimized controls, transcript keyboard reading, jump to latest, and both application and system reduced-motion preferences. Reading earlier messages does not force the transcript to the latest response. Expandable notes support native keyboard interaction. Arabic chat controls have localized accessible names.
- **Operations:** real search, filters, sorting, page size, pagination, navigation, and the collapsible verified Resolved panel. Automatic investigation handles one eligible case at a time. Pausing stops new starts while the current case continues through required checks.
- **Investigation and Decisions:** linked map markers and graph nodes, pipeline inspection, graph layouts and filters, panel resizing, approval/rejection/escalation dialogs, required reasons, authority history, execution, verification, failed outcomes, and verified resolution notifications with Open Case. Approval alone does not produce a resolution-success notification.
- **Explore:** exact route filtering, shipment selection, linked map and graph views, schema inspection, and contextual Canopus filter requests with Undo in English and Arabic. Unsupported filter requests explain the supported examples and preserve the displayed results.
- **Audit:** date shortcuts, custom calendar dates, sorting, pagination, metadata, shipment timelines, and destination/failed-outcome assistant requests with Undo. The initial Today view has 72 events across 14 unique shipments; the 2 October range contains the 10 events for SHP-10442.
- **Shell:** global keyboard search, notifications, theme persistence, Arabic direction, mobile sidebar navigation, direct-link reloads, and unknown-shipment feedback. Browser checks detected no uncaught application errors.

## Visual review

Reviewed the refreshed light and dark screenshots at **1440×900** and **1280×800**, with mobile checks at **390×844**, **320×568**, and **844×390** landscape. Map and graph remain side by side at desktop and laptop sizes. Mobile provides stacked, resizable evidence canvases; Canopus becomes a viewport-fitting bottom sheet with a fixed composer. Arabic mirrors the launcher and conversation anchor. The default graph is checked after responsive fitting before screenshots are captured.

The final screenshots in `screenshots/` include all six pages on desktop and mobile, the four principal pages in dark mode, a laptop Investigation view, and Canopus in English and Arabic. The requested comparison is `final-canopus-collapsed.png` and `final-canopus-floating.png`; additional previews include `final-canopus-floating-reply.png`, `final-canopus-expanded.png`, `final-canopus-floating-dark.png`, and `final-canopus-arabic-mobile.png`.

## Lab boundaries

All operational data, assistant replies, authority decisions, and recovery outcomes are simulated locally. No real AI or backend adapter is configured. The replaceable Canopus service contract and integration notes are in [INTEGRATION.md](INTEGRATION.md).

The Audit fixtures are anchored to 9 October 2026 in Saudi time. OpenStreetMap supplies the optional street basemap; the working offline schematic is available when tiles cannot load. Original fixture names and identifiers may remain in English within the Arabic interface.

Vite reports a non-blocking bundle-size advisory for the shared entry chunk (approximately 839 kB minified, 267 kB compressed). Feature pages and the map/graph libraries are split into separate chunks.
