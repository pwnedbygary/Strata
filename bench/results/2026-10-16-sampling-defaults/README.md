# Sampling defaults verification — October 16, 2026

See [recommendations and primary sources](../../../docs/SAMPLING.md) and
[the installed profile mapping](../../../config/agentic-sampling.json).

- All eight models in live `/v1/models` matched that mapping.
- Seven native CPU tests passed, including default merging, explicit zero/value
  precedence, preservation of sampler fields through API adapters and llama.cpp
  launch flags.
- HTTP admission/auth/origin/profile-save/reset checks passed without a model load.
- Packaged UI check passed: thinking initially enabled, blank temperature omitted
  from requests, explicit zero retained, model changes clear the override and show
  the selected model's recommendation. UI sends were intercepted, not inferred.
- A real Saluki thinking-mode request omitted every sampler override and completed.
  The bundled llama.cpp worker's own `/props` confirmed the expected temperature,
  top-p, top-k, min-p and penalties. Floating-point representation is preserved
  in `effective-backend-sampling.json`.
- The new AppImage and the desktop-installed copy have identical hashes.

This is behavior/defaults validation, not a stochastic coding-quality benchmark
or proof of universally optimal sampling. Prior performance results remain
historical; the core GPU inference executables were not changed. HIP frontend
was rebuilt; CUDA/SYCL/Windows were not built or tested. Saluki remains loaded on
8096 after the checks. No second GPU model was loaded concurrently.
