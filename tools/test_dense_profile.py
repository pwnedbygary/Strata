"""CPU-only checks for the opt-in dense 27B configuration."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import dense_profile
from tools.gguf_reader import TensorInfo
META={'general.architecture':'qwen35','qwen35.block_count':64,'qwen35.context_length':262144,
      **{'qwen35.'+k:v for k,v in {'embedding_length':5120,'feed_forward_length':17408,'attention.head_count':24,
      'attention.head_count_kv':4,'attention.key_length':256,'attention.value_length':256,'ssm.state_size':128,
      'ssm.conv_kernel':4,'ssm.group_count':16,'ssm.time_step_rank':48,'ssm.inner_size':6144,
      'full_attention_interval':4,'rope.dimension_count':64}.items()}}
BASE={'backend':'hip','args':['--pack','old'],'env':{'STRATA_ROUTE_TAIL_SKIP':'7','STRATA_Q35_REPACK_Q8':'1'},'port':8096}
class DenseProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.file=Path(self.tmp.name)/'model.gguf';self.file.write_bytes(bytes(128))
        self.gguf=SimpleNamespace(metadata=copy.deepcopy(META),data_start=64,tensors=[TensorInfo('blk.0.ssm_conv1d.weight',[4,1],0,'F32',0)])
    def prepare(self,base=BASE,context=163840,prefill=512):
        with patch.object(dense_profile,'GGUFFile',return_value=self.gguf):
            return dense_profile.prepare(base,self.file,'/tokenizer',context,prefill)
    def test_opt_in_and_original_preserved(self):
        before=copy.deepcopy(BASE);c=self.prepare()
        self.assertEqual(before,BASE);self.assertEqual(c['arch'],'qwen35')
        self.assertEqual(c['env']['STRATA_Q35_KV_I8'],'1');self.assertEqual(c['env']['STRATA_Q35_NATIVE_LOWBIT'],'1')
        self.assertNotIn('STRATA_ROUTE_TAIL_SKIP',c['env']);self.assertNotIn('STRATA_Q35_REPACK_Q8',c['env'])
        self.assertNotIn('--pack',c['args'])
        self.assertEqual(c['env']['STRATA_Q35_ADAPTIVE_WEIGHTS'],'1')
    def test_invalid_modes_and_context(self):
        for change in ({'backend':'cuda'},{'vision':{'exe':'mmproj'}},{'parallel':2},{'gpu':[0,1]}):
            with self.assertRaises(ValueError):self.prepare({**BASE,**change})
        for n in (0,4097,266240):
            with self.assertRaises(ValueError):self.prepare(context=n)
    def test_wrong_geometry_and_truncated_tensor(self):
        self.gguf.metadata['qwen35.feed_forward_length']=1
        with self.assertRaises(ValueError):self.prepare()
        self.gguf.metadata=copy.deepcopy(META);self.gguf.tensors[0].offset=128
        with self.assertRaises(ValueError):self.prepare()
    def test_native_guard_rechecks_layout(self):
        self.gguf.metadata['general.architecture']='qwen35moe'
        with self.assertRaises(ValueError):self.prepare()
if __name__=='__main__':unittest.main()
