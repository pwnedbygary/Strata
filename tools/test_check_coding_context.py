#!/usr/bin/env python3
"""tools/check_coding_context.py on saved answers: 13 of 13 for working code, and 0 of 13 with the reason, not a
crash, for an answer whose code the checks cannot run."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

TOOL = Path(__file__).resolve().parent / "check_coding_context.py"
sys.path.insert(0, str(TOOL.parent))
import check_coding_context as ccc  # noqa: E402

WORKING = r'''The three functions:

```python
def normalize_path(path):
    parts = []
    for part in path.replace('\\', '/').split('/'):
        if part == '..':
            raise ValueError('parent directory')
        if part and part != '.':
            parts.append(part)
    return '/'.join(parts)


def retry_delay(attempt, base, cap):
    if attempt < 0 or base < 0 or cap < 0:
        raise ValueError('negative value')
    return min(cap, base * 2 ** attempt)


def next_head(head, direction, width, height):
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError('bad board size')
    return ((head[0] + direction[0]) % width, (head[1] + direction[1]) % height)
```
'''


class CheckCodingContextTest(unittest.TestCase):
    def run_tool(self, answer_text):
        with tempfile.TemporaryDirectory() as d:
            answer, out = Path(d) / "fresh.md", Path(d) / "code-check.json"
            answer.write_text(answer_text)
            p = subprocess.run([sys.executable, str(TOOL), str(answer), "--output", str(out)], capture_output=True,
                               text=True, timeout=60)
            report = json.loads(out.read_text()) if out.exists() else None
        return p, report

    def test_working_code_passes_every_check(self):
        p, report = self.run_tool(WORKING)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), "13/13 checks passed")
        self.assertEqual((report["passed"], report["total"], len(report["cases"])), (13, 13, 13))
        self.assertNotIn("error", report)

    def assert_fails_all(self, answer_text, error):
        p, report = self.run_tool(answer_text)
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("Traceback", p.stderr)
        self.assertEqual(p.stdout.strip(), "0/13 checks passed (%s)" % error)
        self.assertEqual(report, {"passed": 0, "total": 13, "error": error, "cases": []})

    def test_answer_without_code_fails_every_check(self):
        self.assert_fails_all("# CHECKPOINT_EARLY: 09ed1747\n# CHECKPOINT_LATE: 5d7f2ce5\n",
                              "ValueError: No Python code block")

    def test_code_that_does_not_parse_fails_every_check(self):
        p, report = self.run_tool("```python\ndef normalize_path(path:\n    return path\n```\n")
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("Traceback", p.stderr)
        self.assertTrue(p.stdout.startswith("0/13 checks passed (SyntaxError: "), p.stdout)
        self.assertTrue(report["error"].startswith("SyntaxError: "), report)
        self.assertEqual((report["passed"], report["total"], report["cases"]), (0, 13, []))

    def test_code_breaking_the_rules_fails_every_check(self):
        self.assert_fails_all("```python\ndef normalize_path(path):\n    import os\n    return path\n```\n",
                              "ValueError: Imports are not allowed")
        self.assert_fails_all("```python\n@staticmethod\ndef normalize_path(path):\n    return path\n```\n",
                              "ValueError: Only undecorated function definitions are allowed")
        self.assert_fails_all("```python\ndef normalize_path(path):\n    return path.upper()\n```\n",
                              "ValueError: Unexpected attribute: upper")
        self.assert_fails_all("```python\ndef normalize_path(path):\n    print(path)\n    return path\n```\n",
                              "ValueError: Unexpected function call: print")

    def test_typeerror_is_an_allowed_name(self):
        namespace = ccc.load_answer("```python\ndef normalize_path(path):\n    raise TypeError('x')\n```\n")
        self.assertIn("normalize_path", namespace)
        self.assertIs(namespace["__builtins__"]["TypeError"], TypeError)

    def test_a_read_error_is_not_an_answer_verdict(self):
        with tempfile.TemporaryDirectory() as d:
            answer, out = Path(d) / "fresh.md", Path(d) / "code-check.json"
            answer.write_bytes(b"\xff\xfe\x00bad")
            p = subprocess.run([sys.executable, str(TOOL), str(answer), "--output", str(out)], capture_output=True,
                               text=True, timeout=60)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("UnicodeDecodeError", p.stderr)
            self.assertNotIn("checks passed", p.stdout)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
