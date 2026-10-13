"""Tests for the opt-in hardware profile; no GPU, downloads or systemd calls."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import hardware_profile as profile


BASE = {
    'backend': 'hip', 'exe': 'engine/strata', 'cwd': '/model-data',
    'tokenizer': '/model-data/tokenizer', 'port': 8081,
    'args': ['--pack', '/model-data/pack', '--native', '/model-data/model.gguf',
             '--expert-profile', 'data/expert-profile.bin', '--resident-experts',
             '--max-context', '65536', '--kv', 'q4_0', '--mtp', '/model-data/mtp'],
    'env': {'STRATA_HIPBLASLT_TUNING': '/tables/tuning.txt'},
    'sampling': {'temperature': 0.7}, 'api_key': 'test-key',
}


class HardwareProfile(unittest.TestCase):
    def test_repeatable_mode_is_separate_and_idempotent(self):
        normal = profile.apply(BASE)
        fixed = profile.apply(BASE, repeatable=True)
        self.assertEqual(profile.apply(fixed, repeatable=True), fixed)
        self.assertEqual(fixed['env']['STRATA_ROUTE_TAIL_SKIP'], '0')
        for flag in ('--adapt-async', '--adapt-swaps', '--pcie-frac', '--prompt-cache'):
            self.assertEqual(fixed['args'][fixed['args'].index(flag) + 1], '0')
        self.assertNotIn('STRATA_ROUTE_TAIL_SKIP', normal['env'])

    def test_opt_in_preserves_original_and_model_settings(self):
        original = copy.deepcopy(BASE)
        result = profile.apply(BASE)
        self.assertEqual(BASE, original)
        for key in ('exe', 'cwd', 'tokenizer', 'port', 'sampling', 'api_key'):
            self.assertEqual(result[key], original[key])
        for flag in ('--pack', '--native', '--mtp', '--expert-profile'):
            self.assertEqual(result['args'][result['args'].index(flag) + 1],
                             original['args'][original['args'].index(flag) + 1])
        self.assertEqual(result['env']['STRATA_HIPBLASLT_TUNING'], original['env']['STRATA_HIPBLASLT_TUNING'])
        self.assertEqual(profile.apply(result), result)

    def test_duplicate_options_do_not_override_profile(self):
        config = copy.deepcopy(BASE)
        config['args'] += ['--kv', 'fp16', '--resident-budget-gib', '24', '--pcie-frac', '0']
        result = profile.apply(config)
        for flag, value in profile.OPTIONS.items():
            self.assertEqual(result['args'].count(flag), 1)
            self.assertEqual(result['args'][result['args'].index(flag) + 1], value)
        self.assertNotIn('--pcie-frac', result['args'])
        self.assertNotIn('--resident-experts', result['args'])

    def test_unsupported_modes_rejected_before_writing(self):
        variants = [{'backend': 'cuda'}, {'parallel': 2}, {'gpu': '0,1'},
                    {'gpu': [0, 1]}, {'vision': {'exe': 'encoder'}}, {'replicas': 2}]
        for change in variants:
            with self.subTest(change=change), self.assertRaises(ValueError):
                profile.apply({**BASE, **change})
        with self.assertRaises(ValueError):
            profile.apply({**BASE, 'args': BASE['args'] + ['--layer-split', '24']})

    def test_malformed_option_rejected(self):
        with self.assertRaisesRegex(ValueError, 'has no value'):
            profile.apply({**BASE, 'args': BASE['args'] + ['--kv']})

    def test_output_does_not_replace_original_or_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'base.json'
            target = Path(directory) / 'tuned.json'
            source.write_text(json.dumps(BASE))
            before = source.read_bytes()
            result = profile.apply(BASE)
            profile.write(result, source, target, False)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(json.loads(target.read_text()), result)
            with self.assertRaises(FileExistsError):
                profile.write(result, source, target, False)
            with self.assertRaises(ValueError):
                profile.write(result, source, source, True)
            if os.name == 'posix':
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_launcher_bounds_whole_process_tree_and_honors_port(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / '.venv/bin/python'
            python.parent.mkdir(parents=True)
            python.touch()
            with mock.patch.object(profile, 'ROOT', root), mock.patch.object(profile.sys, 'platform', 'linux'):
                cmd = profile.command(profile.apply(BASE), root / 'tuned.json')
            self.assertIn('MemoryMax=20G', cmd)
            self.assertIn('MemorySwapMax=0', cmd)
            self.assertIn('--unit=strata-local', cmd)
            self.assertEqual(cmd[cmd.index('--port') + 1], '8081')
            self.assertEqual(cmd[cmd.index('--host') + 1], '127.0.0.1')

    def test_launcher_rejects_public_host_without_key(self):
        config = profile.apply(BASE)
        config.update(host='0.0.0.0', api_key='')
        with mock.patch.object(profile.sys, 'platform', 'linux'), mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'API key'):
                profile.command(config, Path('config.json'))


if __name__ == '__main__':
    unittest.main()
