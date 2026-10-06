"""Cooperative worker pool with automatic selection and append-only migration.

Hosts execute tasks; this module only journals decisions. Unknown action scopes
lock the full evidence inventory, allowing identity reuse without unsafe overlap.
"""
from __future__ import annotations
import copy
import math
from pathlib import Path
import time
import uuid
import subagent_mode as sm

require = sm.require
digest = sm.digest


def configure_new(config):
    """Select pooling for delegated goals unless serialization was explicit."""
    config = copy.deepcopy(config)
    mode = config.get('scheduling_mode', 'auto')
    require(mode in ('auto', 'serialized'), 'Invalid scheduling_mode')
    require(not (mode == 'serialized' and 'agent_pool' in config),
            'Serialized scheduling conflicts with agent_pool')
    if not sm.enabled(config) or mode == 'serialized':
        return config
    if 'agent_pool' not in config:
        config['agent_pool'] = {'max_workers': 2}
        # Absence of both fields means unknown scope, not read-only work.
        for action in config['actions']:
            if 'read_paths' not in action and 'write_paths' not in action:
                action.update(read_paths=[], write_paths=list(config['evidence']))
    return config


def _import_serial_history(controller, state):
    """Recover recorded outcomes from validated history, never synthesize receipts."""
    from long_running_controller import read_json
    requests, results = {}, {}
    reconciliations = {}
    for path in sorted((controller.root / 'journal').glob('*.json')):
        event = read_json(path)
        prior = event['state']
        request = prior.get('pending')
        if request:
            requests[request['token']] = request
        record = prior.get('last_result')
        if record and record['token'] not in results:
            token = record['token']
            require(state['receipts'].get(token) == digest(record['result']),
                    'Historical result does not match its receipt')
            results[token] = dict(copy.deepcopy(record), recorded_at=event['time'])
        if event['kind'] == 'reconciled':
            reconciliation = prior['reconciliation']
            reconciliations[reconciliation['action']] = {
                'outcome': reconciliation['outcome'], 'evidence': reconciliation['evidence'], 'reviewed': False}
    require(set(state['receipts']) == set(results), 'Historical result coverage is incomplete')
    require(set(state['delegations']) <= set(results), 'Historical bound execution is unresolved')
    state['pool_results'] = results
    state['pool_reconciliations'] = reconciliations
    for token, record in results.items():
        request = requests.get(token)
        require(request is not None, 'Historical request is missing')
        if request['kind'] == 'review':
            continue
        binding = state['delegations'].get(token)
        require(binding is not None, 'Historical worker identity is missing; cannot verify review independence')
        result = record['result']
        action = next(a for a in request['config']['actions'] if a['id'] == request['action_id'])
        claims = set(action['affected_claims']) | set(result.get('affected_claims', []))
        state['pool_units'][token] = {
            'token': token, 'action_id': request['action_id'], 'result': copy.deepcopy(result),
            'status': result['status'], 'agent_id': binding['agent_id'],
            'claims': sm.closure(state['config'], claims), 'reviewed': False}


