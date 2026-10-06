"""End-to-end coordinator behavior with a deterministic, explicitly synthetic host."""
import copy
import sys
import time
import unittest
from unittest.mock import patch
from pathlib import Path
import test_agent_pool as base
from native_agent_coordinator import NativeCoordinator
from long_running_controller import Controller, ContractError


class Host:
    def __init__(self, fixture, close_supported=False):
        self.fixture = fixture
        self.close_supported = close_supported
        self.agents = {}
        self.results = {}
        self.spawns = self.starts = self.closes = 0
        self.lose_spawn = self.lose_start = self.lose_close = False
        self.run_results = True
        self.quiescent = True
        self.fake_close = False

    def observe(self):
        return {'observed_at': time.time(), 'source_ref': 'synthetic-host-observation',
                'close_supported': self.close_supported,
                'agents': [dict(agent_id=k, status=v['status'], execution_quiescent=self.quiescent)
                           for k, v in self.agents.items()]}

    def find(self, token):
        return [k for k, v in self.agents.items() if v['token'] == token]

    def spawn(self, request):
        self.spawns += 1
        agent = 'synthetic-agent-' + str(self.spawns)
        self.agents[agent] = {'token': request['token'], 'status': 'idle'}
        if self.lose_spawn:
            self.lose_spawn = False
            raise TimeoutError('synthetic lost spawn response')
        return agent

    def start(self, agent, request):
        self.starts += 1
        self.agents[agent].update(token=request['token'], status='running')
        if self.run_results:
            if request['role'] == 'worker':
                (self.fixture.root / (request['action_id'] + '.txt')).write_text('observed ' + request['action_id'])
                result = {'status': 'done'}
            else:
                final = request['review_scope'] == 'global' and all(v == 'done' for v in request['actions'].values())
                extra = dict(goal_complete=True, verified_criteria=['all outputs reviewed'],
                             evidence_refs=['a.txt', 'b.txt', 'c.txt']) if final else {}
                result = self.fixture.review_result(request, **extra)
            self.results[(agent, request['token'])] = result
            self.agents[agent]['status'] = 'completed'
        if self.lose_start:
            self.lose_start = False
            raise TimeoutError('synthetic lost start response')
        return 'synthetic-start-ack-' + str(self.starts)

    def result(self, agent, token):
        result = self.results.get((agent, token))
        return None if result is None else {'agent_id': agent, 'token': token,
            'result': copy.deepcopy(result), 'source_ref': 'synthetic-result'}

    def close(self, agent):
        self.closes += 1
        if not self.fake_close:
            self.agents[agent]['status'] = 'closed'
        if self.lose_close:
            self.lose_close = False
            raise TimeoutError('synthetic lost close response')
        return {'source_ref': 'synthetic-close-ack', 'closed': True}


