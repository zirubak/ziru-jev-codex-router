"""Terra visual modeling uses the typed decision and preserves caller controls."""
import json
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import jev_server as jev
import test_per_call_routing as fixtures

Edge, message, payload_for = fixtures.Edge, fixtures.message, fixtures.payload_for


class TerraRouting(unittest.TestCase):
    setUp = fixtures.PerCallEndToEnd.setUp
    tearDown = fixtures.PerCallEndToEnd.tearDown
    call = fixtures.PerCallEndToEnd.call

    def test_health_and_smoke_share_the_current_policy_identity(self) -> None:
        from routing_policy import POLICY_VERSION
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.server.server_port}/health",
        ) as response:
            health = json.load(response)
        self.assertEqual(health["policy_version"], POLICY_VERSION)
        self.assertEqual(jev.POLICY_VERSION, POLICY_VERSION)

    def test_terra_visual_modeling_preserves_replay_and_manual_effort(self) -> None:
        requests: list[dict] = []

        class Judge(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                raw = json.dumps({'answers': {
                    'astra_policy': {'choice': 'normal'},
                    'model': {'choice': 'terra_61'},
                    'effort': {'choice': 'high'},
                    'lease': {'choice': 'one_call'},
                }}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        judge = ThreadingHTTPServer(('127.0.0.1', 0), Judge)
        threading.Thread(target=judge.serve_forever, daemon=True).start()
        self.addCleanup(judge.server_close)
        self.addCleanup(judge.shutdown)
        history = [message('user', 'Use this technical drawing to model the part in SolidCraft; inspect the Blender reference.')]
        with mock.patch.object(jev, 'API', f'http://127.0.0.1:{judge.server_port}/v1/systemone'):
            for mode, effort in (('auto', 'high'), ('manual', 'xhigh')):
                with self.subTest(mode=mode):
                    body = payload_for(history, model=mode, reasoning={'effort': 'xhigh'})
                    status, _ = self.call(body)
                    self.assertEqual(status, 200)
                    self.assertEqual(Edge.payloads[-1]['model'], 'gpt-6.1-terra')
                    self.assertEqual(Edge.payloads[-1]['reasoning']['effort'], effort)
                    self.assertEqual(Edge.payloads[-1]['input'], history)
                    self.assertEqual(Edge.payloads[-1]['instructions'], body['instructions'])
                    self.assertEqual(self.records[-1]['model'], 'gpt-6.1-terra')
        criteria = requests[0]['questions']['model']['criteria']
        self.assertIn('Blender/CAD', criteria['terra_61'])
        self.assertIn('Prefer', criteria['terra_61'])
        studies = requests[0]['state']['routing_reference']['studies']
        self.assertTrue(any(study['id'] == 'terra_61_visual' for study in studies))

    def test_terra_choice_cannot_bypass_mandatory_astra_review(self) -> None:
        synthetic = {'answers': {
            'astra_policy': {'choice': 'astra'}, 'model': {'choice': 'terra_61'},
            'effort': {'choice': 'high'}, 'lease': {'choice': 'one_call'},
        }}
        with mock.patch.object(jev, 'call_jev_routed', return_value=synthetic):
            status, _ = self.call(payload_for([message('user', 'Perform final risk review of the CAD plugin permissions.')]))
        self.assertEqual(status, 200)
        self.assertEqual(Edge.payloads[-1]['model'], jev.ASTRA)
        self.assertEqual(self.records[-1]['base_tier'], 'gpt-6.1-terra')
