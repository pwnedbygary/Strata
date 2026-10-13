Independent review of your first Snake revision:

The DOM-free engine is a useful improvement: separate instances are isolated, snapshots
are copied, and an independent Hamiltonian-cycle test grew the snake to 400 cells and
won after 39,671 moves. Preserve this correct engine, seeded placement, layout/accessibility
improvements, labels, zoom settings and win behavior. Do not start another visual redesign.

Fix these integration regressions with minimal uniquely anchored edits:

1. CRITICAL: The page crashes on boot. updateUI calls fmtTime(s.elapsed), but state()
   deliberately returns a copied snapshot without elapsed. undefined.toFixed throws.
   The loop also mutates st.elapsed on a snapshot. Keep stopwatch time in the UI adapter
   instead of introducing timing into the pure engine, and reset it on every UI reset.
2. CRITICAL: Start/Pause mutates st.paused on a copied snapshot. The engine remains
   paused forever, so the next loop exits and the game cannot start. Add an explicit
   engine method to update the internal paused flag, call it from the UI, and keep
   snapshots immutable copies. A UI-only flag that disagrees with window.bench.state()
   is not an acceptable fix. Preserve the bench reset/step/state API.
3. liveEl is declared and an aria-live region exists, but nothing writes to it. Announce
   meaningful mode/score changes there, caching the last announcement so unchanged ticks
   do not cause repeated announcements. Do not announce elapsed time.
4. loop redraws the entire board on every animation frame even when no game tick happened.
   Render when movement/end state changes, and update stopwatch text only when its
   displayed value changes. Stop/cancel scheduling immediately on pause, death or win.
5. Ensure window.bench.reset cancels the UI loop, clears pending input and resets timer
   state as well as the engine. Repeated start/pause/restart must never leave two loops.
6. Ignore e.repeat for Space explicitly, as well as resetting the held-key latch on blur
   to avoid sticking after focus changes.

Verify all callers of the changed state/control interface. Keep the first review's
factory and basic gameplay contract intact. Return only the requested JSON edits.
