#!/usr/bin/env python3
"""Exercise native admission/security without allocating a model or exhausting memory."""
import argparse
import fcntl
import os
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    a = p.parse_args()
    with tempfile.TemporaryDirectory(prefix='strata-admission-') as tmp:
        base = Path(tmp)
        profile = base / 'model.json'
        profile.write_text(json.dumps({'args': ['--native', '/not-a-model.gguf',
                                               '--max-context', '131072']}))
        registry = base / 'router.json'
        registry.write_text(json.dumps({'default': 'test', 'profiles': {'test': str(profile)}}))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        # A deliberately impossible admission floor tests refusal, not actual pressure.
        cmd = [str(a.binary.resolve()), '--registry', str(registry), '--port', str(port),
               '--memory-floor-gib', '1024', '--api-key', 'local-test-key']
        with (base / 'server.log').open('w') as log:
            process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, "XDG_RUNTIME_DIR": str(base)})
            def request(path, body=None, key=True, origin=None):
                headers = {'Content-Type': 'application/json'}
                if key: headers['Authorization'] = 'Bearer local-test-key'
                if origin: headers['Origin'] = origin
                req = urllib.request.Request(f'http://127.0.0.1:{port}{path}',
                    data=None if body is None else json.dumps(body).encode(), headers=headers)
                try:
                    response = urllib.request.urlopen(req, timeout=3)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    return response.code, json.load(response)
            try:
                for _ in range(100):
                    if process.poll() is not None: raise RuntimeError((base/'server.log').read_text())
                    try:
                        if request('/health')[0] == 200: break
                    except OSError: pass
                    time.sleep(.05)
                else: raise RuntimeError('Native router did not start')
                with (base / f'strata-native-model-{os.getuid()}.lock').open('w') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    assert request('/router/status')[1]['external_model_busy'] is True
                    code, result = request('/router/load', {'model': 'test'})
                    assert code == 503 and 'model lock' in result['error']['message'], result
                assert request('/router/status')[1]['external_model_busy'] is False
                assert request('/v1/models', key=False)[0] == 401
                assert request('/v1/models', origin='https://foreign.example')[0] == 403
                code, result = request('/router/tuning?model=test')
                assert code == 200 and result['values']['context'] == 131072, result
                original_profile = profile.read_bytes()
                code, result = request('/router/tuning', {'model': 'test', 'settings': {'context': 65536}})
                assert code == 200 and result['values']['context'] == 65536, result
                code, result = request('/router/tuning', {'model': 'test', 'settings': {'cpu_workers': 4}})
                assert code == 200 and result['values']['context'] == 65536, result
                assert request('/router/tuning', {'model': 'test', 'settings': {'context': 999999}})[0] == 400
                assert request('/v1/models')[1]['data'][0]['context_length'] == 65536
                code, result = request('/router/tuning', {'model': 'test', 'reset': True})
                assert code == 200 and result['values']['context'] == 131072, result
                assert profile.read_bytes() == original_profile
                code, result = request('/router/load', {'model': 'test'})
                assert code == 503 and 'Insufficient' in result['error']['message'], result
                code, result = request('/v1/chat/completions',
                    {'model': 'test', 'messages': [{'role':'user','content':'hello'}]})
                assert code == 503 and result['error']['type'] == 'resource_exhausted', result
                code, result = request('/health')
                assert code == 200 and not result['loaded'] and result['active'] is None, result
            finally:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(); raise RuntimeError('Router shutdown stalled')
    print('PASS: low-memory refusal, tuning save/merge/reset, source preservation, router survival, API key/origin checks and shutdown; no model loaded')


if __name__ == '__main__':
    main()
