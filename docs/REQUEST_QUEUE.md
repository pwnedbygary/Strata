# Waiting requests from coding agents

OpenChamber/OpenCode can send several requests at once: subagents, the parent
agent, and auxiliary tasks. A single-slot Strata worker used to reject every
concurrent request immediately with HTTP 429 and `Model is busy; retry after the
current request`. Those retries did not mean the model had failed to generate.

The native router now has an opt-in FIFO request queue. Enable it in the registry:

```json
{
  "queue_requests": true,
  "default": "your-model",
  "profiles": {"your-model": "/path/to/profile.json"}
}
```

It is enabled in this installation's `~/.config/strata/router.json`. Registries
without the option retain the previous immediate-busy behavior. A restart applies
the registry setting; it does not require changing any model weights or profile
sampling settings.

- Five requests can be admitted: normally one generating and four waiting.
- Generation remains serial, with one model worker and one KV context. The queue
  does not allocate a cache per agent or increase GPU concurrency.
- Estimated retained request payloads are bounded to 256 MiB in total. This uses
  an eight-times-body-size estimate for parsing/copy overhead. Admission and
  physical RAM/VRAM/GTT safeguards remain active; memory is rechecked at dispatch.
- Waiting streams receive SSE comments every two seconds. They are transport
  keep-alives, not model output. Disconnected waiting clients release their slot.
- A request can wait up to ten minutes. A full queue still returns HTTP 429 with
  Retry-After. A waiting stream that expires receives an SSE error; non-streaming
  requests receive HTTP 429. A client's own overall deadline may expire sooner.
- The queued mode reserves HTTP worker capacity for status/cancellation. Monitor
  displays the waiting count; `/router/status` exposes `request_queue` counters.

This prevents routine busy collisions for a small group of subagents. It does
not make one GPU generate four independent answers in parallel or remove the
latency of long prefills. Different-model requests may also incur model switches.
If a client has a short total-request timeout, configure it to cover both waiting
and inference, or reduce its parallel-agent count.

Validation uses the actual router proxy against a fake HTTP backend, without a
GPU model. It checks FIFO order, one active backend call, five accepted requests,
a sixth rejected request, streaming keep-alives, disconnected-waiter cleanup,
non-streaming responses and a responsive status endpoint. It also verifies the
original immediate-429 behavior when the option is absent. Unit tests cover the
payload bound and released tickets. The fixture disables admission floors only
inside its fake Router objects; no production bypass was added.

Worker connection failures now briefly wait for the supervisor exit reason before reporting a generic disconnect. A memory guard stop is reported as such when the supervisor has published it. The worker log records free RAM, VRAM, GTT and cgroup usage alongside the guard limits. This does not change the limits or retry an interrupted generation.