def migrate_for_dispatch(controller, dispatch_id):
    """A durable dispatch intent identifies a pool-capable host. Never migrate reads."""
    from long_running_controller import snapshot, validate_config as validate_controller
    require(isinstance(dispatch_id, str) and dispatch_id.strip(), 'Invalid dispatch_id')
    with controller.locked():
        state, seq, previous = controller._load(sync_reports=False)
        if 'agent_pool' in state['config']:
            return None
        require(sm.enabled(state['config']), 'Pool migration requires authorized subagent_mode')
        require(state['config'].get('scheduling_mode', 'auto') != 'serialized',
                'Explicit serialized scheduling disables automatic pool migration')
        if state['control'] != 'active':
            return {'status': state['control'].upper()}
        if state['pending']:
            return {'status': 'IN_FLIGHT', 'request': state['pending'],
                    'delegation': state['delegations'].get(state['pending']['token']),
                    'migration': 'DEFERRED_UNTIL_FINISH'}
        if state['complete']:
            freshness = sm.observe_freshness(state, snapshot)
            if freshness['completion_current']:
                return {'status': 'COMPLETE', 'freshness': freshness,
                        'migration': 'TERMINAL_GOAL_UNCHANGED'}
        if state['dispatches'] >= state['config'].get('max_dispatches', 100):
            return {'status': 'BUDGET_EXHAUSTED'}
        before_config = state['config_digest']
        before_contract = copy.deepcopy(state['reviewer_contract'])
        try:
            candidate = validate_controller(configure_new(state['config']))
            current = snapshot(candidate)
            contract = sm.reviewer_snapshot(candidate)
            source_changed = current != state['snapshot'] or contract != before_contract
            state['config'] = candidate
            state['config_digest'] = digest(candidate)
            initialize(state)
            _import_serial_history(controller, state)
            state['snapshot'] = current
            state['reviewer_contract'] = contract
            if source_changed:
                # Normal next() reopens failed reviews on actual source drift.
                # Migration itself is not new evidence or another retry allowance.
                state['review_failures'] = 0
            sm.invalidate(state)
            # Historical findings, holds, budgets, failed-review counts, work
            # results and retry reservations stay intact. Only clearance expires.
            state.update(clearances={}, review_due=True, preferred=None, complete=False)
            state['pool_migration'] = {
                'from_config_digest': before_config, 'to_config_digest': state['config_digest'],
                'from_reviewer_contract': before_contract,
                'to_reviewer_contract': copy.deepcopy(state['reviewer_contract']),
                'source_journal_digest': previous, 'source_journal_seq': seq,
                'trigger_dispatch_id': dispatch_id, 'recorded_at': time.time(),
                'source_changed': source_changed,
                'reason': 'Automatic pool transition at a quiescent dispatch boundary'}
        except (sm.ContractError, OSError, KeyError, TypeError) as exc:
            return {'status': 'MIGRATION_BLOCKED', 'reason': str(exc),
                    'source_journal_digest': previous}
        controller._save(state, 'pool_migrated', seq, previous)
        return None


def validate_config(config):
    require(config.get('scheduling_mode', 'auto') in ('auto', 'serialized'), 'Invalid scheduling_mode')
    require(not (config.get('scheduling_mode') == 'serialized' and 'agent_pool' in config),
            'Serialized scheduling conflicts with agent_pool')
    if 'agent_pool' not in config:
        return
    pool = config['agent_pool']
    require(sm.enabled(config), 'agent_pool requires subagent_mode')
    require(isinstance(pool, dict) and set(pool) == {'max_workers'}, 'Invalid agent_pool fields')
    require(type(pool['max_workers']) is int and 1 <= pool['max_workers'] <= 32,
            'max_workers must be an integer from 1 to 32')
    root = Path(config['project_root'])
    canonical = {}
    for name in config['evidence']:
        require(isinstance(name, str) and name and '\\' not in name and ':' not in name, 'Invalid pool evidence path')
        rel = Path(name)
        require(all(part and not part.endswith(('.', ' ')) for part in rel.parts), 'Pool evidence has an ambiguous path component')
        require(isinstance(name, str) and not rel.is_absolute() and '..' not in rel.parts
                and name == rel.as_posix(), 'Pool evidence must use canonical relative POSIX paths')
        resolved = str((root / rel).resolve()).casefold()
        require(resolved not in canonical, 'Pool evidence aliases or case collisions are forbidden')
        canonical[resolved] = name
    for action in config['actions']:
        for field in ('read_paths', 'write_paths'):
            sm.strings(action.get(field), field)
            require(set(action[field]) <= set(config['evidence']), field + ' must be declared evidence')
        require(action['read_paths'] or action['write_paths'], 'Pool action needs an evidence scope')
        require(not set(action['read_paths']).intersection(action['write_paths']),
                'Classify a read-modify-write path as write_paths only')


