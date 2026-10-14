# Router/AppImage smoke tests

October 14, 2026; RX 9070 XT 16 GiB, Ryzen 7800X3D, 32 GB RAM, CachyOS Linux,
system ROCm 7.2. The opt-in router packages the existing Flash executable and the
native dense development executable; original model weights remain external.

| Profile | Prompt / output tokens | Decode | Finish |
| --- | ---: | ---: | --- |
| Saluki 27B IQ2-mix, adaptive 256K limit | 68 / 77 | 33.5 tokens/s | stop |
| Flash-Next IQ3_XXS, 128K | 68 / 73 | 9.2 tokens/s | stop; cold run |

Both ran through the same packaged router at `/v1/chat/completions`; the Flash request
was submitted while Saluki was generating, and the router released Saluki before loading
Flash. This checks routing/lifecycle, not a statistically controlled speed comparison.
The prompt asked for `square(n)` returning `n*n`. Both returned a finished function.
Outputs include model reasoning in the generated-token counts.

[Saluki response and timings](saluki-chat.json) · [Cold Flash response and timings](flash-cold-chat.json).

The Release memory endpoint returned no active model. A subsequent Saluki request reloaded
the worker and produced streamed SSE ending with `[DONE]`. Discovery listed both profiles
while neither was loaded, with configured context/output ceilings and text-only modalities.
These configured limits do not prove full-window speed or quality. A missing/moved model
path failed loading while the router stayed reachable; updating the external paths and
restarting restored operation.

[Discovery JSON](models.json) · [SSE response](saluki-stream.txt) · [Unloaded status](unloaded.json).

The fresh-browser rendering check against the real packaged Saluki server reported no page
errors, showed the correct model name, and loaded the original web app's styles/fonts.
[Router screenshot](../../../docs/media/router/router.png).

Seven router integration tests, nine existing single-model lifecycle tests and 22 profile /
benchmark helper tests passed. The AppImage launcher ran with FUSE and extract-and-run;
the standalone executable reached its CLI. Other distributions, GPUs, CUDA/SYCL, concurrent
model residency and vision were not tested. System ROCm and external model/tokenizer paths
are required. Model weights are not included.
