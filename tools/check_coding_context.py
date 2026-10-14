#!/usr/bin/env python3
"""Check the saved coding-context answer in a bounded subprocess (Linux hardware profile)."""
import argparse
import ast
import json
from pathlib import Path
import re
import subprocess
import sys


def check(path):
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_AS, (256 << 20, 256 << 20))
    match = re.search(r'```(?:python)?\n(.*?)```', path.read_text(), re.S)
    if not match:
        raise ValueError('No Python code block')
    tree = ast.parse(match.group(1))
    if not all(isinstance(node, ast.FunctionDef) and not node.decorator_list for node in tree.body):
        raise ValueError('Only undecorated function definitions are allowed')
    builtins = {'ValueError': ValueError, 'min': min, 'max': max, 'int': int, 'isinstance': isinstance}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError('Imports are not allowed')
        if isinstance(node, ast.Attribute) and node.attr not in {'replace', 'split', 'join', 'append'}:
            raise ValueError('Unexpected attribute: '+node.attr)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id not in builtins:
            raise ValueError('Unexpected function call: '+node.func.id)
    namespace = {'__builtins__': builtins}
    exec(compile(tree, 'saved benchmark answer', 'exec'), namespace)
    cases = [('normalize_path', ('a'+chr(92)+'b',), 'a/b'),
             ('normalize_path', ('a'+chr(92)*2+'b',), 'a/b'),
             ('normalize_path', ('/a//./b',), 'a/b'),
             ('normalize_path', ('a/../b',), ValueError), ('normalize_path', ('',), ''),
             ('retry_delay', (3,2,10), 10), ('retry_delay', (-1,2,10), ValueError),
             ('retry_delay', (0,-1,10), ValueError), ('retry_delay', (0,1,-1), ValueError),
             ('next_head', ((0,0),(-1,0),10,4), (9,0)),
             ('next_head', ((0,0),(1,1),1,1), (0,0)),
             ('next_head', ((0,0),(1,0),0,4), ValueError),
             ('next_head', ((0,0),(1,0),2.5,4), ValueError)]
    results = []
    for name, args, expected in cases:
        try:
            value = namespace[name](*args)
            passed, actual = value == expected, repr(value)
        except Exception as exc:
            passed, actual = expected is ValueError and isinstance(exc, ValueError), type(exc).__name__
        results.append({'function':name, 'args':repr(args), 'expected':repr(expected), 'actual':actual, 'passed':passed})
    return {'passed':sum(row['passed'] for row in results), 'total':len(results), 'cases':results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('answer', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(check(args.answer)))
        return
    result = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()), str(args.answer.resolve()), '--worker'],
                            capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise SystemExit(result.stderr or 'Answer checker failed')
    report = json.loads(result.stdout)
    text = json.dumps(report, indent=2)+'\n'
    if args.output:
        args.output.write_text(text)
    print(f'{report["passed"]}/{report["total"]} checks passed')
    if report['passed'] != report['total']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