def initialize(state):
    if 'agent_pool' not in state['config']:
        return
    state.update(pool_pending={}, pool_dispatches={}, pool_results={}, pool_units={}, pool_starts={}, pool_reconciliations={},
                 pool_reviewed_actions={}, pool_clearances={}, pool_global_review=True,
                 pool_claim_generations={k: 0 for k in state['working_claims']})


def is_pool(controller):
    # Only configuration selects semantics; never infer migration from agent count.
    with controller.locked():
        return 'agent_pool' in controller._load(sync_reports=False)[0]['config']


def has_pending(state):
    return bool(state.get('pending') or state.get('pool_pending'))


def get_pending(state, token):
    if 'agent_pool' in state['config']:
        return state['pool_pending'].get(token)
    request = state.get('pending')
    return request if request and request['token'] == token else None


def ancestors(config, ids):
    found = set(ids)
    definitions = sm.definitions(config)
    while True:
        more = found | {p for key in found for p in definitions[key].get('depends_on', [])}
        if more == found:
            return found
        found = more


def action_claims(config, action):
    return set(sm.closure(config, action['affected_claims'])) | ancestors(config, action['required_claims'])


def action_writes(config, action):
    return set(sm.closure(config, action['affected_claims']))


def project_snapshot(current, paths):
    files = {p: current['files'][p] for p in sorted(paths)}
    return {'files': files, 'digest': digest(files)}


def generations(state, ids):
    return {key: state['pool_claim_generations'][key] for key in sorted(ids)}


def invalidate(state, ids=None):
    changed = set(sm.closure(state['config'], ids if ids is not None else state['working_claims']))
    sm.invalidate(state, changed)
    for key in changed:
        state['pool_claim_generations'][key] += 1
    for action in state['config']['actions']:
        if action_claims(state['config'], action).intersection(changed):
            state['pool_clearances'].pop(action['id'], None)


def actions(state):
    return {a['id']: a for a in state['config']['actions']}


def observe(state, current):
    """Account for owned writes; unknown drift requires a global review barrier."""
    changed = {p for p, sha in current['files'].items() if state['snapshot']['files'].get(p) != sha}
    owned = set()
    for request in state['pool_pending'].values():
        if request['kind'] != 'review':
            owned.update(request['write_paths'])
    contract = sm.reviewer_snapshot(state['config'])
    if changed - owned or contract != state['reviewer_contract']:
        invalidate(state)
        state.update(pool_global_review=True, review_due=True, complete=False, review_failures=0)
        state['pool_clearances'] = {}
    state['snapshot'] = current
    state['reviewer_contract'] = contract


def request_current(state, request, current, completion=False):
    if 'agent_pool' not in state['config']:
        return (request['snapshot'] == current and
                state.get('reviewer_contract') == sm.reviewer_snapshot(state['config']))
    changed = {p for p, sha in current['files'].items() if state['snapshot']['files'].get(p) != sha}
    owned = {p for r in state['pool_pending'].values() if r['kind'] != 'review' for p in r['write_paths']}
    if changed - owned:
        return False
    if request['reviewer_contract'] != sm.reviewer_snapshot(state['config']):
        return False
    if request['config_digest'] != state['config_digest']:
        return False
    ids = request['claim_generations']
    if generations(state, ids) != ids:
        return False
    # Worker output paths may legitimately change after dispatch. Inputs may not.
    running = completion or request['token'] in state.get('pool_starts', {})
    paths = request['read_paths'] if request['kind'] != 'review' and running else request['snapshot']['files']
    return all(current['files'].get(p) == request['snapshot']['files'].get(p) for p in paths)


def _conflicts(state, reads, writes, claim_reads, claim_writes, kind='work'):
    for request in state['pool_pending'].values():
        if kind == 'repair' or request['kind'] == 'repair':
            return True
        if set(writes).intersection(request['read_paths'] + request['write_paths']):
            return True
        if set(reads).intersection(request['write_paths']):
            return True
        if set(claim_writes).intersection(request['claim_reads'] + request['claim_writes']):
            return True
        if set(claim_reads).intersection(request['claim_writes']):
            return True
    return False


