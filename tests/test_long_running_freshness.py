import copy
import unittest
from unittest.mock import patch
import test_long_running_subagents as fixtures
from long_running_controller import read_json

class ReportFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.SubagentModeTests();self.f.setUp()
    def tearDown(self): self.f.tearDown()
    def reviewed(self): self.f.finish_review(self.f.start())
    def drift(self): (self.f.root/'evidence.txt').write_text('contradictory new evidence',encoding='utf-8')
    def view(self):
        _,folder=self.f.report_files()
        return read_json(folder/'claims.json'),(folder/'summary.md').read_text(encoding='utf-8')
    def assert_stale(self):
        s=self.f.controller.status();p,m=self.view()
        self.assertEqual(s['freshness']['status'],'STALE')
        self.assertEqual(p['freshness'],s['freshness'])
        self.assertEqual(set(s['freshness']['review_required_claims']),{'C1','C2'})
        self.assertNotIn('Freshness: Reviewed',m)
        self.assertIn('REVIEW REQUIRED',m)
        self.assertEqual(s['working_claims']['C1']['status'],'supported')
        return s
    def test_idle_source_drift_preserves_history_and_requests_review(self):
        self.reviewed();_,old=self.f.report_files();before=(old/'summary.md').read_bytes()
        self.drift();self.assert_stale()
        self.assertEqual((old/'summary.md').read_bytes(),before)
        self.assertEqual(self.f.controller.next()['request']['role'],'claims_reviewer')
    def test_pending_stale_check_updates_report_without_replacing_token(self):
        q=self.f.dispatch_worker();before=self.f.controller.status();self.drift()
        self.assertEqual(self.f.controller.check(q['token'])['status'],'STALE')
        p,m=self.view();self.assertEqual(p['freshness']['status'],'STALE')
        after=self.assert_stale()
        for key in ['pending','dispatches','attempts','control']:self.assertEqual(before[key],after[key])
        self.assertEqual(self.f.controller.next()['request']['token'],q['token'])
    def test_reviewer_contract_drift_is_visible(self):
        self.reviewed();self.f.skill.write_text('changed instructions',encoding='utf-8')
        s=self.assert_stale();self.assertTrue(s['freshness']['evidence_current']);self.assertFalse(s['freshness']['contract_current'])
    def test_paused_status_detects_drift_without_resuming(self):
        self.reviewed();self.f.controller.control('paused','test pause');self.drift()
        self.assertEqual(self.assert_stale()['control'],'paused')
        self.assertEqual(self.f.controller.next()['status'],'PAUSED')
    def test_completed_state_is_historical_when_source_drifts(self):
        q=self.f.dispatch_worker();self.f.controller.finish(q['token'],{'status':'done'})
        q=self.f.controller.next()['request'];self.f.finish_review(q,cleared_actions=[],next_action=None,goal_complete=True,verified_criteria=['output verified'],evidence_refs=['evidence.txt'])
        self.drift();s=self.assert_stale();self.assertTrue(s['complete'])
        self.assertFalse(s['freshness']['completion_current'])
    def test_unchanged_read_is_current_and_creates_no_journal_event(self):
        self.reviewed();journal=self.f.controller.root/'journal';before={p.name:p.read_bytes() for p in journal.glob('*.json')}
        s=self.f.controller.status();self.assertEqual(s['freshness']['status'],'CURRENT')
        self.assertEqual(s['freshness']['review_required_claims'],[])
        self.assertEqual(before,{p.name:p.read_bytes() for p in journal.glob('*.json')})
    def test_snapshot_failure_is_unknown_and_does_not_block_pause(self):
        self.reviewed()
        with patch('long_running_controller.snapshot',side_effect=OSError('unreadable fixture')):
            s=self.f.controller.status();self.assertEqual(s['freshness']['status'],'UNKNOWN')
            self.assertEqual(set(s['freshness']['review_required_claims']),{'C1','C2'})
            self.assertEqual(self.f.controller.control('paused','pause despite unavailable evidence')['status'],'paused')

if __name__=='__main__': unittest.main()
