#!/usr/bin/env python3
"""Hardware validation of opt-in dense MTP cache growth and eviction (not full-window quality)."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.strata_tokenizer import Tokenizer


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--engine', type=Path, default=ROOT/'build-hip/strata')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    tk = Tokenizer.from_gguf(a.model)
    prefix = tk.encode('<|im_start|>user\nWrite a Python function square(n) returning n*n. Ignore the filler:')
    tail = tk.encode('\nReturn code only.<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n')
    filler = tk.encode(' alpha')
    assert len(filler) == 1
    ids = prefix + filler*(4086-len(prefix)-len(tail)) + tail
    env = dict(os.environ)
    env.update(STRATA_Q35_DENSE='1', STRATA_Q35_NATIVE_LOWBIT='1', STRATA_Q35_KV_I8='1',
               STRATA_Q35_ATTN_SCORE_MIB='128', GPU_PINNED_MIN_XFER_SIZE='1000000')
    env['STRATA_HIPBLASLT_TUNING'] = str(ROOT/'tools/hip/gfx1201-hipblaslt-100202.txt')
    env['LD_LIBRARY_PATH'] = '/opt/rocm/lib:' + env.get('LD_LIBRARY_PATH', '')
    base = [str(a.engine.resolve()), '--native', str(a.model.resolve()), '--prefill', '512',
            '--mtp', '1', '--tokens', ','.join(map(str, ids)), '--n', '64']
    def run(name, context, adaptive=False, cycle=False):
        settings = dict(env)
        settings.pop('STRATA_Q35_ADAPTIVE_WEIGHTS', None)
        settings.pop('STRATA_Q35_ADAPTIVE_MTP', None)
        if adaptive:
            settings.update(STRATA_Q35_ADAPTIVE_WEIGHTS='1', STRATA_Q35_ADAPTIVE_MTP='1')
        cmd = base + ['--max-context', str(context)] + (['--test-dense-cache-cycle'] if cycle else [])
        print(name, flush=True)
        result = subprocess.run(cmd, env=settings, capture_output=True, text=True)
        (a.output/(name+'.log')).write_text(result.stdout+result.stderr)
        if result.returncode:
            raise RuntimeError(name+' failed: '+result.stderr[-1500:])
        match = re.search(r'^gen:(.*)$', result.stdout, re.M)
        if not match:
            raise RuntimeError('No generated tokens')
        generation = list(map(int, match.group(1).split()))
        accepted = re.search(r'MTP 1 drafts: (\d+) of (\d+) accepted', result.stderr)
        return {'tokens':generation, 'accepted':int(accepted[1]), 'offered':int(accepted[2])}
    reference = run('fixed-16k', 16384)
    adaptive = run('adaptive-growth-16k', 16384, True)
    cycle = run('adaptive-cycle-256k', 262144, True, True)
    report = {'prompt_tokens':len(ids),'output_tokens':len(reference['tokens']),
              'growth_tokens_identical':reference['tokens']==adaptive['tokens'],
              'growth_drafts_identical':(reference['accepted'],reference['offered'])==(adaptive['accepted'],adaptive['offered']),
              'cycle_tokens_identical':reference['tokens']==cycle['tokens'],
              'cycle_drafts_identical':(reference['accepted'],reference['offered'])==(cycle['accepted'],cycle['offered']),
              'runs':{'fixed':reference,'growth':adaptive,'cycle':cycle},
              'scope':'internal storage/speculation comparison, not external reference parity or a filled 256K prompt'}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)
    if not all(report[key] for key in ('growth_tokens_identical','growth_drafts_identical','cycle_tokens_identical','cycle_drafts_identical')):
        raise SystemExit('Storage/speculation comparison failed')


if __name__ == '__main__':
    main()
