Independent review of the original Snake game:

The movement, seeded RNG, growth and snapshot logic are correct in the tested cases.
In particular, moving into a tail cell that vacates on that tick is allowed correctly.
Keyboard controls, touch direction buttons and restart work. Preserve those behaviors,
the visual theme and the window.bench reset/step/state API.

Fix these findings:
1. The fixed-height, vertically centered body clips tall content: at a 640x640 viewport
   the header's top is -321.7 pixels at scrollY=0. Make content reachable on small screens
   and in landscape, with normal scrolling rather than hiding overflow.
2. Allow browser zoom. Give direction buttons descriptive accessible names. Give the
   canvas an accessible description and expose meaningful score/status changes to
   assistive technology. Avoid announcing every movement or elapsed-time update.
   Respect reduced-motion preferences for decorative animations.
3. Game movement directly invokes rendering and DOM updates. Separate a DOM-free
   simulation from the UI adapter so its behavior can be unit tested independently.
   Expose window.createSnakeGame(seed) as a small engine factory with reset(seed),
   step(direction), and state() methods, preserving the existing window.bench API.
   The factory itself and its methods must not require DOM, canvas, browser timing
   or shared singleton state. Return copied state, not internal mutable arrays.
4. requestAnimationFrame keeps scheduling itself while paused or dead. Stop scheduling
   the gameplay loop then and resume cleanly on Start. Avoid multiple simultaneous
   loops after repeated pauses/restarts. Re-render only when needed.
5. Food placement checks every grid cell against every snake segment. Use a simple
   occupancy set so the scan grows with board size plus snake length, while preserving
   the exact xorshift and row-major placement rules.
6. Ignore keyboard autorepeat for the pause shortcut so holding Space does not toggle
   pause repeatedly. Remove unused drawing calculations and variables.
7. Handle the full-board completion case explicitly with a win state/message instead
   of remaining alive with no food. Keep existing state fields; extra fields such as
   won are acceptable.

Use concise, readable code rather than adding unnecessary styling or features. Keep
the original one-file/no-dependencies constraint. Return the complete revised HTML.
