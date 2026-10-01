"""Synthetic host failures exercise durable recovery; no real agents are spawned."""
import copy
import json
import subprocess
import sys
import time
import unittest
import test_long_running_subagents as base
from long_running_controller import ContractError, Controller


class SpawnRecoveryTests(unittest.TestCase):
    setUp = base.SubagentModeTests.setUp
    tearDown = base.SubagentModeTests.tearDown
    start = base.SubagentModeTests.start
    update = base.SubagentModeTests.update
    result = base.SubagentModeTests.result
    finish_review = base.SubagentModeTests.finish_review
    dispatch_worker = base.SubagentModeTests.dispatch_worker

    def rejection(self, reservation, error='agent thread limit reached.', absent=True):
        return dict(attempt_id=reservation['attempt_id'], error=error,
                    source_ref='host-call-' + reservation['attempt_id'], no_agent_created=absent)

    def observation(self, available=True, matches=None):
        stamp = time.time()
        return {'host': {'observed_at': stamp, 'source_ref': f'host-list-{stamp}',
                        'close_supported': False, 'agents': []},
                'matching_agent_ids': matches or [], 'capacity_available': available,
                'capacity_evidence_ref': f'capacity-{stamp}'}

    def rejected(self, token, observation=None):
        reservation = self.controller.spawn_attempt(token, observation)
        result = self.rejection(reservation)
        self.assertEqual(self.controller.spawn_result(token, result)['outcome'], 'thread_limit')
        return reservation, result

    def test_reservation_survives_restart_and_never_duplicates_on_retry(self):
        request = self.start(); token = request['token']
        first = self.controller.spawn_attempt(token)
        self.controller = Controller(self.root/'state')
        retry = self.controller.spawn_attempt(token)
        self.assertEqual(first['status'], 'SPAWN_RESERVED')
        self.assertEqual(retry['status'], 'RECOVER_SPAWN')
        self.assertEqual(retry['attempt']['attempt_id'], first['attempt_id'])
        self.assertEqual(self.controller.next()['request'], request)

    def test_rejection_preserves_pending_claims_and_all_work_budgets(self):
        token = self.dispatch_worker()['token']
        before = self.controller.status()
        self.rejected(token)
        after = self.controller.status()
        for key in ('pending', 'actions', 'working_claims', 'claim_dirty', 'review_due',
                    'dispatches', 'attempts', 'review_failures', 'receipts', 'complete'):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(self.controller.spawn_attempt(token)['status'], 'WAITING_FOR_CAPACITY')
        self.assertEqual(self.controller.spawn_attempt(token, self.observation(False))['status'], 'WAITING_FOR_CAPACITY')
        self.assertEqual(len(self.controller.status()['spawn_attempts'][token]), 1)

    def test_fresh_capacity_allows_same_token_then_bind_and_finish(self):
        token = self.dispatch_worker()['token']
        self.rejected(token)
        retry = self.controller.spawn_attempt(token, self.observation())
        self.assertEqual(retry['attempts_used'], 2)
        self.controller.bind_agent(token, 'actual-fixture-host-id')
        self.assertEqual(self.controller.spawn_attempt(token)['status'], 'RECOVER_BOUND_AGENT')
        self.controller.finish(token, {'status': 'done', 'evidence_refs': ['evidence.txt']})
        self.assertTrue(self.controller.status()['claim_dirty'])
        self.assertEqual(self.controller.next()['request']['role'], 'claims_reviewer')

    def test_three_attempt_budget_persists_across_restart(self):
        token = self.start()['token']
        self.rejected(token)
        for number in (2, 3):
            self.controller = Controller(self.root/'state')
            attempt, _ = self.rejected(token, self.observation())
            self.assertEqual(attempt['attempts_used'], number)
        self.controller = Controller(self.root/'state')
        self.assertEqual(self.controller.spawn_attempt(token, self.observation())['status'], 'SPAWN_BUDGET_EXHAUSTED')
        self.assertEqual(self.controller.next()['status'], 'IN_FLIGHT')

    def test_explicit_budget_and_invalid_values(self):
        for value in (True, 0, 101, 1.5, '3'):
            with self.subTest(value=value), self.assertRaises(ContractError):
                self.controller.init(dict(self.config, max_spawn_attempts=value))
        self.config['max_spawn_attempts'] = 1
        token = self.start()['token']; self.rejected(token)
        self.assertEqual(self.controller.spawn_attempt(token)['status'], 'SPAWN_BUDGET_EXHAUSTED')

    def test_unknown_or_ambiguous_errors_never_retry(self):
        token = self.start()['token']
        attempt = self.controller.spawn_attempt(token)
        result = self.rejection(attempt, 'connection lost', False)
        self.assertEqual(self.controller.spawn_result(token, result)['outcome'], 'uncertain')
        self.assertEqual(self.controller.spawn_attempt(token, self.observation())['status'], 'RECOVER_SPAWN')
        self.controller.bind_agent(token, 'recovered-existing-agent')
        self.assertEqual(self.controller.spawn_attempt(token)['status'], 'RECOVER_BOUND_AGENT')

    def test_exact_error_without_no_creation_evidence_is_uncertain(self):
        token = self.start()['token']; attempt = self.controller.spawn_attempt(token)
        self.assertEqual(self.controller.spawn_result(token, self.rejection(attempt, absent=False))['outcome'], 'uncertain')

    def test_error_mentioned_inside_other_text_is_not_a_known_rejection(self):
        token = self.start()['token']; attempt = self.controller.spawn_attempt(token)
        result = self.rejection(attempt, 'timeout after earlier agent thread limit reached.')
        self.assertEqual(self.controller.spawn_result(token, result)['outcome'], 'uncertain')

    def test_duplicate_result_idempotent_conflicting_result_rejected(self):
        token = self.start()['token']; _, result = self.rejected(token)
        self.assertEqual(self.controller.spawn_result(token, result)['status'], 'ALREADY_RECORDED')
        with self.assertRaises(ContractError):
            self.controller.spawn_result(token, dict(result, error='different'))

    def test_pause_stop_and_stale_prevent_new_attempts(self):
        token = self.start()['token']; attempt = self.controller.spawn_attempt(token)
        self.controller.control('paused', 'fixture pause')
        self.controller.spawn_result(token, self.rejection(attempt))
        self.assertEqual(self.controller.spawn_attempt(token, self.observation())['status'], 'PAUSED')
        self.controller.control('active', 'fixture resume')
        (self.root/'evidence.txt').write_text('changed', encoding='utf-8')
        self.assertEqual(self.controller.spawn_attempt(token, self.observation())['status'], 'STALE')
        self.controller.control('stopped', 'fixture stop')
        self.assertEqual(self.controller.spawn_attempt(token)['status'], 'STOPPED')
        self.assertEqual(len(self.controller.status()['spawn_attempts'][token]), 1)

    def test_observation_must_be_fresh_after_failure_and_not_reused(self):
        token = self.start()['token']; old = self.observation(); self.rejected(token)
        for stamp in (old['host']['observed_at'], time.time()-61, time.time()+10):
            obs = self.observation(); obs['host']['observed_at'] = stamp
            with self.assertRaises(ContractError): self.controller.spawn_attempt(token, obs)
        obs = self.observation(); self.rejected(token, obs)
        obs['host']['observed_at'] = time.time()
        with self.assertRaises(ContractError): self.controller.spawn_attempt(token, obs)

    def test_token_matching_agent_requires_recovery_even_if_capacity_available(self):
        token = self.start()['token']; self.rejected(token)
        self.assertEqual(self.controller.spawn_attempt(token, self.observation(matches=['existing']))['status'], 'RECOVER_SPAWN')
        self.assertEqual(len(self.controller.status()['spawn_attempts'][token]), 1)

    def test_wrong_token_attempt_bound_agent_and_bad_boolean_rejected(self):
        token = self.start()['token']; attempt = self.controller.spawn_attempt(token)
        with self.assertRaises(ContractError): self.controller.spawn_attempt('wrong')
        with self.assertRaises(ContractError): self.controller.spawn_result(token, dict(self.rejection(attempt), attempt_id='wrong'))
        with self.assertRaises(ContractError): self.controller.spawn_result(token, dict(self.rejection(attempt), no_agent_created='yes'))
        self.controller.bind_agent(token, 'already-created')
        with self.assertRaises(ContractError): self.controller.spawn_result(token, self.rejection(attempt))

    def test_cli_reserves_and_records_then_reports_waiting(self):
        token = self.start()['token']
        prefix = [sys.executable, '-B', str(base.SCRIPTS/'long_running_controller.py'), '--state', str(self.root/'state')]
        def run(args):
            proc = subprocess.run(prefix+args, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout)
        reservation = run(['spawn-attempt', '--token', token])
        path = self.root/'spawn-result.json'; path.write_text(json.dumps(self.rejection(reservation)), encoding='utf-8')
        self.assertEqual(run(['spawn-result', '--token', token, '--result', str(path)])['outcome'], 'thread_limit')
        self.assertEqual(run(['spawn-attempt', '--token', token])['status'], 'WAITING_FOR_CAPACITY')
