"""Behavioral contracts for opt-in durable concurrency; no native/model claims."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills' / 'analyze-project-claims' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from long_running_controller import Controller, ContractError


class AgentPoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'protocol.txt').write_text('bounded fixture protocol')
        (self.root / 'SKILL.md').write_text('Synthetic reviewer contract; no real model invocation.')
        self.config = {
            'goal_id': 'pool-contract', 'goal_revision': '1', 'objective': 'Checked independent outputs',
            'authorization_ref': 'local fixture', 'project_root': str(self.root),
            'success_criteria': ['all outputs reviewed'], 'max_dispatches': 40,
            'evidence': ['protocol.txt', 'a.txt', 'b.txt', 'c.txt'],
            'agent_pool': {'max_workers': 2},
            'actions': [self.action(k) for k in ('a', 'b', 'c')],
            'subagent_mode': {'authorization_ref': 'local fixture',
                'reviewer_sources': [str(self.root / 'SKILL.md')],
                'claims': [{'id': k, 'statement': 'Fixture ' + k + ' is present', 'scope': k} for k in ('P', 'a', 'b', 'c')],
                'reports': [{'id': 'summary', 'title': 'Fixture', 'claim_ids': ['P', 'a', 'b', 'c']}]}}
        self.controller = Controller(self.root / 'state')
        self.counter = 0

    def tearDown(self):
        self.tmp.cleanup()

    def action(self, key):
        return {'id': key, 'instruction': 'Produce ' + key, 'required_claims': ['P'],
                'affected_claims': [key], 'read_paths': ['protocol.txt'], 'write_paths': [key + '.txt']}

    def next(self, intent=None):
        self.counter += 1
        return self.controller.next(dispatch_id=intent or 'intent-' + str(self.counter))

    def review_result(self, request, **overrides):
        updates = []
        statuses = {k: v['status'] for k, v in request['working_claims'].items()}
        for key in request['required_claim_updates']:
            path = 'protocol.txt' if key == 'P' else key + '.txt'
            sha = request['snapshot']['files'].get(path)
            supported = sha is not None
            update = {'id': key, 'status': 'supported' if supported else 'untested',
                      'evidence': ([{'path': path, 'locator': 'line:1', 'sha256': sha,
                          'method': 'source_inspection', 'relation': 'supports'}] if supported else []),
                      'limitations': [] if supported else ['Fixture output not produced'],
                      'rationale': 'Inspected exact fixture source', 'audit_refs': []}
            updates.append(update)
            statuses[key] = update['status']
        cleared = [a['id'] for a in request['config']['actions']
                   if a['id'] in request.get('clearable_actions', request['actions']) and request['actions'][a['id']] == 'pending'
                   and all(statuses[c] == 'supported' for c in a['required_claims'])]
        result = {'review_status': 'COMPLETE', 'decision': 'CONTINUE',
                  'snapshot_digest': request['snapshot']['digest'], 'request_digest': request['semantic_digest'],
                  'coverage': 'Exact fixture claims; synthetic reviewer, no native invocation',
                  'cleared_actions': cleared, 'next_action': cleared[0] if cleared else None,
                  'skill_invocation': {'skill': 'analyze-project-claims', 'contract_digest': request['reviewer_contract']['digest']},
                  'claim_updates': updates}
        result.update(overrides)
        return result

    def finish_review(self, request, **overrides):
        self.controller.bind_agent(request['token'], 'fixture-reviewer-' + request['token'])
        return self.controller.finish(request['token'], self.review_result(request, **overrides))

    def start(self):
        self.controller.init(self.config)
        request = self.next('initial')['request']
        self.finish_review(request)

    def finish_worker(self, request, status='done'):
        if request['token'] not in self.controller.status().get('delegations', {}):
            self.controller.bind_agent(request['token'], 'fixture-worker-' + request['token'])
        if status == 'done':
            (self.root / (request['action_id'] + '.txt')).write_text('observed ' + request['action_id'])
        return self.controller.finish(request['token'], {'status': status})

    def test_opt_in_pool_requires_positive_finite_worker_limit(self):
        for value in (0, -1, True, 1.5, '2'):
            with self.subTest(value=value):
                config = copy.deepcopy(self.config)
                config['agent_pool']['max_workers'] = value
                with self.assertRaises(ContractError):
                    self.controller.init(config)

    def test_explicit_serialized_configuration_stays_single_token(self):
        del self.config['agent_pool']
        self.config['scheduling_mode'] = 'serialized'
        self.controller.init(self.config)
        initial = self.controller.next()['request']
        self.controller.finish(initial['token'], self.review_result(initial))
        worker = self.controller.next()['request']
        recovered = self.controller.next()
        self.assertEqual(recovered['status'], 'IN_FLIGHT')
        self.assertEqual(recovered['request']['token'], worker['token'])

    def test_disjoint_workers_overlap_and_maximum_is_enforced(self):
        self.start()
        a, b = self.next()['request'], self.next()['request']
        self.assertNotEqual(a['token'], b['token'])
        self.assertEqual({a['action_id'], b['action_id']}, {'a', 'b'})
        self.assertNotEqual(self.next()['status'], 'DISPATCH')
        self.assertFalse(self.controller.status()['complete'])

    def test_dispatch_intent_survives_restart_without_duplicate(self):
        self.start()
        first = self.next('durable-intent')['request']
        recovered = Controller(self.root / 'state').next(dispatch_id='durable-intent')
        self.assertEqual(recovered['request']['token'], first['token'])
        self.assertEqual(self.controller.status()['dispatches'], 2)

    def test_no_intent_inspection_never_reserves_work(self):
        self.start()
        before = self.controller.status()['dispatches']
        self.controller.next()
        self.assertEqual(self.controller.status()['dispatches'], before)

    def test_disjoint_completion_review_and_refill_before_straggler(self):
        self.start()
        a, b = self.next()['request'], self.next()['request']
        self.finish_worker(b)
        review = self.next()['request']
        self.assertEqual(review['role'], 'claims_reviewer')
        self.assertIn(b['token'], review['review_work_tokens'])
        self.finish_review(review)
        c = self.next()['request']
        self.assertEqual(c['action_id'], 'c')
        self.assertEqual(self.controller.check(a['token'])['status'], 'READY')

    def test_write_conflict_prevents_second_worker(self):
        self.config['actions'][1]['write_paths'] = ['a.txt']
        self.config['actions'][2]['write_paths'] = ['a.txt']
        self.start()
        self.next()
        self.assertNotEqual(self.next()['status'], 'DISPATCH')

    def test_read_write_conflict_prevents_second_worker(self):
        self.config['actions'][1]['read_paths'].append('a.txt')
        self.config['actions'][2]['read_paths'].append('a.txt')
        self.start()
        self.next()
        self.assertNotEqual(self.next()['status'], 'DISPATCH')

    def test_changed_shared_input_stales_running_worker(self):
        self.start()
        worker = self.next()['request']
        (self.root / 'protocol.txt').write_text('changed protocol')
        self.assertEqual(self.controller.check(worker['token'])['status'], 'STALE')

    def test_worker_cannot_approve_own_claims(self):
        self.start()
        worker = self.next()['request']
        self.controller.bind_agent(worker['token'], 'fixture-worker')
        with self.assertRaises(ContractError):
            self.controller.finish(worker['token'], {'status': 'done', 'claim_updates': []})

    def test_dependency_waits_for_review(self):
        self.config['actions'][2].update(depends_on=['b'], required_claims=['P', 'b'], read_paths=['protocol.txt', 'b.txt'])
        self.start()
        selected = [self.next()['request'], self.next()['request']]
        b = next(r for r in selected if r['action_id'] == 'b')
        self.finish_worker(b)
        review = self.next()['request']
        self.assertEqual(review['role'], 'claims_reviewer')
        self.assertNotEqual(self.next()['status'], 'DISPATCH')
        self.finish_review(review)
        self.assertEqual(self.next()['request']['action_id'], 'c')

    def test_pause_blocks_new_reservations_but_preserves_results(self):
        self.start()
        worker = self.next()['request']
        self.controller.bind_agent(worker['token'], 'fixture-worker')
        self.controller.control('paused', 'fixture pause')
        self.assertEqual(self.next()['status'], 'PAUSED')
        self.finish_worker(worker)
        self.assertEqual(self.controller.status()['control'], 'paused')

    def test_duplicate_result_is_idempotent_conflict_is_rejected(self):
        self.start()
        worker = self.next()['request']
        self.finish_worker(worker)
        self.assertEqual(self.controller.finish(worker['token'], {'status': 'done'})['status'], 'ALREADY_RECORDED')
        with self.assertRaises(ContractError):
            self.controller.finish(worker['token'], {'status': 'failed'})

    def test_reusing_running_identity_is_rejected(self):
        self.start()
        a, b = self.next()['request'], self.next()['request']
        self.controller.bind_agent(a['token'], 'fixture-worker')
        with self.assertRaises(ContractError):
            self.controller.bind_agent(b['token'], 'fixture-worker')

    def test_idle_reuse_requires_fresh_quiescent_observation(self):
        self.start()
        a, b = self.next()['request'], self.next()['request']
        self.controller.bind_agent(b['token'], 'fixture-worker')
        self.finish_worker(b)
        review = self.next()['request']
        self.finish_review(review)
        c = self.next()['request']
        with self.assertRaises(ContractError):
            self.controller.bind_agent(c['token'], 'fixture-worker')
        observation = {'observed_at': time.time(), 'source_ref': 'fixture-host-log', 'agent_id': 'fixture-worker',
                       'status': 'idle', 'execution_quiescent': True}
        self.assertEqual(self.controller.bind_agent(c['token'], 'fixture-worker', observation=observation)['status'], 'BOUND')

    def test_budget_is_shared_across_concurrent_reservations(self):
        self.config['max_dispatches'] = 2
        self.start()
        self.next()
        self.assertEqual(self.next()['status'], 'BUDGET_EXHAUSTED')
        self.assertEqual(self.controller.status()['dispatches'], 2)


    def test_unit_review_cannot_use_other_live_workers_evidence(self):
        self.start()
        a, b = self.next()['request'], self.next()['request']
        self.controller.bind_agent(a['token'], 'worker-a')
        self.finish_worker(b)
        review = self.next()['request']
        self.controller.bind_agent(review['token'], 'reviewer-b')
        (self.root / 'a.txt').write_text('live unrelated output')
        result = self.review_result(review)
        result['claim_updates'].append({'id': 'a', 'status': 'supported', 'evidence': [{
            'path': 'a.txt', 'sha256': hashlib.sha256((self.root / 'a.txt').read_bytes()).hexdigest(),
            'locator': 'line:1', 'method': 'source_inspection', 'relation': 'supports'}],
            'limitations': [], 'rationale': 'Forbidden unrelated live evidence', 'audit_refs': []})
        with self.assertRaises(ContractError):
            self.controller.finish(review['token'], result)
        self.assertEqual(self.controller.finish(review['token'], self.review_result(review))['status'], 'RECORDED')

    def test_worker_identity_excluded_from_its_unit_review(self):
        self.start()
        worker = self.next()['request']
        self.controller.bind_agent(worker['token'], 'worker-own-output')
        self.finish_worker(worker)
        review = self.next()['request']
        observation = {'observed_at': time.time(), 'source_ref': 'fixture-host-log',
            'agent_id': 'worker-own-output', 'status': 'idle', 'execution_quiescent': True}
        with self.assertRaises(ContractError):
            self.controller.bind_agent(review['token'], 'worker-own-output', observation=observation)

    def test_unbound_result_cannot_bypass_review_independence(self):
        self.controller.init(self.config)
        review = self.next()['request']
        with self.assertRaises(ContractError):
            self.controller.finish(review['token'], self.review_result(review))

    def test_undeclared_write_scope_rejected_at_initialization(self):
        self.config['actions'][0]['write_paths'] = ['outside.txt']
        with self.assertRaises(ContractError):
            self.controller.init(self.config)

    def test_path_alias_rejected_at_initialization(self):
        self.config['evidence'].append('./a.txt')
        self.config['actions'][1]['write_paths'] = ['./a.txt']
        with self.assertRaises(ContractError):
            self.controller.init(self.config)

    def test_failed_and_uncertain_work_create_review_obligations(self):
        self.start()
        a, b = self.next()['request'], self.next()['request']
        self.finish_worker(a, 'failed')
        self.finish_worker(b, 'uncertain')
        reviewed = set()
        for _ in range(2):
            review = self.next()['request']
            self.assertEqual(review['role'], 'claims_reviewer')
            reviewed.update(review['review_work_tokens'])
            self.finish_review(review)
            if reviewed == {a['token'], b['token']}:
                break
        self.assertEqual(reviewed, {a['token'], b['token']})
        state = self.controller.status()
        self.assertFalse(state['complete'])
        self.assertEqual(state['actions']['a'], 'failed')
        self.assertEqual(state['actions']['b'], 'uncertain')

    def test_reused_agent_with_new_pending_assignment_cannot_be_closed(self):
        self.start()
        a, b = self.next()['request'], self.next()['request']
        self.controller.bind_agent(b['token'], 'reusable-worker')
        self.finish_worker(b)
        self.finish_review(self.next()['request'])
        c = self.next()['request']
        observation = {'observed_at': time.time(), 'source_ref': 'fixture-host-log',
            'agent_id': 'reusable-worker', 'status': 'idle', 'execution_quiescent': True}
        self.controller.bind_agent(c['token'], 'reusable-worker', observation=observation)
        plan = self.controller.agent_cleanup({'observed_at': time.time(), 'source_ref': 'fixture-host-log',
            'close_supported': True, 'agents': [{'agent_id': 'reusable-worker', 'status': 'completed', 'execution_quiescent': True}]})
        record = next(a for a in plan['agents'] if a['agent_id'] == 'reusable-worker')
        self.assertNotEqual(record['decision'], 'ELIGIBLE_FOR_HOST_CLOSE')



    def test_spawn_failure_is_recorded_against_pool_token(self):
        self.start()
        token = self.next()['request']['token']
        attempt = self.controller.spawn_attempt(token)
        self.assertEqual(attempt['status'], 'SPAWN_RESERVED')
        failure = {'attempt_id': attempt['attempt_id'], 'error': 'agent thread limit reached.',
                   'source_ref': 'fixture-host-call', 'no_agent_created': True}
        self.assertEqual(self.controller.spawn_result(token, failure)['outcome'], 'thread_limit')
        self.assertEqual(self.controller.spawn_attempt(token)['status'], 'WAITING_FOR_CAPACITY')

    def test_ambiguous_spawn_failure_never_gets_new_reservation(self):
        self.start()
        token = self.next()['request']['token']
        attempt = self.controller.spawn_attempt(token)
        failure = {'attempt_id': attempt['attempt_id'], 'error': 'connection lost',
                   'source_ref': 'fixture-host-call', 'no_agent_created': False}
        self.assertEqual(self.controller.spawn_result(token, failure)['outcome'], 'uncertain')
        self.assertEqual(self.controller.spawn_attempt(token)['status'], 'RECOVER_SPAWN')
        self.assertEqual(len(self.controller.status()['spawn_attempts'][token]), 1)

    def test_goal_revision_forces_fresh_global_review(self):
        self.start()
        self.controller.revise('2', 'Revised checked fixture', ['all outputs reviewed'], 'fixture owner')
        request = self.next()['request']
        self.assertEqual(request['role'], 'claims_reviewer')
        self.assertEqual(request['review_scope'], 'global')

    def test_external_read_modify_write_source_change_is_stale(self):
        (self.root / 'a.txt').write_text('initial read modify write source')
        self.start()
        request = self.next()['request']
        self.assertEqual(request['action_id'], 'a')
        (self.root / 'a.txt').write_text('external mutation before start')
        self.assertEqual(self.controller.check(request['token'])['status'], 'STALE')



    def test_reconciled_uncertain_action_is_reviewed_before_dependent_dispatch(self):
        self.config['actions'][1].update(depends_on=['a'], required_claims=['P', 'a'], read_paths=['protocol.txt', 'a.txt'])
        self.config['actions'][2].update(depends_on=['b'], required_claims=['P', 'b'], read_paths=['protocol.txt', 'b.txt'])
        self.start()
        worker = self.next()['request']
        self.finish_worker(worker, 'uncertain')
        self.finish_review(self.next()['request'])
        (self.root / 'a.txt').write_text('Observed completed result from original operation')
        self.controller.reconcile('a', 'done', 'Inspected original a.txt after operation ended')
        review = self.next()['request']
        self.assertEqual(review['role'], 'claims_reviewer')
        self.finish_review(review)
        self.assertEqual(self.next()['request']['action_id'], 'b')

    def test_malformed_nested_claim_id_rejected_as_contract_error(self):
        self.controller.init(self.config)
        review = self.next()['request']
        self.controller.bind_agent(review['token'], 'fixture-reviewer')
        result = self.review_result(review)
        result['claim_updates'][0]['id'] = []
        with self.assertRaises(ContractError):
            self.controller.finish(review['token'], result)

    def test_self_review_exclusion_survives_restart(self):
        self.start()
        worker = self.next()['request']
        self.controller.bind_agent(worker['token'], 'worker-original')
        self.finish_worker(worker)
        self.controller = Controller(self.root / 'state')
        review = self.next()['request']
        observation = {'observed_at': time.time(), 'source_ref': 'fixture-recovered-host-log',
            'agent_id': 'worker-original', 'status': 'idle', 'execution_quiescent': True}
        with self.assertRaises(ContractError):
            self.controller.bind_agent(review['token'], 'worker-original', observation=observation)

    def test_existing_hardlink_write_alias_rejected(self):
        (self.root / 'a.txt').write_text('shared inode')
        try:
            os.link(self.root / 'a.txt', self.root / 'b.txt')
        except OSError as exc:
            self.skipTest('Host cannot create hardlink fixture: ' + str(exc))
        with self.assertRaises(ContractError):
            self.controller.init(self.config)


if __name__ == '__main__':
    unittest.main()
