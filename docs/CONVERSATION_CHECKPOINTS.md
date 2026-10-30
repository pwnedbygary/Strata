# Conversation checkpoints on the dense engine

The dense Qwen3.8 models can keep a few snapshots of the conversation's state in host RAM; a request whose prompt
differs from the last one then resumes from the last snapshot it shares instead of re-reading the whole prompt. That
happens whenever an agent client edits an earlier message, sends an answer back in another form or prunes tool output.

## Use

Set `STRATA_Q35_CHECKPOINTS=N` in the engine's environment (for a source build, prefix the command:
`STRATA_Q35_CHECKPOINTS=8 build-hip/strata ...`; a profile's `env` reaches its engine, the native server passing it
through): up to N snapshots (1 to 64), off by default. It applies to a dense model with one session, and does
nothing on the mixture-of-experts models or with more than one session. These are not the prompt-cache checkpoints
of `--prompt-cache-tail` ([PROMPT_CACHE_TAIL.md](PROMPT_CACHE_TAIL.md)) or of the message-boundary cache
([MESSAGE_BOUNDARY_CACHE.md](MESSAGE_BOUNDARY_CACHE.md)): those reuse a prompt's cached cells; these keep the
session's recurrent state so a changed conversation resumes.

A snapshot is the session's recurrent state at a cell: each GDN layer's conv and S, and the MTP seed, about
149.6 MiB on the 27B models. The K / V cells need no copy: they are stored by position, and a read resumed at
cell p writes only cells at p or after. Snapshots are taken only at the ends of a read's chunks, so taking one
never changes the read, and a resumed read goes on in the chunks the uninterrupted read used.

Snapshots are taken at:

- the prompt's end (it keeps the last logits, so the same prompt sent again decodes at once);
- the last chunk end at or before each of the last two `<|im_start|>` cells (an edited last message, or the reply
  sent back in another form, resumes there);
- for a read of four chunks or more, the chunk ends nearest a quarter, a half and three quarters of the read (an
  edit further back resumes from one of them).

A request resumes from the longest snapshot at or below the cells its prompt shares with the held tokens; a
snapshot at the prompt's own length is used only when it kept its logits (the same prompt sent again). A resume at
cell p drops the snapshots past p, so the held snapshots lie on one branch of the conversation. When more than N
are held, the shortest stays (the point every request has so far shared, in practice the end of the client's
system prompt), the N/2 most recently used of the others stay, and of the rest the one whose removal leaves the
shortest gap between its neighbours leaves; with a cap below 3 the least recently used leaves.

The engine allocates the N buffers before it prints READY, while `STRATA_Q35_CHECKPOINTS_MIN_FREE_MIB` of RAM
stays available (5,120 by default). A refused allocation does not stop the engine: the buffers it could not take at
start-up are allocated when a snapshot needs one, which took up to 1.82 s per buffer when the buffers were allocated
on demand (the 8K runs of Oct 28 morning). On Windows there is no RAM floor.

## Quality

Checkpoints change no token: on Saluki at 8K and 128K, and on Swift IQ3_S at 8K, every answer with checkpoints was
byte-identical to the same request without them, and the code and retrieval checks matched on both sides (on Swift
the sixth answer stopped inside its code block, so it scored 0 of 13 on either side). The Swift 128K run had no
without-checkpoints side, and its sixth answer stopped mid-code the same way.

## Measured

**Measured on:** RX 9070 XT 16 GB, ROCm 7.2.4 (gfx1201), Ryzen 7 7800X3D, 32 GB RAM, Linux; in the 128K window
the desktop held 1,753 MiB of VRAM. Engine build `9d6bd0de` of this branch (HEAD 76ad36ce, above upstream
0.2.6); the Oct 28 morning runs used `e4a0e29d`, before the start-up allocation.
Underdog-Saluki-27B-1.0-IQ2-mix-MTP-abliterated.gguf (7.83 GiB) and Swift-1.5-Qwen3.8-27B IQ3_S-MTP
(11.32 GiB), each with its profile's sampling values and seed 20261026.

At about 118K tokens (context 131,072; one 9-request agent conversation; Oct 29, timed window, one run per side,
N = 8). Saluki, checkpoints against none: its three requests that edit or prune the conversation started in 10.52,
3.55 and 3.68 s against 155.35, 155.50 and 148.23 s (the 148-155 s ones re-read the whole prompt); its first
request, which reads the whole prompt either way, took 145.86 against 147.44 s; the rest 8.37, 1.52, 1.35, 1.35
and 1.29 against 7.98, 1.32, 1.26, 1.27 and 1.28 s. From engine start to the last answer the run took 4 min 11 s
against 11 min 15 s. The engine allocated 8 of 8 buffers before the first request in 3,822 ms, and after that a
snapshot took about 4 ms (5 taken in 19 ms, 2 in 7 ms). Resident memory after the first request was 2,071,448 KiB
against 875,076 KiB (+1,168 MiB; the 8K runs measured +1,198 MiB on Saluki and +1,199 MiB on Swift IQ3_S). Both
runs started with the desktop holding 1,753 MiB of VRAM, over the 1,700 MiB the window allows, so both are marked.
Swift IQ3_S with checkpoints only (no without-checkpoints side): 9 of 9 requests ran; the three resumed ones
started in 10.85, 3.66 and 3.83 s, its first request in 154.48 s.

At about 8K tokens (Oct 28, untimed, the same conversation at 8K). 8 of 8 buffers were allocated in 1,396 ms on
Saluki and 1,738 ms on Swift IQ3_S; a request's snapshots took 3-7 ms; the short turns' first token was 0.38-0.43 s
on Saluki against 0.37-0.38 s without checkpoints, and 0.76-0.80 s on Swift IQ3_S either way. Before the buffers
were allocated at start-up (Oct 28 morning, the same script at 8K), those turns took 1.35-2.19 s on Saluki with
checkpoints (0.37-0.38 without) and 0.95-1.31 s on Swift IQ3_S (0.82-0.88 without).

## Limits

- Dense Qwen3.8 models with one session; off by default.
- The N buffers are pinned from start-up: 8 x 149.6 MiB = 1,197 MiB for N = 8 on the 27B models (measured: +1,198
  MiB at 8K on Saluki, +1,199 on Swift IQ3_S, +1,168 MiB at the 128K first request), and loading takes longer by
  their allocation (1.4-3.8 s measured).
- With less free RAM, fewer buffers are allocated at start-up and the rest on demand, which took up to 1.82 s per
  buffer in the 8K runs.
- The runs drove the engine directly, not through the native server; whether the pinned buffers count against the
  router worker's cgroup budget was not measured.
- Not built: CUDA. Windows was not run: there is no RAM floor there, so all N buffers are pinned at start-up unless
  a pinned allocation fails.
- The Swift 128K run is incomplete: one side only, and its sixth answer stopped mid-code (0 of 13). The 128K
  numbers are one run (Saluki one run per side; Swift one run, checkpoints only), marked for the desktop's VRAM.
