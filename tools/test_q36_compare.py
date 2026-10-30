#!/usr/bin/env python3
"""tools/qwen35/q36_compare.py without a GPU: its helpers, and whole runs against a fake engine that speaks the
engine's command line (--tokens / --dump-full-logits / --mtp) and its --serve protocol (GEN / GENI)."""
from pathlib import Path
import gc
import io
import json
import math
import os
import struct
import sys
import tempfile
import textwrap
import unittest
import warnings
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parent / "qwen35"))
import q36_compare as qc  # noqa: E402

FAKE_ENGINE = textwrap.dedent(r'''
    import os, random, struct, sys
    V = 16
    args = sys.argv[1:]
    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args else default
    if os.environ.get("FAKE_PROFILE_ENV") != "yes" or opt("--native", "").startswith("@bundle/"):
        sys.exit(4)
    if os.environ.get("FAKE_BROKEN"):
        sys.exit(3)
    noise = float(os.environ.get("FAKE_NOISE", "0"))
    def row(ids, step):
        r = random.Random(sum(ids) * 1000 + step)
        x = [r.uniform(-4, 4) for _ in range(V)]
        top = max(x)
        return [v if v == top else v - noise for v in x]
    def answer(ids, n):
        return [max(range(V), key=row(ids, s).__getitem__) for s in range(n)]
    if "--serve" in args:
        if os.environ.get("FAKE_SERVE_DIE"):
            sys.exit(5)
        shift = int(os.environ.get("FAKE_SERVE_SHIFT", "0"))
        print("INFO context=%s kv=int8" % opt("--max-context"))
        print("READY %s stop" % opt("--max-context"), flush=True)
        for line in sys.stdin:
            f = line.split()
            if not f or f[0] == "STOP":
                break
            if f[0] == "GENI" and ("--vision" not in args or not os.path.exists(f[2])):
                print("ERR GENI needs --vision and a file", flush=True)
                continue
            ids = [int(x) for x in f[-1].split(",")]
            toks = [(t + shift) % V for t in answer(ids, int(f[1]))]
            for t in toks:
                print("T %d" % t)
            print("DONE %d %d 12.5 34.0 length 0 0 0 0 0 0 0 0.0 0 0" % (len(toks), len(ids)), flush=True)
        sys.exit(0)
    ids = [int(x) for x in open(opt("--tokens")[1:]).read().split(",")]
    n = int(opt("--n"))
    toks = answer(ids, n)
    dump, mtp = opt("--dump-full-logits"), int(opt("--mtp", "0"))
    if dump:
        with open(dump, "wb") as f:
            for s in range(n):
                vals = [float("nan")] * V if s == 0 and os.environ.get("FAKE_NAN") else row(ids, s)
                f.write(struct.pack("<%df" % V, *vals))
    elif mtp > 0:
        if os.environ.get("FAKE_MTP_DIFF"):
            toks[-1] = (toks[-1] + 1) % V
        print("strata-q36: prompt %d tokens, MTP %d drafts: 7 of 9 accepted (78%%)" % (len(ids), mtp), file=sys.stderr)
    print("gen: " + " ".join(map(str, toks)))
''')


class FakeTok:
    SPECIAL = {"<|im_start|>": 1, "<|im_end|>": 2, "<|vision_start|>": 3, "<|vision_end|>": 4}

    def encode(self, text, parse_special=False):
        out, i = [], 0
        while i < len(text):
            hit = next((s for s in self.SPECIAL if parse_special and text.startswith(s, i)), None)
            if hit:
                out.append(self.SPECIAL[hit])
                i += len(hit)
            else:
                out.append(1000 + ord(text[i]))
                i += 1
        return out


def write_sve(path, records, width=4):
    with open(path, "wb") as f:
        for nx, ny in records:
            f.write(struct.pack("<5i", qc.SVE_MAGIC, nx * ny, nx, ny, width))
            f.write(struct.pack("<%df" % (nx * ny * width), *([0.25] * (nx * ny * width))))


