"""Finite real subprocess/controller benchmark; synthetic reviews, NOT model validation.

Run: py -3 evaluation/agent-pool/benchmark.py --output <new-dir> --repeats 3
The coordinator executes the identical DAG with serialized or opt-in pool dispatch.
Persistent Python worker PIDs demonstrate real assignment reuse, not invented agents.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import queue
import threading
import statistics
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / 'skills' / 'analyze-project-claims' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from long_running_controller import Controller

DAG = {'a': [], 'b': [], 'c': [], 'd': ['a'], 'e': ['b'], 'f': ['d', 'e', 'c']}
CRITERION = 'Every task output equals frozen expected data and every completed unit is reviewed'
LIMITATION = 'Real Python subprocesses and controller operations; deterministic synthetic reviewer, no LLM invocation, semantic-review accuracy or general speed guarantee.'


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.partial')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True), encoding='utf-8')
    os.replace(temp, path)


def calculate(key, iterations, dependencies):
    password = ('pool-benchmark:' + key + ':' + ':'.join(dependencies)).encode()
    value = hashlib.pbkdf2_hmac('sha256', password, b'fixed-bounded-workload-v1', iterations).hex()
    return {'task': key, 'iterations': iterations, 'dependency_digests': dependencies, 'digest': value}


def worker(request):
    root = Path(request['config']['project_root'])
    protocol = json.loads((root / 'protocol.json').read_text())
    key = request['action_id']
    dependencies = [json.loads((root / (d + '.json')).read_text())['digest'] for d in DAG[key]]
    start = time.perf_counter_ns()
    cpu_start = time.process_time_ns()
    result = calculate(key, protocol['iterations'][key], dependencies)
    save(root / (key + '.json'), result)
    return {'status': 'done', 'evidence_refs': [key + '.json'],
            'benchmark_observation': {'pid': os.getpid(), 'started_ns': start, 'finished_ns': time.perf_counter_ns(), 'cpu_ns': time.process_time_ns() - cpu_start, 'task': key}}


def reviewer(request):
    root = Path(request['config']['project_root'])
    protocol = json.loads((root / 'protocol.json').read_text())
    updates = []
    statuses = {k: v['status'] for k, v in request['working_claims'].items()}
    for key in request['required_claim_updates']:
        name = 'protocol.json' if key == 'P' else key + '.json'
        sha = request['snapshot']['files'].get(name)
        supported = sha is not None
        if supported:
            payload = (root / name).read_bytes()
            if hashlib.sha256(payload).hexdigest() != sha:
                raise ValueError('Snapshot changed during deterministic review: ' + name)
            if key != 'P' and json.loads(payload) != protocol['expected'][key]:
                raise ValueError('Output differs from frozen expected result: ' + key)
        updates.append({'id': key, 'status': 'supported' if supported else 'untested',
            'evidence': ([{'path': name, 'sha256': sha, 'locator': 'complete JSON value',
                'method': 'source_inspection', 'relation': 'supports'}] if supported else []),
            'limitations': [] if supported else ['Task output has not been produced'],
            'rationale': 'Deterministic fixture check against frozen expected bytes; not a native model review', 'audit_refs': []})
        statuses[key] = updates[-1]['status']
    allowed = request.get('clearable_actions', list(request['actions']))
    cleared = [a['id'] for a in request['config']['actions'] if a['id'] in allowed
        and request['actions'][a['id']] == 'pending' and all(statuses[c] == 'supported' for c in a['required_claims'])]
    complete = all(v == 'done' for v in request['actions'].values()) and all(v == 'supported' for v in statuses.values())
    if request.get('review_scope') == 'unit':
        complete = False
    result = {'review_status': 'COMPLETE', 'decision': 'CONTINUE',
        'snapshot_digest': request['snapshot']['digest'], 'request_digest': request['semantic_digest'],
        'coverage': LIMITATION, 'cleared_actions': [] if complete else cleared,
        'next_action': None if complete or not cleared else cleared[0],
        'skill_invocation': {'skill': 'analyze-project-claims', 'contract_digest': request['reviewer_contract']['digest']},
        'claim_updates': updates, 'goal_complete': complete}
    if complete:
        result.update(verified_criteria=[CRITERION], evidence_refs=list(request['snapshot']['files']))
    return result


def server(role):
    print(json.dumps({'ready': True, 'pid': os.getpid(), 'role': role}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            answer = worker(request) if role == 'worker' else reviewer(request)
            print(json.dumps({'ok': True, 'result': answer}), flush=True)
        except Exception as exc:
            print(json.dumps({'ok': False, 'error': repr(exc)}), flush=True)


class Host:
    def __init__(self, role, directory, index, deadline):
        self.deadline = deadline
        self.log = (directory / ('host-' + role + '-' + str(index) + '.stderr')).open('w', encoding='utf-8')
        self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve', role],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.lines = queue.Queue()
        def read_lines():
            try:
                for line in self.process.stdout:
                    self.lines.put(line)
            finally:
                self.lines.put(None)
        threading.Thread(target=read_lines, daemon=True).start()
        try:
            ready = json.loads(self.read_line(10))
        except Exception:
            self.close()
            raise
        if not ready.get('ready'):
            raise RuntimeError('Host did not start')
        self.identity = 'local-' + role + '-pid-' + str(ready['pid'])
        self.used = False
        self.busy = False

    def read_line(self, limit=60):
        remaining = min(limit, self.deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError('Owned host deadline exhausted')
        try:
            line = self.lines.get(timeout=remaining)
        except queue.Empty as exc:
            raise TimeoutError('Owned host response deadline exhausted') from exc
        if line is None:
            raise RuntimeError('Owned host ended without a response')
        return line

    def execute(self, request):
        self.process.stdin.write(json.dumps(request) + '\n')
        self.process.stdin.flush()
        line = self.read_line()
        if not line:
            raise RuntimeError('Host ended without result')
        response = json.loads(line)
        if not response.get('ok'):
            raise RuntimeError(response.get('error'))
        return response['result']

    def close(self):
        try:
            self.process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.log.close()


def make_config(root, expected, iterations, pool, workers):
    root.mkdir(parents=True)
    save(root / 'protocol.json', {'expected': expected, 'iterations': iterations, 'dag': DAG, 'limitation': LIMITATION})
    (root / 'SKILL.md').write_text('Deterministic benchmark reviewer fixture. Does not invoke an LLM skill.\n')
    actions = []
    for key, dependencies in DAG.items():
        actions.append({'id': key, 'instruction': 'Compute frozen PBKDF2 task ' + key, 'depends_on': dependencies,
            'required_claims': ['P'] + dependencies, 'affected_claims': [key],
            'read_paths': ['protocol.json'] + [d + '.json' for d in dependencies], 'write_paths': [key + '.json']})
    config = {'goal_id': 'real-process-dag', 'goal_revision': '1', 'objective': CRITERION,
        'authorization_ref': 'finite local benchmark', 'project_root': str(root), 'success_criteria': [CRITERION],
        'evidence': ['protocol.json'] + [k + '.json' for k in DAG], 'actions': actions, 'max_dispatches': 80,
        'subagent_mode': {'authorization_ref': 'local deterministic fixture',
            'reviewer_sources': [str(root / 'SKILL.md'), str(Path(__file__).resolve())],
            'claims': [{'id': key, 'statement': 'Fixture ' + key + ' matches frozen protocol', 'scope': 'one bounded task', 'depends_on': [] if key == 'P' else ['P']} for key in ['P'] + list(DAG)],
            'reports': [{'id': 'summary', 'title': 'Benchmark fixture', 'claim_ids': ['P'] + list(DAG)}]}}
    if pool:
        config['agent_pool'] = {'max_workers': workers}
    else:
        config['scheduling_mode'] = 'serialized'
    return config


def run_trial(root, expected, iterations, pool, workers, timeout, frozen_hashes):
    config = make_config(root, expected, iterations, pool, workers)
    controller = Controller(root / 'state')
    controller.init(config)
    events, active, hosts = [], {}, []
    counter = 0
    controller_seconds = 0.0
    review_seconds = 0.0
    begin = time.perf_counter_ns()
    deadline = time.monotonic() + timeout
    executor = ThreadPoolExecutor(max_workers=workers)
    try:
        worker_hosts = []
        for i in range(workers):
            host = Host('worker', root, i, deadline)
            worker_hosts.append(host)
            hosts.append(host)
        review_host = Host('reviewer', root, 0, deadline)
        hosts.append(review_host)
        while time.monotonic() < deadline:
            progress = False
            for future, (request, host) in list(active.items()):
                if not future.done():
                    continue
                result = future.result()
                events.append({'event': 'worker_result', 'token': request['token'], 'at_ns': time.perf_counter_ns(), **result['benchmark_observation']})
                stamp = time.perf_counter()
                controller.finish(request['token'], result)
                controller_seconds += time.perf_counter() - stamp
                host.busy = False
                del active[future]
                progress = True
            counter += 1
            stamp = time.perf_counter()
            item = controller.next(dispatch_id='trial-intent-' + str(counter)) if pool else controller.next()
            controller_seconds += time.perf_counter() - stamp
            if item['status'] == 'COMPLETE':
                if active:
                    raise AssertionError('Completion while subprocess work remains')
                break
            if item['status'] == 'DISPATCH':
                request = item['request']
                role = request['role']
                host = review_host if role == 'claims_reviewer' else next((h for h in worker_hosts if not h.busy), None)
                if host is None:
                    raise AssertionError('Controller dispatched above worker capacity')
                observation = {'observed_at': time.time(), 'source_ref': str(root / 'events.json'),
                    'agent_id': host.identity, 'status': 'idle', 'execution_quiescent': True}
                if host.used:
                    events.append({'event': 'host_idle_observation', **observation, 'pid': host.process.pid, 'process_exit': host.process.poll()})
                    save(root / 'events.json', events)
                stamp = time.perf_counter()
                if pool:
                    controller.bind_agent(request['token'], host.identity, observation=observation if host.used else None)
                else:
                    controller.bind_agent(request['token'], host.identity)
                if controller.check(request['token'])['status'] != 'READY':
                    raise AssertionError('Bound task not ready')
                controller_seconds += time.perf_counter() - stamp
                events.append({'event': 'dispatch', 'role': role, 'task': request['action_id'], 'token': request['token'],
                    'host_id': host.identity, 'reused': host.used, 'at_ns': time.perf_counter_ns(),
                    'review_work_tokens': request.get('review_work_tokens', [])})
                host.used = True
                host.busy = True
                if role == 'claims_reviewer':
                    stamp = time.perf_counter()
                    result = host.execute(request)
                    review_seconds += time.perf_counter() - stamp
                    stamp = time.perf_counter()
                    disposition = controller.finish(request['token'], result)
                    controller_seconds += time.perf_counter() - stamp
                    reviewed_actions = [x['action_id'] for x in request.get('review_outcomes', [])]
                    if not reviewed_actions and request.get('last_work'):
                        reviewed_actions = [request['last_work']['action_id']]
                    events.append({'event': 'reviewer_result', 'at_ns': time.perf_counter_ns(), 'token': request['token'],
                        'host_id': host.identity, 'reviewed_actions': reviewed_actions, 'disposition': disposition['status']})
                    host.busy = False
                else:
                    active[executor.submit(host.execute, request)] = (request, host)
                progress = True
            elif item['status'] not in ('IN_FLIGHT', 'WAITING', 'POOL_FULL', 'POOL_BUSY', 'REVIEW_PENDING'):
                raise AssertionError('Unexpected controller stop: ' + json.dumps(item))
            if not progress:
                if not active:
                    raise AssertionError('No executable work or active process: ' + json.dumps(item))
                time.sleep(.002)  # Host event-poll backoff, never the measured task workload.
        else:
            raise TimeoutError('Finite benchmark deadline reached')
        elapsed = (time.perf_counter_ns() - begin) / 1e9
        state = controller.status()
        outputs = {key: json.loads((root / (key + '.json')).read_text()) for key in DAG}
        if outputs != expected or not state['complete'] or state['claim_dirty']:
            raise AssertionError('Acceptance or exact-output equality failed')
        intervals = [e for e in events if e['event'] == 'worker_result']
        overlap = any(a['started_ns'] < b['finished_ns'] and b['started_ns'] < a['finished_ns']
            for i, a in enumerate(intervals) for b in intervals[i + 1:])
        a_interval = next(e for e in intervals if e['task'] == 'a')
        refill = any(e['event'] == 'dispatch' and e['role'] == 'worker' and e['task'] != 'a' and e['reused']
            and a_interval['started_ns'] < e['at_ns'] < a_interval['finished_ns'] for e in events)
        reviewed_at = {}
        dependency_delays = {}
        for event in events:
            if event['event'] == 'reviewer_result' and event['disposition'] == 'RECORDED':
                for action_id in event['reviewed_actions']:
                    reviewed_at[action_id] = event['at_ns']
            if event['event'] == 'dispatch' and event['role'] == 'worker' and DAG[event['task']]:
                deps = DAG[event['task']]
                if not all(d in reviewed_at for d in deps):
                    raise AssertionError('Dependent dispatched before recorded prerequisite reviews')
                dependency_delays[event['task']] = (event['at_ns'] - max(reviewed_at[d] for d in deps)) / 1e9
        if source_hashes() != frozen_hashes:
            raise AssertionError('Benchmark/controller sources changed during timed trial')
        result = {'mode': 'pool' if pool else 'serialized', 'elapsed_seconds': elapsed,
            'controller_seconds': controller_seconds, 'review_process_seconds': review_seconds,
            'worker_cpu_seconds': sum(e['cpu_ns'] / 1e9 for e in intervals),
            'per_task_work_seconds': {e['task']: {'wall': (e['finished_ns'] - e['started_ns']) / 1e9, 'cpu': e['cpu_ns'] / 1e9} for e in intervals},
            'worker_cpu_work_wall_sum_seconds': sum((e['finished_ns'] - e['started_ns']) / 1e9 for e in intervals),
            'overlap_observed': overlap, 'reassignment_before_straggler_done': refill,
            'dependency_review_to_dispatch_seconds': dependency_delays, 'sources_unchanged': True,
            'worker_count': workers, 'worker_executions': len(intervals), 'unique_tasks': len({e['task'] for e in intervals}),
            'outputs_equal': outputs == expected, 'complete': state['complete'], 'claim_dirty': state['claim_dirty'],
            'output_digest': hashlib.sha256(json.dumps(outputs, sort_keys=True).encode()).hexdigest(), 'limitation': LIMITATION}
        if len(intervals) != len(DAG) or len({e['task'] for e in intervals}) != len(DAG):
            raise AssertionError('Duplicated or missing assignment')
        save(root / 'events.json', events)
        save(root / 'result.json', result)
        return result
    finally:
        for host in hosts:
            host.close()
        executor.shutdown(wait=True, cancel_futures=True)
        save(root / 'events.json', events)


def source_hashes():
    paths = [Path(__file__).resolve()] + [SCRIPTS / name for name in
        ('long_running_controller.py', 'subagent_mode.py', 'agent_pool.py', 'agent_cleanup.py')]
    return {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', choices=['worker', 'reviewer'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--iterations', type=int, default=2000000)
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args()
    if args.serve:
        server(args.serve)
        return
    if args.output is None or not 2 <= args.workers <= 3 or not 1 <= args.repeats <= 10 or not 1000 <= args.iterations <= 20000000:
        parser.error('Supply a new output directory, 2-3 workers, 1-10 repeats and 1000-20000000 iterations')
    if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 600:
        parser.error('timeout must be finite and between 1 and 600 seconds')
    args.output.mkdir(parents=True, exist_ok=False)
    iterations = {key: args.iterations * (4 if key == 'a' else 1) for key in DAG}
    expected = {}
    for key in DAG:
        expected[key] = calculate(key, iterations[key], [expected[d]['digest'] for d in DAG[key]])
    frozen_hashes = source_hashes()
    save(args.output / 'manifest.json', {'dag': DAG, 'iterations': iterations, 'expected': expected,
        'python': sys.version, 'platform': platform.platform(), 'cpu_count': os.cpu_count(),
        'permitted_workers': args.workers, 'repeats': args.repeats, 'limitation': LIMITATION,
        'timing_boundary': 'After controller init; includes subprocess startup, all dispatch/work/review/integration until controller COMPLETE; excludes expected-value setup and host shutdown.',
        'source_hashes': frozen_hashes})
    trials = []
    try:
        for index in range(args.repeats):
            for pool in ([False, True] if index % 2 == 0 else [True, False]):
                result = run_trial(args.output / ('trial-' + str(index) + ('-pool' if pool else '-serialized')),
                    expected, iterations, pool, args.workers, args.timeout, frozen_hashes)
                result['pair'] = index
                trials.append(result)
                print(json.dumps(result), flush=True)
        if source_hashes() != frozen_hashes:
            raise AssertionError('Benchmark/controller sources changed before summary')
        ratios = [next(t['elapsed_seconds'] for t in trials if t['pair'] == i and t['mode'] == 'serialized') /
                  next(t['elapsed_seconds'] for t in trials if t['pair'] == i and t['mode'] == 'pool') for i in range(args.repeats)]
        qualified = all(t['overlap_observed'] and t['reassignment_before_straggler_done'] for t in trials if t['mode'] == 'pool')
        acceleration = qualified and statistics.median(ratios) > 1.0
        summary = {'status': 'PASS', 'functional_status': 'PASS',
            'acceleration_evidence': 'OBSERVED_BOUNDED_WORKLOAD' if acceleration else 'INCONCLUSIVE',
            'statistical_limit': 'Paired descriptive measurements only; no significance or generalization claim.', 'trials': trials, 'paired_speed_ratios': ratios,
            'median_paired_speed_ratio': statistics.median(ratios), 'all_outputs_equal': len({t['output_digest'] for t in trials}) == 1,
            'pool_overlap_all_trials': all(t['overlap_observed'] for t in trials if t['mode'] == 'pool'),
            'pool_refill_all_trials': all(t['reassignment_before_straggler_done'] for t in trials if t['mode'] == 'pool'),
            'acceleration_observed': acceleration, 'limitation': LIMITATION}
        save(args.output / 'summary.json', summary)
    except BaseException as exc:
        save(args.output / 'summary.json', {'status': 'INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'FAILED', 'error': repr(exc), 'completed_trials': trials, 'limitation': LIMITATION})
        raise


if __name__ == '__main__':
    main()
