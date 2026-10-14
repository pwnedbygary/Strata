#!/usr/bin/env python3
"""Stream a counted near-full prompt with known retrieval markers and memory telemetry."""
import argparse
import json
from pathlib import Path
import threading
import time
import urllib.request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', default='http://127.0.0.1:8096')
    p.add_argument('--model', required=True)
    p.add_argument('--tokens', type=int, default=261120)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    keys = {'ALPHA':'PINE-4837','BRAVO':'COBALT-9261','CHARLIE':'EMBER-6154'}
    def content(n):
        return ('Read the reference and remember three keyed values. Ignore filler words.\n'
                'ALPHA=PINE-4837\n' + ' alpha'*(n//2) + '\nBRAVO=COBALT-9261\n' +
                ' alpha'*(n-n//2) + '\nCHARLIE=EMBER-6154\n'
                'Return only a JSON object with the exact ALPHA, BRAVO and CHARLIE values. No explanation.')
    def request(path, body):
        return urllib.request.Request(a.base_url+path, data=json.dumps(body).encode(),
                                      headers={'Content-Type':'application/json'})
    def count(n):
        body={'model':a.model,'messages':[{'role':'user','content':content(n)}],'thinking':{'type':'disabled'}}
        with urllib.request.urlopen(request('/v1/messages/count_tokens', body), timeout=600) as r:
            return json.load(r)['input_tokens']
    n = max(0, a.tokens-count(0))
    actual = count(n)
    for _ in range(4):
        if actual == a.tokens: break
        n += a.tokens-actual
        actual = count(n)
    body={'model':a.model,'messages':[{'role':'user','content':content(n)}],
          'temperature':0,'reasoning_effort':'none','max_tokens':256,'stream':True,'return_progress':True}
    (a.output/'request-summary.json').write_text(json.dumps({'model':a.model,'counted_prompt_tokens':actual,
        'expected':keys,'max_output_tokens':256,'temperature':0,'reasoning_effort':'none'},indent=2)+'\n')
    started=time.monotonic();stop=threading.Event();samples=[];progress={};answer='';last={};done=False
    def sample():
        while not stop.wait(1):
            row={'seconds':round(time.monotonic()-started,1)}
            try:
                info=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
                row['available_gib']=round(int(info['MemAvailable'].split()[0])/2**20,3)
                for dev in Path('/sys/class/drm').glob('card*/device'):
                    total=int((dev/'mem_info_vram_total').read_text())
                    if total>2**30:
                        row['vram_free_mib']=round((total-int((dev/'mem_info_vram_used').read_text()))/2**20)
                        break
            except (OSError, ValueError):pass
            samples.append(row)
            (a.output/'progress.json').write_text(json.dumps({'seconds':row['seconds'],'prompt_progress':progress,
                'answer_chars':len(answer),'latest_memory':row})+'\n')
    thread=threading.Thread(target=sample,daemon=True);thread.start()
    print('Sending',actual,'counted input tokens to',a.model,flush=True)
    error=None
    try:
        with urllib.request.urlopen(request('/v1/chat/completions',body),timeout=600) as response, (a.output/'stream.txt').open('w') as out:
            for raw in response:
                line=raw.decode('utf-8');out.write(line);out.flush()
                if not line.startswith('data: '):continue
                data=line[6:].strip()
                if data=='[DONE]':done=True;break
                chunk=json.loads(data)
                if chunk.get('error'):error=str(chunk['error'])
                if 'prompt_progress' in chunk:progress=chunk['prompt_progress']
                for choice in chunk.get('choices',[]):answer+=choice.get('delta',{}).get('content') or ''
                if chunk.get('usage'):last=chunk
    except Exception as exc:error=str(exc)
    finally:
        stop.set();thread.join(timeout=2)
    try:recalled=json.loads(answer.strip().removeprefix('```json').removesuffix('```').strip())
    except (ValueError,TypeError):recalled=None
    report={'counted_prompt_tokens':actual,'completed':done,'error':error,'answer':answer,
            'retrieval_exact':recalled==keys,'elapsed_seconds':round(time.monotonic()-started,2),
            'usage':last.get('usage'),'timings':last.get('timings'),
            'memory_min_available_gib':min((r['available_gib'] for r in samples if 'available_gib' in r),default=None),
            'memory_min_vram_free_mib':min((r['vram_free_mib'] for r in samples if 'vram_free_mib' in r),default=None)}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (a.output/'memory.json').write_text(json.dumps(samples)+'\n')
    print(json.dumps(report),flush=True)
    if not done or error:raise SystemExit(1)
    if not report['retrieval_exact']:raise SystemExit(2)


if __name__=='__main__':main()
