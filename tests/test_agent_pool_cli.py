"""Public CLI recovery and control checks across fresh Python processes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'skills' / 'analyze-project-claims' / 'scripts' / 'long_running_controller.py'


class PoolCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.state = self.root / 'state'
        (self.root / 'protocol.txt').write_text('synthetic CLI fixture', encoding='utf-8')
        source = self.root / 'SKILL.md'
        source.write_text('Fixture only; no model invocation.', encoding='utf-8')
        self.config = {
            'goal_id': 'cli-pool', 'goal_revision': '1', 'objective': 'Test durable CLI reservations',
            'authorization_ref': 'isolated test', 'project_root': str(self.root),
            'evidence': ['protocol.txt', 'output.json'], 'success_criteria': ['output reviewed'],
            'agent_pool': {'max_workers': 2},
            'actions': [{'id': 'work', 'instruction': 'Write isolated output', 'required_claims': [],
                'premise_free_reason': 'This fixture investigates the output claim',
                'affected_claims': ['C'], 'read_paths': ['protocol.txt'], 'write_paths': ['output.json']}],
            'subagent_mode': {'authorization_ref': 'isolated delegation fixture',
                'reviewer_sources': [str(source)],
                'claims': [{'id': 'C', 'statement': 'Output verified', 'scope': 'fixture'}],
                'reports': [{'id': 'summary', 'title': 'Fixture', 'claim_ids': ['C']}]}}
        path = self.root / 'config.json'
        path.write_text(json.dumps(self.config), encoding='utf-8')
        self.call('init', '--config', str(path))

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(CLI), '--state', str(self.state), *args],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout if expected == 0 else result.stderr)

    def test_fresh_process_recovers_same_dispatch_and_pause_blocks_start(self):
        first = self.call('next', '--dispatch-id', 'initial-review')
        token = first['request']['token']
        recovered = self.call('next', '--dispatch-id', 'initial-review')
        self.assertEqual(recovered['request']['token'], token)
        self.call('next')
        self.assertEqual(self.call('status')['dispatches'], 1)
        self.call('bind-agent', '--token', token, '--agent-id', 'fixture-reviewer')
        self.assertEqual(self.call('check', '--token', token)['status'], 'READY')
        self.call('pause', '--reason', 'test explicit user pause')
        self.assertEqual(self.call('check', '--token', token)['status'], 'PAUSED')
        self.assertEqual(self.call('next', '--dispatch-id', 'initial-review')['status'], 'PAUSED')
        self.assertEqual(self.call('next', '--dispatch-id', 'another')['status'], 'PAUSED')
        self.assertEqual(self.call('status')['dispatches'], 1)

    def test_serial_runner_refuses_pool_instead_of_claiming_concurrent_execution(self):
        result = self.call('run', '--execute', expected=2)
        self.assertEqual(result['status'], 'ERROR')
        self.assertIn('adapter', result['error'])
        self.assertEqual(self.call('status')['dispatches'], 0)


if __name__ == '__main__':
    unittest.main()
