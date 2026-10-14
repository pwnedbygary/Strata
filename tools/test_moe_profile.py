"""CPU-only regression checks for experimental MoE preparation."""
import copy
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import hardware_profile, moe_profile, gguf_no_mtp
from tools.gguf_reader import GGUFFile

class MoEProfileTests(unittest.TestCase):
    def test_failed_scope_only_is_reset(self):
        for state in ('active', 'inactive', 'failed'):
            with patch.object(hardware_profile.subprocess, 'run', side_effect=[SimpleNamespace(returncode=0, stdout=state), SimpleNamespace(returncode=0)]) as run:
                hardware_profile.recover_failed_scope()
                self.assertEqual(run.call_count, 2 if state == 'failed' else 1)

    def test_wrong_family_and_backend_rejected(self):
        for base, info in [({'backend':'cuda'}, {'architecture':'qwen35moe'}), ({'backend':'hip'}, {'architecture':'mixtral'})]:
            with self.assertRaises(ValueError):
                moe_profile.prepare(base, info, '/tokenizer')

    def test_metadata_copy_preserves_payload_and_refuses_overwrite(self):
        def string(value):
            data=value.encode(); return struct.pack('<Q',len(data))+data
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'source.gguf'; target=Path(d)/'target.gguf'
            header=struct.pack('<IIQQ',0x46554747,3,1,2)
            header+=string('general.architecture')+struct.pack('<I',8)+string('qwen35moe')
            header+=string('qwen35moe.block_count')+struct.pack('<II',4,40)
            header+=string('blk.0.test')+struct.pack('<IQIQ',1,1,0,0)
            header+=b'\0'*((-len(header))%32)
            payload=struct.pack('<f',1.25);source.write_bytes(header+payload)
            original=source.read_bytes()
            result=gguf_no_mtp.convert(source,target)
            self.assertTrue(result['tensor_payload_identical'])
            self.assertEqual(source.read_bytes(),original)
            g=GGUFFile(target)
            self.assertEqual(target.read_bytes()[g.data_start:],payload)
            self.assertEqual(g.metadata['qwen35moe.nextn_predict_layers'],0)
            with self.assertRaises(FileExistsError):gguf_no_mtp.convert(source,target)
            with self.assertRaises(ValueError):gguf_no_mtp.convert(target,Path(d)/'again.gguf')

if __name__=='__main__':unittest.main()
