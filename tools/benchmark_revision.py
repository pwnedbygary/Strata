#!/usr/bin/env python3
"""Save an auditable source -> independent review -> model revision experiment."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.practical_checks import python_checks, svg_checks


def apply_edits(source, payload):
    """Apply only uniquely anchored literal edits; never overwrite the input file."""
    if not isinstance(payload, dict) or set(payload) != {'edits'}:
        raise ValueError('expected an object containing only edits')
    edits = payload['edits']
    if not isinstance(edits, list) or not 1 <= len(edits) <= 30:
        raise ValueError('expected 1 to 30 edits')
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {'old', 'new'}:
            raise ValueError('each edit must contain only old and new')
        old, new = edit['old'], edit['new']
        if not isinstance(old, str) or not isinstance(new, str) or not old or old == new:
            raise ValueError('expected a nonempty old string and a changed replacement')
        if source.count(old) != 1:
            raise ValueError('edit anchor must match exactly once')
        source = source.replace(old, new, 1)
    return source


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--review', type=Path, required=True)
    p.add_argument('--requirements', type=Path, required=True)
    p.add_argument('--case', choices=['snake', 'merge_intervals', 'lighthouse_svg'], required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--url', default='http://127.0.0.1:8096')
    p.add_argument('--max-tokens', type=int, default=16384)
    p.add_argument('--seed', type=int, default=20261013)
    p.add_argument('--edit-json', action='store_true', help='request small uniquely anchored edits instead of a full rewrite')
    args = p.parse_args()
    if args.max_tokens < 1:
        p.error('--max-tokens must be positive')
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        p.error('output directory must be empty')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source, review, requirements = (path.read_text() for path in
                                   (args.source, args.review, args.requirements))
    prompt = ('Revise your previously generated code using this independent review. '
              'Check each finding against the source, fix applicable issues, and preserve '
              'the original requirements and working behavior. Return only the complete '
              'revised source, without Markdown fences, explanations or example invocations.\n\n'
              'ORIGINAL REQUIREMENTS:\n' + requirements + '\n\nINDEPENDENT REVIEW:\n' + review +
              '\n\nORIGINAL SOURCE:\n' + source)
    if args.edit_json:
        prompt = ('Apply this independent review with a minimal patch, preserving all existing working behavior. '
                  'Return ONLY a valid JSON object {"edits":[{"old":"exact original text","new":"replacement text"}]}. '
                  'Each old string must match exactly once in the source. Use literal text, not regex or line numbers. '
                  'Do not return the whole file, explanations or Markdown fences. Check integrations, not just syntax.\n\n'
                  'ORIGINAL REQUIREMENTS:\n' + requirements + '\n\nINDEPENDENT REVIEW:\n' + review +
                  '\n\nORIGINAL SOURCE:\n' + source)
    for name, value in [('original'+args.source.suffix, source), ('review.md', review),
                        ('requirements.txt', requirements), ('prompt.txt', prompt)]:
        (args.output_dir / name).write_text(value)
    headers = {'Content-Type': 'application/json'}
    if os.environ.get('STRATA_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['STRATA_API_KEY']
    def request(route, body=None):
        req = urllib.request.Request(args.url.rstrip('/') + route, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req, timeout=1800) as response:
            return json.load(response)
    status = request('/v1/status')
    settings = request('/metrics').get('engine')
    print('Requesting revision from', status.get('model'), flush=True)
    start = time.monotonic()
    result = request('/v1/chat/completions', {'model': 'strata', 'temperature': 0, 'top_p': 1,
             'seed': args.seed, 'presence_penalty': 0, 'frequency_penalty': 0,
             'reasoning_effort': 'none', 'max_tokens': args.max_tokens,
             'messages': [{'role': 'user', 'content': prompt}]})
    elapsed = time.monotonic() - start
    choice = result['choices'][0]
    (args.output_dir / 'response.json').write_text(json.dumps(result, indent=2)+'\n')
    raw = choice['message'].get('content') or ''
    code = raw.strip()
    if code.startswith('```') and code.endswith('```'):
        code = code.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    if args.edit_json:
        edits = json.loads(code)
        (args.output_dir / 'edits.json').write_text(json.dumps(edits, indent=2)+'\n')
        code = apply_edits(source, edits)
    artifact = args.output_dir / ('revised' + args.source.suffix)
    artifact.write_text(code + '\n')
    checks = python_checks(artifact) if args.case == 'merge_intervals' else (
             svg_checks(code) if args.case == 'lighthouse_svg' else {})
    browser = {'status': 'not_run'}
    if args.case != 'merge_intervals':
        try:
            process = subprocess.run(['node', str(ROOT / 'tools/benchmark_browser.mjs'),
                        args.case, str(artifact.resolve())], cwd=ROOT, capture_output=True, text=True, timeout=30)
            browser = json.loads(process.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            browser = {'status': 'error', 'message': str(error)[:300]}
    report = {'model': status.get('model'), 'engine': status.get('engine'), 'engine_settings': settings,
              'case': args.case, 'edit_json': args.edit_json, 'seed': args.seed, 'temperature': 0, 'max_tokens': args.max_tokens,
              'wall_seconds': elapsed, 'finish_reason': choice.get('finish_reason'),
              'usage': result.get('usage'), 'timings': result.get('timings'),
              'checks': checks, 'browser': browser, 'independent_review': 'pending',
              'sha256': {name: hashlib.sha256(value.encode()).hexdigest()
                         for name, value in [('original', source), ('review', review),
                                             ('requirements', requirements), ('prompt', prompt), ('revised', code)]}}
    (args.output_dir / 'response.json').write_text(json.dumps(result, indent=2)+'\n')
    (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