def _prerequisites(state, action):
    mapping = actions(state)
    def held(key):
        return key in state['holds'] or any(held(p) for p in mapping[key].get('depends_on', []))
    return (not held(action['id']) and all(state['actions'][p] == 'done' and
            p in state['pool_reviewed_actions'] for p in action.get('depends_on', [])))


def _clearance(state, action, current):
    # Include writes: the reviewer must have seen the initial read-modify-write bytes.
    paths = action['read_paths'] + action['write_paths']
    return {'snapshot': project_snapshot(current, paths),
            'claims': generations(state, action_claims(state['config'], action)),
            'contract_digest': state['reviewer_contract']['digest']}


def _ready(state, action, current):
    if state['actions'][action['id']] != 'pending' or not _prerequisites(state, action):
        return False
    if not sm.ready(state, action):
        return False
    if state['pool_clearances'].get(action['id']) != _clearance(state, action, current):
        return False
    if action.get('kind') == 'repair':
        attempt = state['attempts'].get(action['attempt_id'], {})
        limit = state['config'].get('max_repair_cycles', 3)
        if attempt.get('stopped') or attempt.get('cycles', 0) >= limit:
            return False
    return True


def _review_scope(state, unit, current):
    config = state['config']
    if unit is None:
        return set(current['files']), set(state['claim_dirty']), 'global', []
    action = actions(state)[unit['action_id']]
    ids = set(sm.closure(config, action['affected_claims'] + unit['result'].get('affected_claims', [])))
    paths = set(action['read_paths'] + action['write_paths'])
    for key in ancestors(config, ids):
        paths.update(link['path'] for link in state['working_claims'][key]['evidence'])
    # Pending dependents may need additional stable inputs for a useful clearance.
    # Add only scopes that do not conflict with any running operation.
    for candidate in config['actions']:
        if unit['action_id'] not in candidate.get('depends_on', []):
            continue
        candidate_paths = set(candidate['read_paths'] + candidate['write_paths'])
        if not _conflicts(state, candidate_paths, [], [], []):
            paths.update(candidate_paths)
    return paths, ids, 'unit', [unit['token']]


def _review_request(state, current):
    if any(r['kind'] == 'review' for r in state['pool_pending'].values()):
        return None
    if state['review_failures'] >= 2:
        return None
    if state['pool_global_review']:
        if state['pool_pending']:
            return None
        scope = _review_scope(state, None, current)
    else:
        scope = None
        for unit in state['pool_units'].values():
            if unit['reviewed']:
                continue
            candidate = _review_scope(state, unit, current)
            paths, ids, _, _ = candidate
            if not _conflicts(state, paths, [], ancestors(state['config'], ids), ids):
                scope = candidate
                break
        if scope is None:
            required = [a['id'] for a in state['config']['actions'] if a.get('required', True)]
            if (not state['pool_pending'] and not state['complete'] and
                    all(state['actions'][k] == 'done' and k in state['pool_reviewed_actions'] for k in required)):
                scope = _review_scope(state, None, current)
            else:
                return None
    paths, ids, mode, work_tokens = scope
    # A global review reviews every accumulated outcome, not merely last_work.
    if mode == 'global':
        work_tokens = [u['token'] for u in state['pool_units'].values() if not u['reviewed']]
    excluded = set()
    for unit in state['pool_units'].values():
        if set(unit['claims']).intersection(ids) or unit['token'] in work_tokens or mode == 'global':
            excluded.add(unit['agent_id'])
    request = {'kind': 'review', 'action_id': None, 'command': state['config'].get('reviewer_command'),
               'timeout_seconds': 60, 'review_scope': mode, 'review_work_tokens': work_tokens,
               'review_outcomes': [copy.deepcopy(state['pool_units'][t]) for t in work_tokens],
               'reconciliations': copy.deepcopy({k: v for k, v in state['pool_reconciliations'].items()
                                                if not v['reviewed']}) if mode == 'global' else {},
               'excluded_agent_ids': sorted(excluded), 'read_paths': sorted(paths), 'write_paths': [],
               'claim_reads': sorted(ancestors(state['config'], ids)), 'claim_writes': sorted(ids),
               'required_claim_updates': sorted(ids)}
    # Claims dirtied by a finished unit may be cleared in this review. All others
    # remain blocked. Worker dependencies are checked again when dispatching.
    clearable = []
    for action in state['config']['actions']:
        scope_paths = set(action['read_paths'] + action['write_paths'])
        if (state['actions'][action['id']] == 'pending' and scope_paths <= paths and
                not (action_claims(state['config'], action) & (set(state['claim_dirty']) - ids))):
            clearable.append(action['id'])
    request['clearable_actions'] = clearable
    return request


