# Swift IQ3_S MTP and memory-fit trials

RX 9070 XT 16 GiB / Ryzen 7800X3D / 32 GB JEDEC 4800 RAM, ROCm 7.2, October 14, 2026.
See [settings, measurements and limitations](../../../docs/SWIFT_IQ3_S_TUNING.md).

`8k-off` and `8k-on` compare one greedy draft against no draft on the same embedded-MTP
GGUF, both using the calibrated dense prefill table and original memory settings.
`8k-on-fit` and `32k-on-fit` use 4K cache growth and a 1536 MiB reserve. The smaller
reserve deliberately uses more VRAM for weights: physical free VRAM dipped to 328 MiB
during 8K prefill. These are single trials with synthetic code/tool-log filler.

Saved answers pass 13 targeted checks. First 8K answers are identical across the three
settings. `fit-vision` contains two changed-image fixtures with a 4086-token prompt;
both returned exact values after crossing the initial 4K capacity during MTP decode.
`cache-regression` compares 64 output IDs and draft counters to a fixed-cache native
reference, including allocation/eviction/reset at the 256K ceiling. It does not test
a filled 256K prompt or broad model quality. Telemetry samples are one second apart.
