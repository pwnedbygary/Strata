# Thinking-mode sampling for agentic coding

These are model-author starting points checked on October 16, 2026, not a local
quality optimization result. Temperature zero remains useful for controlled tests;
there is no single sampling configuration that is best for every coding task.
This installation uses thinking mode by default, as requested by its user.

| Model/profile family | Temperature | Top-p | Top-k | Min-p | Presence penalty | Repeat penalty |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Flash-Next IQ3_XXS | 1.0 | 0.95 | 20 | 0 | 0 | 1.0 |
| Swift 1.5 IQ3_S / IQ3_XXS, text and vision | 1.0 | 0.95 | 20 | 0 | 0 | 1.0 |
| Saluki abliterated IQ2-mix | 1.0 | 0.95 | 20 | 0 | 1.1 | 1.0 |
| Tiel Coder Q4_K_XL | 0.6 | 0.95 | 20 | 0 | 0 | 1.0 |
| Cyber Tiel Q4_K_XL | 0.6 | 0.95 | 20 | 0 | 0 | 1.0 |

Frequency penalty is zero throughout. Both Swift quantizations and their vision
variants share the same recommendation; no quant-specific sampler optimum has
been established here. Speculation, context, KV precision, placement and memory
guards are unchanged by this sampling update.

Sources:

- [Qwen Flash-Next: thinking-mode best practices](https://huggingface.co/Qwen/Qwen3.8-Flash-Next#best-practices).
  The GSQ-RCO quantization card does not supply a separate sampler prescription.
- [Swift 1.5 author's evaluation settings](https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-27b).
- [Exact Saluki abliterated release: recommended thinking sampling](https://huggingface.co/Kujira/Underdog-Saluki-27B-1.0-MTP-Abliterated-GGUF).
  This release recommends temperature 1.0 and presence penalty 1.1; its small
  reported comparisons are not a universal quality guarantee. The original,
  non-abliterated Saluki card has different guidance.
- [Tiel MTP author: agentic coding uses temperature 0.6](https://huggingface.co/peculiar-ragdoll/Tiel-Coder-35B-A3B-GGUF-MTP).
- [Cyber Tiel MTP author: agentic-coding settings](https://huggingface.co/peculiar-ragdoll/Cyber-Tiel-Coder-35B-A3B-GGUF-MTP).
  Its separate cybersecurity/CTF exploration preset uses top-k 40 and min-p 0.05;
  that is not the default coding configuration installed here.

## Where defaults apply

The local Strata profile JSONs store these values in `sampling`. The current
profile-ID mapping is recorded in [config/agentic-sampling.json](../config/agentic-sampling.json).
`GET /v1/models` exposes them under `sampling_defaults`. The router fills omitted
sampling fields for streaming and non-streaming requests before forwarding to
either engine. llama.cpp also receives profile defaults as launch flags, and the
native Anthropic/Responses adapters retain supported penalty/filter fields.

Explicit request values always win, including an intentional temperature zero.
A harness that sends `temperature: 0` will therefore still generate greedily:
remove that override or configure the harness to match the model recommendation.
Profiles without a `sampling` object retain their previous backend behavior.

In Chat, the temperature field starts empty and shows the model recommendation
as its placeholder. Empty means use model defaults. Enter a number to override
it for that chat request; changing models clears the temperature override.
Reasoning starts enabled. The output token limit remains a separate setting.

The regular llama app's existing four sections in `models/presets.ini` now use
explicit per-model temperatures: Tiel/Cyber 0.6, Swift 1.0. Their common top-p,
top-k and penalties match the table. This external INI is still separate from
the AppImage registry; no giant Flash-Next llama.cpp preset was added.
Before-change local backups are under `local-tuning/sampling/`.

Validation checks default merging, explicit-zero precedence, API adapter field
preservation, launcher flags, model discovery and UI behavior. Earlier published
throughput/quality benchmarks retain their explicit temperature-zero requests;
they were not rerun or relabeled as stochastic agentic quality results.
