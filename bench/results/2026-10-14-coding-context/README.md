# Filled coding-context checks

October 14, 2026: RX 9070 XT 16 GiB, Ryzen 7800X3D, 32 GB RAM, ROCm 7.2.
Saluki abliterated IQ2-mix with embedded MTP, one greedy draft, int8 KV, adaptive 256K
limit, 128 MiB attention score budget, prefill 512. The screenshot encoder was resident
on the CPU; these requests contained text only, so they test text-prefix reuse.

`tools/coding_context_bench.py` places three Python repair requirements at different
positions among repeated archived code/tool-output blocks. It counts each fresh request
with the server tokenizer and then sends the exact prompt/answer prefix followed by a
review request. The workload is controlled and synthetic, not an actual large repository.

| Saluki MTP workload | Fresh prefill | First answer | Cached follow-up | Follow-up first content |
| --- | --- | ---: | ---: | ---: |
| 30,692 input tokens | 189.8 s; 161.7 tokens/s | 37.2 tokens/s | 35.4 tokens/s | 0.82 s |
| 63,428 input tokens | 534.6 s; 118.6 tokens/s | 16.7 tokens/s | 15.8 tokens/s | 1.10 s |
| 30,692 input tokens, JEDEC 4800 repeat | 221.0 s; 138.9 tokens/s | 32.8 tokens/s | 30.4 tokens/s | 0.88 s |

Both runs finished. The follow-ups reused 30,937 and 63,705 tokens respectively. The
engine log reported no file-backed weights through the 64K cache allocation; the slower
decode at 64K is not evidence of weight transfers. One-second host/physical-VRAM samples
are summarized alongside each response. They may miss shorter peaks. The configured
256K limit was not filled or quality-validated.

The saved first answers (including the retired Swift 32K comparison) passed thirteen
targeted boundary checks for slash normalization, parent traversal rejection, retry caps,
negative inputs, grid wrapping and invalid dimensions. Code and check details are saved
unchanged. This small check set does not establish general coding quality. The Swift
follow-up reached its 768-token cap; the Saluki follow-ups finished normally.

The historical Swift IQ3_XXS MTP run used the same 30,692-token request: 192.8 s fresh
prefill, 28.6 tokens/s initial answer, 26.9 tokens/s cached follow-up, first follow-up content
in 0.84 s. Those Swift MTP selections have since been removed from the user's registry.

## Prefill setting trials

On the same 30,692-token prompt, prefill 1024 / score budget 128 MiB took 210.8 seconds
(145.6 tokens/s), and prefill 512 / score budget 256 MiB took 211.7 seconds (145.0 tokens/s).
Both returned the same first answer and draft acceptance counts as the original run.
Neither observed result justified changing the profile's 512 / 128 MiB defaults. These
were single local trials; CPU build/packaging work also ran in the background, and the
platform had unresolved resets. They do not isolate a general performance effect of
either setting. Responses and memory summaries are retained.

## Reboots and the JEDEC comparison

Two unexpected system resets occurred during this testing period. The following boots
recorded reset reason `0x08000800`, an uncorrected data-fabric error; its originating
component was not identified. Strata runtime errors/OOM kills were not recorded as the
cause. Finishing a benchmark does not establish platform stability.

The user subsequently reset RAM, fabric and SoC settings to Auto and removed Curve
Optimizer. Both DIMMs then reported 4800 MT/s. Linux did not independently verify the
resulting PBO setting. The same 32K workload and cached follow-up completed without a
new kernel message or reboot during that short repeat. Its first answer was identical
to the earlier answer and passed all thirteen checks. One-second samples peaked at 67°C
CPU Tctl, 76°C GPU junction and 68°C GPU memory; minimum available RAM was 21.284 GiB
and minimum physical free VRAM 1,813 MiB. Multiple BIOS settings changed, so the speed
difference and absence of a reset cannot be attributed to one setting. No long-duration
stability claim is made.

Reproduce the answer checks with:

```sh
.venv/bin/python tools/check_coding_context.py path/to/fresh.md --output quality-check.json
```
