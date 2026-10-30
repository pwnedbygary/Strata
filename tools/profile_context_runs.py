#!/usr/bin/env python3
"""profile_context_runs.py - router profiles at their context limits, through the native router.

For each profile named, in order: a fresh router (--app, default the installed AppImage) on 127.0.0.1:--port without an
API key, from a copy of the registry (profile paths made absolute) and its tuning file; then
  * tools/coding_context_bench.py: a prompt of the profile's --max-context minus --margin tokens (or --tokens) with
    three retrieval probes, a fresh answer and an identical-prefix follow-up;
  * tools/check_coding_context.py: the 13 code checks on the fresh answer;
  * for a profile with --vision, a picture question on tools/qwen35/pictures/shapes.png (PASS when the answer names
    the three shapes and the three colours);
  * the router's /router/status (the engine its Automatic route chose).
The bench's requests carry no sampling fields, so the router applies each profile's own `sampling` values, plus a
fixed --seed so a repeated run draws the same tokens; --greedy sends temperature 0 and presence_penalty 0
instead, and refuses an explicit --seed. The picture question is always greedy.
The router is then stopped, and the next profile starts once no GPU compute process is left (at most --settle-max s).
A sampler records the 1-minute load, available RAM, GPU busy %, VRAM used, GPU compute processes and the top CPU users
every --sample-every s; the table takes each profile's peak VRAM, lowest available RAM and highest load from it.

Output in --out: the registry copies, inputs.sha256, progress.txt (with a summary per profile), load.log (JSON lines),
a directory per profile (the bench's files, code-check.json, picture.json, router-status.json, router.log, run.json)
and table.md.  Exit 0 when every profile ran to the end (the checks' results are in the table), 1 when one did not,
2 on a usage error.

  python tools/profile_context_runs.py --out DIR [--registry ~/.config/strata/router.json] [--app APPIMAGE]
      [--deadline "YYYY-MM-DD HH:MM"] [--tokens N] PROFILE...
  python tools/profile_context_runs.py --table DIR        # the table of an earlier run
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import os
import resource
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PICTURE = ROOT / "tools" / "qwen35" / "pictures" / "shapes.png"
PICTURE_QUESTION = "Which shapes are in this picture, and what colour is each one? One short line per shape."
PICTURE_WORDS = ("circle", "square", "triangle", "red", "blue", "green")
KFD = Path("/sys/class/kfd/kfd/proc")
# every request goes to the router on 127.0.0.1, never through a proxy set in the environment
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PROXY_VARS = ("http_proxy", "https_proxy", "all_proxy")


class UsageError(ValueError):
    pass


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def no_core_files():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def gpu_device():
    for dev in sorted(Path("/sys/class/drm").glob("card*/device")):
        try:
            if int((dev / "mem_info_vram_total").read_text()) > 1 << 30:
                return dev
        except (OSError, ValueError):
            continue
    return None


def read_int(path):
    try:
        return int(Path(path).read_text())
    except (OSError, ValueError):
        return None


def gpu_processes():
    return sorted(os.listdir(KFD)) if KFD.is_dir() else []


def machine_state(dev):
    info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    state = {"t": round(time.time(), 1), "time": time.strftime("%H:%M:%S"),
             "load1": float(Path("/proc/loadavg").read_text().split()[0]),
             "mem_avail_gib": round(int(info["MemAvailable"].split()[0]) / 2 ** 20, 1), "kfd": gpu_processes()}
    if dev is not None:
        used = read_int(dev / "mem_info_vram_used")
        state["vram_mib"] = used // 2 ** 20 if used is not None else None
        state["gpu_busy"] = read_int(dev / "gpu_busy_percent")
    return state


def state_text(s):
    return "load %.2f, %.1f GiB available, VRAM %s MiB, GPU busy %s%%, GPU processes [%s]" % (
        s["load1"], s["mem_avail_gib"], s.get("vram_mib", "-"), s.get("gpu_busy", "-"), " ".join(s["kfd"]))


def top_cpu():
    try:
        out = subprocess.run(["ps", "-eo", "pcpu=,comm=", "--sort=-pcpu"], capture_output=True, text=True, timeout=10)
        return ",".join("%s:%s" % tuple(reversed(line.split(None, 1))) for line in out.stdout.splitlines()[:3]
                        if len(line.split(None, 1)) == 2)
    except (OSError, subprocess.TimeoutExpired):
        return None


class Sampler(threading.Thread):
    def __init__(self, path, dev, every):
        super().__init__(daemon=True)
        self.path, self.dev, self.every = path, dev, every
        self.done = threading.Event()

    def run(self):
        with open(self.path, "a") as f:
            while True:
                s = machine_state(self.dev)
                s["top"] = top_cpu()
                f.write(json.dumps(s) + "\n")
                f.flush()
                if self.done.wait(self.every):
                    break

    def stop(self):
        self.done.set()
        self.join(timeout=self.every + 15)


def copy_registry(registry, out):
    """registry (router.json) into out with its profile paths made absolute, and its tuning file beside it (the
    router reads <registry dir>/native-tuning-<registry stem>.json); returns the copy and {name: profile path}."""
    registry = Path(registry).expanduser().resolve()
    reg = json.loads(registry.read_text())
    profiles = {}
    for name, path in reg.get("profiles", {}).items():
        if not isinstance(path, str):
            raise UsageError("%s: profile %r is not a file path" % (registry, name))
        p = Path(path).expanduser()
        profiles[name] = str(p if p.is_absolute() else registry.parent / p)
    reg["profiles"] = profiles
    copy = out / registry.name
    copy.write_text(json.dumps(reg, indent=2) + "\n")
    tuning = registry.parent / ("native-tuning-" + registry.stem + ".json")
    if tuning.exists():
        (out / tuning.name).write_bytes(tuning.read_bytes())
    return copy, profiles


def profile_context(path):
    args = [str(a) for a in load_json(path).get("args", [])]
    ctx = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ("--max-context", "--ctx")), None)
    return (int(ctx) if ctx and ctx.isdigit() else None), "--vision" in args


def picture_pass(status, text):
    return status == 200 and all(w in text.lower() for w in PICTURE_WORDS)


def picture_check(url, model, out_path, timeout):
    png = base64.b64encode(PICTURE.read_bytes()).decode()
    body = {"model": model, "temperature": 0, "presence_penalty": 0, "max_tokens": 160, "reasoning_effort": "none",
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + png}},
                {"type": "text", "text": PICTURE_QUESTION}]}]}
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with LOCAL.open(req, timeout=timeout) as r:
            status, data = r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        status, data = e.code, {"error": e.read().decode(errors="replace")[:2000]}
    except (OSError, ValueError) as e:
        status, data = None, {"error": str(e)}
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    result = {"status": status, "seconds": round(time.monotonic() - t0, 1), "answer": text,
              "pass": picture_pass(status, text), "raw": data}
    out_path.write_text(json.dumps(result, indent=1) + "\n")
    return result


def without_proxies(env):
    return {k: v for k, v in env.items() if k.lower() not in PROXY_VARS}


def get_json(url, timeout=10):
    try:
        with LOCAL.open(url, timeout=timeout) as r:
            return json.loads(r.read())
    except (OSError, ValueError) as e:
        return {"error": str(e)}


def start_router(app, registry, port, log_path):
    env = {k: v for k, v in os.environ.items() if k != "STRATA_API_KEY"}
    log = open(log_path, "w")
    try:
        proc = subprocess.Popen(shlex.split(app) + ["--registry", str(registry), "--host", "127.0.0.1", "--port", str(port)],
                                stdout=log, stderr=subprocess.STDOUT, env=env, preexec_fn=no_core_files)
    except OSError:
        log.close()
        raise
    return proc, log


def wait_health(url, proc, timeout=120):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout and proc.poll() is None:
        try:
            with LOCAL.open(url + "/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except (OSError, ValueError):
            pass
        time.sleep(0.4)
    return False


def stop_router(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    return proc.returncode


def appimage_mounts():
    found = []
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                if b".mount_strata" in (p / "cmdline").read_bytes().lower():
                    found.append(int(p.name))
            except OSError:
                pass
    return found


def settle(max_s):
    t0 = time.monotonic()
    while time.monotonic() - t0 < max_s and (gpu_processes() or appimage_mounts()):
        time.sleep(1)
    return round(time.monotonic() - t0, 1)


def summarize(pdir):
    r = load_json(pdir / "report.json")
    lines = ["%s: prompt %s tokens (target %s)" % (pdir.name, r.get("counted_prompt_tokens"), r.get("target_prompt_tokens"))]
    for x in r.get("runs", []):
        t = x.get("timings") or {}
        lines.append("%s: completed=%s prompt_n=%s cached=%s prompt %.1f tok/s (%.1f s), decode %.2f tok/s x %s, drafts "
                     "%s/%s, first content %.1f s, wall %s s" % (
                         x.get("phase"), x.get("completed"), t.get("prompt_n"), t.get("cache_n"),
                         t.get("prompt_per_second") or 0, (t.get("prompt_ms") or 0) / 1000,
                         t.get("predicted_per_second") or 0, t.get("predicted_n"), t.get("draft_n_accepted"),
                         t.get("draft_n"), x.get("first_content_seconds") or 0, x.get("elapsed_seconds")))
    rc, cc = load_json(pdir / "retrieval-check.json"), load_json(pdir / "code-check.json")
    inf = (load_json(pdir / "router-status.json").get("profile") or {}).get("inference") or {}
    lines.append("retrieval %s/%s; code checks %s/%s; route %s / %s / %s" % (
        rc.get("passed"), rc.get("total"), cc.get("passed"), cc.get("total"), inf.get("engine"), inf.get("device"),
        inf.get("build")))
    if (pdir / "picture.json").exists():
        pic = load_json(pdir / "picture.json")
        lines.append("picture %s (HTTP %s, %s s)" % ("PASS" if pic.get("pass") else "FAIL", pic.get("status"),
                                                    pic.get("seconds")))
    return lines


def table(run_dir):
    """Markdown: per profile (in run order) the engine, prompt size, the fresh answer's prompt and decode speeds and
    drafts, the follow-up's first-content time and decode speed, retrieval, code checks, picture, and from load.log the
    peak VRAM, lowest available RAM and highest 1-minute load while it ran."""
    run_dir = Path(run_dir)
    samples = []
    if (run_dir / "load.log").exists():
        for line in (run_dir / "load.log").read_text().splitlines():
            try:
                samples.append(json.loads(line))
            except ValueError:
                pass
    recs = sorted((load_json(p) for p in run_dir.glob("*/run.json")), key=lambda r: r.get("started", 0))
    modes = sorted({"greedy (temperature 0, presence_penalty 0)" if r["sampling"] == "greedy" else
                    "each profile's own sampling, seed %s" % r.get("seed") for r in recs if r.get("sampling")})
    out = ["Requests: %s." % "; ".join(modes), ""] if modes else []
    out += ["| Profile | Engine | Prompt tokens | Prompt tok/s (s) | Decode tok/s | Drafts | Follow-up: first token s, "
            "decode tok/s | Retrieval | Code | Picture | Peak VRAM MiB | Min RAM free GiB | Max load |",
            "|---|---|---:|---:|---:|---:|---:|---|---|---|---:|---:|---:|"]
    for rec in recs:
        d = run_dir / rec["profile"]
        r = load_json(d / "report.json")
        runs = {x.get("phase"): x for x in r.get("runs", [])}
        fresh, follow = runs.get("fresh", {}), runs.get("follow-up", {})
        ft, ut = fresh.get("timings") or {}, follow.get("timings") or {}
        inf = (load_json(d / "router-status.json").get("profile") or {}).get("inference") or {}
        rc, cc, pic = load_json(d / "retrieval-check.json"), load_json(d / "code-check.json"), load_json(d / "picture.json")
        window = [s for s in samples if rec.get("started", 0) <= s.get("t", 0) <= rec.get("stopped", float("inf"))]
        vram = max((s["vram_mib"] for s in window if s.get("vram_mib") is not None), default=None)
        ram = min((s["mem_avail_gib"] for s in window), default=None)
        load = max((s["load1"] for s in window), default=None)
        note = "" if rec.get("bench_exit") == 0 else " (%s)" % (rec.get("error") or "bench exit %s" % rec.get("bench_exit"))
        out.append("| %s%s | %s | %s | %s | %s | %s | %s | %s/%s | %s/%s | %s | %s | %s | %s |" % (
            rec["profile"], note, inf.get("engine", "-"), r.get("counted_prompt_tokens", "-"),
            "%.0f (%.0f)" % (ft.get("prompt_per_second") or 0, (ft.get("prompt_ms") or 0) / 1000) if ft else "-",
            "%.2f" % (ft.get("predicted_per_second") or 0) if ft else "-",
            "%s/%s" % (ft.get("draft_n_accepted"), ft.get("draft_n")) if ft.get("draft_n") else "-",
            "%.1f, %.2f" % (follow.get("first_content_seconds") or 0, ut.get("predicted_per_second") or 0) if ut else "-",
            rc.get("passed", "-"), rc.get("total", "-"), cc.get("passed", "-"), cc.get("total", "-"),
            ("pass" if pic.get("pass") else "FAIL") if pic else "-", "-" if vram is None else vram,
            "-" if ram is None else "%.1f" % ram, "-" if load is None else "%.1f" % load))
    return "\n".join(out)


def parse_deadline(text):
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M").timestamp()
    except ValueError:
        raise UsageError("--deadline takes a full date and time, YYYY-MM-DD HH:MM, not %r" % text)


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profiles", nargs="*", help="registry profile names, run in this order")
    ap.add_argument("--out", help="output directory")
    ap.add_argument("--table", metavar="DIR", help="print the table of an earlier run and exit")
    ap.add_argument("--registry", default="~/.config/strata/router.json", help="router.json (read only)")
    ap.add_argument("--app", default="~/Applications/strata_model_router.appimage",
                    help="router command (a prefix, split like a shell)")
    ap.add_argument("--port", type=int, default=18098)
    ap.add_argument("--tokens", type=int, help="prompt tokens for every profile (default: context minus --margin)")
    ap.add_argument("--margin", type=int, default=2048, help="context left for the answers")
    ap.add_argument("--greedy", action="store_true", help="greedy requests (temperature 0 and presence_penalty 0), "
                                                          "not the profiles' sampling")
    ap.add_argument("--seed", type=int, help="seed of the sampled requests (default 20261026; refused with --greedy)")
    ap.add_argument("--deadline", help='no profile starts after this ("YYYY-MM-DD HH:MM")')
    ap.add_argument("--request-timeout", type=int, default=7200, help="seconds for one request")
    ap.add_argument("--settle-max", type=float, default=90, help="seconds to wait for the GPU to be free between profiles")
    ap.add_argument("--sample-every", type=float, default=10.0, help="sampler period in seconds")
    a = ap.parse_args(argv)
    if a.greedy and a.seed is not None:
        ap.error("--seed needs the profile's sampling: the runner sends no seed with --greedy")
    if not a.table and (not a.out or not a.profiles):
        ap.error("--out and at least one profile are needed (or --table DIR)")
    a.app = os.path.expanduser(a.app)
    return a


def main(argv=None):
    a = parse_args(argv)
    if a.table:
        print(table(a.table))
        return 0
    seed = a.seed if a.seed is not None else 20261026
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        deadline = parse_deadline(a.deadline) if a.deadline else None
        registry, profiles = copy_registry(a.registry, out)
        missing = [p for p in a.profiles if p not in profiles]
        if missing:
            raise UsageError("not in %s: %s" % (a.registry, ", ".join(missing)))
    except (UsageError, OSError, ValueError) as e:
        print("profile_context_runs: %s" % e, file=sys.stderr)
        return 2
    exe = Path(shlex.split(a.app)[0])
    with open(out / "inputs.sha256", "w") as f:
        for path in ([exe] if exe.is_file() else []) + [Path(profiles[p]) for p in a.profiles]:
            f.write("%s  %s\n" % (file_sha256(path), path))
    progress = open(out / "progress.txt", "a")

    def log(text):
        line = "%s %s" % (time.strftime("%H:%M:%S"), text)
        print(line, flush=True)
        progress.write(line + "\n")
        progress.flush()

    dev = gpu_device()
    url = "http://127.0.0.1:%d" % a.port
    sampler = Sampler(out / "load.log", dev, a.sample_every)
    sampler.start()
    log("start: " + state_text(machine_state(dev)))
    complete = True
    try:
        for name in a.profiles:
            if deadline is not None and time.time() > deadline:
                log("%s not started: past the deadline" % name)
                complete = False
                continue
            ctx, vision = profile_context(profiles[name])
            tokens = a.tokens or (ctx - a.margin if ctx else None)
            if not tokens or tokens < 1:
                log("%s not started: no --max-context in %s and no --tokens" % (name, profiles[name]))
                complete = False
                continue
            pdir = out / name
            pdir.mkdir(exist_ok=True)
            rec = {"profile": name, "profile_file": profiles[name], "context": ctx, "prompt_target": tokens,
                   "sampling": "greedy" if a.greedy else "profile", "seed": None if a.greedy else seed,
                   "started": time.time()}
            try:
                proc, rlog = start_router(a.app, registry, a.port, pdir / "router.log")
            except OSError as e:
                log("%s: cannot start the router: %s" % (name, e))
                complete = False
                continue
            try:
                if not wait_health(url, proc):
                    rec["error"] = "the router did not answer (exit %s)" % proc.poll()
                    log("%s: %s" % (name, rec["error"]))
                else:
                    log("%s start: context %s, prompt target %d tokens, %s requests; %s" % (
                        name, ctx, tokens, rec["sampling"], state_text(machine_state(dev))))
                    cmd = [sys.executable, str(ROOT / "tools" / "coding_context_bench.py"), "--model", name,
                           "--tokens", str(tokens), "--long-context-probes", "--request-timeout", str(a.request_timeout),
                           "--base-url", url, "--output", str(pdir)]
                    cmd += ["--sampling", "greedy"] if a.greedy else ["--sampling", "profile", "--seed", str(seed)]
                    with open(out / (name + ".out"), "w") as bench_out:
                        try:
                            rec["bench_exit"] = subprocess.run(cmd, stdout=bench_out, stderr=subprocess.STDOUT,
                                                               env=without_proxies(os.environ),
                                                               timeout=3 * a.request_timeout).returncode
                        except subprocess.TimeoutExpired:
                            rec["bench_exit"] = "timeout"
                    log("%s bench exit=%s; %s" % (name, rec["bench_exit"], state_text(machine_state(dev))))
                    (pdir / "router-status.json").write_text(json.dumps(get_json(url + "/router/status"), indent=1))
                    if (pdir / "fresh.md").exists():
                        chk = subprocess.run([sys.executable, str(ROOT / "tools" / "check_coding_context.py"),
                                              str(pdir / "fresh.md"), "--output", str(pdir / "code-check.json")],
                                             capture_output=True, text=True, timeout=60)
                        (pdir / "code-check.out").write_text(chk.stdout + chk.stderr)
                    if vision:
                        pic = picture_check(url, name, pdir / "picture.json", min(a.request_timeout, 900))
                        log("%s picture %s: HTTP %s, %.1f s: %r" % (name, "PASS" if pic["pass"] else "FAIL",
                                                                   pic["status"], pic["seconds"], pic["answer"][:200]))
            finally:
                rec["router_exit"] = stop_router(proc)
                rlog.close()
                rec["settle_s"] = settle(a.settle_max)
                rec["stopped"] = time.time()
                (pdir / "run.json").write_text(json.dumps(rec, indent=1) + "\n")
            for line in summarize(pdir):
                log("  " + line)
            log("%s router stopped, GPU free after %s s; %s" % (name, rec["settle_s"], state_text(machine_state(dev))))
            complete = complete and rec.get("bench_exit") == 0
    finally:
        sampler.stop()
        (out / "table.md").write_text(table(out) + "\n")
        log("done")
        progress.close()
    print((out / "table.md").read_text(), end="")
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
