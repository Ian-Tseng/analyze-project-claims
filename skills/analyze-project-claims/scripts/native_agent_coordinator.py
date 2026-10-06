"""Executable, cooperative native-host adapter for a claims agent pool.

Host methods perform real calls; this module never fabricates host capabilities.
No background scheduler is installed. Call tick() on results and recovery.
"""
from __future__ import annotations
import copy
import uuid
import agent_cleanup
from long_running_controller import Controller, require


class NativeCoordinator:
    def __init__(self, controller, host):
        self.controller = controller
        self.host = host
        # Separate process lock: never hold the controller lock across start/spawn.
        self.guard = Controller(controller.root / 'native-coordinator-lock')

    def _state(self):
        with self.controller.locked():
            return self.controller._load(sync_reports=False)[0]

    def _record(self, section, key, value):
        with self.controller.locked():
            state, seq, previous = self.controller._load(sync_reports=False)
            records = state.setdefault('native_lifecycle', {}).setdefault(section, {})
            if records.get(key) != value:
                records[key] = copy.deepcopy(value)
                self.controller._save(state, 'native_' + section, seq, previous, sync_reports=False)

    def _observe(self):
        observation = self.host.observe()
        # Use the established strict freshness, status and boolean checks.
        self.controller.agent_cleanup(observation)
        return observation

    def _harvest(self, observation):
        observed = {a['agent_id']: a for a in observation['agents']}
        state = self._state()
        for token in list(state['pool_pending']):
            binding = state['delegations'].get(token)
            if not binding:
                continue
            agent = binding['agent_id']
            item = observed.get(agent)
            if not item or item['status'] not in ('completed', 'failed', 'cancelled') or not item['execution_quiescent']:
                continue
            prior = state.get('native_lifecycle', {}).get('results', {}).get(token)
            try:
                retrieved = self.host.result(agent, token)
            except (OSError, TimeoutError):
                if prior is None:
                    raise
                retrieved = None
            if prior is not None and retrieved is not None:
                require(all(prior.get(k) == retrieved.get(k) for k in ('agent_id', 'token', 'result')),
                        'Conflicting harvested host result')
            envelope = prior if prior is not None else retrieved
            if envelope is None:
                continue
            require(isinstance(envelope, dict) and set(envelope) == {'agent_id', 'token', 'source_ref', 'result'},
                    'Invalid host result envelope')
            require(envelope['agent_id'] == agent and envelope['token'] == token, 'Host result identity mismatch')
            require(isinstance(envelope['source_ref'], str) and envelope['source_ref'].strip(), 'Record result evidence')
            require(isinstance(envelope['result'], dict), 'Host result must be an object')
            # Persist raw outcome before finishing; controller validates claims.
            if prior is None:
                self._record('harvest_observations', token, observation)
            self._record('results', token, envelope)
            self.controller.finish(token, envelope['result'])

    def _inventory(self, final=False):
        observation = self._observe()
        state = self._state()
        plan = self.controller.agent_cleanup(observation)
        observed = {a['agent_id']: a for a in observation['agents']}
        retained = {'worker': 0, 'claims_reviewer': 0}
        limits = {'worker': state['config']['agent_pool']['max_workers'], 'claims_reviewer': 1}
        def reusable(entry):
            item = observed.get(entry['agent_id'])
            return bool(item and item['status'] in ('idle', 'completed', 'failed', 'cancelled')
                        and item['execution_quiescent'] and all(t in state['receipts'] for t in entry['tokens'])
                        and not set(entry['tokens']).intersection(state['pool_pending'])
                        and entry['agent_id'] not in state.get('native_lifecycle', {}).get('closes', {}))
        # Running and held identities already occupy their role's retained slots.
        for entry in plan['agents']:
            if entry['decision'] != 'ALREADY_CLOSED' and not reusable(entry):
                roles = {state['delegations'][t]['role'] for t in entry['tokens']}
                for role in roles & retained.keys():
                    retained[role] += 1
        for entry in plan['agents']:
            agent = entry['agent_id']
            roles = {state['delegations'][t]['role'] for t in entry['tokens']}
            role = next(iter(roles)) if len(roles) == 1 else None
            item = observed.get(agent)
            close = state.get('native_lifecycle', {}).get('closes', {}).get(agent)
            if entry['decision'] == 'ALREADY_CLOSED':
                if close and 'verified_observation' not in close:
                    self._record('closes', agent, dict(close, verified_observation=observation))
                continue
            if close:
                entry['decision'] = 'RECOVER_CLOSE'
                continue  # Never reuse or repeat an ambiguous close.
            if not final and reusable(entry) and role in limits and retained[role] < limits[role]:
                retained[role] += 1
                entry['decision'] = 'REUSABLE'
            elif entry['decision'] == 'ELIGIBLE_FOR_HOST_CLOSE':
                self._close(agent)
                # Re-observe; a successful call alone never establishes release.
                fresh = self.controller.agent_cleanup(self._observe())
                entry['decision'] = next(a['decision'] for a in fresh['agents'] if a['agent_id'] == agent)
                if entry['decision'] != 'ALREADY_CLOSED':
                    entry['decision'] = 'RECOVER_CLOSE'
        old = state.get('native_lifecycle', {}).get('inventory', {}).get('latest')
        # Persist transitions, not a fresh timestamp on every unchanged wait.
        if old is None or any(old.get(k) != plan.get(k) for k in ('agents', 'ignored_unbound_ids')):
            self._record('inventory', 'latest', plan)
        return plan['agents']

    def _close(self, agent):
        # Serialize eligibility and the host call against controller rebinding.
        # Providers must impose finite I/O timeouts on all host operations.
        observation = self._observe()
        with self.controller.locked():
            state, seq, previous = self.controller._load(sync_reports=False)
            plan = agent_cleanup.plan(state, observation)
            entry = next((a for a in plan['agents'] if a['agent_id'] == agent), None)
            require(entry is not None and entry['decision'] == 'ELIGIBLE_FOR_HOST_CLOSE', 'Agent is no longer eligible for close')
            records = state.setdefault('native_lifecycle', {}).setdefault('closes', {})
            if agent in records:
                return
            record = {'intent_id': uuid.uuid4().hex, 'observation': observation, 'status': 'requested'}
            records[agent] = record
            self.controller._save(state, 'native_close_requested', seq, previous, sync_reports=False)
            try:
                receipt = self.host.close(agent)
                require(isinstance(receipt, dict) and set(receipt) == {'source_ref', 'closed'}
                        and isinstance(receipt['source_ref'], str) and receipt['source_ref'].strip()
                        and type(receipt['closed']) is bool, 'Invalid native close receipt')
                record = dict(record, receipt=receipt, status='acknowledged')
            except Exception as exc:
                record = dict(record, error=type(exc).__name__ + ': ' + str(exc), status='uncertain')
            state, seq, previous = self.controller._load(sync_reports=False)
            state['native_lifecycle']['closes'][agent] = record
            self.controller._save(state, 'native_close_result', seq, previous, sync_reports=False)

    def _assign(self, request):
        token = request['token']
        readiness = self.controller.check(token)
        if readiness['status'] != 'READY':
            return readiness
        state = self._state()
        delivery = state.get('native_lifecycle', {}).get('deliveries', {}).get(token)
        if delivery and delivery['status'] != 'not_started':
            return {'status': 'RECOVER_START', 'token': token, 'agent_id': delivery['agent_id']}
        binding = state['delegations'].get(token)
        if binding and (token in state.get('pool_starts', {}) or
                        token not in state.get('native_lifecycle', {}).get('assignments', {})):
            return {'status': 'RECOVER_START', 'token': token, 'agent_id': binding['agent_id']}
        if not binding:
            observation = self._observe()
            observed = {a['agent_id']: a for a in observation['agents']}
            # Resolve any previous spawn before choosing another reusable identity.
            # Otherwise a lost spawn reply could leave an unbound orphan behind.
            matches = self.host.find(token)
            require(isinstance(matches, list) and all(isinstance(a, str) and a.strip() for a in matches), 'Invalid recovered identities')
            require(len(matches) <= 1, 'Multiple host identities for one token; reconcile before dispatch')
            if matches:
                agent = matches[0]
                require(agent not in {b['agent_id'] for b in state['delegations'].values()}, 'Recovered identity conflicts with existing ownership')
                self._record('assignments', token, {'agent_id': agent, 'mode': 'recovered_spawn', 'matches': matches})
                self.controller.bind_agent(token, agent)
                return self._assign(request)
            if state.get('spawn_attempts', {}).get(token):
                # No match does not prove that a previous call created no agent.
                # Leave capacity-retry evidence to the controller recovery API.
                return self.controller.spawn_attempt(token)
            closed_or_pending_close = set(state.get('native_lifecycle', {}).get('closes', {}))
            candidates = []
            for agent in sorted({b['agent_id'] for b in state['delegations'].values()}):
                tokens = [t for t, b in state['delegations'].items() if b['agent_id'] == agent]
                item = observed.get(agent)
                if (agent not in closed_or_pending_close and agent not in request.get('excluded_agent_ids', [])
                        and item and item['status'] in ('idle', 'completed', 'failed', 'cancelled')
                        and item['execution_quiescent'] and all(t in state['receipts'] for t in tokens)
                        and all(state['delegations'][t]['role'] == request['role'] for t in tokens)):
                    candidates.append(agent)
            if candidates:
                agent = candidates[0]
                item = observed[agent]
                reuse = dict(item, observed_at=observation['observed_at'], source_ref=observation['source_ref'])
                self._record('assignments', token, {'agent_id': agent, 'mode': 'reuse', 'observation': reuse})
                self.controller.bind_agent(token, agent, observation=reuse)
            else:
                retained_ids = {b['agent_id'] for b in state['delegations'].values()
                                if observed.get(b['agent_id'], {}).get('status') != 'closed'}
                limit = state['config']['agent_pool']['max_workers'] + 1
                if len(retained_ids) >= limit:
                    return {'status': 'WAITING_FOR_CAPACITY', 'retained_agents': len(retained_ids), 'limit': limit}
                reserved = self.controller.spawn_attempt(token)
                if reserved['status'] != 'SPAWN_RESERVED':
                    return reserved
                readiness = self.controller.check(token)
                if readiness['status'] != 'READY':
                    return readiness
                try:
                    agent = self.host.spawn(copy.deepcopy(request))
                    require(isinstance(agent, str) and agent.strip(), 'Host did not return an agent ID')
                except Exception as exc:
                    # A general exception never proves that no agent was created.
                    failure = {'attempt_id': reserved['attempt_id'], 'error': type(exc).__name__ + ': ' + str(exc),
                               'source_ref': 'native_lifecycle spawn exception', 'no_agent_created': False}
                    self.controller.spawn_result(token, failure)
                    return {'status': 'RECOVER_SPAWN', 'token': token}
                self._record('assignments', token, {'agent_id': agent, 'mode': 'spawn', 'attempt_id': reserved['attempt_id']})
                self.controller.bind_agent(token, agent)
            binding = self._state()['delegations'][token]
        agent = binding['agent_id']
        assignment = self._state().get('native_lifecycle', {}).get('assignments', {}).get(token)
        require(assignment and assignment['agent_id'] == agent, 'Assignment intent does not match bound identity')
        observed = {a['agent_id']: a for a in self._observe()['agents']}
        item = observed.get(agent)
        if not item or item['status'] not in ('idle', 'completed', 'failed', 'cancelled') or not item['execution_quiescent']:
            return {'status': 'RECOVER_START', 'token': token, 'agent_id': agent}
        # A durable delivery marker prevents a lost reply from replaying a turn.
        readiness = self.controller.check(token)
        if readiness['status'] != 'READY':
            return readiness
        intent = {'agent_id': agent, 'token': token, 'status': 'requested'}
        self._record('deliveries', token, intent)
        readiness = self.controller.check(token)
        if readiness['status'] != 'READY':
            self._record('deliveries', token, dict(intent, status='not_started'))
            return readiness
        try:
            source_ref = self.host.start(agent, copy.deepcopy(request))
            require(isinstance(source_ref, str) and source_ref.strip(), 'Native start needs actual acknowledgement')
            self.controller.start_agent(token, agent, source_ref)
            self._record('deliveries', token, dict(intent, status='acknowledged', source_ref=source_ref))
        except Exception as exc:
            self._record('deliveries', token, dict(intent, status='uncertain', error=type(exc).__name__ + ': ' + str(exc)))
            return {'status': 'RECOVER_START', 'token': token, 'agent_id': agent}
        return {'status': 'STARTED', 'token': token, 'agent_id': agent}

    def tick(self):
        """Harvest all available results, reconcile resources, and start one assignment.

        Invoke again after STARTED to refill independent capacity. On waiting or
        uncertain states, await new host evidence; do not busy poll or reset state.
        """
        with self.guard.locked():
            state = self._state()
            require('agent_pool' in state['config'], 'Native coordinator requires an explicitly selected pool controller')
            self._harvest(self._observe())
            state = self._state()
            # Read actual freshness before treating a historical completion as final.
            status = self.controller.status()
            final = status['complete'] and status['freshness']['completion_current']
            agents = self._inventory(final=final)
            if state['control'] != 'active':
                return {'status': state['control'].upper(), 'agents': agents}
            if final:
                return {'status': 'COMPLETE', 'agents': agents,
                        'resources_released': bool(agents) and all(a['decision'] == 'ALREADY_CLOSED' for a in agents)}
            state = self._state()
            # Recover unresolved dispatch before creating another scheduling intent.
            deliveries = state.get('native_lifecycle', {}).get('deliveries', {})
            for token, request in state['pool_pending'].items():
                if token not in deliveries or deliveries[token]['status'] == 'not_started':
                    return dict(self._assign(request), agents=agents)
            dispatch = self.controller.next(dispatch_id='native-' + uuid.uuid4().hex)
            if dispatch['status'] != 'DISPATCH':
                return dict(dispatch, agents=agents)
            return dict(self._assign(dispatch['request']), agents=agents)


    def run(self, max_ticks=100):
        """Bounded refill; return on wait/uncertainty. Host events trigger later runs."""
        require(type(max_ticks) is int and 1 <= max_ticks <= 10000, 'Invalid tick budget')
        for _ in range(max_ticks):
            result = self.tick()
            if result['status'] != 'STARTED':
                return result
        return {'status': 'TICK_BUDGET_EXHAUSTED', 'last_result': result}


def main(argv=None):
    import argparse
    import importlib
    import json
    from long_running_controller import ContractError
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--adapter', required=True, help='Explicit trusted Python module:factory; factory(controller) returns a host provider')
    parser.add_argument('--max-ticks', type=int, default=100)
    args = parser.parse_args(argv)
    try:
        module, separator, factory = args.adapter.partition(':')
        require(separator and module and factory and factory.isidentifier(), 'Expected module:factory adapter')
        controller = Controller(args.state)
        host = getattr(importlib.import_module(module), factory)(controller)
        result = NativeCoordinator(controller, host).run(args.max_ticks)
        print(json.dumps(result))
        return 0
    except (ContractError, ImportError, AttributeError, OSError, ValueError) as exc:
        print(json.dumps({'status': 'ERROR', 'error': str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
