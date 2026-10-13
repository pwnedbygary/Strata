"""Objective checks for practical benchmark artifacts; no model judging model output."""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def svg_checks(source: str) -> dict:
    if '<!DOCTYPE' in source.upper() or '<!ENTITY' in source.upper():
        return {'valid_svg': False, 'error': 'DTD/entity declarations are not allowed'}
    try:
        root = ET.fromstring(source)
    except ET.ParseError as error:
        return {'valid_svg': False, 'error': str(error)}
    elements = list(root.iter())
    local = lambda node: node.tag.rsplit('}', 1)[-1]
    ids = {node.get('id') for node in elements if node.get('id')}
    groups = {node.get('id') for node in elements if local(node) == 'g'}
    palette = {'#0B1220', '#F8C46C', '#D7E3FC', 'NONE'}
    colors = [value.upper() for node in elements for key, value in node.attrib.items()
              if key in ('fill', 'stroke', 'stop-color') and not value.startswith('url(#')]
    safe = not any(local(node) in {'script', 'image', 'foreignObject', 'style', 'animate', 'set'}
                   or any(key.lower().startswith('on') or
                          (key.rsplit('}', 1)[-1] == 'href' and not value.startswith('#'))
                          for key, value in node.attrib.items()) for node in elements)
    references = root.get('aria-labelledby', '').split()
    return {'valid_svg': root.tag == '{http://www.w3.org/2000/svg}svg',
            'viewbox': root.get('viewBox') == '0 0 512 512',
            'editable_layers': {'sky', 'sea', 'lighthouse', 'beam'} <= groups,
            'palette': bool(colors) and set(colors) <= palette,
            'vector_only': safe,
            'shape_count': sum(local(node) in {'path', 'rect', 'circle', 'ellipse', 'polygon', 'polyline', 'line'}
                               for node in elements) >= 8,
            'accessible': root.get('role') == 'img' and len(references) >= 2 and
                          set(references) <= ids and
                          all(any(local(node) == tag and (node.text or '').strip() for node in elements)
                              for tag in ('title', 'desc'))}


def python_checks(path: Path) -> dict:
    # The worker permits only functions with restricted AST/builtins, then runs
    # fixed tests under CPU/address-space limits. It never executes an arbitrary program.
    try:
        result = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()), str(path.resolve())],
                                capture_output=True, text=True, timeout=5)
        if result.returncode:
            return {'restricted_function_check': False, 'error': 'checker failed or exceeded its resource limit'}
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        return {'restricted_function_check': False, 'error': 'checker timed out or returned invalid output'}


def _python_worker(path: Path) -> dict:
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 2**20, 256 * 2**20))
    source = path.read_text()
    if len(source) > 100000:
        raise ValueError('source is too large')
    tree = ast.parse(source)
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    import builtins
    names = ('len sorted min max sum enumerate range abs bool int float str list tuple dict set '
             'isinstance all any zip reversed ValueError TypeError').split()
    allowed = {name: getattr(builtins, name) for name in names}
    methods = {'append', 'extend', 'copy', 'sort', 'pop', 'insert', 'get', 'items', 'values', 'keys'}
    forbidden = (ast.Import, ast.ImportFrom, ast.ClassDef, ast.Global, ast.Nonlocal,
                 ast.With, ast.AsyncWith, ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom)
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) and not (
                isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            raise ValueError('only functions and docstrings are allowed at module level')
    for node in ast.walk(tree):
        if isinstance(node, forbidden) or isinstance(node, ast.Name) and node.id.startswith('__'):
            raise ValueError('unsupported syntax or name')
        if isinstance(node, ast.FunctionDef) and node.decorator_list:
            raise ValueError('decorators are not supported')
        if isinstance(node, ast.Attribute) and node.attr not in methods:
            raise ValueError('unsupported attribute')
        if isinstance(node, ast.Call) and not (
                isinstance(node.func, ast.Name) and node.func.id in set(names) | functions or
                isinstance(node.func, ast.Attribute) and node.func.attr in methods):
            raise ValueError('unsupported call')
    namespace = {'__builtins__': allowed}
    exec(compile(tree, str(path), 'exec'), namespace)
    merge = namespace['merge_intervals']
    import copy
    cases = {'empty': ([], []),
             'touching': ([[1, 3], [2, 6], [8, 10], [10, 18]], [[1, 6], [8, 18]]),
             'unsorted': ([[8, 10], [1, 3], [2, 6], [15, 18]], [[1, 6], [8, 10], [15, 18]]),
             'negative': ([[-10, -4], [-5, 2], [3, 4]], [[-10, 2], [3, 4]]),
             'duplicate': ([[1, 1], [1, 1]], [[1, 1]]),
             'nested': ([[0, 9], [2, 4], [3, 8]], [[0, 9]])}
    checks = {}
    unchanged = True
    for name, (given, expected) in cases.items():
        original = copy.deepcopy(given)
        try:
            checks[name] = merge(given) == expected
        except Exception:
            checks[name] = False
        unchanged = unchanged and given == original
    checks['input_unchanged'] = unchanged
    for name, value in {'reversed_rejected': [[3, 1]], 'boolean_rejected': [[True, 3]],
                        'float_rejected': [[1.5, 3]], 'malformed_rejected': [[1, 2, 3]]}.items():
        try:
            merge(value)
            checks[name] = False
        except ValueError:
            checks[name] = True
        except Exception:
            checks[name] = False
    return checks


if __name__ == '__main__':
    try:
        print(json.dumps(_python_worker(Path(sys.argv[1]))))
    except Exception as error:
        print(json.dumps({'restricted_function_check': False, 'error': str(error)[:300]}))
