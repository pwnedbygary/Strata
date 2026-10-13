"""Ensure model patches cannot silently apply to ambiguous or stale source."""
import unittest
from tools.benchmark_revision import apply_edits


class RevisionEdits(unittest.TestCase):
    def test_unique_literal_patch_keeps_other_code(self):
        source = 'const a = 1;\nconst b = 2;\n'
        result = apply_edits(source, {'edits':[{'old':'const a = 1;', 'new':'const a = 3;'}]})
        self.assertEqual(result, 'const a = 3;\nconst b = 2;\n')
        self.assertEqual(source, 'const a = 1;\nconst b = 2;\n')

    def test_ambiguous_missing_or_noop_edits_rejected(self):
        for source, old, new in [('x x','x','y'), ('x','z','y'), ('x','','y'), ('x','x','x')]:
            with self.subTest(source=source,old=old,new=new),self.assertRaises(ValueError):
                apply_edits(source, {'edits':[{'old':old,'new':new}]})

    def test_malformed_payloads_rejected(self):
        for payload in [None, {'edits':[]}, {'edits':[{'old':'x'}]},
                        {'edits':[{'old':'x','new':3}]}, {'edits':[],'extra':True}]:
            with self.subTest(payload=payload),self.assertRaises(ValueError):
                apply_edits('x',payload)


if __name__ == '__main__':
    unittest.main()
