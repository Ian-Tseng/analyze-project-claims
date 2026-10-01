"""New budgets are explicit; old journal semantics cannot expand on upgrade."""
import unittest
from unittest.mock import patch
import test_long_running_controller as base
from long_running_controller import Controller, ContractError, digest


class RepairBudgetTests(unittest.TestCase):
    setUp = base.ControllerTests.setUp
    tearDown = base.ControllerTests.tearDown
    start = base.ControllerTests.start
    review = base.ControllerTests.review

    def actions(self, count):
        self.config['max_dispatches'] = 200
        self.config['actions'] = [dict(id=f'fix{i}', kind='repair', instruction='Fix fixture',
            attempt_id='A', attempt_authorization_ref='authorized fixture') for i in range(count)]

    def exhaust(self, limit, request):
        for i in range(limit):
            self.review(request, decision='REPAIR', cleared_actions=[f'fix{i}'], next_action=f'fix{i}',
                        findings=[dict(id=f'f{i}', evidence='evidence.txt', reason=f'case {i}')])
            action = self.controller.next()['request']
            self.assertEqual(action['action_id'], f'fix{i}')
            (self.root/'evidence.txt').write_text(f'candidate {i}')
            self.controller.finish(action['token'], {'status':'done'})
            self.controller = Controller(self.root/'state')
            request = self.controller.next()['request']
        self.review(request, decision='REPAIR', cleared_actions=[f'fix{limit}'], next_action=f'fix{limit}',
                    findings=[dict(id='last', evidence='evidence.txt', reason='remaining mismatch')])
        self.assertEqual(self.controller.next()['status'], 'WAITING')
        self.assertEqual(self.controller.status()['attempts']['A']['cycles'], limit)
        self.assertEqual(self.controller.status()['repair_cycle_limit'], limit)

    def test_default_32_cycles_survive_restarts_and_stop_at_limit(self):
        self.actions(33)
        request = self.start()
        self.assertEqual(request['config']['max_repair_cycles'], 32)
        self.exhaust(32, request)

    def test_explicit_budget_is_enforced(self):
        self.config['max_repair_cycles'] = 5
        self.actions(6)
        self.exhaust(5, self.start())

    def test_invalid_budgets_fail_before_initialization(self):
        for value in (True, False, 0, -1, 1.5, '32', None, 10001):
            with self.subTest(value=value), self.assertRaises(ContractError):
                Controller(self.root/f'invalid-{value}').init(dict(self.config, max_repair_cycles=value))

    def legacy_start(self):
        save = self.controller._save
        def legacy_save(state, kind, seq, previous, **kwargs):
            # Construct a synthetic pre-upgrade initial event, never rewrite a live journal.
            state['config'].pop('max_repair_cycles', None)
            state['config_digest'] = digest(state['config'])
            return save(state, kind, seq, previous, **kwargs)
        with patch.object(self.controller, '_save', side_effect=legacy_save):
            self.controller.init(self.config)
        return self.controller.next()['request']

    def test_legacy_journal_retains_three_cycle_limit(self):
        self.actions(4)
        self.exhaust(3, self.legacy_start())
        self.assertNotIn('max_repair_cycles', self.controller.status()['config'])

    def test_plan_revision_cannot_expand_legacy_budget(self):
        request = self.legacy_start()
        self.review(request)
        state = self.controller.status()
        proposal = dict(revision_id='add-one', base_config_digest=state['config_digest'],
                        add_actions=[dict(id='extra', instruction='Authorized additional observation')], dependencies={})
        self.controller.authorize_plan(proposal, 'existing', self.config['authorization_ref'], 'fixture scope')
        self.controller.revise_plan(proposal)
        state = self.controller.status()
        self.assertNotIn('max_repair_cycles', state['config'])
        self.assertEqual(state['repair_cycle_limit'], 3)

    def test_goal_revision_preserves_explicit_budget(self):
        self.config['max_repair_cycles'] = 48
        self.review(self.start())
        self.controller.revise('2', 'Clarified fixture objective', ['output verified'], 'fixture authority')
        self.assertEqual(self.controller.status()['repair_cycle_limit'], 48)

    def test_plan_patch_cannot_raise_current_attempt_budget(self):
        self.review(self.start())
        state = self.controller.status()
        proposal = dict(revision_id='raise', base_config_digest=state['config_digest'], add_actions=[],
                        dependencies={}, max_repair_cycles=64)
        with self.assertRaises(ContractError):
            self.controller.authorize_plan(proposal, 'existing', self.config['authorization_ref'], 'not a supported patch')