class NativeCoordinatorTests(unittest.TestCase):
    setUp = base.AgentPoolTests.setUp
    tearDown = base.AgentPoolTests.tearDown
    action = base.AgentPoolTests.action
    review_result = base.AgentPoolTests.review_result

    def setup_run(self, close=False):
        self.config['agent_pool']['max_workers'] = 1
        self.controller.init(self.config)
        self.host = Host(self, close)
        self.coordinator = NativeCoordinator(self.controller, self.host)

    def run_to_end(self):
        for _ in range(30):
            result = self.coordinator.tick()
            if result['status'] == 'COMPLETE':
                return result
        self.fail('Coordinator did not complete: ' + str(result))

    def test_complete_journey_reuses_two_identities_without_close(self):
        self.setup_run()
        result = self.run_to_end()
        self.assertEqual(self.host.spawns, 2)
        self.assertEqual(self.host.starts, 8)  # initial + 3 workers + 3 unit reviews + final
        self.assertEqual(self.host.closes, 0)
        self.assertEqual({a['decision'] for a in result['agents']}, {'CLOSE_UNAVAILABLE'})
        self.assertFalse(result['resources_released'])
        state = self.controller.status()
        self.assertTrue(state['complete'])
        self.assertFalse(state['claim_dirty'])
        self.assertEqual(len(state['receipts']), 8)

    def test_complete_journey_closes_and_verifies_both_agents(self):
        self.setup_run(close=True)
        result = self.run_to_end()
        self.assertEqual(self.host.spawns, 2)
        self.assertEqual(self.host.closes, 2)
        self.assertTrue(result['resources_released'])
        self.assertEqual({a['decision'] for a in result['agents']}, {'ALREADY_CLOSED'})
        self.coordinator.tick()
        self.assertEqual(self.host.closes, 2)

    def test_restart_reuses_existing_identity_without_replaying(self):
        self.setup_run()
        self.coordinator.tick()
        self.coordinator = NativeCoordinator(Controller(self.root/'state'), self.host)
        self.run_to_end()
        self.assertEqual(self.host.spawns, 2)
        self.assertEqual(self.host.starts, 8)

    def test_lost_spawn_response_recovers_identity(self):
        self.setup_run()
        self.host.lose_spawn = True
        self.assertEqual(self.coordinator.tick()['status'], 'RECOVER_SPAWN')
        self.run_to_end()
        self.assertEqual(self.host.spawns, 2)
        self.assertEqual(self.host.starts, 8)

    def test_lost_start_response_uses_result_without_resending(self):
        self.setup_run()
        self.host.lose_start = True
        self.assertEqual(self.coordinator.tick()['status'], 'RECOVER_START')
        self.run_to_end()
        self.assertEqual(self.host.starts, 8)

    def test_uncertain_start_with_no_result_never_replays(self):
        self.setup_run()
        self.host.run_results = False
        self.host.lose_start = True
        self.coordinator.tick()
        for _ in range(3):
            self.coordinator.tick()
        self.assertEqual(self.host.starts, 1)
        self.assertEqual(self.host.spawns, 1)

    def test_nonquiescent_result_is_not_finished(self):
        self.setup_run()
        self.coordinator.tick()
        self.host.quiescent = False
        self.coordinator.tick()
        self.assertEqual(len(self.controller.status()['receipts']), 0)
        self.assertEqual(self.host.starts, 1)

    def test_pause_harvests_result_but_starts_nothing(self):
        self.setup_run()
        self.coordinator.tick()
        self.controller.control('paused', 'user fixture pause')
        result = self.coordinator.tick()
        self.assertEqual(result['status'], 'PAUSED')
        self.assertEqual(len(self.controller.status()['receipts']), 1)
        self.assertEqual(self.host.starts, 1)

    def test_mismatched_result_is_rejected(self):
        self.setup_run()
        self.coordinator.tick()
        original = self.host.result
        def mismatch(agent, token):
            value = original(agent, token)
            value['token'] = 'another-token'
            return value
        self.host.result = mismatch
        with self.assertRaises(ContractError):
            self.coordinator.tick()
        self.assertFalse(self.controller.status()['receipts'])

    def test_close_ack_without_observed_closure_is_not_success(self):
        self.setup_run(close=True)
        self.host.fake_close = True
        result = self.run_to_end()
        self.assertFalse(result['resources_released'])
        self.assertEqual(self.host.closes, 2)
        self.coordinator.tick()
        self.assertEqual(self.host.closes, 2)

    def test_lost_close_response_recovers_observed_closure(self):
        self.setup_run(close=True)
        self.host.lose_close = True
        result = self.run_to_end()
        result = self.coordinator.tick()
        self.assertTrue(result['resources_released'])
        self.assertEqual(self.host.closes, 2)

    def test_unrelated_agent_is_never_closed_or_reused(self):
        self.setup_run(close=True)
        self.host.agents['unrelated'] = {'token': 'other', 'status': 'completed'}
        self.run_to_end()
        self.assertEqual(self.host.agents['unrelated']['status'], 'completed')
        self.assertEqual(self.host.spawns, 2)
        self.assertEqual(self.host.closes, 2)

    def test_stale_observation_is_rejected(self):
        self.setup_run()
        original = self.host.observe
        def stale():
            value = original(); value['observed_at'] -= 61; return value
        self.host.observe = stale
        with self.assertRaises(ContractError):
            self.coordinator.tick()
        self.assertEqual(self.host.spawns, 0)

    def test_uncertain_spawn_is_not_bypassed_by_a_reusable_agent(self):
        self.setup_run()
        self.coordinator.tick()
        self.coordinator.tick()
        # Both the initial reviewer and first worker now completed in the host.
        self.coordinator._harvest(self.coordinator._observe())
        request = self.controller.next(dispatch_id='manual-review')['request']
        self.controller.spawn_attempt(request['token'])
        starts = self.host.starts
        outcome = self.coordinator._assign(request)
        self.assertEqual(outcome['status'], 'RECOVER_SPAWN')
        self.assertEqual(self.host.starts, starts)
        self.assertNotIn(request['token'], self.controller.status()['delegations'])

    def test_bounded_runner_stops_without_busy_polling(self):
        self.setup_run()
        self.host.run_results = False
        result = self.coordinator.run(max_ticks=10)
        self.assertIn(result['status'], ('WAITING', 'POOL_FULL'))
        self.assertEqual(self.host.starts, 1)

    def test_missing_agent_never_counts_as_released(self):
        self.setup_run(close=True)
        self.host.fake_close = True
        self.run_to_end()
        self.host.agents.clear()
        result = self.coordinator.tick()
        self.assertFalse(result['resources_released'])
        self.assertEqual(self.host.closes, 2)

    def test_public_cli_executes_explicit_provider_to_verified_cleanup(self):
        import os
        import json
        import subprocess
        self.setup_run(close=True)
        provider = self.root/'fixture_provider.py'
        provider.write_text("from pathlib import Path\nfrom test_agent_pool import AgentPoolTests\nfrom test_native_agent_coordinator import Host\ndef create_host(controller):\n    fixture = AgentPoolTests()\n    fixture.root = Path(controller.status()['config']['project_root'])\n    return Host(fixture, close_supported=True)\n")
        env = dict(os.environ)
        env['PYTHONPATH'] = os.pathsep.join([str(self.root), str(Path(__file__).parent)])
        process = subprocess.run([sys.executable, '-B', str(base.SCRIPTS/'native_agent_coordinator.py'),
            '--state', str(self.root/'state'), '--adapter', 'fixture_provider:create_host', '--max-ticks', '20'],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=45,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertTrue(result['resources_released'])
        state = self.controller.status()
        self.assertEqual(len(state['receipts']), 8)
        self.assertEqual(len({b['agent_id'] for b in state['delegations'].values()}), 2)

    def test_coordinator_code_is_bound_to_reviewer_contract(self):
        self.setup_run()
        paths = self.controller.status()['reviewer_contract']['files']
        self.assertIn(str((base.SCRIPTS/'native_agent_coordinator.py').resolve()), paths)


class CoordinatorRecoveryTests(unittest.TestCase):
    setUp = base.AgentPoolTests.setUp
    tearDown = base.AgentPoolTests.tearDown
    action = base.AgentPoolTests.action
    review_result = base.AgentPoolTests.review_result
    start = base.AgentPoolTests.start
    next = base.AgentPoolTests.next
    finish_worker = base.AgentPoolTests.finish_worker
    finish_review = base.AgentPoolTests.finish_review

    def test_durable_result_replayed_after_finish_crash(self):
        self.config['agent_pool']['max_workers'] = 1
        self.controller.init(self.config)
        host = Host(self)
        coordinator = NativeCoordinator(self.controller, host)
        coordinator.tick()
        token = next(iter(coordinator._state()['pool_pending']))
        with patch.object(self.controller, 'finish', side_effect=RuntimeError('injected crash after durable envelope')):
            with self.assertRaises(RuntimeError):
                coordinator.tick()
        self.assertIn(token, coordinator._state()['native_lifecycle']['results'])
        host.results.clear()  # Host no longer retrieves it; durable local copy exists.
        recovered = NativeCoordinator(Controller(self.root / 'state'), host)
        outcome = recovered.tick()
        self.assertIn(token, recovered._state()['receipts'], outcome['status'])
        self.assertEqual(host.starts, 2)

    def test_surplus_idle_worker_does_not_starve_reviewer(self):
        self.start()
        a = self.next()['request']
        self.finish_worker(a)
        review = self.next()['request']
        self.finish_review(review)
        b = self.next()['request']
        c = self.next()['request']
        self.controller.bind_agent(b['token'], 'worker-b')
        self.controller.bind_agent(c['token'], 'worker-c')
        host = Host(self, close_supported=True)
        state = self.controller.status()
        for token, binding in state['delegations'].items():
            host.agents[binding['agent_id']] = {'token': token, 'status': 'closed' if binding['role'] == 'claims_reviewer' else 'completed'}
        host.agents['worker-c']['status'] = 'running'
        (self.root / (b['action_id'] + '.txt')).write_text('observed ' + b['action_id'])
        host.results[('worker-b', b['token'])] = {'status': 'done'}
        coordinator = NativeCoordinator(self.controller, host)
        for request in (b, c):
            agent = 'worker-' + request['action_id']
            coordinator._record('deliveries', request['token'], {'agent_id': agent, 'token': request['token'], 'status': 'acknowledged'})
        outcome = coordinator.tick()
        self.assertEqual(outcome['status'], 'STARTED', repr(outcome))
        self.assertEqual(host.closes, 1)

    def test_takeover_does_not_restart_acknowledged_running_token(self):
        self.controller.init(self.config)
        request = self.next()['request']
        self.controller.bind_agent(request['token'], 'existing-reviewer')
        self.controller.start_agent(request['token'], 'existing-reviewer', 'actual-previous-tool-start')
        host = Host(self)
        host.run_results = False
        host.agents['existing-reviewer'] = {'token': request['token'], 'status': 'running'}
        coordinator = NativeCoordinator(self.controller, host)
        outcome = coordinator.tick()
        self.assertEqual(host.starts, 0, repr(outcome))


    def test_takeover_of_unacknowledged_binding_does_not_start(self):
        self.controller.init(self.config)
        request = self.next()['request']
        self.controller.bind_agent(request['token'], 'existing-reviewer')
        host = Host(self)
        host.agents['existing-reviewer'] = {'token': request['token'], 'status': 'idle'}
        coordinator = NativeCoordinator(self.controller, host)
        self.assertEqual(coordinator.tick()['status'], 'RECOVER_START')
        self.assertEqual(host.starts, 0)

    def test_unchanged_wait_does_not_grow_journal(self):
        self.controller.init(self.config)
        host = Host(self); host.run_results = False
        coordinator = NativeCoordinator(self.controller, host)
        coordinator.tick(); coordinator.tick()
        before = len(list((self.root/'state/journal').glob('*.json')))
        coordinator.tick(); coordinator.tick()
        self.assertEqual(len(list((self.root/'state/journal').glob('*.json'))), before)

    def test_new_retrieval_reference_does_not_conflict_with_saved_result(self):
        self.controller.init(self.config)
        host = Host(self); coordinator = NativeCoordinator(self.controller, host)
        coordinator.tick()
        with patch.object(self.controller, 'finish', side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError): coordinator.tick()
        original = host.result
        def retrieve(agent, token):
            result = original(agent, token); result['source_ref'] = 'new-retrieval-reference'; return result
        host.result = retrieve
        coordinator.tick()
        self.assertEqual(len(self.controller.status()['receipts']), 1)


if __name__ == '__main__':
    unittest.main()
