"""Plan native agent release from fresh host observations; never close or delete."""
from __future__ import annotations
import math
import time
from subagent_mode import ContractError


def require(value, message):
    if not value:
        raise ContractError(message)


def plan(state, observation, now=None):
    """Return candidates only. The coordinator rechecks the host before closing."""
    require(isinstance(observation, dict) and set(observation) == {
        'observed_at', 'source_ref', 'close_supported', 'agents'}, 'Invalid host observation fields')
    now = time.time() if now is None else now
    stamp = observation['observed_at']
    require(type(stamp) in (int, float) and math.isfinite(stamp) and 0 <= now - stamp <= 60,
            'Host observation must be fresh (at most 60 seconds old, not future-dated)')
    require(isinstance(observation['source_ref'], str) and observation['source_ref'].strip(),
            'Record actual host observation source')
    require(type(observation['close_supported']) is bool, 'close_supported must be boolean')
    require(isinstance(observation['agents'], list), 'agents must be a list')
    observed = {}
    for item in observation['agents']:
        require(isinstance(item, dict) and set(item) == {
            'agent_id', 'status', 'execution_quiescent'}, 'Invalid agent observation fields')
        key = item['agent_id']
        require(isinstance(key, str) and key.strip() and key not in observed, 'Missing or duplicate host agent ID')
        require(item['status'] in ('running', 'idle', 'completed', 'failed', 'cancelled', 'closed', 'unknown'),
                'Unknown normalized host status')
        require(type(item['execution_quiescent']) is bool, 'execution_quiescent must be boolean')
        observed[key] = item
    owned = {}
    for token, binding in state.get('delegations', {}).items():
        owned.setdefault(binding['agent_id'], []).append(token)
    pending = (state.get('pending') or {}).get('token')
    entries = []
    for key, tokens in sorted(owned.items()):
        item = observed.get(key)
        if pending in tokens or any(t not in state['receipts'] for t in tokens):
            decision = 'RETAIN_UNRECORDED_RESULT'
        elif item is None or item['status'] in ('unknown', 'idle'):
            decision = 'RETAIN_UNKNOWN_EXECUTION'
        elif item['status'] == 'running':
            decision = 'RETAIN_RUNNING'
        elif not item['execution_quiescent']:
            decision = 'RETAIN_UNRESOLVED_EXECUTION'
        elif item['status'] == 'closed':
            decision = 'ALREADY_CLOSED'
        elif not observation['close_supported']:
            decision = 'CLOSE_UNAVAILABLE'
        else:
            decision = 'ELIGIBLE_FOR_HOST_CLOSE'
        entries.append({'agent_id': key, 'tokens': sorted(tokens), 'decision': decision,
                        'result_digests': {t: state['receipts'].get(t) for t in sorted(tokens)}})
    return {'status': 'CLEANUP_PLAN', 'observed_at': stamp, 'source_ref': observation['source_ref'],
            'agents': entries, 'ignored_unbound_ids': sorted(set(observed) - set(owned)),
            'host_actions_performed': False, 'claims_review_unchanged': True,
            'recheck_required_before_close': True}