class Helpers(unittest.TestCase):
    def test_set_option_replaces_every_spelling_once_or_appends(self):
        args = ["--native", "m.gguf", "--ctx", "4096", "--prefill", "512", "--max-context", "8192"]
        self.assertEqual(qc.set_option(args, ("--max-context", "--ctx"), 16384),
                         ["--native", "m.gguf", "--max-context", "16384", "--prefill", "512"])
        self.assertEqual(qc.set_option(["--native", "m"], ("--mtp",), 2), ["--native", "m", "--mtp", "2"])

    def test_engine_args_and_profile(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "profile.json"
            p.write_text(json.dumps({"args": ["--native", "@bundle/m.gguf", "--max-context", "131072", "--mtp", "2"],
                                     "env": {"TABLE": "@bundle/tools/hip/t.txt", "N": 1}, "lib_dirs": ["/opt/x"],
                                     "tokenizer": "/packs/t"}))
            prof = qc.load_profile(p, "/b")
            self.assertEqual(prof["args"], ["--native", "/b/m.gguf", "--max-context", "131072", "--mtp", "2"])
            self.assertEqual(prof["env"], {"TABLE": "/b/tools/hip/t.txt", "N": "1"})
            self.assertEqual(qc.engine_args(prof["args"], 16384, "2048", ["--x"]),
                             ["--native", "/b/m.gguf", "--max-context", "16384", "--mtp", "2", "--prefill", "2048", "--x"])
            self.assertEqual(qc.mtp_drafts(prof["args"], None), 2)
            self.assertEqual(qc.mtp_drafts(prof["args"], 0), 0)
            env = qc.environment(prof, ["A=1", "TABLE=mine"], ["N"])
            self.assertEqual((env["A"], env["TABLE"], "N" in env), ("1", "mine", False))
            self.assertTrue(env["LD_LIBRARY_PATH"].startswith("/opt/x"))
            with self.assertRaises(qc.UsageError):
                qc.environment(prof, ["NOEQUALS"])

    def test_compare_logits_against_hand_numbers(self):
        with tempfile.TemporaryDirectory() as d:
            ref, same, other = (Path(d) / n for n in ("ref", "same", "other"))
            # step 0: p = (1/2, 1/2) against q = (1/4, 3/4): KL = 0.5 ln 2 + 0.5 ln(2/3) = 0.5 ln(4/3); top-1 differs
            # step 1: identical rows, KL 0
            ref.write_bytes(struct.pack("<4f", 0.0, 0.0, 2.0, 0.0))
            same.write_bytes(ref.read_bytes())
            other.write_bytes(struct.pack("<4f", 0.0, math.log(3.0), 2.0, 0.0))
            r = qc.compare_logits(ref, same, 2)
            self.assertTrue(r["bit_identical"])
            self.assertEqual((r["vocab"], r["top1_agreement"], r["mean_kl"], r["max_abs_logit_diff"]), (2, 2, 0.0, 0.0))
            r = qc.compare_logits(ref, other, 2)
            self.assertFalse(r["bit_identical"])
            self.assertEqual(r["top1_agreement"], 1)
            self.assertAlmostEqual(r["max_kl"], 0.5 * math.log(4.0 / 3.0), places=6)
            self.assertAlmostEqual(r["mean_kl"], 0.25 * math.log(4.0 / 3.0), places=6)
            self.assertAlmostEqual(r["max_abs_logit_diff"], math.log(3.0), places=5)
            with self.assertRaises(qc.EngineError):
                qc.compare_logits(ref, other, 3)

    def test_sve_records_and_picture_ids(self):
        with tempfile.TemporaryDirectory() as d:
            sve = Path(d) / "two.sve"
            write_sve(sve, [(3, 2), (2, 2)])
            self.assertEqual(qc.sve_records(sve), [(6, 3, 2, 4), (4, 2, 2, 4)])
            sve.write_bytes(sve.read_bytes()[:-4])
            with self.assertRaises(ValueError):
                qc.sve_records(sve)
            sve.write_bytes(struct.pack("<5i", 0x12345678, 1, 1, 1, 4) + b"\0" * 16)
            with self.assertRaises(ValueError):
                qc.sve_records(sve)
        ids = qc.picture_ids(FakeTok(), [6, 4], "Q")
        pads = [i for i, t in enumerate(ids) if t == qc.IMAGE_PAD]
        self.assertEqual(len(pads), 10)
        self.assertEqual(ids[pads[0] - 1], 3)
        self.assertEqual(ids[pads[5] + 1], 4)
        self.assertEqual(ids[pads[6] - 1], 3)
        self.assertEqual(ids[:2], [1, 1000 + ord("u")])

    def test_parse_done_and_first_difference(self):
        d = qc.parse_done("DONE 48 287 120.5 900.0 length 40 45 0 0 0 0 0 0.0 287 0")
        self.assertEqual((d["produced"], d["prompt_tokens"], d["prompt_ms"], d["decode_ms"], d["finish"]),
                         (48, 287, 120.5, 900.0, "length"))
        self.assertEqual(qc.first_difference([1, 2, 3], [1, 2, 3]), None)
        self.assertEqual(qc.first_difference([1, 2, 3], [1, 5, 3]), 1)
        self.assertEqual(qc.first_difference([1, 2], [1, 2, 3]), 2)

    def test_a_missing_module_exits_2(self):
        def missing(a):
            raise ImportError("No module named 'numpy'")
        saved, qc.compare = qc.compare, missing
        buf = io.StringIO()
        try:
            with tempfile.TemporaryDirectory() as d, redirect_stdout(buf):
                code = qc.main(["--ref", "r", "--cand", "c", "--ids", "x", "--out", d])
        finally:
            qc.compare = saved
        self.assertEqual(code, 2)
        self.assertIn("numpy", json.loads(buf.getvalue())["error"])


class WholeRuns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "engine.py").write_text(FAKE_ENGINE)
        (self.d / "prompt.ids").write_text("5,9,11,2,7")
        self.profile = self.d / "profile.json"
        self.profile.write_text(json.dumps({"args": ["--native", "@bundle/m.gguf", "--max-context", "131072",
                                                     "--prefill", "2048", "--mtp", "2"],
                                            "env": {"FAKE_PROFILE_ENV": "yes"}, "tokenizer": "unused"}))
        write_sve(self.d / "pic.sve", [(4, 3)])
        self.engine = "%s %s" % (sys.executable, self.d / "engine.py")
        self.saved = qc.load_tokenizer
        qc.load_tokenizer = lambda directory: FakeTok()

    def tearDown(self):
        qc.load_tokenizer = self.saved
        self.tmp.cleanup()

    def run_compare(self, *extra, name="out", profile=None):
        out = self.d / name
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = qc.main(["--ref", self.engine, "--cand", self.engine, "--profile", str(profile or self.profile),
                            "--bundle", str(self.d), "--ids", str(self.d / "prompt.ids"), "--ctx", "16384",
                            "--n", "6", "--picture", str(self.d / "pic.sve"), "--picture-n", "4", "--out", str(out),
                            *extra])
        report = json.loads((out / "report.json").read_text()) if (out / "report.json").exists() else None
        return code, json.loads(buf.getvalue().strip().splitlines()[-1]), report

    def test_identical_builds_pass_every_check(self):
        code, summary, report = self.run_compare()
        self.assertEqual(code, 0, summary)
        self.assertTrue(summary["bit_identical"] and summary["greedy_identical"] and summary["mtp_identical"])
        self.assertTrue(summary["serve_text_identical"] and summary["serve_picture_identical"])
        self.assertEqual(summary["top1"], "6/6")
        self.assertEqual(summary["mtp_accepted"], "7/9")
        self.assertEqual(report["context"], "16384")
        self.assertEqual(report["picture"]["rows"], [12])
        self.assertEqual(report["serve_picture"]["ref_done"]["prompt_tokens"], report["picture"]["prompt_tokens"])
        self.assertEqual(report["logits"]["steps"], 6)

    def test_changed_logits_fail_unless_inside_the_tolerance(self):
        code, summary, report = self.run_compare("--cand-env", "FAKE_NOISE=0.05")
        self.assertEqual(code, 1)
        self.assertFalse(summary["bit_identical"])
        self.assertTrue(summary["greedy_identical"])
        self.assertGreater(report["logits"]["mean_kl"], 0.0)
        code, summary, _ = self.run_compare("--cand-env", "FAKE_NOISE=0.05", "--kl-max", "1.0", "--top1-min", "0.99",
                                            name="tolerant")
        self.assertEqual(code, 0, summary)

    def test_token_differences(self):
        code, summary, report = self.run_compare("--cand-env", "FAKE_SERVE_SHIFT=1", "--cand-env", "FAKE_MTP_DIFF=1")
        self.assertEqual(code, 1)
        self.assertFalse(summary["serve_text_identical"] or summary["mtp_identical"])
        self.assertEqual(report["serve_text"]["first_token_difference"], 0)
        self.assertEqual(report["mtp"]["first_token_difference"], 5)
        code, _, _ = self.run_compare("--cand-env", "FAKE_SERVE_SHIFT=1", "--tokens-may-differ", name="may")
        self.assertEqual(code, 0)

    def test_mtp_check_without_logits_and_a_broken_engine(self):
        code, summary, report = self.run_compare("--checks", "mtp", name="mtp-only")
        self.assertEqual(code, 0, summary)
        self.assertNotIn("logits", report)
        self.assertTrue((self.d / "mtp-only" / "ref-greedy.log").exists())
        code, summary, report = self.run_compare("--cand-env", "FAKE_BROKEN=1", name="broken")
        self.assertEqual(code, 2)
        self.assertIn("exited 3", summary["error"])
        self.assertIn("error", report)
        code, summary, _ = self.run_compare("--checks", "serve", "--cand-env", "FAKE_SERVE_DIE=1", name="died")
        self.assertEqual(code, 2)
        self.assertIn("exit 5", summary["error"])

    def test_a_nan_row_fails_a_tolerance_check(self):
        code, summary, report = self.run_compare("--ref-env", "FAKE_NAN=1", "--kl-max", "1.0", "--top1-min", "0.5")
        self.assertEqual(code, 1, summary)
        self.assertEqual(report["logits"]["nonfinite_rows"], 1)
        self.assertFalse(report["passed"]["logits"])

    def test_an_mtp_check_that_cannot_run(self):
        plain = self.d / "plain.json"
        plain.write_text(json.dumps({"args": ["--native", "@bundle/m.gguf", "--max-context", "131072"],
                                     "env": {"FAKE_PROFILE_ENV": "yes"}, "tokenizer": "unused"}))
        code, summary, report = self.run_compare(profile=plain, name="default")
        self.assertEqual(code, 0, summary)
        self.assertEqual(summary["skipped"], ["mtp"])
        self.assertIn("no --mtp", report["skipped"]["mtp"])
        self.assertNotIn("mtp", report)
        code, summary, report = self.run_compare("--checks", "logits,mtp", profile=plain, name="named")
        self.assertEqual(code, 2)
        self.assertIn("mtp check cannot run", summary["error"])
        self.assertIsNone(report)
        code, summary, _ = self.run_compare("--checks", "mtp", "--mtp-check", "0", name="zero")
        self.assertEqual(code, 2)
        self.assertIn("--mtp-check 0", summary["error"])

    def test_an_empty_checks_list_is_a_usage_error(self):
        base = ["--ref", self.engine, "--cand", self.engine, "--ids", str(self.d / "prompt.ids"),
                "--out", str(self.d / "empty")]
        self.assertEqual(qc.parse_args(base).check_list, ["logits", "mtp", "serve"])
        for value in ("", ","):
            with self.assertRaises(SystemExit) as cm:
                qc.parse_args(base + ["--checks", value])
            self.assertEqual(cm.exception.code, 2)
        self.assertEqual(qc.parse_args(base + ["--checks", "logits,,,"]).check_list, ["logits"])
        with self.assertRaises(SystemExit) as cm:
            qc.parse_args(base + ["--checks", "logits,bogus"])
        self.assertEqual(cm.exception.code, 2)

    def test_a_dead_engine_gives_an_engine_error_and_closes_cleanly(self):
        env = dict(os.environ, FAKE_PROFILE_ENV="yes")
        eng = qc.Served([sys.executable, str(self.d / "engine.py")], ["--native", "m.gguf", "--max-context", "64"],
                        env, self.d / "serve.log", 30)
        eng.p.kill()
        eng.p.wait()
        with self.assertRaises(qc.EngineError):
            eng.generate([5, 9, 11], 3)
        unraisable, hook = [], sys.unraisablehook
        sys.unraisablehook = unraisable.append
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                eng.close()
                del eng
                gc.collect()
        finally:
            sys.unraisablehook = hook
        self.assertEqual([str(w.message) for w in caught if issubclass(w.category, ResourceWarning)], [])
        self.assertEqual(unraisable, [])


if __name__ == "__main__":
    unittest.main()
