#!/usr/bin/env python3
"""q36_compare.py - do two engine builds (or two settings of one build) give the same answers on the same prompt?

Checks (--checks, comma-separated; default logits,mtp,serve):
  logits  the qwen35 engine's `--tokens @ids --n N --dump-full-logits F` from both commands: the full logits at the
          prompt's last position and at the N - 1 greedy steps after it, compared bit for bit, with the largest
          |difference|, mean and max KL(ref || cand) in float64 and the top-1 agreement; and the two greedy answers.
  mtp     the candidate's greedy answer with its MTP drafts (`--tokens @ids --n N`, --mtp K: the profile's K unless
          --mtp-check gives one) against the reference's plain greedy answer.
  serve   `--serve` with the profile's settings, drafts as the server runs them (any engine that speaks the engine
          protocol, Flash-Next's too): a GEN request on the prompt and, with --picture, a GENI request with the
          picture's rows laid over <|image_pad|> runs; the answers of both compared.

Commands: --ref and --cand are command prefixes, split like a shell ("build-hip/strata", "strata-native --engine").
The engine arguments are the router profile's "args" (--profile) with --ctx and --prefill in place of the profile's
and --ref-args / --cand-args appended.  The environment is the profile's "env", then --set / --unset (both sides) and
--ref-env / --cand-env (one side); "@bundle/" paths resolve against --bundle (default: this checkout) and the
profile's "lib_dirs" go in front of LD_LIBRARY_PATH.  The engines run one at a time, without core files.

Prompt: --prompt FILE (text as one ChatML user turn with thinking off, tokenized with the profile's "tokenizer"
directory or --tokenizer; the text is not escaped; --cut N keeps its first N tokens) or --ids FILE (comma-separated
ids, used as they are).

Report: OUT/report.json, and its summary as one JSON line on stdout.  Exit 0 when every check passes: the logits bit
for bit (or a mean KL and a top-1 rate inside --kl-max / --top1-min), the token answers identical (only reported with
--tokens-may-differ); 1 when a check fails; 2 on a usage or engine error.

  python tools/qwen35/q36_compare.py --ref OLD/strata --cand build-hip/strata --profile PROFILE.json \\
      --prompt prompt.txt --ctx 16384 --prefill 2048 --n 33 --picture shapes.png.sve --out DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import queue
import re
import resource
import shlex
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE_PAD = 248056
SVE_MAGIC = 0x31455653
CHAT_PREFIX = "<|im_start|>user\n"
CHAT_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
PICTURE_QUESTION = "List every shape in the image with its colour, from left to right. One short line each."
CHECKS = ("logits", "mtp", "serve")


class EngineError(RuntimeError):
    pass


class UsageError(ValueError):
    pass


def resolve_bundle(value, bundle):
    if isinstance(value, str) and value.startswith("@bundle/"):
        return str(Path(bundle) / value[len("@bundle/"):])
    return value


def load_profile(path, bundle=ROOT):
    """A router profile's engine arguments, environment, library directories and tokenizer, "@bundle/" resolved."""
    p = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"args": [str(resolve_bundle(a, bundle)) for a in p.get("args", [])],
            "env": {str(k): str(resolve_bundle(v, bundle)) for k, v in p.get("env", {}).items()},
            "lib_dirs": [str(d) for d in p.get("lib_dirs", [])],
            "tokenizer": p.get("tokenizer")}


def option_value(args, names):
    for i, a in enumerate(args[:-1]):
        if a in names:
            return args[i + 1]
    return None


def set_option(args, names, value):
    """args with the option (any spelling in names) set to value: replaced in place, else appended."""
    out, found, i = [], False, 0
    while i < len(args):
        if args[i] in names:
            if not found:
                out += [names[0], str(value)]
                found = True
            i += 2
            continue
        out.append(args[i])
        i += 1
    return out if found else out + [names[0], str(value)]


def engine_args(profile_args, ctx=None, prefill=None, extra=()):
    args = list(profile_args)
    if ctx:
        args = set_option(args, ("--max-context", "--ctx"), ctx)
    if prefill:
        args = set_option(args, ("--prefill", "--chunk"), prefill)
    return args + list(extra)


