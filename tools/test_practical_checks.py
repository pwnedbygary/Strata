"""Check benchmark validators with good and deliberately invalid artifacts."""
import tempfile
import unittest
from pathlib import Path
from tools.practical_checks import python_checks, svg_checks


class Checks(unittest.TestCase):
    def check_python(self, source):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'answer.py'
            path.write_text(source)
            return python_checks(path)

    def test_correct_function(self):
        result = self.check_python('''def merge_intervals(intervals):
    for pair in intervals:
        if len(pair) != 2 or any(type(x) != int for x in pair) or pair[0] > pair[1]:
            raise ValueError()
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out
'''.replace('type(x) != int', 'not isinstance(x, int) or isinstance(x, bool)'))
        self.assertEqual(len(result), 11)
        self.assertTrue(all(result.values()), result)

    def test_bad_function(self):
        self.assertFalse(self.check_python('def merge_intervals(x):\n    return x\n')['touching'])

    def test_program_and_import_rejected(self):
        for source in ('import os', 'print("hello")', 'def merge_intervals(x):\n    return x.__class__\n'):
            self.assertFalse(self.check_python(source)['restricted_function_check'])

    def test_invalid_svg(self):
        self.assertFalse(svg_checks('<svg>')['valid_svg'])
        self.assertFalse(svg_checks('<!DOCTYPE svg><svg/>')['valid_svg'])


if __name__ == '__main__':
    unittest.main()
