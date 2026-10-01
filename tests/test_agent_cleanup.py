"""Host lifecycle cleanup never substitutes for claims review or deletes evidence."""
import copy
import hashlib
import json
import subprocess
import sys
import time
import unittest
import test_long_running_subagents as base
from agent_cleanup import plan
from long_running_controller import ContractError, Controller


class CleanupPlanTests(unittest.TestCase):
    def setUp(self):
        self.state = {'delegations': {'token': {'agent_id': 'child'}},
                      'receipts': {'token': 'recorded-result-digest'}, 'pending': None}
        self.observation = {'observed_at': 100, 'source_ref': 'native-list-result',
            'close_supported': True, 'agents': [dict(agent_id='child', status='completed', execution_quiescent=True)]}

    def decision(self):
        return plan(self.state, self.observation, now=101)['agents'][0]['decision']

    def test_recorded_completed_agent_is_candidate_without_mutation(self):
        before = copy.deepcopy(self.state)
        self.assertEqual(self.decision(), 'ELIGIBLE_FOR_HOST_CLOSE')
        self.assertEqual(self.state, before)
        self.assertFalse(plan(self.state, self.observation, now=101)['host_actions_performed'])

    def test_terminal_outcome_requires_recorded_result(self):
        for status in ('completed', 'failed', 'cancelled', 'closed'):
            with self.subTest(status=status):
                self.observation['agents'][0]['status'] = status
                self.state['receipts'] = {}
                self.assertEqual(self.decision(), 'RETAIN_UNRECORDED_RESULT')

    def test_live_idle_missing_unknown_and_child_execution_are_retained(self):
        for status, decision in [('running','RETAIN_RUNNING'), ('idle','RETAIN_UNKNOWN_EXECUTION'), ('unknown','RETAIN_UNKNOWN_EXECUTION')]:
            self.observation['agents'][0]['status'] = status
            self.assertEqual(self.decision(), decision)
        self.observation['agents'][0].update(status='completed', execution_quiescent=False)
        self.assertEqual(self.decision(), 'RETAIN_UNRESOLVED_EXECUTION')
        self.observation['agents'] = []
        self.assertEqual(self.decision(), 'RETAIN_UNKNOWN_EXECUTION')

    def test_pending_or_reused_identity_blocks_cleanup(self):
        self.state['delegations']['second'] = {'agent_id': 'child'}
        self.state['pending'] = {'token':'second'}
        self.assertEqual(self.decision(), 'RETAIN_UNRECORDED_RESULT')

    def test_unrelated_agents_never_become_candidates(self):
        self.observation['agents'].append(dict(agent_id='other', status='completed', execution_quiescent=True))
        result = plan(self.state, self.observation, now=101)
        self.assertEqual(result['ignored_unbound_ids'], ['other'])
        self.assertEqual([x['agent_id'] for x in result['agents']], ['child'])

    def test_missing_close_capability_and_already_closed_are_explicit(self):
        self.observation['close_supported'] = False
        self.assertEqual(self.decision(), 'CLOSE_UNAVAILABLE')
        self.observation['agents'][0]['status'] = 'closed'
        self.assertEqual(self.decision(), 'ALREADY_CLOSED')

    def test_stale_future_nonfinite_and_boolean_times_rejected(self):
        for stamp in (0, 102, float('nan'), float('inf'), True, '100'):
            with self.subTest(stamp=stamp), self.assertRaises(ContractError):
                plan(self.state, dict(self.observation, observed_at=stamp), now=101)

    def test_duplicate_ids_and_non_boolean_quiescence_rejected(self):
        self.observation['agents'] *= 2
        with self.assertRaises(ContractError): plan(self.state, self.observation, now=101)
        self.observation['agents'] = self.observation['agents'][:1]
        self.observation['agents'][0]['execution_quiescent'] = 'yes'
        with self.assertRaises(ContractError): plan(self.state, self.observation, now=101)


class CleanupControllerTests(unittest.TestCase):
    setUp = base.SubagentModeTests.setUp
    tearDown = base.SubagentModeTests.tearDown
    start = base.SubagentModeTests.start
    update = base.SubagentModeTests.update
    result = base.SubagentModeTests.result
    finish_review = base.SubagentModeTests.finish_review
    dispatch_worker = base.SubagentModeTests.dispatch_worker

    def test_restart_cli_plans_without_mutating_claims_journal_or_reports(self):
        worker = self.dispatch_worker()
        self.controller.bind_agent(worker['token'], 'native-worker')
        self.controller.finish(worker['token'], {'status':'done','evidence_refs':['evidence.txt']})
        self.controller = Controller(self.root/'state')
        observation = {'observed_at':time.time(), 'source_ref':'synthetic-host-list', 'close_supported':True,
                       'agents':[dict(agent_id='native-worker',status='completed',execution_quiescent=True)]}
        path = self.root/'host.json';path.write_text(json.dumps(observation))
        def hashes():
            return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.root/'state').rglob('*') if p.is_file()}
        before = hashes()
        process = subprocess.run([sys.executable,'-B',str(base.SCRIPTS/'long_running_controller.py'),
            '--state',str(self.root/'state'),'agent-cleanup','--observation',str(path)],capture_output=True,text=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(json.loads(process.stdout)['agents'][0]['decision'],'ELIGIBLE_FOR_HOST_CLOSE')
        self.assertEqual(hashes(),before)
        state = self.controller.status()
        self.assertTrue(state['claim_dirty'])
        self.assertTrue(state['review_due'])
        self.assertFalse(state['complete'])
        self.assertEqual(self.controller.next()['request']['role'],'claims_reviewer')