def _worker_request(state, current):
    config = state['config']
    if state['pool_global_review']:
        return None
    workers = [r for r in state['pool_pending'].values() if r['kind'] != 'review']
    if len(workers) >= config['agent_pool']['max_workers']:
        return None
    mapping = actions(state)
    def depth(key):
        children = [a['id'] for a in mapping.values() if key in a.get('depends_on', [])]
        return 1 + max((depth(k) for k in children), default=0)
    candidates = sorted(mapping.values(), key=lambda a: (-depth(a['id']), a['id']))
    for action in candidates:
        if not _ready(state, action, current):
            continue
        read_claims = ancestors(config, action['required_claims'])
        write_claims = action_writes(config, action)
        kind = action.get('kind', 'work')
        if _conflicts(state, action['read_paths'], action['write_paths'], read_claims, write_claims, kind):
            continue
        if kind == 'repair':
            state['attempts'].setdefault(action['attempt_id'], {'cycles': 0, 'stopped': False,
                                                               'candidates': [], 'finding_sets': []})
        return {'kind': kind, 'action_id': action['id'], 'instruction': action['instruction'],
                'command': action.get('command'), 'timeout_seconds': action.get('timeout_seconds', 300),
                'read_paths': action['read_paths'], 'write_paths': action['write_paths'],
                'claim_reads': sorted(read_claims), 'claim_writes': sorted(write_claims)}
    return None


def next_request(controller, dispatch_id=None):
    from long_running_controller import snapshot
    require(dispatch_id is None or isinstance(dispatch_id, str) and dispatch_id.strip(), 'Invalid dispatch_id')
    with controller.locked():
        state, seq, prev = controller._load(sync_reports=False)
        if dispatch_id in state['pool_dispatches']:
            token = state['pool_dispatches'][dispatch_id]
            if token in state['receipts']:
                return {'status': 'ALREADY_RECORDED', 'token': token, 'outcome': state['pool_results'][token]}
            request = state['pool_pending'][token]
            if state['control'] != 'active':
                return {'status': state['control'].upper(), 'request': request, 'recovered': True}
            if not request_current(state, request, snapshot(state['config'])):
                return {'status': 'STALE', 'request': request, 'recovered': True}
            return {'status': 'DISPATCH', 'request': request,
                    'delegation': state['delegations'].get(token), 'recovered': True}
        if state['control'] != 'active':
            return {'status': state['control'].upper(), 'inflight': list(state['pool_pending'].values())}
        if dispatch_id is None:
            if state['complete']:
                freshness = sm.observe_freshness(state, snapshot)
                return {'status': 'COMPLETE' if freshness['completion_current'] else 'STALE',
                        'inflight': list(state['pool_pending'].values()), 'freshness': freshness,
                        'requires_dispatch_id': True}
            return {'status': 'IN_FLIGHT' if state['pool_pending'] else 'WAITING',
                    'inflight': list(state['pool_pending'].values()), 'requires_dispatch_id': True}
        old = digest(state)
        current = snapshot(state['config'])
        observe(state, current)
        if state['complete']:
            return {'status': 'COMPLETE', 'review': state['last_review']}
        if state['dispatches'] >= state['config'].get('max_dispatches', 100):
            if digest(state) != old:
                controller._save(state, 'pool_budget_exhausted', seq, prev)
            return {'status': 'BUDGET_EXHAUSTED', 'inflight': list(state['pool_pending'].values())}
        request = _review_request(state, current) or _worker_request(state, current)
        if request is None:
            if digest(state) != old:
                controller._save(state, 'pool_waiting', seq, prev)
            full = sum(r['kind'] != 'review' for r in state['pool_pending'].values()) >= state['config']['agent_pool']['max_workers']
            return {'status': 'POOL_FULL' if full else 'WAITING', 'inflight': list(state['pool_pending'].values()),
                    'holds': state['holds'], 'review_failures': state['review_failures'],
                    'wake_condition': 'Owned result, evidence, capacity, or authorized reconciliation'}
        if request['kind'] != 'review':
            invalidate(state, request['claim_writes'])
            state['actions'][request['action_id']] = 'running'
        required = request.get('required_claim_updates')
        request.update(token=uuid.uuid4().hex, dispatch_id=dispatch_id,
                       goal_revision=state['config']['goal_revision'], config_digest=state['config_digest'],
                       snapshot=project_snapshot(current, request['read_paths'] + request['write_paths']),
                       actions=copy.deepcopy(state['actions']), holds=copy.deepcopy(state['holds']),
                       findings=copy.deepcopy(state['findings']), attempts=copy.deepcopy(state['attempts']),
                       config=copy.deepcopy(state['config']),
                       claim_generations=generations(state, request['claim_reads'] + request['claim_writes']))
        if request['kind'] == 'repair':
            request['finding_signature'] = digest(sorted((k, v['evidence']) for k, v in state['findings'].items()))
        sm.enrich_request(state, request)
        if required is not None:
            request['required_claim_updates'] = required
        request['semantic_digest'] = digest({k: v for k, v in request.items() if k not in ('semantic_digest', 'token', 'delegation_key')})
        state['pool_pending'][request['token']] = copy.deepcopy(request)
        state['pool_dispatches'][dispatch_id] = request['token']
        state['dispatches'] += 1
        controller._save(state, 'pool_dispatched', seq, prev)
        return {'status': 'DISPATCH', 'request': request}