def environment(profile, overrides=(), unset=()):
    env = dict(os.environ)
    env.update(profile.get("env", {}))
    for kv in overrides:
        k, sep, v = kv.partition("=")
        if not sep or not k:
            raise UsageError("expected VAR=value, got %r" % kv)
        env[k] = v
    for k in unset:
        env.pop(k, None)
    if profile.get("lib_dirs"):
        env["LD_LIBRARY_PATH"] = os.pathsep.join(profile["lib_dirs"] + [p for p in [env.get("LD_LIBRARY_PATH")] if p])
    return env


def load_tokenizer(directory):
    """strata_tokenizer.Tokenizer from a pack's tokenizer/ directory, as serve/server.py builds it."""
    sys.path.insert(0, str(ROOT / "tools"))
    import strata_tokenizer as ST
    d = Path(directory)
    vocab = json.loads((d / "vocab.json").read_text(encoding="utf-8"))
    tokens = [None] * len(vocab)
    for t, i in vocab.items():
        tokens[i] = t
    merges = (d / "merges.txt").read_text(encoding="utf-8").split("\n")
    types = json.loads((d / "token_type.json").read_text())
    try:
        cfg = json.loads((d / "tokenizer.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    return ST.Tokenizer(tokens, merges, types, cfg.get("pre") or "qwen35", cfg.get("special_ids") or None)


def chat_ids(tok, text, cut=0):
    if cut > 0:
        return (tok.encode(CHAT_PREFIX, parse_special=True) + tok.encode(text)[:cut] +
                tok.encode(CHAT_SUFFIX, parse_special=True))
    return tok.encode(CHAT_PREFIX + text + CHAT_SUFFIX, parse_special=True)


def sve_records(path):
    """(rows, nx, ny, width) of each record of a strata-vision embeddings file."""
    recs, size, off = [], os.path.getsize(path), 0
    with open(path, "rb") as f:
        while off < size:
            hdr = f.read(20)
            if len(hdr) != 20:
                raise ValueError("%s: a short record header at byte %d" % (path, off))
            magic, n, nx, ny, width = struct.unpack("<5i", hdr)
            if magic != SVE_MAGIC or n < 1 or nx < 1 or ny < 1 or nx * ny != n or width < 1:
                raise ValueError("%s: not a strata-vision record at byte %d" % (path, off))
            off += 20 + 4 * n * width
            if off > size:
                raise ValueError("%s: the record at byte %d is cut short" % (path, off - 20 - 4 * n * width))
            f.seek(off)
            recs.append((n, nx, ny, width))
    if not recs:
        raise ValueError("%s: no records" % path)
    return recs


def picture_ids(tok, rows, question=PICTURE_QUESTION):
    """One ChatML user turn: each picture as <|vision_start|>, one <|image_pad|> per row, <|vision_end|>; then the
    question."""
    ids = tok.encode(CHAT_PREFIX, parse_special=True)
    for n in rows:
        ids += tok.encode("<|vision_start|>", parse_special=True) + [IMAGE_PAD] * n
        ids += tok.encode("<|vision_end|>", parse_special=True)
    return ids + tok.encode(question + CHAT_SUFFIX, parse_special=True)


def finite(x):
    return float(x) if math.isfinite(x) else str(x)


def compare_logits(ref_path, cand_path, steps):
    """Two --dump-full-logits files (float32 [steps][vocab]): q36_lgcmp.py's numbers, plus bit identity, plus the rows
    holding a NaN or +inf in either file (the KL sum skips them, so a tolerance check must fail on them)."""
    import numpy as np
    ra, ca = Path(ref_path).read_bytes(), Path(cand_path).read_bytes()
    if steps < 1 or len(ra) != len(ca) or not ra or len(ra) % (4 * steps):
        raise EngineError("logits files of %d and %d bytes for %d steps" % (len(ra), len(ca), steps))
    vocab = len(ra) // (4 * steps)
    a = np.frombuffer(ra, dtype=np.float32).reshape(steps, vocab).astype(np.float64)
    b = np.frombuffer(ca, dtype=np.float32).reshape(steps, vocab).astype(np.float64)

    def log_softmax(x):
        m = x.max(axis=1, keepdims=True)
        return x - m - np.log(np.exp(x - m).sum(axis=1, keepdims=True))

    pa, pb = log_softmax(a), log_softmax(b)
    with np.errstate(invalid="ignore"):
        kl = np.where(np.isfinite(pa), np.exp(pa) * (pa - pb), 0.0).sum(axis=1)
    bad = (np.isnan(a) | np.isposinf(a) | np.isnan(b) | np.isposinf(b)).any(axis=1)
    return {"bit_identical": ra == ca, "steps": steps, "vocab": vocab,
            "max_abs_logit_diff": finite(np.abs(a - b).max()), "mean_kl": finite(kl.mean()),
            "max_kl": finite(kl.max()), "top1_agreement": int((a.argmax(1) == b.argmax(1)).sum()),
            "nonfinite_rows": int(bad.sum())}


def no_core_files():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run_tokens(cmd, args, env, log_path, timeout):
    """`cmd args` (a --tokens run): its greedy answer from the "gen:" line, and its stderr log."""
    with open(log_path, "w") as log:
        try:
            p = subprocess.run(cmd + args, env=env, stdout=subprocess.PIPE, stderr=log, text=True, timeout=timeout,
                               preexec_fn=no_core_files)
        except subprocess.TimeoutExpired:
            raise EngineError("%s: no answer after %d s (see %s)" % (cmd[0], timeout, log_path))
        except OSError as e:
            raise EngineError("cannot run %s: %s" % (cmd[0], e))
    toks = next(([int(x) for x in line[4:].split()] for line in p.stdout.splitlines() if line.startswith("gen:")), None)
    if p.returncode != 0 or toks is None:
        raise EngineError("%s exited %d%s (see %s)" % (cmd[0], p.returncode, "" if toks is not None else
                                                         " without a gen: line", log_path))
    return toks, Path(log_path).read_text(errors="replace")


def mtp_counts(log_text):
    m = re.search(r"MTP (\d+) drafts: (\d+) of (\d+) accepted", log_text)
    return {"drafts": int(m.group(1)), "accepted": int(m.group(2)), "offered": int(m.group(3))} if m else None


def parse_done(line):
    """The DONE line's common fields (both engines): produced, prompt tokens, prompt ms, decode ms, finish."""
    f = line.split()
    out = {"line": line}
    for i, (k, conv) in enumerate((("produced", int), ("prompt_tokens", int), ("prompt_ms", float),
                                   ("decode_ms", float), ("finish", str)), start=1):
        try:
            out[k] = conv(f[i])
        except (IndexError, ValueError):
            pass
    return out


class Served:
    """`cmd --serve args`, driven over the engine protocol (tools/qwen35/q36_harness.py's GEN / GENI subset)."""

    def __init__(self, cmd, args, env, log_path, timeout):
        self.log_path, self.timeout = log_path, timeout
        self.log = open(log_path, "w")
        try:
            self.p = subprocess.Popen(cmd + ["--serve"] + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=self.log, text=True, bufsize=1, env=env, preexec_fn=no_core_files)
        except OSError as e:
            self.log.close()
            raise EngineError("cannot run %s: %s" % (cmd[0], e))
        self.q = queue.Queue()
        self.pump = threading.Thread(target=self._pump, daemon=True)
        self.pump.start()
        t0 = time.time()
        try:
            while not self.line().startswith("READY"):
                pass
        except EngineError:
            self.close()
            raise
        self.load_s = time.time() - t0

    def _pump(self):
        for line in self.p.stdout:
            self.q.put(line.rstrip("\n"))
        self.q.put(None)

    def line(self):
        try:
            line = self.q.get(timeout=self.timeout)
        except queue.Empty:
            raise EngineError("engine silent for %d s (see %s)" % (self.timeout, self.log_path))
        if line is None:
            raise EngineError("engine ended (exit %s; see %s)" % (self.p.wait(), self.log_path))
        return line

    def generate(self, ids, n, picture=None):
        head = ("GENI %d %s" % (n, picture)) if picture else ("GEN %d" % n)
        try:
            self.p.stdin.write(head + " " + ",".join(map(str, ids)) + "\n")
            self.p.stdin.flush()
        except OSError as e:
            raise EngineError("cannot send a request to the engine: %s (see %s)" % (e, self.log_path))
        toks = []
        while True:
            line = self.line()
            if line.startswith("T "):
                toks.append(int(line.split()[1]))
            elif line.startswith("DONE"):
                return toks, parse_done(line)
            elif line.startswith("ERR"):
                raise EngineError(line)

    def close(self):
        try:
            self.p.stdin.write("STOP\n")
        except (OSError, ValueError):
            pass
        try:
            self.p.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.p.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()
        self.pump.join(timeout=10)
        self.p.stdout.close()
        self.log.close()


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def command_info(cmd):
    exe = Path(cmd[0])
    return {"command": shlex.join(cmd), "sha256": file_sha256(exe) if exe.is_file() else None}


def mtp_drafts(args, override):
    if override is not None:
        return override
    v = option_value(args, ("--mtp",))
    return int(v) if v and v.isdigit() else 0


def first_difference(a, b):
    return next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None if len(a) == len(b) else min(len(a), len(b)))


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", required=True, help="the reference engine command (a prefix, split like a shell)")
    ap.add_argument("--cand", required=True, help="the candidate engine command")
    ap.add_argument("--profile", help="router profile JSON whose args, env, lib_dirs and tokenizer are used")
    ap.add_argument("--bundle", default=str(ROOT), help='what "@bundle/" means (default: this checkout)')
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--prompt", help="prompt text file (one ChatML user turn, thinking off)")
    src.add_argument("--ids", help="file of comma-separated prompt token ids")
    ap.add_argument("--tokenizer", help="pack tokenizer directory (default: the profile's)")
    ap.add_argument("--cut", type=int, default=0, help="keep the prompt text's first N tokens")
    ap.add_argument("--ctx", type=int, help="--max-context for both (default: the profile's)")
    ap.add_argument("--prefill", help="--prefill for both (default: the profile's)")
    ap.add_argument("--n", type=int, default=33, help="greedy tokens (logits rows) per answer")
    ap.add_argument("--checks", help="comma-separated: logits, mtp, serve (default: all; the mtp check is skipped "
                    "without drafts unless named here)")
    ap.add_argument("--mtp-check", type=int, help="drafts for the mtp check (default: the profile's --mtp; 0: skip)")
    ap.add_argument("--picture", help="strata-vision embeddings file for a GENI request in the serve check")
    ap.add_argument("--question", default=PICTURE_QUESTION, help="the picture request's question")
    ap.add_argument("--picture-n", type=int, default=48, help="greedy tokens of the picture answer")
    ap.add_argument("--set", action="append", default=[], metavar="VAR=VALUE", help="environment for both (repeatable)")
    ap.add_argument("--unset", action="append", default=[], metavar="VAR", help="drop a profile variable for both")
    ap.add_argument("--ref-env", action="append", default=[], metavar="VAR=VALUE", help="environment for ref only")
    ap.add_argument("--cand-env", action="append", default=[], metavar="VAR=VALUE", help="environment for cand only")
    ap.add_argument("--ref-args", default="", help="engine arguments appended for ref only")
    ap.add_argument("--cand-args", default="", help="engine arguments appended for cand only")
    ap.add_argument("--kl-max", type=float, help="logits pass with a mean KL up to this instead of bit for bit")
    ap.add_argument("--top1-min", type=float, help="... and a top-1 agreement rate of at least this (0-1)")
    ap.add_argument("--tokens-may-differ", action="store_true", help="report the token answers, do not fail on them")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds an engine may take for one run or line")
    ap.add_argument("--out", required=True, help="output directory")
    a = ap.parse_args(argv)
    a.checks_named = a.checks is not None
    a.check_list = [c for c in (a.checks or ",".join(CHECKS)).split(",") if c]
    bad = [c for c in a.check_list if c not in CHECKS]
    if bad:
        ap.error("unknown check(s): %s" % ", ".join(bad))
    if a.n < 1 or a.picture_n < 1:
        ap.error("--n and --picture-n must be at least 1")
    return a


def main(argv=None):
    a = parse_args(argv)
    try:
        return compare(a)
    except (ValueError, OSError, ImportError) as e:
        print(json.dumps({"error": str(e)}), flush=True)
        return 2


def compare(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    prof = load_profile(a.profile, a.bundle) if a.profile else {"args": [], "env": {}, "lib_dirs": [], "tokenizer": None}
    base = engine_args(prof["args"], a.ctx, a.prefill)
    drafts = mtp_drafts(base, a.mtp_check)
    skipped = {}
    if "mtp" in a.check_list and drafts < 1:
        why = "--mtp-check %d" % a.mtp_check if a.mtp_check is not None else "the profile has no --mtp N"
        if a.checks_named:
            raise UsageError("the mtp check cannot run (%s): give --mtp-check with 1 or more drafts" % why)
        skipped["mtp"] = why
    tok = None
    if a.prompt or a.picture:
        tdir = a.tokenizer or prof.get("tokenizer")
        if not tdir:
            raise UsageError("--prompt and --picture need --tokenizer or a profile with a tokenizer")
        tok = load_tokenizer(tdir)
    if a.ids:
        ids = [int(x) for x in Path(a.ids).read_text().replace("\n", ",").split(",") if x.strip()]
    else:
        ids = chat_ids(tok, Path(a.prompt).read_text(encoding="utf-8"), a.cut)
    ids_path = out / "prompt.ids"
    ids_path.write_text(",".join(map(str, ids)))
    sides = {}
    for name, cmd, env_kv, extra in (("ref", a.ref, a.ref_env, a.ref_args), ("cand", a.cand, a.cand_env, a.cand_args)):
        sides[name] = {"cmd": shlex.split(cmd), "env": environment(prof, a.set + env_kv, a.unset),
                       "args": base + shlex.split(extra)}
    report = {"profile": a.profile, "prompt": a.prompt or a.ids, "prompt_tokens": len(ids),
              "prompt_ids_sha256": hashlib.sha256(ids_path.read_bytes()).hexdigest(),
              "context": option_value(base, ("--max-context", "--ctx")), "prefill": option_value(base, ("--prefill",)),
              "n": a.n, "set": a.set, "unset": a.unset,
              "ref": {**command_info(sides["ref"]["cmd"]), "env": a.ref_env, "args": a.ref_args},
              "cand": {**command_info(sides["cand"]["cmd"]), "env": a.cand_env, "args": a.cand_args}}
    if skipped:
        report["skipped"] = skipped
    passed = {}
    try:
        greedy = {}
        if "logits" in a.check_list:
            for name, s in sides.items():
                greedy[name], _ = run_tokens(s["cmd"], s["args"] + ["--tokens", "@" + str(ids_path), "--n", str(a.n),
                                                                    "--dump-full-logits", str(out / (name + ".logits"))],
                                             s["env"], out / (name + "-logits.log"), a.timeout)
            lg = compare_logits(out / "ref.logits", out / "cand.logits", a.n)
            lg["greedy_identical"] = greedy["ref"] == greedy["cand"]
            lg["first_token_difference"] = first_difference(greedy["ref"], greedy["cand"])
            lg["ref_tokens"], lg["cand_tokens"] = greedy["ref"], greedy["cand"]
            report["logits"] = lg
            if a.kl_max is None and a.top1_min is None:
                passed["logits"] = lg["bit_identical"]
            else:
                kl_ok = a.kl_max is None or (isinstance(lg["mean_kl"], float) and lg["mean_kl"] <= a.kl_max)
                passed["logits"] = (kl_ok and lg["nonfinite_rows"] == 0 and
                                    (a.top1_min is None or lg["top1_agreement"] >= a.top1_min * lg["steps"]))
            passed["greedy"] = lg["greedy_identical"]
        if "mtp" in a.check_list and drafts > 0:
            if "ref" not in greedy:
                s = sides["ref"]
                greedy["ref"], _ = run_tokens(s["cmd"], set_option(s["args"], ("--mtp",), 0) +
                                              ["--tokens", "@" + str(ids_path), "--n", str(a.n)],
                                              s["env"], out / "ref-greedy.log", a.timeout)
            s = sides["cand"]
            toks, log_text = run_tokens(s["cmd"], set_option(s["args"], ("--mtp",), drafts) +
                                        ["--tokens", "@" + str(ids_path), "--n", str(a.n)],
                                        s["env"], out / "cand-mtp.log", a.timeout)
            counts = mtp_counts(log_text)
            if counts is None:
                raise EngineError("the candidate's MTP run printed no draft count (see %s)" % (out / "cand-mtp.log"))
            report["mtp"] = {**counts, "identical": toks == greedy["ref"],
                             "first_token_difference": first_difference(greedy["ref"], toks), "tokens": toks}
            passed["mtp"] = report["mtp"]["identical"]
        if "serve" in a.check_list:
            pic_ids = None
            if a.picture:
                rows = [r[0] for r in sve_records(a.picture)]
                pic_ids = picture_ids(tok, rows, a.question)
                report["picture"] = {"file": a.picture, "sha256": file_sha256(a.picture), "rows": rows,
                                     "prompt_tokens": len(pic_ids), "question": a.question}
            answers = {}
            for name, s in sides.items():
                args = s["args"] + (["--vision"] if a.picture and "--vision" not in s["args"] else [])
                eng = Served(s["cmd"], args, s["env"], out / (name + "-serve.log"), a.timeout)
                try:
                    answers[name] = {"load_s": round(eng.load_s, 1), "text": eng.generate(ids, a.n)}
                    if a.picture:
                        answers[name]["picture"] = eng.generate(pic_ids, a.picture_n, str(Path(a.picture).resolve()))
                finally:
                    eng.close()
            for kind in ("text", "picture") if a.picture else ("text",):
                (rt, rd), (ct, cd) = answers["ref"][kind], answers["cand"][kind]
                report["serve_" + kind] = {"identical": rt == ct, "first_token_difference": first_difference(rt, ct),
                                           "ref_tokens": rt, "cand_tokens": ct, "ref_done": rd, "cand_done": cd}
                passed["serve_" + kind] = rt == ct
            report["serve_load_s"] = {k: v["load_s"] for k, v in answers.items()}
    except EngineError as e:
        report["error"] = str(e)
        (out / "report.json").write_text(json.dumps(report, indent=1))
        print(json.dumps({"error": str(e)}), flush=True)
        return 2
    token_checks = {"greedy", "mtp", "serve_text", "serve_picture"}
    failed = [k for k, ok in passed.items() if not ok and not (a.tokens_may_differ and k in token_checks)]
    report["passed"] = passed
    report["pass"] = not failed
    (out / "report.json").write_text(json.dumps(report, indent=1))
    summary = {"prompt_tokens": len(ids)}
    if "logits" in report:
        lg = report["logits"]
        summary.update({k: lg[k] for k in ("bit_identical", "max_abs_logit_diff", "mean_kl", "max_kl")})
        summary["top1"] = "%d/%d" % (lg["top1_agreement"], lg["steps"])
        summary["greedy_identical"] = lg["greedy_identical"]
    if "mtp" in report:
        summary["mtp_identical"] = report["mtp"]["identical"]
        summary["mtp_accepted"] = "%d/%d" % (report["mtp"]["accepted"], report["mtp"]["offered"])
    for kind in ("serve_text", "serve_picture"):
        if kind in report:
            summary[kind + "_identical"] = report[kind]["identical"]
    if skipped:
        summary["skipped"] = sorted(skipped)
    summary["pass"] = report["pass"]
    print(json.dumps(summary), flush=True)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
