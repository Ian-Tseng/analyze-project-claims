"""Synthetic acceptance checks for exact-authorized append-only plan changes."""
import copy
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "analyze-project-claims" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from long_running_controller import Controller, ContractError, digest


class PlanRevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'evidence.txt').write_text('fixed evidence')
        self.c = Controller(self.root/'state')
        self.config = {'goal_id':'G', 'goal_revision':'1', 'objective':'Local fixture',
            'authorization_ref':'original owner instruction', 'project_root':str(self.root),
            'evidence':['evidence.txt'], 'success_criteria':['output checked'],
            'actions':[{'id':'base','instruction':'Existing local work'},
                       {'id':'independent','instruction':'Unrelated local work'}]}

    def start(self):
        self.c.init(self.config)
        self.review(cleared_actions=['base','independent'], next_action='base')

    def review(self, **fields):
        request = self.c.next()['request']
        self.assertEqual(request['kind'], 'review')
        result = {'review_status':'COMPLETE','decision':'CONTINUE',
                  'snapshot_digest':request['snapshot']['digest'],
                  'request_digest':request['semantic_digest'], 'coverage':'Synthetic fixture',
                  'cleared_actions':[], 'next_action':None}
        result.update(fields)
        self.c.finish(request['token'], result)
        return result

    def patch(self, **fields):
        value = {'revision_id':'P1','base_config_digest':self.c.status()['config_digest'],
                 'add_actions':[{'id':'new','instruction':'Additional scoped work','depends_on':['base']}],
                 'dependencies':{}}
        value.update(fields)
        return value

    def approve(self, patch, scope='existing', reference=None):
        return self.c.authorize_plan(patch, scope, reference or self.config['authorization_ref'],
                                     'Required to finish the already authorized local fixture')

    def test_add_action_preserves_unaffected_clearances_and_history(self):
        self.start()
        patch = self.patch()
        self.approve(patch)
        before = self.c.status()
        result = self.c.revise_plan(patch)
        after = Controller(self.c.root).status()
        self.assertEqual(result['status'], 'PLAN_REVISED')
        self.assertEqual(result['affected_actions'], ['new'])
        self.assertEqual(after['clearances'], before['clearances'])
        self.assertEqual(after['actions'], {**before['actions'],'new':'pending'})
        for key in ('findings','holds','attempts','dispatches','receipts','last_review'):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(after['config']['authorization_ref'], self.config['authorization_ref'])
        self.assertNotEqual(after['config_digest'], before['config_digest'])
        self.assertTrue(after['review_due'])

    def unchanged_rejection(self, operation, message):
        before = {p.name:p.read_bytes() for p in (self.c.root/'journal').glob('*.json')}
        with self.assertRaisesRegex(ContractError, message):
            operation()
        self.assertEqual(before, {p.name:p.read_bytes() for p in (self.c.root/'journal').glob('*.json')})

    def test_unapproved_or_modified_patch_cannot_apply(self):
        self.start()
        patch = self.patch()
        self.unchanged_rejection(lambda:self.c.revise_plan(patch), 'authorization')
        self.approve(patch)
        altered = copy.deepcopy(patch)
        altered['add_actions'][0]['instruction'] = 'Different side effect'
        self.unchanged_rejection(lambda:self.c.revise_plan(altered), 'authorization')

    def test_stale_grant_and_duplicate_revision_are_rejected(self):
        self.start()
        stale = self.patch()
        self.approve(stale)
        self.c.revise('2','New goal text',['Rechecked'],'Owner goal change')
        self.unchanged_rejection(lambda:self.c.revise_plan(stale), 'Stale')
        fresh = self.patch()
        self.approve(fresh)
        self.c.revise_plan(fresh)
        changed = self.patch(add_actions=[{'id':'another','instruction':'More'}])
        self.unchanged_rejection(lambda:self.approve(changed), 'already used')

    def test_exact_authorization_and_revision_retries_do_not_append_events(self):
        self.start()
        patch = self.patch()
        self.approve(patch)
        count = len(list((self.c.root/'journal').glob('*.json')))
        self.assertEqual(self.approve(patch)['status'], 'ALREADY_AUTHORIZED')
        self.assertEqual(len(list((self.c.root/'journal').glob('*.json'))), count)
        self.c.revise_plan(patch)
        count += 1
        self.assertEqual(self.c.revise_plan(patch)['status'], 'ALREADY_REVISED')
        self.assertEqual(len(list((self.c.root/'journal').glob('*.json'))), count)

    def test_cycle_and_unknown_dependency_rejected_before_grant(self):
        self.start()
        for patch, message in [
            (self.patch(dependencies={'base':['new']}), 'cycle'),
            (self.patch(dependencies={'base':['missing']}), 'Unknown'),
            (self.patch(dependencies={'base':'independent'}), 'dependency list')]:
            self.unchanged_rejection(lambda:self.approve(patch), message)

    def test_cannot_replace_remove_or_change_existing_action_or_budgets(self):
        self.start()
        self.unchanged_rejection(lambda:self.approve(self.patch(add_actions=[{'id':'base','instruction':'Replacement'}])), 'reuse')
        for field,value in [('remove_actions',['base']),('max_dispatches',10000),('objective','Changed')]:
            self.unchanged_rejection(lambda:self.approve(self.patch(**{field:value})), 'fields')

    def test_dependency_change_invalidates_only_changed_and_transitive_dependents(self):
        self.config['actions'] += [{'id':'child','instruction':'Child','depends_on':['base']},
                                   {'id':'last','instruction':'Last','depends_on':['child']}]
        self.c.init(self.config)
        self.review(cleared_actions=['base','child','last','independent'], next_action='base')
        patch = self.patch(add_actions=[], dependencies={'base':['independent']})
        self.approve(patch)
        result = self.c.revise_plan(patch)
        self.assertEqual(result['affected_actions'], ['base','child','last'])
        self.assertEqual(result['invalidated_clearances'], ['base','child','last'])
        self.assertEqual(set(self.c.status()['clearances']), {'independent'})

    def test_evidence_drift_invalidates_all_clearances(self):
        self.start()
        patch = self.patch()
        self.approve(patch)
        (self.root/'evidence.txt').write_text('changed')
        result = self.c.revise_plan(patch)
        self.assertTrue(result['evidence_changed'])
        self.assertEqual(self.c.status()['clearances'], {})

    def test_in_flight_review_and_work_tokens_remain_unchanged(self):
        self.start()
        patch = self.patch()
        self.approve(patch)
        request = self.c.next()['request']
        self.unchanged_rejection(lambda:self.c.revise_plan(patch), 'in-flight')
        self.assertEqual(self.c.status()['pending'], request)
        self.c.finish(request['token'], {'status':'not_started'})
        review = self.c.next()['request']
        self.unchanged_rejection(lambda:self.approve(patch), 'in-flight')
        self.assertEqual(self.c.status()['pending'], review)

    def test_goal_completion_reopens_and_pause_is_preserved(self):
        self.start()
        for key in ('base','independent'):
            request = self.c.next()['request']
            self.assertEqual(request['action_id'], key)
            self.c.finish(request['token'], {'status':'done'})
            if key == 'base':
                self.review(cleared_actions=['independent'], next_action='independent')
        self.review(goal_complete=True, verified_criteria=['output checked'], evidence_refs=['evidence.txt'])
        self.assertTrue(self.c.status()['complete'])
        self.c.control('paused','User pause')
        patch = self.patch()
        self.approve(patch)
        self.c.revise_plan(patch)
        self.assertFalse(self.c.status()['complete'])
        self.assertEqual(self.c.next()['status'], 'PAUSED')
        self.assertEqual(self.c.status()['actions']['base'], 'done')

    def test_stopped_goal_cannot_authorize_or_apply(self):
        self.start()
        patch = self.patch()
        self.approve(patch)
        self.c.control('stopped','User stop')
        self.unchanged_rejection(lambda:self.c.revise_plan(patch), 'Stopped')
        self.unchanged_rejection(lambda:self.approve(patch), 'Stopped')

    def test_scope_authority_must_match_and_remains_recorded(self):
        self.start()
        patch = self.patch()
        self.unchanged_rejection(lambda:self.approve(patch,reference='invented'), 'Scope')
        self.unchanged_rejection(lambda:self.approve(patch,scope='expanded'), 'Scope')
        self.approve(patch,scope='expanded',reference='New owner instruction')
        self.c.revise_plan(patch)
        self.assertEqual(self.c.status()['plan_revisions']['P1']['authorization']['scope'], 'expanded')
        self.assertEqual(self.c.status()['config']['authorization_ref'], self.config['authorization_ref'])

    def test_spent_repair_attempt_holds_and_findings_survive_addition(self):
        self.config['actions'][0].update(kind='repair',attempt_id='A',attempt_authorization_ref='Repair A authority')
        self.c.init(self.config)
        self.review(decision='REPAIR',cleared_actions=['base'],next_action='base',
                    holds={'independent':'Blocked by finding'},
                    findings=[{'id':'F','evidence':'evidence.txt:1','reason':'Synthetic mismatch'}])
        request = self.c.next()['request']
        self.c.finish(request['token'], {'status':'done'})
        before = self.c.status()
        self.assertEqual(before['attempts']['A']['cycles'], 1)
        self.assertTrue(before['attempts']['A']['stopped'])
        patch = self.patch(add_actions=[{'id':'repair2','kind':'repair','instruction':'Next repair',
                                        'attempt_id':'A','attempt_authorization_ref':'Repair A authority'}])
        self.approve(patch)
        self.c.revise_plan(patch)
        after = self.c.status()
        for key in ('holds','findings','attempts','dispatches','receipts'):
            self.assertEqual(after[key], before[key], key)
        self.review(decision='REPAIR',cleared_actions=['repair2'],next_action='repair2')
        self.assertEqual(self.c.next()['status'],'WAITING')

    def test_new_repair_attempt_requires_separate_expanded_authority(self):
        self.config['actions'][0].update(kind='repair',attempt_id='A',attempt_authorization_ref='Repair A authority')
        self.c.init(self.config)
        patch = self.patch(add_actions=[{'id':'repair2','kind':'repair','instruction':'New attempt',
                                        'attempt_id':'B','attempt_authorization_ref':'Repair A authority'}])
        self.unchanged_rejection(lambda:self.approve(patch), 'expanded authority')
        self.unchanged_rejection(lambda:self.approve(patch,scope='expanded',reference='New repair instruction'), 'expanded authority')
        patch['add_actions'][0]['attempt_authorization_ref'] = 'New repair instruction'
        self.approve(patch,scope='expanded',reference='New repair instruction')
        self.c.revise_plan(patch)
        self.assertEqual(self.c.status()['actions']['repair2'],'pending')

    def test_existing_attempt_authority_cannot_be_replaced(self):
        self.config['actions'][0].update(kind='repair',attempt_id='A',attempt_authorization_ref='Repair A authority')
        self.c.init(self.config)
        patch = self.patch(add_actions=[{'id':'repair2','kind':'repair','instruction':'Same attempt',
                                        'attempt_id':'A','attempt_authorization_ref':'Different authority'}])
        self.unchanged_rejection(lambda:self.approve(patch,scope='expanded',reference='Different authority'), 'preserved')

    def test_reconciled_executed_action_cannot_be_rewired(self):
        self.start()
        request = self.c.next()['request']
        self.c.finish(request['token'], {'status':'failed'})
        self.c.reconcile('base','pending','Observed no remaining side effect; retry authorized')
        patch = self.patch(add_actions=[], dependencies={'base':['independent']})
        self.unchanged_rejection(lambda:self.approve(patch), 'executed')

    def test_not_started_action_can_be_rewired(self):
        self.start()
        request = self.c.next()['request']
        self.c.finish(request['token'], {'status':'not_started'})
        patch = self.patch(add_actions=[], dependencies={'base':['independent']})
        self.approve(patch)
        self.c.revise_plan(patch)
        self.assertEqual(self.c.status()['config']['actions'][0]['depends_on'],['independent'])

    def test_old_review_cannot_clear_revised_plan(self):
        self.c.init(self.config)
        result = self.review(cleared_actions=['base'],next_action='base')
        patch = self.patch()
        self.approve(patch)
        self.c.revise_plan(patch)
        request = self.c.next()['request']
        self.unchanged_rejection(lambda:self.c.finish(request['token'],result), 'complete request')

    def test_revision_does_not_replenish_dispatch_or_review_budgets(self):
        self.config['max_dispatches'] = 2
        self.c.init(self.config)
        for _ in range(2):
            self.review(review_status='FAILED')
        patch = self.patch()
        self.approve(patch)
        self.c.revise_plan(patch)
        self.assertEqual(self.c.status()['review_failures'],2)
        self.assertEqual(self.c.status()['dispatches'],2)
        self.assertEqual(self.c.next()['status'],'BUDGET_EXHAUSTED')

    def test_cli_authorize_and_apply_in_separate_processes(self):
        self.start()
        patch = self.patch()
        proposal = self.root/'patch.json'
        proposal.write_text(json.dumps(patch))
        argv = [sys.executable,str(SCRIPTS/'long_running_controller.py'),'--state',str(self.c.root)]
        for tail in [ ['authorize-plan','--proposal',str(proposal),'--scope','existing',
                       '--authority',self.config['authorization_ref'],'--rationale','Scoped local addition'],
                      ['revise-plan','--proposal',str(proposal)] ]:
            result = subprocess.run(argv+tail,capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(json.loads(result.stdout)['status'],('PLAN_AUTHORIZED','PLAN_REVISED'))
        self.assertEqual(self.c.status()['actions']['new'],'pending')

    def test_added_action_runs_and_completes_without_replaying_old_work(self):
        self.start()
        for key in ('base','independent'):
            request = self.c.next()['request']
            self.assertEqual(request['action_id'],key)
            self.c.finish(request['token'],{'status':'done'})
            if key == 'base':
                self.review(cleared_actions=['independent'],next_action='independent')
        patch = self.patch()
        self.approve(patch)
        self.c.revise_plan(patch)
        self.review(cleared_actions=['new'],next_action='new')
        request = self.c.next()['request']
        self.assertEqual(request['action_id'],'new')
        self.c.finish(request['token'],{'status':'done'})
        self.review(goal_complete=True,verified_criteria=['output checked'],evidence_refs=['evidence.txt'])
        self.assertEqual(self.c.next()['status'],'COMPLETE')
        dispatched = [json.loads(p.read_text())['state']['pending']
                      for p in sorted((self.c.root/'journal').glob('*.json'))
                      if json.loads(p.read_text())['kind']=='dispatched']
        self.assertEqual([r['action_id'] for r in dispatched if r['kind']!='review'],['base','independent','new'])


if __name__ == '__main__':
    unittest.main()
