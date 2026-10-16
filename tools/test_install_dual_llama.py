"""Installer regression: preserve presets, old executable and relative library symlinks."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC=importlib.util.spec_from_file_location('install_dual_llama',Path(__file__).with_name('install_dual_llama.py'))
MODULE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

class InstallerTests(unittest.TestCase):
    def test_preserves_user_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);build=base/'build/bin';build.mkdir(parents=True)
            (build/'llama').write_text('#!/bin/sh\necho dual\n');(build/'llama').chmod(0o755)
            (build/'libggml.so.1').write_bytes(b'library');(build/'libggml.so').symlink_to('libggml.so.1')
            executable=base/'llama';executable.write_bytes(b'original executable')
            presets=base/'presets.ini';presets.write_bytes(b'[model]\nctx-size=131072\n')
            argv=['install','--build-dir',str(base/'build'),'--prefix',str(base/'dual runtime'),'--executable',str(executable),'--presets',str(presets)]
            with mock.patch('sys.argv',argv):MODULE.main()
            self.assertEqual(presets.read_bytes(),b'[model]\nctx-size=131072\n')
            self.assertEqual(executable.with_name('llama.vulkan-backup').read_bytes(),b'original executable')
            self.assertTrue((base/'dual runtime/bin/libggml.so').is_symlink())
            self.assertIn('Vulkan0',executable.read_text())
            self.assertIn('"$@"',executable.read_text())
            with mock.patch('sys.argv',argv),self.assertRaises(SystemExit):MODULE.main()
            self.assertEqual(executable.with_name('llama.vulkan-backup').read_bytes(),b'original executable')
if __name__=='__main__':unittest.main()
