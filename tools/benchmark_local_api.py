#!/usr/bin/env python3
"""Measure an already-running local Strata server; never starts another engine."""
import argparse
import json
import statistics
import time
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8096')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--prompt-file', type=Path, help='UTF-8 prompt to measure longer prefills')
    parser.add_argument('--max-tokens', type=int, default=128)
    parser.add_argument('--temperature', type=float, default=0,
                        help='0 for repeatable comparisons; try 0.7 for sampled writing')
    parser.add_argument('--timeout', type=float, default=300,
                        help='Request timeout in seconds; allow more time for large prefills')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    if args.max_tokens < 1:
        parser.error('--max-tokens must be positive')
    prompt = (args.prompt_file.read_text() if args.prompt_file else
              'Write a Python function that merges two sorted lists. Explain its complexity.')
    rows = []
    for i in range(args.repeats):
        payload = {'model': 'strata', 'temperature': args.temperature, 'max_tokens': args.max_tokens,
                   'reasoning_effort': 'none', 'messages': [{'role': 'user',
                   'content': f'Trial {i}: {prompt}'}]}
        request = urllib.request.Request(args.url.rstrip('/') + '/v1/chat/completions',
                    data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            result = json.load(response)
        rows.append({'wall_seconds': time.monotonic() - started,
                     'timings': result.get('timings'), 'usage': result.get('usage'),
                     'choices': result.get('choices')})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'url': args.url,
                     'temperature': args.temperature, 'max_tokens': args.max_tokens,
                     'prompt_file': str(args.prompt_file) if args.prompt_file else None,
                     'trials': rows}, indent=2) + '\n')
        print(json.dumps({k: v for k, v in rows[-1].items() if k != 'choices'}), flush=True)
    print('Median wall seconds:', statistics.median(r['wall_seconds'] for r in rows))


if __name__ == '__main__':
    main()
