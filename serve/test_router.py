"""Router integration checks with real HTTP and isolated mock workers, no GPU."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from serve.router import ROOT, Router, handler, read_registry
import sys


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        for name in ('alpha', 'beta'):
            (root/(name+'.json')).write_text(json.dumps({'exe': 'dummy', 'args': ['--max-context', '262144' if name == 'alpha' else '131072'],
                'tokenizer': str(root/'missing'), 'model_name': name,
                'router': {'max_output_tokens': 4 if name == 'alpha' else 8},
                'sampling': {'temperature': .25 if name == 'alpha' else .5}}))
        self.registry = root/'router.json'
        self.registry.write_text(json.dumps({'default': 'alpha', 'profiles':
             {name: name+'.json' for name in ('alpha', 'beta')}}))
        profiles, default = read_registry(self.registry)
        self.router = Router(profiles, default, contained=False, startup_timeout=10, memory_floor=.001)
        def worker(config, port):
            return [sys.executable, str(ROOT/'serve/server.py'), '--engine', 'mock',
                    '--config', str(config), '--port', str(port), '--script', 'Hello.']
        self.patch = patch('serve.router.worker_command', worker)
        self.patch.start()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.router, 'test-key'))
        self.server.allowed_hosts = {'127.0.0.1', 'localhost'}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.router.close()
        self.patch.stop()
        self.tmp.cleanup()

    def request(self, path, body=None, headers=None, auth=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=15)
        h = {'Authorization': 'Bearer test-key'} if auth else {}
        h.update(headers or {})
        connection.request('POST' if body is not None else 'GET', path,
                           json.dumps(body) if body is not None else None, h)
        response = connection.getresponse()
        status, data, response_headers = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return status, data, response_headers

    def test_physical_vram_guard_stops_worker(self):
        with patch('serve.router.physical_vram_free_mib', return_value=128), patch.object(self.router, '_stop') as stop:
            self.router.vram_floor = 512
            self.router.process = object()
            try:
                deadline = time.monotonic() + 2
                while not stop.called and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(stop.called)
                self.assertIn('physical GPU VRAM', self.router.error)
            finally:
                self.router.process = None
                self.router.vram_floor = 0

    def test_memory_limit_validation(self):
        config = Path(self.tmp.name)/'alpha.json'
        cfg = json.loads(config.read_text())
        for invalid in (True, 0, 513, '24', 24.5):
            cfg['router']['memory_max_gib'] = invalid
            config.write_text(json.dumps(cfg))
            with self.assertRaisesRegex(ValueError, 'memory_max_gib'):
                read_registry(self.registry)
        cfg['router']['memory_max_gib'] = 24
        config.write_text(json.dumps(cfg))
        profiles, _ = read_registry(self.registry)
        self.assertEqual(profiles['alpha'][1]['router']['memory_max_gib'], 24)

    def test_discovery_switch_stream_and_unload(self):
        code, data, _ = self.request('/v1/models')
        self.assertEqual(code, 200)
        self.assertEqual([m['id'] for m in json.loads(data)['data']], ['alpha', 'beta'])
        models = json.loads(data)['data']
        self.assertEqual(models[0]['context_length'], 262144)
        self.assertEqual(models[1]['meta']['n_ctx'], 131072)
        self.assertEqual(models[0]['max_output_tokens'], 4)
        self.assertFalse(models[0]['capabilities']['vision'])
        self.assertNotIn('exe', models[0])
        self.assertIsNone(self.router.active)
        req = {'model': 'alpha', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 8}
        code, data, _ = self.request('/v1/chat/completions', req)
        self.assertEqual(code, 200, data)
        self.assertEqual(json.loads(data)['model'], 'alpha')
        first = self.router.process
        self.assertEqual(self.request('/health')[0], 200)
        self.assertEqual(json.loads(self.request('/health')[1])['model'], 'alpha')
        req.update(model='beta', stream=True)
        code, data, _ = self.request('/v1/chat/completions', req)
        self.assertEqual(code, 200, data)
        self.assertIn(b'[DONE]', data)
        self.assertIsNotNone(first.poll())
        self.assertEqual(self.router.active, 'beta')

        self.assertEqual(self.request('/chat/')[0], 200)
        code, script, _ = self.request('/chat/web/app.js')
        self.assertEqual(code, 200)
        self.assertIn(b'"temperature": 0.5', script)
        self.assertIn(b'sampling:beta', script)
        self.assertEqual(json.loads(self.request('/chat/health')[1])['model'], 'beta')
        self.assertEqual(self.request('/router/unload', {})[0], 200)
        self.assertIsNone(self.router.active)
        self.assertEqual(self.request('/router/load', {'model': 'alpha'})[0], 200)
        self.assertEqual(self.router.active, 'alpha')

    def test_vision_bundle_paths_are_resolved_without_mutating_profile(self):
        _, cfg = self.router.profiles['alpha']
        cfg['vision'] = {'exe': '@bundle/vision-cpu', 'model': 'local.gguf', 'mmproj': 'projector.gguf'}
        seen = {}
        def worker(config, port):
            runtime = json.loads(config.read_text())
            seen.update(runtime['vision'])
            runtime.pop('vision')  # mock worker does not launch a real image encoder
            config.write_text(json.dumps(runtime))
            return [sys.executable, str(ROOT/'serve/server.py'), '--engine', 'mock',
                    '--config', str(config), '--port', str(port), '--script', 'Hello.']
        with patch('serve.router.worker_command', worker):
            self.router.switch('alpha')
        self.assertEqual(seen['exe'], str(ROOT/'engines/vision-cpu'))
        self.assertEqual(seen['model'], str(Path(self.tmp.name)/'local.gguf'))
        self.assertEqual(cfg['vision']['exe'], '@bundle/vision-cpu')

    def test_auth_origin_host_and_unknown_profile(self):
        self.assertEqual(self.request('/router/status', auth=False)[0], 401)
        self.assertEqual(self.request('/router/load', {'model': 'alpha'},
                                     {'Origin': 'https://foreign.invalid'})[0], 403)
        self.assertEqual(self.request('/router/status', headers={'Host': 'evil.invalid'})[0], 403)
        self.assertEqual(self.request('/v1/chat/completions', {'model': 'absent'})[0], 404)
        self.assertIsNone(self.router.active)
        code, _, headers = self.request('/router/session', {})
        self.assertEqual(code, 200)
        cookie = headers['Set-Cookie'].split(';')[0]
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertEqual(self.request('/router/status', headers={'Cookie': cookie}, auth=False)[0], 200)

    def test_token_count_loads_requested_model(self):
        code, data, _ = self.request('/v1/messages/count_tokens', {
            'model': 'beta', 'messages': [{'role': 'user', 'content': 'Count me'}]})
        self.assertEqual(code, 200, data)
        self.assertIn('input_tokens', json.loads(data))
        self.assertEqual(self.router.active, 'beta')

    def test_busy_model_is_not_replaced_and_status_remains_available(self):
        self.router.switch('alpha')
        first = self.router.process
        complete = threading.Event()
        self.router.turn.acquire()
        try:
            thread = threading.Thread(target=lambda: (self.router.switch('beta'), complete.set()))
            thread.start()
            self.assertFalse(complete.wait(.2))
            self.assertIsNone(first.poll())
            self.assertEqual(self.request('/router/status')[0], 200)
        finally:
            self.router.turn.release()
        self.assertTrue(complete.wait(10))
        thread.join()
        self.assertIsNotNone(first.poll())

    def test_failure_is_reported_and_next_model_can_load(self):
        with patch('serve.router.worker_command', return_value=[sys.executable, '-c', 'raise SystemExit(3)']):
            code, _, _ = self.request('/router/load', {'model': 'alpha'})
        self.assertEqual(code, 503)
        self.assertIsNone(self.router.active)
        self.assertTrue(self.router.error)
        self.assertEqual(self.request('/router/load', {'model': 'beta'})[0], 200)
        self.assertIsNone(self.router.error)

    def test_output_cap_is_enforced(self):
        code, data, _ = self.request('/v1/chat/completions', {'model': 'alpha',
            'messages': [{'role': 'user', 'content': 'Hello'}], 'max_tokens': 100})
        self.assertEqual(code, 200, data)
        self.assertLessEqual(json.loads(data)['usage']['completion_tokens'], 4)

    def test_queue_backpressure_keeps_discovery_available(self):
        for _ in range(8):
            self.router.requests.acquire()
        try:
            self.assertEqual(self.request('/router/unload', {})[0], 429)
            self.assertEqual(self.request('/v1/models')[0], 200)
        finally:
            for _ in range(8):
                self.router.requests.release()

    def test_disabled_model_is_listed_but_cannot_replace_active_model(self):
        self.router.switch('alpha')
        first = self.router.process
        self.router.profiles['beta'][1]['router'].update(enabled=False, disabled_reason='Unsupported expert format')
        data = json.loads(self.request('/v1/models')[1])['data'][1]
        self.assertFalse(data['available'])
        self.assertEqual(data['status']['value'], 'unavailable')
        self.assertEqual(self.request('/router/load', {'model': 'beta'})[0], 400)
        self.assertEqual(self.router.active, 'alpha')
        self.assertIsNone(first.poll())

    def test_registry_rejects_bad_default(self):
        self.registry.write_text(json.dumps({'default': 'wrong', 'profiles': {'alpha': 'alpha.json'}}))
        with self.assertRaisesRegex(ValueError, 'default'):
            read_registry(self.registry)


if __name__ == '__main__':
    unittest.main()
