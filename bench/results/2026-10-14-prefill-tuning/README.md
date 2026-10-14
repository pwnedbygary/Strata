# Dense prefill calibration results

RX 9070 XT 16 GiB, Ryzen 7800X3D, 32 GB JEDEC 4800 RAM, ROCm 7.2, October 14, 2026.
Saluki abliterated IQ2-mix, greedy embedded MTP (one draft), adaptive 256K ceiling,
int8 KV, prefill 512, 128 MiB attention score budget. Text-only counted coding tests
with a resident CPU screenshot encoder, then two changed-image regression checks.

See [configuration, interpretation and limits](../../../docs/PREFILL_TUNING.md).
`baseline-4k.log` and `tuned-4k.log` are synthetic native prefill trials (three repeats).
`calibration.log` records numerical error checks against rocBLAS for the nine shapes
in `shapes.json`. Coding reports retain fresh/cached timings, original answers, counted
prompt, SSE progress and one-second resource samples. Both first answers match their
saved baselines and pass 13 checks. Screenshot fixtures both match their exact expected
values. No new kernel error was observed during the short coding trials; previous
platform resets are unresolved. This does not establish 256K quality or system stability.

32K: 67.2 seconds / 456.9 prompt tokens/s; 32.7 decode; 31.3 cached review decode.
64K: 258.9 seconds / 245.0 prompt tokens/s; 16.6 decode.
CUDA and SYCL were not built or tested.