def record_reconciliation(state, action_id, outcome, evidence):
    if 'agent_pool' not in state['config']:
        return
    state['pool_reconciliations'][action_id] = {
        'outcome': outcome, 'evidence': evidence, 'reviewed': False}
    state['pool_reviewed_actions'].pop(action_id, None)


def invalidate_external(state):
    if 'agent_pool' not in state['config']:
        return
    invalidate(state)
    state.update(pool_global_review=True, pool_clearances={}, complete=False, review_due=True)


def start_agent(controller, token, agent_id, source_ref):
    """Record observed host acknowledgement, never infer it from a queued message."""
    require(isinstance(source_ref, str) and source_ref.strip(), 'Record actual host acknowledgement source')
    with controller.locked():
        state, seq, prev = controller._load(sync_reports=False)
        request = get_pending(state, token)
        require(request is not None, 'No matching in-flight action')
        binding = state['delegations'].get(token)
        require(binding is not None and binding['agent_id'] == agent_id, 'Start acknowledgement must match bound agent')
        prior = state['pool_starts'].get(token)
        if prior:
            require(prior['agent_id'] == agent_id and prior['source_ref'] == source_ref, 'Conflicting start acknowledgement')
            return {'status': 'ALREADY_RECORDED', 'acknowledgement': prior}
        # This is historical acknowledgement after a host call. Persist even if a
        # pause arrived meanwhile; no permission to start additional work follows.
        record = {'agent_id': agent_id, 'source_ref': source_ref, 'recorded_at': time.time()}
        state['pool_starts'][token] = record
        controller._save(state, 'pool_start_acknowledged', seq, prev)
        return {'status': 'START_RECORDED', 'acknowledgement': record}


def check(controller, token):
    from long_running_controller import snapshot
    with controller.locked():
        state, _, _ = controller._load(sync_reports=False)
        request = get_pending(state, token)
        require(request is not None, 'No matching in-flight action')
        if state['control'] != 'active':
            return {'status': state['control'].upper()}
        current = snapshot(state['config'])
        return {'status': 'READY' if request_current(state, request, current) else 'STALE'}


