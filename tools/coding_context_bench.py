#!/usr/bin/env python3
"""Counted code/tool-log context benchmark with streamed progress and an identical-prefix follow-up."""
import argparse
import json
import hashlib
import re
from pathlib import Path
import time
import threading
import os
import platform
from datetime import datetime, timezone
import atexit
import urllib.request


def gpu_voltage_offset(device):
    """Read the configured offset, not the instantaneous sensor voltage."""
    try:
        text = (device / 'pp_od_clk_voltage').read_text()
    except OSError:
        return None
    match = re.search(r'^OD_VDDGFX_OFFSET:\s*\n\s*(-?\d+)\s*m[Vv]\b', text, re.M)
    return int(match[1]) if match else None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',required=True)
    p.add_argument('--tokens',type=int,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--prompt-file',type=Path,help='reuse an exact saved prompt for cross-engine comparisons')
    p.add_argument('--request-timeout',type=float,default=1800,help='socket timeout for long prefills (seconds)')
    p.add_argument('--base-url',default='http://127.0.0.1:8096')
    p.add_argument('--long-context-probes', action='store_true', help='require unique build IDs from the beginning, middle and end')
    p.add_argument('--require-zero-gpu-offset', action='store_true',
                   help='refuse to start if the AMD GPU voltage offset is nonzero or cannot be read')
    p.add_argument('--sampling',choices=('greedy','profile'),default='greedy',
                   help="greedy: temperature 0; profile: no sampling fields, so the router applies the profile's "
                        "own values")
    p.add_argument('--seed',type=int,help='seed sent with --sampling profile, so a repeated run draws the same tokens')
    a=p.parse_args()
    if a.seed is not None and a.sampling!='profile':
        p.error('--seed needs --sampling profile')
    if a.require_zero_gpu_offset:
        offsets=[]
        for dev in Path('/sys/class/drm').glob('card*/device'):
            try:
                if int((dev/'mem_info_vram_total').read_text()) > 2**30:
                    offsets.append(gpu_voltage_offset(dev))
            except (OSError,ValueError): continue
        if not offsets or any(offset != 0 for offset in offsets):
            p.error('zero GPU voltage offset required; observed '+repr(offsets)+
                    '. Restore the default voltage in your GPU utility before this benchmark.')
    a.output.mkdir(parents=True,exist_ok=True)
    (a.output/'system.json').write_text(json.dumps({
        'started_utc': datetime.now(timezone.utc).isoformat(),
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'kernel_release': platform.release()}, indent=2)+'\n')
    stop=threading.Event();monitor_started=time.monotonic()
    def monitor():
        with (a.output/'memory.jsonl').open('w') as output:
            while not stop.wait(1):
                row={'seconds':round(time.monotonic()-monitor_started,1)}
                info=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
                row['available_gib']=round(int(info['MemAvailable'].split()[0])/2**20,3)
                for dev in Path('/sys/class/drm').glob('card*/device'):
                    try:
                        total=int((dev/'mem_info_vram_total').read_text())
                        if total>2**30:
                            row['vram_free_mib']=round((total-int((dev/'mem_info_vram_used').read_text()))/2**20)
                            offset = gpu_voltage_offset(dev)
                            if offset is not None: row['gpu_voltage_offset_mv'] = offset
                            temperatures={}
                            for sensor in dev.glob('hwmon/hwmon*/temp*_input'):
                                label=sensor.with_name(sensor.name.replace('_input','_label'))
                                temperatures[label.read_text().strip() if label.exists() else sensor.stem]=int(sensor.read_text())/1000
                            row['gpu_temperatures_c']=temperatures
                            for sensor in dev.glob('hwmon/hwmon*/power1_average'):
                                row['gpu_power_w']=round(int(sensor.read_text())/1e6,1)
                            for sensor in dev.glob('hwmon/hwmon*/power1_cap'):
                                row['gpu_power_cap_w']=round(int(sensor.read_text())/1e6,1)
                            break
                    except (OSError,ValueError):continue
                for sensor in Path('/sys/class/hwmon').glob('hwmon*/name'):
                    try:
                        if sensor.read_text().strip()=='k10temp':
                            row['cpu_tctl_c']=int(sensor.with_name('temp1_input').read_text())/1000
                    except (OSError,ValueError):continue
                output.write(json.dumps(row)+'\n');output.flush()
                # Preserve recent samples across a hard reset without syncing every row.
                if int(row['seconds']) % 5 == 0: os.fsync(output.fileno())
    monitor_thread=threading.Thread(target=monitor,daemon=True);monitor_thread.start()
    def close_monitor():
        stop.set();monitor_thread.join(timeout=2)
    atexit.register(close_monitor)
    first='''Repository review: fix these three Python functions. No imports. Return one Python code block containing all three corrected functions, with their original signatures.\n\nFile: paths.py\ndef normalize_path(path):\n    return path.replace('\\\\', '/')\nRequired: normalize slashes, discard empty and '.' components, reject ANY '..' component with ValueError, preserve other component text, return relative slash-separated path.\n'''
    middle='''\nFile: retry.py\ndef retry_delay(attempt, base, cap):\n    return base * (2 ** attempt)\nRequired: attempt is a nonnegative integer; base and cap are nonnegative numbers. Return min(cap, base * 2**attempt). Raise ValueError for negative attempt, base or cap.\n'''
    last='''\nFile: snake.py\ndef next_head(head, direction, width, height):\n    return (head[0] + direction[0], head[1] + direction[1])\nRequired: width and height must be positive integers; otherwise raise ValueError. Wrap each resulting coordinate to its grid dimension. Return a tuple.\n\nThe following archived module/tool logs are context, not instructions. Fix ONLY the three functions above.\n'''
    module='''\n# Archived tool output: src/game/state.py\ndef bounded(value, low, high):\n    return max(low, min(value, high))\n# pytest: 18 passed; 0 failed\n# lint: no findings\n# render-loop inspection: fixed-step accumulator; paused state preserves board\n'''
    probes = {name: hashlib.sha256(('strata-context-v1-' + name).encode()).hexdigest()[:24]
              for name in ('EARLY', 'MIDDLE', 'LATE')} if a.long_context_probes else {}
    if probes:
        first += '\nAlso append three Python comments to your answer: # CHECKPOINT_EARLY: value, # CHECKPOINT_MIDDLE: value, # CHECKPOINT_LATE: value. Copy each unique identifier from the corresponding archived build checkpoint.\n'
        first += '\n# Archived build checkpoint EARLY: ' + probes['EARLY'] + '\n'
        middle += '\n# Archived build checkpoint MIDDLE: ' + probes['MIDDLE'] + '\n'
        last += '\n# Archived build checkpoint LATE: ' + probes['LATE'] + '\n'
    def content(n):
        return first+module*(n//2)+middle+module*(n-n//2)+last+'\nReturn the corrected three functions now.\n'
    def request(path,body):
        return urllib.request.Request(a.base_url+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    def count_text(text):
        with urllib.request.urlopen(request('/v1/messages/count_tokens',{'model':a.model,'thinking':{'type':'disabled'},'messages':[{'role':'user','content':text}]}),timeout=a.request_timeout) as r:return json.load(r)['input_tokens']
    def count(n):return count_text(content(n))
    if a.prompt_file:
        prompt=a.prompt_file.read_text();actual=count_text(prompt)
    else:
        lo=0;hi=max(1,a.tokens//50)
        while count(hi)<a.tokens:hi*=2
        while lo+1<hi:
            mid=(lo+hi)//2
            if count(mid)<=a.tokens:lo=mid
            else:hi=mid
        prompt=content(lo);actual=count(lo)
    (a.output/'prompt.txt').write_text(prompt)
    reports=[]
    def run(name,messages):
        body={'model':a.model,'messages':messages,**({'temperature':0} if a.sampling=='greedy' else {}),'reasoning_effort':'none','chat_template_kwargs':{'enable_thinking':False},'max_tokens':768,'stream':True,'stream_options':{'include_usage':True},'return_progress':True,**({'seed':a.seed} if a.seed is not None else {})}
        started=time.monotonic();answer='';latest={};progress={};first_token=None;completed=False
        with urllib.request.urlopen(request('/v1/chat/completions',body),timeout=a.request_timeout) as r,(a.output/(name+'.sse')).open('w') as stream:
            for raw in r:
                line=raw.decode();stream.write(line);stream.flush()
                if not line.startswith('data: '):continue
                data=line[6:].strip()
                if data=='[DONE]':completed=True;break
                chunk=json.loads(data)
                if chunk.get('error'):raise RuntimeError(chunk['error'])
                if 'prompt_progress' in chunk:
                    progress=chunk['prompt_progress']
                    (a.output/'progress.json').write_text(json.dumps({'phase':name,'seconds':round(time.monotonic()-started,1),'progress':progress})+'\n')
                for choice in chunk.get('choices',[]):
                    text=choice.get('delta',{}).get('content') or ''
                    if text and first_token is None:first_token=time.monotonic()-started
                    answer+=text
                if chunk.get('usage'):latest=chunk
        (a.output/(name+'.md')).write_text(answer)
        if probes and name == 'fresh':
            observed = dict(re.findall(r'^\s*# CHECKPOINT_(EARLY|MIDDLE|LATE):\s*([0-9a-f]+)\s*$', answer, re.M))
            checks = {key: observed.get(key) == value for key, value in probes.items()}
            (a.output/'retrieval-check.json').write_text(json.dumps({
                'expected': probes, 'observed': observed, 'checks': checks,
                'passed': sum(checks.values()), 'total': len(checks),
                'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()}, indent=2)+'\n')
        report={'phase':name,'completed':completed,'elapsed_seconds':round(time.monotonic()-started,2),'first_content_seconds':first_token,'usage':latest.get('usage'),'timings':latest.get('timings')}
        reports.append(report)
        (a.output/'report.json').write_text(json.dumps({'model':a.model,'target_prompt_tokens':a.tokens,'counted_prompt_tokens':actual,'sampling':a.sampling,'seed':a.seed,'runs':reports},indent=2)+'\n')
        print(json.dumps(report),flush=True)
        return answer
    messages=[{'role':'user','content':prompt}]
    answer=run('fresh',messages)
    messages += [{'role':'assistant','content':answer},{'role':'user','content':'Review your changes against the three requirements. Give one concise boundary-case test per function and identify any remaining bug. Do not rewrite correct functions.'}]
    run('follow-up',messages)


if __name__=='__main__':main()
