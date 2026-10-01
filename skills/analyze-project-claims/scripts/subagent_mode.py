"""Claim-gated cooperative subagents; no model client or acceptance authority."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid


class ContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()


def strings(value, label, nonempty=False):
    require(isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value), label + ' must be a string list')
    require(len(value) == len(set(value)) and (value or not nonempty), 'Empty or duplicate ' + label)
    return value


def is_link_or_reparse(path):
    """Detect links on Python 3.10+, including Windows junction/reparse entries.

    Missing paths are allowed for initial output creation. Other metadata errors
    propagate so an unreadable path cannot silently become trusted.
    """
    try:
        metadata = Path(path).lstat()
    except FileNotFoundError:
        return False
    return (stat.S_ISLNK(metadata.st_mode) or
            bool(getattr(metadata, 'st_file_attributes', 0) &
                 getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)))


def enabled(config):
    return 'subagent_mode' in config


def definitions(config):
    return {c['id']: c for c in config['subagent_mode']['claims']}


def closure(config, ids):
    found = set(ids)
    while True:
        more = found | {k for k, c in definitions(config).items() if found.intersection(c.get('depends_on', []))}
        if more == found:
            return sorted(found)
        found = more


def validate_config(config):
    if not enabled(config):
        return
    mode = config['subagent_mode']
    require(isinstance(mode, dict), 'subagent_mode must be an object')
    require(set(mode) == {'authorization_ref', 'reviewer_sources', 'claims', 'reports'}, 'Invalid subagent_mode fields')
    require(isinstance(mode['authorization_ref'], str) and mode['authorization_ref'].strip(), 'Record actual delegation authority')
    strings(mode['reviewer_sources'], 'reviewer_sources', True)
    require(all(Path(p).is_absolute() and Path(p).is_file() for p in mode['reviewer_sources']), 'Reviewer sources must be existing absolute files')
    require(isinstance(mode['claims'], list) and mode['claims'], 'Declare claims')
    ids = []
    for claim in mode['claims']:
        require(isinstance(claim, dict) and set(claim) <= {'id', 'statement', 'scope', 'depends_on'}, 'Invalid claim definition')
        for field in ('id', 'statement', 'scope'):
            require(isinstance(claim.get(field), str) and claim[field].strip(), 'Claim needs ' + field)
        ids.append(claim['id'])
        strings(claim.get('depends_on', []), 'claim dependencies')
    require(len(ids) == len(set(ids)), 'Duplicate claim IDs')
    graph = definitions(config)
    visited = set()
    def visit(key, active):
        require(key in graph and key not in active, 'Unknown or cyclic claim dependency')
        if key not in visited:
            for parent in graph[key].get('depends_on', []):
                visit(parent, active | {key})
            visited.add(key)
    for key in graph:
        visit(key, set())
    for action in config['actions']:
        premises = strings(action.get('required_claims'), 'required_claims')
        affected = strings(action.get('affected_claims'), 'affected_claims', True)
        require(set(premises + affected) <= graph.keys(), 'Unknown action claim')
        require(premises or isinstance(action.get('premise_free_reason'), str) and action['premise_free_reason'].strip(), 'Premise-free action needs a reason')
        require(action.get('requires_review', True), 'Subagent work always requires claims review')
    command = config.get('reviewer_command') or []
    require(not any(Path(x).name.casefold() == 'codex_reviewer.py' for x in command), 'Legacy codex_reviewer.py cannot invoke skills or return subagent claims; use a compatible adapter')
    require(isinstance(mode['reports'], list) and mode['reports'], 'Declare dependent reports')
    report_ids = []
    for report in mode['reports']:
        require(isinstance(report, dict) and set(report) == {'id', 'title', 'claim_ids'}, 'Invalid dependent report')
        require(isinstance(report['id'], str) and re.fullmatch('[a-z][a-z0-9_-]{0,63}', report['id']), 'Unsafe report ID')
        require(report['id'] not in {'con', 'prn', 'aux', 'nul'} | {f'{prefix}{i}' for prefix in ('com', 'lpt') for i in range(1, 10)}, 'Reserved report ID')
        require(isinstance(report['title'], str) and report['title'].strip(), 'Report title required')
        require(set(strings(report['claim_ids'], 'report claim_ids', True)) <= graph.keys(), 'Unknown report claim')
        report_ids.append(report['id'])
    require(len(report_ids) == len(set(report_ids)), 'Duplicate report IDs')


def reviewer_snapshot(config):
    if not enabled(config):
        return None
    paths = config['subagent_mode']['reviewer_sources']
    # Include the executed orchestration implementation, not just its guide.
    controller = Path(__file__).with_name('long_running_controller.py')
    cleanup = Path(__file__).with_name('agent_cleanup.py')
    paths = sorted(set(paths + [str(Path(__file__).resolve()), str(controller.resolve()), str(cleanup.resolve())]))
    files = {}
    for name in paths:
        path = Path(name)
        if not path.is_file():
            files[name] = None
            continue
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
        require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), 'Reviewer contract changed while reading')
        files[name] = hashlib.sha256(data).hexdigest()
    return {'files': files, 'digest': digest(files)}


def initialize(state, state_root):
    config = state['config']
    if not enabled(config):
        return
    root = Path(config['project_root'])
    require(all(not (root / p).resolve().is_relative_to(state_root) for p in config['evidence']), 'Generated controller state cannot be source evidence')
    state['working_claims'] = {k: dict(id=k, status='untested', evidence=[], limitations=['Initial claims review required'], rationale='No review yet', audit_refs=[]) for k in definitions(config)}
    state['claim_dirty'] = sorted(state['working_claims'])
    state['reviewer_contract'] = reviewer_snapshot(config)
    state['delegations'] = {}
    state['last_work'] = None


def invalidate(state, ids=None):
    if enabled(state['config']):
        state['claim_dirty'] = closure(state['config'], set(state['claim_dirty']) | set(ids if ids is not None else state['working_claims']))


def ready(state, action):
    if not enabled(state['config']):
        return True
    claims, dirty = state['working_claims'], set(state['claim_dirty'])
    if dirty:
        return False
    def supported(key):
        return key not in dirty and claims[key]['status'] == 'supported' and all(supported(p) for p in definitions(state['config'])[key].get('depends_on', []))
    return all(supported(key) for key in action['required_claims'])


def enrich_request(state, request):
    if not enabled(state['config']):
        return
    is_review = request['kind'] == 'review'
    request.update(role='claims_reviewer' if is_review else 'worker', working_claims=copy.deepcopy(state['working_claims']),
                   reviewer_contract=copy.deepcopy(state['reviewer_contract']), required_claim_updates=list(state['claim_dirty']),
                   last_work=copy.deepcopy(state.get('last_work')))
    request['delegation_key'] = request['token']
    if is_review:
        request['instruction'] = ('Invoke the active analyze-project-claims skill and all applicable owner overlays. '
            'Inspect source evidence, counterevidence, limitations and dependent claims/reports. Return the base review result '
            'plus skill_invocation and claim_updates for every required_claim_updates ID and all dependents of any extra update. '
            'Remain read-only: the coordinator commits working claims and renders dependent reports. '
            'Do not accept a formal component map. Link existing formal records in audit_refs; missing acceptance stays explicit. '
            'A work outcome is not proof of a supported claim. Report failed review if required evidence cannot be assessed.')
    else:
        action = next(a for a in state['config']['actions'] if a['id'] == request['action_id'])
        request['required_claims'] = action['required_claims']
        request['affected_claims'] = action['affected_claims']
    request['semantic_digest'] = digest({k: v for k, v in request.items() if k not in ('semantic_digest', 'token', 'delegation_key')})


def apply_review(state, result, current):
    if not enabled(state['config']) or result['review_status'] == 'FAILED':
        return
    request = state['pending']
    invocation = result.get('skill_invocation')
    require(isinstance(invocation, dict) and invocation.get('skill') == 'analyze-project-claims'
            and invocation.get('contract_digest') == request['reviewer_contract']['digest'], 'Exact analyze-project-claims invocation required')
    require(all(request['reviewer_contract']['files'].values()), 'Reviewer contract source missing')
    updates = result.get('claim_updates')
    require(isinstance(updates, list), 'claim_updates must be a list')
    ids = [u.get('id') for u in updates if isinstance(u, dict)]
    require(len(ids) == len(updates) and all(isinstance(k, str) for k in ids) and len(ids) == len(set(ids)), 'Invalid or duplicate claim updates')
    require(set(ids) <= state['working_claims'].keys(), 'Unknown claim update')
    needed = set(request['required_claim_updates']) | set(closure(state['config'], ids))
    require(needed <= set(ids), 'Missing affected claim/dependency updates')
    candidate = copy.deepcopy(state['working_claims'])
    statuses = {'supported', 'partially supported', 'contradicted', 'untested', 'invalidly specified'}
    for update in updates:
        key = update['id']
        require(update.get('status') in statuses, 'Invalid claim status')
        require(isinstance(update.get('rationale'), str) and update['rationale'].strip(), 'Claim rationale required')
        strings(update.get('limitations'), 'limitations')
        strings(update.get('audit_refs'), 'audit_refs')
        require(update['status'] == 'supported' or update['limitations'], 'Non-supported claim needs limitations')
        evidence = update.get('evidence')
        require(isinstance(evidence, list), 'Claim evidence links required')
        for link in evidence:
            require(isinstance(link, dict), 'Evidence link must be an object')
            require(isinstance(link.get('path'), str) and link['path'] in current['files'] and current['files'][link['path']] is not None, 'Evidence must name available declared source')
            require(link.get('sha256') == current['files'][link['path']], 'Stale evidence link')
            require(isinstance(link.get('locator'), str) and link['locator'].strip(), 'Evidence locator required')
            require(link.get('method') in {'source_inspection', 'executed_test', 'deterministic_replay', 'not_tested'}, 'Invalid evidence method')
            require(link.get('relation') in {'supports', 'contradicts', 'limits', 'context'}, 'Invalid evidence relation')
            require(link['method'] != 'not_tested' or link['relation'] == 'context', 'not_tested is context-only')
        relations = {e['relation'] for e in evidence}
        if update['status'] in ('untested', 'invalidly specified'):
            require(not relations.intersection({'supports', 'contradicts'}), 'Untested or unspecified claim cannot carry support or contradiction')
        if update['status'] in ('supported', 'partially supported'):
            require('supports' in relations, 'Support requires direct evidence')
        if update['status'] == 'supported':
            require('contradicts' not in relations, 'Direct counterevidence cannot be averaged away')
        if update['status'] == 'contradicted':
            require('contradicts' in relations, 'Contradiction needs counterevidence')
        removed = [e for e in candidate[key]['evidence'] if e['relation'] == 'contradicts' and e not in evidence]
        dispositions = update.get('superseded_evidence', [])
        require(isinstance(dispositions, list), 'Invalid evidence dispositions')
        for old in removed:
            require(any(isinstance(d, dict) and d.get('evidence') == old and isinstance(d.get('reason'), str) and d['reason'].strip() for d in dispositions), 'Removed counterevidence needs explicit disposition')
        candidate[key] = copy.deepcopy(update)
        candidate[key]['review_token'] = request['token']
        candidate[key]['snapshot_digest'] = current['digest']
    for key, claim in candidate.items():
        if claim['status'] == 'supported':
            require(all(candidate[p]['status'] == 'supported' for p in definitions(state['config'])[key].get('depends_on', [])), 'Supported dependent requires supported premises')
    state['working_claims'] = candidate
    state['claim_dirty'] = sorted(set(state['claim_dirty']) - set(ids))
    for action_id in result.get('cleared_actions', []):
        action = next(a for a in state['config']['actions'] if a['id'] == action_id)
        require(ready(state, action), 'Cannot clear work with unsupported or stale required claims')
    require(not result.get('goal_complete') or not state['claim_dirty'], 'Claims remain unreviewed')


def work_finished(state, pending, result):
    if not enabled(state['config']):
        return
    require('claim_updates' not in result and 'skill_invocation' not in result, 'Worker cannot approve claims')
    added = strings(result.get('affected_claims', []), 'affected_claims')
    require(set(added) <= state['working_claims'].keys(), 'Unknown affected worker claim')
    if result['status'] != 'not_started':
        action = next(a for a in state['config']['actions'] if a['id'] == pending['action_id'])
        invalidate(state, set(action['affected_claims']) | set(added))
        state['last_work'] = {'token': pending['token'], 'action_id': pending['action_id'], 'result': copy.deepcopy(result)}


def _atomic_bytes(path, data):
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with tmp.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def observe_freshness(state, snapshotter):
    """Sample current identities without changing accepted state or pending tokens."""
    if not enabled(state['config']):
        return None
    observation = {'recorded_snapshot_digest': state['snapshot']['digest'],
                   'recorded_contract_digest': state['reviewer_contract']['digest'],
                   'scope': 'Identity sampled on this read; saved reports do not monitor later changes.'}
    try:
        current = snapshotter(state['config'])
        contract = reviewer_snapshot(state['config'])
        observation.update(observed_snapshot_digest=current['digest'], observed_contract_digest=contract['digest'],
                           evidence_current=current == state['snapshot'],
                           contract_current=contract == state['reviewer_contract'] and all(contract['files'].values()))
        observation['status'] = 'CURRENT' if observation['evidence_current'] and observation['contract_current'] else 'STALE'
    except (OSError, ContractError) as exc:
        observation.update(status='UNKNOWN', evidence_current=None, contract_current=None, error=str(exc))
    observation['review_required_claims'] = (list(state['claim_dirty']) if observation['status'] == 'CURRENT'
                                             else sorted(state['working_claims']))
    observation['completion_current'] = bool(state['complete'] and observation['status'] == 'CURRENT'
                                             and not observation['review_required_claims'])
    return observation


def materialize(state, root, freshness=None):
    """Rebuild disposable projections; commit pointer last, under controller lock."""
    if not enabled(state['config']):
        return
    projection = {k: state[k] for k in ('working_claims', 'claim_dirty', 'actions', 'control', 'complete', 'config_digest')}
    if freshness is None:
        freshness = {'status': 'UNKNOWN', 'review_required_claims': sorted(state['working_claims']),
                     'completion_current': False, 'scope': 'No current identity check supplied.'}
    projection['freshness'] = freshness
    projection['claim_definitions'] = definitions(state['config'])
    projection['authority'] = 'Working orchestration state; formal component-map and audit acceptance remain separate.'
    revision = digest(projection)
    folder = root / 'reports' / revision
    for path in (root / 'reports', folder):
        require(not is_link_or_reparse(path), 'Report directory may not cross links')
        path.mkdir(exist_ok=True)
    payloads = {'claims.json': (json.dumps(projection, indent=2, ensure_ascii=False) + '\n').encode('utf-8')}
    claims = definitions(state['config'])
    for report in state['config']['subagent_mode']['reports']:
        lines = ['# ' + report['title'], '', projection['authority'], '', 'Projection revision: `' + revision + '`', '', 'Observed source currency: ' + freshness['status'],
                 freshness['scope'], '', 'Recorded completion: ' + str(state['complete']) +
                 '; completion current at this read: ' + str(freshness['completion_current']), '']
        for key in report['claim_ids']:
            current = state['working_claims'][key]
            fresh = 'REVIEW REQUIRED (last assessed status follows)' if key in freshness['review_required_claims'] else 'Reviewed at sampled identities'
            lines += ['## ' + key, '', claims[key]['statement'], '', 'Scope: ' + claims[key]['scope'], '', 'Depends on: ' + (', '.join(claims[key].get('depends_on', [])) or 'None'), '',
                      'Freshness: ' + fresh, '', 'Status: ' + current['status'], '', current['rationale'], '',
                      'Limitations: ' + ('; '.join(current['limitations']) or 'None declared within the stated scope'), '']
            for link in current['evidence']:
                lines += [f"- {link['relation']}: `{link['path']}` ({link['locator']}); {link['method']}; SHA-256 `{link['sha256']}`"]
            lines += ['', 'Formal audit references: ' + ('; '.join(current['audit_refs']) or 'None linked; no formal acceptance implied'), '']
        payloads[report['id'] + '.md'] = '\n'.join(lines).encode('utf-8')
    hashes = {}
    for name, data in payloads.items():
        target = folder / name
        require(not target.is_symlink(), 'Report file may not be a link')
        if not target.exists() or target.read_bytes() != data:
            _atomic_bytes(target, data)
        require(target.read_bytes() == data, 'Report verification failed')
        hashes[name] = hashlib.sha256(data).hexdigest()
    pointer = {'revision': revision, 'directory': str(folder), 'files': hashes}
    target = root / 'reports' / 'current.json'
    require(not target.is_symlink(), 'Report pointer may not be a link')
    data = (json.dumps(pointer, indent=2) + '\n').encode('utf-8')
    if not target.exists() or target.read_bytes() != data:
        _atomic_bytes(target, data)