def bind_agent(controller, token, agent_id, observation=None):
    from long_running_controller import snapshot
    require(isinstance(agent_id, str) and agent_id.strip(), 'Agent ID required')
    with controller.locked():
        state, seq, prev = controller._load(sync_reports=False)
        request = get_pending(state, token)
        require(request is not None, 'No matching in-flight action')
        binding = {'agent_id': agent_id, 'role': request['role'], 'delegation_key': token}
        prior = state['delegations'].get(token)
        if prior:
            require(all(prior.get(k) == v for k, v in binding.items()), 'Token already bound to another agent')
            return {'status': 'ALREADY_BOUND', 'delegation': prior}
        require(state['control'] == 'active', 'Cannot bind new work while paused or stopped')
        require(request_current(state, request, snapshot(state['config'])), 'Cannot bind stale request')
        require(agent_id not in request.get('excluded_agent_ids', []), 'Worker cannot review its own contribution')
        previous = [t for t, b in state['delegations'].items() if b['agent_id'] == agent_id]
        require(all(t in state['receipts'] for t in previous), 'Agent has unresolved bound execution')
        if previous:
            require(isinstance(observation, dict) and set(observation) == {
                'observed_at', 'source_ref', 'agent_id', 'status', 'execution_quiescent'},
                'Reusing an agent requires a fresh host observation')
            stamp = observation['observed_at']
            require(type(stamp) in (int, float) and math.isfinite(stamp) and 0 <= time.time() - stamp <= 60,
                    'Agent reuse observation must be fresh and not future-dated')
            require(observation['agent_id'] == agent_id and observation['status'] in ('idle', 'completed', 'failed', 'cancelled')
                    and observation['execution_quiescent'] is True, 'Agent is not observed reusable and quiescent')
            require(isinstance(observation['source_ref'], str) and observation['source_ref'].strip(), 'Record host evidence')
            require(stamp >= max(state['pool_results'][t]['recorded_at'] for t in previous),
                    'Observe reuse after previous results were recorded')
            binding['reuse_observation'] = copy.deepcopy(observation)
        elif observation is not None:
            raise sm.ContractError('Reuse observation supplied for an unowned identity')
        # Binding is the durable assignment intent. Host release follows a fresh check.
        state['delegations'][token] = binding
        controller._save(state, 'pool_agent_bound', seq, prev)
        return {'status': 'BOUND', 'delegation': binding}


