# Dense screenshot-input checks

October 14, 2026: RX 9070 XT 16 GiB, Ryzen 7800X3D, 32 GB RAM, ROCm 7.2.
[Profiles, reproduction and limitations](../../../docs/SCREENSHOT_INPUT.md).

Each model directory contains the two fixtures, complete API responses and a report.
`tools/test_vision_profile.py` sends the same prompt with two different screenshots
having the same dimensions; it checks all four visible error fields exactly.
No expected field values are included in the text prompt.

The CPU encoder runs with four threads, maximum 2,048 visual tokens; these small images
produce 200 visual tokens. Temperature is zero, thinking disabled, output capped at 512.
Every fixture passed. Cold timings include loading/encoding and cannot be read as pure
prefill time. GPU generation timings are included separately in each response.

[Saluki abliterated MTP on/off message identity and draft counts](saluki-mtp-comparison.json).
This is a short OCR and changed-image regression check, not broad vision/grounding quality,
external full-model numerical parity, a filled-window benchmark or proof against a system reset.

The `saluki-abliterated-mtp-growth` check adds filler to each image request: 4,086 input
tokens plus 53 generated tokens cross the initial 4K cache during speculative decoding.
Both screenshots were read exactly, accepting all 26 offered drafts, at 42.8 tokens/s.
This verifies the combined image/MTP/cache-growth path, not a full-context image test.
