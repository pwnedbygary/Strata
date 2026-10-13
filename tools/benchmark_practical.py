#!/usr/bin/env python3
"""Run fixed artifact-building prompts against an already-running Strata server."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.practical_checks import python_checks, svg_checks

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8096')
    parser.add_argument('--cases', default='snake,merge_intervals,lighthouse_svg')
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=20261013)
    parser.add_argument('--max-tokens', type=int, help='override each selected task output limit')
    parser.add_argument('--browser-checks', action='store_true', help='run optional isolated Playwright checks')
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    if args.max_tokens is not None and args.max_tokens < 1:
        parser.error('--max-tokens must be positive')
    directory = ROOT / 'bench/practical'
    suite = json.loads((directory / 'suite.json').read_text())
    selected = args.cases.split(',')
    unknown = set(selected) - {case['id'] for case in suite['cases']}
    if unknown:
        parser.error('unknown cases: ' + ', '.join(sorted(unknown)))
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error('output directory must be empty; preserve earlier results')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    headers = {'Content-Type': 'application/json'}
    if os.environ.get('STRATA_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['STRATA_API_KEY']
    def request(path, payload=None):
        req = urllib.request.Request(args.url.rstrip('/') + path,
                    data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        with urllib.request.urlopen(req, timeout=1800) as response:
            return json.load(response)
    status = request('/v1/status')
    report = {'suite_version': suite['version'], 'seed': args.seed, 'temperature': 0,
              'model': status.get('model'), 'engine': status.get('engine'),
              'max_context': status.get('cache_max_tokens'), 'engine_settings': request('/metrics').get('engine'),
              'trials': []}
    by_id = {case['id']: case for case in suite['cases']}
    for case_id in selected:
        case = by_id[case_id]
        source = (directory / case['prompt']).read_text()
        for repeat in range(args.repeats):
            max_tokens = args.max_tokens or case['max_tokens']
            prompt = f"Practical benchmark v{suite['version']}, task {case['id']}, repeat {repeat}.\n" + source
            print(f"Generating {case['id']} ({repeat + 1}/{args.repeats}) ...", flush=True)
            started = time.monotonic()
            result = request('/v1/chat/completions', {'model': 'strata', 'temperature': 0, 'top_p': 1,
                       'seed': args.seed, 'presence_penalty': 0, 'frequency_penalty': 0,
                       'reasoning_effort': 'none', 'max_tokens': max_tokens,
                       'messages': [{'role': 'user', 'content': prompt}]})
            elapsed = time.monotonic() - started
            choice = result['choices'][0]
            raw = choice['message'].get('content') or ''
            artifact = raw.strip()
            fenced = artifact.startswith('```')
            if fenced and artifact.endswith('```'):
                artifact = artifact.split('\n', 1)[1].rsplit('```', 1)[0].strip()
            path = args.output_dir / f"{case['id']}-{repeat}.{case['extension']}"
            path.write_text(artifact + '\n')
            checks = python_checks(path) if case['extension'] == 'py' else (
                     svg_checks(artifact) if case['extension'] == 'svg' else {})
            browser = {'status': 'not_run'}
            if args.browser_checks and case['extension'] in ('html', 'svg'):
                checked = subprocess.run(['node', str(ROOT / 'tools/benchmark_browser.mjs'),
                                          case['id'], str(path.resolve())], capture_output=True, text=True, timeout=30)
                try:
                    browser = json.loads(checked.stdout)
                except ValueError:
                    browser = {'status': 'error', 'message': checked.stderr[-500:]}
            row = {'case': case['id'], 'repeat': repeat, 'max_tokens': max_tokens,
                   'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                   'artifact_sha256': hashlib.sha256(artifact.encode()).hexdigest(),
                   'artifact': path.name, 'wall_seconds': elapsed, 'finish_reason': choice.get('finish_reason'),
                   'fenced_output': fenced, 'usage': result.get('usage'), 'timings': result.get('timings'),
                   'checks': checks, 'browser': browser,
                   'manual_visual_review': 'not_done' if case['extension'] != 'py' else 'not_applicable'}
            report['trials'].append(row)
            (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps({k: row[k] for k in ('case', 'finish_reason', 'timings', 'checks', 'browser')}), flush=True)
    print('Saved artifacts and report:', args.output_dir, flush=True)


if __name__ == '__main__':
    main()
