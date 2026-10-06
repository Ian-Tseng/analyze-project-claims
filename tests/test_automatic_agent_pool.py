"""Automatic selection and append-only migration; synthetic fixtures only."""
import time
import unittest
from unittest.mock import patch
import test_agent_pool as fixtures
from long_running_controller import Controller, ContractError

class AutomaticPoolTests(unittest.TestCase):
    setUp = fixtures.AgentPoolTests.setUp
    tearDown = fixtures.AgentPoolTests.tearDown
    review_result = fixtures.AgentPoolTests.review_result
    finish_review = fixtures.AgentPoolTests.finish_review
    finish_worker = fixtures.AgentPoolTests.finish_worker
    action = fixtures.AgentPoolTests.action
    next = fixtures.AgentPoolTests.next

    def legacy(self):
        self.config.pop('agent_pool', None)
        with patch('agent_pool.configure_new', side_effect=lambda c: c, create=True):
            self.controller.init(self.config)

    def journal(self):
        return {p.name: p.read_bytes() for p in (self.root / 'state' / 'journal').glob('*.json')}

    def legacy_worker(self, bind=True):
        self.legacy()
        review = self.controller.next()['request']
        self.controller.bind_agent(review['token'], 'old-reviewer')
        self.controller.finish(review['token'], self.review_result(review))
        worker = self.controller.next()['request']
        if bind:
            self.controller.bind_agent(worker['token'], 'old-worker')
        (self.root / (worker['action_id'] + '.txt')).write_text('legacy output')
        self.controller.finish(worker['token'], {'status': 'done'})
        return worker

    def observation(self, agent_id):
        return dict(observed_at=time.time(), source_ref='fixture/native-list',
                    agent_id=agent_id, status='idle', execution_quiescent=True)

    def test_new_delegated_goal_defaults_to_pool(self):
        self.config.pop('agent_pool')
        state = self.controller.init(self.config)
        self.assertEqual(state['config']['agent_pool'], {'max_workers': 2})
        self.finish_review(self.next()['request'])
        self.assertNotEqual(self.next()['request']['action_id'], self.next()['request']['action_id'])

    def test_missing_scopes_allow_reuse_but_block_overlap(self):
        self.config.pop('agent_pool')
        for action in self.config['actions']:
            action.pop('read_paths')
            action.pop('write_paths')
        self.controller.init(self.config)
        self.finish_review(self.next()['request'])
        first = self.next()['request']
        self.assertEqual(set(first['write_paths']), set(self.config['evidence']))
        self.assertNotEqual(self.next()['status'], 'DISPATCH')
        self.finish_worker(first)
        self.finish_review(self.next()['request'])
        second = self.next()['request']
        agent_id = 'fixture-worker-' + first['token']
        self.assertEqual(self.controller.bind_agent(second['token'], agent_id, self.observation(agent_id))['status'], 'BOUND')

    def test_explicit_serialized_choice_is_respected(self):
        self.config.pop('agent_pool')
        self.config['scheduling_mode'] = 'serialized'
        self.assertNotIn('agent_pool', self.controller.init(self.config)['config'])
        with self.assertRaises(ContractError):
            self.next()
        self.assertEqual(self.controller.next()['status'], 'DISPATCH')

    def test_migration_preserves_history_budgets_and_review_independence(self):
        self.config.update(max_dispatches=9, max_repair_cycles=3, max_spawn_attempts=1)
        self.config['actions'][2]['depends_on'] = ['a']
        worker = self.legacy_worker()
        before, journal = self.controller.status(), self.journal()
        review = self.next('migrate')['request']
        self.assertEqual(review['role'], 'claims_reviewer')
        self.assertIn(worker['token'], review['review_work_tokens'])
        self.assertIn('old-worker', review['excluded_agent_ids'])
        state = self.controller.status()
        for key in ('receipts', 'actions', 'attempts', 'holds', 'findings', 'delegations'):
            self.assertEqual(state[key], before[key])
        self.assertEqual(state['dispatches'], before['dispatches'] + 1)
        for key in ('max_dispatches', 'max_repair_cycles', 'max_spawn_attempts', 'goal_id', 'goal_revision'):
            self.assertEqual(state['config'][key], before['config'][key])
        for name, data in journal.items():
            self.assertEqual(self.journal()[name], data)
        with self.assertRaises(ContractError):
            self.controller.bind_agent(review['token'], 'old-worker')
        self.controller.bind_agent(review['token'], 'old-reviewer', self.observation('old-reviewer'))
        self.controller.finish(review['token'], self.review_result(review))
        self.assertIn('a', self.controller.status()['pool_reviewed_actions'])
        following = self.next()['request']
        self.controller.bind_agent(following['token'], 'old-worker', self.observation('old-worker'))
        self.assertEqual(self.controller.finish(worker['token'], {'status': 'done'})['status'], 'ALREADY_RECORDED')
        self.assertEqual(Controller(self.root / 'state').next('migrate')['status'], 'ALREADY_RECORDED')

    def test_pending_assignment_defers_migration(self):
        self.legacy()
        original = self.controller.next()['request']
        before = self.journal()
        result = self.next('migration-intent')
        self.assertEqual(result['status'], 'IN_FLIGHT')
        self.assertEqual(result['request']['token'], original['token'])
        self.assertEqual(self.journal(), before)
        self.controller.bind_agent(original['token'], 'old-reviewer')
        self.controller.finish(original['token'], self.review_result(original))
        self.assertEqual(self.next('migration-intent')['request']['role'], 'claims_reviewer')

    def test_pause_stop_and_status_do_not_migrate(self):
        self.legacy()
        self.controller.control('paused', 'owner pause')
        before = self.journal()
        self.assertEqual(self.next()['status'], 'PAUSED')
        self.assertNotIn('agent_pool', self.controller.status()['config'])
        self.assertEqual(self.journal(), before)
        self.controller.control('stopped', 'owner stop')
        before = self.journal()
        self.assertEqual(self.next()['status'], 'STOPPED')
        self.assertEqual(self.journal(), before)

    def test_exhausted_budget_is_not_reset(self):
        self.config['max_dispatches'] = 1
        self.legacy()
        review = self.controller.next()['request']
        self.controller.bind_agent(review['token'], 'old-reviewer')
        self.controller.finish(review['token'], self.review_result(review))
        before = self.journal()
        self.assertEqual(self.next()['status'], 'BUDGET_EXHAUSTED')
        self.assertEqual(self.journal(), before)

    def test_missing_historical_worker_identity_blocks_migration(self):
        self.legacy_worker(bind=False)
        before = self.journal()
        result = self.next()
        self.assertEqual(result['status'], 'MIGRATION_BLOCKED')
        self.assertIn('identity', result['reason'])
        self.assertEqual(self.journal(), before)

    def test_failed_review_allowance_survives_migration(self):
        self.legacy()
        for i in range(2):
            request = self.controller.next()['request']
            self.controller.bind_agent(request['token'], 'failed-reviewer-' + str(i))
            self.controller.finish(request['token'], self.review_result(request, review_status='FAILED'))
        self.assertEqual(self.next()['status'], 'WAITING')
        self.assertEqual(self.controller.status()['review_failures'], 2)
        self.assertEqual(self.controller.status()['dispatches'], 2)

    def test_real_source_drift_still_reopens_failed_review(self):
        self.legacy()
        for i in range(2):
            request = self.controller.next()['request']
            self.controller.bind_agent(request['token'], 'failed-reviewer-' + str(i))
            self.controller.finish(request['token'], self.review_result(request, review_status='FAILED'))
        (self.root / 'protocol.txt').write_text('new evidence after failed review')
        request = self.next()['request']
        self.assertEqual(request['role'], 'claims_reviewer')
        self.assertEqual(self.controller.status()['review_failures'], 0)
        self.assertEqual(self.controller.status()['dispatches'], 3)

    def test_actual_repair_and_spawn_history_survive(self):
        self.config['actions'][0].update(kind='repair', attempt_id='repair-1',
                                        attempt_authorization_ref='fixture owner')
        self.legacy()
        review = self.controller.next()['request']
        self.controller.spawn_attempt(review['token'])
        self.controller.bind_agent(review['token'], 'legacy-reviewer')
        self.controller.finish(review['token'], self.review_result(
            review, decision='REPAIR', cleared_actions=['a'], next_action='a',
            findings=[dict(id='F', evidence='protocol.txt', reason='fixture defect')]))
        worker = self.controller.next()['request']
        self.controller.bind_agent(worker['token'], 'repair-worker')
        (self.root / 'a.txt').write_text('candidate repair')
        self.controller.finish(worker['token'], {'status': 'done'})
        before = self.controller.status()
        self.next()
        after = self.controller.status()
        self.assertEqual(before['attempts']['repair-1']['cycles'], 1)
        for key in ('attempts', 'spawn_attempts', 'findings', 'holds'):
            self.assertEqual(after.get(key), before.get(key))

    def test_invalid_partial_scope_is_rejected_without_state(self):
        self.config.pop('agent_pool')
        self.config['actions'][0].pop('write_paths')
        with self.assertRaises(ContractError):
            self.controller.init(self.config)
        self.assertFalse((self.root / 'state' / 'journal').exists())

    def test_migration_with_no_work_is_idempotent_and_retains_global_review(self):
        self.legacy()
        first = self.next('durable-migration')['request']
        before = self.journal()
        recovered = Controller(self.root / 'state').next('durable-migration')['request']
        self.assertEqual(recovered['token'], first['token'])
        self.assertEqual(self.journal(), before)
        self.assertEqual(first['review_scope'], 'global')

    def complete_legacy(self):
        self.legacy()
        for i in range(3):
            review = self.controller.next()['request']
            self.controller.bind_agent(review['token'], 'reviewer-' + str(i))
            self.controller.finish(review['token'], self.review_result(review))
            worker = self.controller.next()['request']
            self.controller.bind_agent(worker['token'], 'worker-' + str(i))
            (self.root / (worker['action_id'] + '.txt')).write_text('completed output')
            self.controller.finish(worker['token'], {'status': 'done'})
        review = self.controller.next()['request']
        self.controller.bind_agent(review['token'], 'legacy-final-reviewer')
        self.controller.finish(review['token'], self.review_result(
            review, goal_complete=True, verified_criteria=self.config['success_criteria'],
            evidence_refs=['protocol.txt']))

    def test_current_completed_goal_is_unchanged(self):
        self.complete_legacy()
        before = self.journal()
        self.assertEqual(self.next()['status'], 'COMPLETE')
        self.assertEqual(self.journal(), before)

    def test_completed_goal_with_new_evidence_reopens_review_without_repeating_work(self):
        self.complete_legacy()
        before = self.controller.status()
        (self.root / 'protocol.txt').write_text('changed completed goal input')
        review = self.next()['request']
        self.assertEqual(review['review_scope'], 'global')
        self.assertEqual(self.controller.status()['actions'], before['actions'])
        self.assertFalse(self.controller.status()['complete'])
        self.finish_review(review, goal_complete=True,
                           verified_criteria=self.config['success_criteria'], evidence_refs=['protocol.txt'])
        self.assertEqual(self.next()['status'], 'COMPLETE')
