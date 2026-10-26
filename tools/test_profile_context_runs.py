#!/usr/bin/env python3
"""tools/profile_context_runs.py without a GPU or a model: whole runs against a fake router that counts tokens,
streams an answer echoing the prompt's retrieval checkpoints, and describes the picture."""
from pathlib import Path
import http.server
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_context_runs as pcr  # noqa: E402

FAKE_ROUTER = textwrap.dedent(r'''
    import json, os, re, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    args = sys.argv[1:]
    registry = json.load(open(args[args.index("--registry") + 1]))
    port = int(args[args.index("--port") + 1])
    CODE = """```python
    def normalize_path(path):
        parts = []
        for part in path.replace('\\\\', '/').split('/'):
            if part == '..':
                raise ValueError('parent component')
            if part and part != '.':
                parts.append(part)
        return '/'.join(parts)

    def retry_delay(attempt, base, cap):
        if attempt < 0 or base < 0 or cap < 0:
            raise ValueError('negative')
        return min(cap, base * 2 ** attempt)

    def next_head(head, direction, width, height):
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            raise ValueError('size')
        return ((head[0] + direction[0]) % width, (head[1] + direction[1]) % height)
    ```
    """
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def reply(self, obj, status=200):
            data = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            if self.path == "/health":
                self.reply({"ok": True})
            elif self.path == "/router/status":
                self.reply({"profile": {"inference": {"engine": "strata", "device": "hip", "build": "native"}}})
            else:
                self.reply({"error": "no"}, 404)
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if os.environ.get("FAKE_ROUTER_LOG") and self.path == "/v1/chat/completions":
                with open(os.environ["FAKE_ROUTER_LOG"], "a") as f:
                    f.write(json.dumps({k: v for k, v in body.items() if k != "messages"}) + "\n")
            if body.get("model") not in registry["profiles"]:
                return self.reply({"error": "unknown model"}, 404)
            content = body["messages"][0]["content"]
            if self.path == "/v1/messages/count_tokens":
                return self.reply({"input_tokens": len(content) // 4})
            if isinstance(content, list):
                return self.reply({"choices": [{"message": {"content": "Circle - Red\nSquare - Blue\nTriangle - Green"}}]})
            if len(body["messages"]) > 1:
                answer = "Each function now rejects its bad inputs."
            else:
                probes = re.findall(r"# Archived build checkpoint (EARLY|MIDDLE|LATE): ([0-9a-f]+)", content)
                answer = CODE + "".join("# CHECKPOINT_%s: %s\n" % p for p in probes)
            n = len(content) // 4 if isinstance(content, str) else 0
            timings = {"prompt_n": n, "cache_n": 0, "prompt_ms": 2000.0, "prompt_per_second": n / 2.0,
                       "predicted_n": 120, "predicted_ms": 3000.0, "predicted_per_second": 40.0,
                       "draft_n": 90, "draft_n_accepted": 80}
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for chunk in ({"choices": [{"delta": {"content": answer}}]},
                          {"choices": [], "usage": {"prompt_tokens": n, "completion_tokens": 120}, "timings": timings}):
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
''')


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Runs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "router.py").write_text(FAKE_ROUTER)
        reg = self.d / "reg"
        (reg / "profiles").mkdir(parents=True)
        (reg / "profiles" / "pic.json").write_text(json.dumps({"args": ["--native", "x.gguf", "--max-context", "6144",
                                                                        "--vision"]}))
        (reg / "profiles" / "plain.json").write_text(json.dumps({"args": ["--native", "y.gguf", "--max-context", "5120"]}))
        (reg / "profiles" / "noctx.json").write_text(json.dumps({"args": ["--native", "z.gguf"]}))
        (reg / "router.json").write_text(json.dumps({"default": "pic", "profiles": {
            "pic": "profiles/pic.json", "plain": str(reg / "profiles" / "plain.json"), "noctx": "profiles/noctx.json"}}))
        (reg / "native-tuning-router.json").write_text('{"pic":{"engine_policy":"auto"}}')
        self.reg = reg

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args, out="out"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = pcr.main(["--out", str(self.d / out), "--registry", str(self.reg / "router.json"),
                             "--app", "%s %s" % (sys.executable, self.d / "router.py"), "--port", str(free_port()),
                             "--settle-max", "0", "--sample-every", "0.2", *args])
        return code, buf.getvalue()

    def test_two_profiles_to_the_end(self):
        code, text = self.run_tool("pic", "plain")
        out = self.d / "out"
        self.assertEqual(code, 0, text)
        copy = json.loads((out / "router.json").read_text())
        self.assertEqual(copy["profiles"]["pic"], str(self.reg / "profiles" / "pic.json"))
        self.assertEqual((out / "native-tuning-router.json").read_text(), '{"pic":{"engine_policy":"auto"}}')
        rec = json.loads((out / "pic" / "run.json").read_text())
        self.assertEqual((rec["context"], rec["prompt_target"], rec["bench_exit"]), (6144, 4096, 0))
        self.assertEqual(json.loads((out / "pic" / "retrieval-check.json").read_text())["passed"], 3)
        self.assertEqual(json.loads((out / "pic" / "code-check.json").read_text())["passed"], 13)
        self.assertTrue(json.loads((out / "pic" / "picture.json").read_text())["pass"])
        self.assertFalse((out / "plain" / "picture.json").exists())
        rows = [line for line in (out / "table.md").read_text().splitlines() if line.startswith("| p")]
        self.assertEqual([r.split(" | ")[0] for r in rows], ["| pic", "| plain"])
        cells = [c.strip() for c in rows[0].strip("|").split("|")]
        self.assertEqual(cells[1], "strata")
        self.assertEqual(cells[5], "80/90")
        self.assertEqual(cells[7:10], ["3/3", "13/13", "pass"])
        self.assertLessEqual(int(cells[2]), 4096)
        self.assertGreater(len((out / "load.log").read_text().splitlines()), 1)
        self.assertIn(str(self.reg / "profiles" / "plain.json"), (out / "inputs.sha256").read_text())
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(pcr.main(["--table", str(out)]), 0)
        self.assertEqual(buf.getvalue().strip(), (out / "table.md").read_text().strip())

    def test_tokens_override_deadline_and_bad_input(self):
        code, _ = self.run_tool("--tokens", "1000", "plain", out="tokens")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads((self.d / "tokens" / "plain" / "run.json").read_text())["prompt_target"], 1000)
        code, _ = self.run_tool("--deadline", "2020-01-01 00:00", "plain", out="late")
        self.assertEqual(code, 1)
        self.assertIn("not started: past the deadline", (self.d / "late" / "progress.txt").read_text())
        code, _ = self.run_tool("noctx", out="noctx")
        self.assertEqual(code, 1)
        self.assertEqual(self.run_tool("--deadline", "23:30", "plain", out="bare")[0], 2)
        self.assertEqual(self.run_tool("missing", out="missing")[0], 2)

    def test_sampled_and_greedy_requests(self):
        log = self.d / "requests.jsonl"
        with mock.patch.dict(os.environ, {"FAKE_ROUTER_LOG": str(log)}):
            self.assertEqual(self.run_tool("--tokens", "1000", "pic", out="sampled")[0], 0)
            sampled = [json.loads(line) for line in log.read_text().splitlines()]
            log.unlink()
            self.assertEqual(self.run_tool("--tokens", "1000", "--greedy", "plain", out="greedy")[0], 0)
            greedy = [json.loads(line) for line in log.read_text().splitlines()]
        bench = [r for r in sampled if r["max_tokens"] == 768]
        self.assertEqual(len(bench), 2)
        self.assertTrue(all("temperature" not in r and r["seed"] == 20261026 for r in bench))
        picture = [r for r in sampled if r["max_tokens"] != 768]
        self.assertEqual([(r["temperature"], "seed" in r) for r in picture], [(0, False)])
        self.assertEqual([(r["temperature"], "seed" in r) for r in greedy], [(0, False), (0, False)])
        rec = json.loads((self.d / "sampled" / "pic" / "run.json").read_text())
        self.assertEqual((rec["sampling"], rec["seed"]), ("profile", 20261026))
        report = json.loads((self.d / "sampled" / "pic" / "report.json").read_text())
        self.assertEqual((report["sampling"], report["seed"]), ("profile", 20261026))
        self.assertTrue((self.d / "sampled" / "table.md").read_text().startswith(
            "Requests: each profile's own sampling, seed 20261026."))
        self.assertTrue((self.d / "greedy" / "table.md").read_text().startswith("Requests: greedy (temperature 0)."))
        script = Path(pcr.__file__).parent / "coding_context_bench.py"
        bad = subprocess.run([sys.executable, str(script), "--model", "m", "--tokens", "10", "--output",
                              str(self.d / "bad"), "--seed", "1"], capture_output=True, text=True, timeout=60)
        self.assertEqual(bad.returncode, 2)
        self.assertIn("--seed needs --sampling profile", bad.stderr)

    def test_picture_pass_rule(self):
        self.assertTrue(pcr.picture_pass(200, "A red Circle, a blue square and a GREEN triangle."))
        self.assertFalse(pcr.picture_pass(200, "A red circle and a blue square."))
        self.assertFalse(pcr.picture_pass(500, "red circle blue square green triangle"))


class LocalCalls(unittest.TestCase):
    def test_router_calls_and_the_bench_bypass_proxies(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        dead_proxy = {"http_proxy": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "no_proxy": ""}
        try:
            with mock.patch.dict(os.environ, dead_proxy):
                self.assertEqual(pcr.get_json("http://127.0.0.1:%d/router/status" % srv.server_port), {"ok": True})
                self.assertFalse({"http_proxy", "HTTPS_PROXY"} & set(pcr.without_proxies(os.environ)))
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
