# Coding-agent request queue — October 16, 2026

The native router previously returned the exact busy message shown in the user's
OpenChamber/OpenCode screenshots whenever a concurrent request missed its single
generation mutex. The screenshot also showed several subagent tasks competing.
This change enables a bounded FIFO queue for this installation, rather than
increasing GPU inference slots. See [behavior and limits](../../../docs/REQUEST_QUEUE.md).

The queue is opt-in through `queue_requests: true` in the saved router registry.
Without that flag, the immediate busy/429 path remains. The HTTP fixture checks
that behavior as well as the new path. Model paths, sampler settings, context,
KV precision, backend binaries and memory floors were preserved.

Validation:

- Nine native tests passed, including request queue unit and HTTP integration tests.
- The HTTP test invokes the actual router proxy against a fake backend. Five
  admitted requests finish in FIFO order; one is non-streaming, the others stream
  SSE. The sixth is rejected. A disconnected waiting stream is removed before
  backend dispatch. Maximum active fake backend requests is one. A status request
  remains responsive while all five generation admissions are occupied.
- Unit tests cover FIFO eligibility, payload capacity, cancelled/released tickets
  and serial ownership. No GPU model is allocated by these tests.
- Existing low-memory, auth, origin, settings and lifecycle HTTP checks passed.
- UI syntax and a packaged Monitor check passed. The latter simulates the waiting
  count on read-only status traffic; it does not submit inference.
- HIP frontend built and the dedicated Vulkan/ROCm AppImage packaged. CUDA, SYCL
  and Windows were not built or tested. No GPU kernel changed.

The desktop AppImage was atomically replaced, and the live server switched after
an old request released its generation slot. An OpenChamber request then loaded
Cyber Tiel and began prefill under the new router, with no error at the recorded
status snapshot. No extra test generation was injected into the user's session.
The cache was released by the restart, so that first request needed fresh prefill.
Old failed subagent tasks in the client may still require retrying; queue capacity,
resource exhaustion and client deadlines can still produce errors. This is not
a claim of parallel GPU throughput or a new model-performance benchmark.
