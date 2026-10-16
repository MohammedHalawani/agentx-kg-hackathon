Selected SVG icons adapted from Animate UI on 2026-10-16:

- https://animate-ui.com/r/icons-users.json
- https://animate-ui.com/r/icons-clock.json
- https://animate-ui.com/r/icons-message-square-text.json

Upstream: https://github.com/imskyleen/animate-ui
License: MIT + Commons Clause, complete upstream text in LICENSE.txt.

Only these three icons are included. The local icon.tsx adapter uses the existing
Motion dependency and implements the small subset used here: animate, animation,
size, SVG props and shared controls. It is not the complete Animate UI wrapper.
The parent controls hover/focus; transitions are 180 ms, with no looping icon
animation. User and OS reduced-motion settings suppress animation. SVG paths and
variant definitions originate upstream; durations/delays and context lookup are
adapted for this console. No new runtime dependency was added.
