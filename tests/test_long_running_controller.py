import copy
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "analyze-project-claims" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from long_running_controller import Controller, ContractError, read_json


def contend(root, queue):
    try:
        Controller(root).status()
        queue.put("unlocked")
    except ContractError:
        queue.put("locked")

class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'evidence.txt').write_text('initial')
        self.config = {
            'goal_id': 'test-goal', 'goal_revision': '1', 'objective': 'Produce checked output',
            'authorization_ref': 'test fixture only', 'project_root': str(self.root),
            'evidence': ['evidence.txt'], 'success_criteria': ['output verified'],
            'actions': [{'id': 'build', 'instruction': 'Produce output', 'kind': 'work'}]}
        self.controller = Controller(self.root / 'state')

    def tearDown(self):
        self.tmp.cleanup()

    def start(self):
        self.controller.init(self.config)
        return self.controller.next()['request']

    def review(self, request, **overrides):
        result = {'review_status': 'COMPLETE', 'decision': 'CONTINUE',
                  'snapshot_digest': request['snapshot']['digest'], 'request_digest': request['semantic_digest'], 'coverage': 'Test-only evidence file and action',
                  'cleared_actions': ['build'], 'next_action': 'build'}
        result.update(overrides)
        self.controller.finish(request['token'], result)
        return result

    def test_clean_review_automatically_selects_action(self):
        self.review(self.start())
        self.assertEqual(self.controller.next()['request']['action_id'], 'build')

    def test_stale_review_never_clears_action(self):
        request = self.start()
        (self.root / 'evidence.txt').write_text('changed')
        result = self.review(request)
        self.assertEqual(self.controller.status()['clearances'], {})
        self.assertEqual(self.controller.next()['request']['kind'], 'review')

    def test_pause_beats_queued_continuation(self):
        request = self.start()
        self.controller.control('paused', 'User requested pause')
        self.review(request)
        self.assertEqual(self.controller.next()['status'], 'PAUSED')
        self.controller.control('active', 'User requested resume')
        self.assertEqual(self.controller.next()['request']['action_id'], 'build')

    def test_duplicate_next_does_not_redispatch(self):
        request = self.start()
        other = Controller(self.root / 'state').next()
        self.assertEqual(other['status'], 'IN_FLIGHT')
        self.assertEqual(other['request']['token'], request['token'])

    def test_duplicate_receipt_is_idempotent_and_conflict_rejected(self):
        request = self.start()
        result = self.review(request)
        self.assertEqual(self.controller.finish(request['token'], result)['status'], 'ALREADY_RECORDED')
        with self.assertRaises(ContractError):
            self.controller.finish(request['token'], dict(result, coverage='different'))

    def test_partial_review_only_clears_assessed_action(self):
        self.config['actions'].append({'id': 'publish', 'instruction': 'Second task'})
        self.review(self.start(), review_status='PARTIAL', cleared_actions=['build'])
        self.assertNotIn('publish', self.controller.status()['clearances'])
        self.assertEqual(self.controller.next()['request']['action_id'], 'build')

    def test_hold_persists_and_independent_work_continues(self):
        self.config['actions'].append({'id': 'other', 'instruction': 'Independent task'})
        request = self.start()
        self.review(request, decision='HOLD_DEPENDENT_ACTION', holds={'build': 'Missing data'}, cleared_actions=['other'], next_action='other')
        action = self.controller.next()['request']
        self.assertEqual(action['action_id'], 'other')
        self.controller.finish(action['token'], {'status': 'done'})
        with self.assertRaises(ContractError):
            self.review(self.controller.next()['request'])

    def test_hold_release_requires_specific_evidence(self):
        request = self.start()
        self.review(request, decision='HOLD_DEPENDENT_ACTION', holds={'build': 'Missing data'}, cleared_actions=[], next_action=None)
        (self.root / 'evidence.txt').write_text('required data')
        request = self.controller.next()['request']
        self.review(request, release_holds={'build': 'evidence.txt now contains required data'})
        self.assertEqual(self.controller.next()['request']['action_id'], 'build')

    def test_review_failure_retries_once_then_waits(self):
        request = self.start()
        for _ in range(2):
            self.review(request, review_status='FAILED', cleared_actions=[], next_action=None)
            item = self.controller.next()
            request = item.get('request')
        self.assertEqual(item['status'], 'WAITING')
        self.assertEqual(self.controller.status()['review_failures'], 2)

    def test_failed_review_does_not_block_declared_independent_action(self):
        self.config['actions'][0]['requires_review'] = False
        request = self.start()
        for _ in range(2):
            self.review(request, review_status='FAILED', cleared_actions=[], next_action=None)
            item = self.controller.next()
            request = item.get('request')
        self.assertEqual(item['request']['action_id'], 'build')

    def test_unknown_action_is_not_authorized_by_reviewer(self):
        with self.assertRaises(ContractError):
            self.review(self.start(), cleared_actions=['unknown'], next_action='unknown')

    def test_partial_review_cannot_complete_goal(self):
        with self.assertRaises(ContractError):
            self.review(self.start(), review_status='PARTIAL', goal_complete=True)

    def test_complete_review_cannot_skip_required_work(self):
        with self.assertRaises(ContractError):
            self.review(self.start(), goal_complete=True, verified_criteria=['output verified'], evidence_refs=['evidence.txt'])

    def test_goal_completes_only_after_work_and_current_evidence(self):
        self.review(self.start())
        request = self.controller.next()['request']
        self.controller.finish(request['token'], {'status': 'done'})
        review = self.controller.next()['request']
        self.review(review, cleared_actions=[], next_action=None, goal_complete=True,
                    verified_criteria=['output verified'], evidence_refs=['evidence.txt'])
        self.assertEqual(self.controller.next()['status'], 'COMPLETE')
        (self.root / 'evidence.txt').write_text('new evidence')
        self.assertEqual(self.controller.next()['request']['kind'], 'review')

    def test_uncertain_action_is_not_replayed(self):
        self.review(self.start())
        request = self.controller.next()['request']
        self.controller.finish(request['token'], {'status': 'uncertain'})
        self.review(self.controller.next()['request'])
        self.assertEqual(self.controller.next()['status'], 'WAITING')
        self.controller.reconcile('build', 'done', 'Observed actual output and execution receipt')
        self.assertEqual(self.controller.status()['actions']['build'], 'done')

    def test_budget_stops_dispatch(self):
        self.config['max_dispatches'] = 1
        self.review(self.start())
        self.assertEqual(self.controller.next()['status'], 'BUDGET_EXHAUSTED')

    def test_repeated_repair_candidate_stops_attempt(self):
        self.config['actions'][0].update(kind='repair', attempt_id='A', attempt_authorization_ref='owner instruction')
        request = self.start()
        self.review(request, decision='REPAIR', findings=[{'id': 'f1', 'evidence': 'evidence.txt', 'reason': 'Mismatch'}])
        action = self.controller.next()['request']
        self.controller.finish(action['token'], {'status': 'done'})
        self.assertTrue(self.controller.status()['attempts']['A']['stopped'])

    def test_three_cycle_budget_survives_restart(self):
        self.config["max_repair_cycles"] = 3
        self.config['actions'] = [{'id': f'fix{i}', 'kind': 'repair', 'instruction': 'Fix evidence',
                                  'attempt_id': 'A', 'attempt_authorization_ref': 'owner instruction'} for i in range(4)]
        request = self.start()
        for i in range(3):
            self.review(request, decision='REPAIR', cleared_actions=[f'fix{i}'], next_action=f'fix{i}',
                        findings=[{'id': f'f{i}', 'evidence': 'evidence.txt', 'reason': f'mismatch {i}'}])
            action = self.controller.next()['request']
            (self.root / 'evidence.txt').write_text(f'candidate {i}')
            self.controller.finish(action['token'], {'status': 'done'})
            self.controller = Controller(self.root / 'state')
            request = self.controller.next()['request']
        self.review(request, decision='REPAIR', cleared_actions=['fix3'], next_action='fix3',
                    findings=[{'id': 'f3', 'evidence': 'evidence.txt', 'reason': 'different mismatch'}])
        self.assertEqual(self.controller.next()['status'], 'WAITING')
        self.assertEqual(self.controller.status()['attempts']['A']['cycles'], 3)

    def test_findings_cannot_be_silently_dropped(self):
        self.review(self.start(), findings=[{'id': 'f1', 'evidence': 'evidence.txt', 'reason': 'Unresolved'}])
        action = self.controller.next()['request']
        self.controller.finish(action['token'], {'status': 'done'})
        with self.assertRaises(ContractError):
            self.review(self.controller.next()['request'], cleared_actions=[], next_action=None,
                        goal_complete=True, verified_criteria=['output verified'], evidence_refs=['evidence.txt'])

    def test_tampered_journal_rejected(self):
        self.start()
        path = self.root / 'state/journal/00000001.json'
        entry = read_json(path)
        entry['state']['control'] = 'stopped'
        path.write_text(json.dumps(entry))
        with self.assertRaises(ContractError):
            self.controller.status()

    def test_process_lock_prevents_second_writer(self):
        self.start()
        ctx = multiprocessing.get_context('spawn')
        queue = ctx.Queue()
        with self.controller.locked():
            process = ctx.Process(target=contend, args=(str(self.root / 'state'), queue))
            process.start()
            self.assertEqual(queue.get(timeout=10), 'locked')
            process.join(10)
        self.assertEqual(process.exitcode, 0)
        queue.close()

    def test_config_cannot_escape_evidence_root(self):
        self.config['evidence'] = ['../outside.txt']
        with self.assertRaises(ContractError):
            self.start()

    def test_dependency_cycle_rejected(self):
        self.config['actions'][0]['depends_on'] = ['build']
        with self.assertRaises(ContractError):
            self.start()

    def test_runner_executes_and_reviews_without_user_continue(self):
        reviewer = self.root / 'reviewer.py'
        reviewer.write_text('''import json,sys
r=json.load(sys.stdin)
done=r['actions']['build']=='done'
print(json.dumps({'review_status':'COMPLETE','decision':'CONTINUE','snapshot_digest':r['snapshot']['digest'],'request_digest':r['semantic_digest'],'coverage':'fixture only','cleared_actions':[] if done else ['build'],'next_action':None if done else 'build','goal_complete':done,'verified_criteria':['output verified'] if done else [],'evidence_refs':['evidence.txt']}))
''')
        self.config['reviewer_command'] = [sys.executable, str(reviewer)]
        self.config['actions'][0]['command'] = [sys.executable, '-c', "from pathlib import Path; Path('evidence.txt').write_text('done')"]
        self.controller.init(self.config)
        self.assertEqual(self.controller.run(execute=True)['status'], 'COMPLETE')
        self.assertEqual((self.root / 'evidence.txt').read_text(), 'done')
        self.assertEqual(self.controller.status()['dispatches'], 3)

    def test_malformed_reviewer_is_bounded_failure(self):
        self.config['reviewer_command'] = [sys.executable, '-c', "print('not json')"]
        self.controller.init(self.config)
        self.assertEqual(self.controller.run(execute=True)['status'], 'WAITING')
        self.assertEqual(self.controller.status()['dispatches'], 2)

    def test_missing_command_returns_pending_agent_request(self):
        self.controller.init(self.config)
        self.assertEqual(self.controller.run(execute=True)['status'], 'NEEDS_AGENT')
        self.assertEqual(self.controller.next()['status'], 'IN_FLIGHT')

    def test_command_execution_requires_explicit_switch(self):
        self.controller.init(self.config)
        with self.assertRaises(ContractError):
            self.controller.run()

    def test_repair_cannot_bypass_review(self):
        self.config['actions'][0].update(kind='repair', requires_review=False, attempt_id='A', attempt_authorization_ref='owner')
        with self.assertRaises(ContractError):
            self.start()

    def test_continue_cannot_authorize_repair(self):
        self.config['actions'][0].update(kind='repair', attempt_id='A', attempt_authorization_ref='owner')
        with self.assertRaises(ContractError):
            self.review(self.start())

    def test_repeated_finding_with_reworded_reason_stops_attempt(self):
        self.config['actions'] = [{'id': f'fix{i}', 'kind': 'repair', 'instruction': 'Fix', 'attempt_id': 'A', 'attempt_authorization_ref': 'owner'} for i in range(2)]
        request = self.start()
        self.review(request, decision='REPAIR', cleared_actions=['fix0'], next_action='fix0', findings=[{'id':'f1','evidence':'evidence.txt:1','reason':'First wording'}])
        action = self.controller.next()['request']
        (self.root / 'evidence.txt').write_text('changed candidate')
        self.controller.finish(action['token'], {'status':'done'})
        self.review(self.controller.next()['request'], decision='REPAIR', cleared_actions=['fix1'], next_action='fix1', findings=[{'id':'f1','evidence':'evidence.txt:1','reason':'Reworded'}])
        self.assertEqual(self.controller.next()['status'], 'WAITING')

    def test_check_catches_change_after_dispatch_before_execution(self):
        self.review(self.start())
        action = self.controller.next()['request']
        (self.root / 'evidence.txt').write_text('changed')
        self.assertEqual(self.controller.check(action['token'])['status'], 'STALE')

    def test_revision_preserves_repair_attempt_history(self):
        self.config['actions'][0].update(kind='repair', attempt_id='A', attempt_authorization_ref='owner')
        self.review(self.start(), decision='REPAIR')
        action = self.controller.next()['request']
        self.controller.finish(action['token'], {'status':'done'})
        before = copy.deepcopy(self.controller.status()['attempts'])
        self.controller.revise('2', 'Revised authorized goal', ['new criterion'], 'User instruction')
        self.assertEqual(self.controller.status()['attempts'], before)
        self.assertEqual(self.controller.next()['request']['goal_revision'], '2')

    def test_completion_field_requires_boolean(self):
        with self.assertRaises(ContractError):
            self.review(self.start(), goal_complete='false')

    def test_unchanged_wait_does_not_grow_journal(self):
        request = self.start()
        self.review(request, decision='HOLD_DEPENDENT_ACTION', holds={'build':'missing'}, cleared_actions=[], next_action=None)
        self.assertEqual(self.controller.next()['status'], 'WAITING')
        before = len(list((self.root/'state/journal').glob('*.json')))
        for _ in range(5):
            self.assertEqual(self.controller.next()['status'], 'WAITING')
        self.assertEqual(len(list((self.root/'state/journal').glob('*.json'))), before)

    def test_stale_result_retained_as_historical_evidence(self):
        request = self.start()
        (self.root/'evidence.txt').write_text('changed')
        result = self.review(request)
        recorded = self.controller.status()['last_result']
        self.assertEqual(recorded['result'], result)
        self.assertEqual(recorded['disposition'], 'STALE_REVIEW')

    def test_invalid_nested_reviewer_output_is_bounded_failure(self):
        self.config['reviewer_command'] = [sys.executable, '-c', "import json,sys; r=json.load(sys.stdin); print(json.dumps({'holds':[], 'review_status':'COMPLETE', 'decision':'CONTINUE','snapshot_digest':r['snapshot']['digest'],'request_digest':r['semantic_digest']}))"]
        self.controller.init(self.config)
        self.assertEqual(self.controller.run(execute=True)['status'], 'WAITING')
        self.assertEqual(self.controller.status()['review_failures'], 2)

    def test_old_review_cannot_clear_revised_goal(self):
        request = self.start()
        old = self.review(request)
        self.controller.revise('2', 'Different objective', ['different criterion'], 'User revised goal')
        fresh = self.controller.next()['request']
        self.assertEqual(request['snapshot'], fresh['snapshot'])
        self.assertNotEqual(request['semantic_digest'], fresh['semantic_digest'])
        with self.assertRaisesRegex(ContractError, 'complete request'):
            self.controller.finish(fresh['token'], old)
        self.assertEqual(self.controller.status()['clearances'], {})

    def test_review_must_supply_full_request_binding(self):
        request = self.start()
        result = {'review_status':'COMPLETE','decision':'CONTINUE', 'snapshot_digest':request['snapshot']['digest'], 'coverage':'files only','cleared_actions':['build'],'next_action':'build'}
        with self.assertRaisesRegex(ContractError, 'complete request'):
            self.controller.finish(request['token'], result)

    def test_paused_unstarted_repair_does_not_consume_attempt(self):
        self.config['actions'][0].update(kind='repair', attempt_id='A', attempt_authorization_ref='owner')
        self.review(self.start(), decision='REPAIR', findings=[{'id':'f1','evidence':'evidence.txt:1','reason':'Mismatch'}])
        repair = self.controller.next()['request']
        self.controller.control('paused', 'User pause before execution')
        self.controller.finish(repair['token'], {'status':'not_started'})
        attempt = self.controller.status()['attempts']['A']
        self.assertEqual(attempt['cycles'], 0)
        self.assertFalse(attempt['stopped'])
        self.assertEqual(attempt['candidates'], [])
        self.assertEqual(attempt['finding_sets'], [])
        self.controller.control('active', 'User resume')
        self.review(self.controller.next()['request'], decision='REPAIR')
        self.assertEqual(self.controller.next()['request']['kind'], 'repair')

    def test_hold_on_completed_premise_blocks_transitive_dependents(self):
        self.config['actions'].extend([
            {'id':'middle','instruction':'Middle task','depends_on':['build']},
            {'id':'last','instruction':'Last task','depends_on':['middle']},
            {'id':'independent','instruction':'Independent task'}])
        self.review(self.start())
        first = self.controller.next()['request']
        self.controller.finish(first['token'], {'status':'done'})
        self.review(self.controller.next()['request'], cleared_actions=['middle'], next_action='middle')
        middle = self.controller.next()['request']
        self.controller.finish(middle['token'], {'status':'done'})
        self.review(self.controller.next()['request'], holds={'build':'New counterevidence'}, cleared_actions=['last','independent'], next_action='last')
        chosen = self.controller.next()['request']
        self.assertEqual(chosen['action_id'], 'independent')
        self.controller.finish(chosen['token'], {'status':'done'})
        self.review(self.controller.next()['request'], cleared_actions=['last'], next_action='last')
        self.assertEqual(self.controller.next()['status'], 'WAITING')
        (self.root/'evidence.txt').write_text('resolved premise')
        self.review(self.controller.next()['request'], release_holds={'build':'New evidence resolves original premise'}, cleared_actions=['build','last'], next_action='last')
        self.assertEqual(self.controller.next()['request']['action_id'], 'last')

if __name__ == '__main__':
    unittest.main()