def finish(controller, token, result):
    from long_running_controller import snapshot
    require(isinstance(result, dict), 'Result must be an object')
    with controller.locked():
        state, seq, prev = controller._load(sync_reports=False)
        if token in state['receipts']:
            require(state['receipts'][token] == digest(result), 'Conflicting duplicate result')
            return {'status': 'ALREADY_RECORDED'}
        request = get_pending(state, token)
        require(request is not None, 'No matching in-flight action')
        require(token in state['delegations'], 'Pool results require a recorded host binding')
        current = snapshot(state['config'])
        before = request_current(state, request, current, completion=True)
        observe(state, current)
        if request['kind'] == 'review':
            if not before or not request_current(state, request, current):
                outcome = 'STALE_REVIEW'
                state['review_failures'] = 0
            else:
                require(isinstance(result.get('cleared_actions', []), list) and
                        all(isinstance(k, str) for k in result.get('cleared_actions', [])), 'Invalid cleared_actions')
                require(isinstance(result.get('claim_updates', []), list) and
                        all(isinstance(u, dict) and isinstance(u.get('id'), str)
                            for u in result.get('claim_updates', [])), 'Invalid claim_updates')
                require(set(result.get('cleared_actions', [])) <= set(request['clearable_actions']),
                        'Review clears an action outside its evidence scope')
                require(not result.get('goal_complete') or request['review_scope'] == 'global',
                        'Scoped review cannot complete the goal')
                if result.get('goal_complete'):
                    require(len(state['pool_pending']) == 1, 'In-flight work prevents goal completion')
                update_ids = {u.get('id') for u in result.get('claim_updates', []) if isinstance(u, dict)}
                require(update_ids <= set(request['required_claim_updates']), 'Review updates claims outside its scope')
                # Reuse the established review/evidence validator on a transaction-local view.
                # No temporary pending token is ever journaled.
                view = copy.deepcopy(state)
                view['pending'] = copy.deepcopy(request)
                scoped = project_snapshot(current, request['snapshot']['files'])
                controller._review(view, result, scoped)
                for field in ('working_claims', 'claim_dirty', 'holds', 'findings', 'preferred',
                              'last_review', 'review_failures', 'review_due', 'attempts', 'complete'):
                    state[field] = view[field]
                if result['review_status'] != 'FAILED':
                    for work_token in request['review_work_tokens']:
                        unit = state['pool_units'][work_token]
                        unit['reviewed'] = True
                        unit['review_token'] = token
                        if unit['status'] == 'done':
                            state['pool_reviewed_actions'][unit['action_id']] = work_token
                    for key, reconciliation in request.get('reconciliations', {}).items():
                        require(state['pool_reconciliations'].get(key) == reconciliation, 'Reconciliation changed during review')
                        state['pool_reconciliations'][key].update(reviewed=True, review_token=token)
                        if reconciliation['outcome'] == 'done' and state['actions'][key] == 'done':
                            state['pool_reviewed_actions'][key] = token
                    if request['review_scope'] == 'global':
                        state['pool_global_review'] = False
                    for key in result.get('cleared_actions', []):
                        state['pool_clearances'][key] = _clearance(state, actions(state)[key], current)
                outcome = 'RECORDED'
        else:
            require(result.get('status') in ('done', 'failed', 'uncertain', 'not_started'), 'Invalid action result')
            require('claim_updates' not in result and 'skill_invocation' not in result, 'Worker cannot approve claims')
            added = sm.strings(result.get('affected_claims', []), 'affected_claims')
            require(set(added) <= set(state['working_claims']), 'Unknown affected worker claim')
            key = request['action_id']
            action = actions(state)[key]
            outcome = 'RECORDED' if before else 'STALE_WORK'
            status = result['status'] if before or result['status'] != 'done' else 'uncertain'
            state['actions'][key] = 'pending' if status == 'not_started' else status
            if status == 'not_started':
                # Dispatch dirtied claims even if no execution occurred. Review is still
                # needed before another action may consume the same claims.
                pass
            changed_claims = set(action['affected_claims']) | set(added)
            invalidate(state, changed_claims)
            if set(added) - set(request['claim_writes']):
                state['pool_global_review'] = True
            unit = {'token': token, 'action_id': key, 'result': copy.deepcopy(result), 'status': status,
                    'agent_id': state['delegations'][token]['agent_id'],
                    'claims': sm.closure(state['config'], changed_claims), 'reviewed': False}
            state['pool_units'][token] = unit
            state['last_work'] = {'token': token, 'action_id': key, 'result': copy.deepcopy(result)}
            state.update(review_due=True, review_failures=0, complete=False)
            if request['kind'] == 'repair' and status != 'not_started':
                attempt = state['attempts'][action['attempt_id']]
                attempt['cycles'] += 1
                if not attempt['candidates']:
                    attempt['candidates'].append(request['snapshot']['digest'])
                candidate = project_snapshot(current, request['snapshot']['files'])['digest']
                if candidate in attempt['candidates']:
                    attempt['stopped'] = True
                attempt['candidates'].append(candidate)
                attempt['finding_sets'].append(request['finding_signature'])
        record = {'token': token, 'request_semantic_digest': request['semantic_digest'],
                  'result': copy.deepcopy(result), 'disposition': outcome, 'recorded_at': time.time()}
        state['last_result'] = record
        state['pool_results'][token] = record
        state['receipts'][token] = digest(result)
        del state['pool_pending'][token]
        controller._save(state, 'pool_' + outcome.lower(), seq, prev)
        return {'status': outcome, 'goal_complete': state['complete']}